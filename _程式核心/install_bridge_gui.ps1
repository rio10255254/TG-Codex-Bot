param()

$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

$installScript = Join-Path $PSScriptRoot 'install_bridge.ps1'
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

function Normalize-BotToken([string]$Value) {
    return ([string]$Value -replace '\s', '').Trim()
}

function Test-BotTokenLooksValid([string]$Value) {
    return [bool]([string]$Value -match '^\d{6,}:[A-Za-z0-9_-]{30,}$')
}

function Start-InstallProcess {
    param(
        [string]$InstallDir,
        [string]$BotToken,
        [string]$AllowedChatIds,
        [string]$DefaultCwd,
        [string]$TelegramProjects,
        [string]$UpdateManifestUrl,
        [bool]$AutoInstallDependencies,
        [bool]$RegisterTask,
        [bool]$CreateDesktopShortcut,
        [bool]$StartNow
    )

    $payload = [ordered]@{
        InstallScript = $installScript
        InstallDir = $InstallDir
        BotToken = $BotToken
        AllowedChatIds = $AllowedChatIds
        DefaultCwd = $DefaultCwd
        TelegramProjects = $TelegramProjects
        UpdateManifestUrl = $UpdateManifestUrl
        AutoInstallDependencies = $AutoInstallDependencies
        RegisterTask = $RegisterTask
        CreateDesktopShortcut = $CreateDesktopShortcut
        StartNow = $StartNow
    }
    $payloadJson = $payload | ConvertTo-Json -Depth 5 -Compress
    $launcherLines = @(
        '$ErrorActionPreference = ''Stop'''
        "`$payload = @'"
        $payloadJson
        "'@ | ConvertFrom-Json"
        '$params = @{'
        '    InstallDir = [string]$payload.InstallDir'
        '    BotToken = [string]$payload.BotToken'
        '    AllowedChatIds = [string]$payload.AllowedChatIds'
        '    DefaultCwd = [string]$payload.DefaultCwd'
        '    TelegramProjects = [string]$payload.TelegramProjects'
        '    UpdateManifestUrl = [string]$payload.UpdateManifestUrl'
        '    AutoInstallDependencies = [bool]$payload.AutoInstallDependencies'
        '    RegisterTask = [bool]$payload.RegisterTask'
        '    CreateDesktopShortcut = [bool]$payload.CreateDesktopShortcut'
        '    StartNow = [bool]$payload.StartNow'
        '}'
        '& ([string]$payload.InstallScript) @params'
    )
    $launcherScript = $launcherLines -join "`r`n"
    $encodedLauncher = [Convert]::ToBase64String([System.Text.Encoding]::Unicode.GetBytes($launcherScript))

    try {
        $outputLines = [System.Collections.ArrayList]::Synchronized((New-Object System.Collections.ArrayList))
        $psi = New-Object System.Diagnostics.ProcessStartInfo
        $psi.FileName = 'powershell.exe'
        $psi.Arguments = ('-NoProfile -ExecutionPolicy Bypass -OutputFormat Text -EncodedCommand ' + $encodedLauncher)
        $psi.UseShellExecute = $false
        $psi.CreateNoWindow = $true
        $psi.RedirectStandardOutput = $true
        $psi.RedirectStandardError = $true

        $proc = New-Object System.Diagnostics.Process
        $proc.StartInfo = $psi
        $null = Register-ObjectEvent -InputObject $proc -EventName OutputDataReceived -Action {
            if ($EventArgs.Data -ne $null) {
                [void]$Event.MessageData.Add($EventArgs.Data)
            }
        } -MessageData $outputLines
        $null = Register-ObjectEvent -InputObject $proc -EventName ErrorDataReceived -Action {
            if ($EventArgs.Data -ne $null) {
                [void]$Event.MessageData.Add($EventArgs.Data)
            }
        } -MessageData $outputLines
        $null = $proc.Start()
        $proc.BeginOutputReadLine()
        $proc.BeginErrorReadLine()
    } catch {
        throw
    }

    return [pscustomobject]@{
        Process = $proc
        OutputLines = $outputLines
    }
}

function Read-InstallOutput {
    param(
        [Parameter(Mandatory = $true)]
        [pscustomobject]$InstallRun
    )

    if (-not $InstallRun.OutputLines) {
        return ''
    }
    $snapshot = $InstallRun.OutputLines.ToArray()
    $lines = foreach ($line in $snapshot) {
        if ($null -eq $line) {
            continue
        }
        $text = [string]$line
        if ($text -eq '#< CLIXML') {
            continue
        }
        if ($text -like '<Objs *') {
            continue
        }
        $text
    }
    return ((@($lines) -join "`r`n")).Trim()
}

