from __future__ import annotations

import importlib.util
import traceback
from datetime import datetime
from pathlib import Path

VERSION = "2.2.15"
HOME = Path.home()
CORE_PATH = HOME / "dispatcher_core.py"
BOOTSTRAP_LOG = HOME / "ai-dispatcher-bootstrap.log"


def _write_bootstrap_error(exc: BaseException) -> None:
    try:
        with BOOTSTRAP_LOG.open("a", encoding="utf-8") as fh:
            fh.write(
                f"\n[{datetime.now().isoformat(timespec='seconds')}] "
                f"{type(exc).__name__}: {exc}\n"
            )
            fh.write(traceback.format_exc())
            fh.write("\n")
    except Exception:
        pass


try:
    spec = importlib.util.spec_from_file_location("dispatcher_core", CORE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load dispatcher core from {CORE_PATH}")

    core = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(core)

    core_version = str(getattr(core, "VERSION", ""))
    if core_version != VERSION:
        raise RuntimeError(
            f"Dispatcher runtime/core version mismatch: runtime={VERSION}, core={core_version or 'unknown'}"
        )
except Exception as exc:
    _write_bootstrap_error(exc)
    raise


QUESTION_TEXT = "Эта задача была выполнена успешно?"
CONTINUE_TEXT = "Продолжить работу"


def _first_visible(locator):
    try:
        count = locator.count()
    except Exception:
        return None
    for i in range(count):
        item = locator.nth(i)
        try:
            if item.is_visible():
                return item
        except Exception:
            continue
    return None


def dismiss_arena_completion_prompt(page) -> bool:
    """Dismiss only Arena's completion prompt by clicking 'Продолжить работу'.

    Never clicks 'Да' or 'Нет'. Returns True only if the continue action was
    clicked successfully.
    """
    if page is None:
        return False

    try:
        question = _first_visible(page.get_by_text(QUESTION_TEXT, exact=True))
        if question is None:
            return False

        continue_action = _first_visible(page.get_by_text(CONTINUE_TEXT, exact=True))
        if continue_action is None:
            core.log("ARENA: найдено итоговое табло, но 'Продолжить работу' не найдено.")
            return False

        continue_action.click(timeout=3000)
        page.wait_for_timeout(500)

        try:
            question.wait_for(state="hidden", timeout=4000)
        except Exception:
            pass

        still_visible = False
        try:
            still_visible = question.is_visible()
        except Exception:
            still_visible = False

        if still_visible:
            core.log("ARENA: 'Продолжить работу' нажато, но табло ещё видно.")
            return False

        core.log("ARENA: итоговое табло закрыто через 'Продолжить работу'.")
        return True
    except Exception as exc:
        core.log(f"ARENA: не удалось закрыть итоговое табло: {type(exc).__name__}: {exc}")
        return False


_original_find_arena_page = core.find_arena_page
_original_arena_editor = core.arena_editor
_original_send_to_arena = core.send_to_arena


def find_arena_page(browser):
    page = _original_find_arena_page(browser)
    dismiss_arena_completion_prompt(page)
    return page


def arena_editor(page):
    dismiss_arena_completion_prompt(page)
    return _original_arena_editor(page)


def send_to_arena(page, wake: str) -> None:
    dismiss_arena_completion_prompt(page)
    return _original_send_to_arena(page, wake)


core.find_arena_page = find_arena_page
core.arena_editor = arena_editor
core.send_to_arena = send_to_arena


def dismiss_prompt_once() -> int:
    core.start_service_chrome()
    with core.sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(core.CDP)
        page = _original_find_arena_page(browser)
        if dismiss_arena_completion_prompt(page):
            core.log("ARENA: одноразовое закрытие итогового табло выполнено.")
            return 0
        core.log("ARENA: одноразовое закрытие не потребовалось или табло не найдено.")
        return 0


def run() -> int:
    try:
        if len(core.sys.argv) > 1:
            arg = core.sys.argv[1].strip().upper()
            if arg == "GPT-ПУСК":
                core.manual_wake("GPT")
            elif arg == "ARENA-ПУСК":
                core.manual_wake("ARENA")
            elif arg == "DISMISS-ARENA-PROMPT":
                return dismiss_prompt_once()
            else:
                raise SystemExit(
                    "Неизвестный аргумент. Используй GPT-ПУСК, ARENA-ПУСК, "
                    "DISMISS-ARENA-PROMPT или запусти без аргументов."
                )
        else:
            core.watch()
        return 0
    except BaseException as exc:
        _write_bootstrap_error(exc)
        raise


if __name__ == "__main__":
    raise SystemExit(run())
