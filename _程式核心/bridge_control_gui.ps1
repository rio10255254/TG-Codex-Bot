param()

$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
Add-Type -AssemblyName Microsoft.VisualBasic

$controlScript = Join-Path $PSScriptRoot 'bridge_control.ps1'
$installGuiScript = Join-Path $PSScriptRoot 'install_bridge_gui.ps1'
$iconPath = Join-Path $PSScriptRoot 'assets\codex_bridge.ico'
$heroPath = Join-Path $PSScriptRoot 'assets\codex_welcome.png'

function Load-ImageCopy([string]$Path) {
    $bytes = [System.IO.File]::ReadAllBytes($Path)
    $stream = New-Object System.IO.MemoryStream(,$bytes)
    try {
        $image = [System.Drawing.Image]::FromStream($stream)
        return New-Object System.Drawing.Bitmap($image)
    } finally {
        $stream.Dispose()
    }
}

function Invoke-BridgeAction {
    param(
        [string]$Action,
        [string]$ManifestUrl = '',
        [switch]$Force
    )

    $args = @(
        '-NoProfile',
        '-ExecutionPolicy', 'Bypass',
        '-File', $controlScript,
        '-Action', $Action
    )
    if ($PSBoundParameters.ContainsKey('ManifestUrl')) {
        $args += @('-ManifestUrl', $ManifestUrl)
    }
    if ($Force) {
        $args += '-Force'
    }
    & powershell.exe @args | Out-String
}

function Get-BridgeStatusObject {
    $json = Invoke-BridgeAction -Action 'status-json'
    try {
        return $json | ConvertFrom-Json
    } catch {
        return [pscustomobject]@{
            Folder = $PSScriptRoot
            TaskState = 'unknown'
            LastRunTime = $null
            LastTaskResult = $null
            ProcessSummary = 'unknown'
            ProcessCount = 0
            ManualStop = $false
            OutLog = ''
            ErrLog = ''
            CurrentVersion = '0.0.0'
            UpdateManifestUrl = ''
            LastUpdateCheck = ''
            LastAvailableVersion = ''
            LastUpdateStatus = ''
        }
    }
}

function Open-InstallerGui {
    Start-Process -FilePath 'powershell.exe' -ArgumentList @(
        '-NoProfile',
        '-ExecutionPolicy', 'Bypass',
        '-File', $installGuiScript
    ) -WorkingDirectory $PSScriptRoot | Out-Null
}

function Format-SummaryText([object]$Status) {
    $lines = @(
        ('Folder: ' + [string]$Status.Folder),
        ('Version: ' + [string]$Status.CurrentVersion),
        ('Config: ' + $(if ($Status.ConfigMessage) { [string]$Status.ConfigMessage } else { 'unknown' })),
        ('Task Scheduler: ' + [string]$Status.TaskState),
        ('Processes: ' + [string]$Status.ProcessSummary),
        ('Update Source: ' + $(if ($Status.UpdateManifestUrl) { [string]$Status.UpdateManifestUrl } else { 'not configured' })),
        ('Last Update Check: ' + $(if ($Status.LastUpdateCheck) { [string]$Status.LastUpdateCheck } else { 'not yet checked' })),
        ('Last Available Version: ' + $(if ($Status.LastAvailableVersion) { [string]$Status.LastAvailableVersion } else { 'unknown' })),
        ('Last Update Status: ' + $(if ($Status.LastUpdateStatus) { [string]$Status.LastUpdateStatus } else { 'none' }))
    )
    return ($lines -join [Environment]::NewLine)
}

$form = New-Object System.Windows.Forms.Form
$form.Text = 'Telegram Codex Bridge'
$form.Size = New-Object System.Drawing.Size(980, 760)
$form.StartPosition = 'CenterScreen'
$form.BackColor = [System.Drawing.ColorTranslator]::FromHtml('#f5f1e8')
$form.FormBorderStyle = 'FixedDialog'
$form.MaximizeBox = $false
$form.MinimizeBox = $true

if (Test-Path $iconPath) {
    $form.Icon = New-Object System.Drawing.Icon($iconPath)
}

$headerPanel = New-Object System.Windows.Forms.Panel
$headerPanel.Location = New-Object System.Drawing.Point(0, 0)
$headerPanel.Size = New-Object System.Drawing.Size(980, 180)
$headerPanel.BackColor = [System.Drawing.ColorTranslator]::FromHtml('#111111')
$form.Controls.Add($headerPanel)

