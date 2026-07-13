param(
    [string]$InstallDir = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path,
    [string[]]$DriverGroups = @()
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version 2.0

$UserRoot = Join-Path ([Environment]::GetFolderPath("LocalApplicationData")) "UrsaLabs\Zoo"
$LogDir = Join-Path $UserRoot "logs"
$Timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$LogPath = Join-Path $LogDir "zoo-install-runtime-$Timestamp.log"

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

# Progress state shared across the step/heartbeat helpers below. The runtime
# install is a long, mostly-silent sequence of pip commands, so we surface an
# explicit "[step/total]" banner per phase plus a periodic heartbeat while a
# command is still running. Everything is emitted as pipeline output (via
# Tee-Object) rather than Write-Host so it survives being piped through
# Start-Zoo.ps1's Tee-Object into the launch log and the operator's console.
$script:ProgressActivity = "Installing Zoo and CubOS runtime packages"
$script:StepIndex = 0
$script:TotalSteps = 0

function Write-Log {
    param([string]$Message)

    $Line = "$(Get-Date -Format o) $Message"
    $Line | Tee-Object -FilePath $LogPath -Append
}

function Set-TotalSteps {
    param([int]$Count)

    $script:TotalSteps = $Count
}

function Get-StepPercent {
    if ($script:TotalSteps -le 0) {
        return 0
    }
    $Percent = [int](100 * ($script:StepIndex - 1) / $script:TotalSteps)
    if ($Percent -lt 0) {
        return 0
    }
    if ($Percent -gt 100) {
        return 100
    }
    return $Percent
}

function Start-Step {
    param([string]$Title)

    $script:StepIndex++
    $Label = "[$($script:StepIndex)/$($script:TotalSteps)] $Title"
    "" | Tee-Object -FilePath $LogPath -Append
    Write-Log "==> $Label"
    Write-Progress -Activity $script:ProgressActivity -Status $Label -PercentComplete (Get-StepPercent)
}

function Invoke-LoggedNative {
    param(
        [string]$FilePath,
        [string[]]$Arguments,
        [string]$Activity = ""
    )

    Write-Log "> $FilePath $($Arguments -join ' ')"

    $Label = if ($Activity) { $Activity } else { "working" }

    # Pre-quote arguments so paths containing spaces (e.g. a wheelhouse under a
    # user profile with a space in the name) survive Start-Process.
    $QuotedArgs = @(
        foreach ($Arg in $Arguments) {
            if ($Arg -match '[\s"]') { '"' + ($Arg -replace '"', '\"') + '"' } else { $Arg }
        }
    )

    $OutFile = [System.IO.Path]::GetTempFileName()
    $ErrFile = [System.IO.Path]::GetTempFileName()
    $StartTime = Get-Date
    $LastBeat = Get-Date
    $SeenOut = 0
    $SeenErr = 0
    $ExitCode = 0

    try {
        $StartArgs = @{
            FilePath               = $FilePath
            NoNewWindow            = $true
            PassThru               = $true
            RedirectStandardOutput = $OutFile
            RedirectStandardError  = $ErrFile
        }
        if ($QuotedArgs.Count -gt 0) {
            $StartArgs['ArgumentList'] = $QuotedArgs
        }

        $Process = Start-Process @StartArgs

        while (-not $Process.HasExited) {
            Start-Sleep -Milliseconds 1000
            $Printed = $false

            # Emit newly completed output lines. Hold back the last line while
            # the process runs because it may still be partially written.
            $OutLines = @(Get-Content -LiteralPath $OutFile -ErrorAction SilentlyContinue)
            while ($SeenOut -lt ($OutLines.Count - 1)) {
                $OutLines[$SeenOut] | Tee-Object -FilePath $LogPath -Append
                $SeenOut++
                $Printed = $true
            }

            $ErrLines = @(Get-Content -LiteralPath $ErrFile -ErrorAction SilentlyContinue)
            while ($SeenErr -lt ($ErrLines.Count - 1)) {
                $ErrLines[$SeenErr] | Tee-Object -FilePath $LogPath -Append
                $SeenErr++
                $Printed = $true
            }

            $Now = Get-Date
            if ($Printed) {
                $LastBeat = $Now
            }
            elseif (($Now - $LastBeat).TotalSeconds -ge 5) {
                $Elapsed = [int]($Now - $StartTime).TotalSeconds
                "    ...still $Label (${Elapsed}s elapsed)" | Tee-Object -FilePath $LogPath -Append
                $LastBeat = $Now
                Write-Progress -Activity $script:ProgressActivity -Status "$Label (${Elapsed}s)" -PercentComplete (Get-StepPercent)
            }
        }

        $Process.WaitForExit()
        $ExitCode = $Process.ExitCode

        # Flush any trailing output, including a final line without a newline.
        $OutLines = @(Get-Content -LiteralPath $OutFile -ErrorAction SilentlyContinue)
        while ($SeenOut -lt $OutLines.Count) {
            $OutLines[$SeenOut] | Tee-Object -FilePath $LogPath -Append
            $SeenOut++
        }
        $ErrLines = @(Get-Content -LiteralPath $ErrFile -ErrorAction SilentlyContinue)
        while ($SeenErr -lt $ErrLines.Count) {
            $ErrLines[$SeenErr] | Tee-Object -FilePath $LogPath -Append
            $SeenErr++
        }

        if ($ExitCode -eq 0) {
            $Total = [int]((Get-Date) - $StartTime).TotalSeconds
            "    done ${Label} (${Total}s)" | Tee-Object -FilePath $LogPath -Append
        }
    }
    finally {
        Remove-Item -LiteralPath $OutFile, $ErrFile -Force -ErrorAction SilentlyContinue
    }

    if ($ExitCode -ne 0) {
        throw "$FilePath $($Arguments -join ' ') failed with exit code $ExitCode"
    }
}

$Python = Join-Path $InstallDir "Python\python.exe"
$VenvDir = Join-Path $InstallDir "venv"
$VenvPython = Join-Path $VenvDir "Scripts\python.exe"
$Wheelhouse = Join-Path $InstallDir "wheelhouse"
$Requirements = Join-Path $InstallDir "requirements\runtime-requirements.txt"
$DriverRequirementsDir = Join-Path $InstallDir "requirements\drivers"
$Marker = Join-Path $InstallDir "runtime-installed.txt"
$DriverGroupsFile = Join-Path $InstallDir "driver-groups.txt"
$DriverGroupsExplicitlyProvided = @($DriverGroups | Where-Object { $_ -and $_.Trim() }).Count -gt 0
$SelectedDriverGroups = @(
    $DriverGroups |
        ForEach-Object { $_ -split "," } |
        Where-Object { $_ -and $_.Trim() } |
        ForEach-Object { $_.Trim().ToLowerInvariant() } |
        Where-Object { $_ -ne 'none' } |
        Select-Object -Unique
)

try {
    Write-Log "Installing Zoo runtime"
    Write-Log "Install directory: $InstallDir"
    Write-Log "Expected Python: $Python"
    Write-Log "Runtime virtual environment: $VenvDir"
    Write-Log "Wheelhouse: $Wheelhouse"
    Write-Log "Requirements: $Requirements"
    Write-Log "Selected public driver groups: $(if ($SelectedDriverGroups.Count) { $SelectedDriverGroups -join ', ' } else { 'none' })"

    if ($DriverGroupsExplicitlyProvided) {
        Set-Content -Path $DriverGroupsFile -Value ($SelectedDriverGroups -join ",") -Encoding UTF8
        Write-Log "Persisted selected driver groups to $DriverGroupsFile"
    }

    if (-not (Test-Path $Python)) {
        throw "Python runtime not found at $Python"
    }

    if (-not (Test-Path $Wheelhouse)) {
        throw "Wheelhouse not found at $Wheelhouse"
    }

    if (-not (Test-Path $Requirements)) {
        throw "Runtime requirements file not found at $Requirements"
    }

    # Steps: virtual environment + core dependencies + one per driver group +
    # Zoo/CubOS + verification. Keeping the total in sync with the Start-Step
    # calls below is what makes the "[step/total]" banner and progress bar
    # meaningful to the operator.
    Set-TotalSteps (4 + $SelectedDriverGroups.Count)

    Start-Step "Preparing Python virtual environment"
    if (-not (Test-Path $VenvPython)) {
        Invoke-LoggedNative $Python @("-m", "venv", $VenvDir)
    }
    else {
        Write-Log "Virtual environment already present at $VenvDir"
    }

    if (-not (Test-Path $VenvPython)) {
        throw "Virtual environment creation completed but python.exe was not found at $VenvPython"
    }

    Start-Step "Installing core runtime dependencies"
    Invoke-LoggedNative $VenvPython @("-m", "pip", "install", "--no-index", "--find-links", $Wheelhouse, "-r", $Requirements) -Activity "installing core runtime dependencies"

    foreach ($DriverGroup in $SelectedDriverGroups) {
        Start-Step "Installing hardware driver support: $DriverGroup"
        $DriverRequirements = Join-Path $DriverRequirementsDir "$DriverGroup.txt"
        if (-not (Test-Path $DriverRequirements)) {
            throw "No public driver requirements file found for '$DriverGroup' at $DriverRequirements"
        }
        Invoke-LoggedNative $VenvPython @("-m", "pip", "install", "--no-index", "--find-links", $Wheelhouse, "-r", $DriverRequirements) -Activity "installing driver group '$DriverGroup'"
    }

    Start-Step "Installing Zoo and CubOS"
    Invoke-LoggedNative $VenvPython @("-m", "pip", "install", "--no-index", "--find-links", $Wheelhouse, "--no-deps", "--force-reinstall", "cubos", "zoo") -Activity "installing Zoo and CubOS"

    Start-Step "Verifying installation"
    Invoke-LoggedNative $VenvPython @("-m", "pip", "check") -Activity "checking installed dependencies"
    Invoke-LoggedNative $VenvPython @("-c", "import zoo, gantry, deck, protocol_engine; print('Zoo runtime import check passed')") -Activity "verifying Zoo and CubOS imports"

    Write-Progress -Activity $script:ProgressActivity -Completed

    @(
        "Installed $(Get-Date -Format o)",
        "Python=$VenvPython",
        "DriverGroups=$(if ($SelectedDriverGroups.Count) { $SelectedDriverGroups -join ',' } else { 'none' })"
    ) | Set-Content -Path $Marker -Encoding UTF8
    Write-Log "Runtime install complete"
    exit 0
}
catch {
    Write-Progress -Activity $script:ProgressActivity -Completed
    Write-Log "ERROR: $($_.Exception.Message)"
    if ($_.ScriptStackTrace) {
        Write-Log $_.ScriptStackTrace
    }
    exit 1
}
