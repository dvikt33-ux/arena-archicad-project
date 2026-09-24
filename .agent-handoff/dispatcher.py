from __future__ import annotations

import ctypes
import json
import logging
import os
import socket
import subprocess
import sys
import time
import urllib.request
from logging.handlers import RotatingFileHandler
from pathlib import Path

from playwright.sync_api import sync_playwright

# =========================
# AI Dispatcher 2.2.3
# =========================

VERSION = "2.2.3"

HOME = Path.home()
STATE_PATH = HOME / ".ai-dispatcher-state.json"
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

CHATGPT_URL = "https://chatgpt.com/c/6ab457e5-237c-83eb-a463-df52d23fd58f"
ARENA_URL = "https://arena.ai/agent/01a09014-9139-71e7-b51b-5b3f8a49d904"

CHECK_INTERVAL = 5
ARENA_RETRY_SECONDS = 60
PAGE_TIMEOUT = 15000
CHROME_START_TIMEOUT = 25

TERMINAL_STATUSES = {"cancelled", "canceled", "done"}
HOLD_STATUSES = {"blocked", "paused", "idle"}
READY_STATUSES = {"ready", "pending", "queued"}
# Unobserved Enter is not success. Retry the same turn_id wake, slowly.
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
    return {
        "last_turn_id": 0,
        "inflight": None,
    }


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
            headers={"User-Agent": "AI-Dispatcher-2.2.3"},
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

def is_github_network_error(exc: BaseException) -> bool:
    name = type(exc).__name__
    if name in {
        "URLError",
        "TimeoutError",
        "RemoteDisconnected",
        "SSLError",
        "ConnectionError",
        "ConnectionResetError",
    }:
        return True
    text = str(exc)
    return any(
        token in text
        for token in ("RemoteDisconnected", "UNEXPECTED_EOF", "handshake", "timed out")
    )


def fetch_signal() -> dict:
    last_exc: BaseException | None = None
    for attempt in range(3):
        try:
            return _fetch_signal_once()
        except Exception as exc:
            if not is_github_network_error(exc) or attempt == 2:
                raise
            last_exc = exc
            delay = 1 + attempt * 2
            log(f"GITHUB: сеть недоступна ({type(exc).__name__}), повтор через {delay} сек.")
            time.sleep(delay)
    raise last_exc if last_exc else RuntimeError("fetch_signal failed")


