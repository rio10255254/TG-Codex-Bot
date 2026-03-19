param(
    [string]$OutputDir = ""
)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$PackageRoot = Split-Path -Parent $PSScriptRoot

if (-not $OutputDir) {
    $OutputDir = Join-Path $PackageRoot '_發布封包'
}

New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null

$zipPath = Join-Path $OutputDir 'GitHub_可發佈版.zip'
$stageRoot = Join-Path ([System.IO.Path]::GetTempPath()) ('telegram_codex_bridge_stage_' + [guid]::NewGuid().ToString('N'))

if (Test-Path $stageRoot) {
    Remove-Item $stageRoot -Recurse -Force
}
if (Test-Path $zipPath) {
    Remove-Item $zipPath -Force
}

New-Item -ItemType Directory -Force -Path $stageRoot | Out-Null

$items = @(
    '01_OPEN_CONTROL_PANEL.cmd',
    '02_INSTALL_ON_THIS_PC.cmd',
    '_launch_open_control_panel.ps1',
    '_launch_install_on_this_pc.ps1',
    '03_MANUAL_zh-TW.md',
    'README.md',
    '.gitignore',
    '_開發者文件'
)

foreach ($item in $items) {
    $src = Join-Path $PackageRoot $item
    if (!(Test-Path $src)) { continue }
    $dst = Join-Path $stageRoot $item
    if (Test-Path $src -PathType Container) {
        Copy-Item $src $dst -Recurse -Force
    } else {
        Copy-Item $src $dst -Force
    }
}

$coreStage = Join-Path $stageRoot '_程式核心'
New-Item -ItemType Directory -Force -Path $coreStage | Out-Null

$coreFiles = @(
    '.env.example',
    '.gitignore',
    'APP_VERSION.json',
    'bot.py',
    'bridge_control.ps1',
    'bridge_control_gui.ps1',
    'build_portable_package.ps1',
    'install_bridge.ps1',
    'install_bridge_gui.ps1',
    'INSTALL_TELEGRAM_CODEX_BRIDGE.cmd',
    'OPEN_TELEGRAM_CODEX_BRIDGE.cmd',
    'start_bot.ps1',
    'START_TELEGRAM_CODEX_BRIDGE.cmd',
    'update_bridge.ps1'
)

foreach ($item in $coreFiles) {
    $src = Join-Path $PSScriptRoot $item
    if (Test-Path $src) {
        Copy-Item $src (Join-Path $coreStage $item) -Force
    }
}

if (Test-Path (Join-Path $PSScriptRoot 'assets')) {
    Copy-Item (Join-Path $PSScriptRoot 'assets') (Join-Path $coreStage 'assets') -Recurse -Force
}

Compress-Archive -Path (Join-Path $stageRoot '*') -DestinationPath $zipPath -Force
Remove-Item $stageRoot -Recurse -Force

Write-Output ("Zip package: " + $zipPath)

