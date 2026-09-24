from __future__ import annotations

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
# AI Dispatcher 2.2.6
# =========================

VERSION = "2.2.6"

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

CHATGPT_HOME = "https://chatgpt.com/"
ARENA_URL = "https://arena.ai/agent/01a09014-9139-71e7-b51b-5b3f8a49d904"

CONTROL_BOOTSTRAP = (
    "Служебный чат 01 — CONTROL & BRIDGE. "
    "Этот чат используется только локальным AI Dispatcher как машинный транспортный канал. "
    "Когда приходит сообщение вида «Проверь GitHub. turn_id=N», открой через подключённый GitHub "
    "репозиторий dvikt33-ux/arena-archicad-project, ветку agent-handoff, файл "
    ".agent-handoff/signal.json; проверь, что turn_id совпадает, выполни только инструкцию из поля "
    "message и при необходимости запиши следующий handoff обратно в этот signal.json. "
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


def control_bootstrap_decision(record: dict | None, messages: list[dict]) -> str:
    """ready: send the pending wake. wait: do not resend. send: one bootstrap."""
    if assistant_has_control_ready(messages):
        return "ready"
    if bootstrap_was_sent(record) or user_has_bootstrap_marker(messages):
        return "wait"
    return "send"


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
    tmp = CONTROL_PATH.with_suffix(".tmp")
    tmp.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    os.replace(tmp, CONTROL_PATH)


def save_control_url(url: str, bootstrap_sent: bool = True) -> None:
    save_control_record(
        {
            "chatgpt_control_url": url,
            "bootstrap_sent": bootstrap_sent,
            "bootstrap_sent_at": time.time() if bootstrap_sent else None,
        }
    )
    log(f"CONTROL: закреплён отдельный машинный ChatGPT-чат: {url}")


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


def fetch_signal() -> dict:
    last_exc: BaseException | None = None

    for attempt in range(3):
        try:
            return _fetch_signal_once()
        except Exception as exc:
            if not _is_network_exception(exc):
                raise
            last_exc = exc
            if attempt < 2:
                delay = 1 + attempt * 2
                log(
                    f"GITHUB: сеть недоступна ({type(exc).__name__}), "
                    f"повтор через {delay} сек."
                )
                time.sleep(delay)

    raise GitHubNetworkError(str(last_exc or "fetch_signal failed")) from last_exc


def _fetch_signal_once() -> dict:
    url = f"{SIGNAL_URL}?ts={time.time_ns()}"
    req = urllib.request.Request(
        url,
        headers={
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
            "User-Agent": f"AI-Dispatcher-{VERSION}",
        },
    )

    with urllib.request.urlopen(req, timeout=15) as resp:
        raw = resp.read().decode("utf-8")

    data = json.loads(raw)

    return {
        "protocol": int(data.get("protocol", 0) or 0),
        "turn_id": int(data.get("turn_id", 0) or 0),
        "target": str(data.get("target", "") or "").upper(),
        "source": str(data.get("source", "") or "").upper(),
        "status": str(data.get("status", "") or "").lower(),
        "message": str(data.get("message", "") or ""),
    }


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


def find_control_page(browser):
    control_url = load_control_url()

    if control_url:
        exact = [
            page
            for page in chatgpt_pages(browser)
            if url_matches(page.url or "", control_url)
        ]
        page = choose_page(exact)
        if page is not None:
            return page

        pages = chatgpt_pages(browser)
        page = choose_page(pages)
        if page is None:
            page = browser.contexts[0].new_page()
        page.goto(control_url, wait_until="domcontentloaded", timeout=PAGE_TIMEOUT)
        return page

    return provision_control_chat(browser)


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

def chatgpt_messages(page) -> list[dict]:
    try:
        return page.locator("[data-message-author-role]").evaluate_all(
            """nodes => nodes.map(n => ({
                role: n.getAttribute('data-message-author-role') || '',
                text: (n.innerText || '').trim()
            }))"""
        )
    except Exception:
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


def send_to_chatgpt(page, text: str) -> None:
    box = chatgpt_prompt(page)
    try:
        box.evaluate("(el) => el.focus()")
    except Exception:
        pass
    box.fill(text)
    box.press("Enter")


def wait_for_conversation_url(page, timeout_seconds: int = 30) -> str:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        url = page.url or ""
        if is_chatgpt_conversation_url(url):
            return url.split("?", 1)[0].split("#", 1)[0]
        time.sleep(0.25)
    return ""


def provision_control_chat(browser):
    context = browser.contexts[0]
    page = context.new_page()
    page.goto(CHATGPT_HOME, wait_until="domcontentloaded", timeout=PAGE_TIMEOUT)

    log("CONTROL: создаю отдельный машинный ChatGPT-чат 01 — CONTROL & BRIDGE.")
    send_to_chatgpt(page, CONTROL_BOOTSTRAP)

    control_url = wait_for_conversation_url(page, 30)
    if not control_url:
        raise RuntimeError("CONTROL_CHAT_URL_NOT_CREATED")

    save_control_url(control_url)
    return page


def ensure_control_ready(browser):
    page = find_control_page(browser)
    record = load_control_record()
    messages = chatgpt_messages(page)
    decision = control_bootstrap_decision(record, messages)

    if decision == "ready":
        log("CONTROL: CONTROL READY найден, продолжаю без ожидания bootstrap.")
        return page, True

    if decision == "wait":
        log("CONTROL: bootstrap уже отправлен, CONTROL READY ещё нет. Повтор не отправляю.")
        return page, False

    log("CONTROL: bootstrap отсутствует, отправляю один раз.")
    send_to_chatgpt(page, CONTROL_BOOTSTRAP)
    url = str(record.get("chatgpt_control_url") or "")
    if not is_chatgpt_conversation_url(url):
        url = str(page.url or "").split("?", 1)[0].split("#", 1)[0]
    if is_chatgpt_conversation_url(url):
        save_control_url(url, bootstrap_sent=True)
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

    page, ready = ensure_control_ready(browser)
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

            except GitHubNetworkError as exc:
                log(
                    f"GITHUB: временная ошибка сети после повторов: {exc}. "
                    "CDP не перезапускаю."
                )

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
