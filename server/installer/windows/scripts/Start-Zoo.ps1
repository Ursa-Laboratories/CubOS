param(
    [string]$InstallDir = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version 2.0

$UserRoot = Join-Path ([Environment]::GetFolderPath("LocalApplicationData")) "UrsaLabs\Zoo"
$LogDir = Join-Path $UserRoot "logs"
$DataDir = Join-Path $UserRoot "data"
$DataDbPath = Join-Path $DataDir "panda_data.db"
$Timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$LogPath = Join-Path $LogDir "zoo-launch-$Timestamp.log"

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
New-Item -ItemType Directory -Force -Path $DataDir | Out-Null

function Write-Log {
    param([string]$Message)

    $Line = "$(Get-Date -Format o) $Message"
    $Line | Tee-Object -FilePath $LogPath -Append
}

function Show-Failure {
    param([string]$Message)

    Write-Host ""
    Write-Host "Zoo failed to start." -ForegroundColor Red
    Write-Host $Message -ForegroundColor Red
    Write-Host "Log written to: $LogPath"
    Read-Host "Press Enter to close"
}

$Python = Join-Path $InstallDir "Python\python.exe"
$RuntimePython = Join-Path $InstallDir "venv\Scripts\python.exe"
$PythonInstaller = Join-Path $InstallDir "installers\python-installer.exe"
$InstallPythonScript = Join-Path $InstallDir "scripts\Install-Python.ps1"
$InstallRuntimeScript = Join-Path $InstallDir "scripts\Install-Runtime.ps1"
$RuntimeMarker = Join-Path $InstallDir "runtime-installed.txt"
$DriverGroupsFile = Join-Path $InstallDir "driver-groups.txt"
$ZooDir = Join-Path $InstallDir "app\Zoo"
$ZooSeedConfigDir = Join-Path $ZooDir "configs"
$ConfigDir = if ($env:ZOO_CONFIG_DIR) { $env:ZOO_CONFIG_DIR } else { Join-Path $UserRoot "configs" }

function Invoke-LauncherScript {
    param(
        [string]$ScriptPath,
        [string[]]$Arguments
    )

    if (-not (Test-Path $ScriptPath)) {
        throw "Required installer script not found at $ScriptPath"
    }

    Write-Log "> powershell.exe -NoProfile -ExecutionPolicy Bypass -File $ScriptPath $($Arguments -join ' ')"
    $PreviousErrorActionPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $ScriptPath @Arguments 2>&1 | ForEach-Object { $_.ToString() } | Tee-Object -FilePath $LogPath -Append
    }
    finally {
        $ErrorActionPreference = $PreviousErrorActionPreference
    }
    if ($LASTEXITCODE -ne 0) {
        throw "$ScriptPath failed with exit code $LASTEXITCODE"
    }
}

function Get-InstalledDriverGroups {
    if (Test-Path $DriverGroupsFile) {
        $FileValue = Get-Content -Path $DriverGroupsFile -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($FileValue -and $FileValue.Trim()) {
            return $FileValue.Trim()
        }
    }

    if (-not (Test-Path $RuntimeMarker)) {
        return ""
    }

    $DriverLine = Get-Content -Path $RuntimeMarker -ErrorAction SilentlyContinue |
        Where-Object { $_ -like "DriverGroups=*" } |
        Select-Object -First 1
    if (-not $DriverLine) {
        return ""
    }

    $Value = $DriverLine.Substring("DriverGroups=".Length)
    if ($Value -eq "none") {
        return ""
    }
    return $Value
}

try {
    Write-Log "Starting Zoo launcher"
    Write-Log "Install directory: $InstallDir"
    Write-Log "Expected Python: $Python"
    Write-Log "Expected runtime Python: $RuntimePython"
    Write-Log "Zoo source directory: $ZooDir"
    Write-Log "Config directory: $ConfigDir"
    Write-Log "Data database path: $DataDbPath"

    $NeedsRuntimeInstall = (-not (Test-Path $RuntimeMarker)) -or (-not (Test-Path $RuntimePython))

    if (-not (Test-Path $Python)) {
        Write-Log "Python runtime missing; installing from bundled installer"
        Invoke-LauncherScript $InstallPythonScript @("-InstallDir", $InstallDir, "-PythonInstaller", $PythonInstaller)
        $NeedsRuntimeInstall = $true
    }

    if (-not (Test-Path $ZooDir)) {
        throw "Zoo source directory not found at $ZooDir"
    }

    if ($NeedsRuntimeInstall) {
        Write-Log "Zoo runtime packages need installation"
        $InstalledDriverGroups = Get-InstalledDriverGroups
        Invoke-LauncherScript $InstallRuntimeScript @("-InstallDir", $InstallDir, "-DriverGroups", $InstalledDriverGroups)
    }

    $FrontendDist = Join-Path $ZooDir "frontend\dist"
    if (-not (Test-Path $FrontendDist)) {
        throw "Zoo frontend build not found at $FrontendDist. Rebuild the installer so Node.js is not needed on the operator machine."
    }

    New-Item -ItemType Directory -Force -Path $ConfigDir | Out-Null

    $ExistingConfig = Get-ChildItem -Path $ConfigDir -Recurse -Filter "*.yaml" -ErrorAction SilentlyContinue | Select-Object -First 1
    if (-not $ExistingConfig -and (Test-Path $ZooSeedConfigDir)) {
        $GantryConfigDir = Join-Path $ConfigDir "gantry"
        $DeckConfigDir = Join-Path $ConfigDir "deck"
        New-Item -ItemType Directory -Force -Path $GantryConfigDir | Out-Null
        New-Item -ItemType Directory -Force -Path $DeckConfigDir | Out-Null
        Write-Log "Seeding config directory with generic templates from $ZooSeedConfigDir"
        Copy-Item -Path (Join-Path $ZooSeedConfigDir "gantry\cub_seed.yaml") -Destination $GantryConfigDir -Force
        Copy-Item -Path (Join-Path $ZooSeedConfigDir "gantry\cub_xl_seed.yaml") -Destination $GantryConfigDir -Force
        Copy-Item -Path (Join-Path $ZooSeedConfigDir "deck\cub_deck_example.yaml") -Destination $DeckConfigDir -Force
        Copy-Item -Path (Join-Path $ZooSeedConfigDir "deck\cubxl_deck_example.yaml") -Destination $DeckConfigDir -Force
    }

    $env:ZOO_CONFIG_DIR = $ConfigDir
    $env:CUBOS_DATA_DB_PATH = $DataDbPath
    $env:ZOO_HOST = "127.0.0.1"
    $env:ZOO_PORT = "8742"
    $env:ZOO_OPEN_BROWSER = "true"
    $env:PYTHONUTF8 = "1"

    Write-Log "Launching Zoo at http://127.0.0.1:8742"

    Push-Location $ZooDir
    try {
        $PreviousErrorActionPreference = $ErrorActionPreference
        $ErrorActionPreference = "Continue"
        try {
            & $RuntimePython -m zoo 2>&1 | ForEach-Object { $_.ToString() } | Tee-Object -FilePath $LogPath -Append
            $ExitCode = $LASTEXITCODE
        }
        finally {
            $ErrorActionPreference = $PreviousErrorActionPreference
        }
    }
    finally {
        Pop-Location
    }

    if ($ExitCode -ne 0) {
        throw "python -m zoo exited with code $ExitCode"
    }

    exit 0
}
catch {
    $Message = $_.Exception.Message
    Write-Log "ERROR: $Message"
    if ($_.ScriptStackTrace) {
        Write-Log $_.ScriptStackTrace
    }
    Show-Failure $Message
    exit 1
}
