"""Rebind tests for an inaccessible control chat. No Playwright and no network."""
from __future__ import annotations

import ast
import json
import tempfile
from pathlib import Path

CORE = Path(__file__).with_name("dispatcher.py")

WANTED = {
    "is_chatgpt_conversation_url",
    "conversation_id",
    "conversation_identity",
    "same_conversation",
    "is_usable_control_url",
    "normalize_conversation_url",
    "url_matches",
    "assistant_has_control_ready",
    "user_has_bootstrap_marker",
    "bootstrap_was_sent",
    "_last_bootstrap_index",
    "assistant_after_bootstrap",
    "assistant_error_after_bootstrap",
    "hard_unavailable_text",
    "hard_control_unavailable",
    "diagnose_control",
    "control_is_ready",
    "recovery_allowed",
    "rebind_target",
    "rebind_bound",
    "rebind_completed",
    "rebind_cooldown_active",
    "rebind_allowed",
    "rebind_page_action",
    "positive_control_identity",
    "canonicalization_eligible",
    "submitted_bootstrap_idle_ready",
    "next_control_action",
    "pending_wake_action",
    "wake_attempt_count",
    "wake_send_allowed",
    "load_control_record",
    "save_control_record",
    "_read_control_file",
    "_write_rebind_state",
    "mark_rebind_started",
    "mark_rebind_bootstrap_sent",
    "mark_rebind_failed",
    "commit_rebind",
    "all_pages",
    "page_restore_mark",
    "find_rebind_page",
    "mark_rebind_page",
    "page_shows_unavailable",
    "stable_rebind_reason",
    "rebind_page_on_home",
    "wait_for_rebind_composer",
    "hydrate_rebind_page",
    "begin_control_rebind",
}


def load_helpers(control_path: Path):
    tree = ast.parse(CORE.read_text(encoding="utf-8"))
    keep = []
    for node in tree.body:
        if isinstance(node, ast.Assign):
            names = [t.id for t in node.targets if isinstance(t, ast.Name)]
            if names and names[0] in {
                "VERSION",
                "CHECK_INTERVAL",
                "CONTROL_READY_MARKER",
                "CONTROL_BOOTSTRAP_MARKER",
                "CONTROL_BOOTSTRAP",
                "CONTROL_ERROR_MARKERS",
                "CONTROL_UNAVAILABLE_MARKERS",
                "CONTROL_REBIND_COOLDOWN_SECONDS",
                "CONTROL_REBIND_URL_WAIT",
                "CONTROL_RESTORE_GOTO_TIMEOUT",
                "REBIND_PAGE_MARK",
                "CHATGPT_HOME",
                "CONTROL_REBIND_COMPOSER_WAIT",
                "REBIND_COMPOSER_POLL_SECONDS",
                "REBIND_FAILURE_REASONS",
                "MAX_WAKE_ATTEMPTS",
                "WAKE_CONFIRM_SECONDS",
            }:
                keep.append(node)
        elif isinstance(node, ast.FunctionDef) and node.name in WANTED:
            keep.append(node)
    ns = {
        "json": json,
        "os": __import__("os"),
        "time": __import__("time"),
        "log": lambda message: None,
        "CONTROL_PATH": control_path,
    }
    exec(compile(ast.Module(keep, []), str(CORE), "exec"), ns)
    return ns


class FakePage:
    def __init__(self, url: str):
        self.url = url
        self.gotos: list[str] = []
        self.window_name = ""

    def evaluate(self, script: str, arg=None):
        if arg is not None:
            self.window_name = arg
            return None
        if script == "window.name":
            return self.window_name
        return ""

    def goto(self, url: str, **_kwargs) -> None:
        self.gotos.append(url)
        self.url = url


class FakeContext:
    def __init__(self):
        self.pages: list[FakePage] = []
        self.created = self.pages

    def new_page(self) -> FakePage:
        page = FakePage("about:blank")
        self.pages.append(page)
        return page


class FakeBrowser:
    def __init__(self, pages: list[FakePage]):
        self.pages = pages
        self.contexts = [FakeContext()]


