param(
    [string]$ZooRepoUrl = "https://github.com/Ursa-Laboratories/Zoo.git",
    [string]$CubOSRepoUrl = "https://github.com/Ursa-Laboratories/CubOS.git",
    [string]$Branch = "main",
    [string]$ZooSourceDir = "",
    [string]$PythonVersion = "3.11.9",
    [string]$AppVersion = "0.1.0",
    [string]$BuildPythonPath = "",
    [string]$BuildRoot = (Join-Path $PSScriptRoot "build"),
    [string]$InnoCompiler = ""
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version 2.0

function Invoke-Checked {
    param(
        [string]$FilePath,
        [string[]]$Arguments,
        [string]$WorkingDirectory = (Get-Location).Path
    )

    & $FilePath @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "$FilePath $($Arguments -join ' ') failed with exit code $LASTEXITCODE"
    }
}

function Invoke-RobocopyChecked {
    param(
        [string]$Source,
        [string]$Destination
    )

    New-Item -ItemType Directory -Force -Path $Destination | Out-Null
    & robocopy $Source $Destination /E /NFL /NDL /NJH /NJS /NC /NS /XD .git .venv venv node_modules .pytest_cache .omx build /XF *.pyc
    if ($LASTEXITCODE -gt 7) {
        throw "robocopy from $Source to $Destination failed with exit code $LASTEXITCODE"
    }
}

function Resolve-BuildPython {
    param([string]$ExplicitPath)

    if ($ExplicitPath) {
        if (-not (Test-Path $ExplicitPath)) {
            throw "Build Python not found at $ExplicitPath"
        }
        return [pscustomobject]@{
            Path = (Resolve-Path -Path $ExplicitPath).Path
            Args = @()
        }
    }

    $py = Get-Command py -ErrorAction SilentlyContinue
    if ($py) {
        return [pscustomobject]@{
            Path = $py.Source
            Args = @("-3.11")
        }
    }

    $python = Get-Command python -ErrorAction SilentlyContinue
    if ($python) {
        return [pscustomobject]@{
            Path = $python.Source
            Args = @()
        }
    }

    throw "No build Python found. Install Python 3.11 on the packaging machine."
}

function Resolve-InnoCompiler {
    param([string]$ExplicitPath)

    if ($ExplicitPath) {
        if (-not (Test-Path $ExplicitPath)) {
            throw "Inno Setup compiler not found at $ExplicitPath"
        }
        return $ExplicitPath
    }

    $cmd = Get-Command ISCC.exe -ErrorAction SilentlyContinue
    if ($cmd) {
        return $cmd.Source
    }

    $candidates = @(
        (Join-Path ${env:ProgramFiles(x86)} "Inno Setup 6\ISCC.exe"),
        (Join-Path $env:ProgramFiles "Inno Setup 6\ISCC.exe")
    )

    foreach ($candidate in $candidates) {
        if ($candidate -and (Test-Path $candidate)) {
            return $candidate
        }
    }

    throw "Inno Setup 6 compiler was not found. Install Inno Setup or pass -InnoCompiler."
}

New-Item -ItemType Directory -Force -Path $BuildRoot | Out-Null
$BuildRoot = (Resolve-Path -Path $BuildRoot).Path
$Work = Join-Path $BuildRoot "work"
$Stage = Join-Path $BuildRoot "stage"
$Dist = Join-Path $BuildRoot "dist"
$Downloads = Join-Path $BuildRoot "downloads"
$ZooClone = Join-Path $Work "Zoo"
$CubOSClone = Join-Path $Work "CubOS"
$Wheelhouse = Join-Path $Stage "wheelhouse"
$RequirementsDir = Join-Path $Stage "requirements"
$PythonInstaller = Join-Path $Stage "python-installer.exe"
$RuntimeRequirements = Join-Path $PSScriptRoot "runtime-requirements.txt"
$DriverRequirementsDir = Join-Path $PSScriptRoot "requirements\drivers"

Remove-Item -Path $Work, $Stage -Recurse -Force -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force -Path $Work, $Stage, $Dist, $Downloads, $Wheelhouse, $RequirementsDir | Out-Null

Invoke-Checked git @("clone", "--depth", "1", "--branch", $Branch, $CubOSRepoUrl, $CubOSClone)

if ($ZooSourceDir) {
    $ZooSource = (Resolve-Path -Path $ZooSourceDir).Path
}
else {
    Invoke-Checked git @("clone", "--depth", "1", "--branch", $Branch, $ZooRepoUrl, $ZooClone)
    $ZooSource = $ZooClone
}

