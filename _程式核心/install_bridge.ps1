param(
    [string]$InstallDir = "",
    [string]$BotToken = "",
    [string]$AllowedChatIds = "",
    [string]$DefaultCwd = "",
    [string]$TelegramProjects = "",
    [string]$UpdateManifestUrl = "",
    [switch]$AutoInstallDependencies,
    [switch]$RegisterTask,
    [switch]$CreateDesktopShortcut,
    [switch]$StartNow
)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$PackageRoot = Split-Path -Parent $PSScriptRoot

if (-not $InstallDir) {
    $InstallDir = Join-Path $env:USERPROFILE 'telegram_codex_bridge'
}
if (-not $DefaultCwd) {
    $DefaultCwd = $env:USERPROFILE
}

if (-not $PSBoundParameters.ContainsKey('RegisterTask')) {
    $RegisterTask = $true
}
if (-not $PSBoundParameters.ContainsKey('CreateDesktopShortcut')) {
    $CreateDesktopShortcut = $true
}
if (-not $PSBoundParameters.ContainsKey('StartNow')) {
    $StartNow = $true
}
if (-not $PSBoundParameters.ContainsKey('AutoInstallDependencies')) {
    $AutoInstallDependencies = $true
}

if (-not $BotToken) {
    $BotToken = Read-Host 'Telegram bot token from @BotFather (leave blank to fill later)'
}
if (-not $PSBoundParameters.ContainsKey('AllowedChatIds')) {
    $AllowedChatIds = Read-Host 'Allowed Telegram chat IDs, comma-separated (leave blank for first run)'
}
if (-not $PSBoundParameters.ContainsKey('DefaultCwd')) {
    $enteredCwd = Read-Host ("Default Codex working directory [" + $DefaultCwd + "]")
    if ($enteredCwd) {
        $DefaultCwd = $enteredCwd
    }
}
if (-not $PSBoundParameters.ContainsKey('TelegramProjects')) {
    $TelegramProjects = Read-Host 'Pinned projects as name=path;name=path (optional)'
}
if (-not $PSBoundParameters.ContainsKey('UpdateManifestUrl')) {
    $UpdateManifestUrl = Read-Host 'GitHub update manifest URL (optional, can be left blank for now)'
}

function Normalize-BotToken([string]$Value) {
    return ([string]$Value -replace '\s', '').Trim()
}

function Test-BotTokenLooksValid([string]$Value) {
    return [bool]([string]$Value -match '^\d{6,}:[A-Za-z0-9_-]{30,}$')
}

$BotToken = Normalize-BotToken $BotToken
if ($BotToken -and -not (Test-BotTokenLooksValid $BotToken)) {
    throw 'Telegram bot token looks invalid. Paste the full token from @BotFather without spaces or line breaks.'
}

function Read-EnvFile([string]$Path) {
    $map = [ordered]@{}
    if (Test-Path $Path) {
        foreach ($line in Get-Content $Path -Encoding UTF8) {
            if ([string]::IsNullOrWhiteSpace($line) -or $line.TrimStart().StartsWith('#')) {
                continue
            }
            $pair = $line.Split('=', 2)
            if ($pair.Count -eq 2) {
                $map[$pair[0].Trim()] = $pair[1]
            }
        }
    }
    return $map
}

function Write-Section([string]$Title) {
    Write-Output ""
    Write-Output ("=== " + $Title + " ===")
}

function Get-CommandSourceOrEmpty([string]$Name) {
    $cmd = Get-Command $Name -ErrorAction SilentlyContinue
    if ($cmd -and $cmd.Source) {
        return [string]$cmd.Source
    }
    return ""
}

function Invoke-LoggedProcess {
    param(
        [string]$FilePath,
        [string[]]$Arguments,
        [string]$Label,
        [int]$TimeoutSeconds = 900
    )

    $stdoutPath = [System.IO.Path]::GetTempFileName()
    $stderrPath = [System.IO.Path]::GetTempFileName()
    try {
        Write-Output ($Label + "...")
        $proc = Start-Process -FilePath $FilePath -ArgumentList $Arguments -PassThru -WindowStyle Hidden -RedirectStandardOutput $stdoutPath -RedirectStandardError $stderrPath
        if (-not $proc.WaitForExit($TimeoutSeconds * 1000)) {
            try {
                Stop-Process -Id $proc.Id -Force -ErrorAction Stop
            } catch {
            }
            throw ($Label + " timed out after " + $TimeoutSeconds + " seconds.")
        }

        $stdout = if (Test-Path $stdoutPath) { Get-Content $stdoutPath -Raw -Encoding UTF8 } else { '' }
        $stderr = if (Test-Path $stderrPath) { Get-Content $stderrPath -Raw -Encoding UTF8 } else { '' }
        if ($stdout) {
            Write-Output $stdout.TrimEnd()
        }
        if ($stderr) {
            Write-Output $stderr.TrimEnd()
        }
        if ($proc.ExitCode -ne 0) {
            throw ($Label + " failed with exit code " + $proc.ExitCode + ".")
        }
    } finally {
        if (Test-Path $stdoutPath) { Remove-Item $stdoutPath -Force -ErrorAction SilentlyContinue }
        if (Test-Path $stderrPath) { Remove-Item $stderrPath -Force -ErrorAction SilentlyContinue }
    }
}

