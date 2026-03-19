param(
    [ValidateSet('start', 'stop', 'restart', 'status', 'status-json', 'version-json', 'set-update-manifest', 'check-update', 'apply-update', 'open-folder', 'open-logs', 'create-shortcut', 'package', 'open-gui')]
    [string]$Action = 'start',
    [string]$ManifestUrl = '',
    [switch]$Force
)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$packageRoot = Split-Path -Parent $PSScriptRoot
$taskName = 'TelegramCodexBridge'
$startScript = Join-Path $PSScriptRoot 'start_bot.ps1'
$startCmd = Join-Path $PSScriptRoot 'START_TELEGRAM_CODEX_BRIDGE.cmd'
$guiScript = Join-Path $PSScriptRoot 'bridge_control_gui.ps1'
$guiCmd = Join-Path $PSScriptRoot 'OPEN_TELEGRAM_CODEX_BRIDGE.cmd'
$buildScript = Join-Path $PSScriptRoot 'build_portable_package.ps1'
$desktop = Join-Path $env:USERPROFILE 'Desktop'
$shortcutPath = Join-Path $desktop 'Telegram Codex Bridge.lnk'
$iconPath = Join-Path $PSScriptRoot 'assets\codex_bridge.ico'
$dataDir = Join-Path $PSScriptRoot 'data'
$logOut = Join-Path $dataDir 'bot.out.log'
$logErr = Join-Path $dataDir 'bot.err.log'
$lockPath = Join-Path $dataDir 'bot.supervisor.lock'
$manualStopPath = Join-Path $dataDir 'bot.manual_stop'
$appConfigPath = Join-Path $dataDir 'app_config.json'
$versionPath = Join-Path $PSScriptRoot 'APP_VERSION.json'
$updaterScript = Join-Path $PSScriptRoot 'update_bridge.ps1'
$envLocalPath = Join-Path $PSScriptRoot '.env.local'
$envPath = Join-Path $PSScriptRoot '.env'

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

function Get-BridgeConfigState {
    $envMap = [ordered]@{}
    foreach ($path in @($envPath, $envLocalPath)) {
        foreach ($entry in (Read-EnvFile $path).GetEnumerator()) {
            $envMap[$entry.Key] = $entry.Value
        }
    }

    $token = [string]$envMap['TELEGRAM_BOT_TOKEN']
    if ([string]::IsNullOrWhiteSpace($token)) {
        return [pscustomobject]@{
            IsConfigured = $false
            Message = 'Bridge is not configured yet. Run the installer and save a Telegram bot token first.'
        }
    }
    if ($token -match '\s' -or $token -notmatch '^\d{6,}:[A-Za-z0-9_-]{30,}$') {
        return [pscustomobject]@{
            IsConfigured = $false
            Message = 'Telegram bot token looks invalid. Re-run the installer and paste the full token from @BotFather.'
        }
    }

    return [pscustomobject]@{
        IsConfigured = $true
        Message = 'Configured.'
    }
}

function Get-BridgeProcessRecords {
    try {
        $all = @(Get-CimInstance Win32_Process)
        $supervisors = @($all | Where-Object {
                $_.Name -like 'powershell*.exe' -and
                $_.CommandLine -and
                $_.CommandLine.Contains($startScript)
            })
        $supervisorIds = @($supervisors | Select-Object -ExpandProperty ProcessId)
        $children = @()
        if ($supervisorIds.Count -gt 0) {
            $children = @($all | Where-Object {
                    $_.ParentProcessId -in $supervisorIds -or
                    ($_.Name -like 'python*.exe' -and $_.CommandLine -and $_.CommandLine.Contains('bot.py'))
                })
        }
        $direct = @($all | Where-Object {
                ($_.Name -like 'powershell*.exe' -and $_.CommandLine -and $_.CommandLine.Contains($startScript)) -or
                ($_.Name -like 'python*.exe' -and $_.CommandLine -and $_.CommandLine.Contains('bot.py'))
            })
        return @($direct + $children | Sort-Object ProcessId -Unique)
    } catch {
        return @()
    }
}

function Get-TaskRecord {
    try {
        return Get-ScheduledTask -TaskName $taskName -ErrorAction Stop
    } catch {
        return $null
    }
}

function Register-BridgeTask {
    $userId = "$env:USERDOMAIN\$env:USERNAME"
    $action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument ('-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "' + $startScript + '"') -WorkingDirectory $PSScriptRoot
    $trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
    $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -StartWhenAvailable -MultipleInstances IgnoreNew -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1)
    $settings.ExecutionTimeLimit = 'PT0S'
    $principal = New-ScheduledTaskPrincipal -UserId $userId -LogonType Interactive -RunLevel Limited
    $existingTask = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
    if ($existingTask) {
        Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
    }
    Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Description 'Start Telegram Codex Bridge at user logon and restart on failure' | Out-Null
}

