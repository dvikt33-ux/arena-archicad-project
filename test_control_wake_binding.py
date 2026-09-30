"""Focused regression tests for CONTROL wake acknowledgement binding."""
from __future__ import annotations

import importlib.util
import tempfile
from pathlib import Path

CORE = Path(__file__).with_name("dispatcher.py")
spec = importlib.util.spec_from_file_location("dispatcher_under_test", CORE)
dispatcher = importlib.util.module_from_spec(spec)
assert spec.loader is not None
with tempfile.TemporaryDirectory() as _tmp:
    _original_home = Path.home
    Path.home = classmethod(lambda _cls: Path(_tmp))
    try:
        spec.loader.exec_module(dispatcher)
    finally:
        for _handler in list(dispatcher.logger.handlers):
            _handler.close()
            dispatcher.logger.removeHandler(_handler)
        Path.home = _original_home


class Page:
    def __init__(self, url: str, wake: str = ""):
        self.url = url
        self.messages = [wake] if wake else []

    def wait_for_timeout(self, _ms: int) -> None:
        return None


def run_case(page: Page, inflight: dict) -> tuple[dict, int]:
    state = {"inflight": inflight}
    sends = []
    dispatcher.ensure_control_ready = lambda _browser, _wake: (page, True)
    dispatcher.chatgpt_response_complete = lambda _page, _wake: False
    dispatcher.chatgpt_wake_exists = lambda current, wake: wake in current.messages
    dispatcher.send_to_chatgpt = lambda current, wake: (sends.append(wake), current.messages.append(wake))
    dispatcher.save_state = lambda _state: None
    dispatcher.process_gpt(None, state, inflight)
    return state, len(sends)


def main() -> None:
    old = "https://chatgpt.com/c/old-control"
    new = "https://chatgpt.com/c/new-control"
    wake = dispatcher.wake_text(57)

    inflight = {"turn_id": 57, "target": "GPT", "wake": wake, "wake_seen": True,
                "wake_seen_control_identity": "old-control", "submitted": True,
                "send_attempts": 1, "retry_after": 0}
    state, sends = run_case(Page(new), inflight)
    assert sends == 1
    assert state["inflight"]["turn_id"] == 57
    assert state["inflight"]["wake_seen_control_identity"] == "new-control"
    _, sends = run_case(Page(new, wake), inflight)
    assert sends == 0

    legacy = {"turn_id": 57, "target": "GPT", "wake": wake, "wake_seen": True,
              "submitted": True, "send_attempts": 1, "retry_after": 0}
    state, sends = run_case(Page(new, wake), legacy)
    assert sends == 0
    assert state["inflight"]["wake_seen_control_identity"] == "new-control"

    assert state["inflight"]["turn_id"] == 57
    assert state["inflight"]["target"] == "GPT"
    print("test_control_wake_binding: OK")


if __name__ == "__main__":
    main()