$ZooCommit = (& git -C $ZooSource rev-parse HEAD).Trim()
$CubOSCommit = (& git -C $CubOSClone rev-parse HEAD).Trim()
$ZooBranch = (& git -C $ZooSource rev-parse --abbrev-ref HEAD).Trim()
$CubOSBranch = (& git -C $CubOSClone rev-parse --abbrev-ref HEAD).Trim()

if (-not $ZooSourceDir -and $ZooBranch -ne $Branch) {
    throw "Zoo clone is on $ZooBranch, expected $Branch"
}
if ($CubOSBranch -ne $Branch) {
    throw "CubOS clone is on $CubOSBranch, expected $Branch"
}

Push-Location (Join-Path $ZooSource "frontend")
try {
    Invoke-Checked npm @("ci")
    Invoke-Checked npm @("run", "build")
}
finally {
    Pop-Location
}

$BuildPython = Resolve-BuildPython $BuildPythonPath
$PythonExe = $BuildPython.Path
$PythonPrefixArgs = [string[]]$BuildPython.Args

Invoke-Checked $PythonExe ($PythonPrefixArgs + @("-m", "pip", "install", "--upgrade", "pip", "build", "wheel"))
Invoke-Checked $PythonExe ($PythonPrefixArgs + @("-m", "pip", "download", "--only-binary", ":all:", "--dest", $Wheelhouse, "-r", $RuntimeRequirements))
foreach ($DriverRequirements in Get-ChildItem -Path $DriverRequirementsDir -Filter "*.txt") {
    Invoke-Checked $PythonExe ($PythonPrefixArgs + @("-m", "pip", "download", "--only-binary", ":all:", "--dest", $Wheelhouse, "-r", $DriverRequirements.FullName))
}
Invoke-Checked $PythonExe ($PythonPrefixArgs + @("-m", "pip", "wheel", "--no-deps", "--wheel-dir", $Wheelhouse, $CubOSClone))
Invoke-Checked $PythonExe ($PythonPrefixArgs + @("-m", "pip", "wheel", "--no-deps", "--wheel-dir", $Wheelhouse, $ZooSource))

Invoke-RobocopyChecked $ZooSource (Join-Path $Stage "app\Zoo")
Invoke-RobocopyChecked $CubOSClone (Join-Path $Stage "app\CubOS")
Invoke-RobocopyChecked (Join-Path $PSScriptRoot "scripts") (Join-Path $Stage "scripts")
Copy-Item $RuntimeRequirements (Join-Path $RequirementsDir "runtime-requirements.txt") -Force
Copy-Item (Join-Path $PSScriptRoot "requirements\*") $RequirementsDir -Recurse -Force

$PythonUrl = "https://www.python.org/ftp/python/$PythonVersion/python-$PythonVersion-amd64.exe"
$DownloadedPython = Join-Path $Downloads "python-$PythonVersion-amd64.exe"
if (-not (Test-Path $DownloadedPython)) {
    Invoke-WebRequest -Uri $PythonUrl -OutFile $DownloadedPython
}
Copy-Item $DownloadedPython $PythonInstaller -Force
$PythonInstallerInfo = Get-Item -Path $PythonInstaller -ErrorAction SilentlyContinue
if (-not $PythonInstallerInfo -or $PythonInstallerInfo.Length -eq 0) {
    throw "Python installer was not staged at $PythonInstaller"
}

$BuildInfo = [ordered]@{
    generated_at = (Get-Date -Format o)
    zoo_repo = $ZooRepoUrl
    zoo_branch = $ZooBranch
    zoo_commit = $ZooCommit
    cubos_repo = $CubOSRepoUrl
    cubos_branch = $CubOSBranch
    cubos_commit = $CubOSCommit
    python_version = $PythonVersion
    app_version = $AppVersion
}
$BuildInfo | ConvertTo-Json -Depth 3 | Set-Content -Path (Join-Path $Stage "build-info.json") -Encoding UTF8

$Inno = Resolve-InnoCompiler $InnoCompiler
Invoke-Checked $Inno @(
    "/DSourceDir=$Stage",
    "/DOutputDir=$Dist",
    "/DAppVersion=$AppVersion",
    (Join-Path $PSScriptRoot "Zoo.iss")
)

Write-Host "Zoo installer written to $Dist"