function Ensure-TaskRegistrationCurrent {
    $task = Get-TaskRecord
    if (-not $task) {
        return $null
    }
    $action = @($task.Actions | Select-Object -First 1)
    $arguments = if ($action.Count -gt 0) { [string]$action[0].Arguments } else { '' }
    $workingDirectory = if ($action.Count -gt 0) { [string]$action[0].WorkingDirectory } else { '' }
    if ($arguments -notlike ('*' + $startScript + '*') -or $workingDirectory -ne $PSScriptRoot) {
        Register-BridgeTask
        return Get-TaskRecord
    }
    return $task
}

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

function Save-JsonFile([string]$Path, [hashtable]$Payload) {
    $dir = Split-Path -Parent $Path
    if (!(Test-Path $dir)) {
        New-Item -ItemType Directory -Path $dir | Out-Null
    }
    $Payload | ConvertTo-Json -Depth 8 | Set-Content -Path $Path -Encoding UTF8
}

function Get-AppVersionPayload {
    return Read-JsonFile $versionPath ([pscustomobject]@{
            app_name = 'Telegram Codex Bridge'
            version = '0.0.0'
            channel = 'stable'
            package_asset_name = 'GitHub_可發佈版.zip'
        })
}

function Get-AppVersion {
    $payload = Get-AppVersionPayload
    if ($payload -and $payload.version) {
        return [string]$payload.version
    }
    return '0.0.0'
}

function Get-AppConfigObject {
    $default = [pscustomobject]@{
        update_manifest_url = ''
        current_version = (Get-AppVersion)
        install_root = $packageRoot
        last_update_check = ''
        last_available_version = ''
        last_update_status = ''
    }
    return Read-JsonFile $appConfigPath $default
}

function Save-AppConfigObject([hashtable]$Payload) {
    Save-JsonFile $appConfigPath $Payload
}

function Update-AppConfig([hashtable]$Overrides) {
    $config = Get-AppConfigObject
    $payload = [ordered]@{
        update_manifest_url = $(if ($Overrides.ContainsKey('update_manifest_url')) { [string]$Overrides['update_manifest_url'] } elseif ($config.update_manifest_url) { [string]$config.update_manifest_url } else { '' })
        current_version = $(if ($Overrides.ContainsKey('current_version')) { [string]$Overrides['current_version'] } elseif ($config.current_version) { [string]$config.current_version } else { Get-AppVersion })
        install_root = $(if ($Overrides.ContainsKey('install_root')) { [string]$Overrides['install_root'] } elseif ($config.install_root) { [string]$config.install_root } else { $packageRoot })
        last_update_check = $(if ($Overrides.ContainsKey('last_update_check')) { [string]$Overrides['last_update_check'] } elseif ($config.last_update_check) { [string]$config.last_update_check } else { '' })
        last_available_version = $(if ($Overrides.ContainsKey('last_available_version')) { [string]$Overrides['last_available_version'] } elseif ($config.last_available_version) { [string]$config.last_available_version } else { '' })
        last_update_status = $(if ($Overrides.ContainsKey('last_update_status')) { [string]$Overrides['last_update_status'] } elseif ($config.last_update_status) { [string]$config.last_update_status } else { '' })
    }
    Save-AppConfigObject $payload
    return [pscustomobject]$payload
}

function Set-UpdateManifest([string]$Url) {
    $normalized = ([string]$Url).Trim()
    Update-AppConfig @{
        update_manifest_url = $normalized
        current_version = (Get-AppVersion)
        install_root = $packageRoot
        last_update_check = ''
        last_available_version = ''
        last_update_status = $(if ($normalized) { 'Update source configured.' } else { 'Update source cleared.' })
    } | Out-Null
    if ($normalized) {
        Write-Output 'Update manifest URL set.'
    } else {
        Write-Output 'Update manifest URL cleared.'
    }
}

function Read-Manifest([string]$Source) {
    if (-not $Source) {
        throw 'Update manifest source is not configured.'
    }
    if ($Source -match '^https?://') {
        return Invoke-RestMethod -Uri $Source -TimeoutSec 30
    }
    if (Test-Path $Source) {
        return Get-Content $Source -Raw -Encoding UTF8 | ConvertFrom-Json
    }
    throw ('Update manifest source not found: ' + $Source)
}

function Compare-Version([string]$A, [string]$B) {
    try {
        return ([version]$A).CompareTo([version]$B)
    } catch {
        return [string]::Compare($A, $B, $true)
    }
}