function Wait-InstallOutputSettled {
    param(
        [Parameter(Mandatory = $true)]
        [pscustomobject]$InstallRun,
        [int]$MaxWaitMilliseconds = 2000,
        [int]$StableChecks = 5
    )

    $lastCount = -1
    $stable = 0
    $deadline = [DateTime]::UtcNow.AddMilliseconds($MaxWaitMilliseconds)
    while ([DateTime]::UtcNow -lt $deadline) {
        $currentCount = $InstallRun.OutputLines.Count
        if ($currentCount -eq $lastCount) {
            $stable += 1
            if ($stable -ge $StableChecks) {
                break
            }
        } else {
            $stable = 0
            $lastCount = $currentCount
        }
        Start-Sleep -Milliseconds 120
    }
}

function Cleanup-InstallProcess {
    param(
        [Parameter(Mandatory = $true)]
        [pscustomobject]$InstallRun
    )

    Get-EventSubscriber | Where-Object {
        $_.SourceObject -eq $InstallRun.Process
    } | Unregister-Event -Force -ErrorAction SilentlyContinue

    if ($InstallRun.Process) {
        try {
            $InstallRun.Process.CancelOutputRead()
        } catch {
        }
        try {
            $InstallRun.Process.CancelErrorRead()
        } catch {
        }
        try {
            $InstallRun.Process.Dispose()
        } catch {
        }
    }
}

$form = New-Object System.Windows.Forms.Form
$form.Text = 'Telegram Codex Bridge Installer'
$form.Size = New-Object System.Drawing.Size(880, 840)
$form.StartPosition = 'CenterScreen'
$form.BackColor = [System.Drawing.ColorTranslator]::FromHtml('#f5f1e8')
$form.FormBorderStyle = 'FixedDialog'
$form.MaximizeBox = $false

if (Test-Path $iconPath) {
    $form.Icon = New-Object System.Drawing.Icon($iconPath)
}

$header = New-Object System.Windows.Forms.Panel
$header.Location = New-Object System.Drawing.Point(0, 0)
$header.Size = New-Object System.Drawing.Size(880, 150)
$header.BackColor = [System.Drawing.ColorTranslator]::FromHtml('#111111')
$form.Controls.Add($header)

if (Test-Path $heroPath) {
    $hero = New-Object System.Windows.Forms.PictureBox
    $hero.Location = New-Object System.Drawing.Point(24, 18)
    $hero.Size = New-Object System.Drawing.Size(106, 106)
    $hero.SizeMode = 'Zoom'
    $hero.Image = Load-ImageCopy $heroPath
    $header.Controls.Add($hero)
}

$title = New-Object System.Windows.Forms.Label
$title.Text = 'Telegram Codex Bridge Setup'
$title.Font = New-Object System.Drawing.Font('Bahnschrift', 24, [System.Drawing.FontStyle]::Bold)
$title.AutoSize = $true
$title.Location = New-Object System.Drawing.Point(150, 28)
$title.ForeColor = [System.Drawing.Color]::White
$header.Controls.Add($title)

$subtitle = New-Object System.Windows.Forms.Label
$subtitle.Text = 'Fill in your bot token and paths, then install. No manual file editing required.'
$subtitle.Font = New-Object System.Drawing.Font('Segoe UI', 10)
$subtitle.AutoSize = $true
$subtitle.Location = New-Object System.Drawing.Point(153, 76)
$subtitle.ForeColor = [System.Drawing.ColorTranslator]::FromHtml('#d8d3ca')
$header.Controls.Add($subtitle)

$panel = New-Object System.Windows.Forms.Panel
$panel.Location = New-Object System.Drawing.Point(22, 170)
$panel.Size = New-Object System.Drawing.Size(836, 610)
$panel.BackColor = [System.Drawing.Color]::White
$panel.BorderStyle = 'FixedSingle'
$panel.AutoScroll = $true
$form.Controls.Add($panel)

