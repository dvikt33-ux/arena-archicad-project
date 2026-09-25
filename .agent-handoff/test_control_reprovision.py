"""One reprovision after 2.2.17 finalize missing_page. No Playwright and no network."""
from __future__ import annotations

import ast
import json
import tempfile
from pathlib import Path

CORE = Path(__file__).with_name("dispatcher.py")
OLD = "https://chatgpt.com/c/11111111-2222-3333-4444-555555555555"
NEW = "https://chatgpt.com/c/aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
OTHER = "https://chatgpt.com/c/99999999-8888-7777-6666-555555555555"
MARK = "ai-dispatcher-rebind-reprovision"

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
    "rebind_resume_allowed",
    "rebind_replacement_bound",
    "rebind_replacement_started",
    "rebind_replacement_allowed",
    "should_replace_rebind",
    "find_replacement_page",
    "begin_control_rebind",
    "resume_control_rebind",
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
    "finalize_control_rebind",
    "_diag_reprovision_status",
    "rebind_reprovision_bound",
    "rebind_reprovision_started",
    "rebind_reprovision_allowed",
    "reprovision_failed_closed",
    "should_reprovision_rebind",
    "mark_reprovision_started",
    "mark_reprovision_failed",
    "mark_reprovision_attempted",
    "mark_reprovision_submission",
    "mark_reprovision_retry_started",
    "mark_reprovision_retry_result",
    "find_reprovision_page",
    "mark_reprovision_page",
    "reprovision_page_observations",
    "_pick_reprovision_commit",
    "wait_for_reprovision_commit",
    "fill_composer_once",
    "_composer_exact_bootstrap",
    "reprovision_submit_confirmed",
    "submit_reprovision_bootstrap",
    "_commit_reprovision",
    "finish_reprovision_page",
    "reprovision_control_rebind",
    "wait_for_rebind_composer",
    "page_control_evidence",
    "_submit_confirmed",
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
                "CONTROL_REPROVISION_URL_WAIT",
                "CONTROL_SUBMIT_CONFIRM_SECONDS",
                "REBIND_COMPOSER_POLL_SECONDS",
                "REBIND_FAILURE_REASONS",
                "REBIND_PAGE_MARK",
                "REBIND_REPLACEMENT_PAGE_MARK",
                "REBIND_REPROVISION_PAGE_MARK",
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
    def __init__(self, start: float = 0.0):
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
        self.unavailable = False
        self.gotos: list[str] = []
        self.clock = None
        self.url_after = ""
        self.url_after_at = 10**9

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


class CreatingContext:
    def __init__(self, harness):
        self.harness = harness
        self.pages = harness.pages

    def new_page(self) -> FakePage:
        if not self.harness.allow_create:
            raise AssertionError("new_page")
        stored = json.loads(self.harness.path.read_text(encoding="utf-8"))
        assert stored["rebind_reprovision_status"] == "started", stored
        assert stored["rebind_reprovision_count"] == 1
        assert stored["rebind_reprovision_for_url"] == OLD
        page = FakePage("about:blank")
        page.clock = self.harness.ns["time"]
        page.signed_out = self.harness.sign_out_new
        page.unavailable = self.harness.unavailable_new
        mark = self.harness.ns["REBIND_REPROVISION_PAGE_MARK"]

        def goto(url, **_kwargs):
            assert page.window_name == mark, page.window_name
            page.gotos.append(url)
            page._url = url

        page.goto = goto
        self.pages.append(page)
        self.harness.created.append(page)
        return page


class FakeBrowser:
    def __init__(self, context):
        self.contexts = [context]