if (Test-Path $heroPath) {
    $picture = New-Object System.Windows.Forms.PictureBox
    $picture.Location = New-Object System.Drawing.Point(28, 18)
    $picture.Size = New-Object System.Drawing.Size(118, 118)
    $picture.SizeMode = 'Zoom'
    $picture.Image = Load-ImageCopy $heroPath
    $headerPanel.Controls.Add($picture)
}

$title = New-Object System.Windows.Forms.Label
$title.Text = 'Telegram Codex Bridge'
$title.Font = New-Object System.Drawing.Font('Bahnschrift', 24, [System.Drawing.FontStyle]::Bold)
$title.AutoSize = $true
$title.Location = New-Object System.Drawing.Point(168, 28)
$title.ForeColor = [System.Drawing.Color]::White
$headerPanel.Controls.Add($title)

$subtitle = New-Object System.Windows.Forms.Label
$subtitle.Text = 'Local app-style control panel for running, repairing, packaging, and updating your Telegram bridge.'
$subtitle.Font = New-Object System.Drawing.Font('Segoe UI', 10)
$subtitle.AutoSize = $true
$subtitle.Location = New-Object System.Drawing.Point(171, 74)
$subtitle.ForeColor = [System.Drawing.ColorTranslator]::FromHtml('#d8d3ca')
$headerPanel.Controls.Add($subtitle)

$stateBadge = New-Object System.Windows.Forms.Label
$stateBadge.Text = 'Status'
$stateBadge.Font = New-Object System.Drawing.Font('Segoe UI', 10, [System.Drawing.FontStyle]::Bold)
$stateBadge.AutoSize = $false
$stateBadge.Size = New-Object System.Drawing.Size(180, 36)
$stateBadge.Location = New-Object System.Drawing.Point(171, 108)
$stateBadge.TextAlign = 'MiddleCenter'
$stateBadge.BackColor = [System.Drawing.ColorTranslator]::FromHtml('#e9e4d8')
$stateBadge.ForeColor = [System.Drawing.ColorTranslator]::FromHtml('#111111')
$headerPanel.Controls.Add($stateBadge)

$lastAction = New-Object System.Windows.Forms.Label
$lastAction.Text = 'Ready.'
$lastAction.Font = New-Object System.Drawing.Font('Segoe UI', 9)
$lastAction.AutoSize = $true
$lastAction.Location = New-Object System.Drawing.Point(390, 116)
$lastAction.ForeColor = [System.Drawing.ColorTranslator]::FromHtml('#d8d3ca')
$headerPanel.Controls.Add($lastAction)

$versionBadge = New-Object System.Windows.Forms.Label
$versionBadge.Text = 'v0.0.0'
$versionBadge.Font = New-Object System.Drawing.Font('Segoe UI', 10, [System.Drawing.FontStyle]::Bold)
$versionBadge.AutoSize = $false
$versionBadge.Size = New-Object System.Drawing.Size(120, 36)
$versionBadge.Location = New-Object System.Drawing.Point(760, 28)
$versionBadge.TextAlign = 'MiddleCenter'
$versionBadge.BackColor = [System.Drawing.ColorTranslator]::FromHtml('#1d1d1d')
$versionBadge.ForeColor = [System.Drawing.ColorTranslator]::FromHtml('#f5f1e8')
$headerPanel.Controls.Add($versionBadge)

$updateBadge = New-Object System.Windows.Forms.Label
$updateBadge.Text = 'No update source'
$updateBadge.Font = New-Object System.Drawing.Font('Segoe UI', 9, [System.Drawing.FontStyle]::Bold)
$updateBadge.AutoSize = $false
$updateBadge.Size = New-Object System.Drawing.Size(190, 36)
$updateBadge.Location = New-Object System.Drawing.Point(760, 76)
$updateBadge.TextAlign = 'MiddleCenter'
$updateBadge.BackColor = [System.Drawing.ColorTranslator]::FromHtml('#2b2b2b')
$updateBadge.ForeColor = [System.Drawing.ColorTranslator]::FromHtml('#d8d3ca')
$headerPanel.Controls.Add($updateBadge)

$sourceCaption = New-Object System.Windows.Forms.Label
$sourceCaption.Text = 'Set one update source once, then Update Now can reuse it.'
$sourceCaption.Font = New-Object System.Drawing.Font('Segoe UI', 8)
$sourceCaption.AutoSize = $true
$sourceCaption.Location = New-Object System.Drawing.Point(760, 121)
$sourceCaption.ForeColor = [System.Drawing.ColorTranslator]::FromHtml('#b9b4ab')
$headerPanel.Controls.Add($sourceCaption)