function Add-Field {
    param(
        [string]$Label,
        [int]$Y,
        [string]$DefaultValue = '',
        [switch]$Wide
    )
    $fieldLabel = New-Object System.Windows.Forms.Label
    $fieldLabel.Text = $Label
    $fieldLabel.Location = New-Object System.Drawing.Point(20, $Y)
    $fieldLabel.Size = New-Object System.Drawing.Size(240, 24)
    $fieldLabel.Font = New-Object System.Drawing.Font('Segoe UI', 10, [System.Drawing.FontStyle]::Bold)
    $panel.Controls.Add($fieldLabel)

    $fieldTextBox = New-Object System.Windows.Forms.TextBox
    $fieldTextBox.Location = New-Object System.Drawing.Point(20, ($Y + 28))
    $fieldTextBox.Size = New-Object System.Drawing.Size($(if ($Wide) { 780 } else { 620 }), 28)
    $fieldTextBox.Text = $DefaultValue
    $panel.Controls.Add($fieldTextBox)
    return $fieldTextBox
}

$tokenBox = Add-Field -Label 'Telegram bot token' -Y 20
$installDirBox = Add-Field -Label 'Install folder' -Y 90 -DefaultValue (Join-Path $env:USERPROFILE 'telegram_codex_bridge') -Wide
$cwdBox = Add-Field -Label 'Default Codex working directory' -Y 160 -DefaultValue $env:USERPROFILE -Wide
$allowedBox = Add-Field -Label 'Allowed chat IDs (optional, comma-separated)' -Y 230 -Wide
$projectsBox = Add-Field -Label 'Pinned projects (optional, name=path;name=path)' -Y 300 -Wide
$updateBox = Add-Field -Label 'GitHub update manifest URL (optional)' -Y 370 -Wide

$autoDeps = New-Object System.Windows.Forms.CheckBox
$autoDeps.Text = 'Auto-install Python / Node.js / Codex if missing'
$autoDeps.Location = New-Object System.Drawing.Point(24, 450)
$autoDeps.Size = New-Object System.Drawing.Size(360, 24)
$autoDeps.Checked = $true
$panel.Controls.Add($autoDeps)

$registerTask = New-Object System.Windows.Forms.CheckBox
$registerTask.Text = 'Register auto-start task'
$registerTask.Location = New-Object System.Drawing.Point(24, 480)
$registerTask.Size = New-Object System.Drawing.Size(240, 24)
$registerTask.Checked = $true
$panel.Controls.Add($registerTask)

$desktopShortcut = New-Object System.Windows.Forms.CheckBox
$desktopShortcut.Text = 'Create desktop shortcut'
$desktopShortcut.Location = New-Object System.Drawing.Point(290, 480)
$desktopShortcut.Size = New-Object System.Drawing.Size(240, 24)
$desktopShortcut.Checked = $true
$panel.Controls.Add($desktopShortcut)

$startNow = New-Object System.Windows.Forms.CheckBox
$startNow.Text = 'Start bridge after install'
$startNow.Location = New-Object System.Drawing.Point(550, 480)
$startNow.Size = New-Object System.Drawing.Size(220, 24)
$startNow.Checked = $true
$panel.Controls.Add($startNow)

$statusBox = New-Object System.Windows.Forms.TextBox
$statusBox.Location = New-Object System.Drawing.Point(20, 518)
$statusBox.Size = New-Object System.Drawing.Size(780, 88)
$statusBox.Multiline = $true
$statusBox.ScrollBars = 'Both'
$statusBox.ReadOnly = $true
$statusBox.BackColor = [System.Drawing.ColorTranslator]::FromHtml('#fbfaf7')
$statusBox.Font = New-Object System.Drawing.Font('Consolas', 9)
$statusBox.WordWrap = $false
$statusBox.HideSelection = $false
$panel.Controls.Add($statusBox)

$activeInstall = $null
$lastStatusSnapshot = ''

$installButton = New-Object System.Windows.Forms.Button
$installButton.Text = 'Install Now'
$installButton.Size = New-Object System.Drawing.Size(160, 42)
$installButton.Location = New-Object System.Drawing.Point(640, 20)
$installButton.BackColor = [System.Drawing.ColorTranslator]::FromHtml('#111111')
$installButton.ForeColor = [System.Drawing.Color]::White
$installButton.FlatStyle = 'Flat'
$panel.Controls.Add($installButton)

$browseInstall = New-Object System.Windows.Forms.Button
$browseInstall.Text = 'Browse'
$browseInstall.Size = New-Object System.Drawing.Size(110, 30)
$browseInstall.Location = New-Object System.Drawing.Point(690, 118)
$panel.Controls.Add($browseInstall)

$browseCwd = New-Object System.Windows.Forms.Button
$browseCwd.Text = 'Browse'
$browseCwd.Size = New-Object System.Drawing.Size(110, 30)
$browseCwd.Location = New-Object System.Drawing.Point(690, 188)
$panel.Controls.Add($browseCwd)

