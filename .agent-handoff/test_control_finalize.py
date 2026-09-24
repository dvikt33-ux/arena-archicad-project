"""Finalize a no_new_url bootstrap without a new tab. No Playwright and no network."""
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
    "positive_control_identity",
    "canonicalization_eligible",
    "submitted_bootstrap_idle_ready",
    "diagnose_control",
    "control_is_ready",
    "recovery_allowed",
    "rebind_target",
    "rebind_bound",
    "rebind_completed",
    "rebind_cooldown_active",
    "rebind_allowed",
    "rebind_page_action",
    "next_control_action",
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
    "stable_rebind_reason",
    "rebind_page_on_home",
    "rebind_replacement_bound",
    "rebind_replacement_started",
    "rebind_replacement_allowed",
    "should_replace_rebind",
    "find_replacement_page",
    "begin_control_rebind",
    "replace_control_rebind",
    "messages_exact_bootstrap",
    "positive_finalize_identity",
    "finalize_commit_url",
    "submit_confirmation_action",
    "rebind_finalize_bound",
    "rebind_finalize_continue",
    "rebind_finalize_allowed",
    "should_finalize_rebind",
    "mark_finalize_started",
    "mark_finalize_submitted",
    "mark_finalize_failed",
    "mark_submit_retry_started",
    "mark_submit_retry_result",
    "finalize_page_observations",
    "_pick_finalize_commit",
    "_finalize_positive",
    "wait_for_finalize_commit",
    "_commit_finalize",
    "finalize_control_rebind",
    "composer_text",
    "composer_has_exact_text",
    "submit_composer_only",
    "chatgpt_prompt",
    "_submit_confirmed",
    "send_to_chatgpt",
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
                "CONTROL_REBIND_URL_WAIT",
                "CONTROL_RESTORE_GOTO_TIMEOUT",
                "CONTROL_REBIND_COMPOSER_WAIT",
                "CONTROL_FINALIZE_URL_WAIT",
                "CONTROL_SUBMIT_CONFIRM_SECONDS",
                "REBIND_COMPOSER_POLL_SECONDS",
                "REBIND_FAILURE_REASONS",
                "REBIND_PAGE_MARK",
                "REBIND_REPLACEMENT_PAGE_MARK",
                "CHATGPT_HOME",
                "PAGE_TIMEOUT",
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


class Clock:
    def __init__(self, start: float = 10000.0):
        self.now = start

    def time(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += float(seconds)


class FakePage:
    def __init__(self, url: str, name: str = "", messages=None, composer: str = ""):
        self._url = url
        self.window_name = name
        self.messages = list(messages or [])
        self.composer = composer
        self.generating = False
        self.signed_out = False
        self.gotos: list[str] = []
        self.clock = None
        self.url_after = ""
        self.url_after_at = 0.0

    @property
    def url(self) -> str:
        if self.clock is not None and self.url_after and self.clock.now >= self.url_after_at:
            return self.url_after
        return self._url

    @url.setter
    def url(self, value: str) -> None:
        self._url = value

    def evaluate(self, script: str, arg=None):
        if arg is not None:
            self.window_name = arg
            return None
        if script == "window.name":
            return self.window_name
        return ""

    def goto(self, url: str, **_kwargs) -> None:
        self.gotos.append(url)
        self._url = url


class FakeContext:
    def __init__(self, pages=None):
        self.pages = list(pages or [])
        self.created: list[FakePage] = []

    def new_page(self) -> FakePage:
        raise AssertionError("new_page")


class FakeBrowser:
    def __init__(self, pages):
        self.contexts = [FakeContext(pages)]


def no_new_url_state(old: str) -> dict:
    return {
        "chatgpt_control_url": old,
        "bootstrap_sent": True,
        "bootstrap_sent_at": 1000.0,
        "bootstrap_migrated_from": "2.2.5",
        "recovery_used": True,
        "recovery_reason": "stale_url",
        "recovered_from": "https://chatgpt.com/c/old",
        "restore_attempted_at": 1500.0,
        "restore_failures": 1,
        "rebind_for_url": old,
        "rebind_count": 1,
        "rebind_status": "failed",
        "rebind_attempted_at": 2200.0,
        "rebind_bootstrap_sent": True,
        "rebind_failure_reason": "no_new_url",
        "rebind_replacement_for_url": old,
        "rebind_replacement_count": 1,
        "rebind_replacement_status": "failed",
        "rebind_replacement_failure_reason": "no_new_url",
        "rebind_resume_count": 1,
        "rebind_resume_status": "failed",
        "blank_for_url": old,
        "blank_checks": 6,
        "blank_since": 1800.0,
    }


def bind(ns, path: Path, pages: list[FakePage]) -> tuple[FakeBrowser, list[str], list[int]]:
    logs: list[str] = []
    submits: list[int] = []
    ns["log"] = logs.append
    ns["time"] = Clock()

    def evidence(page):
        return {
            "url": page.url,
            "messages": list(page.messages),
            "composer": page.composer,
            "generation": page.generating,
            "signed_out": page.signed_out,
            "unavailable": False,
        }

    def submit_only(page, expected=""):
        stored = json.loads(path.read_text(encoding="utf-8"))
        assert stored["rebind_submit_retry_count"] == 1
        assert stored["rebind_submit_retry_status"] == "started"
        submits.append(1)
        page.messages = [{"role": "user", "text": ns["CONTROL_BOOTSTRAP"]}]
        page.composer = ""
        if page.url_after:
            page._url = page.url_after
        else:
            page._url = "https://chatgpt.com/c/aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"

    ns["page_control_evidence"] = evidence
    ns["submit_composer_only"] = submit_only
    ns["send_to_chatgpt"] = lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("refill"))
    for page in pages:
        page.clock = ns["time"]
    return FakeBrowser(pages), logs, submits