$card = New-Object System.Windows.Forms.Panel
$card.Location = New-Object System.Drawing.Point(22, 198)
$card.Size = New-Object System.Drawing.Size(936, 518)
$card.BackColor = [System.Drawing.Color]::White
$card.BorderStyle = 'FixedSingle'
$form.Controls.Add($card)

$sectionLabel = New-Object System.Windows.Forms.Label
$sectionLabel.Text = 'Controls'
$sectionLabel.Font = New-Object System.Drawing.Font('Segoe UI', 11, [System.Drawing.FontStyle]::Bold)
$sectionLabel.AutoSize = $true
$sectionLabel.Location = New-Object System.Drawing.Point(22, 16)
$sectionLabel.ForeColor = [System.Drawing.ColorTranslator]::FromHtml('#222222')
$card.Controls.Add($sectionLabel)

$summaryLabel = New-Object System.Windows.Forms.Label
$summaryLabel.Text = 'Live Summary'
$summaryLabel.Font = New-Object System.Drawing.Font('Segoe UI', 11, [System.Drawing.FontStyle]::Bold)
$summaryLabel.AutoSize = $true
$summaryLabel.Location = New-Object System.Drawing.Point(652, 16)
$summaryLabel.ForeColor = [System.Drawing.ColorTranslator]::FromHtml('#222222')
$card.Controls.Add($summaryLabel)

$actions = @(
    @{ Label = 'Start'; X = 22; Y = 48; Action = 'start'; Tone = '#111111'; Fore = '#ffffff'; Width = 150 },
    @{ Label = 'Restart'; X = 192; Y = 48; Action = 'restart'; Tone = '#efe7d8'; Fore = '#111111'; Width = 150 },
    @{ Label = 'Stop'; X = 362; Y = 48; Action = 'stop'; Tone = '#f7d7d1'; Fore = '#722b1f'; Width = 150 },
    @{ Label = 'Open Logs'; X = 22; Y = 102; Action = 'open-logs'; Tone = '#efe7d8'; Fore = '#111111'; Width = 150 },
    @{ Label = 'Open Folder'; X = 192; Y = 102; Action = 'open-folder'; Tone = '#efe7d8'; Fore = '#111111'; Width = 150 },
    @{ Label = 'Package Zip'; X = 362; Y = 102; Action = 'package'; Tone = '#dbe9f1'; Fore = '#12384b'; Width = 150 },
    @{ Label = 'Shortcut'; X = 22; Y = 156; Action = 'create-shortcut'; Tone = '#efe7d8'; Fore = '#111111'; Width = 150 },
    @{ Label = 'Check Update'; X = 192; Y = 156; Action = 'check-update'; Tone = '#dbe9f1'; Fore = '#12384b'; Width = 150 },
    @{ Label = 'Update Now'; X = 362; Y = 156; Action = 'apply-update'; Tone = '#ddebdc'; Fore = '#214d27'; Width = 150 },
    @{ Label = 'Set Update Source'; X = 22; Y = 210; Action = 'set-update-manifest'; Tone = '#efe7d8'; Fore = '#111111'; Width = 220 },
    @{ Label = 'Install / Repair'; X = 262; Y = 210; Action = 'open-installer'; Tone = '#efe7d8'; Fore = '#111111'; Width = 160 },
    @{ Label = 'Uninstall'; X = 442; Y = 210; Action = 'uninstall'; Tone = '#f7d7d1'; Fore = '#722b1f'; Width = 150 }
)

$summaryBox = New-Object System.Windows.Forms.TextBox
$summaryBox.Location = New-Object System.Drawing.Point(652, 48)
$summaryBox.Size = New-Object System.Drawing.Size(252, 214)
$summaryBox.Multiline = $true
$summaryBox.ReadOnly = $true
$summaryBox.ScrollBars = 'Vertical'
$summaryBox.Font = New-Object System.Drawing.Font('Consolas', 9)
$summaryBox.BackColor = [System.Drawing.ColorTranslator]::FromHtml('#fbfaf7')
$summaryBox.ForeColor = [System.Drawing.ColorTranslator]::FromHtml('#222222')
$card.Controls.Add($summaryBox)

