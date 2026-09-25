from __future__ import annotations

import base64
import ctypes
import http.client
import json
import logging
import os
import socket
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.request
from logging.handlers import RotatingFileHandler
from pathlib import Path

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

# =========================
# AI Dispatcher 2.2.19
# =========================

VERSION = "2.2.19"

HOME = Path.home()
STATE_PATH = HOME / ".ai-dispatcher-state.json"
CONTROL_PATH = HOME / ".ai-dispatcher-control.json"
LOG_PATH = HOME / "ai-dispatcher.log"

CDP_HOST = "127.0.0.1"
CDP_PORT = 9223
CDP = f"http://{CDP_HOST}:{CDP_PORT}"

CHROME_PATH = Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe")
CHROME_PROFILE = HOME / "AI-Dispatcher-Chrome"

SIGNAL_URL = (
    "https://raw.githubusercontent.com/"
    "dvikt33-ux/arena-archicad-project/"
    "agent-handoff/.agent-handoff/signal.json"
)
SIGNAL_API_URL = (
    "https://api.github.com/repos/"
    "dvikt33-ux/arena-archicad-project/contents/"
    ".agent-handoff/signal.json?ref=agent-handoff"
)
SIGNAL_FETCH_TIMEOUT = 8

CHATGPT_HOME = "https://chatgpt.com/"
ARENA_URL = "https://arena.ai/agent/01a09014-9139-71e7-b51b-5b3f8a49d904"

CONTROL_BOOTSTRAP = (
    "Служебный чат 01 — CONTROL & BRIDGE. "
    "Этот чат используется только локальным AI Dispatcher как машинный транспортный канал "
    "в обычном ChatGPT, не в Codex/Work. "
    "Когда приходит сообщение вида «Проверь GitHub. turn_id=N», открой через подключённый GitHub "
    "репозиторий dvikt33-ux/arena-archicad-project, ветку agent-handoff, файл "
    ".agent-handoff/signal.json; проверь, что turn_id совпадает, выполни только инструкцию из поля "
    "message и при необходимости запиши следующий handoff обратно в этот signal.json. "
    "Не запускай, не открывай и не расходуй Codex/Work, если signal не содержит точное JSON-поле "
    "requires_codex=true. Отсутствующий requires_codex означает false. "
    "Не меняй main и arena/local-agent-v0. Не включай Phase 2 или live mailbox без явной инструкции "
    "в signal. Этот чат не предназначен для ручной переписки пользователя. "
    "На это инициализирующее сообщение ответь только: CONTROL READY."
)

CHECK_INTERVAL = 5
ARENA_RETRY_SECONDS = 60
CONTROL_RETRY_SECONDS = 15
PAGE_TIMEOUT = 15000
CHROME_START_TIMEOUT = 25
CONTROL_READY_MARKER = "CONTROL READY"
CONTROL_BOOTSTRAP_MARKER = "Служебный чат 01 — CONTROL & BRIDGE"
CONTROL_RECOVERY_CHECKS = 3
CONTROL_READY_GRACE_SECONDS = 20
CONTROL_RESTORE_WAIT_SECONDS = 6
CONTROL_RESTORE_COOLDOWN_SECONDS = 60
CONTROL_RESTORE_GOTO_TIMEOUT = 10000
RESTORE_PAGE_MARK = "ai-dispatcher-restore"
REBIND_PAGE_MARK = "ai-dispatcher-rebind"
REBIND_REPLACEMENT_PAGE_MARK = "ai-dispatcher-rebind-replacement"
REBIND_REPROVISION_PAGE_MARK = "ai-dispatcher-rebind-reprovision"
CONTROL_PROVISION_PAGE_MARK = "ai-dispatcher-provision"
CONTROL_SERVICE_PAGE_MARKS = frozenset(
    {
        RESTORE_PAGE_MARK,
        REBIND_PAGE_MARK,
        REBIND_REPLACEMENT_PAGE_MARK,
        REBIND_REPROVISION_PAGE_MARK,
        CONTROL_PROVISION_PAGE_MARK,
    }
)
CONTROL_REBIND_COOLDOWN_SECONDS = 60
CONTROL_REBIND_URL_WAIT = 20
BLANK_REBIND_POLLS = 6
BLANK_REBIND_SECONDS = 30
CONTROL_REBIND_COMPOSER_WAIT = 20
CONTROL_FINALIZE_URL_WAIT = 60
CONTROL_REPROVISION_URL_WAIT = 90
CONTROL_SUBMIT_CONFIRM_SECONDS = 8
REBIND_COMPOSER_POLL_SECONDS = 0.5
REBIND_FAILURE_REASONS = (
    "no_composer",
    "signed_out",
    "hard_unavailable",
    "no_new_url",
    "goto",
    "missing_page",
    "unexpected_url",
    "failed",
    "no_evidence",
    "submit_unconfirmed",
)
CONTROL_ERROR_MARKERS = (
    "something went wrong",
    "unable to load",
    "network error",
    "conversation not found",
    "не удалось загрузить",
)
CONTROL_UNAVAILABLE_MARKERS = CONTROL_ERROR_MARKERS + (
    "unable to load this conversation",
    "unable to load conversation",
    "couldn't load this conversation",
    "could not load this conversation",
    "this conversation could not be loaded",
    "не удалось загрузить этот разговор",
)
SIGN_IN_MARKERS = (
    "log in",
    "sign in",
    "войти",
    "log in to chatgpt",
)

TERMINAL_STATUSES = {"cancelled", "canceled", "done"}
HOLD_STATUSES = {"blocked", "paused", "idle"}
READY_STATUSES = {"ready", "pending", "queued"}

WAKE_CONFIRM_SECONDS = 90
MAX_WAKE_ATTEMPTS = 3

MUTEX_NAME = r"Local\AI_Dispatcher_22"


# -------------------------
# Logging
# -------------------------

logger = logging.getLogger("ai-dispatcher")
logger.setLevel(logging.INFO)

_file_handler = RotatingFileHandler(
    LOG_PATH,
    maxBytes=1_000_000,
    backupCount=3,
    encoding="utf-8",
)
_file_handler.setFormatter(
    logging.Formatter("%(asctime)s | %(levelname)s | %(message)s")
)
logger.addHandler(_file_handler)

if sys.stdout and getattr(sys.stdout, "isatty", lambda: False)():
    _console = logging.StreamHandler(sys.stdout)
    _console.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(_console)


def log(message: str) -> None:
    logger.info(message)


# -------------------------
# Single instance
# -------------------------

_MUTEX_HANDLE = None


def acquire_single_instance() -> None:
    global _MUTEX_HANDLE
    if os.name != "nt":
        return

    kernel32 = ctypes.windll.kernel32
    handle = kernel32.CreateMutexW(None, False, MUTEX_NAME)
    if not handle:
        raise RuntimeError("Не удалось создать mutex AI Dispatcher.")

    ERROR_ALREADY_EXISTS = 183
    if kernel32.GetLastError() == ERROR_ALREADY_EXISTS:
        log("AI Dispatcher уже запущен. Второй экземпляр завершён.")
        sys.exit(0)

    _MUTEX_HANDLE = handle


# -------------------------
# State
# -------------------------

def default_state() -> dict:
    return {"last_turn_id": 0, "inflight": None}


def load_state() -> dict:
    if not STATE_PATH.exists():
        return default_state()

    try:
        data = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except Exception as exc:
        log(f"STATE: повреждён state-файл, использую безопасный default: {exc}")
        return default_state()

    state = default_state()
    state["last_turn_id"] = int(data.get("last_turn_id", 0) or 0)
    inflight = data.get("inflight")
    state["inflight"] = inflight if isinstance(inflight, dict) else None
    return state