class SendPage:
    def __init__(self, url: str = "https://chatgpt.com/"):
        self.url = url
        self.composer = ""
        self.messages: list[dict] = []
        self.generating = False
        self.fills: list[str] = []
        self.presses: list[str] = []
        self.clicks: list[str] = []
        self.show_send = False
        self.on_enter = None
        self.on_click = None

    def locator(self, selector: str):
        return SendLocator(self, selector)


class SendLocator:
    def __init__(self, page: SendPage, selector: str):
        self.page = page
        self.selector = selector

    def count(self) -> int:
        if "button" in self.selector:
            return 1 if self.page.show_send else 0
        return 1

    def wait_for(self, **_kwargs) -> None:
        return None

    def evaluate(self, _script) -> None:
        return None

    def fill(self, text: str) -> None:
        self.page.fills.append(text)
        self.page.composer = text

    def press(self, key: str) -> None:
        self.page.presses.append(key)
        if self.page.on_enter:
            self.page.on_enter()

    def input_value(self) -> str:
        return self.page.composer

    def inner_text(self) -> str:
        return self.page.composer

    def is_visible(self) -> bool:
        return True

    def click(self) -> None:
        self.page.clicks.append(self.selector)
        if self.page.on_click:
            self.page.on_click()

    @property
    def first(self):
        return self


def send_confirmation() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        ns = load_helpers(Path(tmp) / "control.json")
        ns["time"] = Clock()
        logs: list[str] = []
        ns["log"] = logs.append

        def user_exists(page, text: str) -> bool:
            return any(item.get("role") == "user" and item.get("text") == text for item in page.messages)

        ns["chatgpt_user_message_exists"] = user_exists
        ns["generation_is_active"] = lambda page: bool(page.generating)
        text = "Проверь GitHub. turn_id=50"

        page = SendPage("https://chatgpt.com/")

        def land_message() -> None:
            page.messages.append({"role": "user", "text": page.composer or text})
            page.composer = ""

        page.on_enter = land_message
        assert ns["send_to_chatgpt"](page, text) is True
        assert page.fills == [text]
        assert logs[-1] == "CONTROL: submit=confirmed"
        assert text not in "\n".join(logs)

        page = SendPage("https://chatgpt.com/")
        page.show_send = True

        def land_on_click() -> None:
            page.messages.append({"role": "user", "text": text})
            page.composer = ""

        page.on_click = land_on_click
        logs.clear()
        assert ns["send_to_chatgpt"](page, text) is True
        assert page.fills == [text]
        assert page.clicks
        assert "CONTROL: submit=retry" in logs
        assert text not in "\n".join(logs)

        page = SendPage("https://chatgpt.com/c/aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")

        def clear_only() -> None:
            page.composer = ""

        page.on_enter = clear_only
        logs.clear()
        assert ns["send_to_chatgpt"](page, text) is False
        assert page.fills == [text]
        assert page.clicks == []
        assert logs[-1] == "CONTROL: submit=unconfirmed"
        assert text not in "\n".join(logs)

        page = SendPage("https://chatgpt.com/")
        page.show_send = True
        page.on_enter = lambda: None
        page.on_click = lambda: None
        logs.clear()
        assert ns["send_to_chatgpt"](page, text) is False
        assert page.fills == [text]
        assert page.clicks
        assert logs[-1] == "CONTROL: submit=unconfirmed"


