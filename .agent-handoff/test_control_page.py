"""Pure control-page selection tests. No Playwright and no network."""
from __future__ import annotations

import ast
import json
from pathlib import Path

CORE = Path(__file__).with_name("dispatcher.py")

WANTED = {
    "is_chatgpt_conversation_url",
    "conversation_id",
    "conversation_identity",
    "same_conversation",
    "is_usable_control_url",
    "normalize_conversation_url",
    "assistant_has_control_ready",
    "user_has_bootstrap_marker",
    "positive_control_identity",
    "_preferred_index",
    "plan_control_page",
    "page_is_foreground",
    "find_control_page",
    "canonicalize_control_url",
    "save_control_record",
    "load_control_record",
    "_read_control_file",
    "note_restore_failure",
    "clear_restore_latch",
    "restore_candidates",
    "restore_observation_accepted",
    "restore_cooldown_active",
    "restore_page_action",
    "page_restore_mark",
    "mark_restore_page",
    "find_restore_page",
    "wait_for_restore_url",
    "_inspect_restore",
    "_observe_restore",
    "begin_control_restore",
    "all_pages",
    "composer_is_ready",
}


def load_helpers(control_path: Path):
    tree = ast.parse(CORE.read_text(encoding="utf-8"))
    keep = []
    for node in tree.body:
        if isinstance(node, ast.Assign):
            names = [t.id for t in node.targets if isinstance(t, ast.Name)]
            if names and names[0] in {
                "VERSION",
                "CONTROL_READY_MARKER",
                "CONTROL_BOOTSTRAP_MARKER",
                "PAGE_TIMEOUT",
                "CONTROL_RESTORE_WAIT_SECONDS",
                "CONTROL_RESTORE_COOLDOWN_SECONDS",
                "CONTROL_RESTORE_GOTO_TIMEOUT",
                "RESTORE_PAGE_MARK",
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
    def __init__(self, url: str, messages=None, foreground: bool = False):
        self.url = url
        self.messages = list(messages or [])
        self.foreground = foreground
        self.gotos: list[str] = []

    def evaluate(self, script: str, arg=None):
        if arg is not None:
            self.window_name = arg
            return None
        if script == "window.name":
            return getattr(self, "window_name", "")
        return "visible" if self.foreground else "hidden"

    def goto(self, url: str, **_kwargs) -> None:
        self.gotos.append(url)
        self.url = url


class FakeContext:
    def __init__(self):
        self.created: list[FakePage] = []
        self.pages = self.created

    def new_page(self) -> FakePage:
        page = FakePage("about:blank")
        self.created.append(page)
        return page


class FakeBrowser:
    def __init__(self, pages: list[FakePage]):
        self.pages = pages
        self.contexts = [FakeContext()]


def main() -> None:
    saved = "https://chatgpt.com/c/WEB:4f943fa5-39fa-4b25-95f8-e06ea1ffabed"
    canonical = "https://chatgpt.com/c/4f943fa5-39fa-4b25-95f8-e06ea1ffabed"
    other = "https://chatgpt.com/c/11111111-1111-1111-1111-111111111111"
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        ns = load_helpers(Path(tmp) / "control.json")
        assert ns["same_conversation"](saved, canonical) is True
        assert ns["same_conversation"](canonical + "?ref=1", saved) is True
        assert ns["same_conversation"](saved, other) is False
        assert ns["same_conversation"](
            "https://chatgpt.com/c/WEB:aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
            other,
        ) is False
        assert ns["conversation_identity"](saved) == ns["conversation_identity"](canonical)
        assert ns["conversation_id"](saved).startswith("WEB:")

        unrelated = {"url": other, "messages": [{"role": "user", "text": "ordinary chat"}]}
        open_canonical = {"url": canonical, "messages": [], "foreground": True}
        plan = ns["plan_control_page"]([unrelated, open_canonical], saved)
        assert plan["action"] == "use"
        assert plan["index"] == 1
        assert plan["reason"] == "equivalent"
        assert plan["url"] == canonical

        marker = ns["CONTROL_BOOTSTRAP_MARKER"]
        proven = {
            "url": other,
            "messages": [{"role": "user", "text": marker + " tail"}],
        }
        home = {"url": "https://chatgpt.com/", "messages": []}
        plan = ns["plan_control_page"]([unrelated, home, proven], saved, wake="Проверь GitHub. turn_id=37")
        assert plan["action"] == "use"
        assert plan["index"] == 2
        assert plan["reason"] == "identity"
        assert plan["url"] == other

        wake = "Проверь GitHub. turn_id=37"
        by_wake = {"url": other, "messages": [{"role": "user", "text": wake}]}
        plan = ns["plan_control_page"]([unrelated, by_wake], saved, wake=wake)
        assert plan["action"] == "use"
        assert plan["reason"] == "identity"
        assert plan["index"] == 1

        plan = ns["plan_control_page"]([unrelated, home], saved, wake=wake)
        assert plan["action"] == "goto"
        assert plan["index"] is None
        assert plan["url"] == saved

        canonical_page = FakePage(canonical)
        other_page = FakePage(other, messages=[{"role": "user", "text": "leave me"}])
        browser = FakeBrowser([other_page, canonical_page])
        real_canonicalize = ns["canonicalize_control_url"]
        ns["load_control_url"] = lambda: saved
        ns["chatgpt_pages"] = lambda _browser: browser.pages
        ns["chatgpt_messages"] = lambda page: page.messages
        saved_urls: list[str] = []
        ns["canonicalize_control_url"] = saved_urls.append
        ns["provision_control_chat"] = lambda _browser: (_ for _ in ()).throw(AssertionError("provisioned"))
        chosen = ns["find_control_page"](browser)
        assert chosen is canonical_page
        assert other_page.gotos == []
        assert canonical_page.gotos == []
        assert browser.contexts[0].created == []
        assert saved_urls == [canonical]

        identity_page = FakePage(other, messages=[{"role": "user", "text": marker}])
        stranger = FakePage("https://chatgpt.com/c/22222222-2222-2222-2222-222222222222")
        browser = FakeBrowser([stranger, identity_page])
        ns["chatgpt_pages"] = lambda _browser: browser.pages
        saved_urls.clear()
        chosen = ns["find_control_page"](browser, wake)
        assert chosen is identity_page
        assert stranger.gotos == []
        assert identity_page.gotos == []
        assert browser.contexts[0].created == []
        assert saved_urls == [other]

        browser = FakeBrowser([stranger])
        ns["chatgpt_pages"] = lambda _browser: browser.pages
        chosen = ns["find_control_page"](browser)
        assert chosen is browser.contexts[0].created[0]
        assert stranger.gotos == []
        assert chosen.gotos == [canonical]
        assert saved_urls[-1] == canonical

        record = {
            "chatgpt_control_url": saved,
            "bootstrap_sent": True,
            "bootstrap_sent_at": 1000.0,
            "recovery_used": True,
            "recovery_reason": "stale_url",
            "recovered_from": "https://chatgpt.com/c/old",
            "unready_checks": 2,
        }
        path = Path(tmp) / "control.json"
        ns["CONTROL_PATH"] = path
        path.write_text(json.dumps(record), encoding="utf-8")
        real_canonicalize(canonical + "#top")
        stored = json.loads(path.read_text(encoding="utf-8"))
        assert stored["chatgpt_control_url"] == canonical
        assert stored["bootstrap_sent_at"] == 1000.0
        assert stored["recovery_used"] is True
        assert stored["recovery_reason"] == "stale_url"
        assert stored["recovered_from"] == "https://chatgpt.com/c/old"
        assert stored["bootstrap_sent"] is True

    print("test_control_page: OK")


if __name__ == "__main__":
    main()