def save_state(state: dict) -> None:
    tmp = STATE_PATH.with_suffix(".tmp")
    tmp.write_text(
        json.dumps(state, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    os.replace(tmp, STATE_PATH)


def is_chatgpt_conversation_url(url: str) -> bool:
    return bool(url) and url.startswith("https://chatgpt.com/c/")


def assistant_has_control_ready(messages: list[dict]) -> bool:
    return any(
        item.get("role") == "assistant"
        and CONTROL_READY_MARKER in str(item.get("text") or "")
        for item in messages
    )


def user_has_bootstrap_marker(messages: list[dict]) -> bool:
    return any(
        item.get("role") == "user"
        and CONTROL_BOOTSTRAP_MARKER in str(item.get("text") or "")
        for item in messages[-60:]
    )


def bootstrap_was_sent(record: dict | None) -> bool:
    """A saved control URL without the flag was written by 2.2.5 after bootstrap."""
    record = record or {}
    url = str(record.get("chatgpt_control_url", "") or "").strip()
    if not is_chatgpt_conversation_url(url):
        return False
    if "bootstrap_sent" not in record:
        return True
    return bool(record.get("bootstrap_sent"))


def conversation_id(url: str) -> str:
    if not is_chatgpt_conversation_url(url):
        return ""
    path = url.split("?", 1)[0].split("#", 1)[0].rstrip("/")
    return path.rsplit("/", 1)[-1]


def conversation_identity(url: str) -> str:
    """UUID used for matching only. WEB: is an alias, not a different chat."""
    ident = conversation_id(url)
    if ident.upper().startswith("WEB:"):
        ident = ident.split(":", 1)[1]
    return ident.lower()


def same_conversation(url: str, expected: str) -> bool:
    left = conversation_identity(url)
    right = conversation_identity(expected)
    return bool(left) and left == right


def is_usable_control_url(url: str) -> bool:
    """Accept the conversation URL the live ChatGPT UI actually emits.

    A /c/WEB:<id> URL is not stale by syntax. Staleness comes from page
    behavior in diagnose_control.
    """
    return is_chatgpt_conversation_url(str(url or "").strip()) and bool(conversation_id(url))


def _last_bootstrap_index(messages: list[dict]) -> int | None:
    for idx in range(len(messages) - 1, -1, -1):
        item = messages[idx]
        if item.get("role") == "user" and CONTROL_BOOTSTRAP_MARKER in str(item.get("text") or ""):
            return idx
    return None


def assistant_after_bootstrap(messages: list[dict]) -> bool:
    start = _last_bootstrap_index(messages)
    if start is None:
        return False
    return any(
        item.get("role") == "assistant" and str(item.get("text") or "").strip()
        for item in messages[start + 1 :]
    )


def assistant_error_after_bootstrap(messages: list[dict]) -> bool:
    start = _last_bootstrap_index(messages)
    if start is None:
        return False
    for item in messages[start + 1 :]:
        if item.get("role") != "assistant":
            continue
        text = str(item.get("text") or "")
        if CONTROL_READY_MARKER in text:
            return False
        lowered = text.lower()
        if any(marker in lowered for marker in CONTROL_ERROR_MARKERS):
            return True
    return False


def normalize_conversation_url(url: str) -> str:
    url = str(url or "").strip()
    if not is_usable_control_url(url):
        return ""
    return url.split("?", 1)[0].split("#", 1)[0]


def positive_control_identity(messages: list[dict], wake: str = "") -> bool:
    """Bootstrap, CONTROL READY, or the pending wake proves this is the control chat."""
    if assistant_has_control_ready(messages) or user_has_bootstrap_marker(messages):
        return True
    wake = str(wake or "").strip()
    if not wake:
        return False
    return any(
        item.get("role") == "user" and str(item.get("text") or "").strip() == wake
        for item in messages[-60:]
    )


def canonicalization_eligible(
    record: dict | None,
    messages: list[dict],
    page_url: str = "",
    wake: str = "",
) -> bool:
    """A different live conversation URL is an alias, not a stale chat, when identity is proven."""
    record = record or {}
    saved = normalize_conversation_url(str(record.get("chatgpt_control_url", "") or ""))
    observed = normalize_conversation_url(page_url)
    if not saved or not observed or saved == observed:
        return False
    if same_conversation(saved, observed):
        return True
    return positive_control_identity(messages, wake) and is_usable_control_url(observed)


def submitted_bootstrap_idle_ready(
    record: dict | None,
    generation_active: bool,
    composer_ready: bool,
    now: float | None = None,
) -> bool:
    """Initialized when bootstrap was submitted, generation stopped, and the composer is usable."""
    if generation_active or not composer_ready:
        return False
    sent_at = (record or {}).get("bootstrap_sent_at")
    if sent_at in (None, ""):
        return False
    try:
        sent_at = float(sent_at)
    except (TypeError, ValueError):
        return False
    if now is None:
        now = time.time()
    return float(now) - sent_at >= CONTROL_READY_GRACE_SECONDS


def hard_unavailable_text(text: str) -> bool:
    """True for a rendered conversation-load failure. Empty text is not a failure."""
    lowered = str(text or "").lower()
    if not lowered.strip():
        return False
    return any(marker in lowered for marker in CONTROL_UNAVAILABLE_MARKERS)


def hard_control_unavailable(messages: list[dict] | None = None, page_unavailable: bool = False) -> bool:
    if page_unavailable:
        return True
    for item in messages or []:
        text = str(item.get("text") or "")
        if CONTROL_BOOTSTRAP_MARKER in text or CONTROL_READY_MARKER in text:
            continue
        if hard_unavailable_text(text):
            return True
    return False


def diagnose_control(
    record: dict | None,
    messages: list[dict],
    page_url: str = "",
    wake: str = "",
    generation_active: bool = False,
    composer_ready: bool = False,
    now: float | None = None,
    page_unavailable: bool = False,
) -> str:
    """Stable token only. Does not include message text."""
    record = record or {}
    messages = list(messages or [])
    saved = str(record.get("chatgpt_control_url", "") or "").strip()
    if assistant_has_control_ready(messages):
        return "ready_marker"
    if page_unavailable:
        return "unavailable"
    if user_has_bootstrap_marker(messages):
        if assistant_error_after_bootstrap(messages):
            return "assistant_error"
        if assistant_after_bootstrap(messages):
            return "ready_fallback"
        if submitted_bootstrap_idle_ready(record, generation_active, composer_ready, now):
            return "ready_idle"
        return "bootstrap_without_response"
    # WEB: ids are valid. A saved conversation is stale only when navigation
    # was observed away from it and the page did not prove this is the same chat.
    if saved and page_url and not url_matches(page_url, saved):
        if not canonicalization_eligible(record, messages, page_url, wake):
            return "stale_url"
    if not messages:
        return "zero_messages"
    if any(
        item.get("role") == "assistant" and str(item.get("text") or "").strip()
        for item in messages
    ):
        return "marker_mismatch"
    return "zero_messages"


def control_is_ready(diagnosis: str) -> bool:
    return diagnosis in {"ready_marker", "ready_fallback", "ready_idle"}


def recovery_allowed(record: dict | None, diagnosis: str, checks: int = 0) -> bool:
    record = record or {}
    if record.get("recovery_used"):
        return False
    if control_is_ready(diagnosis):
        return False
    if diagnosis in {"bootstrap_without_response", "assistant_error", "alias_redirect", "unavailable"}:
        return False
    saved = str(record.get("chatgpt_control_url", "") or "").strip()
    if not is_chatgpt_conversation_url(saved):
        return False
    if diagnosis == "stale_url":
        return True
    return int(checks or 0) >= CONTROL_RECOVERY_CHECKS


def next_control_action(
    record: dict | None,
    messages: list[dict],
    page_url: str = "",
    checks: int = 0,
    wake: str = "",
    generation_active: bool = False,
    composer_ready: bool = False,
    now: float | None = None,
    page_unavailable: bool = False,
    blank_rebind: bool = False,
) -> str:
    """ready, wait, send, recover, or rebind. send/recover/rebind happen at most once."""
    record = record or {}
    diagnosis = diagnose_control(
        record,
        messages,
        page_url,
        wake=wake,
        generation_active=generation_active,
        composer_ready=composer_ready,
        now=now,
        page_unavailable=page_unavailable,
    )
    if control_is_ready(diagnosis):
        return "ready"
    saved = str(record.get("chatgpt_control_url", "") or "")
    rendered = page_unavailable or diagnosis == "unavailable" or blank_rebind
    if not rendered and not user_has_bootstrap_marker(messages):
        rendered = hard_control_unavailable(messages, False)
    if rebind_allowed(record, saved, rendered, now):
        return "rebind"
    if canonicalization_eligible(record, messages, page_url, wake):
        return "wait"
    if recovery_allowed(record, diagnosis, checks):
        return "recover"
    if (
        not record.get("recovery_used")
        and not bootstrap_was_sent(record)
        and not user_has_bootstrap_marker(messages)
        and diagnosis != "stale_url"
    ):
        return "send"
    return "wait"


def control_bootstrap_decision(
    record: dict | None,
    messages: list[dict],
    checks: int = 0,
) -> str:
    return next_control_action(record, messages, "", checks)


def pending_wake_action(control_action: str, inflight: dict, now: float | None = None) -> str:
    if control_action != "ready":
        return "hold"
    if inflight.get("wake_seen"):
        return "already_sent"
    if not wake_send_allowed(inflight, now):
        return "hold"
    return "send_wake"


def control_diag_counts(messages: list[dict]) -> tuple[int, int]:
    users = sum(1 for item in messages if item.get("role") == "user")
    assistants = sum(
        1
        for item in messages
        if item.get("role") == "assistant" and str(item.get("text") or "").strip()
    )
    return users, assistants


def load_control_record() -> dict:
    if not CONTROL_PATH.exists():
        return {}
    try:
        data = json.loads(CONTROL_PATH.read_text(encoding="utf-8"))
    except Exception as exc:
        log(f"CONTROL: не удалось прочитать {CONTROL_PATH.name}: {exc}")
        return {}
    if not isinstance(data, dict):
        return {}
    url = str(data.get("chatgpt_control_url", "") or "").strip()
    if not is_chatgpt_conversation_url(url):
        return {}
    if "bootstrap_sent" not in data:
        data["bootstrap_sent"] = True
        data["bootstrap_migrated_from"] = str(data.get("dispatcher_version") or "2.2.5")
        save_control_record(data)
        log("CONTROL: существующий control URL принят как bootstrap уже отправленный.")
    return data


def load_control_url() -> str:
    return str(load_control_record().get("chatgpt_control_url", "") or "")


def save_control_record(record: dict) -> None:
    url = str(record.get("chatgpt_control_url", "") or "").strip()
    if not is_chatgpt_conversation_url(url):
        raise ValueError(f"Некорректный control URL: {url!r}")
    payload = {
        "chatgpt_control_url": url,
        "name": record.get("name") or "01 — CONTROL & BRIDGE",
        "dispatcher_version": VERSION,
        "bootstrap_sent": bool(record.get("bootstrap_sent")),
    }
    if record.get("bootstrap_sent_at"):
        payload["bootstrap_sent_at"] = record["bootstrap_sent_at"]
    if record.get("bootstrap_migrated_from"):
        payload["bootstrap_migrated_from"] = record["bootstrap_migrated_from"]
    if "recovery_used" in record:
        payload["recovery_used"] = bool(record.get("recovery_used"))
    if record.get("recovery_reason"):
        payload["recovery_reason"] = record["recovery_reason"]
    if record.get("recovered_from"):
        payload["recovered_from"] = record["recovered_from"]
    if "unready_checks" in record:
        payload["unready_checks"] = int(record.get("unready_checks") or 0)
    if record.get("restore_attempted_at"):
        payload["restore_attempted_at"] = record["restore_attempted_at"]
    if "restore_failures" in record:
        payload["restore_failures"] = int(record.get("restore_failures") or 0)
    if record.get("rebind_for_url"):
        payload["rebind_for_url"] = record["rebind_for_url"]
    if record.get("rebind_attempted_at"):
        payload["rebind_attempted_at"] = record["rebind_attempted_at"]
    if "rebind_count" in record:
        payload["rebind_count"] = int(record.get("rebind_count") or 0)
    if record.get("rebind_status"):
        payload["rebind_status"] = record["rebind_status"]
    if "rebind_bootstrap_sent" in record:
        payload["rebind_bootstrap_sent"] = bool(record.get("rebind_bootstrap_sent"))
    reason = str(record.get("rebind_failure_reason") or "").strip()
    if (
        reason
        and " " not in reason
        and len(reason) <= 32
        and reason == reason.lower()
        and reason.replace("_", "").isalpha()
    ):
        payload["rebind_failure_reason"] = reason
    if "rebind_resume_count" in record:
        payload["rebind_resume_count"] = int(record.get("rebind_resume_count") or 0)
    resume_status = str(record.get("rebind_resume_status") or "")
    if resume_status in {"started", "failed", "done"}:
        payload["rebind_resume_status"] = resume_status
    if record.get("rebind_resume_for_url"):
        payload["rebind_resume_for_url"] = record["rebind_resume_for_url"]
    if record.get("rebind_replacement_for_url"):
        payload["rebind_replacement_for_url"] = record["rebind_replacement_for_url"]
    if "rebind_replacement_count" in record:
        payload["rebind_replacement_count"] = int(record.get("rebind_replacement_count") or 0)
    replacement_status = str(record.get("rebind_replacement_status") or "")
    if replacement_status in {"started", "failed", "done"}:
        payload["rebind_replacement_status"] = replacement_status
    replacement_reason = str(record.get("rebind_replacement_failure_reason") or "").strip()
    if (
        replacement_reason
        and " " not in replacement_reason
        and len(replacement_reason) <= 32
        and replacement_reason == replacement_reason.lower()
        and replacement_reason.replace("_", "").isalpha()
    ):
        payload["rebind_replacement_failure_reason"] = replacement_reason
    if record.get("rebind_finalize_for_url"):
        payload["rebind_finalize_for_url"] = record["rebind_finalize_for_url"]
    if "rebind_finalize_count" in record:
        payload["rebind_finalize_count"] = int(record.get("rebind_finalize_count") or 0)
    finalize_status = str(record.get("rebind_finalize_status") or "")
    if finalize_status in {"started", "submitted", "done", "failed"}:
        payload["rebind_finalize_status"] = finalize_status
    finalize_reason = str(record.get("rebind_finalize_failure_reason") or "").strip()
    if (
        finalize_reason
        and " " not in finalize_reason
        and len(finalize_reason) <= 32
        and finalize_reason == finalize_reason.lower()
        and finalize_reason.replace("_", "").isalpha()
    ):
        payload["rebind_finalize_failure_reason"] = finalize_reason
    if record.get("rebind_submit_retry_for_url"):
        payload["rebind_submit_retry_for_url"] = record["rebind_submit_retry_for_url"]
    if "rebind_submit_retry_count" in record:
        payload["rebind_submit_retry_count"] = int(record.get("rebind_submit_retry_count") or 0)
    retry_status = str(record.get("rebind_submit_retry_status") or "")
    if retry_status in {"started", "done", "failed"}:
        payload["rebind_submit_retry_status"] = retry_status
    if "rebind_bootstrap_attempted" in record:
        payload["rebind_bootstrap_attempted"] = bool(record.get("rebind_bootstrap_attempted"))
    submission_status = str(record.get("rebind_submission_status") or "")
    if submission_status in {"attempted", "confirmed", "failed"}:
        payload["rebind_submission_status"] = submission_status
    url_status = str(record.get("rebind_url_status") or "")
    if url_status in {"pending", "committed"}:
        payload["rebind_url_status"] = url_status
    if record.get("rebind_reprovision_for_url"):
        payload["rebind_reprovision_for_url"] = record["rebind_reprovision_for_url"]
    if "rebind_reprovision_count" in record:
        payload["rebind_reprovision_count"] = int(record.get("rebind_reprovision_count") or 0)
    reprovision_status = str(record.get("rebind_reprovision_status") or "")
    if reprovision_status in {"started", "failed", "done"}:
        payload["rebind_reprovision_status"] = reprovision_status
    reprovision_reason = str(record.get("rebind_reprovision_failure_reason") or "").strip()
    if (
        reprovision_reason
        and " " not in reprovision_reason
        and len(reprovision_reason) <= 32
        and reprovision_reason == reprovision_reason.lower()
        and reprovision_reason.replace("_", "").isalpha()
    ):
        payload["rebind_reprovision_failure_reason"] = reprovision_reason
    if "rebind_reprovision_bootstrap_attempted" in record:
        payload["rebind_reprovision_bootstrap_attempted"] = bool(
            record.get("rebind_reprovision_bootstrap_attempted")
        )
    reprovision_submission = str(record.get("rebind_reprovision_submission_status") or "")
    if reprovision_submission in {"attempted", "confirmed", "failed"}:
        payload["rebind_reprovision_submission_status"] = reprovision_submission
    if record.get("rebind_reprovision_submit_retry_for_url"):
        payload["rebind_reprovision_submit_retry_for_url"] = record["rebind_reprovision_submit_retry_for_url"]
    if "rebind_reprovision_submit_retry_count" in record:
        payload["rebind_reprovision_submit_retry_count"] = int(
            record.get("rebind_reprovision_submit_retry_count") or 0
        )
    reprovision_retry = str(record.get("rebind_reprovision_submit_retry_status") or "")
    if reprovision_retry in {"started", "done", "failed"}:
        payload["rebind_reprovision_submit_retry_status"] = reprovision_retry
    if record.get("replaced_from"):
        payload["replaced_from"] = record["replaced_from"]
    if record.get("bootstrap_previous_sent_at"):
        payload["bootstrap_previous_sent_at"] = record["bootstrap_previous_sent_at"]
    if record.get("blank_for_url"):
        payload["blank_for_url"] = record["blank_for_url"]
    if "blank_checks" in record:
        payload["blank_checks"] = int(record.get("blank_checks") or 0)
    if record.get("blank_since"):
        payload["blank_since"] = record["blank_since"]
    tmp = CONTROL_PATH.with_suffix(".tmp")
    tmp.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    os.replace(tmp, CONTROL_PATH)


def save_control_url(url: str, bootstrap_sent: bool = True) -> None:
    """Replace the URL in one write and keep the one-recovery latch."""
    existing = {}
    if CONTROL_PATH.exists():
        try:
            loaded = json.loads(CONTROL_PATH.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                existing = loaded
        except Exception:
            existing = {}
    record = {
        "chatgpt_control_url": url,
        "name": existing.get("name") or "01 — CONTROL & BRIDGE",
        "bootstrap_sent": bootstrap_sent,
        "bootstrap_sent_at": time.time() if bootstrap_sent else existing.get("bootstrap_sent_at"),
    }
    for key in ("recovery_used", "recovery_reason", "recovered_from", "bootstrap_migrated_from"):
        if key in existing:
            record[key] = existing[key]
    if "unready_checks" in existing:
        record["unready_checks"] = existing["unready_checks"]
    save_control_record(record)
    log(f"CONTROL: закреплён отдельный машинный ChatGPT-чат: {url}")


def _read_control_file() -> dict:
    if not CONTROL_PATH.exists():
        return {}
    try:
        loaded = json.loads(CONTROL_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return loaded if isinstance(loaded, dict) else {}


def blank_control_match(
    record: dict | None,
    page_url: str,
    messages: list[dict] | None,
    composer_ready: bool,
    generation_active: bool,
    signed_out: bool,
    page_unavailable: bool,
) -> bool:
    """A blank equivalent control page. One observation is not enough to rebind."""
    if page_unavailable or signed_out or composer_ready or generation_active:
        return False
    if messages:
        return False
    saved = str((record or {}).get("chatgpt_control_url") or "")
    if not is_usable_control_url(saved) or not page_url:
        return False
    return same_conversation(page_url, saved) or url_matches(page_url, saved)


def apply_blank_observation(record: dict | None, saved_url: str, blank: bool, now: float) -> dict:
    """URL-scoped consecutive counter. Non-matching observations clear it."""
    updated = dict(record or {})
    saved = normalize_conversation_url(saved_url)
    if not blank or not saved:
        updated.pop("blank_for_url", None)
        updated.pop("blank_checks", None)
        updated.pop("blank_since", None)
        return updated
    same = normalize_conversation_url(str(updated.get("blank_for_url") or "")) == saved
    if not same:
        updated["blank_for_url"] = saved
        updated["blank_checks"] = 1
        updated["blank_since"] = now
        return updated
    updated["blank_checks"] = int(updated.get("blank_checks") or 0) + 1
    if not updated.get("blank_since"):
        updated["blank_since"] = now
    return updated


def blank_rebind_ready(record: dict | None, saved_url: str, now: float) -> bool:
    record = record or {}
    saved = normalize_conversation_url(saved_url)
    if not saved or normalize_conversation_url(str(record.get("blank_for_url") or "")) != saved:
        return False
    if int(record.get("blank_checks") or 0) < BLANK_REBIND_POLLS:
        return False
    try:
        since = float(record.get("blank_since"))
    except (TypeError, ValueError):
        return False
    return float(now) - since >= BLANK_REBIND_SECONDS


def rebind_target(url: str) -> str:
    return normalize_conversation_url(url)


def rebind_bound(record: dict | None, saved_url: str) -> bool:
    record = record or {}
    saved = rebind_target(saved_url)
    bound = rebind_target(str(record.get("rebind_for_url") or ""))
    return bool(saved) and saved == bound


def rebind_completed(record: dict | None, saved_url: str) -> bool:
    record = record or {}
    if not rebind_bound(record, saved_url):
        return False
    return int(record.get("rebind_count") or 0) >= 1 and record.get("rebind_status") in {"done", "failed"}


def rebind_cooldown_active(record: dict | None, now: float | None = None) -> bool:
    record = record or {}
    attempted = record.get("rebind_attempted_at")
    if attempted in (None, ""):
        return False
    try:
        attempted = float(attempted)
    except (TypeError, ValueError):
        return False
    if now is None:
        now = time.time()
    return float(now) - attempted < CONTROL_REBIND_COOLDOWN_SECONDS


def rebind_allowed(
    record: dict | None,
    saved_url: str,
    unavailable: bool,
    now: float | None = None,
) -> bool:
    record = record or {}
    if not unavailable or not is_usable_control_url(saved_url):
        return False
    if rebind_completed(record, saved_url):
        return False
    if rebind_bound(record, saved_url) and record.get("rebind_status") == "pending":
        return True
    if rebind_bound(record, saved_url) and rebind_cooldown_active(record, now):
        return False
    return True


def rebind_page_action(
    record: dict | None,
    saved_url: str,
    unavailable: bool,
    now: float,
    has_page: bool,
) -> str:
    """create, reuse, wait, or none. A saved URL gets at most one new page."""
    record = record or {}
    if rebind_completed(record, saved_url):
        return "wait"
    bound = rebind_bound(record, saved_url)
    status = record.get("rebind_status") if bound else ""
    count = int(record.get("rebind_count") or 0) if bound else 0
    if count >= 1 and status == "pending":
        return "reuse" if has_page else "wait"
    if count >= 1 and status == "failed":
        return "wait"
    if not unavailable:
        return "none"
    if bound and rebind_cooldown_active(record, now):
        return "reuse" if has_page else "wait"
    return "create"


def _write_rebind_state(
    old_url: str,
    status: str,
    bootstrap_sent: bool | None = None,
    failure_reason: str | None = None,
) -> None:
    existing = _read_control_file()
    if not is_chatgpt_conversation_url(str(existing.get("chatgpt_control_url") or "")):
        return
    existing["rebind_for_url"] = rebind_target(old_url) or str(old_url)
    existing["rebind_count"] = max(1, int(existing.get("rebind_count") or 0))
    existing["rebind_status"] = status
    existing["rebind_attempted_at"] = time.time()
    if bootstrap_sent is not None:
        existing["rebind_bootstrap_sent"] = bootstrap_sent
    if failure_reason:
        existing["rebind_failure_reason"] = stable_rebind_reason(failure_reason)
    save_control_record(existing)


def mark_rebind_started(old_url: str) -> None:
    _write_rebind_state(old_url, "pending", bootstrap_sent=False)


def mark_rebind_bootstrap_sent(old_url: str) -> None:
    """Record confirmed submission. Call only after Enter was observed to land."""
    _write_rebind_state(old_url, "pending", bootstrap_sent=True)
    existing = _read_control_file()
    if not is_chatgpt_conversation_url(str(existing.get("chatgpt_control_url") or "")):
        return
    existing["rebind_bootstrap_attempted"] = True
    existing["rebind_submission_status"] = "confirmed"
    save_control_record(existing)


def mark_rebind_failed(old_url: str, reason: str = "") -> None:
    existing = _read_control_file()
    sent = bool(existing.get("rebind_bootstrap_sent"))
    token = stable_rebind_reason(reason) if str(reason or "").strip() else None
    _write_rebind_state(old_url, "failed", bootstrap_sent=sent, failure_reason=token)


def commit_rebind(new_url: str, old_url: str, browser=None, keep=None) -> None:
    """Replace the URL once. Keep recovery fields and drop only the restore latch."""
    existing = _read_control_file()
    observed = normalize_conversation_url(new_url)
    if not observed:
        raise ValueError(f"Некорректный control URL: {new_url!r}")
    previous_sent = existing.get("bootstrap_sent_at")
    if previous_sent and not existing.get("bootstrap_previous_sent_at"):
        existing["bootstrap_previous_sent_at"] = previous_sent
    existing["chatgpt_control_url"] = observed
    existing["replaced_from"] = rebind_target(old_url) or str(old_url)
    existing["rebind_for_url"] = existing["replaced_from"]
    existing["rebind_count"] = max(1, int(existing.get("rebind_count") or 0))
    existing["rebind_status"] = "done"
    existing["rebind_attempted_at"] = existing.get("rebind_attempted_at") or time.time()
    existing["rebind_bootstrap_sent"] = True
    existing["bootstrap_sent"] = True
    existing["bootstrap_sent_at"] = time.time()
    existing.pop("restore_attempted_at", None)
    existing.pop("restore_failures", None)
    existing.pop("blank_for_url", None)
    existing.pop("blank_checks", None)
    existing.pop("blank_since", None)
    replacement_for = rebind_target(str(existing.get("rebind_replacement_for_url") or ""))
    if replacement_for and replacement_for == (rebind_target(old_url) or str(old_url)):
        existing["rebind_replacement_count"] = max(1, int(existing.get("rebind_replacement_count") or 0))
        existing["rebind_replacement_status"] = "done"
        existing.pop("rebind_replacement_failure_reason", None)
    finalize_for = rebind_target(str(existing.get("rebind_finalize_for_url") or ""))
    if finalize_for and finalize_for == (rebind_target(old_url) or str(old_url)):
        existing["rebind_finalize_count"] = max(1, int(existing.get("rebind_finalize_count") or 0))
        existing["rebind_finalize_status"] = "done"
        existing.pop("rebind_finalize_failure_reason", None)
    reprovision_for = rebind_target(str(existing.get("rebind_reprovision_for_url") or ""))
    if reprovision_for and reprovision_for == (rebind_target(old_url) or str(old_url)):
        existing["rebind_reprovision_count"] = max(1, int(existing.get("rebind_reprovision_count") or 0))
        existing["rebind_reprovision_status"] = "done"
        existing.pop("rebind_reprovision_failure_reason", None)
        existing["rebind_reprovision_submission_status"] = "confirmed"
        existing["rebind_reprovision_bootstrap_attempted"] = True
    existing["rebind_submission_status"] = "confirmed"
    existing["rebind_url_status"] = "committed"
    existing["rebind_bootstrap_attempted"] = True
    save_control_record(existing)
    cleanup = globals().get("close_control_service_pages")
    if browser is not None and callable(cleanup):
        cleanup(browser, keep=keep, old_url=old_url)
    log("CONTROL: url_rebound")


def note_restore_failure() -> None:
    """Remember a failed restore without touching bootstrap or recovery_used."""
    existing = _read_control_file()
    if not is_chatgpt_conversation_url(str(existing.get("chatgpt_control_url") or "")):
        return
    existing["restore_attempted_at"] = time.time()
    existing["restore_failures"] = int(existing.get("restore_failures") or 0) + 1
    save_control_record(existing)


def clear_restore_latch() -> None:
    existing = _read_control_file()
    if not is_chatgpt_conversation_url(str(existing.get("chatgpt_control_url") or "")):
        return
    existing.pop("restore_attempted_at", None)
    existing.pop("restore_failures", None)
    save_control_record(existing)


def canonicalize_control_url(url: str) -> None:
    """Replace only the URL. Keep bootstrap time and the one-recovery latch."""
    observed = normalize_conversation_url(url)
    if not observed:
        raise ValueError(f"Некорректный control URL: {url!r}")
    existing = {}
    if CONTROL_PATH.exists():
        try:
            loaded = json.loads(CONTROL_PATH.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                existing = loaded
        except Exception:
            existing = {}
    record = dict(existing)
    record["chatgpt_control_url"] = observed
    if "bootstrap_sent" not in record:
        record["bootstrap_sent"] = True
    save_control_record(record)
    log("CONTROL: url_canonicalized")


# -------------------------
# Chrome / CDP
# -------------------------

def port_open(host: str, port: int, timeout: float = 0.7) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


_CHROME_PROC = None


def cdp_http_ready() -> bool:
    try:
        req = urllib.request.Request(
            f"{CDP}/json/version",
            headers={"User-Agent": f"AI-Dispatcher-{VERSION}"},
        )
        with urllib.request.urlopen(req, timeout=2) as resp:
            payload = json.loads(resp.read().decode("utf-8", "replace"))
        return bool(payload.get("webSocketDebuggerUrl"))
    except Exception:
        return False


def stop_owned_chrome() -> None:
    global _CHROME_PROC

    if _CHROME_PROC is not None and _CHROME_PROC.poll() is None:
        _CHROME_PROC.terminate()
        try:
            _CHROME_PROC.wait(timeout=5)
        except Exception:
            _CHROME_PROC.kill()
    _CHROME_PROC = None

    if os.name != "nt":
        return

    script = (
        "Get-CimInstance Win32_Process -Filter \"Name = 'chrome.exe'\" | "
        "Where-Object { $_.CommandLine -like '*AI-Dispatcher-Chrome*' -and "
        "$_.CommandLine -like '*--remote-debugging-port=9223*' } | "
        "ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"
    )
    subprocess.run(
        ["powershell", "-NoProfile", "-Command", script],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=20,
    )

    deadline = time.time() + 8
    while time.time() < deadline and port_open(CDP_HOST, CDP_PORT):
        time.sleep(0.3)


def start_service_chrome(force: bool = False) -> None:
    global _CHROME_PROC

    if not force and cdp_http_ready():
        return

    if force or port_open(CDP_HOST, CDP_PORT):
        log("CHROME: перезапускаю сервисный профиль.")
        stop_owned_chrome()
        if port_open(CDP_HOST, CDP_PORT):
            raise RuntimeError(
                f"Порт {CDP_PORT} занят, но это не CDP сервисного Chrome."
            )

    if not CHROME_PATH.exists():
        raise FileNotFoundError(f"Chrome не найден: {CHROME_PATH}")

    CHROME_PROFILE.mkdir(parents=True, exist_ok=True)

    args = [
        str(CHROME_PATH),
        f"--remote-debugging-port={CDP_PORT}",
        "--remote-allow-origins=*",
        f"--user-data-dir={CHROME_PROFILE}",
        "--no-first-run",
        "--no-default-browser-check",
    ]

    creationflags = 0
    if os.name == "nt":
        creationflags = (
            getattr(subprocess, "DETACHED_PROCESS", 0)
            | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        )

    _CHROME_PROC = subprocess.Popen(
        args,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=creationflags,
    )

    deadline = time.time() + CHROME_START_TIMEOUT
    while time.time() < deadline:
        if cdp_http_ready():
            log("CHROME: сервисный Chrome запущен.")
            return
        time.sleep(0.5)

    raise RuntimeError(
        f"Chrome запущен, но CDP {CDP_HOST}:{CDP_PORT} не поднялся "
        f"за {CHROME_START_TIMEOUT} сек."
    )


# -------------------------
# GitHub signal
# -------------------------

class GitHubNetworkError(RuntimeError):
    pass


class GitHubSignalError(RuntimeError):
    pass


def _is_network_exception(exc: BaseException) -> bool:
    if isinstance(exc, PlaywrightTimeoutError):
        return False
    if isinstance(
        exc,
        (
            urllib.error.URLError,
            http.client.RemoteDisconnected,
            ssl.SSLError,
            socket.timeout,
            TimeoutError,
            ConnectionError,
            ConnectionResetError,
        ),
    ):
        return True

    text = str(exc)
    return any(
        token in text
        for token in (
            "RemoteDisconnected",
            "UNEXPECTED_EOF",
            "SSL",
            "handshake",
            "Name or service not known",
            "Temporary failure in name resolution",
        )
    )


def parse_signal(data: dict) -> dict:
    """Normalize a signal object. Raises GitHubSignalError; does not log message text."""
    if not isinstance(data, dict):
        raise GitHubSignalError("signal_not_object")
    requires_codex = data.get("requires_codex", False)
    if not isinstance(requires_codex, bool):
        raise GitHubSignalError("requires_codex_invalid")
    try:
        return {
            "protocol": int(data.get("protocol", 0) or 0),
            "turn_id": int(data.get("turn_id", 0) or 0),
            "target": str(data.get("target", "") or "").upper(),
            "source": str(data.get("source", "") or "").upper(),
            "status": str(data.get("status", "") or "").lower(),
            "message": str(data.get("message", "") or ""),
            "requires_codex": requires_codex,
        }
    except (TypeError, ValueError) as exc:
        raise GitHubSignalError("signal_fields_invalid") from exc


def parse_signal_text(raw: str) -> dict:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise GitHubSignalError("signal_json_invalid") from exc
    return parse_signal(data)


def parse_api_contents(raw: str) -> dict:
    try:
        body = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise GitHubSignalError("api_json_invalid") from exc
    if not isinstance(body, dict):
        raise GitHubSignalError("api_not_object")
    if body.get("encoding") != "base64":
        raise GitHubSignalError("api_encoding_invalid")
    content = body.get("content")
    if not isinstance(content, str) or not content.strip():
        raise GitHubSignalError("api_content_missing")
    try:
        decoded = base64.b64decode("".join(content.split()), validate=True)
        text = decoded.decode("utf-8")
    except (ValueError, UnicodeDecodeError) as exc:
        raise GitHubSignalError("api_base64_invalid") from exc
    return parse_signal_text(text)


def _signal_request(url: str) -> urllib.request.Request:
    return urllib.request.Request(
        url,
        headers={
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
            "Accept": "application/vnd.github+json",
            "User-Agent": f"AI-Dispatcher-{VERSION}",
        },
    )


def _read_response(url: str, timeout: float, opener=None) -> str:
    open_fn = opener or urllib.request.urlopen
    with open_fn(_signal_request(url), timeout=timeout) as resp:
        payload = resp.read()
    if isinstance(payload, str):
        return payload
    return payload.decode("utf-8")


def fetch_signal(opener=None, timeout: float | None = None) -> dict:
    """Try raw once, then the contents API once. No same-host retry and no sleep."""
    limit = SIGNAL_FETCH_TIMEOUT if timeout is None else timeout
    endpoints = (
        ("raw", f"{SIGNAL_URL}?ts={time.time_ns()}", parse_signal_text),
        ("api", SIGNAL_API_URL, parse_api_contents),
    )
    last_network: BaseException | None = None
    for name, url, parser in endpoints:
        try:
            signal = parser(_read_response(url, limit, opener))
        except GitHubSignalError:
            log(f"GITHUB: endpoint={name} error=GitHubSignalError")
            raise
        except Exception as exc:
            if not _is_network_exception(exc):
                log(f"GITHUB: endpoint={name} error={type(exc).__name__}")
                raise
            last_network = exc
            log(f"GITHUB: endpoint={name} error={type(exc).__name__}")
            continue
        if name == "api":
            log("GITHUB: endpoint=api ok")
        return signal
    raise GitHubNetworkError("github_endpoints_unavailable") from last_network


def wake_text(turn_id: int) -> str:
    return f"Проверь GitHub. turn_id={turn_id}"


# -------------------------
# Browser page helpers
# -------------------------

def all_pages(browser):
    for context in browser.contexts:
        for page in context.pages:
            yield page


def url_matches(url: str, expected: str) -> bool:
    if not url or not expected:
        return False
    if url == expected:
        return True
    return (
        url.startswith(expected + "/")
        or url.startswith(expected + "?")
        or url.startswith(expected + "#")
    )


def page_is_foreground(page) -> bool:
    try:
        return page.evaluate("document.visibilityState") == "visible"
    except Exception:
        return False


def choose_page(pages):
    pages = list(pages)
    if not pages:
        return None
    foreground = [page for page in pages if page_is_foreground(page)]
    return foreground[0] if foreground else pages[0]


def chatgpt_pages(browser):
    return [
        page
        for page in all_pages(browser)
        if "chatgpt.com" in (page.url or "")
    ]


def close_control_service_pages(browser, keep=None, old_url: str = "") -> int:
    """Close only dispatcher-owned pages after a control transition.

    Ownership is proved by a dispatcher window.name marker or the previously
    persisted CONTROL URL. Unmarked conversations are always left alone.
    """
    old = normalize_conversation_url(old_url)
    closed = 0
    for page in list(all_pages(browser)):
        if page is keep:
            continue
        mark = page_restore_mark(page)
        url = normalize_conversation_url(str(getattr(page, "url", "") or ""))
        owned = mark in CONTROL_SERVICE_PAGE_MARKS or (old and same_conversation(url, old))
        if not owned:
            continue
        try:
            page.close()
        except Exception:
            # Cleanup is best effort; routing state remains fail-closed.
            continue
        closed += 1
    return closed


def mark_control_service_page(page, mark: str) -> None:
    try:
        page.evaluate("(name) => { window.name = name }", mark)
    except Exception:
        pass


def _preferred_index(pages: list[dict], indexes: list[int]) -> int:
    for index in indexes:
        if pages[index].get("foreground"):
            return index
    return indexes[0]


def restore_candidates(saved_url: str) -> list[str]:
    """Canonical /c/<uuid> before a saved WEB alias. Other URLs stay as saved."""
    saved = normalize_conversation_url(saved_url)
    if not saved:
        return []
    raw_id = conversation_id(saved)
    if raw_id.upper().startswith("WEB:"):
        uuid = conversation_identity(saved)
        candidates = []
        if uuid:
            canonical = f"https://chatgpt.com/c/{uuid}"
            candidates.append(canonical)
        if saved not in candidates:
            candidates.append(saved)
        return candidates
    return [saved]


def restore_observation_accepted(
    saved_url: str,
    observed_url: str,
    messages: list[dict] | None = None,
    composer_ready: bool = False,
    wake: str = "",
) -> bool:
    """Accept a restore when the page is the same conversation or shows control identity."""
    del composer_ready
    if same_conversation(observed_url, saved_url):
        return True
    return positive_control_identity(list(messages or []), wake)


def restore_cooldown_active(record: dict | None, now: float | None = None) -> bool:
    record = record or {}
    attempted = record.get("restore_attempted_at")
    if attempted in (None, ""):
        return False
    try:
        attempted = float(attempted)
    except (TypeError, ValueError):
        return False
    if now is None:
        now = time.time()
    return float(now) - attempted < CONTROL_RESTORE_COOLDOWN_SECONDS


def restore_page_action(record: dict | None, now: float, has_restore_page: bool) -> str:
    """create, reuse_attempt, reuse_idle, or wait. Never create while one page exists."""
    cooling = restore_cooldown_active(record, now)
    if has_restore_page and cooling:
        return "reuse_idle"
    if has_restore_page:
        return "reuse_attempt"
    if cooling:
        return "wait"
    return "create"


def plan_control_page(pages: list[dict], saved_url: str, wake: str = "") -> dict:
    """Choose an open control page without navigating. goto means restore, not hijack."""
    saved = str(saved_url or "").strip()
    if not is_usable_control_url(saved):
        return {"action": "provision", "index": None, "url": "", "reason": "missing"}
    equivalent = [
        index
        for index, page in enumerate(pages)
        if same_conversation(str(page.get("url") or ""), saved)
    ]
    if equivalent:
        index = _preferred_index(pages, equivalent)
        return {
            "action": "use",
            "index": index,
            "url": str(pages[index].get("url") or ""),
            "reason": "equivalent",
        }
    proven = []
    for index, page in enumerate(pages):
        url = str(page.get("url") or "")
        if not is_chatgpt_conversation_url(url):
            continue
        if positive_control_identity(list(page.get("messages") or []), wake):
            proven.append(index)
    if proven:
        index = _preferred_index(pages, proven)
        return {
            "action": "use",
            "index": index,
            "url": str(pages[index].get("url") or ""),
            "reason": "identity",
        }
    return {"action": "goto", "index": None, "url": saved, "reason": "new_page"}


def find_control_page(browser, wake: str = ""):
    control_url = load_control_url()

    if control_url and not is_usable_control_url(control_url):
        return None

    if not control_url:
        return provision_control_chat(browser)

    pages = [
        page
        for page in chatgpt_pages(browser)
        if is_chatgpt_conversation_url(page.url or "")
    ]
    equivalent_open = any(same_conversation(page.url or "", control_url) for page in pages)
    snapshots = []
    for page in pages:
        messages: list[dict] = []
        if not equivalent_open:
            try:
                messages = chatgpt_messages(page)
            except Exception:
                messages = []
        snapshots.append(
            {
                "url": page.url or "",
                "messages": messages,
                "foreground": page_is_foreground(page),
            }
        )
    plan = plan_control_page(snapshots, control_url, wake)
    if plan["action"] == "use":
        page = pages[plan["index"]]
        observed = normalize_conversation_url(page.url or "")
        if observed and observed != normalize_conversation_url(control_url):
            canonicalize_control_url(page.url or "")
        log(f"CONTROL: page={plan['reason']}")
        return page

    return begin_control_restore(browser, control_url, wake)


def page_restore_mark(page) -> str:
    try:
        return str(page.evaluate("window.name") or "")
    except Exception:
        return ""


def mark_restore_page(page) -> None:
    try:
        page.evaluate("(name) => { window.name = name }", RESTORE_PAGE_MARK)
    except Exception:
        pass


def find_restore_page(browser):
    for page in all_pages(browser):
        if page_restore_mark(page) == RESTORE_PAGE_MARK:
            return page
    return None


def wait_for_restore_url(page, timeout_seconds: float | None = None) -> str:
    timeout = CONTROL_RESTORE_WAIT_SECONDS if timeout_seconds is None else timeout_seconds
    deadline = time.time() + max(0.0, float(timeout))
    last = page.url or ""
    while True:
        last = page.url or ""
        if is_chatgpt_conversation_url(last) or time.time() >= deadline:
            return last
        time.sleep(0.25)
    return last


def _inspect_restore(page, saved_url: str, wake: str, observed: str) -> tuple[list[dict], bool, bool]:
    try:
        messages = chatgpt_messages(page)
    except Exception:
        messages = []
    try:
        composer = composer_is_ready(page)
    except Exception:
        composer = False
    accepted = restore_observation_accepted(saved_url, observed, messages, composer, wake)
    return messages, composer, accepted


def _observe_restore(page, saved_url: str, wake: str) -> tuple[str, list[dict], bool, bool]:
    observed = wait_for_restore_url(page)
    _messages, composer, accepted = _inspect_restore(page, saved_url, wake, observed)
    return observed, _messages, composer, accepted


def begin_control_restore(browser, control_url: str, wake: str = ""):
    """Open the saved conversation on one marked page. Do not hijack another chat."""
    record = load_control_record()
    now = time.time()
    page = find_restore_page(browser)
    action = restore_page_action(record, now, page is not None)
    if action == "wait":
        log("CONTROL: page=restore_wait")
        return None
    if action == "create":
        page = browser.contexts[0].new_page()
        mark_restore_page(page)
        log("CONTROL: page=restore_create")
    elif action == "reuse_idle":
        observed = page.url or ""
        _messages, composer, accepted = _inspect_restore(page, control_url, wake, observed)
        log(f"CONTROL: page=restore_wait accepted={int(accepted)} composer={int(bool(composer))}")
        if accepted and is_usable_control_url(observed):
            canonicalize_control_url(observed)
            clear_restore_latch()
        return page
    else:
        log("CONTROL: page=restore_attempt")

    observed = page.url or ""
    _messages, composer, accepted = _inspect_restore(page, control_url, wake, observed)
    if accepted and is_usable_control_url(observed):
        canonicalize_control_url(observed)
        clear_restore_latch()
        globals().get("close_control_service_pages", lambda *_a, **_k: 0)(browser, keep=page, old_url=control_url)
        log("CONTROL: page=restored")
        return page

    for index, candidate in enumerate(restore_candidates(control_url)):
        try:
            page.goto(
                candidate,
                wait_until="domcontentloaded",
                timeout=CONTROL_RESTORE_GOTO_TIMEOUT,
            )
        except Exception as exc:
            log(f"CONTROL: restore candidate={index} error={type(exc).__name__}")
            continue
        observed, _messages, composer, accepted = _observe_restore(page, control_url, wake)
        log(
            "CONTROL: "
            f"restore candidate={index} accepted={int(accepted)} "
            f"composer={int(bool(composer))}"
        )
        if accepted and is_usable_control_url(observed):
            canonicalize_control_url(observed)
            clear_restore_latch()
            globals().get("close_control_service_pages", lambda *_a, **_k: 0)(browser, keep=page, old_url=control_url)
            log("CONTROL: page=restored")
            return page
    note_restore_failure()
    log("CONTROL: page=restore_failed")
    return page


def page_shows_unavailable(page) -> bool:
    """Read the rendered error state and return only a boolean."""
    try:
        text = page.evaluate(
            """() => {
              const nodes = document.querySelectorAll('[role="alert"], [data-testid*="error"], h1, h2');
              const headed = Array.from(nodes).slice(0, 12).map(n => n.innerText || '').join('\n');
              const body = ((document.body && document.body.innerText) || '').slice(0, 1500);
              return (headed + '\n' + body).slice(0, 2500);
            }"""
        )
    except Exception:
        return False
    return hard_unavailable_text(text)


def page_signed_out(page) -> bool:
    try:
        text = page.evaluate(
            """() => ((document.body && document.body.innerText) || '').slice(0, 2000)"""
        )
    except Exception:
        return False
    lowered = str(text or "").lower()
    return any(marker in lowered for marker in SIGN_IN_MARKERS)


def find_rebind_page(browser):
    for page in all_pages(browser):
        if page_restore_mark(page) == REBIND_PAGE_MARK:
            return page
    return None


def mark_rebind_page(page) -> None:
    try:
        page.evaluate("(name) => { window.name = name }", REBIND_PAGE_MARK)
    except Exception:
        pass


def stable_rebind_reason(reason: str) -> str:
    """Persist only a short token. Never store rendered UI text."""
    token = str(reason or "").strip()
    if token in REBIND_FAILURE_REASONS:
        return token
    return "failed"


def _diag_failure_reason(record: dict | None) -> str:
    token = str((record or {}).get("rebind_failure_reason") or "").strip()
    return token if token in REBIND_FAILURE_REASONS else "none"


def rebind_page_on_home(url: str) -> bool:
    raw = str(url or "").strip().split("#", 1)[0].split("?", 1)[0].rstrip("/")
    return raw == "https://chatgpt.com"


def rebind_resume_allowed(record: dict | None, saved_url: str) -> bool:
    """Legacy 2.2.14 failed rebind with no stored reason may resume once.

    A stored failure reason means 2.2.15 already waited. Do not resume that.
    """
    record = record or {}
    if not rebind_bound(record, saved_url):
        return False
    if record.get("rebind_status") != "failed":
        return False
    if int(record.get("rebind_count") or 0) < 1:
        return False
    if bool(record.get("rebind_bootstrap_sent")):
        return False
    if int(record.get("rebind_resume_count") or 0) >= 1:
        return False
    if str(record.get("rebind_resume_status") or "") in {"started", "failed", "done"}:
        return False
    if str(record.get("rebind_failure_reason") or "").strip():
        return False
    return True


def should_resume_rebind(record: dict | None, saved_url: str, action: str) -> bool:
    """Resume only from a later wait poll. Never instead of ready/send/recover/rebind."""
    if action in {"ready", "rebind", "send", "recover"}:
        return False
    return rebind_resume_allowed(record, saved_url)


def mark_rebind_resume_started(old_url: str) -> None:
    existing = _read_control_file()
    if not is_chatgpt_conversation_url(str(existing.get("chatgpt_control_url") or "")):
        return
    existing["rebind_resume_count"] = max(1, int(existing.get("rebind_resume_count") or 0))
    existing["rebind_resume_status"] = "started"
    existing["rebind_resume_for_url"] = rebind_target(old_url) or str(old_url)
    save_control_record(existing)


def mark_rebind_resume_result(old_url: str) -> None:
    existing = _read_control_file()
    if not is_chatgpt_conversation_url(str(existing.get("chatgpt_control_url") or "")):
        return
    existing["rebind_resume_count"] = max(1, int(existing.get("rebind_resume_count") or 0))
    existing["rebind_resume_for_url"] = rebind_target(old_url) or str(existing.get("rebind_resume_for_url") or "")
    existing["rebind_resume_status"] = "done" if existing.get("rebind_status") == "done" else "failed"
    save_control_record(existing)


def wait_for_rebind_composer(page, timeout_seconds: float | None = None) -> str:
    """Poll an already-created page. One immediate miss is not a failure."""
    timeout = CONTROL_REBIND_COMPOSER_WAIT if timeout_seconds is None else float(timeout_seconds)
    deadline = time.time() + max(0.0, timeout)
    announced = False
    while True:
        try:
            if page_signed_out(page):
                return "signed_out"
        except Exception:
            pass
        try:
            if page_shows_unavailable(page):
                return "hard_unavailable"
        except Exception:
            pass
        try:
            if composer_is_ready(page):
                return "ready"
        except Exception:
            pass
        now = time.time()
        if now >= deadline:
            return "no_composer"
        if not announced:
            log("CONTROL: rebind=composer_wait")
            announced = True
        remaining = deadline - now
        time.sleep(min(REBIND_COMPOSER_POLL_SECONDS, max(0.05, remaining)))


def hydrate_rebind_page(page, old_url: str, goto_home: bool = True, browser=None):
    """Bootstrap once on a page that already exists. Never opens a tab."""
    record = load_control_record()
    if record.get("rebind_bootstrap_sent"):
        url = wait_for_conversation_url(page, CONTROL_REBIND_URL_WAIT)
        if url and is_usable_control_url(url) and not same_conversation(url, old_url):
            commit_rebind(url, old_url, browser=browser, keep=page)
            log("CONTROL: page=rebound")
        return page

    if goto_home:
        try:
            page.goto(CHATGPT_HOME, wait_until="domcontentloaded", timeout=CONTROL_RESTORE_GOTO_TIMEOUT)
        except Exception as exc:
            mark_rebind_failed(old_url, "goto")
            log(f"CONTROL: rebind=failed reason=goto error={type(exc).__name__}")
            return page

    outcome = wait_for_rebind_composer(page)
    if outcome != "ready":
        mark_rebind_failed(old_url, outcome)
        log(f"CONTROL: rebind=failed reason={outcome}")
        return page

    record = load_control_record()
    if record.get("rebind_bootstrap_sent"):
        log("CONTROL: rebind=bootstrap_already_sent")
        return page
    existing = _read_control_file()
    if is_chatgpt_conversation_url(str(existing.get("chatgpt_control_url") or "")):
        existing["rebind_bootstrap_attempted"] = True
        existing["rebind_submission_status"] = "attempted"
        save_control_record(existing)
    submitted = send_to_chatgpt(page, CONTROL_BOOTSTRAP)
    if submitted is True:
        mark_rebind_bootstrap_sent(old_url)
    elif submitted is False:
        existing = _read_control_file()
        if is_chatgpt_conversation_url(str(existing.get("chatgpt_control_url") or "")):
            existing["rebind_bootstrap_attempted"] = True
            existing["rebind_submission_status"] = "failed"
            save_control_record(existing)
        mark_rebind_failed(old_url, "submit_unconfirmed")
        log("CONTROL: rebind=failed reason=submit_unconfirmed")
        return page
    url = wait_for_conversation_url(page, CONTROL_REBIND_URL_WAIT)
    if not url or not is_usable_control_url(url) or same_conversation(url, old_url):
        if submitted is True:
            existing = _read_control_file()
            if is_chatgpt_conversation_url(str(existing.get("chatgpt_control_url") or "")):
                existing["rebind_submission_status"] = "confirmed"
                existing["rebind_url_status"] = "pending"
                existing["rebind_bootstrap_sent"] = True
                save_control_record(existing)
        mark_rebind_failed(old_url, "no_new_url")
        log("CONTROL: rebind=failed reason=no_new_url")
        return page
    commit_rebind(url, old_url, browser=browser, keep=page)
    log("CONTROL: page=rebound")
    return page


def begin_control_rebind(browser, old_url: str):
    """Create at most one new service chat. Never touch an unrelated conversation."""
    record = load_control_record()
    now = time.time()
    page = find_rebind_page(browser)
    action = rebind_page_action(record, old_url, True, now, page is not None)
    log(f"CONTROL: rebind={action}")
    if action in {"none", "wait"}:
        return page
    if action == "create":
        mark_rebind_started(old_url)
        page = browser.contexts[0].new_page()
        mark_rebind_page(page)
        log("CONTROL: page=rebind_create")
        result = hydrate_rebind_page(page, old_url, goto_home=True, browser=browser)
        if str(load_control_record().get("rebind_status") or "") == "failed":
            globals().get("close_control_service_pages", lambda *_a, **_k: 0)(browser, keep=None)
        return result
    log("CONTROL: page=rebind_reuse")
    on_home = rebind_page_on_home(str(getattr(page, "url", "") or ""))
    return hydrate_rebind_page(page, old_url, goto_home=not on_home, browser=browser)


def resume_control_rebind(browser, old_url: str):
    """Exactly one resume on the existing marked page. Never opens another tab."""
    record = load_control_record()
    if not rebind_resume_allowed(record, old_url):
        return find_rebind_page(browser)
    page = find_rebind_page(browser)
    mark_rebind_resume_started(old_url)
    log("CONTROL: rebind=resume")
    if page is None:
        mark_rebind_failed(old_url, "missing_page")
        mark_rebind_resume_result(old_url)
        log("CONTROL: rebind=resume_failed reason=missing_page")
        return None
    current = str(getattr(page, "url", "") or "")
    if is_usable_control_url(current) and not same_conversation(current, old_url):
        mark_rebind_failed(old_url, "unexpected_url")
        mark_rebind_resume_result(old_url)
        log("CONTROL: rebind=resume_failed reason=unexpected_url")
        return page
    hydrate_rebind_page(page, old_url, goto_home=not rebind_page_on_home(current), browser=browser)
    mark_rebind_resume_result(old_url)
    return page


def _diag_replacement_status(record: dict | None) -> str:
    token = str((record or {}).get("rebind_replacement_status") or "").strip()
    return token if token in {"started", "failed", "done"} else "none"


def rebind_replacement_bound(record: dict | None, saved_url: str) -> bool:
    record = record or {}
    saved = rebind_target(saved_url)
    bound = rebind_target(str(record.get("rebind_replacement_for_url") or ""))
    return bool(saved) and saved == bound


def rebind_replacement_started(record: dict | None, saved_url: str) -> bool:
    record = record or {}
    if not rebind_replacement_bound(record, saved_url):
        return False
    if int(record.get("rebind_replacement_count") or 0) < 1:
        return False
    return str(record.get("rebind_replacement_status") or "") == "started"


def rebind_resume_consumed(record: dict | None) -> bool:
    record = record or {}
    return int(record.get("rebind_resume_count") or 0) >= 1


def rebind_replacement_allowed(record: dict | None, saved_url: str) -> bool:
    """One replacement, only for the 2.2.15 missing-page migration state."""
    record = record or {}
    if rebind_replacement_started(record, saved_url):
        return False
    if not rebind_bound(record, saved_url):
        return False
    if str(record.get("rebind_status") or "") != "failed":
        return False
    if int(record.get("rebind_count") or 0) < 1:
        return False
    if bool(record.get("rebind_bootstrap_sent")):
        return False
    if str(record.get("rebind_failure_reason") or "").strip() != "missing_page":
        return False
    if not rebind_resume_consumed(record):
        return False
    saved = rebind_target(saved_url)
    current = rebind_target(str(record.get("chatgpt_control_url") or ""))
    if not saved or current != saved:
        return False
    if str(record.get("rebind_replacement_status") or "") in {"started", "failed", "done"}:
        return False
    if int(record.get("rebind_replacement_count") or 0) >= 1:
        return False
    return True


def should_replace_rebind(record: dict | None, saved_url: str, action: str) -> bool:
    """Continue a started replacement, or start one from the missing-page state."""
    if action == "ready":
        return False
    if rebind_replacement_started(record, saved_url):
        return True
    if action == "rebind":
        return False
    return rebind_replacement_allowed(record, saved_url)


def mark_rebind_replacement_started(old_url: str) -> bool:
    existing = _read_control_file()
    if not is_chatgpt_conversation_url(str(existing.get("chatgpt_control_url") or "")):
        return False
    existing["rebind_replacement_for_url"] = rebind_target(old_url) or str(old_url)
    existing["rebind_replacement_count"] = max(1, int(existing.get("rebind_replacement_count") or 0))
    existing["rebind_replacement_status"] = "started"
    save_control_record(existing)
    return True


def mark_rebind_replacement_failed(old_url: str, reason: str) -> None:
    existing = _read_control_file()
    if not is_chatgpt_conversation_url(str(existing.get("chatgpt_control_url") or "")):
        return
    existing["rebind_replacement_for_url"] = rebind_target(old_url) or str(existing.get("rebind_replacement_for_url") or "")
    existing["rebind_replacement_count"] = max(1, int(existing.get("rebind_replacement_count") or 0))
    existing["rebind_replacement_status"] = "failed"
    existing["rebind_replacement_failure_reason"] = stable_rebind_reason(reason)
    save_control_record(existing)


def mark_rebind_replacement_result(old_url: str, failure_reason: str = "") -> None:
    existing = _read_control_file()
    if not is_chatgpt_conversation_url(str(existing.get("chatgpt_control_url") or "")):
        return
    existing["rebind_replacement_for_url"] = rebind_target(old_url) or str(existing.get("rebind_replacement_for_url") or "")
    existing["rebind_replacement_count"] = max(1, int(existing.get("rebind_replacement_count") or 0))
    if existing.get("rebind_status") == "done":
        existing["rebind_replacement_status"] = "done"
        existing.pop("rebind_replacement_failure_reason", None)
    else:
        existing["rebind_replacement_status"] = "failed"
        reason = str(failure_reason or existing.get("rebind_failure_reason") or "").strip() or "failed"
        existing["rebind_replacement_failure_reason"] = stable_rebind_reason(reason)
    save_control_record(existing)


def find_replacement_page(browser):
    for page in all_pages(browser):
        if page_restore_mark(page) == REBIND_REPLACEMENT_PAGE_MARK:
            return page
    return None


def mark_replacement_page(page) -> None:
    try:
        page.evaluate("(name) => { window.name = name }", REBIND_REPLACEMENT_PAGE_MARK)
    except Exception:
        pass


def finish_replacement_page(page, old_url: str, goto_home: bool, browser=None) -> None:
    """Hydrate one already-created replacement page. Never opens a tab."""
    record = load_control_record()
    if record.get("rebind_bootstrap_sent"):
        url = wait_for_conversation_url(page, CONTROL_REBIND_URL_WAIT)
        if url and is_usable_control_url(url) and not same_conversation(url, old_url):
            commit_rebind(url, old_url, browser=browser, keep=page)
            mark_rebind_replacement_result(old_url)
            log("CONTROL: page=rebound")
            return
        mark_rebind_failed(old_url, "no_new_url")
        mark_rebind_replacement_result(old_url, "no_new_url")
        log("CONTROL: rebind=replacement_failed reason=no_new_url")
        return
    hydrate_rebind_page(page, old_url, goto_home=goto_home, browser=browser)
    record = load_control_record()
    if record.get("rebind_status") == "done":
        mark_rebind_replacement_result(old_url)
        log("CONTROL: rebind=replacement_done")
        return
    reason = str(record.get("rebind_failure_reason") or "").strip() or "failed"
    mark_rebind_replacement_result(old_url, reason)
    log(f"CONTROL: rebind=replacement_failed reason={stable_rebind_reason(reason)}")


def replace_control_rebind(browser, old_url: str):
    """One fresh service page after the missing-page migration. Never a second tab."""
    record = load_control_record()
    started = rebind_replacement_started(record, old_url)
    if not started and not rebind_replacement_allowed(record, old_url):
        return find_replacement_page(browser)
    page = find_replacement_page(browser)
    if started:
        log("CONTROL: rebind=replacement_resume")
        if page is None:
            mark_rebind_replacement_failed(old_url, "missing_page")
            log("CONTROL: rebind=replacement_failed reason=missing_page")
            return None
        current = str(getattr(page, "url", "") or "")
        if (
            is_usable_control_url(current)
            and not same_conversation(current, old_url)
            and not record.get("rebind_bootstrap_sent")
        ):
            mark_rebind_replacement_failed(old_url, "unexpected_url")
            log("CONTROL: rebind=replacement_failed reason=unexpected_url")
            return page
        finish_replacement_page(page, old_url, goto_home=not rebind_page_on_home(current), browser=browser)
        if str(load_control_record().get("rebind_replacement_status") or "") == "failed":
            globals().get("close_control_service_pages", lambda *_a, **_k: 0)(browser, keep=None)
        return page
    if not mark_rebind_replacement_started(old_url):
        log("CONTROL: rebind=replacement_failed reason=failed")
        return None
    log("CONTROL: rebind=replacement")
    try:
        page = browser.contexts[0].new_page()
    except Exception as exc:
        mark_rebind_replacement_failed(old_url, "failed")
        log(f"CONTROL: rebind=replacement_failed reason=failed error={type(exc).__name__}")
        return None
    mark_replacement_page(page)
    log("CONTROL: page=replacement_create")
    finish_replacement_page(page, old_url, goto_home=True, browser=browser)
    if str(load_control_record().get("rebind_replacement_status") or "") == "failed":
        globals().get("close_control_service_pages", lambda *_a, **_k: 0)(browser, keep=None)
    return page


def _diag_finalize_status(record: dict | None) -> str:
    token = str((record or {}).get("rebind_finalize_status") or "").strip()
    return token if token in {"started", "submitted", "done", "failed"} else "none"


def messages_exact_bootstrap(messages: list[dict] | None) -> bool:
    expected = str(CONTROL_BOOTSTRAP or "").strip()
    return any(
        item.get("role") == "user" and str(item.get("text") or "").strip() == expected
        for item in list(messages or [])[-60:]
    )


def positive_finalize_identity(messages: list[dict] | None) -> bool:
    """Exact bootstrap user text or CONTROL READY. Marker-only text is not enough."""
    return messages_exact_bootstrap(messages) or assistant_has_control_ready(list(messages or []))


def finalize_commit_url(url: str, old_url: str, messages: list[dict] | None) -> str:
    observed = normalize_conversation_url(url)
    if not observed or same_conversation(observed, old_url):
        return ""
    if not positive_finalize_identity(messages):
        return ""
    return observed


def submit_confirmation_action(
    user_message: bool,
    generation_active: bool,
    usable_new_url: bool,
    composer_exact: bool,
    retry_used: bool,
) -> str:
    """confirmed, retry, or fail. Does not include message text."""
    if user_message or generation_active or usable_new_url:
        return "confirmed"
    if composer_exact and not retry_used:
        return "retry"
    return "fail"


def rebind_finalize_bound(record: dict | None, saved_url: str) -> bool:
    record = record or {}
    saved = rebind_target(saved_url)
    bound = rebind_target(str(record.get("rebind_finalize_for_url") or ""))
    return bool(saved) and saved == bound


def rebind_finalize_continue(record: dict | None, saved_url: str) -> bool:
    record = record or {}
    if not rebind_finalize_bound(record, saved_url):
        return False
    if int(record.get("rebind_finalize_count") or 0) < 1:
        return False
    return str(record.get("rebind_finalize_status") or "") in {"started", "submitted"}


def rebind_finalize_allowed(record: dict | None, saved_url: str) -> bool:
    """Only the consumed no_new_url replacement may be finalized."""
    record = record or {}
    if rebind_finalize_continue(record, saved_url):
        return False
    if int(record.get("rebind_finalize_count") or 0) >= 1:
        return False
    if str(record.get("rebind_finalize_status") or "") in {"started", "submitted", "done", "failed"}:
        return False
    if not rebind_bound(record, saved_url):
        return False
    if str(record.get("rebind_status") or "") != "failed":
        return False
    if not bool(record.get("rebind_bootstrap_sent")):
        return False
    if str(record.get("rebind_failure_reason") or "").strip() != "no_new_url":
        return False
    if int(record.get("rebind_replacement_count") or 0) < 1:
        return False
    if str(record.get("rebind_replacement_status") or "") != "failed":
        return False
    if str(record.get("rebind_replacement_failure_reason") or "").strip() != "no_new_url":
        return False
    saved = rebind_target(saved_url)
    current = rebind_target(str(record.get("chatgpt_control_url") or ""))
    if not saved or current != saved:
        return False
    return True


def should_finalize_rebind(record: dict | None, saved_url: str, action: str) -> bool:
    if action == "ready":
        return False
    if rebind_finalize_continue(record, saved_url):
        return True
    if action == "rebind":
        return False
    return rebind_finalize_allowed(record, saved_url)


def mark_finalize_started(old_url: str) -> bool:
    existing = _read_control_file()
    if not is_chatgpt_conversation_url(str(existing.get("chatgpt_control_url") or "")):
        return False
    status = str(existing.get("rebind_finalize_status") or "")
    if status in {"done", "failed"}:
        return False
    existing["rebind_finalize_for_url"] = rebind_target(old_url) or str(old_url)
    existing["rebind_finalize_count"] = max(1, int(existing.get("rebind_finalize_count") or 0))
    if status != "submitted":
        existing["rebind_finalize_status"] = "started"
    save_control_record(existing)
    return True


def mark_finalize_submitted(old_url: str) -> None:
    existing = _read_control_file()
    if not is_chatgpt_conversation_url(str(existing.get("chatgpt_control_url") or "")):
        return
    existing["rebind_finalize_for_url"] = rebind_target(old_url) or str(existing.get("rebind_finalize_for_url") or "")
    existing["rebind_finalize_count"] = max(1, int(existing.get("rebind_finalize_count") or 0))
    existing["rebind_finalize_status"] = "submitted"
    existing["rebind_submission_status"] = "confirmed"
    existing["rebind_url_status"] = "pending"
    existing["rebind_bootstrap_sent"] = True
    existing.pop("rebind_finalize_failure_reason", None)
    save_control_record(existing)


def mark_finalize_failed(old_url: str, reason: str) -> None:
    existing = _read_control_file()
    if not is_chatgpt_conversation_url(str(existing.get("chatgpt_control_url") or "")):
        return
    existing["rebind_finalize_for_url"] = rebind_target(old_url) or str(existing.get("rebind_finalize_for_url") or "")
    existing["rebind_finalize_count"] = max(1, int(existing.get("rebind_finalize_count") or 0))
    existing["rebind_finalize_status"] = "failed"
    existing["rebind_finalize_failure_reason"] = stable_rebind_reason(reason)
    save_control_record(existing)


def mark_submit_retry_started(old_url: str) -> bool:
    existing = _read_control_file()
    if not is_chatgpt_conversation_url(str(existing.get("chatgpt_control_url") or "")):
        return False
    if int(existing.get("rebind_submit_retry_count") or 0) >= 1:
        return False
    existing["rebind_submit_retry_for_url"] = rebind_target(old_url) or str(old_url)
    existing["rebind_submit_retry_count"] = 1
    existing["rebind_submit_retry_status"] = "started"
    save_control_record(existing)
    return True


def mark_submit_retry_result(old_url: str, status: str) -> None:
    existing = _read_control_file()
    if not is_chatgpt_conversation_url(str(existing.get("chatgpt_control_url") or "")):
        return
    existing["rebind_submit_retry_for_url"] = rebind_target(old_url) or str(existing.get("rebind_submit_retry_for_url") or "")
    existing["rebind_submit_retry_count"] = max(1, int(existing.get("rebind_submit_retry_count") or 0))
    existing["rebind_submit_retry_status"] = "done" if status == "done" else "failed"
    save_control_record(existing)


def composer_text(page) -> str:
    selectors = ("#prompt-textarea", "[contenteditable='true'][role='textbox']")
    for selector in selectors:
        try:
            loc = page.locator(selector)
            if loc.count() == 0:
                continue
            box = loc.first
            value = ""
            try:
                value = box.input_value()
            except Exception:
                try:
                    value = box.inner_text()
                except Exception:
                    value = ""
            return str(value or "").strip()
        except Exception:
            continue
    return ""


def composer_has_exact_text(page, text: str) -> bool:
    return str(composer_text(page) or "").strip() == str(text or "").strip()


def submit_composer_only(page, expected: str = "") -> str:
    """Press Enter or click send on the current composer. Never fills text."""
    pressed = False
    selectors = ("#prompt-textarea", "[contenteditable='true'][role='textbox']")
    for selector in selectors:
        try:
            loc = page.locator(selector)
            if loc.count() == 0:
                continue
            box = loc.first
            try:
                box.evaluate("(el) => el.focus()")
            except Exception:
                pass
            box.press("Enter")
            pressed = True
            break
        except Exception:
            continue
    still_exact = bool(expected) and composer_has_exact_text(page, expected)
    if still_exact or not pressed:
        for selector in (
            "button[data-testid='send-button']",
            "button[data-testid='composer-send-button']",
            "button[aria-label='Send prompt']",
            "button[aria-label='Send message']",
        ):
            try:
                loc = page.locator(selector)
                if loc.count() and loc.first.is_visible():
                    loc.first.click()
                    return "click"
            except Exception:
                continue
    return "enter" if pressed else "failed"


def _submit_confirmed(page, text: str, before_url: str) -> bool:
    deadline = time.time() + CONTROL_SUBMIT_CONFIRM_SECONDS
    before = normalize_conversation_url(before_url)
    while True:
        user_message = False
        generating = False
        try:
            user_message = bool(chatgpt_user_message_exists(page, text))
        except Exception:
            user_message = False
        try:
            generating = bool(generation_is_active(page))
        except Exception:
            generating = False
        current = normalize_conversation_url(str(getattr(page, "url", "") or ""))
        usable_new = bool(current) and current != before
        if submit_confirmation_action(user_message, generating, usable_new, False, True) == "confirmed":
            return True
        now = time.time()
        if now >= deadline:
            return False
        remaining = deadline - now
        time.sleep(min(REBIND_COMPOSER_POLL_SECONDS, max(0.05, remaining)))


def page_control_evidence(page) -> dict:
    messages: list[dict] = []
    try:
        messages = list(chatgpt_messages(page) or [])
    except Exception:
        messages = []
    composer = ""
    try:
        composer = composer_text(page)
    except Exception:
        composer = ""
    generating = False
    signed_out = False
    unavailable = False
    try:
        generating = bool(generation_is_active(page))
    except Exception:
        generating = False
    try:
        signed_out = bool(page_signed_out(page))
    except Exception:
        signed_out = False
    try:
        unavailable = bool(page_shows_unavailable(page))
    except Exception:
        unavailable = False
    return {
        "url": str(getattr(page, "url", "") or ""),
        "messages": messages,
        "composer": composer,
        "generation": generating,
        "signed_out": signed_out,
        "unavailable": unavailable,
    }


def finalize_page_observations(browser) -> list[tuple]:
    marked = find_replacement_page(browser)
    ordered = []
    seen = set()
    if marked is not None:
        ordered.append(marked)
        seen.add(id(marked))
    for page in all_pages(browser):
        if id(page) in seen:
            continue
        if "chatgpt.com" not in str(getattr(page, "url", "") or ""):
            continue
        ordered.append(page)
    observations = []
    for page in ordered:
        evidence = page_control_evidence(page)
        evidence["marked"] = page is marked
        observations.append((page, evidence))
    return observations


def _pick_finalize_commit(observations, old_url: str, submission_confirmed: bool):
    for page, evidence in observations:
        observed = normalize_conversation_url(str(evidence.get("url") or ""))
        if not observed or same_conversation(observed, old_url):
            continue
        if positive_finalize_identity(evidence.get("messages") or []):
            return page, observed
        if submission_confirmed and evidence.get("marked"):
            return page, observed
    return None, ""


def _finalize_positive(observations) -> bool:
    return any(positive_finalize_identity(evidence.get("messages") or []) for _page, evidence in observations)


def wait_for_finalize_commit(browser, old_url: str, submission_confirmed: bool):
    deadline = time.time() + CONTROL_FINALIZE_URL_WAIT
    announced = False
    while True:
        observations = finalize_page_observations(browser)
        page, url = _pick_finalize_commit(observations, old_url, submission_confirmed)
        if url:
            return page, url
        now = time.time()
        if now >= deadline:
            return None, ""
        if not announced:
            log("CONTROL: rebind=finalize_wait")
            announced = True
        remaining = deadline - now
        time.sleep(min(REBIND_COMPOSER_POLL_SECONDS, max(0.05, remaining)))


def _commit_finalize(browser, page, url: str, old_url: str):
    commit_rebind(url, old_url, browser=browser, keep=page)
    log("CONTROL: page=finalize_commit")
    return page


def finalize_control_rebind(browser, old_url: str):
    """Rescue one no_new_url submission. Never opens a tab or refills bootstrap."""
    record = load_control_record()
    if not rebind_finalize_continue(record, old_url) and not rebind_finalize_allowed(record, old_url):
        return find_replacement_page(browser)
    already_submitted = str(record.get("rebind_finalize_status") or "") == "submitted"
    if not mark_finalize_started(old_url):
        log("CONTROL: rebind=finalize_failed reason=failed")
        return find_replacement_page(browser)
    log("CONTROL: rebind=finalize")
    observations = finalize_page_observations(browser)
    page, url = _pick_finalize_commit(observations, old_url, False)
    if url:
        return _commit_finalize(browser, page, url, old_url)
    if already_submitted:
        log("CONTROL: rebind=finalize_scan")
        return find_replacement_page(browser)

    marked = find_replacement_page(browser)
    marked_evidence = {}
    for candidate, evidence in observations:
        if evidence.get("marked"):
            marked_evidence = evidence
            break
    positive = _finalize_positive(observations)
    if positive:
        page, url = wait_for_finalize_commit(browser, old_url, True)
        if url:
            return _commit_finalize(browser, page, url, old_url)
        mark_finalize_submitted(old_url)
        log("CONTROL: rebind=finalize_submitted")
        return marked

    composer = str(marked_evidence.get("composer") or "")
    on_home = marked is not None and rebind_page_on_home(str(marked_evidence.get("url") or getattr(marked, "url", "") or ""))
    exact_composer = on_home and composer.strip() == str(CONTROL_BOOTSTRAP or "").strip()
    if exact_composer and not positive:
        record = load_control_record()
        if int(record.get("rebind_submit_retry_count") or 0) >= 1:
            mark_finalize_failed(old_url, "submit_unconfirmed")
            log("CONTROL: rebind=finalize_failed reason=submit_unconfirmed")
            return marked
        if not mark_submit_retry_started(old_url):
            mark_finalize_failed(old_url, "failed")
            log("CONTROL: rebind=finalize_failed reason=failed")
            return marked
        log("CONTROL: rebind=finalize_submit")
        submit_composer_only(marked, CONTROL_BOOTSTRAP)
        mark_submit_retry_result(old_url, "done")
        observations = finalize_page_observations(browser)
        page, url = _pick_finalize_commit(observations, old_url, True)
        if url:
            return _commit_finalize(browser, page, url, old_url)
        if _finalize_positive(observations) or any(item[1].get("generation") and item[1].get("marked") for item in observations):
            page, url = wait_for_finalize_commit(browser, old_url, True)
            if url:
                return _commit_finalize(browser, page, url, old_url)
            mark_finalize_submitted(old_url)
            log("CONTROL: rebind=finalize_submitted")
            return marked
        mark_finalize_failed(old_url, "submit_unconfirmed")
        log("CONTROL: rebind=finalize_failed reason=submit_unconfirmed")
        return marked

    if marked is None:
        mark_finalize_failed(old_url, "missing_page")
        log("CONTROL: rebind=finalize_failed reason=missing_page")
        return None
    if marked_evidence.get("signed_out"):
        mark_finalize_failed(old_url, "signed_out")
        log("CONTROL: rebind=finalize_failed reason=signed_out")
        return marked
    if marked_evidence.get("unavailable"):
        mark_finalize_failed(old_url, "hard_unavailable")
        log("CONTROL: rebind=finalize_failed reason=hard_unavailable")
        return marked
    mark_finalize_failed(old_url, "no_evidence")
    log("CONTROL: rebind=finalize_failed reason=no_evidence")
    return marked


def _diag_reprovision_status(record: dict | None) -> str:
    token = str((record or {}).get("rebind_reprovision_status") or "").strip()
    return token if token in {"started", "failed", "done"} else "none"


def rebind_reprovision_bound(record: dict | None, saved_url: str) -> bool:
    if not record or not saved_url:
        return False
    target = rebind_target(saved_url)
    bound = rebind_target(str(record.get("rebind_reprovision_for_url") or ""))
    return bool(target) and target == bound


def rebind_reprovision_started(record: dict | None, saved_url: str) -> bool:
    if not rebind_reprovision_bound(record, saved_url):
        return False
    return (
        int(record.get("rebind_reprovision_count") or 0) >= 1
        and str(record.get("rebind_reprovision_status") or "") == "started"
    )


def rebind_reprovision_allowed(record: dict | None, saved_url: str) -> bool:
    """Only the consumed 2.2.17 missing_page state may open one service page."""
    if not record or not is_usable_control_url(saved_url):
        return False
    target = rebind_target(saved_url)
    if not target or rebind_target(str(record.get("chatgpt_control_url") or "")) != target:
        return False
    if rebind_target(str(record.get("rebind_for_url") or "")) != target:
        return False
    if str(record.get("rebind_status") or "") != "failed":
        return False
    if str(record.get("rebind_failure_reason") or "") != "no_new_url":
        return False
    if record.get("rebind_bootstrap_sent") is not True:
        return False
    if int(record.get("rebind_replacement_count") or 0) < 1:
        return False
    if str(record.get("rebind_replacement_status") or "") != "failed":
        return False
    if str(record.get("rebind_replacement_failure_reason") or "") != "no_new_url":
        return False
    if rebind_target(str(record.get("rebind_replacement_for_url") or "")) != target:
        return False
    if int(record.get("rebind_finalize_count") or 0) < 1:
        return False
    if str(record.get("rebind_finalize_status") or "") != "failed":
        return False
    if str(record.get("rebind_finalize_failure_reason") or "") != "missing_page":
        return False
    if rebind_target(str(record.get("rebind_finalize_for_url") or "")) != target:
        return False
    if int(record.get("rebind_reprovision_count") or 0) >= 1:
        return False
    if str(record.get("rebind_reprovision_status") or "") in {"started", "failed", "done"}:
        return False
    return True


def reprovision_failed_closed(record: dict | None, saved_url: str) -> bool:
    """A consumed reprovision must not fall through to another new tab."""
    if not rebind_reprovision_bound(record, saved_url):
        return False
    if rebind_target(str(record.get("chatgpt_control_url") or "")) != rebind_target(saved_url):
        return False
    if int(record.get("rebind_reprovision_count") or 0) < 1:
        return False
    return str(record.get("rebind_reprovision_status") or "") == "failed"


def should_reprovision_rebind(record: dict | None, saved_url: str, action: str) -> bool:
    if action == "ready":
        return False
    if rebind_reprovision_started(record, saved_url):
        return True
    return rebind_reprovision_allowed(record, saved_url)


def mark_reprovision_started(old_url: str) -> bool:
    existing = _read_control_file()
    if not is_chatgpt_conversation_url(str(existing.get("chatgpt_control_url") or "")):
        return False
    target = rebind_target(old_url) or str(old_url)
    if int(existing.get("rebind_reprovision_count") or 0) >= 1:
        return False
    if str(existing.get("rebind_reprovision_status") or "") in {"started", "failed", "done"}:
        return False
    existing["rebind_reprovision_for_url"] = target
    existing["rebind_reprovision_count"] = 1
    existing["rebind_reprovision_status"] = "started"
    save_control_record(existing)
    return True


def mark_reprovision_failed(old_url: str, reason: str) -> None:
    existing = _read_control_file()
    if not is_chatgpt_conversation_url(str(existing.get("chatgpt_control_url") or "")):
        return
    target = rebind_target(old_url) or str(old_url)
    bound = rebind_target(str(existing.get("rebind_reprovision_for_url") or ""))
    if bound and bound != target:
        return
    existing["rebind_reprovision_for_url"] = target
    existing["rebind_reprovision_count"] = max(1, int(existing.get("rebind_reprovision_count") or 0))
    existing["rebind_reprovision_status"] = "failed"
    existing["rebind_reprovision_failure_reason"] = stable_rebind_reason(reason)
    save_control_record(existing)


def mark_reprovision_attempted(old_url: str) -> bool:
    existing = _read_control_file()
    if not is_chatgpt_conversation_url(str(existing.get("chatgpt_control_url") or "")):
        return False
    if existing.get("rebind_reprovision_bootstrap_attempted"):
        return False
    existing["rebind_reprovision_bootstrap_attempted"] = True
    existing["rebind_reprovision_submission_status"] = "attempted"
    save_control_record(existing)
    return True


def mark_reprovision_submission(old_url: str, status: str) -> None:
    existing = _read_control_file()
    if not is_chatgpt_conversation_url(str(existing.get("chatgpt_control_url") or "")):
        return
    if status not in {"attempted", "confirmed", "failed"}:
        return
    existing["rebind_reprovision_bootstrap_attempted"] = True
    existing["rebind_reprovision_submission_status"] = status
    save_control_record(existing)


def mark_reprovision_retry_started(old_url: str) -> bool:
    existing = _read_control_file()
    if not is_chatgpt_conversation_url(str(existing.get("chatgpt_control_url") or "")):
        return False
    target = rebind_target(old_url) or str(old_url)
    if int(existing.get("rebind_reprovision_submit_retry_count") or 0) >= 1:
        return False
    existing["rebind_reprovision_submit_retry_for_url"] = target
    existing["rebind_reprovision_submit_retry_count"] = 1
    existing["rebind_reprovision_submit_retry_status"] = "started"
    save_control_record(existing)
    return True


def mark_reprovision_retry_result(old_url: str, status: str) -> None:
    existing = _read_control_file()
    if not is_chatgpt_conversation_url(str(existing.get("chatgpt_control_url") or "")):
        return
    if status not in {"done", "failed"}:
        return
    existing["rebind_reprovision_submit_retry_count"] = max(
        1, int(existing.get("rebind_reprovision_submit_retry_count") or 0)
    )
    existing["rebind_reprovision_submit_retry_status"] = status
    save_control_record(existing)


def find_reprovision_page(browser):
    for page in all_pages(browser):
        if page_restore_mark(page) == REBIND_REPROVISION_PAGE_MARK:
            return page
    return None


def mark_reprovision_page(page) -> None:
    try:
        page.evaluate("(name) => { window.name = name }", REBIND_REPROVISION_PAGE_MARK)
    except Exception:
        pass


def reprovision_page_observations(browser) -> list[tuple]:
    marked = find_reprovision_page(browser)
    ordered = []
    seen = set()
    if marked is not None:
        ordered.append(marked)
        seen.add(id(marked))
    for page in all_pages(browser):
        if id(page) in seen:
            continue
        if "chatgpt.com" not in str(getattr(page, "url", "") or ""):
            continue
        ordered.append(page)
    observations = []
    for page in ordered:
        evidence = page_control_evidence(page)
        evidence["reprovision"] = page is marked
        observations.append((page, evidence))
    return observations


def _pick_reprovision_commit(observations, old_url: str, marked_confirmed: bool):
    for page, evidence in observations:
        observed = normalize_conversation_url(str(evidence.get("url") or ""))
        if not observed or same_conversation(observed, old_url):
            continue
        if positive_finalize_identity(evidence.get("messages") or []):
            return page, observed
        if marked_confirmed and evidence.get("reprovision"):
            return page, observed
    return None, ""


def wait_for_reprovision_commit(browser, old_url: str, marked_confirmed: bool):
    deadline = time.time() + CONTROL_REPROVISION_URL_WAIT
    announced = False
    while True:
        observations = reprovision_page_observations(browser)
        page, url = _pick_reprovision_commit(observations, old_url, marked_confirmed)
        if url:
            return page, url
        now = time.time()
        if now >= deadline:
            return None, ""
        if not announced:
            log("CONTROL: rebind=reprovision_wait")
            announced = True
        remaining = deadline - now
        time.sleep(min(REBIND_COMPOSER_POLL_SECONDS, max(0.05, remaining)))


def fill_composer_once(page, text: str) -> None:
    box = chatgpt_prompt(page)
    try:
        box.evaluate("(el) => el.focus()")
    except Exception:
        pass
    box.fill(text)
    box.press("Enter")


def _composer_exact_bootstrap(text: str) -> bool:
    return str(text or "").strip() == str(CONTROL_BOOTSTRAP or "").strip()


def reprovision_submit_confirmed(page, before_url: str) -> bool:
    """Same 8s confirmation as 2.2.17: exact user text, generation, or a new /c/ URL."""
    return bool(_submit_confirmed(page, CONTROL_BOOTSTRAP, before_url))


def submit_reprovision_bootstrap(page, old_url: str) -> str:
    """Fill at most once. The legacy sent flag is not consulted."""
    record = load_control_record()
    if str(record.get("rebind_reprovision_submission_status") or "") == "confirmed":
        return "confirmed"
    before = str(getattr(page, "url", "") or "")
    attempted = bool(record.get("rebind_reprovision_bootstrap_attempted"))
    if not attempted:
        if not mark_reprovision_attempted(old_url):
            return "failed"
        log("CONTROL: rebind=reprovision_send")
        try:
            fill_composer_once(page, CONTROL_BOOTSTRAP)
        except Exception as exc:
            mark_reprovision_submission(old_url, "failed")
            log(f"CONTROL: rebind=reprovision_failed reason=failed error={type(exc).__name__}")
            return "failed"
        if reprovision_submit_confirmed(page, before):
            mark_reprovision_submission(old_url, "confirmed")
            log("CONTROL: rebind=reprovision_confirmed")
            return "confirmed"
    elif reprovision_submit_confirmed(page, before):
        mark_reprovision_submission(old_url, "confirmed")
        log("CONTROL: rebind=reprovision_confirmed")
        return "confirmed"
    evidence = page_control_evidence(page)
    composer = str(evidence.get("composer") or "")
    record = load_control_record()
    retry_used = int(record.get("rebind_reprovision_submit_retry_count") or 0) >= 1
    if _composer_exact_bootstrap(composer) and not retry_used:
        if not mark_reprovision_retry_started(old_url):
            mark_reprovision_submission(old_url, "failed")
            return "submit_unconfirmed"
        log("CONTROL: rebind=reprovision_submit")
        try:
            submit_composer_only(page, CONTROL_BOOTSTRAP)
        except Exception as exc:
            mark_reprovision_retry_result(old_url, "failed")
            mark_reprovision_submission(old_url, "failed")
            log(f"CONTROL: rebind=reprovision_failed reason=failed error={type(exc).__name__}")
            return "submit_unconfirmed"
        if reprovision_submit_confirmed(page, before):
            mark_reprovision_retry_result(old_url, "done")
            mark_reprovision_submission(old_url, "confirmed")
            log("CONTROL: rebind=reprovision_confirmed")
            return "confirmed"
        mark_reprovision_retry_result(old_url, "failed")
        mark_reprovision_submission(old_url, "failed")
        return "submit_unconfirmed"
    mark_reprovision_submission(old_url, "failed")
    return "submit_unconfirmed"


def _commit_reprovision(browser, page, url: str, old_url: str):
    observed = normalize_conversation_url(url)
    if not observed or same_conversation(observed, old_url):
        mark_reprovision_failed(old_url, "no_new_url")
        log("CONTROL: rebind=reprovision_failed reason=no_new_url")
        return page
    try:
        commit_rebind(observed, old_url, browser=browser, keep=page)
    except Exception as exc:
        mark_reprovision_failed(old_url, "failed")
        log(f"CONTROL: rebind=reprovision_failed reason=failed error={type(exc).__name__}")
        return page
    log("CONTROL: page=reprovision_commit")
    return page


def finish_reprovision_page(browser, page, old_url: str, goto_home: bool):
    if goto_home:
        log("CONTROL: rebind=reprovision_home")
        try:
            page.goto(
                CHATGPT_HOME,
                wait_until="domcontentloaded",
                timeout=CONTROL_RESTORE_GOTO_TIMEOUT,
            )
        except Exception as exc:
            mark_reprovision_failed(old_url, "goto")
            log(f"CONTROL: rebind=reprovision_failed reason=goto error={type(exc).__name__}")
            return page
    record = load_control_record()
    confirmed = str(record.get("rebind_reprovision_submission_status") or "") == "confirmed"
    if not confirmed:
        try:
            signed_out = bool(page_signed_out(page))
        except Exception:
            signed_out = False
        if signed_out:
            mark_reprovision_failed(old_url, "signed_out")
            log("CONTROL: rebind=reprovision_failed reason=signed_out")
            return page
        try:
            unavailable = bool(page_shows_unavailable(page))
        except Exception:
            unavailable = False
        if unavailable:
            mark_reprovision_failed(old_url, "hard_unavailable")
            log("CONTROL: rebind=reprovision_failed reason=hard_unavailable")
            return page
        if not bool(record.get("rebind_reprovision_bootstrap_attempted")):
            composer = wait_for_rebind_composer(page, CONTROL_REBIND_COMPOSER_WAIT)
            if composer != "ready":
                reason = stable_rebind_reason(composer or "no_composer")
                mark_reprovision_failed(old_url, reason)
                log(f"CONTROL: rebind=reprovision_failed reason={reason}")
                return page
        result = submit_reprovision_bootstrap(page, old_url)
        if result != "confirmed":
            reason = stable_rebind_reason(result)
            mark_reprovision_failed(old_url, reason)
            log(f"CONTROL: rebind=reprovision_failed reason={reason}")
            return page
    found, url = wait_for_reprovision_commit(browser, old_url, True)
    if url:
        return _commit_reprovision(browser, found, url, old_url)
    mark_reprovision_failed(old_url, "no_new_url")
    log("CONTROL: rebind=reprovision_failed reason=no_new_url")
    return page


def reprovision_control_rebind(browser, old_url: str):
    """One service page after finalize missing_page. Never a second tab."""
    record = load_control_record()
    started = rebind_reprovision_started(record, old_url)
    if not started and not rebind_reprovision_allowed(record, old_url):
        return find_reprovision_page(browser)
    if not started:
        observations = reprovision_page_observations(browser)
        page, url = _pick_reprovision_commit(observations, old_url, False)
        if url:
            if not mark_reprovision_started(old_url):
                log("CONTROL: rebind=reprovision_failed reason=failed")
                return page
            return _commit_reprovision(browser, page, url, old_url)
        if not mark_reprovision_started(old_url):
            log("CONTROL: rebind=reprovision_failed reason=failed")
            return None
        log("CONTROL: rebind=reprovision")
        try:
            page = browser.contexts[0].new_page()
        except Exception as exc:
            mark_reprovision_failed(old_url, "failed")
            log(f"CONTROL: rebind=reprovision_failed reason=failed error={type(exc).__name__}")
            return None
        mark_reprovision_page(page)
        log("CONTROL: page=reprovision_create")
        return finish_reprovision_page(browser, page, old_url, True)
    log("CONTROL: rebind=reprovision_resume")
    page = find_reprovision_page(browser)
    if page is None:
        mark_reprovision_failed(old_url, "missing_page")
        log("CONTROL: rebind=reprovision_failed reason=missing_page")
        return None
    current = str(getattr(page, "url", "") or "")
    if is_usable_control_url(current) and not same_conversation(current, old_url):
        evidence = page_control_evidence(page)
        confirmed = str(record.get("rebind_reprovision_submission_status") or "") == "confirmed"
        if positive_finalize_identity(evidence.get("messages") or []) or confirmed:
            return _commit_reprovision(browser, page, current, old_url)
        mark_reprovision_failed(old_url, "unexpected_url")
        log("CONTROL: rebind=reprovision_failed reason=unexpected_url")
        return page
    result = finish_reprovision_page(
        browser,
        page,
        old_url,
        not rebind_page_on_home(current),
    )
    if str(load_control_record().get("rebind_reprovision_status") or "") == "failed":
        globals().get("close_control_service_pages", lambda *_a, **_k: 0)(browser, keep=None)
    return result


def find_arena_page(browser):
    exact = []
    fallback = []

    for page in all_pages(browser):
        url = page.url or ""
        if url_matches(url, ARENA_URL):
            exact.append(page)
        elif "arena.ai" in url:
            fallback.append(page)

    page = choose_page(exact)
    if page is None:
        page = choose_page(fallback)
    if page is None:
        page = browser.contexts[0].new_page()

    if not url_matches(page.url or "", ARENA_URL):
        page.goto(ARENA_URL, wait_until="domcontentloaded", timeout=PAGE_TIMEOUT)

    return page


# -------------------------
# ChatGPT control chat
# -------------------------

INFER_TURN_ROLE_JS = r"""
function inferTurnRole(roleAttr, labels) {
  const role = String(roleAttr || '').trim().toLowerCase();
  if (role === 'user' || role === 'human' || role.endsWith(':user')) return 'user';
  if (role.includes('assistant')) return 'assistant';
  const blob = String(labels || '').toLowerCase();
  if (blob.includes('you said') || blob.includes('вы сказали')) return 'user';
  if (blob.includes('chatgpt said') || blob.includes('assistant')) return 'assistant';
  return '';
}
"""

TURN_SELECTOR = "article[data-testid^='conversation-turn-'], [data-message-id]"


def infer_turn_role(role_attr: str = "", labels: str = "") -> str:
    """Map a turn node to user/assistant. The test id itself is not a role."""
    role = str(role_attr or "").strip().lower()
    if role in {"user", "human"} or role.endswith(":user"):
        return "user"
    if "assistant" in role:
        return "assistant"
    blob = str(labels or "").lower()
    if "you said" in blob or "вы сказали" in blob:
        return "user"
    if "chatgpt said" in blob or "assistant" in blob:
        return "assistant"
    return ""


def _read_message_nodes(page, selector: str) -> list[dict]:
    try:
        return page.locator(selector).evaluate_all(
            """nodes => nodes.map(n => ({
                role: n.getAttribute('data-message-author-role') || '',
                text: (n.innerText || '').trim()
            }))"""
        )
    except Exception:
        return []


def _read_turn_nodes(page) -> list[dict]:
    script = INFER_TURN_ROLE_JS + """
nodes => nodes.map(n => {
  const roleNode = n.matches('[data-message-author-role], [data-message-author]')
    ? n
    : n.querySelector('[data-message-author-role], [data-message-author]');
  const roleAttr = roleNode
    ? (roleNode.getAttribute('data-message-author-role') || roleNode.getAttribute('data-message-author') || '')
    : '';
  const labelNode = n.querySelector('h5, h6, [class*="sr-only"], [class*="screen-reader"]');
  const labels = [
    n.getAttribute('aria-label') || '',
    labelNode ? (labelNode.innerText || '') : ''
  ].join(' ');
  return {
    role: inferTurnRole(roleAttr, labels),
    text: (n.innerText || '').trim()
  };
}).filter(x => x.text)
"""
    try:
        return page.locator(TURN_SELECTOR).evaluate_all(script)
    except Exception:
        return []


def _normalize_message(item: dict) -> dict:
    role = infer_turn_role(str(item.get("role") or ""), "")
    if not role:
        role = str(item.get("role") or "").strip().lower()
        if role in {"user", "assistant"}:
            pass
        elif "assistant" in role:
            role = "assistant"
        elif role in {"user", "human"} or role.endswith(":user"):
            role = "user"
        else:
            role = ""
    return {"role": role, "text": str(item.get("text") or "").strip()}


def chatgpt_messages(page) -> list[dict]:
    primary = [_normalize_message(item) for item in _read_message_nodes(page, "[data-message-author-role]")]
    if any(item.get("role") in {"user", "assistant"} and item.get("text") for item in primary):
        return primary
    fallback = [_normalize_message(item) for item in _read_turn_nodes(page)]
    if any(item.get("role") in {"user", "assistant"} and item.get("text") for item in fallback):
        log(f"CONTROL: primary selector empty, fallback messages={len(fallback)}")
        return fallback
    return []


def chatgpt_user_message_exists(page, text: str) -> bool:
    return any(
        item.get("role") == "user" and item.get("text", "").strip() == text
        for item in chatgpt_messages(page)[-60:]
    )


def chatgpt_wake_exists(page, wake: str) -> bool:
    return chatgpt_user_message_exists(page, wake)


def chatgpt_response_complete(page, user_text: str) -> bool:
    messages = chatgpt_messages(page)

    user_index = None
    for idx in range(len(messages) - 1, -1, -1):
        item = messages[idx]
        if item.get("role") == "user" and item.get("text", "").strip() == user_text:
            user_index = idx
            break

    if user_index is None:
        return False

    has_assistant_after = any(
        item.get("role") == "assistant" and item.get("text", "").strip()
        for item in messages[user_index + 1 :]
    )
    if not has_assistant_after:
        return False

    stop_selectors = [
        'button[data-testid="stop-button"]',
        'button[aria-label*="Stop"]',
        'button[aria-label*="Останов"]',
    ]
    for selector in stop_selectors:
        loc = page.locator(selector)
        try:
            for i in range(loc.count()):
                if loc.nth(i).is_visible():
                    return False
        except Exception:
            continue

    return True


def generation_is_active(page) -> bool:
    selectors = (
        "[data-testid='stop-button']",
        "button[aria-label='Stop streaming']",
        "button[aria-label='Stop generating']",
        "button[aria-label='Остановить генерацию']",
        "button[aria-label='Остановить']",
    )
    for selector in selectors:
        try:
            loc = page.locator(selector)
            if loc.count() and loc.first.is_visible():
                return True
        except Exception:
            continue
    return False


def composer_is_ready(page) -> bool:
    selectors = ("#prompt-textarea", "[contenteditable='true'][role='textbox']")
    for selector in selectors:
        try:
            loc = page.locator(selector)
            if loc.count() == 0:
                continue
            box = loc.first
            if not box.is_visible():
                continue
            if box.get_attribute("disabled") is not None:
                continue
            if str(box.get_attribute("aria-disabled") or "").lower() == "true":
                continue
            return True
        except Exception:
            continue
    return False


def chatgpt_prompt(page):
    box = page.locator("#prompt-textarea")
    try:
        box.wait_for(state="visible", timeout=PAGE_TIMEOUT)
        return box
    except Exception:
        fallback = page.locator(
            '[contenteditable="true"][data-virtualkeyboard="true"], '
            '[contenteditable="true"][role="textbox"]'
        )
        fallback.first.wait_for(state="visible", timeout=PAGE_TIMEOUT)
        return fallback.first


def send_to_chatgpt(page, text: str) -> bool:
    """Fill once, confirm submission, and never log the text."""
    before = str(getattr(page, "url", "") or "")
    box = chatgpt_prompt(page)
    try:
        box.evaluate("(el) => el.focus()")
    except Exception:
        pass
    box.fill(text)
    box.press("Enter")
    if _submit_confirmed(page, text, before):
        log("CONTROL: submit=confirmed")
        return True
    if submit_confirmation_action(False, False, False, composer_has_exact_text(page, text), False) == "retry":
        log("CONTROL: submit=retry")
        submit_composer_only(page, text)
        if _submit_confirmed(page, text, before):
            log("CONTROL: submit=confirmed")
            return True
    log("CONTROL: submit=unconfirmed")
    return False


def wait_for_conversation_url(page, timeout_seconds: int = 30) -> str:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        url = page.url or ""
        if is_usable_control_url(url):
            return url.split("?", 1)[0].split("#", 1)[0]
        time.sleep(0.25)
    return ""


def provision_control_chat(browser):
    context = browser.contexts[0]
    page = context.new_page()
    mark_control_service_page(page, CONTROL_PROVISION_PAGE_MARK)
    try:
        page.goto(CHATGPT_HOME, wait_until="domcontentloaded", timeout=PAGE_TIMEOUT)

        log("CONTROL: создаю отдельный машинный ChatGPT-чат 01 — CONTROL & BRIDGE.")
        submitted = send_to_chatgpt(page, CONTROL_BOOTSTRAP)
        if submitted is False:
            raise RuntimeError("CONTROL_BOOTSTRAP_NOT_SUBMITTED")

        control_url = wait_for_conversation_url(page, 30)
        if not control_url:
            raise RuntimeError("CONTROL_CHAT_URL_NOT_CREATED")

        save_control_url(control_url)
        globals().get("close_control_service_pages", lambda *_a, **_k: 0)(browser, keep=page, old_url=control_url)
        return page
    except Exception:
        globals().get("close_control_service_pages", lambda *_a, **_k: 0)(browser)
        raise


def _log_control_diag(
    record: dict,
    messages: list[dict],
    page_url: str,
    action: str,
    wake: str = "",
    generation_active: bool = False,
    composer_ready: bool = False,
    now: float | None = None,
    page_unavailable: bool = False,
) -> str:
    diagnosis = diagnose_control(
        record,
        messages,
        page_url,
        wake=wake,
        generation_active=generation_active,
        composer_ready=composer_ready,
        now=now,
        page_unavailable=page_unavailable,
    )
    users, assistants = control_diag_counts(messages)
    checks = int(record.get("unready_checks") or 0)
    log(
        "CONTROL: "
        f"diag={diagnosis} action={action} messages={len(messages)} "
        f"users={users} assistants={assistants} "
        f"url_usable={int(is_usable_control_url(str(record.get('chatgpt_control_url') or '')))} "
        f"checks={checks} recovery_used={int(bool(record.get('recovery_used')))} "
        f"gen={int(bool(generation_active))} composer={int(bool(composer_ready))} "
        f"unavailable={int(diagnosis == 'unavailable')} "
        f"blank_checks={int(record.get('blank_checks') or 0)} "
        f"blank_rebind={int(bool(record.get('_blank_rebind')))} "
        f"fail={_diag_failure_reason(record)} "
        f"resume_count={int(record.get('rebind_resume_count') or 0)} "
        f"replace_count={int(record.get('rebind_replacement_count') or 0)} "
        f"replace_status={_diag_replacement_status(record)} "
        f"finalize_count={int(record.get('rebind_finalize_count') or 0)} "
        f"finalize_status={_diag_finalize_status(record)} "
        f"reprovision_count={int(record.get('rebind_reprovision_count') or 0)} "
        f"reprovision_status={_diag_reprovision_status(record)}"
    )
    return diagnosis


def _mark_recovery(record: dict, reason: str) -> dict:
    updated = dict(record)
    updated["recovery_used"] = True
    updated["recovery_reason"] = reason
    updated["recovered_from"] = str(record.get("chatgpt_control_url") or "")
    updated["unready_checks"] = 0
    save_control_record(updated)
    return updated


def ensure_control_ready(browser, wake: str = ""):
    record = load_control_record()
    saved = str(record.get("chatgpt_control_url") or "")
    page = None
    page_url = ""
    messages: list[dict] = []
    generation_active = False
    composer_ready = False
    page_unavailable = False
    if is_usable_control_url(saved):
        page = find_control_page(browser, wake)
        record = load_control_record()
        saved = str(record.get("chatgpt_control_url") or "")
        if page is not None:
            page_url = page.url or ""
            messages = chatgpt_messages(page)
            if canonicalization_eligible(record, messages, page_url, wake):
                canonicalize_control_url(page_url)
                record = load_control_record()
                saved = str(record.get("chatgpt_control_url") or "")
                page_url = normalize_conversation_url(page_url) or page_url
            generation_active = generation_is_active(page)
            composer_ready = composer_is_ready(page)
            page_unavailable = page_shows_unavailable(page)

    checks = int(record.get("unready_checks") or 0)
    now = time.time()
    signed_out = False
    if page is not None and not messages and not composer_ready and not page_unavailable:
        try:
            signed_out = page_signed_out(page)
        except Exception:
            signed_out = False
    blank = blank_control_match(
        record,
        page_url,
        messages,
        composer_ready,
        generation_active,
        signed_out,
        page_unavailable,
    )
    record = apply_blank_observation(record, saved, blank, now)
    if is_usable_control_url(saved):
        save_control_record(record)
    blank_rebind = blank_rebind_ready(record, saved, now)
    record["_blank_rebind"] = blank_rebind
    action = next_control_action(
        record,
        messages,
        page_url,
        checks,
        wake=wake,
        generation_active=generation_active,
        composer_ready=composer_ready,
        now=now,
        page_unavailable=page_unavailable,
        blank_rebind=blank_rebind,
    )
    _log_control_diag(
        record,
        messages,
        page_url,
        action,
        wake=wake,
        generation_active=generation_active,
        composer_ready=composer_ready,
        now=now,
        page_unavailable=page_unavailable,
    )

    if action != "ready" and should_reprovision_rebind(record, saved, action):
        if rebind_reprovision_started(record, saved):
            log("CONTROL: rebind=reprovision_resume")
        else:
            log("CONTROL: rebind=reprovision_legacy")
        page = reprovision_control_rebind(browser, saved)
        return page, False

    if action != "ready" and reprovision_failed_closed(record, saved):
        log("CONTROL: rebind=reprovision_closed")
        return find_reprovision_page(browser) or page, False

    if action != "ready" and should_finalize_rebind(record, saved, action):
        if rebind_finalize_continue(record, saved):
            log("CONTROL: rebind=finalize_resume")
        else:
            log("CONTROL: rebind=finalize_legacy")
        page = finalize_control_rebind(browser, saved)
        return page, False

    if action != "ready" and should_replace_rebind(record, saved, action):
        if rebind_replacement_started(record, saved):
            log("CONTROL: rebind=replacement_resume")
        else:
            log("CONTROL: rebind=replacement_legacy")
        page = replace_control_rebind(browser, saved)
        return page, False

    if action == "rebind":
        log("CONTROL: rebind hard-unavailable")
        page = begin_control_rebind(browser, saved)
        return page, False

    if should_resume_rebind(record, saved, action):
        log("CONTROL: rebind=resume_legacy")
        page = resume_control_rebind(browser, saved)
        return page, False

    if action == "ready":
        if checks:
            record["unready_checks"] = 0
            save_control_record(record)
        log("CONTROL: чат готов, wake можно отправлять.")
        return page, True

    if action == "recover":
        if record.get("recovery_used"):
            log("CONTROL: recovery уже использовано, новый чат не создаю.")
            return page, False
        reason = diagnose_control(record, messages, page_url)
        _mark_recovery(record, reason)
        log(f"CONTROL: одноразовое восстановление, причина={reason}")
        page = provision_control_chat(browser)
        updated = load_control_record()
        updated["recovery_used"] = True
        updated["recovery_reason"] = reason
        updated["recovered_from"] = saved
        updated["unready_checks"] = 0
        save_control_record(updated)
        messages = chatgpt_messages(page)
        if control_is_ready(diagnose_control(updated, messages, page.url or "")):
            log("CONTROL: чат готов сразу после восстановления, wake можно отправлять.")
            return page, True
        return page, False

    if action == "send":
        if page is None:
            page = provision_control_chat(browser)
            return page, False
        log("CONTROL: bootstrap отсутствует, отправляю один раз.")
        submitted = send_to_chatgpt(page, CONTROL_BOOTSTRAP)
        if submitted is False:
            log("CONTROL: submit=unconfirmed")
            return page, False
        url = saved
        if not is_usable_control_url(url):
            url = str(page.url or "").split("?", 1)[0].split("#", 1)[0]
        if is_usable_control_url(url):
            save_control_url(url, bootstrap_sent=True)
        return page, False

    record["unready_checks"] = checks + 1
    save_control_record(record)
    log("CONTROL: bootstrap не повторяю и новый чат не создаю.")
    return page, False


# -------------------------
# Arena handling
# -------------------------

def dismiss_arena_completion(page) -> bool:
    selectors = [
        'button:has-text("Продолжить работу")',
        'button:has-text("Continue working")',
        'button:has-text("Continue")',
    ]

    for selector in selectors:
        loc = page.locator(selector)
        try:
            count = loc.count()
        except Exception:
            continue

        for i in range(count):
            btn = loc.nth(i)
            try:
                if btn.is_visible():
                    btn.click(timeout=5000)
                    page.wait_for_timeout(500)
                    log("ARENA: итоговое табло закрыто через 'Продолжить работу'.")
                    return True
            except Exception:
                continue

    return False


def arena_editor(page):
    candidates = [
        'div.tiptap.ProseMirror[contenteditable="true"][aria-disabled="false"]',
        'div[contenteditable="true"][aria-disabled="false"]',
        'div.tiptap.ProseMirror[contenteditable="true"]',
        '[contenteditable="true"][role="textbox"]',
        'textarea[placeholder="Ask anything…"]',
        'textarea[placeholder="Ask anything..."]',
    ]

    for selector in candidates:
        loc = page.locator(selector)
        try:
            count = loc.count()
        except Exception:
            continue

        for i in range(count):
            el = loc.nth(i)
            try:
                if el.is_visible():
                    return el
            except Exception:
                continue

    return None


def arena_user_texts(page) -> list[str]:
    try:
        return page.locator("[data-message-author-role='user']").evaluate_all(
            "nodes => nodes.map(n => (n.innerText || '').trim())"
        )
    except Exception:
        return []


def editor_text(editor) -> str:
    try:
        return editor.evaluate("""el => (el.innerText || el.value || '').trim()""")
    except Exception:
        return ""


def arena_wake_exists(page, wake: str) -> bool:
    if any(text == wake for text in arena_user_texts(page)[-40:]):
        return True

    editor = arena_editor(page)
    composer = editor_text(editor) if editor is not None else ""

    try:
        body = page.locator("body").inner_text(timeout=5000)
    except Exception:
        return False

    lines = [line.strip() for line in body.splitlines() if line.strip() == wake]
    if composer == wake:
        return len(lines) > 1
    return len(lines) >= 1


def send_to_arena(page, wake: str) -> None:
    dismiss_arena_completion(page)

    editor = arena_editor(page)
    if editor is None:
        raise RuntimeError("ARENA_INPUT_UNAVAILABLE")

    editor.click()
    inserted = False

    try:
        editor.fill(wake)
        inserted = editor_text(editor) == wake
    except Exception:
        inserted = False

    if not inserted:
        try:
            editor.press("Control+A")
            editor.press("Backspace")
            page.keyboard.insert_text(wake)
            inserted = editor_text(editor) == wake
        except Exception:
            inserted = False

    if not inserted:
        raise RuntimeError("ARENA_INPUT_UNAVAILABLE")

    editor.press("Enter", timeout=10000)
    page.wait_for_timeout(800)

    if not arena_wake_exists(page, wake) and editor_text(editor) == wake:
        raise RuntimeError("ARENA_INPUT_UNAVAILABLE")


# -------------------------
# Turn processing
# -------------------------

def wake_attempt_count(inflight: dict) -> int:
    if "send_attempts" in inflight:
        return int(inflight.get("send_attempts") or 0)
    if inflight.get("submitted"):
        return 1
    return 0


def wake_send_allowed(inflight: dict, now: float | None = None) -> bool:
    now = time.time() if now is None else now
    attempts = wake_attempt_count(inflight)

    if attempts >= MAX_WAKE_ATTEMPTS:
        return False

    retry_after = float(inflight.get("retry_after", 0) or 0)
    if attempts == 0:
        return now >= retry_after
    if retry_after:
        return now >= retry_after

    submitted_at = float(inflight.get("submitted_at") or inflight.get("created_at") or now)
    return now >= submitted_at + WAKE_CONFIRM_SECONDS


def mark_unobserved_wake(state: dict, inflight: dict, turn_id: int, target: str) -> None:
    attempts = wake_attempt_count(inflight) + 1
    inflight["send_attempts"] = attempts
    inflight["submitted"] = True
    inflight["submitted_at"] = inflight.get("submitted_at") or time.time()
    inflight["last_error"] = f"{target} wake not observed"

    if attempts < MAX_WAKE_ATTEMPTS:
        inflight["retry_after"] = time.time() + WAKE_CONFIRM_SECONDS
        log(
            f"{target}: wake turn_id={turn_id} не подтверждён. "
            f"Попытка {attempts}/{MAX_WAKE_ATTEMPTS}. "
            f"Повтор того же turn_id через {WAKE_CONFIRM_SECONDS} сек."
        )
    else:
        inflight["retry_after"] = 0
        log(
            f"{target}: wake turn_id={turn_id} не подтверждён после {attempts} попыток. "
            "Больше не отправляю; жду историю или новый turn_id."
        )

    state["inflight"] = inflight
    save_state(state)


def consume_turn(state: dict, turn_id: int, reason: str) -> None:
    state["last_turn_id"] = max(int(state.get("last_turn_id", 0)), turn_id)
    state["inflight"] = None
    save_state(state)
    log(f"TURN {turn_id} обработан: {reason}")


def create_inflight(state: dict, signal: dict) -> dict:
    inflight = {
        "turn_id": signal["turn_id"],
        "target": signal["target"],
        "requires_codex": bool(signal.get("requires_codex", False)),
        "wake": wake_text(signal["turn_id"]),
        "submitted": False,
        "send_attempts": 0,
        "created_at": time.time(),
        "retry_after": 0,
        "last_error": None,
    }
    state["inflight"] = inflight
    save_state(state)
    return inflight


def process_gpt(browser, state: dict, inflight: dict) -> None:
    turn_id = int(inflight["turn_id"])
    wake = str(inflight["wake"])

    if (
        inflight.get("last_error") == "Control chat bootstrap pending"
        and time.time() < float(inflight.get("retry_after", 0) or 0)
    ):
        return

    page, ready = ensure_control_ready(browser, wake)
    if not ready:
        inflight["retry_after"] = time.time() + CONTROL_RETRY_SECONDS
        inflight["last_error"] = "Control chat bootstrap pending"
        state["inflight"] = inflight
        save_state(state)
        return

    if chatgpt_response_complete(page, wake):
        consume_turn(state, turn_id, "GPT control chat уже ответил")
        return

    if chatgpt_wake_exists(page, wake) or inflight.get("wake_seen"):
        if not inflight.get("wake_seen"):
            inflight["wake_seen"] = True
            inflight["submitted"] = True
            inflight["submitted_at"] = inflight.get("submitted_at") or time.time()
            inflight["last_error"] = None
            inflight["retry_after"] = 0
            state["inflight"] = inflight
            save_state(state)
            log(f"GPT: wake подтверждён в control chat ({wake})")
        return

    if not wake_send_allowed(inflight):
        return

    send_to_chatgpt(page, wake)

    try:
        page.wait_for_timeout(800)
    except Exception:
        pass

    if chatgpt_wake_exists(page, wake):
        inflight["wake_seen"] = True
        inflight["submitted"] = True
        inflight["submitted_at"] = time.time()
        inflight["send_attempts"] = wake_attempt_count(inflight) + 1
        inflight["last_error"] = None
        inflight["retry_after"] = 0
        state["inflight"] = inflight
        save_state(state)
        log(f"GPT: команда отправлена в control chat ({wake})")
        return

    log(f"GPT: команда отправлена, но wake turn_id={turn_id} в истории control chat не виден.")
    mark_unobserved_wake(state, inflight, turn_id, "GPT")


def process_arena(browser, state: dict, inflight: dict) -> None:
    turn_id = int(inflight["turn_id"])
    wake = str(inflight["wake"])

    page = find_arena_page(browser)
    dismiss_arena_completion(page)

    if arena_wake_exists(page, wake):
        consume_turn(state, turn_id, "Arena уже получила команду")
        return

    if not wake_send_allowed(inflight):
        return

    try:
        send_to_arena(page, wake)
    except RuntimeError as exc:
        if str(exc) != "ARENA_INPUT_UNAVAILABLE":
            raise

        inflight["retry_after"] = time.time() + ARENA_RETRY_SECONDS
        inflight["last_error"] = "Arena input unavailable"
        state["inflight"] = inflight
        save_state(state)

        log(
            f"ARENA: поле ввода недоступно для turn_id={turn_id}. "
            f"Повтор через {ARENA_RETRY_SECONDS} сек., без дублирования."
        )
        return

    if not arena_wake_exists(page, wake):
        log(f"ARENA: Enter для turn_id={turn_id} не виден в истории.")
        mark_unobserved_wake(state, inflight, turn_id, "ARENA")
        return

    inflight["submitted"] = True
    inflight["submitted_at"] = time.time()
    inflight["last_error"] = None
    state["inflight"] = inflight
    save_state(state)

    log(f"ARENA: команда отправлена ({wake})")
    consume_turn(state, turn_id, "команда отправлена в Arena")


def current_signal_cancels_inflight(signal: dict, inflight: dict) -> bool:
    if not inflight:
        return False

    if int(signal.get("turn_id", 0)) != int(inflight.get("turn_id", -1)):
        return False

    status = str(signal.get("status", "")).lower()
    target = str(signal.get("target", "")).upper()

    return target == "NONE" or status in TERMINAL_STATUSES


def newer_signal_supersedes_inflight(signal: dict, inflight: dict) -> bool:
    if not inflight:
        return False
    return int(signal.get("turn_id", 0)) > int(inflight.get("turn_id", 0))


def handle_signal_without_action(state: dict, signal: dict) -> bool:
    turn_id = int(signal["turn_id"])
    target = str(signal["target"]).upper()
    status = str(signal["status"]).lower()

    if turn_id <= int(state.get("last_turn_id", 0)):
        return True

    if status in HOLD_STATUSES and target != "NONE":
        log(f"TURN {turn_id}: status={status}, отправка отложена без consume.")
        return True

    if target == "NONE" or status in TERMINAL_STATUSES:
        consume_turn(
            state,
            turn_id,
            f"signal status={status or '-'} target={target or '-'}",
        )
        return True

    return False


# -------------------------
# Main watch loop
# -------------------------

def watch() -> None:
    acquire_single_instance()
    start_service_chrome()

    state = load_state()

    log(f"AI Dispatcher {VERSION} запущен")
    log(f"Последний обработанный turn_id: {state['last_turn_id']}")
    if state.get("inflight"):
        log(f"Незавершённый turn_id: {state['inflight'].get('turn_id')}")
    control_url = load_control_url()
    log(
        "CONTROL: "
        + (
            f"машинный чат закреплён: {control_url}"
            if control_url
            else "машинный чат будет создан автоматически при первом target=GPT"
        )
    )
    log(f"Проверка GitHub каждые {CHECK_INTERVAL} сек.")
    log(f"Лог: {LOG_PATH}")

    with sync_playwright() as p:
        browser = None

        while True:
            try:
                if browser is None:
                    start_service_chrome()
                    browser = p.chromium.connect_over_cdp(CDP)

                signal = fetch_signal()
                inflight = state.get("inflight")

                if inflight and newer_signal_supersedes_inflight(signal, inflight):
                    old_turn = int(inflight["turn_id"])
                    new_turn = int(signal["turn_id"])
                    consume_turn(
                        state,
                        old_turn,
                        f"подтверждён более новым GitHub turn_id={new_turn}",
                    )
                    inflight = None

                if (
                    inflight
                    and int(signal.get("turn_id", 0)) == int(inflight.get("turn_id", -1))
                    and str(signal.get("status", "")).lower() in HOLD_STATUSES
                    and str(signal.get("target", "")).upper() != "NONE"
                ):
                    log(
                        f"TURN {int(inflight['turn_id'])}: "
                        f"status={signal['status']}, inflight не отправляю."
                    )
                    time.sleep(CHECK_INTERVAL)
                    continue

                if inflight and current_signal_cancels_inflight(signal, inflight):
                    consume_turn(
                        state,
                        int(inflight["turn_id"]),
                        f"handoff закрыт: status={signal['status']} target={signal['target']}",
                    )
                    inflight = None

                if not inflight:
                    if handle_signal_without_action(state, signal):
                        time.sleep(CHECK_INTERVAL)
                        continue

                    turn_id = int(signal["turn_id"])
                    if turn_id > int(state["last_turn_id"]):
                        status = signal["status"]
                        target = signal["target"]

                        if status not in READY_STATUSES:
                            log(
                                f"TURN {turn_id}: неизвестный status={status!r}; "
                                "действие не выполняю."
                            )
                            time.sleep(CHECK_INTERVAL)
                            continue

                        if target not in {"GPT", "ARENA"}:
                            log(
                                f"TURN {turn_id}: неизвестный target={target!r}; "
                                "действие не выполняю."
                            )
                            time.sleep(CHECK_INTERVAL)
                            continue

                        inflight = create_inflight(state, signal)
                        log(f"NEW TURN {turn_id} -> {target}")

                if inflight:
                    target = str(inflight.get("target", "")).upper()

                    if target == "GPT":
                        process_gpt(browser, state, inflight)
                    elif target == "ARENA":
                        process_arena(browser, state, inflight)
                    else:
                        consume_turn(
                            state,
                            int(inflight["turn_id"]),
                            f"неизвестный inflight target={target}",
                        )

            except KeyboardInterrupt:
                log("Остановка по Ctrl+C.")
                raise

            except GitHubNetworkError:
                log("GITHUB: endpoint=unavailable error=GitHubNetworkError. CDP не перезапускаю.")

            except GitHubSignalError:
                log("GITHUB: endpoint=signal error=GitHubSignalError. CDP не перезапускаю.")

            except PlaywrightTimeoutError as exc:
                log(
                    f"UI: Playwright timeout: {exc}. "
                    "Это не ошибка GitHub; CDP не перезапускаю."
                )

            except Exception as exc:
                log(f"ERROR: {type(exc).__name__}: {exc}")
                browser = None

                try:
                    log("CHROME: восстанавливаю CDP после не-классифицированной ошибки.")
                    start_service_chrome(force=not cdp_http_ready())
                    browser = p.chromium.connect_over_cdp(CDP)
                    log("CHROME: соединение восстановлено.")
                except Exception as chrome_exc:
                    log(
                        f"CHROME: восстановление не удалось: "
                        f"{type(chrome_exc).__name__}: {chrome_exc}"
                    )

            time.sleep(CHECK_INTERVAL)


# -------------------------
# Manual diagnostics
# -------------------------

def manual_wake(target: str) -> None:
    acquire_single_instance()
    start_service_chrome()

    target = target.upper()
    if target not in {"GPT", "ARENA"}:
        raise SystemExit("Использование: dispatcher.py GPT-ПУСК | ARENA-ПУСК")

    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(CDP)
        wake = "Проверь GitHub"

        if target == "GPT":
            page, ready = ensure_control_ready(browser)
            if not ready:
                raise SystemExit("CONTROL chat ещё инициализируется; повтори позже.")
            send_to_chatgpt(page, wake)
            log("OK: GPT-ПУСК -> ChatGPT control chat")
        else:
            page = find_arena_page(browser)
            send_to_arena(page, wake)
            log("OK: ARENA-ПУСК -> Arena")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        arg = sys.argv[1].strip().upper()
        if arg == "GPT-ПУСК":
            manual_wake("GPT")
        elif arg == "ARENA-ПУСК":
            manual_wake("ARENA")
        else:
            raise SystemExit(
                "Неизвестный аргумент. Используй GPT-ПУСК или ARENA-ПУСК, "
                "либо запусти без аргументов."
            )
    else:
        watch()
