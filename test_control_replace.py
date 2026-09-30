"""One-shot replacement after a missing rebind page. No Playwright and no network."""
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
    "is_provisional_control_url",
    "is_durable_control_url",
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
    "rebind_resume_allowed",
    "should_resume_rebind",
    "wait_for_rebind_composer",
    "hydrate_rebind_page",
    "begin_control_rebind",
    "rebind_replacement_bound",
    "rebind_replacement_started",
    "rebind_resume_consumed",
    "rebind_replacement_allowed",
    "should_replace_rebind",
    "mark_rebind_replacement_started",
    "mark_rebind_replacement_failed",
    "mark_rebind_replacement_result",
    "find_replacement_page",
    "mark_replacement_page",
    "finish_replacement_page",
    "replace_control_rebind",
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
                "CONTROL_REBIND_COMPOSER_WAIT",
                "REBIND_COMPOSER_POLL_SECONDS",
                "REBIND_FAILURE_REASONS",
                "REBIND_PAGE_MARK",
                "REBIND_REPLACEMENT_PAGE_MARK",
                "CHATGPT_HOME",
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
    def __init__(self, url: str, name: str = ""):
        self.url = url
        self.window_name = name
        self.gotos: list[str] = []
        self.expect_mark = ""

    def evaluate(self, script: str, arg=None):
        if arg is not None:
            self.window_name = arg
            return None
        if script == "window.name":
            return self.window_name
        return ""

    def goto(self, url: str, **_kwargs) -> None:
        if self.expect_mark:
            assert self.window_name == self.expect_mark
        self.gotos.append(url)
        self.url = url


class FakeContext:
    def __init__(self, pages: list[FakePage] | None = None, on_new=None):
        self.pages = list(pages or [])
        self.created: list[FakePage] = []
        self.on_new = on_new

    def new_page(self) -> FakePage:
        if self.on_new:
            self.on_new()
        page = FakePage("about:blank")
        self.pages.append(page)
        self.created.append(page)
        return page


class FakeBrowser:
    def __init__(self, pages: list[FakePage] | None = None, on_new=None):
        self.contexts = [FakeContext(pages, on_new)]


def missing_page_state(old: str) -> dict:
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
        "rebind_attempted_at": 2000.0,
        "rebind_bootstrap_sent": False,
        "rebind_failure_reason": "missing_page",
        "rebind_resume_count": 1,
        "rebind_resume_status": "failed",
        "rebind_resume_for_url": old,
        "blank_for_url": old,
        "blank_checks": 6,
        "blank_since": 1800.0,
    }


def bind_clock(ns) -> Clock:
    clock = Clock()
    ns["time"] = clock
    return clock