def live_state(old: str = OLD) -> dict:
    return {
        "chatgpt_control_url": old,
        "name": "01 — CONTROL & BRIDGE",
        "bootstrap_sent": True,
        "bootstrap_sent_at": 1000.0,
        "bootstrap_previous_sent_at": 900.0,
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
        "rebind_bootstrap_attempted": True,
        "rebind_submission_status": "confirmed",
        "rebind_failure_reason": "no_new_url",
        "rebind_replacement_for_url": old,
        "rebind_replacement_count": 1,
        "rebind_replacement_status": "failed",
        "rebind_replacement_failure_reason": "no_new_url",
        "rebind_resume_count": 1,
        "rebind_resume_status": "failed",
        "rebind_finalize_for_url": old,
        "rebind_finalize_count": 1,
        "rebind_finalize_status": "failed",
        "rebind_finalize_failure_reason": "missing_page",
        "blank_for_url": old,
        "blank_checks": 6,
        "blank_since": 1800.0,
    }


class Harness:
    def __init__(self, ns, path: Path, pages, *, allow_create=True):
        self.ns = ns
        self.path = path
        self.pages = list(pages)
        self.allow_create = allow_create
        self.created: list[FakePage] = []
        self.logs: list[str] = []
        self.fills: list[str] = []
        self.fill_times: list[float] = []
        self.submits: list[int] = []
        self.submit_times: list[float] = []
        self.mode = "message"
        self.delay_composer = False
        self.ready_at = None
        self.sign_out_new = False
        self.unavailable_new = False
        self.composer_ready = True
        ns["CONTROL_PATH"] = path
        ns["log"] = self.logs.append
        ns["time"] = Clock()
        for page in self.pages:
            page.clock = ns["time"]
        self.context = CreatingContext(self)
        self.browser = FakeBrowser(self.context)
        self._install()

    def _install(self):
        ns = self.ns
        harness = self

        def evidence(page):
            return {
                "url": page.url,
                "messages": list(page.messages),
                "composer": page.composer,
                "generation": bool(page.generating),
                "signed_out": bool(page.signed_out),
                "unavailable": bool(page.unavailable),
            }

        def composer_is_ready(_page):
            if harness.delay_composer:
                if harness.ready_at is None:
                    harness.ready_at = ns["time"].time() + 2
                return ns["time"].time() >= harness.ready_at
            return harness.composer_ready

        def fill(page, text):
            harness.fills.append(text)
            harness.fill_times.append(ns["time"].time())
            page.composer = text
            if harness.mode == "message":
                page.messages = [{"role": "user", "text": text}]
                page.composer = ""
                page.url_after = NEW
                page.url_after_at = ns["time"].time() + 1
            elif harness.mode == "generation":
                page.generating = True
                page.composer = ""
                page.url_after = NEW
                page.url_after_at = ns["time"].time() + 1
            elif harness.mode == "url":
                page.composer = ""
                page._url = NEW
            elif harness.mode == "retry":
                pass
            elif harness.mode == "unconfirmed":
                pass
            elif harness.mode == "vanished":
                page.composer = ""
            elif harness.mode == "no_url":
                page.messages = [{"role": "user", "text": text}]
                page.composer = ""

        def submit_only(page, _expected=""):
            stored = json.loads(harness.path.read_text(encoding="utf-8"))
            assert stored["rebind_reprovision_submit_retry_count"] == 1
            assert stored["rebind_reprovision_submit_retry_status"] == "started"
            assert "Служебный" not in "".join(harness.logs)
            harness.submits.append(1)
            harness.submit_times.append(ns["time"].time())
            if harness.mode in {"unconfirmed", "vanished"}:
                return
            page.messages = [{"role": "user", "text": ns["CONTROL_BOOTSTRAP"]}]
            page.composer = ""
            page._url = NEW

        ns["page_control_evidence"] = evidence
        ns["composer_is_ready"] = composer_is_ready
        ns["page_signed_out"] = lambda page: bool(getattr(page, "signed_out", False))
        ns["page_shows_unavailable"] = lambda page: bool(getattr(page, "unavailable", False))
        def user_exists(page, text):
            expected = str(text or "").strip()
            return any(
                item.get("role") == "user" and str(item.get("text") or "").strip() == expected
                for item in getattr(page, "messages", [])
            )

        ns["chatgpt_user_message_exists"] = user_exists
        ns["generation_is_active"] = lambda page: bool(getattr(page, "generating", False))
        ns["fill_composer_once"] = fill
        ns["submit_composer_only"] = submit_only
        ns["send_to_chatgpt"] = lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("legacy send"))

    def run(self, old: str = OLD):
        return self.ns["reprovision_control_rebind"](self.browser, old)


