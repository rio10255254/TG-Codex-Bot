$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

function Get-PythonLaunchSpec {
    $specs = @()

    if ($env:TELEGRAM_BRIDGE_PYTHON) {
        $specs += [pscustomobject]@{
            FilePath = $env:TELEGRAM_BRIDGE_PYTHON
            Arguments = @('.\bot.py')
        }
    }

    $venvPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
    if (Test-Path $venvPython) {
        $specs += [pscustomobject]@{
            FilePath = $venvPython
            Arguments = @('.\bot.py')
        }
    }

    $pythonCmd = Get-Command python -ErrorAction SilentlyContinue
    if ($pythonCmd -and $pythonCmd.Source) {
        $specs += [pscustomobject]@{
            FilePath = $pythonCmd.Source
            Arguments = @('.\bot.py')
        }
    }

    $pyLauncher = Get-Command py -ErrorAction SilentlyContinue
    if ($pyLauncher -and $pyLauncher.Source) {
        $specs += [pscustomobject]@{
            FilePath = $pyLauncher.Source
            Arguments = @('-3', '.\bot.py')
        }
    }

    foreach ($spec in $specs) {
        if (-not [string]::IsNullOrWhiteSpace($spec.FilePath)) {
            return $spec
        }
    }

    throw "Could not locate a usable Python runtime. Install Python or set TELEGRAM_BRIDGE_PYTHON."
}

$restartDelaySeconds = 6
$dataDir = Join-Path $PSScriptRoot "data"
if (!(Test-Path $dataDir)) {
    New-Item -ItemType Directory -Path $dataDir | Out-Null
}
$lockPath = Join-Path $dataDir "bot.supervisor.lock"
$manualStopPath = Join-Path $dataDir "bot.manual_stop"

try {
    $lockStream = [System.IO.File]::Open($lockPath, [System.IO.FileMode]::OpenOrCreate, [System.IO.FileAccess]::ReadWrite, [System.IO.FileShare]::None)
} catch {
    Write-Output "Telegram bridge already running."
    exit 0
}

try {
    if (Test-Path $manualStopPath) {
        Write-Output "Telegram bridge is in manual stop mode."
        exit 0
    }

    $launch = Get-PythonLaunchSpec
    while ($true) {
        if (Test-Path $manualStopPath) {
            Write-Output "Telegram bridge stop flag detected."
            break
        }
        $proc = Start-Process -FilePath $launch.FilePath -ArgumentList $launch.Arguments -WorkingDirectory $PSScriptRoot -WindowStyle Hidden -PassThru
        $proc.WaitForExit()
        $exitCode = $proc.ExitCode
        if (Test-Path $manualStopPath) {
            Write-Output "Telegram bridge stopped by control panel."
            break
        }
        Write-Output ("Telegram bridge exited with code " + $exitCode + ". Restarting in " + $restartDelaySeconds + " seconds.")
        Start-Sleep -Seconds $restartDelaySeconds
    }
} finally {
    if ($lockStream) {
        $lockStream.Dispose()
    }
}

