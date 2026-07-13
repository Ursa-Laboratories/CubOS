param(
    [string]$InstallDir = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version 2.0

$Python = Join-Path $InstallDir "Python\python.exe"
$RuntimePython = Join-Path $InstallDir "venv\Scripts\python.exe"
$RuntimeMarker = Join-Path $InstallDir "runtime-installed.txt"
$UserRoot = Join-Path $env:LOCALAPPDATA "UrsaLabs\Zoo"
$ConfigDir = if ($env:ZOO_CONFIG_DIR) { $env:ZOO_CONFIG_DIR } else { Join-Path $UserRoot "configs" }
$LogDir = Join-Path $UserRoot "logs"
$Timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$WorkDir = Join-Path $env:TEMP "Zoo-Diagnostics-$Timestamp"
$OutputZip = Join-Path ([Environment]::GetFolderPath("Desktop")) "Zoo-Diagnostics-$Timestamp.zip"

if (Test-Path $WorkDir) {
    Remove-Item -Path $WorkDir -Recurse -Force
}
New-Item -ItemType Directory -Force -Path $WorkDir | Out-Null

$BuildInfo = Join-Path $InstallDir "build-info.json"
if (Test-Path $BuildInfo) {
    Copy-Item $BuildInfo (Join-Path $WorkDir "build-info.json")
}

if (Test-Path $ConfigDir) {
    Copy-Item $ConfigDir (Join-Path $WorkDir "configs") -Recurse -Force
}

if (Test-Path $LogDir) {
    Copy-Item $LogDir (Join-Path $WorkDir "logs") -Recurse -Force
}

$RuntimeReport = Join-Path $WorkDir "runtime.txt"
"Generated: $(Get-Date -Format o)" | Set-Content -Path $RuntimeReport -Encoding UTF8
"InstallDir: $InstallDir" | Add-Content -Path $RuntimeReport
"ConfigDir: $ConfigDir" | Add-Content -Path $RuntimeReport
"LogDir: $LogDir" | Add-Content -Path $RuntimeReport

if (Test-Path $RuntimeMarker) {
    "`nruntime-installed.txt" | Add-Content -Path $RuntimeReport
    Get-Content -Path $RuntimeMarker -ErrorAction SilentlyContinue | Add-Content -Path $RuntimeReport
}

$DiagnosticsPython = $RuntimePython
if (-not (Test-Path $RuntimePython)) {
    "`nRuntime virtual environment python not found at $RuntimePython; falling back to $Python" | Add-Content -Path $RuntimeReport
    $DiagnosticsPython = $Python
}

if (Test-Path $DiagnosticsPython) {
    "`npython --version" | Add-Content -Path $RuntimeReport
    (& $DiagnosticsPython --version 2>&1) | Add-Content -Path $RuntimeReport
    "`npip freeze" | Add-Content -Path $RuntimeReport
    (& $DiagnosticsPython -m pip freeze 2>&1) | Add-Content -Path $RuntimeReport
    "`nimport check" | Add-Content -Path $RuntimeReport
    (& $DiagnosticsPython -c "import sys, zoo, gantry, deck, protocol_engine; print(sys.executable); print(zoo.__file__); print(gantry.__file__)" 2>&1) | Add-Content -Path $RuntimeReport
}
else {
    "Python runtime not found at $DiagnosticsPython" | Add-Content -Path $RuntimeReport
}

if (Test-Path $OutputZip) {
    Remove-Item $OutputZip -Force
}
Compress-Archive -Path (Join-Path $WorkDir "*") -DestinationPath $OutputZip -Force
Remove-Item -Path $WorkDir -Recurse -Force

Write-Host "Diagnostics exported to $OutputZip"
Read-Host "Press Enter to close"
