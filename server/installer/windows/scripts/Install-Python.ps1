param(
    [string]$InstallDir = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path,
    [string]$PythonInstaller = (Join-Path $InstallDir "installers\python-installer.exe")
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version 2.0

$UserRoot = Join-Path ([Environment]::GetFolderPath("LocalApplicationData")) "UrsaLabs\Zoo"
$LogDir = Join-Path $UserRoot "logs"
$Timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$LogPath = Join-Path $LogDir "zoo-install-python-$Timestamp.log"
$Python = Join-Path $InstallDir "Python\python.exe"

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

function Write-Log {
    param([string]$Message)

    $Line = "$(Get-Date -Format o) $Message"
    $Line | Tee-Object -FilePath $LogPath -Append
}

function Invoke-LoggedNative {
    param(
        [string]$FilePath,
        [string[]]$Arguments
    )

    Write-Log "> $FilePath $($Arguments -join ' ')"
    $PreviousErrorActionPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        & $FilePath @Arguments 2>&1 | Tee-Object -FilePath $LogPath -Append
    }
    finally {
        $ErrorActionPreference = $PreviousErrorActionPreference
    }
    if ($LASTEXITCODE -ne 0) {
        throw "$FilePath $($Arguments -join ' ') failed with exit code $LASTEXITCODE"
    }
}

try {
    Write-Log "Installing private Python runtime"
    Write-Log "Install directory: $InstallDir"
    Write-Log "Python installer: $PythonInstaller"
    Write-Log "Expected Python: $Python"

    if (Test-Path $Python) {
        Write-Log "Python runtime already present"
        exit 0
    }

    if (-not (Test-Path $PythonInstaller)) {
        throw "Bundled Python installer not found at $PythonInstaller"
    }

    New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null
    Invoke-LoggedNative $PythonInstaller @(
        "/quiet",
        "InstallAllUsers=0",
        "TargetDir=$InstallDir\Python",
        "Include_launcher=0",
        "PrependPath=0",
        "Include_test=0",
        "Include_doc=0",
        "Include_tcltk=1",
        "Include_pip=1",
        "SimpleInstall=1"
    )

    if (-not (Test-Path $Python)) {
        throw "Python installer completed but python.exe was not found at $Python"
    }

    Invoke-LoggedNative $Python @("--version")
    Write-Log "Private Python runtime install complete"
    exit 0
}
catch {
    Write-Log "ERROR: $($_.Exception.Message)"
    if ($_.ScriptStackTrace) {
        Write-Log $_.ScriptStackTrace
    }
    exit 1
}
