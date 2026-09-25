"""Focused regressions for current ChatGPT CONTROL UI behavior. No network."""
from __future__ import annotations

import ast
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
    "infer_turn_role",
    "_normalize_message",
    "_read_message_nodes",
    "_read_turn_nodes",
    "_read_accessible_turn_nodes",
    "chatgpt_messages",
    "assistant_has_control_ready",
    "user_has_bootstrap_marker",
    "hard_unavailable_text",
    "hard_control_unavailable",
    "page_shows_unavailable",
    "diagnose_control",
    "positive_control_identity",
    "restore_observation_accepted",
    "_preferred_index",
    "plan_control_page",
    "pending_wake_action",
}


def helpers():
    tree = ast.parse(CORE.read_text(encoding="utf-8"))
    keep = []
    constants = {
        "CONTROL_READY_MARKER",
        "CONTROL_BOOTSTRAP_MARKER",
        "CONTROL_ERROR_MARKERS",
        "CONTROL_UNAVAILABLE_MARKERS",
        "CONTROL_PAGE_UNAVAILABLE_MARKERS",
        "INFER_TURN_ROLE_JS",
        "TURN_SELECTOR",
        "ACCESSIBLE_TURN_HEADING_SELECTOR",
    }
    for node in tree.body:
        if isinstance(node, ast.Assign):
            names = [target.id for target in node.targets if isinstance(target, ast.Name)]
            if names and names[0] in constants:
                keep.append(node)
        elif isinstance(node, ast.FunctionDef) and node.name in WANTED:
            keep.append(node)
    ns = {"log": lambda _message: None}
    exec(compile(ast.Module(keep, []), str(CORE), "exec"), ns)
    return ns


class EmptyLocator:
    def evaluate_all(self, _script):
        return []


class AccessibleOnlyPage:
    """No data-message attributes or turn test ids; only sr-heading semantics."""

    def locator(self, _selector):
        return EmptyLocator()

    def evaluate(self, script):
        assert "h1, h2, h3, h4, h5, h6" in script
        return [
            {"role": "user", "text": "Служебный чат 01 — CONTROL & BRIDGE."},
            {"role": "assistant", "text": "CONTROL READY"},
            {"role": "user", "text": "Проверь GitHub. turn_id=57"},
        ]


class TailDeletedPage:
    def evaluate(self, _script):
        return "cached transcript\n" + ("x" * 7000) + "\nЧат был удален. Начните новый чат."


class BodyPage:
    def __init__(self, text):
        self.text = text

    def evaluate(self, _script):
        return self.text


def main() -> None:
    ns = helpers()
    old = "https://chatgpt.com/c/WEB:4f943fa5-39fa-4b25-95f8-e06ea1ffabed"
    canonical = "https://chatgpt.com/c/4f943fa5-39fa-4b25-95f8-e06ea1ffabed"
    local = "https://chatgpt.com/c/local-chatgpt:temporary-57"
    deleted = "Чат был удален. Начните новый чат."

    # Current DOM can expose only screen-reader headings like `Вы сказали:`
    # and `ChatGPT сказал:`. The fallback reaches a complete CONTROL transcript.
    messages = ns["chatgpt_messages"](AccessibleOnlyPage())
    assert [item["role"] for item in messages] == ["user", "assistant", "user"]
    assert ns["assistant_has_control_ready"](messages) is True
    assert messages[-1]["text"].endswith("turn_id=57")

    assert ns["hard_unavailable_text"]("cached transcript\n" + deleted) is True
    assert ns["page_shows_unavailable"](TailDeletedPage()) is True
    assert ns["page_shows_unavailable"](
        BodyPage("Не удалось загрузить историю")
    ) is False
    assert ns["page_shows_unavailable"](
        BodyPage("Unable to load history")
    ) is False
    assert ns["page_shows_unavailable"](
        BodyPage("Чат был удален")
    ) is True
    assert ns["page_shows_unavailable"](
        BodyPage("Chat was deleted")
    ) is True
    ready_then_deleted = [
        {"role": "assistant", "text": "CONTROL READY"},
        {"role": "user", "text": deleted},
    ]
    assert ns["diagnose_control"](
        {"chatgpt_control_url": old}, ready_then_deleted, page_unavailable=True
    ) == "unavailable"

    # A blank alias / transient local URL is not a successful restore.
    assert ns["restore_observation_accepted"](old, canonical, [], False) is False
    assert ns["restore_observation_accepted"](old, local, messages, True) is False
    assert ns["is_provisional_control_url"](local) is True
    assert ns["is_durable_control_url"](local) is False

    # Identity never resurrects a page whose current body says it was deleted.
    pages = [
        {"url": old, "messages": messages, "unavailable": True, "foreground": True},
        {"url": canonical, "messages": messages, "unavailable": False},
    ]
    plan = ns["plan_control_page"](pages, old, "Проверь GitHub. turn_id=57")
    assert plan == {"action": "use", "index": 1, "url": canonical, "reason": "equivalent"}

    # Pending 57 remains held until readiness and cannot be sent twice.
    inflight = {"wake_seen": True}
    assert ns["pending_wake_action"]("ready", inflight) == "already_sent"
    assert ns["pending_wake_action"]("wait", {"wake_seen": False}) == "hold"

    print("test_control_live_regressions: OK")


if __name__ == "__main__":
    main()