def main() -> None:
    old = "https://chatgpt.com/c/WEB:4f943fa5-39fa-4b25-95f8-e06ea1ffabed"
    new = "https://chatgpt.com/c/aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    other = "https://chatgpt.com/c/11111111-1111-1111-1111-111111111111"
    home = "https://chatgpt.com/"
    ui_text = "Не удалось загрузить этот разговор"
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "control.json"
        ns = load_helpers(path)
        logs: list[str] = []
        ns["log"] = logs.append
        assert ns["VERSION"] == "2.2.19"
        assert ns["CHECK_INTERVAL"] == 5
        assert ns["CONTROL_REBIND_COMPOSER_WAIT"] >= 20
        assert ns["stable_rebind_reason"](ui_text) == "failed"

        live = missing_page_state(old)
        assert ns["rebind_replacement_allowed"](live, old) is True
        assert ns["should_replace_rebind"](live, old, "wait") is True
        assert ns["should_replace_rebind"](live, old, "recover") is True
        assert ns["should_replace_rebind"](live, old, "ready") is False
        assert ns["should_replace_rebind"](live, old, "rebind") is False
        assert ns["should_resume_rebind"](live, old, "wait") is False
        assert ns["next_control_action"](live, [], page_unavailable=True, now=9000) == "wait"
        assert ns["rebind_page_action"](live, old, True, 9000, False) == "wait"

        path.write_text(json.dumps(live), encoding="utf-8")
        ns["mark_rebind_replacement_failed"](old, ui_text)
        leaked = json.loads(path.read_text(encoding="utf-8"))
        assert leaked["rebind_replacement_failure_reason"] == "failed"
        assert ui_text not in path.read_text(encoding="utf-8")
        path.write_text(json.dumps(live), encoding="utf-8")

        # The normal rebind entry must not open a tab for this already-failed state.
        bind_clock(ns)
        ns["composer_is_ready"] = lambda _page: True
        ns["page_signed_out"] = lambda _page: False
        ns["page_shows_unavailable"] = lambda _page: False
        stranger = FakePage(other)
        browser = FakeBrowser([stranger])
        ns["begin_control_rebind"](browser, old)
        assert browser.contexts[0].created == []
        assert stranger.gotos == []

        # Exact missing_page state creates one page, and the latch is written first.
        latch_seen = {"ok": False}

        def on_new() -> None:
            stored = json.loads(path.read_text(encoding="utf-8"))
            assert stored["rebind_replacement_count"] == 1
            assert stored["rebind_replacement_status"] == "started"
            assert stored["rebind_replacement_for_url"] == old
            assert stored["chatgpt_control_url"] == old
            latch_seen["ok"] = True

        bind_clock(ns)
        polls = {"composer": 0}

        def delayed_ready(_page) -> bool:
            polls["composer"] += 1
            return polls["composer"] >= 4

        sends: list[str] = []
        ns["composer_is_ready"] = delayed_ready
        ns["page_signed_out"] = lambda _page: False
        ns["page_shows_unavailable"] = lambda _page: False
        ns["send_to_chatgpt"] = lambda _page, text: sends.append(text)
        ns["wait_for_conversation_url"] = lambda _page, _timeout: new
        stranger = FakePage(other)
        browser = FakeBrowser([stranger], on_new=on_new)
        chosen = ns["replace_control_rebind"](browser, old)
        assert latch_seen["ok"] is True
        assert polls["composer"] >= 4
        assert sends == [ns["CONTROL_BOOTSTRAP"]]
        assert len(browser.contexts[0].created) == 1
        assert chosen is browser.contexts[0].created[0]
        assert chosen.window_name == ns["REBIND_REPLACEMENT_PAGE_MARK"]
        assert chosen.gotos == [home]
        assert stranger.gotos == []
        stored = json.loads(path.read_text(encoding="utf-8"))
        assert stored["chatgpt_control_url"] == new
        assert stored["chatgpt_control_url"] != home
        assert stored["replaced_from"] == old
        assert stored["rebind_status"] == "done"
        assert stored["rebind_bootstrap_sent"] is True
        assert stored["rebind_replacement_count"] == 1
        assert stored["rebind_replacement_status"] == "done"
        assert stored["rebind_replacement_for_url"] == old
        assert stored["recovery_used"] is True
        assert stored["recovery_reason"] == "stale_url"
        assert stored["recovered_from"] == "https://chatgpt.com/c/old"
        assert stored["bootstrap_migrated_from"] == "2.2.5"
        assert stored["bootstrap_previous_sent_at"] == 1000.0
        assert "blank_for_url" not in stored
        assert "blank_checks" not in stored
        assert "restore_attempted_at" not in stored
        assert "rebind_replacement_failure_reason" not in stored
        created = len(browser.contexts[0].created)
        ns["replace_control_rebind"](browser, old)
        assert len(browser.contexts[0].created) == created
        assert sends == [ns["CONTROL_BOOTSTRAP"]]
        assert ns["rebind_replacement_allowed"](stored, old) is False
        assert ui_text not in "\n".join(logs)

        # Restart during replacement resumes the marked page and does not create another.
        started = missing_page_state(old)
        started.update({
            "rebind_replacement_for_url": old,
            "rebind_replacement_count": 1,
            "rebind_replacement_status": "started",
        })
        assert ns["rebind_replacement_allowed"](started, old) is False
        assert ns["should_replace_rebind"](started, old, "wait") is True
        assert ns["should_replace_rebind"](started, old, "rebind") is True
        path.write_text(json.dumps(started), encoding="utf-8")
        bind_clock(ns)
        polls = {"composer": 0}
        ns["composer_is_ready"] = delayed_ready
        sends.clear()
        marked = FakePage(home, ns["REBIND_REPLACEMENT_PAGE_MARK"])
        unrelated = FakePage(other)
        browser = FakeBrowser([unrelated, marked], on_new=lambda: (_ for _ in ()).throw(AssertionError("new_page")))
        resumed = ns["replace_control_rebind"](browser, old)
        assert resumed is marked
        assert polls["composer"] >= 4
        assert browser.contexts[0].created == []
        assert marked.gotos == []
        assert unrelated.gotos == []
        assert sends == [ns["CONTROL_BOOTSTRAP"]]
        rebound = json.loads(path.read_text(encoding="utf-8"))
        assert rebound["chatgpt_control_url"] == new
        assert rebound["rebind_replacement_status"] == "done"
        assert rebound["recovery_used"] is True
        ns["replace_control_rebind"](browser, old)
        assert browser.contexts[0].created == []
        assert sends == [ns["CONTROL_BOOTSTRAP"]]

        # Restart with a started latch but no marked page fails closed.
        path.write_text(json.dumps(started), encoding="utf-8")
        bind_clock(ns)
        sends.clear()
        unrelated = FakePage(other)
        empty = FakeBrowser([unrelated])
        missing = ns["replace_control_rebind"](empty, old)
        assert missing is None
        assert empty.contexts[0].created == []
        assert unrelated.gotos == []
        missed = json.loads(path.read_text(encoding="utf-8"))
        assert missed["chatgpt_control_url"] == old
        assert missed["rebind_replacement_status"] == "failed"
        assert missed["rebind_replacement_count"] == 1
        assert missed["rebind_replacement_failure_reason"] == "missing_page"
        assert sends == []
        ns["replace_control_rebind"](empty, old)
        assert empty.contexts[0].created == []
        restarted = load_helpers(path)
        restarted["log"] = lambda _message: None
        again = FakeBrowser([FakePage(other)])
        restarted["replace_control_rebind"](again, old)
        assert again.contexts[0].created == []
        assert json.loads(path.read_text(encoding="utf-8"))["chatgpt_control_url"] == old

        # Every other failure reason, and nearby failed shapes, create nothing.
        blocked = [
            "no_composer",
            "signed_out",
            "hard_unavailable",
            "no_new_url",
            "goto",
            "unexpected_url",
            "failed",
            "",
        ]
        for reason in blocked:
            variant = missing_page_state(old)
            if reason:
                variant["rebind_failure_reason"] = reason
            else:
                variant.pop("rebind_failure_reason")
            assert ns["rebind_replacement_allowed"](variant, old) is False
            path.write_text(json.dumps(variant), encoding="utf-8")
            browser = FakeBrowser([FakePage(other)])
            ns["replace_control_rebind"](browser, old)
            assert browser.contexts[0].created == []
            assert json.loads(path.read_text(encoding="utf-8"))["chatgpt_control_url"] == old

        not_consumed = missing_page_state(old)
        not_consumed["rebind_resume_count"] = 0
        not_consumed.pop("rebind_resume_status")
        assert ns["rebind_replacement_allowed"](not_consumed, old) is False
        sent = missing_page_state(old)
        sent["rebind_bootstrap_sent"] = True
        assert ns["rebind_replacement_allowed"](sent, old) is False
        done = missing_page_state(old)
        done["rebind_status"] = "done"
        assert ns["rebind_replacement_allowed"](done, old) is False

        # A replacement that never gets a conversation URL does not persist home or open another tab.
        path.write_text(json.dumps(live), encoding="utf-8")
        bind_clock(ns)
        ns["composer_is_ready"] = lambda _page: True
        ns["wait_for_conversation_url"] = lambda _page, _timeout: home
        sends.clear()
        browser = FakeBrowser([FakePage(other)])
        ns["replace_control_rebind"](browser, old)
        home_fail = json.loads(path.read_text(encoding="utf-8"))
        assert len(browser.contexts[0].created) == 1
        assert home_fail["chatgpt_control_url"] == old
        assert home_fail["chatgpt_control_url"] != home
        assert home_fail["rebind_replacement_status"] == "failed"
        assert home_fail["rebind_replacement_failure_reason"] == "no_new_url"
        assert sends == [ns["CONTROL_BOOTSTRAP"]]
        ns["replace_control_rebind"](browser, old)
        assert len(browser.contexts[0].created) == 1

        # Signed out during the replacement wait consumes the attempt and does not grow tabs.
        path.write_text(json.dumps(live), encoding="utf-8")
        bind_clock(ns)
        state = {"n": 0}

        def signed_later(_page) -> bool:
            state["n"] += 1
            return state["n"] >= 3

        ns["page_signed_out"] = signed_later
        ns["composer_is_ready"] = lambda _page: False
        sends.clear()
        browser = FakeBrowser([FakePage(other)])
        ns["replace_control_rebind"](browser, old)
        assert state["n"] >= 3
        signed = json.loads(path.read_text(encoding="utf-8"))
        assert signed["rebind_replacement_status"] == "failed"
        assert signed["rebind_replacement_failure_reason"] == "signed_out"
        assert signed["chatgpt_control_url"] == old
        assert sends == []
        assert len(browser.contexts[0].created) == 1
        ns["replace_control_rebind"](browser, old)
        assert len(browser.contexts[0].created) == 1

    print("test_control_replace: OK")


if __name__ == "__main__":
    main()
