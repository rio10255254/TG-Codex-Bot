# Telegram Codex Bridge

Use Telegram on your phone to chat with `codex exec` on this Windows machine.

## What it does

- Polls a Telegram bot with long polling
- Restricts access by Telegram chat ID
- Treats plain Telegram text like a normal Codex prompt
- Keeps one Codex conversation session per Telegram chat
- Streams progress messages back while Codex is working
- Returns the final Codex reply back to Telegram
- Writes local chat transcripts and session transcripts
- Maintains a bridge-side session history index
- Best-effort mirrors Telegram sessions into Codex history files
- Lets you list and cancel running jobs

## Files

- `bot.py`: main bridge process
- `.env.example`: config template
- `start_bot.ps1`: simple Windows launcher
- `bridge_control.ps1`: local start/stop/status helper
- `bridge_control_gui.ps1`: local Windows control panel UI
- `OPEN_TELEGRAM_CODEX_BRIDGE.cmd`: opens the local control panel
- `START_TELEGRAM_CODEX_BRIDGE.cmd`: one-click launcher entry
- `INSTALL_TELEGRAM_CODEX_BRIDGE.cmd`: one-click installer entry for packaged builds
- `install_bridge.ps1`: portable installer for a fresh Windows machine
- `build_portable_package.ps1`: creates a redistributable zip package
- `data/chat_state.json`: saved per-chat working directory and session ID
- `data/bridge_session_index.json`: bridge-side session index
- `data/chat_transcripts/<chat_id>.jsonl`: full Telegram transcript
- `data/session_transcripts/<session_id>.jsonl`: per-session transcript

## Setup

1. Create a Telegram bot with `@BotFather` and copy the bot token.
2. Copy `.env.example` to `.env`.
3. Fill in at least:

```env
TELEGRAM_BOT_TOKEN=123456:replace-me
TELEGRAM_ALLOWED_CHAT_IDS=
CODEX_DEFAULT_CWD=C:\Users\YourName\Projects
```

4. Start the bot:

```powershell
cd C:\Users\YourName\telegram_codex_bridge
.\OPEN_TELEGRAM_CODEX_BRIDGE.cmd
```

5. Open Telegram and send your bot `/start`.
6. If no allowlist is configured yet, the first Telegram chat can claim the bridge directly from Telegram without editing local files.

Example:

```env
TELEGRAM_ALLOWED_CHAT_IDS=123456789
```

After the first admin chat is authorized, it can add more Telegram users without editing `.env`:

```text
/allow 123456789
/revoke 123456789
```

## Commands

- Plain text: send it directly to Codex as a normal prompt
- `/run <prompt>`: send a prompt explicitly
- `/cd <path>`: change the working directory for this Telegram chat
- `/pwd`: show the current working directory
- `/session`: show the current Codex session ID
- `/menu`: resend the quick keyboard and menu summary
- `/projects`: open the project picker
- `/sessions`: open the unified conversation picker for TG + local Codex desktop sessions
- `/use <history_index|session_id>`: switch the active session for this chat
- `/title <name>`: rename the active session to a human-friendly title
- `/new`: clear the current Codex session and start fresh next time
- `/status`: show the current bot and Codex settings
- `/where`: show the current cwd, session, and transcript paths
- `/jobs`: show recent jobs
- `/cancel <job_id>`: stop a running job
- `/history [N|all]`: show bridge session history
- `/transcript [session_id]`: show transcript file locations
- `/id`: show your Telegram chat ID
- `/help`: show command help

The bot also sends a persistent Telegram keyboard with the most common commands, so you can tap instead of typing for project selection, conversation switching, status, and reset actions.
The `Chats` view merges Telegram-created conversations with local Codex desktop sessions from CLI / VSCode when their local session metadata is available.

## Portable Install

If you want a version that can be copied to another Windows machine:

1. Run:

```powershell
powershell -ExecutionPolicy Bypass -File .\build_portable_package.ps1
```

2. This creates the single release zip in `_發布封包\GitHub_可發佈版.zip`.
3. Copy that zip to the target machine and extract it.
4. Double-click `INSTALL_TELEGRAM_CODEX_BRIDGE.cmd`.
5. The installer copies the bridge, creates `.env`, auto-checks dependencies, can auto-install Python / Node.js / Codex, registers Task Scheduler, and creates a desktop shortcut.

What the target machine still needs:

- A Telegram bot token from `@BotFather`
- A real `CODEX_DEFAULT_CWD`

The installer now tries to auto-install these if they are missing:

- Python 3.12 via `winget`
- Node.js LTS via `winget`
- Codex CLI via `npm install -g @openai/codex`

After install, the obvious local entry is:

- desktop shortcut: `Telegram Codex Bridge`
- file: `OPEN_TELEGRAM_CODEX_BRIDGE.cmd`

That opens the local control panel UI, so users can start, stop, restart, inspect logs, and rebuild the package without opening scripts or editing files manually.

Recommended model for formal use:

- Each person should use their own Telegram bot token and their own machine.
- If multiple people must share one machine, the first admin chat can authorize more people later with `/allow <chat_id>`.

## Example usage

```text
/cd C:\Users\YourName\my-project
先讀一下這個 repo，告訴我目前有哪些主要模組。
```

Then continue naturally:

```text
幫我修掉登入流程的 bug，改完後跑測試。
```

If you want a clean conversation reset:

```text
/new
從頭重新分析這個專案。
```

Switch back to an older thread later:

```text
/history
/use 2
```

## Recommended `.env` defaults

```env
TELEGRAM_PROJECTS=ProjectA=D:\YourProject;Bridge=C:\Users\YourName\telegram_codex_bridge
CODEX_SANDBOX=danger-full-access
CODEX_APPROVAL_POLICY=never
CODEX_TIMEOUT_SECONDS=1800
MAX_CONCURRENT_JOBS=2
HEARTBEAT_SECONDS=25
```

`TELEGRAM_PROJECTS` is optional. Those entries are pinned at the top of `/projects`, and the bot fills the rest of the menu with recently used project folders from this chat.

`CODEX_APPROVAL_POLICY=never` is practical for unattended bot use, but it means Codex cannot pause and ask for permission mid-run. Keep the bot chat allowlist tight.
`CODEX_SANDBOX=danger-full-access` makes Telegram runs much closer to desktop Codex behavior, but it also gives the bot full machine access.

## Live feedback model

The bridge runs `codex exec --json` and forwards these events back to Telegram:

- Commentary updates from Codex while it is thinking and exploring
- Tool activity such as shell commands and web searches
- A heartbeat message if the task is still running quietly
- The final answer when the run completes

This is close to the normal Codex CLI feel, but Telegram is still a message app, so it does not render the terminal UI itself.
The bridge can now adopt existing local Codex sessions, so continuing a VSCode / CLI conversation from Telegram resumes the same session id even though Telegram is not a literal terminal emulator.

## History and transcripts

- `/where` shows the active cwd, session ID, and transcript files
- `/history` shows the unified session list for this Telegram chat, including adoptable local Codex sessions when available
- `/transcript` shows the absolute paths of the local transcript files
- The bridge also tries to append Telegram-created sessions to `.codex/session_index.jsonl` and `.codex/history.jsonl`
- If those Codex files are locked or read-only, the bridge keeps working and only logs the sync skip in `data/bot.err.log`

## Task Scheduler

If you want the bridge to start automatically on Windows:

- Program/script: `powershell.exe`
- Arguments: `-ExecutionPolicy Bypass -File C:\Users\YourName\telegram_codex_bridge\start_bot.ps1`
- Start in: `C:\Users\YourName\telegram_codex_bridge`

The packaged installer can register the same task automatically, with failure retry enabled.
The desktop shortcut opens the local control panel UI instead of silently starting the bot in the background.

## Built-in updates

If you want installed copies to follow GitHub releases:

1. Publish `_發布封包\GitHub_可發佈版.zip` to GitHub Releases.
2. Publish a manifest JSON based on `_開發者文件\UPDATE_MANIFEST_TEMPLATE.json`.
3. Put that manifest URL into the installer or local control panel.
4. Users can then click `Check Update` or `Update Now` from the local control panel.

The updater reinstalls over the same folder while preserving local `.env.local` and `data`.

## Notes

- This bridge uses the Telegram Bot HTTP API directly and does not require extra Python packages.
- The bot runs on your local machine. If your PC sleeps or shuts down, the bridge stops.
- If `codex` is not on `PATH`, the bridge will fail at startup.
- `OPEN_TELEGRAM_CODEX_BRIDGE.cmd` is the obvious local launcher entry; the desktop shortcut points to it.