function Ensure-WingetPackage([string]$Id, [string]$Label) {
    $winget = Get-Command winget -ErrorAction SilentlyContinue
    if (-not $winget) {
        throw "winget is required to auto-install $Label on this machine."
    }
    Invoke-LoggedProcess -FilePath $winget.Source -Arguments @(
        'install',
        '--id', $Id,
        '--accept-package-agreements',
        '--accept-source-agreements',
        '--silent',
        '--disable-interactivity'
    ) -Label ("Installing " + $Label + " via winget") -TimeoutSeconds 1800
}

function Ensure-PythonRuntime {
    Write-Output 'Checking Python runtime...'
    $python = Get-CommandSourceOrEmpty 'python'
    if ($python) {
        Write-Output ('Python already available: ' + $python)
        return $python
    }
    $pyLauncher = Get-CommandSourceOrEmpty 'py'
    if ($pyLauncher) {
        Write-Output ('Python launcher already available: ' + $pyLauncher)
        return $pyLauncher
    }
    if (-not $AutoInstallDependencies) {
        throw "Python was not found."
    }
    Ensure-WingetPackage -Id 'Python.Python.3.12' -Label 'Python 3.12'
    $python = Get-CommandSourceOrEmpty 'python'
    if ($python) {
        return $python
    }
    $pyLauncher = Get-CommandSourceOrEmpty 'py'
    if ($pyLauncher) {
        return $pyLauncher
    }
    throw "Python installation completed, but python was still not found on PATH."
}

function Ensure-NodeRuntime {
    Write-Output 'Checking Node.js runtime...'
    $node = Get-CommandSourceOrEmpty 'node'
    $npm = Get-CommandSourceOrEmpty 'npm'
    if ($node -and $npm) {
        Write-Output ('Node already available: ' + $node)
        Write-Output ('npm already available: ' + $npm)
        return @{ node = $node; npm = $npm }
    }
    if (-not $AutoInstallDependencies) {
        throw "Node.js / npm was not found."
    }
    Ensure-WingetPackage -Id 'OpenJS.NodeJS.LTS' -Label 'Node.js LTS'
    $node = Get-CommandSourceOrEmpty 'node'
    $npm = Get-CommandSourceOrEmpty 'npm'
    if ($node -and $npm) {
        return @{ node = $node; npm = $npm }
    }
    throw "Node.js installation completed, but node/npm was still not found on PATH."
}

function Ensure-CodexCli {
    Write-Output 'Checking Codex CLI...'
    $codex = Get-CommandSourceOrEmpty 'codex'
    if ($codex) {
        Write-Output ('Codex already available: ' + $codex)
        return $codex
    }
    $codexCmd = Get-CommandSourceOrEmpty 'codex.cmd'
    if ($codexCmd) {
        Write-Output ('Codex already available: ' + $codexCmd)
        return $codexCmd
    }
    if (-not $AutoInstallDependencies) {
        throw "Codex CLI was not found."
    }
    $nodeTools = Ensure-NodeRuntime
    Invoke-LoggedProcess -FilePath 'cmd.exe' -Arguments @('/c', 'npm', 'install', '-g', '@openai/codex') -Label 'Installing Codex CLI via npm' -TimeoutSeconds 1800
    $codex = Get-CommandSourceOrEmpty 'codex'
    if ($codex) {
        return $codex
    }
    $codexCmd = Get-CommandSourceOrEmpty 'codex.cmd'
    if ($codexCmd) {
        return $codexCmd
    }
    throw "Codex CLI installation completed, but codex/codex.cmd was still not found on PATH."
}

