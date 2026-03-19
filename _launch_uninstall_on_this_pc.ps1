$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.Windows.Forms

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$localEnv = Join-Path $root '_程式核心\.env.local'
$localTarget = Join-Path $root '_程式核心\uninstall_bridge.ps1'
$installedRoot = Join-Path $env:USERPROFILE 'telegram_codex_bridge'
$installedTarget = Join-Path $installedRoot '_程式核心\uninstall_bridge.ps1'

if ((Test-Path $localEnv) -and (Test-Path $localTarget)) {
    & $localTarget
    exit 0
}

if (Test-Path $installedTarget) {
    & $installedTarget
    exit 0
}

[System.Windows.Forms.MessageBox]::Show(
    'Bridge is not installed yet, so there is nothing to uninstall.',
    'Telegram Codex Bridge',
    [System.Windows.Forms.MessageBoxButtons]::OK,
    [System.Windows.Forms.MessageBoxIcon]::Information
) | Out-Null