def main() -> None:
    old = "https://chatgpt.com/c/WEB:4f943fa5-39fa-4b25-95f8-e06ea1ffabed"
    new = "https://chatgpt.com/c/aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    other = "https://chatgpt.com/c/11111111-1111-1111-1111-111111111111"
    home = "https://chatgpt.com/"
    source = CORE.read_text(encoding="utf-8")
    submit_source = ast.get_source_segment(
        source,
        next(
            node
            for node in ast.parse(source).body
            if isinstance(node, ast.FunctionDef) and node.name == "submit_composer_only"
        ),
    )
    assert ".fill(" not in submit_source
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "control.json"
        ns = load_helpers(path)
        assert ns["VERSION"] == "2.2.18"
        assert ns["CHECK_INTERVAL"] == 5
        assert ns["CONTROL_FINALIZE_URL_WAIT"] >= 60
        live = no_new_url_state(old)
        assert ns["rebind_finalize_allowed"](live, old) is True
        assert ns["should_finalize_rebind"](live, old, "wait") is True
        assert ns["should_finalize_rebind"](live, old, "recover") is True
        assert ns["should_finalize_rebind"](live, old, "ready") is False
        assert ns["should_replace_rebind"](live, old, "wait") is False
        assert ns["rebind_page_action"](live, old, True, 9000, False) == "wait"
        assert ns["messages_exact_bootstrap"]([
            {"role": "user", "text": ns["CONTROL_BOOTSTRAP_MARKER"]},
        ]) is False
        assert ns["messages_exact_bootstrap"]([
            {"role": "user", "text": ns["CONTROL_BOOTSTRAP"]},
        ]) is True
        assert ns["finalize_commit_url"](new, old, [{"role": "user", "text": ns["CONTROL_BOOTSTRAP_MARKER"]}]) == ""
        assert ns["finalize_commit_url"](home, old, [{"role": "user", "text": ns["CONTROL_BOOTSTRAP"]}]) == ""
        assert ns["finalize_commit_url"](old, old, [{"role": "assistant", "text": "CONTROL READY"}]) == ""
        assert ns["submit_confirmation_action"](False, False, False, True, False) == "retry"
        assert ns["submit_confirmation_action"](False, False, False, True, True) == "fail"
        assert ns["submit_confirmation_action"](False, False, False, False, False) == "fail"
        assert ns["submit_confirmation_action"](True, False, False, True, False) == "confirmed"
        assert ns["submit_confirmation_action"](False, True, False, False, True) == "confirmed"
        assert ns["submit_confirmation_action"](False, False, True, False, True) == "confirmed"

        for reason in ("no_composer", "signed_out", "hard_unavailable", "goto", "unexpected_url", "missing_page", "failed"):
            blocked = no_new_url_state(old)
            blocked["rebind_failure_reason"] = reason
            blocked["rebind_replacement_failure_reason"] = reason
            assert ns["rebind_finalize_allowed"](blocked, old) is False
        not_sent = no_new_url_state(old)
        not_sent["rebind_bootstrap_sent"] = False
        assert ns["rebind_finalize_allowed"](not_sent, old) is False

        # Existing new conversation with exact identity commits without resend or navigation.
        path.write_text(json.dumps(live), encoding="utf-8")
        marked = FakePage(new, ns["REBIND_REPLACEMENT_PAGE_MARK"], [{"role": "user", "text": ns["CONTROL_BOOTSTRAP"]}])
        unrelated = FakePage(other)
        browser, logs, submits = bind(ns, path, [unrelated, marked])
        chosen = ns["finalize_control_rebind"](browser, old)
        assert chosen is marked
        assert submits == []
        assert marked.gotos == []
        assert unrelated.gotos == []
        assert browser.contexts[0].created == []
        stored = json.loads(path.read_text(encoding="utf-8"))
        assert stored["chatgpt_control_url"] == new
        assert stored["chatgpt_control_url"] != home
        assert stored["replaced_from"] == old
        assert stored["rebind_status"] == "done"
        assert stored["rebind_replacement_status"] == "done"
        assert stored["rebind_finalize_status"] == "done"
        assert stored["rebind_finalize_count"] == 1
        assert stored["rebind_url_status"] == "committed"
        assert stored["recovery_used"] is True
        assert stored["recovery_reason"] == "stale_url"
        assert stored["recovered_from"] == "https://chatgpt.com/c/old"
        assert stored["bootstrap_migrated_from"] == "2.2.5"
        assert "blank_for_url" not in stored
        assert "restore_attempted_at" not in stored
        assert ns["CONTROL_BOOTSTRAP_MARKER"] not in "\n".join(logs)
        ns["finalize_control_rebind"](browser, old)
        assert submits == []
        assert browser.contexts[0].created == []

        # Read-only scan finds a different open page and does not touch it.
        path.write_text(json.dumps(live), encoding="utf-8")
        marked = FakePage(home, ns["REBIND_REPLACEMENT_PAGE_MARK"])
        found = FakePage(new, "", [{"role": "assistant", "text": "CONTROL READY"}])
        unrelated = FakePage(other, "", [{"role": "user", "text": "ordinary chat"}])
        browser, logs, submits = bind(ns, path, [unrelated, marked, found])
        chosen = ns["finalize_control_rebind"](browser, old)
        assert chosen is found
        assert submits == []
        assert marked.gotos == []
        assert found.gotos == []
        assert unrelated.gotos == []
        assert json.loads(path.read_text(encoding="utf-8"))["chatgpt_control_url"] == new

        # Marker-only text on another conversation is not identity.
        path.write_text(json.dumps(live), encoding="utf-8")
        marked = FakePage(home, ns["REBIND_REPLACEMENT_PAGE_MARK"], composer="")
        decoy = FakePage(new, "", [{"role": "user", "text": ns["CONTROL_BOOTSTRAP_MARKER"]}])
        browser, _logs, submits = bind(ns, path, [decoy, marked])
        ns["finalize_control_rebind"](browser, old)
        missed = json.loads(path.read_text(encoding="utf-8"))
        assert missed["chatgpt_control_url"] == old
        assert missed["rebind_finalize_status"] == "failed"
        assert missed["rebind_finalize_failure_reason"] == "no_evidence"
        assert decoy.gotos == []
        assert submits == []

        # Home page already showing the exact user message waits and does not resend.
        path.write_text(json.dumps(live), encoding="utf-8")
        marked = FakePage(
            home,
            ns["REBIND_REPLACEMENT_PAGE_MARK"],
            [{"role": "user", "text": ns["CONTROL_BOOTSTRAP"]}],
        )
        marked.url_after = new
        marked.url_after_at = 10002.0
        unrelated = FakePage(other)
        browser, logs, submits = bind(ns, path, [unrelated, marked])
        chosen = ns["finalize_control_rebind"](browser, old)
        assert chosen is marked
        assert submits == []
        assert marked.gotos == []
        assert unrelated.gotos == []
        assert ns["time"].now >= 10002.0
        assert json.loads(path.read_text(encoding="utf-8"))["chatgpt_control_url"] == new
        assert "finalize_wait" in "\n".join(logs)

        # A timeout after confirmed submission stays retryable and can commit later.
        path.write_text(json.dumps(live), encoding="utf-8")
        marked = FakePage(home, ns["REBIND_REPLACEMENT_PAGE_MARK"], [{"role": "user", "text": ns["CONTROL_BOOTSTRAP"]}])
        browser, logs, submits = bind(ns, path, [marked])
        ns["finalize_control_rebind"](browser, old)
        pending = json.loads(path.read_text(encoding="utf-8"))
        assert pending["chatgpt_control_url"] == old
        assert pending["rebind_finalize_status"] == "submitted"
        assert pending["rebind_submission_status"] == "confirmed"
        assert pending["rebind_url_status"] == "pending"
        assert pending["rebind_finalize_count"] == 1
        assert submits == []
        marked._url = new
        ns["finalize_control_rebind"](browser, old)
        assert submits == []
        assert json.loads(path.read_text(encoding="utf-8"))["chatgpt_control_url"] == new
        assert browser.contexts[0].created == []

        # Exact bootstrap still in the composer gets one submit-only retry.
        path.write_text(json.dumps(live), encoding="utf-8")
        marked = FakePage(home, ns["REBIND_REPLACEMENT_PAGE_MARK"], composer=ns["CONTROL_BOOTSTRAP"])
        unrelated = FakePage(other)
        browser, logs, submits = bind(ns, path, [unrelated, marked])
        ns["finalize_control_rebind"](browser, old)
        assert submits == [1]
        assert unrelated.gotos == []
        assert marked.gotos == []
        saved = json.loads(path.read_text(encoding="utf-8"))
        assert saved["chatgpt_control_url"] == new
        assert saved["rebind_submit_retry_count"] == 1
        assert saved["rebind_finalize_status"] == "done"
        ns["finalize_control_rebind"](browser, old)
        assert submits == [1]

        # Restart after the submit latch does not press Enter again.
        retry_state = no_new_url_state(old)
        retry_state.update({
            "rebind_finalize_for_url": old,
            "rebind_finalize_count": 1,
            "rebind_finalize_status": "started",
            "rebind_submit_retry_for_url": old,
            "rebind_submit_retry_count": 1,
            "rebind_submit_retry_status": "started",
        })
        path.write_text(json.dumps(retry_state), encoding="utf-8")
        marked = FakePage(home, ns["REBIND_REPLACEMENT_PAGE_MARK"], composer=ns["CONTROL_BOOTSTRAP"])
        browser, _logs, submits = bind(ns, path, [marked])
        restarted = load_helpers(path)
        restarted["log"] = lambda _message: None
        restarted["page_control_evidence"] = ns["page_control_evidence"]
        restarted["submit_composer_only"] = lambda *_args, **_kwargs: submits.append(1)
        restarted["send_to_chatgpt"] = lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("refill"))
        restarted["finalize_control_rebind"](FakeBrowser([marked]), old)
        assert submits == []
        blocked = json.loads(path.read_text(encoding="utf-8"))
        assert blocked["rebind_finalize_status"] == "failed"
        assert blocked["rebind_finalize_failure_reason"] == "submit_unconfirmed"
        assert blocked["chatgpt_control_url"] == old

        # Empty composer and no evidence fails closed, including after restart.
        path.write_text(json.dumps(live), encoding="utf-8")
        marked = FakePage(home, ns["REBIND_REPLACEMENT_PAGE_MARK"], composer="")
        unrelated = FakePage(other)
        browser, logs, submits = bind(ns, path, [unrelated, marked])
        ns["finalize_control_rebind"](browser, old)
        assert submits == []
        assert unrelated.gotos == []
        empty = json.loads(path.read_text(encoding="utf-8"))
        assert empty["chatgpt_control_url"] == old
        assert empty["rebind_finalize_status"] == "failed"
        assert empty["rebind_finalize_failure_reason"] == "no_evidence"
        again = load_helpers(path)
        again["log"] = lambda _message: None
        again["page_control_evidence"] = ns["page_control_evidence"]
        again["submit_composer_only"] = lambda *_args, **_kwargs: submits.append(1)
        quiet = FakeBrowser([FakePage(other), marked])
        again["finalize_control_rebind"](quiet, old)
        assert submits == []
        assert quiet.contexts[0].created == []

        # The normal rebind and replacement entries do not open a tab for this state.
        path.write_text(json.dumps(live), encoding="utf-8")
        stranger = FakePage(other)
        browser = FakeBrowser([stranger])
        ns["begin_control_rebind"](browser, old)
        ns["replace_control_rebind"](browser, old)
        assert browser.contexts[0].created == []
        assert stranger.gotos == []

    send_confirmation()
    print("test_control_finalize: OK")


if __name__ == "__main__":
    main()