function Write-EnvFile([string]$Path, [hashtable]$Map) {
    $lines = @(
        '# Telegram bot token from @BotFather'
        ('TELEGRAM_BOT_TOKEN=' + $Map['TELEGRAM_BOT_TOKEN'])
        ''
        '# Comma-separated Telegram chat IDs that are allowed to control the bot.'
        '# Leave blank for first run. The bot will reply with your chat ID and refuse execution.'
        ('TELEGRAM_ALLOWED_CHAT_IDS=' + $Map['TELEGRAM_ALLOWED_CHAT_IDS'])
        ''
        '# Default working directory used before /cd is set for a chat'
        ('CODEX_DEFAULT_CWD=' + $Map['CODEX_DEFAULT_CWD'])
        ''
        '# Optional pinned projects shown first in the Telegram project picker.'
        '# Format: name=path;name=path'
        ('TELEGRAM_PROJECTS=' + $Map['TELEGRAM_PROJECTS'])
        ''
        '# Optional Codex defaults'
        ('CODEX_MODEL=' + $Map['CODEX_MODEL'])
        ('CODEX_PROFILE=' + $Map['CODEX_PROFILE'])
        ('CODEX_SANDBOX=' + $Map['CODEX_SANDBOX'])
        ('CODEX_APPROVAL_POLICY=' + $Map['CODEX_APPROVAL_POLICY'])
        ('CODEX_TIMEOUT_SECONDS=' + $Map['CODEX_TIMEOUT_SECONDS'])
        ('TELEGRAM_POLL_TIMEOUT_SECONDS=' + $Map['TELEGRAM_POLL_TIMEOUT_SECONDS'])
        ('MAX_CONCURRENT_JOBS=' + $Map['MAX_CONCURRENT_JOBS'])
        ('HEARTBEAT_SECONDS=' + $Map['HEARTBEAT_SECONDS'])
        ''
        '# Optional extra top-level Codex arguments, for example:'
        '# CODEX_EXTRA_ARGS=--search'
        ('CODEX_EXTRA_ARGS=' + $Map['CODEX_EXTRA_ARGS'])
    )
    Set-Content -Path $Path -Value $lines -Encoding UTF8
}

function Read-AppVersion([string]$CorePath) {
    $path = Join-Path $CorePath 'APP_VERSION.json'
    if (!(Test-Path $path)) {
        return "0.0.0"
    }
    try {
        $payload = Get-Content $path -Raw -Encoding UTF8 | ConvertFrom-Json
        return [string]$payload.version
    } catch {
        return "0.0.0"
    }
}

function Save-AppConfig([string]$Path, [hashtable]$Payload) {
    $dir = Split-Path -Parent $Path
    if (!(Test-Path $dir)) {
        New-Item -ItemType Directory -Path $dir | Out-Null
    }
    $Payload | ConvertTo-Json -Depth 8 | Set-Content -Path $Path -Encoding UTF8
}

function Copy-DirectoryContents([string]$SourceDir, [string]$TargetDir) {
    New-Item -ItemType Directory -Force -Path $TargetDir | Out-Null
    foreach ($child in Get-ChildItem -Force $SourceDir) {
        Copy-Item $child.FullName (Join-Path $TargetDir $child.Name) -Recurse -Force
    }
}

function Copy-BridgeFiles([string]$SourceRoot, [string]$TargetRoot) {
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
    New-Item -ItemType Directory -Force -Path $TargetRoot | Out-Null
    foreach ($item in $items) {
        $src = Join-Path $SourceRoot $item
        if (!(Test-Path $src)) {
            continue
        }
        $dst = Join-Path $TargetRoot $item
        if (Test-Path $src -PathType Container) {
            Copy-DirectoryContents -SourceDir $src -TargetDir $dst
        } else {
            Copy-Item $src $dst -Force
        }
    }

    $sourceCore = Join-Path $SourceRoot '_程式核心'
    $targetCore = Join-Path $TargetRoot '_程式核心'
    New-Item -ItemType Directory -Force -Path $targetCore | Out-Null

    foreach ($item in $coreFiles) {
        $src = Join-Path $sourceCore $item
        if (Test-Path $src) {
            Copy-Item $src (Join-Path $targetCore $item) -Force
        }
    }

    $sourceAssets = Join-Path $sourceCore 'assets'
    if (Test-Path $sourceAssets) {
        Copy-DirectoryContents -SourceDir $sourceAssets -TargetDir (Join-Path $targetCore 'assets')
    }

    New-Item -ItemType Directory -Force -Path (Join-Path $targetCore 'data') | Out-Null
}

Write-Section 'Dependency Check'
$pythonRuntime = Ensure-PythonRuntime
$codexRuntime = Ensure-CodexCli
Write-Output ("Python ready: " + $pythonRuntime)
Write-Output ("Codex ready: " + $codexRuntime)

Write-Section 'Copy Files'
Copy-BridgeFiles -SourceRoot $PackageRoot -TargetRoot $InstallDir