function Get-UpdateStatusObject([string]$SourceOverride = '') {
    $config = Get-AppConfigObject
    $current = Get-AppVersion
    $result = [ordered]@{
        current_version = $current
        manifest_url = $(if ($SourceOverride) { [string]$SourceOverride } else { [string]$config.update_manifest_url })
        available_version = ''
        update_available = $false
        package_url = ''
        notes_url = ''
        message = ''
    }
    if (-not $result.manifest_url) {
        $result.message = 'Update source is not configured.'
        return [pscustomobject]$result
    }
    try {
        $manifest = Read-Manifest $result.manifest_url
        $result.available_version = [string]$manifest.version
        $result.package_url = [string]$manifest.package_url
        $result.notes_url = [string]$manifest.notes_url
        $result.update_available = ((Compare-Version $result.available_version $current) -gt 0)
        if ($result.update_available) {
            $result.message = ('Update available: ' + $result.available_version)
        } else {
            $result.message = ('Already up to date: ' + $current)
        }
    } catch {
        $result.message = $_.Exception.Message
    }
    return [pscustomobject]$result
}

function Save-UpdateCheckResult([object]$Status) {
    Update-AppConfig @{
        update_manifest_url = [string]$Status.manifest_url
        current_version = (Get-AppVersion)
        install_root = $packageRoot
        last_update_check = (Get-Date).ToString('s')
        last_available_version = [string]$Status.available_version
        last_update_status = [string]$Status.message
    } | Out-Null
}

function Wait-BridgeState {
    param(
        [bool]$WantRunning,
        [int]$TimeoutSeconds = 18
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        $status = Get-BridgeStatusObject
        if ($WantRunning) {
            if ($status.IsRunning) {
                return
            }
        } else {
            if (-not $status.IsRunning) {
                return
            }
        }
        Start-Sleep -Milliseconds 750
    }
}

function Show-BridgeStatus {
    $status = Get-BridgeStatusObject
    Write-Output 'Telegram Codex Bridge'
    Write-Output ('Folder: ' + $status.Folder)
    Write-Output ('Version: ' + $status.CurrentVersion)
    Write-Output ('Config: ' + $status.ConfigMessage)
    Write-Output ('Task Scheduler: ' + $status.TaskState)
    Write-Output ('Processes: ' + $status.ProcessSummary)
    Write-Output ('Update Source: ' + $(if ($status.UpdateManifestUrl) { $status.UpdateManifestUrl } else { 'not configured' }))
    if ($status.LastUpdateCheck) {
        Write-Output ('Last Update Check: ' + $status.LastUpdateCheck)
    }
    if ($status.LastAvailableVersion) {
        Write-Output ('Last Available Version: ' + $status.LastAvailableVersion)
    }
    if ($status.LastUpdateStatus) {
        Write-Output ('Last Update Status: ' + $status.LastUpdateStatus)
    }
    if ($status.LastRunTime) {
        Write-Output ('Last Run: ' + $status.LastRunTime)
    }
    if ($status.LastTaskResult -ne $null) {
        Write-Output ('Last Result: ' + $status.LastTaskResult)
    }
    Write-Output ('Logs: ' + $status.OutLog)
    Write-Output ('Errors: ' + $status.ErrLog)
}

function Get-BridgeStatusObject {
    $task = Get-TaskRecord
    $procs = Get-BridgeProcessRecords
    $info = $null
    $config = Get-AppConfigObject
    $bridgeConfig = Get-BridgeConfigState
    if ($task) {
        $info = Get-ScheduledTaskInfo -TaskName $taskName -ErrorAction SilentlyContinue
    }
    return [pscustomobject]@{
        Folder = $PSScriptRoot
        TaskState = $(if ($task) { [string]$task.State } else { 'not installed' })
        LastRunTime = $(if ($info) { $info.LastRunTime } else { $null })
        LastTaskResult = $(if ($info) { $info.LastTaskResult } else { $null })
        ProcessSummary = $(if ($procs.Count -gt 0) { (($procs | Select-Object -ExpandProperty ProcessId) -join ', ') } else { 'not running' })
        ProcessCount = $procs.Count
        IsRunning = ($procs.Count -gt 0)
        ManualStop = (Test-Path $manualStopPath)
        OutLog = $logOut
        ErrLog = $logErr
        CurrentVersion = (Get-AppVersion)
        UpdateManifestUrl = [string]$config.update_manifest_url
        LastUpdateCheck = [string]$config.last_update_check
        LastAvailableVersion = [string]$config.last_available_version
        LastUpdateStatus = [string]$config.last_update_status
        IsConfigured = [bool]$bridgeConfig.IsConfigured
        ConfigMessage = [string]$bridgeConfig.Message
    }
}

