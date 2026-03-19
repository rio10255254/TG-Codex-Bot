from __future__ import annotations

import json
import os
import queue
import re
import shlex
import shutil
import subprocess
import sys
import threading
import time
import traceback
import uuid
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from io import BytesIO
from mimetypes import guess_type
from pathlib import Path
from typing import Any, Optional


BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
CHAT_STATE_PATH = DATA_DIR / "chat_state.json"
BRIDGE_INDEX_PATH = DATA_DIR / "bridge_session_index.json"
RUNTIME_CONFIG_PATH = DATA_DIR / "runtime_config.json"
CHAT_TRANSCRIPTS_DIR = DATA_DIR / "chat_transcripts"
SESSION_TRANSCRIPTS_DIR = DATA_DIR / "session_transcripts"
CODEX_HOME = Path.home() / ".codex"
CODEX_SESSIONS_DIR = CODEX_HOME / "sessions"
CODEX_SESSION_INDEX_PATH = CODEX_HOME / "session_index.jsonl"
CODEX_HISTORY_PATH = CODEX_HOME / "history.jsonl"
MAX_TELEGRAM_MESSAGE = 3500
RECENT_JOB_LIMIT = 20
MAX_PROJECT_CHOICES = 24
MAX_SESSION_CHOICES = 30
PROJECTS_PAGE_SIZE = 5
SESSIONS_PAGE_SIZE = 5
TELEGRAM_ALLOWED_UPDATES = ["message", "edited_message", "callback_query"]
REPLY_KEYBOARD_VERSION = 2
MENU_HOME_COMMAND = "/menu"
MENU_PROJECTS_COMMAND = "/projects"
MENU_SESSIONS_COMMAND = "/sessions"
MENU_NEW_COMMAND = "/new"
MENU_STATUS_COMMAND = "/status"
MENU_WHERE_COMMAND = "/where"
MENU_HELP_COMMAND = "/help"
MENU_CANCEL_COMMAND = "/cancel_current"
MENU_HOME_LABEL = "Menu"
MENU_PROJECTS_LABEL = "Projects"
MENU_SESSIONS_LABEL = "Chats"
MENU_NEW_LABEL = "New Chat"
MENU_STATUS_LABEL = "Status"
MENU_WHERE_LABEL = "Where"
MENU_HELP_LABEL = "Help"
MENU_CANCEL_LABEL = "Cancel Job"
ROLLOUT_FILENAME_PATTERN = re.compile(r"rollout-.*-([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}|test-session)\.jsonl$", re.IGNORECASE)
WELCOME_IMAGE_PATH = BASE_DIR / "assets" / "codex_welcome.png"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def local_now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def parse_iso_timestamp(raw: str) -> Optional[datetime]:
    text = str(raw or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def human_timestamp(raw: str) -> str:
    parsed = parse_iso_timestamp(raw)
    if not parsed:
        return "(unknown)"
    return parsed.astimezone().strftime("%Y-%m-%d %H:%M")


def relative_age_text(raw: str) -> str:
    parsed = parse_iso_timestamp(raw)
    if not parsed:
        return "(unknown)"
    delta = datetime.now(timezone.utc) - parsed.astimezone(timezone.utc)
    seconds = max(0, int(delta.total_seconds()))
    if seconds < 60:
        return "just now"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes}m ago"
    hours = minutes // 60
    if hours < 24:
        return f"{hours}h ago"
    days = hours // 24
    return f"{days}d ago"


def duration_text(seconds_value: float) -> str:
    seconds = max(0, int(seconds_value))
    if seconds < 60:
        return f"{seconds}s"
    minutes, seconds = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes}m {seconds}s"
    hours, minutes = divmod(minutes, 60)
    if hours < 24:
        return f"{hours}h {minutes}m"
    days, hours = divmod(hours, 24)
    return f"{days}d {hours}h"


def load_dotenv(path: Path) -> dict[str, str]:
    env: dict[str, str] = {}
    if path.exists():
        for raw_line in path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            env[key.strip()] = value.strip()
    for key, value in os.environ.items():
        env[key] = value
    return env


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except Exception:
        return default


def save_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)


def append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


def parse_allowed_chat_ids(raw: str) -> set[str]:
    return {item.strip() for item in raw.split(",") if item.strip()}


def parse_project_shortcuts(raw: str) -> list[tuple[str, str]]:
    shortcuts: list[tuple[str, str]] = []
    for raw_item in raw.split(";"):
        item = raw_item.strip()
        if not item:
            continue
        name, separator, value = item.partition("=")
        path = value.strip() if separator else item
        if not path:
            continue
        label = name.strip() if separator else ""
        if not label:
            label = Path(path).name or path
        shortcuts.append((label, path))
    return shortcuts


def preview_text(text: str, limit: int = 80) -> str:
    cleaned = " ".join(text.strip().split())
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 3] + "..."


def derive_title(text: str, fallback: str = "Telegram session") -> str:
    cleaned = " ".join(text.strip().split())
    if not cleaned:
        return fallback
    return cleaned[:80]


def is_placeholder_title(title: str) -> bool:
    normalized = (title or "").strip().lower()
    return normalized in {"", "telegram session", "recovered telegram session", "(untitled)", "(unknown)"}


def split_message(text: str, limit: int = MAX_TELEGRAM_MESSAGE) -> list[str]:
    if len(text) <= limit:
        return [text]
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0
    for line in text.splitlines(keepends=True):
        if len(line) > limit:
            if current:
                chunks.append("".join(current).rstrip())
                current = []
                current_len = 0
            start = 0
            while start < len(line):
                chunks.append(line[start : start + limit].rstrip())
                start += limit
            continue
        if current_len + len(line) > limit and current:
            chunks.append("".join(current).rstrip())
            current = [line]
            current_len = len(line)
        else:
            current.append(line)
            current_len += len(line)
    if current:
        chunks.append("".join(current).rstrip())
    return [chunk if chunk else " " for chunk in chunks]


@dataclass
class Config:
    telegram_bot_token: str
    allowed_chat_ids: set[str]
    default_cwd: str
    telegram_projects: list[tuple[str, str]]
    codex_model: str
    codex_profile: str
    codex_sandbox: str
    codex_approval_policy: str
    codex_timeout_seconds: int
    telegram_poll_timeout_seconds: int
    max_concurrent_jobs: int
    heartbeat_seconds: int
    codex_extra_args: list[str]

    @classmethod
    def from_env(cls, env: dict[str, str]) -> "Config":
        def int_value(key: str, default: int) -> int:
            try:
                return int(env.get(key, default))
            except ValueError:
                return default

        return cls(
            telegram_bot_token=env.get("TELEGRAM_BOT_TOKEN", "").strip(),
            allowed_chat_ids=parse_allowed_chat_ids(env.get("TELEGRAM_ALLOWED_CHAT_IDS", "")),
            default_cwd=env.get("CODEX_DEFAULT_CWD", str(Path.home())).strip() or str(Path.home()),
            telegram_projects=parse_project_shortcuts(env.get("TELEGRAM_PROJECTS", "").strip()),
            codex_model=env.get("CODEX_MODEL", "").strip(),
            codex_profile=env.get("CODEX_PROFILE", "").strip(),
            codex_sandbox=env.get("CODEX_SANDBOX", "workspace-write").strip(),
            codex_approval_policy=env.get("CODEX_APPROVAL_POLICY", "never").strip(),
            codex_timeout_seconds=int_value("CODEX_TIMEOUT_SECONDS", 1800),
            telegram_poll_timeout_seconds=int_value("TELEGRAM_POLL_TIMEOUT_SECONDS", 30),
            max_concurrent_jobs=max(1, int_value("MAX_CONCURRENT_JOBS", 2)),
            heartbeat_seconds=max(5, int_value("HEARTBEAT_SECONDS", 25)),
            codex_extra_args=shlex.split(env.get("CODEX_EXTRA_ARGS", "").strip()),
        )


@dataclass
class Job:
    job_id: int
    chat_id: str
    prompt: str
    cwd: str
    session_mode: str
    prior_session_id: Optional[str]
    started_at: float = field(default_factory=time.time)
    process: Optional[subprocess.Popen[str]] = None
    status: str = "running"
    final_session_id: Optional[str] = None
    result_text: str = ""
    stderr_lines: list[str] = field(default_factory=list)
    error_text: str = ""
    visible_update_count: int = 0
    timed_out: bool = False
    canceled: bool = False
    prompt_logged: bool = False
    prompt_title: str = ""
    pending_agent_message: str = ""
    result_logged: bool = False
    last_stage: str = "Preparing task"
    last_event_at: float = field(default_factory=time.time)
    completed_at: Optional[float] = None
    last_progress_text: str = ""
    last_progress_sent_at: float = 0.0
    pending_progress_text: str = ""


