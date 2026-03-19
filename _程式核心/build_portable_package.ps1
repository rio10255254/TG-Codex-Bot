param(
    [string]$OutputDir = "",
    [string]$PackageName = "GitHub_可發佈版",
    [ValidateSet('zip', 'folder')]
    [string]$Format = 'zip'
)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$PackageRoot = Split-Path -Parent $PSScriptRoot

if (-not $OutputDir) {
    $OutputDir = Join-Path $PackageRoot '_發布封包'
}

$packagePath = Join-Path $OutputDir $(if ($Format -eq 'zip') { $PackageName + '.zip' } else { $PackageName })
$stageRoot = Join-Path ([System.IO.Path]::GetTempPath()) ('telegram_codex_bridge_stage_' + [guid]::NewGuid().ToString('N'))

if (Test-Path $stageRoot) {
    Remove-Item $stageRoot -Recurse -Force
}
if (Test-Path $packagePath) {
    Remove-Item $packagePath -Recurse -Force
}

New-Item -ItemType Directory -Force -Path $stageRoot | Out-Null
New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null

$items = @(
    '01_INSTALL_ON_THIS_PC.cmd',
    '02_OPEN_CONTROL_PANEL.cmd',
    '04_UNINSTALL_ON_THIS_PC.cmd',
    '_launch_open_control_panel.ps1',
    '_launch_install_on_this_pc.ps1',
    '_launch_uninstall_on_this_pc.ps1',
    '03_MANUAL_zh-TW.md',
    'README.md',
    '.gitignore',
    '_開發者文件'
)

foreach ($item in $items) {
    $src = Join-Path $PackageRoot $item
    if (!(Test-Path $src)) {
        continue
    }
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
    'uninstall_bridge.ps1',
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

if ($Format -eq 'folder') {
    New-Item -ItemType Directory -Force -Path $packagePath | Out-Null
    Copy-Item (Join-Path $stageRoot '*') $packagePath -Recurse -Force
    Remove-Item $stageRoot -Recurse -Force
    Write-Output ("Folder package: " + $packagePath)
} else {
    Compress-Archive -Path (Join-Path $stageRoot '*') -DestinationPath $packagePath -Force
    Remove-Item $stageRoot -Recurse -Force
    Write-Output ("Zip package: " + $packagePath)
}