def main() -> None:
    old = "https://chatgpt.com/c/WEB:4f943fa5-39fa-4b25-95f8-e06ea1ffabed"
    new = "https://chatgpt.com/c/aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    other = "https://chatgpt.com/c/11111111-1111-1111-1111-111111111111"
    with tempfile.TemporaryDirectory() as tmp:
        ns = load_helpers(Path(tmp) / "control.json")
        assert ns["VERSION"] == "2.2.15"
        assert ns["CHECK_INTERVAL"] == 5
        assert ns["hard_unavailable_text"]("Не удалось загрузить этот разговор ChatGPT") is True
        assert ns["hard_unavailable_text"]("Unable to load this conversation") is True
        assert ns["hard_unavailable_text"]("Conversation not found") is True
        assert ns["hard_unavailable_text"]("") is False
        assert ns["hard_unavailable_text"]("composer not ready") is False

        record = {
            "chatgpt_control_url": old,
            "bootstrap_sent": True,
            "bootstrap_sent_at": 1000.0,
            "bootstrap_migrated_from": "2.2.5",
            "recovery_used": True,
            "recovery_reason": "stale_url",
            "recovered_from": "https://chatgpt.com/c/old",
            "restore_attempted_at": 1500.0,
            "restore_failures": 2,
        }
        assert ns["diagnose_control"](record, []) == "zero_messages"
        assert ns["next_control_action"](record, [], checks=9) == "wait"
        assert ns["rebind_allowed"](record, old, False, 2000) is False
        assert ns["next_control_action"](record, [], page_unavailable=True, now=2000) == "rebind"
        assert ns["diagnose_control"](record, [], page_unavailable=True) == "unavailable"

        failed = dict(record)
        failed.update({
            "rebind_for_url": old,
            "rebind_count": 1,
            "rebind_status": "failed",
            "rebind_attempted_at": 2000.0,
        })
        cool = ns["CONTROL_REBIND_COOLDOWN_SECONDS"]
        assert ns["rebind_allowed"](failed, old, True, 2000 + 1) is False
        assert ns["rebind_page_action"](failed, old, True, 2000 + 1, False) == "wait"
        assert ns["rebind_page_action"](failed, old, True, 2000 + cool + 5, False) == "wait"
        assert ns["next_control_action"](failed, [], page_unavailable=True, now=3000) == "wait"

        path = Path(tmp) / "control.json"
        path.write_text(json.dumps(record), encoding="utf-8")
        ns["commit_rebind"](new, old)
        stored = json.loads(path.read_text(encoding="utf-8"))
        assert stored["chatgpt_control_url"] == new
        assert stored["replaced_from"] == old
        assert stored["rebind_for_url"] == old
        assert stored["rebind_status"] == "done"
        assert stored["rebind_count"] == 1
        assert stored["recovery_used"] is True
        assert stored["recovery_reason"] == "stale_url"
        assert stored["recovered_from"] == "https://chatgpt.com/c/old"
        assert stored["bootstrap_sent"] is True
        assert stored["bootstrap_migrated_from"] == "2.2.5"
        assert stored["bootstrap_previous_sent_at"] == 1000.0
        assert "restore_attempted_at" not in stored
        assert "restore_failures" not in stored
        assert ns["rebind_allowed"](stored, old, True, 5000) is False

        path.write_text(json.dumps(record), encoding="utf-8")
        ns["mark_rebind_failed"](old)
        failed_file = json.loads(path.read_text(encoding="utf-8"))
        assert failed_file["recovery_used"] is True
        assert failed_file["recovered_from"] == "https://chatgpt.com/c/old"
        assert failed_file["bootstrap_sent_at"] == 1000.0
        assert failed_file["chatgpt_control_url"] == old
        assert failed_file["rebind_status"] == "failed"
        assert failed_file["rebind_count"] == 1

        ready = dict(stored)
        ready_messages = [{"role": "assistant", "text": ns["CONTROL_READY_MARKER"]}]
        assert ns["next_control_action"](ready, ready_messages) == "ready"
        inflight = {"wake_seen": False, "send_attempts": 0, "retry_after": 0}
        assert ns["pending_wake_action"]("ready", inflight, 1000.0) == "send_wake"
        inflight["wake_seen"] = True
        assert ns["pending_wake_action"]("ready", inflight, 1000.0) == "already_sent"

        path.write_text(json.dumps(record), encoding="utf-8")
        stranger = FakePage(other)
        browser = FakeBrowser([stranger])
        sends: list[str] = []
        ns["composer_is_ready"] = lambda _page: True
        ns["page_signed_out"] = lambda _page: False
        ns["send_to_chatgpt"] = lambda page, text: sends.append(page.url)
        ns["wait_for_conversation_url"] = lambda page, timeout: new
        chosen = ns["begin_control_rebind"](browser, old)
        assert chosen is browser.contexts[0].created[0]
        assert stranger.gotos == []
        assert chosen.gotos == [ns["CHATGPT_HOME"]]
        assert sends == [ns["CHATGPT_HOME"]]
        rebound = json.loads(path.read_text(encoding="utf-8"))
        assert rebound["chatgpt_control_url"] == new
        assert rebound["recovery_used"] is True
        created = len(browser.contexts[0].created)
        again = ns["begin_control_rebind"](browser, old)
        assert len(browser.contexts[0].created) == created
        assert again is chosen or again is None or again is chosen
        assert len(sends) == 1

        path.write_text(json.dumps(record), encoding="utf-8")
        browser = FakeBrowser([stranger])
        ns["composer_is_ready"] = lambda _page: False
        ns["page_signed_out"] = lambda _page: True
        ns["begin_control_rebind"](browser, old)
        assert len(browser.contexts[0].created) == 1
        assert stranger.gotos == []
        failed_again = json.loads(path.read_text(encoding="utf-8"))
        assert failed_again["rebind_status"] == "failed"
        assert failed_again["recovery_used"] is True
        ns["begin_control_rebind"](browser, old)
        assert len(browser.contexts[0].created) == 1

    print("test_control_rebind: OK")


if __name__ == "__main__":
    main()