class TelegramCodexBridge:
    def __init__(self, config: Config) -> None:
        self.config = config
        self.state_lock = threading.RLock()
        self.jobs_lock = threading.RLock()
        self.chat_state: dict[str, dict[str, Any]] = load_json(CHAT_STATE_PATH, {})
        self.bridge_index: dict[str, dict[str, Any]] = load_json(BRIDGE_INDEX_PATH, {})
        self.runtime_config: dict[str, Any] = load_json(RUNTIME_CONFIG_PATH, {})
        self.codex_index_ids = self._load_codex_session_ids()
        self.active_jobs: dict[int, Job] = {}
        self.chat_running_jobs: dict[str, int] = {}
        self.recent_jobs: list[Job] = []
        self.next_job_id = 1
        self.telegram_offset = 0
        self.codex_cmd = self._resolve_codex_cmd()
        self.rollout_path_cache: dict[str, str] = {}
        self.rollout_path_cache_at = 0.0

        DATA_DIR.mkdir(parents=True, exist_ok=True)
        CHAT_TRANSCRIPTS_DIR.mkdir(parents=True, exist_ok=True)
        SESSION_TRANSCRIPTS_DIR.mkdir(parents=True, exist_ok=True)
        self._bootstrap_existing_sessions()

    def _runtime_allowed_chat_ids(self) -> set[str]:
        values = self.runtime_config.get("allowed_chat_ids")
        if not isinstance(values, list):
            return set()
        return {str(item).strip() for item in values if str(item).strip()}

    def _runtime_admin_chat_ids(self) -> set[str]:
        values = self.runtime_config.get("admin_chat_ids")
        if not isinstance(values, list):
            return set()
        return {str(item).strip() for item in values if str(item).strip()}

    def _save_runtime_config(self) -> None:
        save_json(RUNTIME_CONFIG_PATH, self.runtime_config)

    def _add_runtime_allowed_chat(self, chat_id: str, *, admin: bool = False) -> None:
        allowed = sorted(self._runtime_allowed_chat_ids() | {chat_id})
        self.runtime_config["allowed_chat_ids"] = allowed
        if admin:
            admins = sorted(self._runtime_admin_chat_ids() | {chat_id})
            self.runtime_config["admin_chat_ids"] = admins
        self._save_runtime_config()

    def _remove_runtime_allowed_chat(self, chat_id: str) -> None:
        allowed = {item for item in self._runtime_allowed_chat_ids() if item != chat_id}
        admins = {item for item in self._runtime_admin_chat_ids() if item != chat_id}
        self.runtime_config["allowed_chat_ids"] = sorted(allowed)
        self.runtime_config["admin_chat_ids"] = sorted(admins)
        self._save_runtime_config()

    def _resolve_codex_cmd(self) -> Path:
        candidates = [
            shutil.which("codex.cmd"),
            shutil.which("codex"),
            str(Path.home() / "AppData" / "Roaming" / "npm" / "codex.cmd"),
        ]
        for candidate in candidates:
            if not candidate:
                continue
            path = Path(candidate)
            if path.exists():
                return path
        raise FileNotFoundError("Could not locate codex or codex.cmd on PATH.")

    def _load_codex_session_ids(self) -> set[str]:
        session_ids: set[str] = set()
        if CODEX_SESSION_INDEX_PATH.exists():
            for raw in CODEX_SESSION_INDEX_PATH.read_text(encoding="utf-8", errors="replace").splitlines():
                try:
                    payload = json.loads(raw)
                except Exception:
                    continue
                session_id = str(payload.get("id", "")).strip()
                if session_id:
                    session_ids.add(session_id)
        return session_ids

    def _bootstrap_existing_sessions(self) -> None:
        changed = False
        for chat_id, state in self.chat_state.items():
            session_id = str(state.get("session_id") or "").strip()
            if not session_id:
                continue
            cwd = str(state.get("cwd") or self.config.default_cwd)
            if session_id not in self.bridge_index:
                self.bridge_index[session_id] = {
                    "session_id": session_id,
                    "chat_id": chat_id,
                    "cwd": cwd,
                    "title": "Recovered Telegram session",
                    "source_kind": "telegram",
                    "source_label": "TG",
                    "created_at": utc_now_iso(),
                    "updated_at": utc_now_iso(),
                    "message_count": 0,
                    "transcript_path": str(self._session_transcript_path(session_id)),
                    "chat_transcript_path": str(self._chat_transcript_path(chat_id)),
                }
                changed = True
            if session_id not in self.codex_index_ids:
                self._append_codex_session_index(session_id, self.bridge_index[session_id].get("title", "Recovered Telegram session"))
        if changed:
            save_json(BRIDGE_INDEX_PATH, self.bridge_index)

    def run(self) -> None:
        if not self.config.telegram_bot_token:
            raise RuntimeError("TELEGRAM_BOT_TOKEN is missing in .env.local or .env")
        self._delete_webhook()
        print(f"Telegram bridge running. Default cwd: {self.config.default_cwd}", flush=True)
        while True:
            try:
                updates = self._telegram_api(
                    "getUpdates",
                    {
                        "offset": self.telegram_offset,
                        "timeout": self.config.telegram_poll_timeout_seconds,
                        "allowed_updates": TELEGRAM_ALLOWED_UPDATES,
                    },
                )
                for update in updates:
                    self.telegram_offset = max(self.telegram_offset, int(update["update_id"]) + 1)
                    self._handle_update(update)
            except KeyboardInterrupt:
                print("Stopping bridge.", flush=True)
                return
            except Exception as exc:
                print(f"[bridge] polling error: {exc}", file=sys.stderr, flush=True)
                time.sleep(3)

    def _telegram_api(self, method: str, payload: dict[str, Any]) -> Any:
        url = f"https://api.telegram.org/bot{self.config.telegram_bot_token}/{method}"
        data = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(request, timeout=self.config.telegram_poll_timeout_seconds + 10) as response:
            body = json.loads(response.read().decode("utf-8"))
        if not body.get("ok"):
            raise RuntimeError(f"Telegram API error for {method}: {body}")
        return body.get("result")

    def _telegram_api_multipart(
        self,
        method: str,
        fields: dict[str, Any],
        files: dict[str, tuple[str, bytes, str]],
    ) -> Any:
        url = f"https://api.telegram.org/bot{self.config.telegram_bot_token}/{method}"
        boundary = f"----telegram-{uuid.uuid4().hex}"
        body = BytesIO()

        for name, value in fields.items():
            if value is None:
                continue
            body.write(f"--{boundary}\r\n".encode("utf-8"))
            body.write(f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode("utf-8"))
            if isinstance(value, (dict, list)):
                body.write(json.dumps(value, ensure_ascii=False).encode("utf-8"))
            else:
                body.write(str(value).encode("utf-8"))
            body.write(b"\r\n")

        for name, (filename, content, content_type) in files.items():
            body.write(f"--{boundary}\r\n".encode("utf-8"))
            body.write(
                (
                    f'Content-Disposition: form-data; name="{name}"; filename="{filename}"\r\n'
                    f"Content-Type: {content_type}\r\n\r\n"
                ).encode("utf-8")
            )
            body.write(content)
            body.write(b"\r\n")

        body.write(f"--{boundary}--\r\n".encode("utf-8"))
        request = urllib.request.Request(
            url,
            data=body.getvalue(),
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        )
        with urllib.request.urlopen(request, timeout=self.config.telegram_poll_timeout_seconds + 20) as response:
            body_json = json.loads(response.read().decode("utf-8"))
        if not body_json.get("ok"):
            raise RuntimeError(f"Telegram API error for {method}: {body_json}")
        return body_json.get("result")

    def _delete_webhook(self) -> None:
        try:
            self._telegram_api("deleteWebhook", {"drop_pending_updates": False})
        except Exception as exc:
            print(f"[bridge] deleteWebhook failed: {exc}", file=sys.stderr, flush=True)

    def _handle_update(self, update: dict[str, Any]) -> None:
        callback_query = update.get("callback_query")
        if callback_query:
            self._handle_callback_query(callback_query)
            return

        message = update.get("message") or update.get("edited_message")
        if not message:
            return
        text = (message.get("text") or "").strip()
        if not text:
            return

        chat_id = str(message["chat"]["id"])
        self._log_chat_transcript(chat_id, role="user", kind="telegram_in", text=text)

        if not self._is_chat_allowed(chat_id):
            reply_markup = None
            if not self._has_any_allowed_chat():
                reply_markup = {"inline_keyboard": [[{"text": "Authorize This Chat", "callback_data": "auth:claim"}]]}
            self._send_text(chat_id, self._unauthorized_text(chat_id), kind="auth", source="bridge", reply_markup=reply_markup)
            return

        quick_command = self._quick_action_command(text)
        if quick_command:
            self._handle_command(chat_id, quick_command)
            return

        if text.startswith("/"):
            self._handle_command(chat_id, text)
            return

        if self._consume_pending_input(chat_id, text):
            return

        self._start_job(chat_id, text)

    def _is_chat_allowed(self, chat_id: str) -> bool:
        allowed = self.config.allowed_chat_ids | self._runtime_allowed_chat_ids()
        return bool(allowed) and chat_id in allowed

    def _is_chat_admin(self, chat_id: str) -> bool:
        admins = self.config.allowed_chat_ids | self._runtime_admin_chat_ids()
        return chat_id in admins

    def _has_any_allowed_chat(self) -> bool:
        return bool(self.config.allowed_chat_ids | self._runtime_allowed_chat_ids())

    def _unauthorized_text(self, chat_id: str) -> str:
        if not self._has_any_allowed_chat():
            return (
                "This bot is not armed yet.\n"
                f"Your chat ID is {chat_id}.\n"
                "Tap Authorize This Chat below to claim this bridge without editing local files."
            )
        return (
            "This chat is not allowed to control the bot.\n"
            f"Your chat ID is {chat_id}.\n"
            "Ask an already authorized user to send /allow <your_chat_id>."
        )

    def _quick_action_command(self, text: str) -> Optional[str]:
        normalized = " ".join(str(text or "").strip().split()).casefold()
        if not normalized:
            return None
        mapping = {
            MENU_HOME_LABEL.casefold(): MENU_HOME_COMMAND,
            MENU_PROJECTS_LABEL.casefold(): MENU_PROJECTS_COMMAND,
            MENU_SESSIONS_LABEL.casefold(): MENU_SESSIONS_COMMAND,
            MENU_NEW_LABEL.casefold(): MENU_NEW_COMMAND,
            MENU_STATUS_LABEL.casefold(): MENU_STATUS_COMMAND,
            MENU_WHERE_LABEL.casefold(): MENU_WHERE_COMMAND,
            MENU_HELP_LABEL.casefold(): MENU_HELP_COMMAND,
            MENU_CANCEL_LABEL.casefold(): MENU_CANCEL_COMMAND,
        }
        return mapping.get(normalized)

    def _handle_command(self, chat_id: str, text: str) -> None:
        command, _, argument = text.partition(" ")
        command_name = command.split("@", 1)[0].lower()
        argument = argument.strip()

        if command_name == "/start":
            self._send_welcome_screen(chat_id)
            return
        if command_name == "/help":
            self._send_detail_panel(chat_id, self._help_text(chat_id))
            return
        if command_name == MENU_HOME_COMMAND:
            self._send_dashboard(chat_id)
            return
        if command_name == "/id":
            self._send_text(chat_id, f"Telegram chat ID: {chat_id}", kind="status", source="bridge")
            return
        if command_name == "/allow":
            if not self._is_chat_admin(chat_id):
                self._send_text(chat_id, "Only an authorized admin chat can add more users.", kind="error", source="bridge")
                return
            target_id = argument.strip()
            if not target_id:
                self._send_text(chat_id, "Usage: /allow <chat_id>", kind="error", source="bridge")
                return
            self._add_runtime_allowed_chat(target_id)
            self._send_text(chat_id, f"Allowed chat: {target_id}", kind="status", source="bridge")
            return
        if command_name == "/revoke":
            if not self._is_chat_admin(chat_id):
                self._send_text(chat_id, "Only an authorized admin chat can revoke access.", kind="error", source="bridge")
                return
            target_id = argument.strip()
            if not target_id:
                self._send_text(chat_id, "Usage: /revoke <chat_id>", kind="error", source="bridge")
                return
            self._remove_runtime_allowed_chat(target_id)
            self._send_text(chat_id, f"Revoked chat: {target_id}", kind="status", source="bridge")
            return
        if command_name == "/pwd":
            self._send_text(chat_id, self._get_chat_state(chat_id)["cwd"], kind="status", source="bridge")
            return
        if command_name == "/session":
            state = self._get_chat_state(chat_id)
            session_id = state.get("session_id")
            if session_id:
                self._send_text(chat_id, f"Active Codex session:\n{session_id}", kind="status", source="bridge")
            else:
                self._send_text(chat_id, "No active Codex session for this chat yet.", kind="status", source="bridge")
            return
        if command_name == "/use":
            if not argument:
                self._send_text(chat_id, "Usage: /use <history_index|session_id>", kind="error", source="bridge")
                return
            self._switch_session(chat_id, argument)
            return
        if command_name == "/title":
            if not argument:
                self._send_text(chat_id, "Usage: /title <human readable name>", kind="error", source="bridge")
                return
            self._rename_current_session(chat_id, argument)
            return
        if command_name == "/new":
            self._send_text(chat_id, self._clear_session(chat_id), kind="status", source="bridge")
            return
        if command_name == "/cd":
            if not argument:
                self._send_text(chat_id, "Usage: /cd C:\\path\\to\\project", kind="error", source="bridge")
                return
            target = Path(argument).expanduser()
            if not target.exists() or not target.is_dir():
                self._send_text(chat_id, f"Directory not found:\n{target}", kind="error", source="bridge")
                return
            _, reply = self._set_chat_cwd(chat_id, str(target.resolve()))
            self._send_text(chat_id, reply, kind="status", source="bridge")
            return
        if command_name == "/status":
            self._send_status_panel(chat_id)
            return
        if command_name == "/projects":
            self._send_project_menu(chat_id)
            return
        if command_name == "/sessions":
            self._send_session_menu(chat_id)
            return
        if command_name == "/where":
            self._send_detail_panel(chat_id, self._where_text(chat_id))
            return
        if command_name == "/jobs":
            self._send_text(chat_id, self._jobs_text(chat_id), kind="status", source="bridge")
            return
        if command_name == "/cancel":
            if not argument.isdigit():
                self._send_text(chat_id, "Usage: /cancel <job_id>", kind="error", source="bridge")
                return
            self._cancel_job(chat_id, int(argument))
            return
        if command_name == MENU_CANCEL_COMMAND:
            self._cancel_running_job_for_chat(chat_id, send_message=True)
            return
        if command_name == "/history":
            self._send_text(chat_id, self._history_text(chat_id, argument), kind="status", source="bridge")
            return
        if command_name == "/transcript":
            self._send_text(chat_id, self._transcript_text(chat_id, argument), kind="status", source="bridge")
            return
        if command_name == "/run":
            if not argument:
                self._send_text(chat_id, "Usage: /run <prompt>", kind="error", source="bridge")
                return
            self._start_job(chat_id, argument)
            return

        self._send_text(chat_id, f"Unknown command: {command_name}\n\n{self._help_text(chat_id)}", kind="error", source="bridge")

    def _help_text(self, chat_id: str) -> str:
        return (
            "Telegram Codex Bridge\n\n"
            "Send a normal message anytime to ask Codex to work.\n\n"
            "Quick actions:\n"
            f"{MENU_HOME_LABEL}: open the control center\n"
            f"{MENU_PROJECTS_LABEL}: choose the working project\n"
            f"{MENU_SESSIONS_LABEL}: browse TG + desktop Codex conversations\n"
            f"{MENU_NEW_LABEL}: clear the active conversation\n"
            f"{MENU_CANCEL_LABEL}: stop the current running task\n\n"
            "Inside the dashboard you can also open Current Chat, rename the active chat, or enter a new project path.\n\n"
            "Commands:\n"
            f"{MENU_HOME_COMMAND}\n"
            f"{MENU_PROJECTS_COMMAND}\n"
            f"{MENU_SESSIONS_COMMAND}\n"
            "/run <prompt>\n"
            "/cd <path>\n"
            "/pwd\n"
            "/session\n"
            "/use <history_index|session_id>\n"
            "/title <name>\n"
            "/new\n"
            "/status\n"
            "/where\n"
            "/jobs\n"
            "/cancel <job_id>\n"
            "/history [N|all]\n"
            "/transcript [session_id]\n"
            "/id\n"
            "/allow <chat_id>\n"
            "/revoke <chat_id>\n"
            "/help\n\n"
            "The bottom keyboard keeps the main controls one tap away.\n\n"
            "When the UI asks for input, your next normal message is used for that action instead of being sent to Codex.\n\n"
            f"Current chat: {chat_id}"
        )

    def _menu_text(self, chat_id: str) -> str:
        state = self._get_chat_state(chat_id)
        session_meta = self._current_session_meta(chat_id)
        current_job = self._current_job_for_chat(chat_id)
        project_name = Path(state["cwd"]).name or state["cwd"]
        session_id = str(state.get("session_id") or "").strip()
        session_title = str(session_meta.get("title") or "").strip() if session_meta else ""
        session_source = str(session_meta.get("source_label") or "").strip() if session_meta else ""
        if session_id:
            session_line = ((f"[{session_source}] " if session_source else "") + (session_title or "Untitled conversation")).strip()
        else:
            session_line = "(new conversation)"
        if session_id and session_meta and session_meta.get("updated_at"):
            session_line += f"\nlast active: {human_timestamp(str(session_meta.get('updated_at')))}"
        running_line = f"Working on job #{current_job.job_id}" if current_job else "Ready for your next message"
        pending_line = self._pending_input_label(state.get("pending_input_action"))
        preview_line = str(session_meta.get("last_result_preview") or "").strip() if session_meta else ""
        lines = [
            "Control center",
            "",
            "Project",
            project_name,
            state["cwd"],
            "",
            "Conversation",
            session_line,
        ]
        if preview_line:
            lines.append(f"last reply: {preview_text(preview_line, 140)}")
        lines.extend(
            [
                "",
                "Status",
                running_line,
                f"access: {self._access_mode_label()}",
                "",
            ]
        )
        if pending_line:
            lines.extend(
                [
                    f"Input mode: {pending_line}",
                    "",
                    "Your next normal message will be used for this input action, not sent to Codex.",
                    "Use Cancel Input or New Chat if you want to leave this mode first.",
                ]
            )
        else:
            lines.append(
                "Send a normal message to run Codex here.\nUse the buttons below if you want to switch project, open a TG/desktop chat, or change bot controls first."
            )
        return "\n".join(lines)

    def _welcome_caption(self, chat_id: str) -> str:
        return (
            "Codex\n"
            "Local coding bridge.\n\n"
            "Use the keyboard below.\n"
            "Tap Menu when you want the full control center."
        )

    def _get_chat_state(self, chat_id: str) -> dict[str, Any]:
        with self.state_lock:
            state = self.chat_state.setdefault(chat_id, {})
            state.setdefault("cwd", self.config.default_cwd)
            state.setdefault("session_id", None)
            state.setdefault("last_job_id", None)
            state.setdefault("reply_keyboard_version", 0)
            state.setdefault("pending_input_action", None)
            return state

    def _save_chat_state(self) -> None:
        with self.state_lock:
            save_json(CHAT_STATE_PATH, self.chat_state)

    def _chat_transcript_path(self, chat_id: str) -> Path:
        return CHAT_TRANSCRIPTS_DIR / f"{chat_id}.jsonl"

    def _session_transcript_path(self, session_id: str) -> Path:
        return SESSION_TRANSCRIPTS_DIR / f"{session_id}.jsonl"

    def _log_chat_transcript(self, chat_id: str, role: str, kind: str, text: str, source: str = "telegram") -> None:
        append_jsonl(
            self._chat_transcript_path(chat_id),
            {
                "ts": utc_now_iso(),
                "chat_id": chat_id,
                "role": role,
                "kind": kind,
                "source": source,
                "text": text,
            },
        )

    def _log_session_transcript(self, session_id: str, chat_id: str, role: str, kind: str, text: str, source: str) -> None:
        append_jsonl(
            self._session_transcript_path(session_id),
            {
                "ts": utc_now_iso(),
                "chat_id": chat_id,
                "session_id": session_id,
                "role": role,
                "kind": kind,
                "source": source,
                "text": text,
            },
        )
        self._upsert_bridge_session(session_id, chat_id=chat_id, message_delta=1)

    def _send_text(
        self,
        chat_id: str,
        text: str,
        *,
        kind: str,
        source: str,
        session_id: Optional[str] = None,
        reply_markup: Optional[dict[str, Any]] = None,
    ) -> None:
        chunks = split_message(text)
        for index, chunk in enumerate(chunks):
            payload: dict[str, Any] = {
                "chat_id": int(chat_id),
                "text": chunk,
                "disable_web_page_preview": True,
            }
            if index == len(chunks) - 1:
                payload["reply_markup"] = reply_markup or self._default_reply_markup()
            self._telegram_api(
                "sendMessage",
                payload,
            )
        self._log_chat_transcript(chat_id, role="assistant", kind=kind, text=text, source=source)
        if session_id:
            self._log_session_transcript(session_id, chat_id, role="assistant", kind=kind, text=text, source=source)

    def _send_photo(
        self,
        chat_id: str,
        photo_path: Path,
        caption: str,
        *,
        kind: str,
        source: str,
        session_id: Optional[str] = None,
        reply_markup: Optional[dict[str, Any]] = None,
    ) -> None:
        if not photo_path.exists():
            raise FileNotFoundError(f"Welcome image not found: {photo_path}")
        content_type = guess_type(photo_path.name)[0] or "application/octet-stream"
        self._telegram_api_multipart(
            "sendPhoto",
            {
                "chat_id": int(chat_id),
                "caption": caption,
                "reply_markup": reply_markup or self._default_reply_markup(),
            },
            {
                "photo": (photo_path.name, photo_path.read_bytes(), content_type),
            },
        )
        self._log_chat_transcript(chat_id, role="assistant", kind=kind, text=caption, source=source)
        if session_id:
            self._log_session_transcript(session_id, chat_id, role="assistant", kind=kind, text=caption, source=source)

    def _default_reply_markup(self) -> dict[str, Any]:
        return {
            "keyboard": [
                [{"text": MENU_PROJECTS_LABEL}, {"text": MENU_SESSIONS_LABEL}],
                [{"text": MENU_NEW_LABEL}, {"text": MENU_STATUS_LABEL}],
                [{"text": MENU_WHERE_LABEL}, {"text": MENU_CANCEL_LABEL}],
                [{"text": MENU_HOME_LABEL}, {"text": MENU_HELP_LABEL}],
            ],
            "resize_keyboard": True,
            "is_persistent": True,
            "input_field_placeholder": "Send a prompt or tap a quick action",
        }

    def _ensure_reply_keyboard(self, chat_id: str, *, force: bool = False) -> None:
        state = self._get_chat_state(chat_id)
        current_version = int(state.get("reply_keyboard_version") or 0)
        if not force and current_version >= REPLY_KEYBOARD_VERSION:
            return
        self._send_text(
            chat_id,
            "Quick actions updated.\nUse the bottom keyboard below.",
            kind="status",
            source="bridge",
        )
        state["reply_keyboard_version"] = REPLY_KEYBOARD_VERSION
        self._save_chat_state()

    def _current_job_for_chat(self, chat_id: str) -> Optional[Job]:
        with self.jobs_lock:
            job_id = self.chat_running_jobs.get(chat_id)
            if job_id is None:
                return None
            return self.active_jobs.get(job_id)

    def _current_session_meta(self, chat_id: str) -> dict[str, Any]:
        state = self._get_chat_state(chat_id)
        session_id = str(state.get("session_id") or "").strip()
        if not session_id:
            return {}
        for item in self._unified_sessions(chat_id):
            if str(item.get("session_id") or "") == session_id:
                return dict(item)
        if session_id in self.bridge_index:
            return dict(self.bridge_index.get(session_id, {}))
        return {}

    def _refresh_rollout_path_cache(self) -> None:
        now = time.time()
        if self.rollout_path_cache and (now - self.rollout_path_cache_at) < 30:
            return
        mapping: dict[str, str] = {}
        sessions_root = CODEX_HOME / "sessions"
        if sessions_root.exists():
            for path in sessions_root.rglob("rollout-*.jsonl"):
                match = ROLLOUT_FILENAME_PATTERN.search(path.name)
                if not match:
                    continue
                session_id = match.group(1)
                previous = mapping.get(session_id)
                if not previous or path.stat().st_mtime > Path(previous).stat().st_mtime:
                    mapping[session_id] = str(path)
        self.rollout_path_cache = mapping
        self.rollout_path_cache_at = now

    def _get_rollout_path(self, session_id: str) -> Optional[str]:
        self._refresh_rollout_path_cache()
        return self.rollout_path_cache.get(session_id)

    def _load_rollout_session_meta(self, session_id: str) -> dict[str, Any]:
        rollout_path = self._get_rollout_path(session_id)
        if not rollout_path:
            return {}
        try:
            with Path(rollout_path).open("r", encoding="utf-8", errors="replace") as handle:
                for raw in handle:
                    try:
                        payload = json.loads(raw)
                    except Exception:
                        continue
                    if str(payload.get("type") or "") != "session_meta":
                        continue
                    meta = payload.get("payload") or {}
                    if str(meta.get("id") or "").strip() == session_id:
                        if isinstance(meta, dict):
                            return meta
        except Exception:
            return {}
        return {}

    def _load_codex_history_latest(self) -> dict[str, str]:
        latest: dict[str, str] = {}
        if not CODEX_HISTORY_PATH.exists():
            return latest
        try:
            for raw in CODEX_HISTORY_PATH.read_text(encoding="utf-8", errors="replace").splitlines():
                try:
                    payload = json.loads(raw)
                except Exception:
                    continue
                session_id = str(payload.get("session_id") or "").strip()
                text = str(payload.get("text") or "").strip()
                if session_id and text:
                    latest[session_id] = text
        except Exception:
            return latest
        return latest

    def _load_codex_index_entries(self) -> dict[str, dict[str, Any]]:
        entries: dict[str, dict[str, Any]] = {}
        if not CODEX_SESSION_INDEX_PATH.exists():
            return entries
        try:
            for raw in CODEX_SESSION_INDEX_PATH.read_text(encoding="utf-8", errors="replace").splitlines():
                try:
                    payload = json.loads(raw)
                except Exception:
                    continue
                session_id = str(payload.get("id") or "").strip()
                if session_id:
                    entries[session_id] = payload
        except Exception:
            return {}
        return entries

    def _rollout_updated_at(self, rollout_path: Optional[str], fallback: str = "") -> str:
        if rollout_path:
            try:
                ts = Path(rollout_path).stat().st_mtime
                return datetime.fromtimestamp(ts, timezone.utc).isoformat().replace("+00:00", "Z")
            except Exception:
                pass
        return fallback

    def _session_source_info(self, thread_name: str, meta: dict[str, Any]) -> tuple[str, str]:
        if thread_name.startswith("[TG]"):
            return "telegram", "TG"
        source = meta.get("source")
        originator = str(meta.get("originator") or "").strip().lower()
        if isinstance(source, dict) and source.get("subagent"):
            return "subagent", "Subagent"
        source_text = str(source or "").strip().lower()
        if source_text == "vscode" or "vscode" in originator:
            return "vscode", "VSCode"
        if source_text == "exec" or "exec" in originator:
            return "exec", "CLI"
        if source_text:
            return source_text, source_text.title()
        if originator:
            return originator, originator.replace("_", " ").title()
        return "local", "Local"

    def _unified_sessions(self, chat_id: str) -> list[dict[str, Any]]:
        history_latest = self._load_codex_history_latest()
        index_entries = self._load_codex_index_entries()
        unified: dict[str, dict[str, Any]] = {}

        for session_id, item in self.bridge_index.items():
            if str(item.get("chat_id")) != chat_id:
                continue
            entry = dict(item)
            entry["session_id"] = session_id
            entry["source_kind"] = str(entry.get("source_kind") or "telegram")
            entry["source_label"] = str(entry.get("source_label") or "TG")
            entry["adopted"] = True
            unified[session_id] = entry

        self._refresh_rollout_path_cache()
        for session_id, rollout_path in self.rollout_path_cache.items():
            index_entry = index_entries.get(session_id, {})
            thread_name = str(index_entry.get("thread_name") or "").strip()
            is_tg = thread_name.startswith("[TG]")
            if is_tg and session_id not in unified:
                continue

            meta = self._load_rollout_session_meta(session_id)
            source_kind, source_label = self._session_source_info(thread_name, meta)
            if source_kind == "subagent":
                continue

            preview = (
                str(unified.get(session_id, {}).get("last_result_preview") or "").strip()
                or str(history_latest.get(session_id) or "").strip()
            )
            title = thread_name.removeprefix("[TG]").strip() if thread_name else ""
            title = title or str(meta.get("thread_name") or "").strip()
            if not title and preview:
                title = derive_title(preview, fallback="Untitled conversation")
            title = title or "Untitled conversation"
            cwd = str(meta.get("cwd") or unified.get(session_id, {}).get("cwd") or "").strip()
            updated_at = (
                str(unified.get(session_id, {}).get("updated_at") or "").strip()
                or self._rollout_updated_at(
                    rollout_path,
                    str(index_entry.get("updated_at") or "").strip() or str(meta.get("timestamp") or "").strip(),
                )
            )
            entry = unified.setdefault(session_id, {})
            entry.setdefault("session_id", session_id)
            entry.setdefault("chat_id", chat_id)
            entry["title"] = title
            entry["updated_at"] = updated_at
            entry["cwd"] = cwd
            entry["source_kind"] = source_kind
            entry["source_label"] = source_label
            entry["transcript_path"] = str(entry.get("transcript_path") or rollout_path or "")
            entry["chat_transcript_path"] = str(entry.get("chat_transcript_path") or self._chat_transcript_path(chat_id))
            if preview:
                entry["last_result_preview"] = preview
            entry["adopted"] = bool(session_id in self.bridge_index)
            entry.setdefault("message_count", int(entry.get("message_count", 0) or 0))

        return list(unified.values())

    def _set_job_stage(self, job: Job, stage: str) -> None:
        job.last_stage = stage
        job.last_event_at = time.time()

    def _project_activity(self, chat_id: str) -> dict[str, dict[str, Any]]:
        activity: dict[str, dict[str, Any]] = {}
        for item in self._unified_sessions(chat_id):
            cwd = self._normalize_existing_dir(str(item.get("cwd") or ""))
            if not cwd:
                continue
            entry = activity.setdefault(
                cwd,
                {
                    "updated_at": "",
                    "session_count": 0,
                    "message_count": 0,
                    "sample_title": "",
                    "last_result_preview": "",
                },
            )
            entry["session_count"] += 1
            entry["message_count"] += int(item.get("message_count", 0) or 0)
            updated_at = str(item.get("updated_at") or "")
            if updated_at and updated_at > str(entry.get("updated_at") or ""):
                entry["updated_at"] = updated_at
            if not str(entry.get("sample_title") or "").strip():
                entry["sample_title"] = str(item.get("title") or "").strip()
            if not str(entry.get("last_result_preview") or "").strip():
                entry["last_result_preview"] = str(item.get("last_result_preview") or "").strip()
        return activity

    def _pending_input_label(self, action: Optional[str]) -> str:
        mapping = {
            "rename_session": "Waiting for a new conversation title",
            "set_project_path": "Waiting for a project path",
        }
        return mapping.get(str(action or "").strip(), "")

    def _access_mode_label(self) -> str:
        sandbox = str(self.config.codex_sandbox or "").strip().lower()
        if sandbox == "danger-full-access":
            return "Full machine access"
        if sandbox == "workspace-write":
            return "Workspace sandbox"
        if sandbox:
            return sandbox
        return "(default)"

    def _set_pending_input(self, chat_id: str, action: str) -> None:
        state = self._get_chat_state(chat_id)
        state["pending_input_action"] = action
        self._save_chat_state()

    def _clear_pending_input(self, chat_id: str) -> None:
        state = self._get_chat_state(chat_id)
        if state.get("pending_input_action") is not None:
            state["pending_input_action"] = None
            self._save_chat_state()

    def _consume_pending_input(self, chat_id: str, text: str) -> bool:
        state = self._get_chat_state(chat_id)
        action = str(state.get("pending_input_action") or "").strip()
        if not action:
            return False

        if action == "rename_session":
            self._clear_pending_input(chat_id)
            self._rename_current_session(chat_id, text)
            self._send_dashboard(chat_id)
            return True

        if action == "set_project_path":
            target = Path(text).expanduser()
            if not target.exists() or not target.is_dir():
                self._send_text(
                    chat_id,
                    f"Directory not found:\n{target}\n\nSend another path, or tap Menu to leave path entry mode.",
                    kind="error",
                    source="bridge",
                )
                return True
            self._clear_pending_input(chat_id)
            _, reply = self._set_chat_cwd(chat_id, str(target.resolve()))
            self._send_text(chat_id, reply, kind="status", source="bridge")
            self._send_dashboard(chat_id)
            return True

        self._clear_pending_input(chat_id)
        return False

    def _paginate_items(self, items: list[Any], page: int, page_size: int) -> tuple[list[Any], int, int, int]:
        if page_size <= 0:
            page_size = 1
        total_pages = max(1, (len(items) + page_size - 1) // page_size)
        safe_page = max(0, min(page, total_pages - 1))
        start = safe_page * page_size
        return items[start : start + page_size], safe_page, total_pages, start

    def _callback_message_target(self, callback_query: dict[str, Any]) -> tuple[str, int] | None:
        message = callback_query.get("message") or {}
        chat = message.get("chat") or {}
        chat_id = str(chat.get("id") or "").strip()
        message_id = message.get("message_id")
        if not chat_id or message_id is None:
            return None
        return chat_id, int(message_id)

    def _edit_message_text(self, chat_id: str, message_id: int, text: str, reply_markup: dict[str, Any]) -> bool:
        try:
            self._telegram_api(
                "editMessageText",
                {
                    "chat_id": int(chat_id),
                    "message_id": int(message_id),
                    "text": text,
                    "disable_web_page_preview": True,
                    "reply_markup": reply_markup,
                },
            )
            return True
        except Exception as exc:
            lowered = str(exc).lower()
            if "message is not modified" in lowered:
                return True
            return False

    def _send_or_edit_panel(
        self,
        chat_id: str,
        text: str,
        reply_markup: dict[str, Any],
        *,
        message_id: Optional[int] = None,
        kind: str = "status",
    ) -> None:
        if message_id is None:
            self._ensure_reply_keyboard(chat_id)
        if message_id is not None and self._edit_message_text(chat_id, message_id, text, reply_markup):
            return
        self._send_text(chat_id, text, kind=kind, source="bridge", reply_markup=reply_markup)

    def _menu_markup(self, chat_id: str) -> dict[str, Any]:
        current_job = self._current_job_for_chat(chat_id)
        current_session = str(self._get_chat_state(chat_id).get("session_id") or "").strip()
        cancel_label = MENU_CANCEL_LABEL if current_job else "Cancel Job (idle)"
        rename_label = "Rename Chat" if current_session else "Rename Chat (none)"
        return {
            "inline_keyboard": [
                [
                    {"text": MENU_PROJECTS_LABEL, "callback_data": "nav:projects:0"},
                    {"text": MENU_SESSIONS_LABEL, "callback_data": "nav:sessions:0"},
                ],
                [
                    {"text": "Current Chat", "callback_data": "nav:current"},
                    {"text": "Set Path", "callback_data": "act:setpath"},
                ],
                [
                    {"text": rename_label, "callback_data": "act:rename"},
                    {"text": MENU_NEW_LABEL, "callback_data": "act:new"},
                ],
                [
                    {"text": MENU_STATUS_LABEL, "callback_data": "nav:status"},
                    {"text": MENU_WHERE_LABEL, "callback_data": "nav:where"},
                ],
                [
                    {"text": cancel_label, "callback_data": "act:cancel"},
                    {"text": MENU_HELP_LABEL, "callback_data": "nav:help"},
                ],
                [
                    {"text": "Refresh", "callback_data": "nav:home"},
                ],
            ]
        }

    def _detail_markup(self) -> dict[str, Any]:
        return {
            "inline_keyboard": [
                [
                    {"text": MENU_HOME_LABEL, "callback_data": "nav:home"},
                    {"text": MENU_PROJECTS_LABEL, "callback_data": "nav:projects:0"},
                    {"text": MENU_SESSIONS_LABEL, "callback_data": "nav:sessions:0"},
                ]
            ]
        }

    def _send_dashboard(self, chat_id: str, message_id: Optional[int] = None) -> None:
        self._send_or_edit_panel(chat_id, self._menu_text(chat_id), self._menu_markup(chat_id), message_id=message_id)

    def _send_welcome_screen(self, chat_id: str) -> None:
        self._send_photo(
            chat_id,
            WELCOME_IMAGE_PATH,
            self._welcome_caption(chat_id),
            kind="welcome",
            source="bridge",
            reply_markup=self._default_reply_markup(),
        )
        state = self._get_chat_state(chat_id)
        state["reply_keyboard_version"] = REPLY_KEYBOARD_VERSION
        self._save_chat_state()

    def _send_detail_panel(self, chat_id: str, text: str, message_id: Optional[int] = None) -> None:
        self._send_or_edit_panel(chat_id, text, self._detail_markup(), message_id=message_id)

    def _input_prompt_markup(self) -> dict[str, Any]:
        return {
            "inline_keyboard": [
                [
                    {"text": MENU_HOME_LABEL, "callback_data": "nav:home"},
                    {"text": "Current Chat", "callback_data": "nav:current"},
                ],
                [
                    {"text": MENU_PROJECTS_LABEL, "callback_data": "nav:projects:0"},
                    {"text": MENU_SESSIONS_LABEL, "callback_data": "nav:sessions:0"},
                ],
                [
                    {"text": "Cancel Input", "callback_data": "act:clearpending"},
                ],
            ]
        }

    def _send_input_prompt(self, chat_id: str, text: str, message_id: Optional[int] = None) -> None:
        self._send_or_edit_panel(chat_id, text, self._input_prompt_markup(), message_id=message_id)

    def _current_session_text(self, chat_id: str) -> str:
        state = self._get_chat_state(chat_id)
        session_id = str(state.get("session_id") or "").strip()
        if not session_id:
            return (
                "Current chat\n"
                "No active conversation yet.\n\n"
                "Your next normal message will start a fresh conversation in the current project."
            )
        meta = self._current_session_meta(chat_id)
        title = str(meta.get("title") or "").strip() or "Untitled conversation"
        preview = str(meta.get("last_result_preview") or "").strip()
        message_count = int(meta.get("message_count", 0) or 0)
        source_label = str(meta.get("source_label") or "TG").strip()
        lines = [
            "Current chat",
            f"title: {title}",
            f"source: {source_label}",
            f"project: {Path(state['cwd']).name or state['cwd']}",
            f"updated: {human_timestamp(str(meta.get('updated_at') or ''))} ({relative_age_text(str(meta.get('updated_at') or ''))})",
            f"messages: {message_count}",
            f"session: {session_id}",
        ]
        if source_label != "TG":
            lines.append("link: This chat is attached to a desktop Codex session.")
        if preview:
            lines.append(f"last reply: {preview}")
        return "\n".join(lines)

    def _current_session_markup(self, chat_id: str) -> dict[str, Any]:
        has_session = bool(str(self._get_chat_state(chat_id).get("session_id") or "").strip())
        first_row: list[dict[str, str]] = []
        if has_session:
            first_row.append({"text": "Rename Chat", "callback_data": "act:rename"})
        first_row.append({"text": MENU_NEW_LABEL, "callback_data": "act:new"})
        return {
            "inline_keyboard": [
                first_row,
                [
                    {"text": MENU_PROJECTS_LABEL, "callback_data": "nav:projects:0"},
                    {"text": MENU_SESSIONS_LABEL, "callback_data": "nav:sessions:0"},
                ],
                [
                    {"text": "Set Path", "callback_data": "act:setpath"},
                    {"text": MENU_HOME_LABEL, "callback_data": "nav:home"},
                ],
            ]
        }

    def _send_current_session_panel(self, chat_id: str, message_id: Optional[int] = None) -> None:
        self._send_or_edit_panel(
            chat_id,
            self._current_session_text(chat_id),
            self._current_session_markup(chat_id),
            message_id=message_id,
        )

    def _handle_callback_query(self, callback_query: dict[str, Any]) -> None:
        callback_id = str(callback_query.get("id") or "").strip()
        data = str(callback_query.get("data") or "").strip()
        target = self._callback_message_target(callback_query)
        if not callback_id or not target:
            return
        chat_id, message_id = target

        self._log_chat_transcript(chat_id, role="user", kind="telegram_action", text=f"callback:{data}", source="telegram")

        if data == "auth:claim" and not self._has_any_allowed_chat():
            self._add_runtime_allowed_chat(chat_id, admin=True)
            self._answer_callback_query(callback_id, "This chat is now authorized.")
            self._send_dashboard(chat_id, message_id=message_id)
            return

        if not self._is_chat_allowed(chat_id):
            self._answer_callback_query(callback_id, "This chat is not allowed.", show_alert=True)
            return

        if data == "nav:home":
            self._answer_callback_query(callback_id, "Opening control center…")
            self._send_dashboard(chat_id, message_id=message_id)
            return
        if data == "nav:status":
            self._answer_callback_query(callback_id, "Opening task status…")
            self._send_status_panel(chat_id, message_id=message_id)
            return
        if data == "nav:current":
            self._answer_callback_query(callback_id, "Opening current chat…")
            self._send_current_session_panel(chat_id, message_id=message_id)
            return
        if data == "nav:where":
            self._answer_callback_query(callback_id, "Opening path details…")
            self._send_detail_panel(chat_id, self._where_text(chat_id), message_id=message_id)
            return
        if data == "nav:help":
            self._answer_callback_query(callback_id, "Opening help…")
            self._send_detail_panel(chat_id, self._help_text(chat_id), message_id=message_id)
            return
        if data == "act:clearpending":
            self._clear_pending_input(chat_id)
            self._answer_callback_query(callback_id, "Input mode cleared.")
            self._send_dashboard(chat_id, message_id=message_id)
            return
        if data == "act:setpath":
            self._set_pending_input(chat_id, "set_project_path")
            self._answer_callback_query(callback_id, "Send the folder path in your next message.")
            current_path = self._get_chat_state(chat_id)["cwd"]
            suggestions = self._project_choices(chat_id)[:3]
            suggestion_lines = []
            if suggestions:
                suggestion_lines.append("")
                suggestion_lines.append("Quick suggestions:")
                for item in suggestions:
                    suggestion_lines.append(f"- {item['path']}")
            self._send_input_prompt(
                chat_id,
                (
                    "Set project path\n"
                    f"current: {current_path}\n\n"
                    "Send the folder path in your next message.\n\n"
                    "Example:\n"
                    "D:\\GMM_2_Final"
                    + ("\n" + "\n".join(suggestion_lines) if suggestion_lines else "")
                ),
                message_id=message_id,
            )
            return
        if data == "act:rename":
            if not str(self._get_chat_state(chat_id).get("session_id") or "").strip():
                self._answer_callback_query(callback_id, "No active conversation to rename.", show_alert=True)
                return
            self._set_pending_input(chat_id, "rename_session")
            self._answer_callback_query(callback_id, "Send the new title in your next message.")
            current_title = str(self._current_session_meta(chat_id).get("title") or "").strip() or "Untitled conversation"
            self._send_input_prompt(
                chat_id,
                (
                    "Rename current chat\n"
                    f"current title: {current_title}\n\n"
                    "Send the new title in your next message.\n\n"
                    "Tip: a short, clear title works best."
                ),
                message_id=message_id,
            )
            return
        if data == "act:new":
            self._answer_callback_query(callback_id, "Started a fresh conversation.")
            self._clear_session(chat_id)
            self._send_dashboard(chat_id, message_id=message_id)
            return
        if data == "act:cancel":
            reply = self._cancel_running_job_for_chat(chat_id, send_message=False)
            self._answer_callback_query(callback_id, preview_text(reply, 100), show_alert="No running job" in reply)
            self._send_dashboard(chat_id, message_id=message_id)
            return
        if data.startswith("nav:projects:"):
            page_text = data.rsplit(":", 1)[1]
            page = int(page_text) if page_text.isdigit() else 0
            self._answer_callback_query(callback_id, "Loading projects…")
            self._send_project_menu(chat_id, page=page, message_id=message_id)
            return
        if data.startswith("nav:sessions:"):
            page_text = data.rsplit(":", 1)[1]
            page = int(page_text) if page_text.isdigit() else 0
            self._answer_callback_query(callback_id, "Loading chats…")
            self._send_session_menu(chat_id, page=page, message_id=message_id)
            return
        if data.startswith("proj:refresh:"):
            page_text = data.rsplit(":", 1)[1]
            page = int(page_text) if page_text.isdigit() else 0
            self._answer_callback_query(callback_id, "Project list refreshed.")
            self._send_project_menu(chat_id, page=page, message_id=message_id)
            return
        if data.startswith("sess:refresh:"):
            page_text = data.rsplit(":", 1)[1]
            page = int(page_text) if page_text.isdigit() else 0
            self._answer_callback_query(callback_id, "Conversation list refreshed.")
            self._send_session_menu(chat_id, page=page, message_id=message_id)
            return
        if data.startswith("proj:set:"):
            index_text = data.rsplit(":", 1)[1]
            if not index_text.isdigit():
                self._answer_callback_query(callback_id, "Invalid project selection.", show_alert=True)
                return
            ok, reply = self._apply_project_choice(chat_id, int(index_text))
            if ok:
                self._answer_callback_query(callback_id, preview_text(reply, 100))
                self._send_dashboard(chat_id, message_id=message_id)
            else:
                self._answer_callback_query(callback_id, reply, show_alert=True)
            return
        if data.startswith("sessid:"):
            session_id = data.split(":", 1)[1].strip()
            if not session_id:
                self._answer_callback_query(callback_id, "Invalid conversation selection.", show_alert=True)
                return
            ok, reply = self._apply_session_choice(chat_id, session_id)
            if ok:
                self._answer_callback_query(callback_id, preview_text(reply, 100))
                self._send_dashboard(chat_id, message_id=message_id)
            else:
                self._answer_callback_query(callback_id, reply, show_alert=True)
            return

        self._answer_callback_query(callback_id, "Unknown action.", show_alert=True)

    def _answer_callback_query(self, callback_id: str, text: str = "", show_alert: bool = False) -> None:
        payload: dict[str, Any] = {"callback_query_id": callback_id}
        if text:
            payload["text"] = text
            payload["show_alert"] = show_alert
        self._telegram_api("answerCallbackQuery", payload)

    def _normalize_existing_dir(self, path_value: str) -> Optional[str]:
        path_text = str(path_value or "").strip()
        if not path_text:
            return None
        try:
            candidate = Path(path_text).expanduser()
        except Exception:
            return None
        if not candidate.exists() or not candidate.is_dir():
            return None
        try:
            resolved = candidate.resolve()
        except Exception:
            resolved = candidate
        return str(resolved)

    def _path_key(self, path_value: str) -> str:
        return path_value.casefold() if os.name == "nt" else path_value

    def _project_label(self, label: str, path_value: str) -> str:
        folder_name = Path(path_value).name or path_value
        if label.casefold() == folder_name.casefold():
            return label
        return f"{label} [{folder_name}]"

    def _project_choices(self, chat_id: str) -> list[dict[str, str]]:
        choices: list[dict[str, Any]] = []
        seen_paths: set[str] = set()
        activity = self._project_activity(chat_id)
        state = self._get_chat_state(chat_id)
        current_cwd = self._normalize_existing_dir(state["cwd"]) or state["cwd"]
        current_key = self._path_key(current_cwd)

        def add_choice(label: str, path_value: str, source: str) -> None:
            normalized = self._normalize_existing_dir(path_value)
            if not normalized:
                return
            key = self._path_key(normalized)
            if key in seen_paths:
                return
            seen_paths.add(key)
            meta = activity.get(normalized, {})
            choices.append(
                {
                    "label": label.strip() or (Path(normalized).name or normalized),
                    "path": normalized,
                    "source": source,
                    "updated_at": str(meta.get("updated_at") or ""),
                    "session_count": int(meta.get("session_count", 0) or 0),
                    "message_count": int(meta.get("message_count", 0) or 0),
                    "sample_title": str(meta.get("sample_title") or "").strip(),
                    "last_result_preview": str(meta.get("last_result_preview") or "").strip(),
                }
            )

        add_choice(Path(current_cwd).name or current_cwd, current_cwd, "current")

        for label, path_value in self.config.telegram_projects:
            add_choice(label, path_value, "pinned")

        recent_paths = sorted(
            activity.items(),
            key=lambda pair: (
                int(self._path_key(pair[0]) == current_key),
                str(pair[1].get("updated_at") or ""),
                int(pair[1].get("session_count", 0) or 0),
                int(pair[1].get("message_count", 0) or 0),
            ),
            reverse=True,
        )
        for path_value, meta in recent_paths:
            label = Path(path_value).name or path_value
            add_choice(label, path_value, "recent")
            if len(choices) >= MAX_PROJECT_CHOICES:
                break

        return choices[:MAX_PROJECT_CHOICES]

    def _project_menu_text(
        self,
        chat_id: str,
        choices: list[dict[str, str]],
        *,
        page: int,
        total_pages: int,
        start_index: int,
    ) -> str:
        state = self._get_chat_state(chat_id)
        lines = [
            "Projects",
            f"current project: {self._project_label(Path(state['cwd']).name or state['cwd'], state['cwd'])}",
            f"page {page + 1}/{total_pages}",
        ]
        if not choices:
            lines.append("No saved projects yet.")
            lines.append("Add TELEGRAM_PROJECTS in .env or use /cd to build recent projects.")
            return "\n".join(lines)

        lines.append("Pinned options come first. Switching project clears the active conversation to keep repo context clean.")
        for index, choice in enumerate(choices, start=1):
            absolute_index = start_index + index
            marker = " (current)" if self._path_key(choice["path"]) == self._path_key(state["cwd"]) else ""
            source_label = {"pinned": "Pinned", "current": "Current", "recent": "Recent"}.get(choice["source"], "Saved")
            lines.append(f"{absolute_index}. {self._project_label(choice['label'], choice['path'])} [{source_label}]{marker}")
            if choice.get("updated_at"):
                lines.append(f"updated: {human_timestamp(choice['updated_at'])} ({relative_age_text(choice['updated_at'])})")
            if choice.get("session_count") or choice.get("message_count"):
                lines.append(f"activity: {choice.get('session_count', 0)} chats, {choice.get('message_count', 0)} messages")
            if choice.get("last_result_preview"):
                lines.append(f"preview: {preview_text(str(choice['last_result_preview']), 110)}")
            lines.append(f"path: {choice['path']}")
        return "\n".join(lines)

    def _project_menu_markup(
        self,
        chat_id: str,
        choices: list[dict[str, str]],
        *,
        page: int,
        total_pages: int,
        start_index: int,
    ) -> dict[str, Any]:
        current_cwd = self._path_key(self._get_chat_state(chat_id)["cwd"])
        keyboard: list[list[dict[str, str]]] = []
        for index, choice in enumerate(choices, start=1):
            absolute_index = start_index + index
            button_text = self._project_label(choice["label"], choice["path"])
            if self._path_key(choice["path"]) == current_cwd:
                button_text = f"{button_text} (current)"
            keyboard.append([{"text": button_text[:60], "callback_data": f"proj:set:{absolute_index}"}])
        if total_pages > 1:
            nav_row: list[dict[str, str]] = []
            if page > 0:
                nav_row.append({"text": "Prev", "callback_data": f"nav:projects:{page - 1}"})
            nav_row.append({"text": f"{page + 1}/{total_pages}", "callback_data": f"proj:refresh:{page}"})
            if page + 1 < total_pages:
                nav_row.append({"text": "Next", "callback_data": f"nav:projects:{page + 1}"})
            keyboard.append(nav_row)
        keyboard.append(
            [
                {"text": "Refresh", "callback_data": f"proj:refresh:{page}"},
                {"text": MENU_SESSIONS_LABEL, "callback_data": "nav:sessions:0"},
            ]
        )
        keyboard.append(
            [
                {"text": MENU_HOME_LABEL, "callback_data": "nav:home"},
                {"text": MENU_NEW_LABEL, "callback_data": "act:new"},
            ]
        )
        return {"inline_keyboard": keyboard}

    def _send_project_menu(self, chat_id: str, page: int = 0, message_id: Optional[int] = None) -> None:
        all_choices = self._project_choices(chat_id)
        visible_choices, safe_page, total_pages, start_index = self._paginate_items(all_choices, page, PROJECTS_PAGE_SIZE)
        self._send_or_edit_panel(
            chat_id,
            self._project_menu_text(chat_id, visible_choices, page=safe_page, total_pages=total_pages, start_index=start_index),
            self._project_menu_markup(chat_id, visible_choices, page=safe_page, total_pages=total_pages, start_index=start_index),
            message_id=message_id,
        )

    def _set_chat_cwd(self, chat_id: str, target_cwd: str) -> tuple[bool, str]:
        self._clear_pending_input(chat_id)
        state = self._get_chat_state(chat_id)
        current_cwd = state["cwd"]
        current_key = self._path_key(current_cwd)
        target_key = self._path_key(target_cwd)
        previous_session = state.get("session_id")
        state["cwd"] = target_cwd
        if target_key != current_key:
            state["session_id"] = None
        self._save_chat_state()

        if target_key == current_key:
            return (
                False,
                "Project unchanged.\n"
                f"cwd: {target_cwd}\n"
                f"session: {state.get('session_id') or '(none)'}",
            )

        suffix = ""
        if previous_session:
            suffix = f"\nCleared previous session {previous_session} to avoid cross-repo context."
        return (
            True,
            "Project selected.\n"
            f"cwd: {target_cwd}\n"
            "Next prompt will start a new session."
            f"{suffix}",
        )

    def _apply_project_choice(self, chat_id: str, index: int) -> tuple[bool, str]:
        choices = self._project_choices(chat_id)
        if not (1 <= index <= len(choices)):
            return False, "That project menu expired. Reopen Projects."
        selected = choices[index - 1]
        changed, reply = self._set_chat_cwd(chat_id, selected["path"])
        label = self._project_label(selected["label"], selected["path"])
        if changed:
            return True, f"Project set to {label}. Next prompt starts fresh."
        return True, f"Already using {label}."

    def _session_choices(self, chat_id: str) -> list[dict[str, Any]]:
        return self._sorted_unified_sessions(chat_id)[:MAX_SESSION_CHOICES]

    def _session_button_text(self, item: dict[str, Any], current_session: Optional[str], index: int) -> str:
        source_label = str(item.get("source_label") or "Local")
        title = preview_text(str(item.get("title") or "Untitled conversation"), 34)
        title = f"[{source_label}] {title}"
        if item.get("session_id") == current_session:
            return f"{index}. {title} (current)"
        return f"{index}. {title}"

    def _session_menu_text(
        self,
        chat_id: str,
        sessions: list[dict[str, Any]],
        *,
        page: int,
        total_pages: int,
        start_index: int,
    ) -> str:
        current_session = self._get_chat_state(chat_id).get("session_id")
        if not sessions:
            return "Conversations\nNo saved conversations yet."
        lines = ["Conversations", "TG + desktop Codex sessions", f"page {page + 1}/{total_pages}"]
        for index, item in enumerate(sessions, start=1):
            absolute_index = start_index + index
            marker = " (current)" if item.get("session_id") == current_session else ""
            title = str(item.get("title") or "").strip() or "Untitled conversation"
            lines.append(f"{absolute_index}. [{item.get('source_label', 'Local')}] {title}{marker}")
            lines.append(f"updated: {human_timestamp(str(item.get('updated_at') or ''))} ({relative_age_text(str(item.get('updated_at') or ''))})")
            cwd = str(item.get("cwd") or "").strip()
            lines.append(f"project: {Path(cwd).name if cwd else '(unknown)'}")
            lines.append(f"messages: {int(item.get('message_count', 0) or 0)}")
            lines.append(f"source: {item.get('source_label', 'Local')}")
            preview = str(item.get("last_result_preview") or "").strip()
            if preview:
                lines.append(f"preview: {preview_text(preview, 120)}")
        return "\n".join(lines)

    def _session_menu_markup(
        self,
        chat_id: str,
        sessions: list[dict[str, Any]],
        *,
        page: int,
        total_pages: int,
        start_index: int,
    ) -> dict[str, Any]:
        current_session = self._get_chat_state(chat_id).get("session_id")
        keyboard: list[list[dict[str, str]]] = []
        for index, item in enumerate(sessions, start=1):
            session_id = str(item.get("session_id") or "").strip()
            if not session_id:
                continue
            keyboard.append(
                [
                    {
                        "text": self._session_button_text(item, current_session, start_index + index),
                        "callback_data": f"sessid:{session_id}",
                    }
                ]
            )
        if total_pages > 1:
            nav_row: list[dict[str, str]] = []
            if page > 0:
                nav_row.append({"text": "Prev", "callback_data": f"nav:sessions:{page - 1}"})
            nav_row.append({"text": f"{page + 1}/{total_pages}", "callback_data": f"sess:refresh:{page}"})
            if page + 1 < total_pages:
                nav_row.append({"text": "Next", "callback_data": f"nav:sessions:{page + 1}"})
            keyboard.append(nav_row)
        keyboard.append(
            [
                {"text": "Refresh", "callback_data": f"sess:refresh:{page}"},
                {"text": MENU_PROJECTS_LABEL, "callback_data": "nav:projects:0"},
            ]
        )
        keyboard.append(
            [
                {"text": MENU_HOME_LABEL, "callback_data": "nav:home"},
                {"text": MENU_NEW_LABEL, "callback_data": "act:new"},
            ]
        )
        return {"inline_keyboard": keyboard}

    def _send_session_menu(self, chat_id: str, page: int = 0, message_id: Optional[int] = None) -> None:
        all_sessions = self._session_choices(chat_id)
        visible_sessions, safe_page, total_pages, start_index = self._paginate_items(all_sessions, page, SESSIONS_PAGE_SIZE)
        self._send_or_edit_panel(
            chat_id,
            self._session_menu_text(chat_id, visible_sessions, page=safe_page, total_pages=total_pages, start_index=start_index),
            self._session_menu_markup(chat_id, visible_sessions, page=safe_page, total_pages=total_pages, start_index=start_index),
            message_id=message_id,
        )

    def _clear_session(self, chat_id: str) -> str:
        self._clear_pending_input(chat_id)
        state = self._get_chat_state(chat_id)
        old_session = state.get("session_id")
        state["session_id"] = None
        self._save_chat_state()
        if old_session:
            return f"Cleared session {old_session}.\nNext prompt will start a new Codex conversation."
        return "No active session was set.\nNext prompt will start a new Codex conversation."

    def _adopt_unified_session(self, chat_id: str, session: dict[str, Any]) -> None:
        session_id = str(session.get("session_id") or "").strip()
        if not session_id:
            return
        self._upsert_bridge_session(
            session_id,
            chat_id=chat_id,
            cwd=str(session.get("cwd") or self.config.default_cwd),
            title=str(session.get("title") or "Imported conversation"),
            transcript_path=str(session.get("transcript_path") or self._find_codex_rollout_path(session_id) or ""),
            chat_transcript_path=str(self._chat_transcript_path(chat_id)),
            last_result_preview=str(session.get("last_result_preview") or ""),
            source_kind=str(session.get("source_kind") or ""),
            source_label=str(session.get("source_label") or ""),
        )

    def _apply_session_choice(self, chat_id: str, session_id: str) -> tuple[bool, str]:
        target = None
        for item in self._session_choices(chat_id):
            if str(item.get("session_id") or "") == session_id:
                target = item
                break
        if not target:
            return False, "That conversation menu expired. Reopen Chats."
        if str(target.get("source_kind") or "") != "telegram":
            self._adopt_unified_session(chat_id, target)
        return self._switch_session(chat_id, session_id, send_message=False)

    def _status_text(self, chat_id: str) -> str:
        state = self._get_chat_state(chat_id)
        current_job = self._current_job_for_chat(chat_id)
        recent = [job for job in self.recent_jobs if job.chat_id == chat_id][:3]
        lines = [
            "Task status",
            f"time: {local_now_text()}",
            f"project: {Path(state['cwd']).name or state['cwd']}",
            f"session: {state.get('session_id') or '(new conversation)'}",
            "",
        ]
        if current_job:
            elapsed = duration_text(time.time() - current_job.started_at)
            since_event = duration_text(time.time() - current_job.last_event_at)
            lines.extend(
                [
                    "Running now",
                    f"job: #{current_job.job_id}",
                    f"stage: {current_job.last_stage}",
                    f"elapsed: {elapsed}",
                    f"last activity: {since_event} ago",
                    f"mode: {current_job.session_mode}",
                    f"prompt: {preview_text(current_job.prompt, 160)}",
                    "",
                ]
            )
        else:
            lines.extend(
                [
                    "Running now",
                    "No active task for this chat.",
                    "",
                ]
            )
        if recent:
            lines.append("Recent tasks")
            for job in recent:
                outcome = "canceled" if job.canceled else ("timeout" if job.timed_out else job.status)
                if job.completed_at:
                    when_text = duration_text(max(0, time.time() - job.completed_at)) + " ago"
                else:
                    when_text = "just now"
                lines.append(f"#{job.job_id} | {outcome} | {when_text}")
                lines.append(f"prompt: {preview_text(job.prompt, 120)}")
            lines.append("")
        lines.extend(
            [
                "Bridge",
                f"max parallel jobs: {self.config.max_concurrent_jobs}",
                f"access: {self._access_mode_label()}",
                f"sandbox: {self.config.codex_sandbox}",
                f"approval policy: {self.config.codex_approval_policy}",
            ]
        )
        return "\n".join(lines)

    def _status_markup(self, chat_id: str) -> dict[str, Any]:
        current_job = self._current_job_for_chat(chat_id)
        row_two = [{"text": MENU_HOME_LABEL, "callback_data": "nav:home"}]
        if current_job:
            row_two.append({"text": MENU_CANCEL_LABEL, "callback_data": "act:cancel"})
        return {
            "inline_keyboard": [
                [
                    {"text": "Refresh", "callback_data": "nav:status"},
                    {"text": "Current Chat", "callback_data": "nav:current"},
                ],
                row_two,
            ]
        }

    def _send_status_panel(self, chat_id: str, message_id: Optional[int] = None) -> None:
        self._send_or_edit_panel(chat_id, self._status_text(chat_id), self._status_markup(chat_id), message_id=message_id)

    def _sorted_bridge_sessions(self, chat_id: str, include_all: bool = False) -> list[dict[str, Any]]:
        with self.state_lock:
            sessions = list(self.bridge_index.values())
        if not include_all:
            sessions = [item for item in sessions if str(item.get("chat_id")) == chat_id]
        sessions.sort(key=lambda item: str(item.get("updated_at", "")), reverse=True)
        return sessions

    def _sorted_unified_sessions(self, chat_id: str) -> list[dict[str, Any]]:
        state = self._get_chat_state(chat_id)
        current_session = str(state.get("session_id") or "").strip()
        current_cwd_key = self._path_key(str(state.get("cwd") or ""))
        sessions = self._unified_sessions(chat_id)
        sessions.sort(
            key=lambda item: (
                int(str(item.get("session_id") or "") == current_session),
                int(self._path_key(str(item.get("cwd") or "")) == current_cwd_key),
                str(item.get("updated_at") or ""),
                int(item.get("message_count", 0) or 0),
            ),
            reverse=True,
        )
        return sessions

    def _switch_session(self, chat_id: str, argument: str, *, send_message: bool = True) -> tuple[bool, str]:
        with self.jobs_lock:
            if chat_id in self.chat_running_jobs:
                running_job_id = self.chat_running_jobs[chat_id]
                reply = f"Job #{running_job_id} is still running for this chat.\nWait for it to finish before switching sessions."
                if send_message:
                    self._send_text(chat_id, reply, kind="error", source="bridge")
                return False, reply

        target = self._resolve_session_target(chat_id, argument)
        if not target:
            reply = "Session not found.\nUse /history to get the numbered list, then /use <number>."
            if send_message:
                self._send_text(chat_id, reply, kind="error", source="bridge")
            return False, reply

        if str(target.get("source_kind") or "") != "telegram":
            self._adopt_unified_session(chat_id, target)
        self._clear_pending_input(chat_id)
        state = self._get_chat_state(chat_id)
        state["session_id"] = str(target.get("session_id"))
        if target.get("cwd"):
            state["cwd"] = str(target["cwd"])
        self._save_chat_state()

        reply = (
            "Switched active session\n"
            f"title: {target.get('title', '(untitled)')}\n"
            f"session: {target.get('session_id')}\n"
            f"cwd: {target.get('cwd', state['cwd'])}"
        )
        if send_message:
            self._send_text(
                chat_id,
                reply,
                kind="status",
                source="bridge",
                session_id=str(target.get("session_id") or ""),
            )
        title = str(target.get("title") or "(untitled)")
        source_label = str(target.get("source_label") or "Local")
        return True, f"Conversation set to [{source_label}] {preview_text(title, 60)}."

    def _resolve_session_target(self, chat_id: str, argument: str) -> Optional[dict[str, Any]]:
        query = argument.strip()
        if not query:
            return None
        sessions = self._sorted_unified_sessions(chat_id)
        if query.isdigit():
            index = int(query)
            if 1 <= index <= len(sessions):
                return sessions[index - 1]
            return None
        for item in sessions:
            if str(item.get("session_id") or "") == query:
                return item
        matches = [item for item in sessions if str(item.get("session_id", "")).startswith(query)]
        if len(matches) == 1:
            return matches[0]
        return None

    def _rename_current_session(self, chat_id: str, title: str) -> None:
        state = self._get_chat_state(chat_id)
        session_id = str(state.get("session_id") or "").strip()
        if not session_id:
            self._send_text(chat_id, "No active session to rename.\nStart or switch to a session first.", kind="error", source="bridge")
            return
        clean_title = derive_title(title, fallback="Telegram session")
        self._upsert_bridge_session(session_id, chat_id=chat_id, cwd=state["cwd"], title=clean_title, force_title=True)
        self._send_text(
            chat_id,
            f"Renamed active session.\nTitle: {clean_title}\nSession: {session_id}",
            kind="status",
            source="bridge",
            session_id=session_id,
        )

    def _where_text(self, chat_id: str) -> str:
        state = self._get_chat_state(chat_id)
        session_id = state.get("session_id")
        lines = [
            "Current routing",
            f"cwd: {state['cwd']}",
            f"session: {session_id or '(none)'}",
            f"chat transcript: {self._chat_transcript_path(chat_id)}",
        ]
        if session_id:
            meta = self.bridge_index.get(session_id, {})
            lines.append(f"session transcript: {self._session_transcript_path(session_id)}")
            lines.append(f"bridge title: {meta.get('title', '(unknown)')}")
            lines.append(f"last updated: {meta.get('updated_at', '(unknown)')}")
            lines.append("switch: /history then /use <number>")
        else:
            lines.append("session transcript: (none yet)")
        return "\n".join(lines)

    def _history_text(self, chat_id: str, argument: str) -> str:
        sessions = self._sorted_unified_sessions(chat_id)
        limit = 5
        if argument.strip().isdigit():
            limit = max(1, min(20, int(argument.strip())))
            sessions = sessions[:limit]
        elif argument.strip().lower() != "all":
            sessions = sessions[:limit]
        if not sessions:
            return "No conversation history yet."

        current_session = self._get_chat_state(chat_id).get("session_id")
        lines = ["Conversation history"]
        for index, item in enumerate(sessions, start=1):
            marker = " (current)" if item.get("session_id") == current_session else ""
            lines.append(f"{index}. [{item.get('source_label', 'Local')}] {item.get('title', '(untitled)')}{marker}")
            lines.append(f"id: {item.get('session_id', '(none)')}")
            lines.append(f"updated: {human_timestamp(str(item.get('updated_at') or ''))} ({relative_age_text(str(item.get('updated_at') or ''))})")
            lines.append(f"cwd: {item.get('cwd', '(unknown)')}")
            lines.append(f"use: /use {index}")
            lines.append(f"transcript: {item.get('transcript_path', '(missing)')}")
        return "\n".join(lines)

    def _transcript_text(self, chat_id: str, argument: str) -> str:
        requested_session = argument.strip() or self._get_chat_state(chat_id).get("session_id")
        lines = [
            "Transcript locations",
            f"chat transcript: {self._chat_transcript_path(chat_id)}",
        ]
        if requested_session:
            meta = self.bridge_index.get(requested_session, {})
            lines.append(f"session: {requested_session}")
            lines.append(f"session transcript: {self._session_transcript_path(requested_session)}")
            rollout_path = self._find_codex_rollout_path(requested_session)
            lines.append(f"codex rollout: {rollout_path or '(not found yet)'}")
            if meta:
                lines.append(f"title: {meta.get('title', '(untitled)')}")
                lines.append(f"updated_at: {meta.get('updated_at', '(unknown)')}")
        else:
            lines.append("session transcript: (no active session)")
        lines.append(f"bridge index: {BRIDGE_INDEX_PATH}")
        lines.append(f"codex session index: {CODEX_SESSION_INDEX_PATH}")
        lines.append(f"codex history: {CODEX_HISTORY_PATH}")
        return "\n".join(lines)

    def _find_codex_rollout_path(self, session_id: str) -> Optional[str]:
        return self._get_rollout_path(session_id)

    def _jobs_text(self, chat_id: str) -> str:
        with self.jobs_lock:
            active = [job for job in self.active_jobs.values() if job.chat_id == chat_id]
            recent = [job for job in self.recent_jobs if job.chat_id == chat_id][:10]
        lines = ["Jobs"]
        if active:
            lines.append("Active:")
            for job in active:
                lines.append(
                    f"#{job.job_id} | {job.status} | mode={job.session_mode} | cwd={job.cwd} | session={job.final_session_id or job.prior_session_id or '(new)'}"
                )
        else:
            lines.append("Active: none")
        if recent:
            lines.append("Recent:")
            for job in recent:
                outcome = "timeout" if job.timed_out else ("canceled" if job.canceled else "done")
                lines.append(f"#{job.job_id} | {job.status} | {outcome} | {preview_text(job.prompt, 70)}")
        return "\n".join(lines)

    def _cancel_job(self, chat_id: str, job_id: int, *, send_message: bool = True) -> bool:
        with self.jobs_lock:
            job = self.active_jobs.get(job_id)
        if not job or job.chat_id != chat_id:
            if send_message:
                self._send_text(chat_id, f"Job #{job_id} is not running for this chat.", kind="error", source="bridge")
            return False
        job.canceled = True
        if job.process and job.process.poll() is None:
            self._terminate_process_tree(job.process.pid)
        if send_message:
            self._send_text(
                chat_id,
                f"Cancellation requested for job #{job_id}.",
                kind="status",
                source="bridge",
                session_id=job.final_session_id or job.prior_session_id,
            )
        return True

    def _cancel_running_job_for_chat(self, chat_id: str, *, send_message: bool) -> str:
        with self.jobs_lock:
            job_id = self.chat_running_jobs.get(chat_id)
        if job_id is None:
            if send_message:
                self._send_text(chat_id, "No running job for this chat.", kind="status", source="bridge")
            return "No running job for this chat."
        self._cancel_job(chat_id, job_id, send_message=send_message)
        return f"Cancellation requested for job #{job_id}."

    def _terminate_process_tree(self, pid: int) -> None:
        try:
            if os.name == "nt":
                subprocess.run(
                    ["taskkill", "/PID", str(pid), "/T", "/F"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                )
            else:
                os.kill(pid, 15)
        except Exception:
            pass

    def _start_job(self, chat_id: str, prompt: str) -> None:
        state = self._get_chat_state(chat_id)
        cwd = state["cwd"]
        prior_session_id = state.get("session_id")
        session_mode = "resume" if prior_session_id else "new"

        with self.jobs_lock:
            if chat_id in self.chat_running_jobs:
                running_job_id = self.chat_running_jobs[chat_id]
                self._send_text(
                    chat_id,
                    f"Job #{running_job_id} is still running for this chat.\nWait for it to finish or use /cancel {running_job_id}.",
                    kind="error",
                    source="bridge",
                    session_id=prior_session_id,
                )
                return
            if len(self.active_jobs) >= self.config.max_concurrent_jobs:
                self._send_text(
                    chat_id,
                    f"The bridge is already running {len(self.active_jobs)} jobs.\nTry again in a moment.",
                    kind="error",
                    source="bridge",
                    session_id=prior_session_id,
                )
                return
            job_id = self.next_job_id
            self.next_job_id += 1
            job = Job(
                job_id=job_id,
                chat_id=chat_id,
                prompt=prompt,
                cwd=cwd,
                session_mode=session_mode,
                prior_session_id=prior_session_id,
                prompt_title=derive_title(prompt),
            )
            self._set_job_stage(job, "Queued")
            self.active_jobs[job_id] = job
            self.chat_running_jobs[chat_id] = job_id
            self.recent_jobs.insert(0, job)
            self.recent_jobs = self.recent_jobs[:RECENT_JOB_LIMIT]
            state["last_job_id"] = job_id
            self._save_chat_state()

        threading.Thread(target=self._run_job, args=(job,), daemon=True).start()

    def _build_codex_command(self, job: Job) -> list[str]:
        command = ["cmd.exe", "/c", str(self.codex_cmd), "exec"]

        wants_full_auto = (
            self.config.codex_approval_policy.lower() == "never"
            and self.config.codex_sandbox.lower() == "workspace-write"
        )

        if self.config.codex_model:
            command.extend(["--model", self.config.codex_model])
        if self.config.codex_profile:
            command.extend(["--profile", self.config.codex_profile])
        if wants_full_auto:
            command.append("--full-auto")
        elif self.config.codex_sandbox:
            command.extend(["--sandbox", self.config.codex_sandbox])
        command.extend(self.config.codex_extra_args)

        if job.session_mode == "resume":
            command.append("resume")
            command.extend(["--skip-git-repo-check", "--json"])
            if job.prior_session_id:
                command.append(job.prior_session_id)
            command.append(job.prompt)
            return command

        command.extend(["--skip-git-repo-check", "--json"])
        command.append(job.prompt)
        return command

    def _run_job(self, job: Job) -> None:
        stdout_queue: "queue.Queue[str]" = queue.Queue()
        stderr_queue: "queue.Queue[str]" = queue.Queue()
        last_heartbeat = time.monotonic()

        try:
            self._set_job_stage(job, "Launching Codex")
            self._send_progress(job, "Task accepted. Launching Codex.", force=True)
            if job.prior_session_id:
                job.final_session_id = job.prior_session_id
                self._ensure_session_registered(job.chat_id, job.prior_session_id, job.cwd, job.prompt_title, job.job_id)
                self._log_session_transcript(job.prior_session_id, job.chat_id, "user", "prompt", job.prompt, "telegram")
                self._append_codex_history(job.prior_session_id, job.prompt)
                job.prompt_logged = True

            process = subprocess.Popen(
                self._build_codex_command(job),
                cwd=job.cwd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
            )
            job.process = process
            self._set_job_stage(job, "Waiting for Codex output")
            threading.Thread(target=self._read_stream, args=(process.stdout, stdout_queue), daemon=True).start()
            threading.Thread(target=self._read_stream, args=(process.stderr, stderr_queue), daemon=True).start()

            while True:
                self._drain_stderr(job, stderr_queue)
                saw_output = self._drain_stdout(job, stdout_queue)
                if saw_output:
                    last_heartbeat = time.monotonic()

                self._flush_pending_progress(job)

                if process.poll() is not None and stdout_queue.empty() and stderr_queue.empty():
                    break

                if self.config.codex_timeout_seconds > 0 and (time.time() - job.started_at) > self.config.codex_timeout_seconds:
                    job.timed_out = True
                    self._terminate_process_tree(process.pid)
                    break

                if self.config.heartbeat_seconds > 0 and (time.monotonic() - last_heartbeat) >= self.config.heartbeat_seconds:
                    self._send_progress(job, "Still working. Waiting for the next Codex update.", force=True, heartbeat=True)
                    last_heartbeat = time.monotonic()

                time.sleep(0.2)

            self._drain_stdout(job, stdout_queue)
            self._drain_stderr(job, stderr_queue)
            return_code = process.poll() if process else None
            if job.timed_out:
                job.status = "timeout"
            elif job.canceled:
                job.status = "canceled"
            elif return_code == 0:
                job.status = "completed"
            else:
                job.status = "failed"
            job.completed_at = time.time()

            final_session = job.final_session_id or job.prior_session_id
            result_text = job.result_text.strip()
            error_text = job.error_text.strip()
            if job.status == "completed" and result_text:
                self._send_text(
                    job.chat_id,
                    result_text,
                    kind="result",
                    source="codex",
                    session_id=final_session,
                )
                job.result_logged = True
            elif job.status == "canceled":
                self._send_text(
                    job.chat_id,
                    "Canceled.",
                    kind="status",
                    source="bridge",
                    session_id=final_session,
                )
            elif job.status == "timeout":
                message = f"Timed out after {self.config.codex_timeout_seconds}s."
                if error_text:
                    message += f"\n\nstderr:\n{error_text}"
                self._send_text(
                    job.chat_id,
                    message,
                    kind="error",
                    source="bridge",
                    session_id=final_session,
                )
            else:
                detail = error_text or "No final answer returned."
                self._send_text(
                    job.chat_id,
                    f"Execution failed.\n\nstderr:\n{detail}",
                    kind="error",
                    source="bridge",
                    session_id=final_session,
                )

            if final_session:
                self._upsert_bridge_session(
                    final_session,
                    chat_id=job.chat_id,
                    cwd=job.cwd,
                    title=job.prompt_title,
                    last_job_id=job.job_id,
                    last_result_preview=preview_text(job.result_text or job.error_text, 120),
                )

        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            traceback.print_exc()
            job.status = "failed"
            job.error_text = error
            job.completed_at = time.time()
            self._set_job_stage(job, "Bridge error")
            self._send_text(
                job.chat_id,
                f"Execution failed.\n\nstderr:\n{error}",
                kind="error",
                source="bridge",
                session_id=job.final_session_id or job.prior_session_id,
            )
        finally:
            with self.jobs_lock:
                self.active_jobs.pop(job.job_id, None)
                self.chat_running_jobs.pop(job.chat_id, None)

    def _read_stream(self, stream: Any, target: "queue.Queue[str]") -> None:
        if stream is None:
            return
        try:
            for line in iter(stream.readline, ""):
                target.put(line.rstrip("\r\n"))
        finally:
            try:
                stream.close()
            except Exception:
                pass

    def _drain_stdout(self, job: Job, target: "queue.Queue[str]") -> bool:
        saw_output = False
        while True:
            try:
                line = target.get_nowait()
            except queue.Empty:
                break
            saw_output = True
            if not line.strip():
                continue
            try:
                event = json.loads(line)
            except Exception:
                continue
            self._handle_codex_event(job, event)
        return saw_output

    def _drain_stderr(self, job: Job, target: "queue.Queue[str]") -> None:
        saw_stderr = False
        while True:
            try:
                line = target.get_nowait()
            except queue.Empty:
                break
            if line:
                saw_stderr = True
                job.stderr_lines.append(line)
        job.error_text = "\n".join(job.stderr_lines[-40:])
        if saw_stderr and job.status == "running":
            self._set_job_stage(job, "Receiving stderr output")

    def _handle_codex_event(self, job: Job, event: dict[str, Any]) -> None:
        event_type = str(event.get("type", ""))

        if event_type == "thread.started":
            thread_id = str(event.get("thread_id", "")).strip()
            if thread_id:
                self._set_job_stage(job, "Conversation ready")
                job.final_session_id = thread_id
                self._ensure_session_registered(job.chat_id, thread_id, job.cwd, job.prompt_title, job.job_id)
                if not job.prompt_logged:
                    self._log_session_transcript(thread_id, job.chat_id, "user", "prompt", job.prompt, "telegram")
                    self._append_codex_history(thread_id, job.prompt)
                    job.prompt_logged = True
            return

        if event_type == "item.started":
            item = event.get("item") or {}
            self._set_job_stage(job, self._stage_text_for_item(item, started=True))
            self._flush_pending_agent_message(job)
            live_text = self._render_live_item(job, item, started=True)
            if live_text:
                self._send_progress(job, live_text)
            return

        if event_type == "item.completed":
            item = event.get("item") or {}
            item_type = str(item.get("type", ""))
            if item_type == "agent_message":
                text = self._extract_text(item)
                if text:
                    self._set_job_stage(job, "Drafting final answer")
                    if job.pending_agent_message and job.pending_agent_message != text:
                        self._send_progress(job, job.pending_agent_message)
                    job.result_text = text
                    job.pending_agent_message = text
                return
            self._set_job_stage(job, self._stage_text_for_item(item, started=False))
            self._flush_pending_agent_message(job)
            live_text = self._render_live_item(job, item, started=False)
            if live_text:
                self._send_progress(job, live_text)
            return

        if event_type == "turn.completed":
            self._set_job_stage(job, "Finalizing answer")
            return

        live_text = self._render_generic_event(event)
        if live_text:
            self._flush_pending_agent_message(job)
            self._send_progress(job, live_text)

    def _trim_progress_text(self, text: str, limit: int = 3200) -> str:
        cleaned = text.rstrip()
        if len(cleaned) <= limit:
            return cleaned
        return cleaned[: limit - 18].rstrip() + "\n... [truncated]"

    def _format_progress_text(self, job: Job, text: str, *, heartbeat: bool) -> str:
        body = str(text or "").strip()
        lines = [
            f"Working on job #{job.job_id}",
            f"stage: {job.last_stage}",
            f"elapsed: {duration_text(time.time() - job.started_at)}",
        ]
        if heartbeat:
            lines.append(f"last update: {duration_text(max(0, time.time() - job.last_event_at))} ago")
            if not body:
                body = "Still working."
        if body:
            lines.extend(["", body])
        return self._trim_progress_text("\n".join(lines))

    def _publish_progress(self, job: Job, text: str) -> None:
        if not text:
            return
        try:
            self._send_text(
                job.chat_id,
                text,
                kind="progress",
                source="bridge",
                session_id=job.final_session_id or job.prior_session_id,
            )
            job.visible_update_count += 1
            job.last_progress_text = text
            job.last_progress_sent_at = time.time()
            job.pending_progress_text = ""
        except Exception as exc:
            print(f"[bridge] progress send failed: {exc}", file=sys.stderr, flush=True)

    def _flush_pending_progress(self, job: Job, *, force: bool = False) -> None:
        text = job.pending_progress_text.strip()
        if not text:
            return
        if not force and (time.time() - job.last_progress_sent_at) < 2.0:
            return
        if text == job.last_progress_text:
            job.pending_progress_text = ""
            return
        self._publish_progress(job, text)

    def _send_progress(self, job: Job, text: str, *, force: bool = False, heartbeat: bool = False) -> None:
        formatted = self._format_progress_text(job, text, heartbeat=heartbeat)
        if not formatted or formatted == job.last_progress_text:
            return
        if not force and job.last_progress_sent_at and (time.time() - job.last_progress_sent_at) < 2.0:
            job.pending_progress_text = formatted
            return
        self._publish_progress(job, formatted)

    def _stage_text_for_item(self, item: dict[str, Any], *, started: bool) -> str:
        item_type = str(item.get("type", "")).strip()
        if item_type == "command_execution":
            command_text = self._display_command_text(str(item.get("command") or "").strip())
            if started:
                return f"Running command: {preview_text(command_text, 90)}"
            return "Command finished"
        if item_type in {"tool_call", "function_call"}:
            name = str(item.get("name") or item.get("tool_name") or "tool").strip()
            return f"Using tool: {name}" if started else f"Tool finished: {name}"
        if item_type in {"reasoning", "commentary"}:
            return "Thinking"
        if item_type == "agent_message":
            return "Drafting answer"
        if item_type:
            return f"{item_type} {'started' if started else 'finished'}"
        return "Working"

    def _flush_pending_agent_message(self, job: Job) -> None:
        text = job.pending_agent_message.strip()
        if not text:
            return
        self._send_progress(job, text)
        job.pending_agent_message = ""

    def _extract_text(self, payload: dict[str, Any]) -> str:
        if isinstance(payload.get("text"), str):
            return payload["text"]
        content = payload.get("content")
        if isinstance(content, list):
            parts: list[str] = []
            for item in content:
                if isinstance(item, dict):
                    text = item.get("text")
                    if isinstance(text, str):
                        parts.append(text)
            if parts:
                return "\n".join(parts).strip()
        message = payload.get("message")
        if isinstance(message, str):
            return message
        return ""

    def _render_live_item(self, job: Job, item: dict[str, Any], *, started: bool) -> str:
        item_type = str(item.get("type", ""))
        name = str(item.get("name") or item.get("tool_name") or item.get("call_id") or "").strip()
        text = self._extract_text(item)
        if item_type == "command_execution":
            return self._render_command_execution(job, item, started=started)
        if started:
            if item_type in {"tool_call", "function_call"}:
                prefix = f"Tool {name}" if name else "Tool call"
                return f"{prefix} started"
            return ""
        if item_type in {"tool_call", "function_call"}:
            summary = preview_text(text or json.dumps(item, ensure_ascii=False), 180)
            prefix = f"Tool {name}" if name else "Tool call"
            return f"{prefix}\n{summary}"
        if item_type in {"reasoning", "commentary"} and text:
            return text
        if item_type and text and item_type != "agent_message":
            return f"{item_type}\n{text}"
        return ""

    def _display_command_text(self, raw_command: str) -> str:
        text = raw_command.strip()
        for marker in (" -Command '", ' -Command "', " /c '", ' /c "'):
            if marker not in text:
                continue
            _, _, remainder = text.partition(marker)
            if remainder.endswith(("'", '"')):
                remainder = remainder[:-1]
            remainder = remainder.strip()
            if remainder:
                return remainder
        return text

    def _trim_terminal_output(self, text: str, limit: int = 1800) -> str:
        cleaned = text.rstrip()
        if len(cleaned) <= limit:
            return cleaned
        return cleaned[: limit - 22].rstrip() + "\n... [output truncated]"

    def _render_command_execution(self, job: Job, item: dict[str, Any], *, started: bool) -> str:
        command_text = self._display_command_text(str(item.get("command") or "").strip())
        if started:
            return f"PS {job.cwd}> {command_text}"

        output = self._trim_terminal_output(str(item.get("aggregated_output") or ""))
        exit_code = item.get("exit_code")
        lines: list[str] = []
        if output:
            lines.append(output)
        if exit_code is not None:
            lines.append(f"[exit {exit_code}]")
        if not lines:
            lines.append("[command finished]")
        return "\n".join(lines)

    def _render_generic_event(self, event: dict[str, Any]) -> str:
        event_type = str(event.get("type", ""))
        if event_type in {"turn.started", "turn.completed", "item.started", "item.completed", "item.updated"}:
            return ""
        message = event.get("message") or event.get("msg")
        if isinstance(message, str) and message.strip():
            return message.strip()
        return ""

    def _ensure_session_registered(
        self,
        chat_id: str,
        session_id: str,
        cwd: str,
        title: str,
        job_id: int,
    ) -> None:
        state = self._get_chat_state(chat_id)
        state["session_id"] = session_id
        state["cwd"] = cwd
        state["last_job_id"] = job_id
        self._save_chat_state()
        self._upsert_bridge_session(
            session_id,
            chat_id=chat_id,
            cwd=cwd,
            title=title,
            transcript_path=str(self._session_transcript_path(session_id)),
            chat_transcript_path=str(self._chat_transcript_path(chat_id)),
            last_job_id=job_id,
            source_kind="telegram",
            source_label="TG",
        )
        self._append_codex_session_index(session_id, title)

    def _upsert_bridge_session(
        self,
        session_id: str,
        *,
        chat_id: Optional[str] = None,
        cwd: Optional[str] = None,
        title: Optional[str] = None,
        transcript_path: Optional[str] = None,
        chat_transcript_path: Optional[str] = None,
        last_job_id: Optional[int] = None,
        last_result_preview: Optional[str] = None,
        source_kind: Optional[str] = None,
        source_label: Optional[str] = None,
        message_delta: int = 0,
        force_title: bool = False,
    ) -> None:
        with self.state_lock:
            entry = self.bridge_index.setdefault(session_id, {})
            entry.setdefault("session_id", session_id)
            entry.setdefault("created_at", utc_now_iso())
            entry["updated_at"] = utc_now_iso()
            if chat_id is not None:
                entry["chat_id"] = chat_id
            if cwd is not None:
                entry["cwd"] = cwd
            if transcript_path is not None:
                entry["transcript_path"] = transcript_path
            if chat_transcript_path is not None:
                entry["chat_transcript_path"] = chat_transcript_path
            if last_job_id is not None:
                entry["last_job_id"] = last_job_id
            if last_result_preview is not None:
                entry["last_result_preview"] = last_result_preview
            if source_kind is not None:
                entry["source_kind"] = source_kind
            if source_label is not None:
                entry["source_label"] = source_label
            if title is not None and (
                force_title
                or is_placeholder_title(str(entry.get("title", "")))
                or not str(entry.get("title", "")).strip()
            ):
                entry["title"] = title
            entry["message_count"] = int(entry.get("message_count", 0)) + int(message_delta)
            save_json(BRIDGE_INDEX_PATH, self.bridge_index)

    def _append_codex_session_index(self, session_id: str, title: str) -> None:
        if session_id in self.codex_index_ids:
            return
        try:
            append_jsonl(
                CODEX_SESSION_INDEX_PATH,
                {
                    "id": session_id,
                    "thread_name": f"[TG] {title}",
                    "updated_at": utc_now_iso(),
                },
            )
            self.codex_index_ids.add(session_id)
        except Exception as exc:
            print(f"[bridge] codex session index sync skipped: {exc}", file=sys.stderr, flush=True)

    def _append_codex_history(self, session_id: str, text: str) -> None:
        try:
            append_jsonl(
                CODEX_HISTORY_PATH,
                {
                    "session_id": session_id,
                    "ts": int(time.time()),
                    "text": text,
                },
            )
        except Exception as exc:
            print(f"[bridge] codex history sync skipped: {exc}", file=sys.stderr, flush=True)


def main() -> None:
    env_path = BASE_DIR / ".env.local"
    if not env_path.exists():
        env_path = BASE_DIR / ".env"
    config = Config.from_env(load_dotenv(env_path))
    bridge = TelegramCodexBridge(config)
    bridge.run()


if __name__ == "__main__":
    main()
