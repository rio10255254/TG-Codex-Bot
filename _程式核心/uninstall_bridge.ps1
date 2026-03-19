param(
    [switch]$KeepData = $false
)

$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

$installRoot = Split-Path -Parent $PSScriptRoot
$taskName = 'TelegramCodexBridge'
$controlScript = Join-Path $PSScriptRoot 'bridge_control.ps1'
$desktopShortcut = Join-Path $env:USERPROFILE 'Desktop\Telegram Codex Bridge.lnk'
$cleanupScript = Join-Path $env:TEMP ('telegram_codex_bridge_uninstall_' + [guid]::NewGuid().ToString('N') + '.cmd')
$cleanupLines = @(
    '@echo off',
    'timeout /t 2 /nobreak >nul',
    ('rmdir /s /q "' + $installRoot + '"'),
    'del /f /q "%~f0"'
)

try {
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $controlScript -Action stop | Out-Null
} catch {
}

try {
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction Stop
} catch {
}

if (Test-Path $desktopShortcut) {
    Remove-Item $desktopShortcut -Force -ErrorAction SilentlyContinue
}

if ($KeepData) {
    Write-Output 'Bridge stopped and startup integration removed.'
    Write-Output 'Install folder was kept because -KeepData was specified.'
    exit 0
}

Set-Content -Path $cleanupScript -Value $cleanupLines -Encoding Ascii
Start-Process -FilePath 'cmd.exe' -ArgumentList @('/c', '"' + $cleanupScript + '"') -WindowStyle Hidden | Out-Null

Write-Output 'Bridge uninstall started.'
Write-Output 'The install folder will be removed in a moment.'



