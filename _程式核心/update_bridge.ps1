param(
    [string]$ManifestSource = "",
    [switch]$Force
)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$CoreRoot = $PSScriptRoot
$InstallRoot = Split-Path -Parent $CoreRoot
$DataDir = Join-Path $CoreRoot 'data'
$EnvPath = Join-Path $CoreRoot '.env'
$EnvLocalPath = Join-Path $CoreRoot '.env.local'
$AppConfigPath = Join-Path $DataDir 'app_config.json'
$VersionPath = Join-Path $CoreRoot 'APP_VERSION.json'
$ControlScript = Join-Path $CoreRoot 'bridge_control.ps1'

function Read-JsonFile([string]$Path, [object]$DefaultValue) {
    if (!(Test-Path $Path)) {
        return $DefaultValue
    }
    try {
        return Get-Content $Path -Raw -Encoding UTF8 | ConvertFrom-Json
    } catch {
        return $DefaultValue
    }
}

function Read-EnvFile([string]$Path) {
    $map = [ordered]@{}
    if (!(Test-Path $Path)) {
        return $map
    }
    foreach ($line in Get-Content $Path -Encoding UTF8) {
        if ([string]::IsNullOrWhiteSpace($line) -or $line.TrimStart().StartsWith('#')) {
            continue
        }
        $pair = $line.Split('=', 2)
        if ($pair.Count -eq 2) {
            $map[$pair[0].Trim()] = $pair[1]
        }
    }
    return $map
}

function Read-CurrentEnvMap {
    $merged = [ordered]@{}
    foreach ($path in @($EnvPath, $EnvLocalPath)) {
        foreach ($entry in (Read-EnvFile $path).GetEnumerator()) {
            $merged[$entry.Key] = $entry.Value
        }
    }
    return $merged
}

function Get-InstalledVersion {
    $versionInfo = Read-JsonFile $VersionPath $null
    if ($versionInfo -and $versionInfo.version) {
        return [string]$versionInfo.version
    }
    return "0.0.0"
}

function Read-AppConfig {
    $default = [pscustomobject]@{
        update_manifest_url = ""
        current_version = (Get-InstalledVersion)
        install_root = $InstallRoot
        last_update_check = ""
        last_available_version = ""
        last_update_status = ""
    }
    return Read-JsonFile $AppConfigPath $default
}

function Save-AppConfig([hashtable]$Map) {
    if (!(Test-Path $DataDir)) {
        New-Item -ItemType Directory -Path $DataDir | Out-Null
    }
    $Map | ConvertTo-Json -Depth 8 | Set-Content -Path $AppConfigPath -Encoding UTF8
}

function Compare-Version([string]$A, [string]$B) {
    try {
        return ([version]$A).CompareTo([version]$B)
    } catch {
        return [string]::Compare($A, $B, $true)
    }
}

function Read-Manifest([string]$Source) {
    if (-not $Source) {
        throw "Update manifest source is not configured."
    }
    if ($Source -match '^https?://') {
        return Invoke-RestMethod -Uri $Source -TimeoutSec 30
    }
    if (Test-Path $Source) {
        return Get-Content $Source -Raw -Encoding UTF8 | ConvertFrom-Json
    }
    throw "Update manifest source not found: $Source"
}

function Get-UpdateInfo([string]$Source) {
    $manifest = Read-Manifest $Source
    if (-not $manifest.version) {
        throw "Manifest is missing version."
    }
    if (-not $manifest.package_url) {
        throw "Manifest is missing package_url."
    }
    $current = Get-InstalledVersion
    $available = [string]$manifest.version
    return [pscustomobject]@{
        CurrentVersion = $current
        AvailableVersion = $available
        UpdateAvailable = ((Compare-Version $available $current) -gt 0)
        PackageUrl = [string]$manifest.package_url
        NotesUrl = [string]($manifest.notes_url)
        ManifestSource = $Source
    }
}

function Invoke-Update([string]$Source, [switch]$ForceUpdate) {
    $info = Get-UpdateInfo $Source
    if (-not $info.UpdateAvailable -and -not $ForceUpdate) {
        Save-AppConfig ([ordered]@{
                update_manifest_url = $Source
                current_version = $info.CurrentVersion
                install_root = $InstallRoot
                last_update_check = (Get-Date).ToString('s')
                last_available_version = $info.AvailableVersion
                last_update_status = 'Already up to date.'
            })
        Write-Output ("Already up to date: " + $info.CurrentVersion)
        return
    }

    $tempRoot = Join-Path ([System.IO.Path]::GetTempPath()) ('telegram_codex_update_' + [guid]::NewGuid().ToString('N'))
    $zipPath = Join-Path $tempRoot 'package.zip'
    $extractPath = Join-Path $tempRoot 'extract'
    New-Item -ItemType Directory -Path $tempRoot | Out-Null

    try {
        if ($info.PackageUrl -match '^https?://') {
            Invoke-WebRequest -Uri $info.PackageUrl -OutFile $zipPath -TimeoutSec 120
        } elseif (Test-Path $info.PackageUrl) {
            Copy-Item $info.PackageUrl $zipPath -Force
        } else {
            throw "Package URL/path is invalid: $($info.PackageUrl)"
        }

        Expand-Archive -Path $zipPath -DestinationPath $extractPath -Force
        $installer = Join-Path $extractPath '_程式核心\install_bridge.ps1'
        if (!(Test-Path $installer)) {
            throw "Downloaded package is missing install_bridge.ps1"
        }

        $envMap = Read-CurrentEnvMap
        if (-not [string]$envMap['TELEGRAM_BOT_TOKEN']) {
            throw 'Current installation has no TELEGRAM_BOT_TOKEN in .env.local or .env.'
        }

        & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $ControlScript -Action stop | Out-Null

        & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $installer `
            -InstallDir $InstallRoot `
            -BotToken ([string]$envMap['TELEGRAM_BOT_TOKEN']) `
            -AllowedChatIds ([string]$envMap['TELEGRAM_ALLOWED_CHAT_IDS']) `
            -DefaultCwd ([string]$envMap['CODEX_DEFAULT_CWD']) `
            -TelegramProjects ([string]$envMap['TELEGRAM_PROJECTS']) `
            -UpdateManifestUrl $Source `
            -RegisterTask:$true `
            -CreateDesktopShortcut:$true `
            -StartNow:$true `
            -AutoInstallDependencies:$true

        $config = [ordered]@{
            update_manifest_url = $Source
            current_version = $info.AvailableVersion
            install_root = $InstallRoot
            last_update_check = (Get-Date).ToString('s')
            last_available_version = $info.AvailableVersion
            last_update_status = 'Updated successfully.'
        }
        Save-AppConfig $config
        Write-Output ("Updated from " + $info.CurrentVersion + " to " + $info.AvailableVersion)
    } finally {
        if (Test-Path $tempRoot) {
            Remove-Item $tempRoot -Recurse -Force -ErrorAction SilentlyContinue
        }
    }
}

$config = Read-AppConfig
$source = if ($ManifestSource) { $ManifestSource } else { [string]$config.update_manifest_url }
Invoke-Update -Source $source -ForceUpdate:$Force