$outputLabel = New-Object System.Windows.Forms.Label
$outputLabel.Text = 'Action Output'
$outputLabel.Font = New-Object System.Drawing.Font('Segoe UI', 11, [System.Drawing.FontStyle]::Bold)
$outputLabel.AutoSize = $true
$outputLabel.Location = New-Object System.Drawing.Point(22, 286)
$outputLabel.ForeColor = [System.Drawing.ColorTranslator]::FromHtml('#222222')
$card.Controls.Add($outputLabel)

$statusBox = New-Object System.Windows.Forms.TextBox
$statusBox.Location = New-Object System.Drawing.Point(22, 318)
$statusBox.Size = New-Object System.Drawing.Size(882, 150)
$statusBox.Multiline = $true
$statusBox.ReadOnly = $true
$statusBox.ScrollBars = 'Vertical'
$statusBox.Font = New-Object System.Drawing.Font('Consolas', 10)
$statusBox.BackColor = [System.Drawing.ColorTranslator]::FromHtml('#fbfaf7')
$statusBox.ForeColor = [System.Drawing.ColorTranslator]::FromHtml('#222222')
$card.Controls.Add($statusBox)

$hint = New-Object System.Windows.Forms.Label
$hint.Text = 'This window is the local app entry point. Telegram is for remote operation; install, repair, packaging, and updates live here.'
$hint.Font = New-Object System.Drawing.Font('Segoe UI', 9)
$hint.AutoSize = $false
$hint.Size = New-Object System.Drawing.Size(882, 38)
$hint.Location = New-Object System.Drawing.Point(22, 476)
$hint.ForeColor = [System.Drawing.ColorTranslator]::FromHtml('#5f5a51')
$card.Controls.Add($hint)

function Refresh-StatusUi {
    param(
        [switch]$RefreshOutput
    )

    $status = Get-BridgeStatusObject
    if ($RefreshOutput -or [string]::IsNullOrWhiteSpace($statusBox.Text)) {
        $statusBox.Text = Invoke-BridgeAction -Action 'status'
    }
    $summaryBox.Text = Format-SummaryText $status
    $versionBadge.Text = ('v' + [string]$status.CurrentVersion)
    if ([bool]$status.ManualStop) {
        $stateBadge.Text = 'Stopped'
        $stateBadge.BackColor = [System.Drawing.ColorTranslator]::FromHtml('#f3ddd7')
        $stateBadge.ForeColor = [System.Drawing.ColorTranslator]::FromHtml('#7a2d21')
    } elseif ([int]$status.ProcessCount -gt 0) {
        $stateBadge.Text = 'Running'
        $stateBadge.BackColor = [System.Drawing.ColorTranslator]::FromHtml('#ddebdc')
        $stateBadge.ForeColor = [System.Drawing.ColorTranslator]::FromHtml('#214d27')
    } else {
        $stateBadge.Text = 'Stopped'
        $stateBadge.BackColor = [System.Drawing.ColorTranslator]::FromHtml('#f3ddd7')
        $stateBadge.ForeColor = [System.Drawing.ColorTranslator]::FromHtml('#7a2d21')
    }
    if ($status.UpdateManifestUrl) {
        $updateBadge.Text = 'Update source ready'
        $updateBadge.BackColor = [System.Drawing.ColorTranslator]::FromHtml('#ddebdc')
        $updateBadge.ForeColor = [System.Drawing.ColorTranslator]::FromHtml('#214d27')
    } else {
        $updateBadge.Text = 'No update source'
        $updateBadge.BackColor = [System.Drawing.ColorTranslator]::FromHtml('#2b2b2b')
        $updateBadge.ForeColor = [System.Drawing.ColorTranslator]::FromHtml('#d8d3ca')
    }
}

$invokeBridgeAction = ${function:Invoke-BridgeAction}
$getBridgeStatusObject = ${function:Get-BridgeStatusObject}
$openInstallerGui = ${function:Open-InstallerGui}
$refreshStatusUi = ${function:Refresh-StatusUi}
$uninstallScript = Join-Path $PSScriptRoot 'uninstall_bridge.ps1'