function Start-Bridge {
    $bridgeConfig = Get-BridgeConfigState
    if (-not $bridgeConfig.IsConfigured) {
        throw [System.InvalidOperationException]::new([string]$bridgeConfig.Message)
    }

    if (Test-Path $manualStopPath) {
        Remove-Item $manualStopPath -Force -ErrorAction SilentlyContinue
    }
    $task = Ensure-TaskRegistrationCurrent
    if ($task) {
        Start-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
        Wait-BridgeState -WantRunning $true -TimeoutSeconds 8
        if ((Get-BridgeStatusObject).IsRunning) {
            Show-BridgeStatus
            return
        }
    }

    Start-Process -FilePath 'powershell.exe' -ArgumentList @(
        '-NoProfile',
        '-ExecutionPolicy', 'Bypass',
        '-WindowStyle', 'Hidden',
        '-File', $startScript
    ) -WorkingDirectory $PSScriptRoot | Out-Null
    Wait-BridgeState -WantRunning $true
    Show-BridgeStatus
}

function Stop-Bridge {
    New-Item -ItemType File -Path $manualStopPath -Force | Out-Null
    $task = Get-TaskRecord
    if ($task) {
        Stop-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
    }
    foreach ($proc in Get-BridgeProcessRecords) {
        try {
            Stop-Process -Id $proc.ProcessId -Force -ErrorAction Stop
        } catch {
        }
    }
    if (Test-Path $lockPath) {
        try {
            Remove-Item $lockPath -Force -ErrorAction Stop
        } catch {
        }
    }
    Wait-BridgeState -WantRunning $false
    Show-BridgeStatus
}

function Show-BridgeStatusJson {
    Get-BridgeStatusObject | ConvertTo-Json -Depth 6
}

function Show-VersionJson {
    $versionInfo = Get-AppVersionPayload
    $config = Get-AppConfigObject
    [ordered]@{
        app_name = [string]$versionInfo.app_name
        current_version = [string]$versionInfo.version
        channel = [string]$versionInfo.channel
        package_asset_name = [string]$versionInfo.package_asset_name
        update_manifest_url = [string]$config.update_manifest_url
        install_root = $packageRoot
    } | ConvertTo-Json -Depth 6
}

function Show-UpdateStatus {
    $status = Get-UpdateStatusObject $ManifestUrl
    Save-UpdateCheckResult $status
    $status | ConvertTo-Json -Depth 6
}

function Apply-BridgeUpdate {
    $config = Get-AppConfigObject
    $source = $(if ($ManifestUrl) { [string]$ManifestUrl } else { [string]$config.update_manifest_url })
    if (-not $source) {
        throw 'Update manifest URL is not configured.'
    }
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $updaterScript -ManifestSource $source -Force:$Force
}

function Create-DesktopShortcut {
    if (!(Test-Path $desktop)) {
        throw "Desktop folder not found: $desktop"
    }
    $shell = New-Object -ComObject WScript.Shell
    $shortcut = $shell.CreateShortcut($shortcutPath)
    $publicCmd = Join-Path $packageRoot '02_OPEN_CONTROL_PANEL.cmd'
    $shortcut.TargetPath = $(if (Test-Path $publicCmd) { $publicCmd } else { $guiCmd })
    $shortcut.WorkingDirectory = $(if (Test-Path $publicCmd) { $packageRoot } else { $PSScriptRoot })
    if (Test-Path $iconPath) {
        $shortcut.IconLocation = $iconPath
    }
    $shortcut.Description = 'Open the Telegram Codex Bridge control panel'
    $shortcut.Save()
    Write-Output ('Created desktop shortcut: ' + $shortcutPath)
}

function Open-Gui {
    Start-Process -FilePath 'powershell.exe' -ArgumentList @(
        '-NoProfile',
        '-ExecutionPolicy', 'Bypass',
        '-File', $guiScript
    ) -WorkingDirectory $PSScriptRoot | Out-Null
}

switch ($Action) {
    'start' { Start-Bridge; break }
    'stop' { Stop-Bridge; break }
    'restart' { Stop-Bridge; Start-Sleep -Seconds 2; Start-Bridge; break }
    'status' { Show-BridgeStatus; break }
    'status-json' { Show-BridgeStatusJson; break }
    'version-json' { Show-VersionJson; break }
    'set-update-manifest' { Set-UpdateManifest $ManifestUrl; break }
    'check-update' { Show-UpdateStatus; break }
    'apply-update' { Apply-BridgeUpdate; break }
    'open-folder' { Start-Process explorer.exe $PSScriptRoot | Out-Null; break }
    'open-logs' {
        if (Test-Path $logOut) { Start-Process notepad.exe $logOut | Out-Null }
        if (Test-Path $logErr) { Start-Process notepad.exe $logErr | Out-Null }
        break
    }
    'create-shortcut' { Create-DesktopShortcut; break }
    'open-gui' { Open-Gui; break }
    'package' {
        & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $buildScript
        break
    }
}