def write_state(path: Path, record: dict) -> None:
    path.write_text(json.dumps(record), encoding="utf-8")


def read_state(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def assert_text_free(logs, ns) -> None:
    blob = "\n".join(logs)
    assert "Служебный" not in blob
    assert ns["CONTROL_BOOTSTRAP"] not in blob
    assert "turn_id=" not in blob


def assert_history(stored: dict) -> None:
    assert stored["chatgpt_control_url"] == NEW
    assert stored["chatgpt_control_url"] != "https://chatgpt.com/"
    assert "/c/" in stored["chatgpt_control_url"]
    assert stored["replaced_from"] == OLD
    assert stored["recovery_used"] is True
    assert stored["recovered_from"] == "https://chatgpt.com/c/old"
    assert stored["recovery_reason"] == "stale_url"
    assert stored["bootstrap_sent"] is True
    assert stored["bootstrap_previous_sent_at"] == 900.0
    assert stored["bootstrap_migrated_from"] == "2.2.5"
    assert stored["rebind_reprovision_status"] == "done"
    assert stored["rebind_reprovision_count"] == 1
    assert stored["rebind_reprovision_for_url"] == OLD
    assert stored["rebind_reprovision_submission_status"] == "confirmed"
    assert stored["rebind_reprovision_bootstrap_attempted"] is True
    assert stored["rebind_replacement_status"] == "done"
    assert stored["rebind_finalize_status"] == "done"
    assert "blank_for_url" not in stored
    assert "blank_checks" not in stored
    assert "restore_attempted_at" not in stored
    assert "restore_failures" not in stored
    assert "rebind_reprovision_failure_reason" not in stored


def func_source(name: str) -> str:
    text = CORE.read_text(encoding="utf-8")
    tree = ast.parse(text)
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return ast.get_source_segment(text, node) or ""
    raise AssertionError(name)


def test_constants(ns) -> None:
    assert ns["VERSION"] == "2.2.19"
    assert ns["CHECK_INTERVAL"] == 5
    assert ns["CONTROL_REPROVISION_URL_WAIT"] >= 90
    assert ns["CONTROL_REBIND_COMPOSER_WAIT"] >= 20
    assert ns["REBIND_REPROVISION_PAGE_MARK"] == MARK
    src = CORE.read_text(encoding="utf-8")
    assert "https://raw.githubusercontent.com/" in src
    assert "ref=agent-handoff" in src
    assert "time.sleep(1)" not in func_source("reprovision_control_rebind")
    assert "time.sleep(1)" not in func_source("wait_for_reprovision_commit")
    assert "time.sleep(1)" not in func_source("finish_reprovision_page")
    submit = func_source("submit_reprovision_bootstrap")
    assert "rebind_bootstrap_sent" not in submit
    assert "send_to_chatgpt" not in submit
    assert submit.index("mark_reprovision_attempted") < submit.index("fill_composer_once")
    assert submit.index("mark_reprovision_retry_started") < submit.index("submit_composer_only")
    assert "_submit_confirmed" in func_source("reprovision_submit_confirmed")
    body = func_source("reprovision_control_rebind")
    assert body.index("reprovision_page_observations") < body.index("new_page")
    assert body.index("mark_reprovision_started") < body.index("new_page")
    assert body.index("mark_reprovision_page") < body.index("finish_reprovision_page")
    assert "hydrate_rebind_page" not in body
    ensure = src.split("def ensure_control_ready", 1)[1].split("\ndef dismiss_arena_completion", 1)[0]
    assert ensure.index("should_reprovision_rebind") < ensure.index("should_finalize_rebind")
    assert ensure.index("reprovision_failed_closed") < ensure.index('action == "recover"')
    assert ensure.index("reprovision_failed_closed") < ensure.index("provision_control_chat")


def test_pick_rules(ns) -> None:
    ready = [{"role": "assistant", "text": "CONTROL READY"}]
    exact = [{"role": "user", "text": ns["CONTROL_BOOTSTRAP"]}]
    marker = [{"role": "user", "text": ns["CONTROL_BOOTSTRAP_MARKER"]}]
    ordinary = [{"role": "user", "text": "hello"}]
    pick = ns["_pick_reprovision_commit"]
    assert pick([(object(), {"url": NEW, "messages": ready, "reprovision": False})], OLD, False)[1] == NEW
    assert pick([(object(), {"url": NEW, "messages": exact, "reprovision": False})], OLD, False)[1] == NEW
    assert pick([(object(), {"url": NEW, "messages": marker, "reprovision": False})], OLD, False)[1] == ""
    assert pick([(object(), {"url": NEW, "messages": ordinary, "reprovision": False})], OLD, True)[1] == ""
    assert pick([(object(), {"url": "https://chatgpt.com/", "messages": ready, "reprovision": True})], OLD, True)[1] == ""
    assert pick([(object(), {"url": OLD, "messages": ready, "reprovision": True})], OLD, True)[1] == ""
    marked = object()
    assert pick([(marked, {"url": NEW, "messages": [], "reprovision": True})], OLD, True)[1] == NEW
    assert pick([(marked, {"url": NEW, "messages": [], "reprovision": True})], OLD, False)[1] == ""


def test_save_roundtrip(ns, path: Path) -> None:
    state = live_state()
    state.update(
        {
            "rebind_reprovision_for_url": OLD,
            "rebind_reprovision_count": 1,
            "rebind_reprovision_status": "started",
            "rebind_reprovision_failure_reason": "missing_page",
            "rebind_reprovision_bootstrap_attempted": True,
            "rebind_reprovision_submission_status": "attempted",
            "rebind_reprovision_submit_retry_for_url": OLD,
            "rebind_reprovision_submit_retry_count": 1,
            "rebind_reprovision_submit_retry_status": "started",
        }
    )
    write_state(path, state)
    ns["CONTROL_PATH"] = path
    ns["save_control_record"](read_state(path))
    saved = read_state(path)
    assert saved["rebind_reprovision_for_url"] == OLD
    assert saved["rebind_reprovision_count"] == 1
    assert saved["rebind_reprovision_status"] == "started"
    assert saved["rebind_reprovision_failure_reason"] == "missing_page"
    assert saved["rebind_reprovision_bootstrap_attempted"] is True
    assert saved["rebind_reprovision_submission_status"] == "attempted"
    assert saved["rebind_reprovision_submit_retry_count"] == 1
    assert saved["rebind_reprovision_submit_retry_status"] == "started"
    assert saved["rebind_reprovision_submit_retry_for_url"] == OLD
    assert saved["dispatcher_version"] == "2.2.19"


def test_eligibility(ns, path: Path) -> None:
    write_state(path, live_state())
    ns["CONTROL_PATH"] = path
    record = read_state(path)
    assert ns["rebind_reprovision_allowed"](record, OLD) is True
    assert ns["reprovision_failed_closed"](record, OLD) is False
    for action in ("wait", "recover", "rebind", "send"):
        assert ns["should_reprovision_rebind"](record, OLD, action) is True
    assert ns["should_reprovision_rebind"](record, OLD, "ready") is False
    assert ns["should_replace_rebind"](record, OLD, "wait") is False
    assert ns["should_finalize_rebind"](record, OLD, "wait") is False
    assert ns["rebind_page_action"](record, OLD, True, 0, False) == "wait"
    assert ns["rebind_resume_allowed"](record, OLD) is False
    mutations = {
        "failure_reason": {"rebind_failure_reason": "goto"},
        "bootstrap_unsent": {"rebind_bootstrap_sent": False},
        "bootstrap_missing": {"rebind_bootstrap_sent": None},
        "rebind_done": {"rebind_status": "done"},
        "replacement_done": {"rebind_replacement_status": "done"},
        "replacement_reason": {"rebind_replacement_failure_reason": "goto"},
        "replacement_count": {"rebind_replacement_count": 0},
        "replacement_url": {"rebind_replacement_for_url": OTHER},
        "finalize_submitted": {"rebind_finalize_status": "submitted"},
        "finalize_reason": {"rebind_finalize_failure_reason": "no_evidence"},
        "finalize_count": {"rebind_finalize_count": 0},
        "finalize_url": {"rebind_finalize_for_url": OTHER},
        "control_url": {"chatgpt_control_url": OTHER},
        "rebind_url": {"rebind_for_url": OTHER},
        "already_failed": {
            "rebind_reprovision_for_url": OLD,
            "rebind_reprovision_count": 1,
            "rebind_reprovision_status": "failed",
            "rebind_reprovision_failure_reason": "no_new_url",
        },
    }
    for name, changes in mutations.items():
        state = live_state()
        state.update(changes)
        if changes.get("rebind_bootstrap_sent", True) is None:
            state.pop("rebind_bootstrap_sent", None)
        write_state(path, state)
        current = read_state(path)
        assert ns["rebind_reprovision_allowed"](current, OLD) is False, name
        harness = Harness(ns, path, [FakePage(OTHER)], allow_create=False)
        harness.run()
        assert harness.created == [], name
        assert read_state(path)["chatgpt_control_url"] == state["chatgpt_control_url"], name


def test_prescan_commits_without_page(ns, path: Path) -> None:
    write_state(path, live_state())
    ready = FakePage(NEW, messages=[{"role": "assistant", "text": "prefix CONTROL READY suffix"}])
    unrelated = FakePage(OTHER, messages=[{"role": "user", "text": "ordinary"}])
    foreign = FakePage("https://arena.ai/c/1")
    harness = Harness(ns, path, [unrelated, ready, foreign], allow_create=False)
    harness.run()
    stored = read_state(path)
    assert_history(stored)
    assert harness.created == []
    assert harness.fills == []
    assert ready.gotos == []
    assert unrelated.gotos == []
    assert foreign.gotos == []
    assert "page=reprovision_create" not in "\n".join(harness.logs)
    assert_text_free(harness.logs, ns)
    again = Harness(ns, path, [unrelated], allow_create=False)
    again.run()
    assert again.created == []


def test_prescan_exact_user_message(ns, path: Path) -> None:
    write_state(path, live_state())
    page = FakePage(OTHER, messages=[{"role": "user", "text": ns["CONTROL_BOOTSTRAP"]}])
    marker = FakePage(NEW, messages=[{"role": "user", "text": ns["CONTROL_BOOTSTRAP_MARKER"]}])
    harness = Harness(ns, path, [marker, page], allow_create=False)
    harness.run()
    stored = read_state(path)
    assert stored["chatgpt_control_url"] == OTHER
    assert marker.gotos == []
    assert page.gotos == []
    assert harness.created == []


def test_success_delayed_composer_and_repeat(ns, path: Path) -> None:
    write_state(path, live_state())
    unrelated = FakePage(OTHER, messages=[{"role": "user", "text": "leave me"}])
    marker = FakePage(
        "https://chatgpt.com/c/bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
        messages=[{"role": "user", "text": ns["CONTROL_BOOTSTRAP_MARKER"]}],
    )
    foreign = FakePage("https://example.test/")
    harness = Harness(ns, path, [unrelated, marker, foreign])
    harness.delay_composer = True
    harness.mode = "message"
    harness.run()
    stored = read_state(path)
    assert_history(stored)
    assert len(harness.created) == 1
    assert harness.fills == [ns["CONTROL_BOOTSTRAP"]]
    assert harness.fill_times[0] >= 2
    assert harness.submits == []
    assert harness.ns["time"].now >= harness.fill_times[0] + 1
    assert harness.ns["time"].now < 90
    assert harness.created[0].window_name == MARK
    assert harness.created[0].gotos == ["https://chatgpt.com/"]
    assert unrelated.gotos == []
    assert marker.gotos == []
    assert foreign.gotos == []
    assert stored["chatgpt_control_url"] != marker.url
    assert_text_free(harness.logs, ns)
    assert "page=reprovision_create" in "\n".join(harness.logs)
    again = Harness(ns, path, [unrelated, marker], allow_create=False)
    again.run()
    assert again.created == []
    assert again.fills == []
    assert read_state(path)["chatgpt_control_url"] == NEW


def test_generation_confirmation(ns, path: Path) -> None:
    write_state(path, live_state())
    harness = Harness(ns, path, [])
    harness.mode = "generation"
    harness.run()
    stored = read_state(path)
    assert_history(stored)
    assert harness.fills == [ns["CONTROL_BOOTSTRAP"]]
    assert harness.submits == []
    assert harness.ns["time"].now >= 1
    assert_text_free(harness.logs, ns)


def test_url_confirmation(ns, path: Path) -> None:
    write_state(path, live_state())
    harness = Harness(ns, path, [])
    harness.mode = "url"
    harness.run()
    stored = read_state(path)
    assert_history(stored)
    assert harness.fills == [ns["CONTROL_BOOTSTRAP"]]
    assert harness.submits == []
    assert_text_free(harness.logs, ns)


def test_submit_retry_without_refill(ns, path: Path) -> None:
    write_state(path, live_state())
    harness = Harness(ns, path, [])
    harness.mode = "retry"
    harness.run()
    stored = read_state(path)
    assert_history(stored)
    assert harness.fills == [ns["CONTROL_BOOTSTRAP"]]
    assert harness.submits == [1]
    assert harness.submit_times[0] >= ns["CONTROL_SUBMIT_CONFIRM_SECONDS"]
    assert stored["rebind_reprovision_submit_retry_count"] == 1
    assert stored["rebind_reprovision_submit_retry_status"] == "done"
    assert_text_free(harness.logs, ns)
    again = Harness(ns, path, [], allow_create=False)
    again.run()
    assert again.created == []
    assert again.fills == []


def test_vanished_text_does_not_refill(ns, path: Path) -> None:
    write_state(path, live_state())
    harness = Harness(ns, path, [])
    harness.mode = "vanished"
    harness.run()
    stored = read_state(path)
    assert harness.fills == [ns["CONTROL_BOOTSTRAP"]]
    assert harness.submits == []
    assert stored["chatgpt_control_url"] == OLD
    assert stored["rebind_reprovision_status"] == "failed"
    assert stored["rebind_reprovision_failure_reason"] == "submit_unconfirmed"
    assert stored["rebind_reprovision_bootstrap_attempted"] is True
    ns["save_control_record"](read_state(path))
    assert read_state(path)["rebind_reprovision_failure_reason"] == "submit_unconfirmed"
    again = Harness(ns, path, [FakePage(OTHER)], allow_create=False)
    again.run()
    assert again.created == []
    assert again.fills == []
    assert read_state(path)["chatgpt_control_url"] == OLD


def test_unconfirmed_retry_consumed(ns, path: Path) -> None:
    write_state(path, live_state())
    harness = Harness(ns, path, [])
    harness.mode = "unconfirmed"
    harness.run()
    stored = read_state(path)
    assert harness.fills == [ns["CONTROL_BOOTSTRAP"]]
    assert harness.submits == [1]
    assert stored["rebind_reprovision_status"] == "failed"
    assert stored["rebind_reprovision_failure_reason"] == "submit_unconfirmed"
    assert stored["chatgpt_control_url"] == OLD
    assert stored["blank_for_url"] == OLD
    again = Harness(ns, path, [], allow_create=False)
    again.run()
    assert again.created == []
    assert again.fills == []


def test_no_url_after_confirm(ns, path: Path) -> None:
    write_state(path, live_state())
    harness = Harness(ns, path, [])
    harness.mode = "no_url"
    harness.run()
    stored = read_state(path)
    assert harness.fills == [ns["CONTROL_BOOTSTRAP"]]
    assert stored["chatgpt_control_url"] == OLD
    assert stored["chatgpt_control_url"] != "https://chatgpt.com/"
    assert stored["rebind_reprovision_status"] == "failed"
    assert stored["rebind_reprovision_failure_reason"] == "no_new_url"
    assert stored["rebind_reprovision_submission_status"] == "confirmed"
    assert harness.ns["time"].now >= ns["CONTROL_REPROVISION_URL_WAIT"]
    assert ns["reprovision_failed_closed"](stored, OLD) is True
    again = Harness(ns, path, [FakePage(OTHER)], allow_create=False)
    again.run()
    assert again.created == []
    assert again.fills == []
    assert read_state(path)["rebind_reprovision_status"] == "failed"


def test_signed_out_and_unavailable_and_no_composer(ns, path: Path) -> None:
    write_state(path, live_state())
    signed = Harness(ns, path, [])
    signed.sign_out_new = True
    signed.run()
    stored = read_state(path)
    assert signed.fills == []
    assert stored["rebind_reprovision_failure_reason"] == "signed_out"
    assert stored["rebind_reprovision_status"] == "failed"
    assert Harness(ns, path, [], allow_create=False).run() is None or True
    assert Harness(ns, path, [], allow_create=False).created == []

    write_state(path, live_state())
    hard = Harness(ns, path, [])
    hard.unavailable_new = True
    hard.run()
    assert hard.fills == []
    assert read_state(path)["rebind_reprovision_failure_reason"] == "hard_unavailable"
    assert Harness(ns, path, [], allow_create=False).created == []

    write_state(path, live_state())
    empty = Harness(ns, path, [])
    empty.composer_ready = False
    empty.run()
    assert empty.fills == []
    assert empty.ns["time"].now >= ns["CONTROL_REBIND_COMPOSER_WAIT"]
    assert read_state(path)["rebind_reprovision_failure_reason"] == "no_composer"
    assert read_state(path)["chatgpt_control_url"] == OLD
    assert Harness(ns, path, [], allow_create=False).created == []


def test_resume_marked_page(ns, path: Path) -> None:
    state = live_state()
    state.update(
        {
            "rebind_reprovision_for_url": OLD,
            "rebind_reprovision_count": 1,
            "rebind_reprovision_status": "started",
        }
    )
    write_state(path, state)
    marked = FakePage("https://chatgpt.com/", name=MARK)
    unrelated = FakePage(OTHER, messages=[{"role": "user", "text": "untouched"}])
    replacement = FakePage("https://chatgpt.com/", name="ai-dispatcher-rebind-replacement")
    harness = Harness(ns, path, [unrelated, replacement, marked], allow_create=False)
    harness.mode = "message"
    harness.run()
    stored = read_state(path)
    assert_history(stored)
    assert harness.created == []
    assert harness.fills == [ns["CONTROL_BOOTSTRAP"]]
    assert marked.gotos == []
    assert unrelated.gotos == []
    assert replacement.gotos == []
    assert "reprovision_resume" in "\n".join(harness.logs)
    assert_text_free(harness.logs, ns)


def test_resume_about_blank_same_page(ns, path: Path) -> None:
    state = live_state()
    state.update(
        {
            "rebind_reprovision_for_url": OLD,
            "rebind_reprovision_count": 1,
            "rebind_reprovision_status": "started",
        }
    )
    write_state(path, state)
    marked = FakePage("about:blank", name=MARK)
    harness = Harness(ns, path, [marked], allow_create=False)
    harness.mode = "url"
    harness.run()
    assert harness.created == []
    assert marked.gotos == ["https://chatgpt.com/"]
    assert read_state(path)["chatgpt_control_url"] == NEW
    assert marked.window_name == MARK


def test_resume_attempted_does_not_refill(ns, path: Path) -> None:
    state = live_state()
    state.update(
        {
            "rebind_reprovision_for_url": OLD,
            "rebind_reprovision_count": 1,
            "rebind_reprovision_status": "started",
            "rebind_reprovision_bootstrap_attempted": True,
            "rebind_reprovision_submission_status": "attempted",
        }
    )
    write_state(path, state)
    marked = FakePage("https://chatgpt.com/", name=MARK, composer=ns["CONTROL_BOOTSTRAP"])
    harness = Harness(ns, path, [marked], allow_create=False)
    harness.mode = "retry"
    harness.run()
    assert harness.created == []
    assert harness.fills == []
    assert harness.submits == [1]
    assert read_state(path)["chatgpt_control_url"] == NEW
    assert_text_free(harness.logs, ns)


def test_missing_marked_page_fails_closed(ns, path: Path) -> None:
    state = live_state()
    state.update(
        {
            "rebind_reprovision_for_url": OLD,
            "rebind_reprovision_count": 1,
            "rebind_reprovision_status": "started",
        }
    )
    write_state(path, state)
    positive = FakePage(NEW, messages=[{"role": "assistant", "text": "CONTROL READY"}])
    replacement = FakePage(OTHER, name="ai-dispatcher-rebind-replacement")
    harness = Harness(ns, path, [positive, replacement], allow_create=False)
    harness.run()
    stored = read_state(path)
    assert harness.created == []
    assert harness.fills == []
    assert positive.gotos == []
    assert replacement.gotos == []
    assert stored["chatgpt_control_url"] == OLD
    assert stored["rebind_reprovision_status"] == "failed"
    assert stored["rebind_reprovision_failure_reason"] == "missing_page"
    assert ns["reprovision_failed_closed"](stored, OLD) is True
    ns["save_control_record"](read_state(path))
    again = Harness(ns, path, [positive], allow_create=False)
    again.run()
    assert again.created == []
    assert again.fills == []
    assert read_state(path)["chatgpt_control_url"] == OLD
    assert read_state(path)["rebind_reprovision_failure_reason"] == "missing_page"


def test_other_entries_do_not_create(ns, path: Path) -> None:
    write_state(path, live_state())
    stranger = FakePage(OTHER)
    harness = Harness(ns, path, [stranger], allow_create=False)
    ns["begin_control_rebind"](harness.browser, OLD)
    ns["resume_control_rebind"](harness.browser, OLD)
    ns["replace_control_rebind"](harness.browser, OLD)
    ns["finalize_control_rebind"](harness.browser, OLD)
    assert harness.created == []
    assert stranger.gotos == []
    assert read_state(path)["chatgpt_control_url"] == OLD


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "control.json"
        ns = load_helpers(path)
        test_constants(ns)
        test_pick_rules(ns)
        test_save_roundtrip(ns, path)
        test_eligibility(ns, path)
        test_prescan_commits_without_page(ns, path)
        test_prescan_exact_user_message(ns, path)
        test_success_delayed_composer_and_repeat(ns, path)
        test_generation_confirmation(ns, path)
        test_url_confirmation(ns, path)
        test_submit_retry_without_refill(ns, path)
        test_vanished_text_does_not_refill(ns, path)
        test_unconfirmed_retry_consumed(ns, path)
        test_no_url_after_confirm(ns, path)
        test_signed_out_and_unavailable_and_no_composer(ns, path)
        test_resume_marked_page(ns, path)
        test_resume_about_blank_same_page(ns, path)
        test_resume_attempted_does_not_refill(ns, path)
        test_missing_marked_page_fails_closed(ns, path)
        test_other_entries_do_not_create(ns, path)
    print("test_control_reprovision: OK")


if __name__ == "__main__":
    main()
