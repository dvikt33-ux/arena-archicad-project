"""Composer-wait and one-shot rebind resume. No Playwright and no network."""
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
    "mark_rebind_resume_started",
    "mark_rebind_resume_result",
    "wait_for_rebind_composer",
    "hydrate_rebind_page",
    "begin_control_rebind",
    "resume_control_rebind",
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
    def __init__(self, pages: list[FakePage] | None = None):
        self.pages = list(pages or [])
        self.created: list[FakePage] = []

    def new_page(self) -> FakePage:
        page = FakePage("about:blank")
        self.pages.append(page)
        self.created.append(page)
        return page


class FakeBrowser:
    def __init__(self, pages: list[FakePage] | None = None):
        self.contexts = [FakeContext(pages)]


def legacy_failed(old: str) -> dict:
    return {
        "chatgpt_control_url": old,
        "bootstrap_sent": True,
        "bootstrap_sent_at": 1000.0,
        "bootstrap_migrated_from": "2.2.5",
        "recovery_used": True,
        "recovery_reason": "stale_url",
        "recovered_from": "https://chatgpt.com/c/old",
        "restore_attempted_at": 1500.0,
        "restore_failures": 2,
        "rebind_for_url": old,
        "rebind_count": 1,
        "rebind_status": "failed",
        "rebind_attempted_at": 2000.0,
        "rebind_bootstrap_sent": False,
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
        assert ns["REBIND_COMPOSER_POLL_SECONDS"] > 0
        assert ns["stable_rebind_reason"](ui_text) == "failed"
        assert ns["stable_rebind_reason"]("no_composer") == "no_composer"

        fresh = {
            "chatgpt_control_url": old,
            "bootstrap_sent": True,
            "bootstrap_sent_at": 1000.0,
            "bootstrap_migrated_from": "2.2.5",
            "recovery_used": True,
            "recovery_reason": "stale_url",
            "recovered_from": "https://chatgpt.com/c/old",
        }
        path.write_text(json.dumps(fresh), encoding="utf-8")
        ns["mark_rebind_failed"](old, ui_text)
        leaked = json.loads(path.read_text(encoding="utf-8"))
        assert leaked["rebind_failure_reason"] == "failed"
        assert ui_text not in path.read_text(encoding="utf-8")
        assert leaked["chatgpt_control_url"] == old

        # Delayed composer on a newly created rebind page is not an immediate failure.
        path.write_text(json.dumps(fresh), encoding="utf-8")
        bind_clock(ns)
        polls = {"composer": 0}
        sends: list[str] = []

        def delayed_ready(_page) -> bool:
            polls["composer"] += 1
            return polls["composer"] >= 4

        ns["composer_is_ready"] = delayed_ready
        ns["page_signed_out"] = lambda _page: False
        ns["page_shows_unavailable"] = lambda _page: False
        ns["send_to_chatgpt"] = lambda _page, text: sends.append(text)
        ns["wait_for_conversation_url"] = lambda _page, _timeout: new
        stranger = FakePage(other)
        browser = FakeBrowser([stranger])
        chosen = ns["begin_control_rebind"](browser, old)
        assert polls["composer"] >= 4
        assert sends == [ns["CONTROL_BOOTSTRAP"]]
        assert stranger.gotos == []
        assert len(browser.contexts[0].created) == 1
        assert chosen is browser.contexts[0].created[0]
        assert chosen.gotos == [home]
        stored = json.loads(path.read_text(encoding="utf-8"))
        assert stored["chatgpt_control_url"] == new
        assert stored["chatgpt_control_url"] != home
        assert stored["chatgpt_control_url"].startswith("https://chatgpt.com/c/")
        assert stored["rebind_status"] == "done"
        assert stored["rebind_bootstrap_sent"] is True
        assert stored["recovery_used"] is True
        assert stored["recovery_reason"] == "stale_url"
        created = len(browser.contexts[0].created)
        ns["begin_control_rebind"](browser, old)
        assert len(browser.contexts[0].created) == created
        assert sends == [ns["CONTROL_BOOTSTRAP"]]

        # Persistent no-composer waits out the bound, then does not open another tab.
        path.write_text(json.dumps(fresh), encoding="utf-8")
        clock = bind_clock(ns)
        polls = {"composer": 0}

        def never_ready(_page) -> bool:
            polls["composer"] += 1
            return False

        ns["composer_is_ready"] = never_ready
        ns["send_to_chatgpt"] = lambda _page, text: sends.append(text)
        sends.clear()
        browser = FakeBrowser([stranger])
        ns["begin_control_rebind"](browser, old)
        assert polls["composer"] >= 3
        assert clock.now - 10000.0 >= ns["CONTROL_REBIND_COMPOSER_WAIT"]
        assert sends == []
        assert len(browser.contexts[0].created) == 1
        failed = json.loads(path.read_text(encoding="utf-8"))
        assert failed["rebind_status"] == "failed"
        assert failed["rebind_failure_reason"] == "no_composer"
        assert failed["rebind_bootstrap_sent"] is False
        assert failed["chatgpt_control_url"] == old
        assert failed["chatgpt_control_url"] != home
        ns["begin_control_rebind"](browser, old)
        assert len(browser.contexts[0].created) == 1
        assert ns["rebind_resume_allowed"](failed, old) is False

        # Signed out during the wait fails closed before the deadline.
        path.write_text(json.dumps(fresh), encoding="utf-8")
        clock = bind_clock(ns)
        state = {"n": 0}

        def signed_later(_page) -> bool:
            state["n"] += 1
            return state["n"] >= 3

        ns["page_signed_out"] = signed_later
        ns["composer_is_ready"] = lambda _page: False
        sends.clear()
        browser = FakeBrowser([stranger])
        ns["begin_control_rebind"](browser, old)
        assert state["n"] >= 3
        assert clock.now - 10000.0 < ns["CONTROL_REBIND_COMPOSER_WAIT"]
        signed = json.loads(path.read_text(encoding="utf-8"))
        assert signed["rebind_failure_reason"] == "signed_out"
        assert signed["rebind_status"] == "failed"
        assert sends == []
        assert stranger.gotos == []
        assert len(browser.contexts[0].created) == 1
        assert ui_text not in "\n".join(logs)

        # Hard-unavailable during the wait also fails closed.
        path.write_text(json.dumps(fresh), encoding="utf-8")
        bind_clock(ns)
        bad = {"n": 0}

        def unavailable_later(_page) -> bool:
            bad["n"] += 1
            return bad["n"] >= 2

        ns["page_signed_out"] = lambda _page: False
        ns["page_shows_unavailable"] = unavailable_later
        ns["begin_control_rebind"](FakeBrowser([stranger]), old)
        unavailable = json.loads(path.read_text(encoding="utf-8"))
        assert bad["n"] >= 2
        assert unavailable["rebind_failure_reason"] == "hard_unavailable"
        assert sends == []

        # Home is never committed when no conversation URL appears.
        path.write_text(json.dumps(fresh), encoding="utf-8")
        bind_clock(ns)
        ns["composer_is_ready"] = lambda _page: True
        ns["page_shows_unavailable"] = lambda _page: False
        ns["wait_for_conversation_url"] = lambda _page, _timeout: home
        sends.clear()
        ns["begin_control_rebind"](FakeBrowser([stranger]), old)
        home_fail = json.loads(path.read_text(encoding="utf-8"))
        assert home_fail["chatgpt_control_url"] == old
        assert home_fail["rebind_failure_reason"] == "no_new_url"
        assert home_fail["chatgpt_control_url"] != home
        assert sends == [ns["CONTROL_BOOTSTRAP"]]

        # Legacy 2.2.14 failed/no-reason state resumes once on the marked page.
        legacy = legacy_failed(old)
        assert "rebind_failure_reason" not in legacy
        assert ns["rebind_resume_allowed"](legacy, old) is True
        assert ns["should_resume_rebind"](legacy, old, "wait") is True
        assert ns["should_resume_rebind"](legacy, old, "ready") is False
        assert ns["should_resume_rebind"](legacy, old, "rebind") is False
        assert ns["next_control_action"](legacy, [], page_unavailable=True, now=9000) == "wait"
        assert ns["rebind_page_action"](legacy, old, True, 9000, True) == "wait"
        assert ns["rebind_page_action"](legacy, old, True, 9000, False) == "wait"
        path.write_text(json.dumps(legacy), encoding="utf-8")
        bind_clock(ns)
        polls = {"composer": 0}

        def resume_ready(_page) -> bool:
            polls["composer"] += 1
            return polls["composer"] >= 4

        ns["composer_is_ready"] = resume_ready
        ns["page_signed_out"] = lambda _page: False
        ns["page_shows_unavailable"] = lambda _page: False
        ns["wait_for_conversation_url"] = lambda _page, _timeout: new
        sends.clear()
        marked = FakePage(home, ns["REBIND_PAGE_MARK"])
        unrelated = FakePage(other)
        browser = FakeBrowser([unrelated, marked])
        resumed = ns["resume_control_rebind"](browser, old)
        assert resumed is marked
        assert polls["composer"] >= 4
        assert browser.contexts[0].created == []
        assert marked.gotos == []
        assert unrelated.gotos == []
        assert sends == [ns["CONTROL_BOOTSTRAP"]]
        rebound = json.loads(path.read_text(encoding="utf-8"))
        assert rebound["chatgpt_control_url"] == new
        assert rebound["chatgpt_control_url"] != home
        assert rebound["replaced_from"] == old
        assert rebound["rebind_status"] == "done"
        assert rebound["rebind_count"] == 1
        assert rebound["rebind_bootstrap_sent"] is True
        assert rebound["rebind_resume_count"] == 1
        assert rebound["rebind_resume_status"] == "done"
        assert rebound["recovery_used"] is True
        assert rebound["recovery_reason"] == "stale_url"
        assert rebound["recovered_from"] == "https://chatgpt.com/c/old"
        assert rebound["bootstrap_migrated_from"] == "2.2.5"
        assert rebound["bootstrap_previous_sent_at"] == 1000.0
        assert "blank_for_url" not in rebound
        assert "blank_checks" not in rebound
        assert "restore_attempted_at" not in rebound
        assert ns["rebind_resume_allowed"](rebound, old) is False
        assert ns["should_resume_rebind"](rebound, old, "wait") is False
        ns["resume_control_rebind"](browser, old)
        assert sends == [ns["CONTROL_BOOTSTRAP"]]
        assert browser.contexts[0].created == []

        # Restart reloads the latch and does not resume or create a tab.
        restarted = load_helpers(path)
        restarted["log"] = lambda _message: None
        restarted["send_to_chatgpt"] = lambda _page, text: sends.append(text)
        restarted["composer_is_ready"] = lambda _page: True
        restarted["page_signed_out"] = lambda _page: False
        restarted["page_shows_unavailable"] = lambda _page: False
        disk = json.loads(path.read_text(encoding="utf-8"))
        assert restarted["rebind_resume_allowed"](disk, old) is False
        restarted["resume_control_rebind"](FakeBrowser([marked]), old)
        assert sends == [ns["CONTROL_BOOTSTRAP"]]
        assert json.loads(path.read_text(encoding="utf-8"))["chatgpt_control_url"] == new

        # Missing marked page consumes the latch and opens nothing.
        path.write_text(json.dumps(legacy), encoding="utf-8")
        bind_clock(ns)
        sends.clear()
        empty = FakeBrowser([])
        missing = ns["resume_control_rebind"](empty, old)
        assert missing is None
        assert empty.contexts[0].created == []
        assert empty.contexts[0].pages == []
        missed = json.loads(path.read_text(encoding="utf-8"))
        assert missed["chatgpt_control_url"] == old
        assert missed["rebind_failure_reason"] == "missing_page"
        assert missed["rebind_resume_count"] == 1
        assert missed["rebind_resume_status"] == "failed"
        assert missed["rebind_bootstrap_sent"] is False
        assert sends == []
        ns["resume_control_rebind"](empty, old)
        assert empty.contexts[0].created == []
        assert empty.contexts[0].pages == []
        reloaded = load_helpers(path)
        reloaded["log"] = lambda _message: None
        again = FakeBrowser([])
        reloaded["resume_control_rebind"](again, old)
        assert again.contexts[0].created == []
        assert json.loads(path.read_text(encoding="utf-8"))["chatgpt_control_url"] == old

        # A stored 2.2.15 reason is not a legacy resume, even with the page present.
        reasoned = legacy_failed(old)
        reasoned["rebind_failure_reason"] = "no_composer"
        assert ns["rebind_resume_allowed"](reasoned, old) is False
        path.write_text(json.dumps(reasoned), encoding="utf-8")
        sends.clear()
        kept = FakePage(home, ns["REBIND_PAGE_MARK"])
        browser = FakeBrowser([kept])
        ns["composer_is_ready"] = lambda _page: True
        ns["resume_control_rebind"](browser, old)
        assert sends == []
        assert browser.contexts[0].created == []
        assert kept.gotos == []
        assert json.loads(path.read_text(encoding="utf-8"))["chatgpt_control_url"] == old

        # Bootstrap already sent is not sent again.
        sent = legacy_failed(old)
        sent["rebind_bootstrap_sent"] = True
        assert ns["rebind_resume_allowed"](sent, old) is False
        path.write_text(json.dumps(sent), encoding="utf-8")
        sends.clear()
        ns["wait_for_conversation_url"] = lambda _page, _timeout: new
        ns["hydrate_rebind_page"](FakePage(home, ns["REBIND_PAGE_MARK"]), old, goto_home=False)
        assert sends == []
        assert json.loads(path.read_text(encoding="utf-8"))["chatgpt_control_url"] == new

        # The normal rebind entry does not create a second page for the legacy failure.
        path.write_text(json.dumps(legacy), encoding="utf-8")
        sends.clear()
        marked = FakePage(home, ns["REBIND_PAGE_MARK"])
        browser = FakeBrowser([marked])
        ns["begin_control_rebind"](browser, old)
        assert browser.contexts[0].created == []
        assert sends == []
        assert marked.gotos == []

    print("test_control_resume: OK")


if __name__ == "__main__":
    main()