foreach ($entry in $actions) {
    $button = New-Object System.Windows.Forms.Button
    $button.Text = $entry.Label
    $button.Size = New-Object System.Drawing.Size($entry.Width, 42)
    $button.Location = New-Object System.Drawing.Point($entry.X, $entry.Y)
    $button.BackColor = [System.Drawing.ColorTranslator]::FromHtml($entry.Tone)
    $button.ForeColor = [System.Drawing.ColorTranslator]::FromHtml($entry.Fore)
    $button.FlatStyle = 'Flat'
    $button.FlatAppearance.BorderSize = 0
    $actionName = [string]$entry.Action
    $actionLabel = [string]$entry.Label
    $handler = {
        $form.UseWaitCursor = $true
        $statusBox.Text = ('Running: ' + $actionLabel + ' ...')
        [System.Windows.Forms.Application]::DoEvents()
        try {
            if ($actionName -eq 'open-installer') {
                & $openInstallerGui
                $lastAction.Text = ('Last action: ' + $actionLabel)
                $statusBox.Text = 'Opened the installer / repair wizard.'
                return
            }
            if ($actionName -eq 'uninstall') {
                $decision = [System.Windows.Forms.MessageBox]::Show(
                    'This will stop the bridge, remove startup integration, delete the desktop shortcut, and remove the installed folder. Continue?',
                    'Telegram Codex Bridge',
                    [System.Windows.Forms.MessageBoxButtons]::YesNo,
                    [System.Windows.Forms.MessageBoxIcon]::Warning
                )
                if ($decision -ne [System.Windows.Forms.DialogResult]::Yes) {
                    $statusBox.Text = 'Uninstall canceled.'
                    $lastAction.Text = 'Last action: Uninstall canceled'
                    return
                }
                Start-Process -FilePath 'powershell.exe' -ArgumentList @(
                    '-NoProfile',
                    '-ExecutionPolicy', 'Bypass',
                    '-File', $uninstallScript
                ) -WorkingDirectory $PSScriptRoot | Out-Null
                $statusBox.Text = 'Uninstall started. This control panel will now close.'
                $lastAction.Text = ('Last action: ' + $actionLabel)
                $form.Close()
                return
            }

            $result = $null
            if ($actionName -eq 'set-update-manifest') {
                $status = & $getBridgeStatusObject
                $input = [Microsoft.VisualBasic.Interaction]::InputBox('Paste the GitHub update manifest URL. Type CLEAR to remove it.', 'Set Update Source', [string]$status.UpdateManifestUrl)
                $normalized = $input.Trim()
                if ([string]::IsNullOrWhiteSpace($normalized)) {
                    $result = 'Update source unchanged.'
                } elseif ($normalized.ToUpperInvariant() -eq 'CLEAR') {
                    $result = & $invokeBridgeAction -Action $actionName -ManifestUrl ''
                } else {
                    $result = & $invokeBridgeAction -Action $actionName -ManifestUrl $normalized
                }
            } elseif ($actionName -eq 'check-update') {
                $json = & $invokeBridgeAction -Action $actionName
                try {
                    $update = $json | ConvertFrom-Json
                    $result = @(
                        ('Current version: ' + [string]$update.current_version),
                        ('Available version: ' + $(if ($update.available_version) { [string]$update.available_version } else { 'unknown' })),
                        ('Update available: ' + [string]$update.update_available),
                        ('Manifest: ' + $(if ($update.manifest_url) { [string]$update.manifest_url } else { 'not configured' })),
                        ('Package: ' + $(if ($update.package_url) { [string]$update.package_url } else { 'none' })),
                        ('Notes: ' + $(if ($update.notes_url) { [string]$update.notes_url } else { 'none' })),
                        ('Message: ' + [string]$update.message)
                    ) -join [Environment]::NewLine
                } catch {
                    $result = $json
                }
            } else {
                $result = & $invokeBridgeAction -Action $actionName
            }
            $lastAction.Text = ('Last action: ' + $actionLabel)
            if ($result) {
                $statusBox.Text = $result.Trim()
            }
        } catch {
            $statusBox.Text = $_.Exception.Message
            $lastAction.Text = ('Last action failed: ' + $actionLabel)
        } finally {
            $form.UseWaitCursor = $false
            & $refreshStatusUi
        }
    }.GetNewClosure()
    $button.Add_Click($handler)
    $card.Controls.Add($button)
}

$refreshButton = New-Object System.Windows.Forms.Button
$refreshButton.Text = 'Refresh'
$refreshButton.Size = New-Object System.Drawing.Size(100, 36)
$refreshButton.Location = New-Object System.Drawing.Point(804, 14)
$refreshButton.FlatStyle = 'Flat'
$refreshButton.Add_Click({ & $refreshStatusUi -RefreshOutput })
$card.Controls.Add($refreshButton)

$timer = New-Object System.Windows.Forms.Timer
$timer.Interval = 5000
$timer.Add_Tick({ & $refreshStatusUi })
$timer.Start()

& $refreshStatusUi -RefreshOutput
[void]$form.ShowDialog()