Write-Section 'Write Config'
$envPath = Join-Path $InstallDir '_程式核心\.env.local'
$existing = Read-EnvFile $envPath
$existing['TELEGRAM_BOT_TOKEN'] = if ($BotToken) { Normalize-BotToken $BotToken } else { Normalize-BotToken ([string]($existing['TELEGRAM_BOT_TOKEN'])) }
$existing['TELEGRAM_ALLOWED_CHAT_IDS'] = if ($AllowedChatIds) { $AllowedChatIds } else { [string]($existing['TELEGRAM_ALLOWED_CHAT_IDS']) }
$existing['CODEX_DEFAULT_CWD'] = if ($DefaultCwd) { $DefaultCwd } else { [string]($existing['CODEX_DEFAULT_CWD']) }
$existing['TELEGRAM_PROJECTS'] = if ($TelegramProjects) { $TelegramProjects } else { [string]($existing['TELEGRAM_PROJECTS']) }
$existing['CODEX_MODEL'] = [string]($existing['CODEX_MODEL'])
$existing['CODEX_PROFILE'] = [string]($existing['CODEX_PROFILE'])
$existing['CODEX_SANDBOX'] = if ($existing['CODEX_SANDBOX']) { [string]$existing['CODEX_SANDBOX'] } else { 'danger-full-access' }
$existing['CODEX_APPROVAL_POLICY'] = if ($existing['CODEX_APPROVAL_POLICY']) { [string]$existing['CODEX_APPROVAL_POLICY'] } else { 'never' }
$existing['CODEX_TIMEOUT_SECONDS'] = if ($existing['CODEX_TIMEOUT_SECONDS']) { [string]$existing['CODEX_TIMEOUT_SECONDS'] } else { '1800' }
$existing['TELEGRAM_POLL_TIMEOUT_SECONDS'] = if ($existing['TELEGRAM_POLL_TIMEOUT_SECONDS']) { [string]$existing['TELEGRAM_POLL_TIMEOUT_SECONDS'] } else { '30' }
$existing['MAX_CONCURRENT_JOBS'] = if ($existing['MAX_CONCURRENT_JOBS']) { [string]$existing['MAX_CONCURRENT_JOBS'] } else { '2' }
$existing['HEARTBEAT_SECONDS'] = if ($existing['HEARTBEAT_SECONDS']) { [string]$existing['HEARTBEAT_SECONDS'] } else { '25' }
$existing['CODEX_EXTRA_ARGS'] = [string]($existing['CODEX_EXTRA_ARGS'])
Write-EnvFile -Path $envPath -Map $existing

$appVersion = Read-AppVersion (Join-Path $InstallDir '_程式核心')
$appConfigPath = Join-Path $InstallDir '_程式核心\data\app_config.json'
$appConfig = [ordered]@{
    update_manifest_url = $UpdateManifestUrl
    current_version = $appVersion
    install_root = $InstallDir
    last_update_check = ""
    last_available_version = ""
    last_update_status = ""
}
Save-AppConfig -Path $appConfigPath -Payload $appConfig

Write-Output ("Installed bridge to: " + $InstallDir)
Write-Output ("Python: " + $pythonRuntime)
Write-Output ("Codex CLI: " + $codexRuntime)
Write-Output ("App version: " + $appVersion)

$controlScript = Join-Path $InstallDir '_程式核心\bridge_control.ps1'
if ($RegisterTask) {
    Write-Section 'Register Task Scheduler'
    $taskName = 'TelegramCodexBridge'
    $scriptPath = Join-Path $InstallDir '_程式核心\start_bot.ps1'
    $workingDir = Join-Path $InstallDir '_程式核心'
    $userId = "$env:USERDOMAIN\$env:USERNAME"
    $action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument ('-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "' + $scriptPath + '"') -WorkingDirectory $workingDir
    $trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
    $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -StartWhenAvailable -MultipleInstances IgnoreNew -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1)
    $settings.ExecutionTimeLimit = 'PT0S'
    $principal = New-ScheduledTaskPrincipal -UserId $userId -LogonType Interactive -RunLevel Limited
    $existingTask = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
    if ($existingTask) { Unregister-ScheduledTask -TaskName $taskName -Confirm:$false }
    Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Description 'Start Telegram Codex Bridge at user logon and restart on failure' | Out-Null
    Write-Output "Task Scheduler entry installed."
}

if ($CreateDesktopShortcut) {
    Write-Section 'Create Desktop Shortcut'
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $controlScript -Action create-shortcut
}

if ($StartNow) {
    Write-Section 'Start Bridge'
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $controlScript -Action start
}

Write-Output ""
Write-Output "Next steps:"
Write-Output "1. Open the desktop shortcut 'Telegram Codex Bridge' or the file '02_OPEN_CONTROL_PANEL.cmd'."
Write-Output "2. Open the bot in Telegram and send /start."
Write-Output "3. If no allowlist is set yet, the first Telegram chat can claim the bridge directly from Telegram."
Write-Output "4. Later, an authorized admin chat can add more users with /allow <chat_id>."