def _fetch_signal_once() -> dict:
    url = f"{SIGNAL_URL}?ts={time.time_ns()}"
    req = urllib.request.Request(
        url,
        headers={
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
            "User-Agent": "AI-Dispatcher-2.2.3",
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


def find_chatgpt_page(browser):
    exact = []
    fallback = []

    for page in all_pages(browser):
        url = page.url or ""
        if url_matches(url, CHATGPT_URL):
            exact.append(page)
        elif "chatgpt.com" in url:
            fallback.append(page)

    page = choose_page(exact)
    if page is not None:
        return page

    page = choose_page(fallback)
    if page is not None:
        page.goto(CHATGPT_URL, wait_until="domcontentloaded", timeout=PAGE_TIMEOUT)
        return page

    context = browser.contexts[0]
    page = context.new_page()
    page.goto(CHATGPT_URL, wait_until="domcontentloaded", timeout=PAGE_TIMEOUT)
    return page


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
        context = browser.contexts[0]
        page = context.new_page()
    if not url_matches(page.url or "", ARENA_URL):
        page.goto(ARENA_URL, wait_until="domcontentloaded", timeout=PAGE_TIMEOUT)
    return page


# -------------------------
# ChatGPT handling
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


def chatgpt_wake_exists(page, wake: str) -> bool:
    messages = chatgpt_messages(page)
    return any(
        item.get("role") == "user" and item.get("text", "").strip() == wake
        for item in messages[-40:]
    )


def chatgpt_response_complete(page, wake: str) -> bool:
    messages = chatgpt_messages(page)

    wake_index = None
    for idx in range(len(messages) - 1, -1, -1):
        item = messages[idx]
        if item.get("role") == "user" and item.get("text", "").strip() == wake:
            wake_index = idx
            break

    if wake_index is None:
        return False

    has_assistant_after = any(
        item.get("role") == "assistant" and item.get("text", "").strip()
        for item in messages[wake_index + 1 :]
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


def send_to_chatgpt(page, wake: str) -> None:
    box = page.locator("#prompt-textarea")

    try:
        box.wait_for(state="visible", timeout=PAGE_TIMEOUT)
    except Exception:
        fallback = page.locator(
            '[contenteditable="true"][data-virtualkeyboard="true"], '
            '[contenteditable="true"][role="textbox"]'
        )
        fallback.wait_for(state="visible", timeout=PAGE_TIMEOUT)
        box = fallback.first

    try:
        box.evaluate("(el) => el.focus()")
    except Exception:
        pass

    box.fill(wake)
    box.press("Enter")


def refresh_desktop_chatgpt() -> None:
    try:
        import pyautogui
        import pygetwindow as gw
    except Exception as exc:
        log(f"DESKTOP: refresh пропущен, модуль недоступен: {exc}")
        return

    try:
        windows = gw.getWindowsWithTitle("ChatGPT")
        if not windows:
            log("DESKTOP: окно ChatGPT не найдено, refresh пропущен.")
            return

        win = windows[0]

        try:
            if win.isMinimized:
                win.restore()
                time.sleep(0.5)
        except Exception:
            pass

        try:
            win.activate()
        except Exception:
            pass

        time.sleep(0.5)
        pyautogui.hotkey("ctrl", "r")
        log("DESKTOP: ChatGPT обновлён и активирован.")
    except Exception as exc:
        log(f"DESKTOP: не удалось обновить ChatGPT: {exc}")


# -------------------------
# Arena handling
# -------------------------

def arena_user_texts(page) -> list[str]:
    try:
        return page.locator("[data-message-author-role='user']").evaluate_all(
            "nodes => nodes.map(n => (n.innerText || '').trim())"
        )
    except Exception:
        return []


def arena_wake_exists(page, wake: str) -> bool:
    if any(text == wake for text in arena_user_texts(page)[-40:]):
        return True
    editor = arena_editor(page)
    composer = editor_text(editor) if editor is not None else ""
    try:
        body = page.locator("body").inner_text(timeout=5000)
    except Exception:
        return False
    # Exact line, not a substring: a quoted wake inside a longer message must not match.
    # Skip the line when it is only the still-unsent composer text.
    lines = [line.strip() for line in body.splitlines() if line.strip() == wake]
    if composer == wake:
        return len(lines) > 1
    return len(lines) >= 1


def editor_text(editor) -> str:
    try:
        return editor.evaluate(
            """el => (el.innerText || el.value || '').trim()"""
        )
    except Exception:
        return ""


def send_to_arena(page, wake: str) -> None:
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

    editor.press("Enter")
    page.wait_for_timeout(800)
    if not arena_wake_exists(page, wake) and editor_text(editor) == wake:
        raise RuntimeError("ARENA_INPUT_UNAVAILABLE")


# -------------------------
# Turn processing
# -------------------------

def wake_attempt_count(inflight: dict) -> int:
    if "send_attempts" in inflight:
        return int(inflight.get("send_attempts") or 0)
    # 2.2.2 persisted submitted=True and then never retried.
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
    page = find_chatgpt_page(browser)

    if chatgpt_response_complete(page, wake):
        consume_turn(state, turn_id, "GPT уже ответил")
        refresh_desktop_chatgpt()
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
        log(f"GPT: команда уже есть в чате, повтор не отправляю ({wake})")
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
        log(f"GPT: команда отправлена ({wake})")
        return

    log(f"GPT: команда отправлена, но wake turn_id={turn_id} в истории не виден.")
    mark_unobserved_wake(state, inflight, turn_id, "GPT")


def process_arena(browser, state: dict, inflight: dict) -> None:
    turn_id = int(inflight["turn_id"])
    wake = str(inflight["wake"])

    page = find_arena_page(browser)

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

                # Ключевой fail-safe: GitHub — источник истины. Если там уже появился
                # более новый turn_id, предыдущий inflight точно был обработан стороной,
                # которая смогла записать следующий handoff. Не зависаем на старом UI.
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
                        (
                            f"handoff закрыт: "
                            f"status={signal['status']} target={signal['target']}"
                        ),
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
            except Exception as exc:
                log(f"ERROR: {type(exc).__name__}: {exc}")
                if is_github_network_error(exc):
                    log("GITHUB: временная ошибка сети, CDP не перезапускаю.")
                    time.sleep(CHECK_INTERVAL)
                    continue
                browser = None

                try:
                    log("CHROME: восстанавливаю CDP, не только если порт закрыт.")
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
# Manual diagnostic wake
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
            page = find_chatgpt_page(browser)
            send_to_chatgpt(page, wake)
            log("OK: GPT-ПУСК -> ChatGPT")
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
                "Неизвестный аргумент. "
                "Используй GPT-ПУСК или ARENA-ПУСК, либо запусти без аргументов."
            )
    else:
        watch()