$hint = New-Object System.Windows.Forms.Label
$hint.Text = 'Leave chat IDs blank if you want the first Telegram user to claim the bridge directly from Telegram.'
$hint.Location = New-Object System.Drawing.Point(20, 422)
$hint.Size = New-Object System.Drawing.Size(780, 20)
$hint.ForeColor = [System.Drawing.ColorTranslator]::FromHtml('#6c665d')
$panel.Controls.Add($hint)

$folderBrowser = New-Object System.Windows.Forms.FolderBrowserDialog

$browseInstall.Add_Click({
    if ($folderBrowser.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) {
        $installDirBox.Text = $folderBrowser.SelectedPath
    }
})

$browseCwd.Add_Click({
    if ($folderBrowser.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) {
        $cwdBox.Text = $folderBrowser.SelectedPath
    }
})

$installButton.Add_Click({
    $normalizedToken = Normalize-BotToken $tokenBox.Text
    $tokenBox.Text = $normalizedToken
    if ([string]::IsNullOrWhiteSpace($normalizedToken)) {
        [System.Windows.Forms.MessageBox]::Show('Please enter a Telegram bot token.', 'Missing Token')
        return
    }
    if (-not (Test-BotTokenLooksValid $normalizedToken)) {
        [System.Windows.Forms.MessageBox]::Show('Telegram bot token looks invalid. Paste the full token from @BotFather without spaces or line breaks.', 'Invalid Token')
        return
    }
    if ([string]::IsNullOrWhiteSpace($installDirBox.Text)) {
        [System.Windows.Forms.MessageBox]::Show('Please choose an install folder.', 'Missing Install Folder')
        return
    }
    if ([string]::IsNullOrWhiteSpace($cwdBox.Text)) {
        [System.Windows.Forms.MessageBox]::Show('Please choose a default working directory.', 'Missing Working Directory')
        return
    }

    $installButton.Enabled = $false
    $form.UseWaitCursor = $true
    $lastStatusSnapshot = ''
    $statusBox.Text = "Installing bridge...`r`nLive output will appear here.`r`nThis may take a while if dependencies need to be installed."
    try {
        $activeInstall = Start-InstallProcess -InstallDir $installDirBox.Text -BotToken $normalizedToken -AllowedChatIds $allowedBox.Text -DefaultCwd $cwdBox.Text -TelegramProjects $projectsBox.Text -UpdateManifestUrl $updateBox.Text -AutoInstallDependencies $autoDeps.Checked -RegisterTask $registerTask.Checked -CreateDesktopShortcut $desktopShortcut.Checked -StartNow $startNow.Checked
        while (-not $activeInstall.Process.HasExited) {
            $snapshot = Read-InstallOutput -InstallRun $activeInstall
            if ($snapshot -and $snapshot -ne $lastStatusSnapshot) {
                $statusBox.Text = $snapshot
                $statusBox.SelectionStart = $statusBox.TextLength
                $statusBox.ScrollToCaret()
                $lastStatusSnapshot = $snapshot
            }
            [System.Windows.Forms.Application]::DoEvents()
            Start-Sleep -Milliseconds 200
        }

        $activeInstall.Process.WaitForExit()
        Wait-InstallOutputSettled -InstallRun $activeInstall
        $finalSnapshot = Read-InstallOutput -InstallRun $activeInstall
        if ($finalSnapshot) {
            $statusBox.Text = $finalSnapshot
            $statusBox.SelectionStart = $statusBox.TextLength
            $statusBox.ScrollToCaret()
            $lastStatusSnapshot = $finalSnapshot
        }
        $exitCode = $activeInstall.Process.ExitCode
        if ($exitCode -eq 0) {
            [System.Windows.Forms.MessageBox]::Show('Install completed.', 'Telegram Codex Bridge')
        } else {
            [System.Windows.Forms.MessageBox]::Show('Install finished with errors. Check the output box.', 'Telegram Codex Bridge')
        }
    } catch {
        $statusBox.Text = $_.Exception.Message
        [System.Windows.Forms.MessageBox]::Show('Failed to start install. Check the output box.', 'Telegram Codex Bridge')
    } finally {
        if ($activeInstall) {
            Cleanup-InstallProcess -InstallRun $activeInstall
            $activeInstall = $null
        }
        $form.UseWaitCursor = $false
        $installButton.Enabled = $true
    }
})

[void]$form.ShowDialog()





