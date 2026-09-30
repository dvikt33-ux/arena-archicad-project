"""Regression tests for reading the current ChatGPT conversation DOM."""
from __future__ import annotations

import ast
from pathlib import Path

CORE = Path(__file__).with_name("dispatcher.py")


def load_helpers():
    tree = ast.parse(CORE.read_text(encoding="utf-8"))
    wanted = {
        "CONTROL_READY_MARKER",
        "INFER_TURN_ROLE_JS", "TURN_SELECTOR", "infer_turn_role",
        "_read_message_nodes", "_read_turn_nodes", "_normalize_message",
        "chatgpt_messages", "chatgpt_user_message_exists",
        "assistant_has_control_ready",
    }
    nodes = []
    for node in tree.body:
        if isinstance(node, ast.Assign):
            names = {t.id for t in node.targets if isinstance(t, ast.Name)}
            if names & wanted:
                nodes.append(node)
        elif isinstance(node, ast.FunctionDef) and node.name in wanted:
            nodes.append(node)
    ns = {}
    exec(compile(ast.Module(nodes, []), str(CORE), "exec"), ns)
    return ns


class _Locator:
    def __init__(self, values):
        self.values = values

    def evaluate_all(self, _script):
        return self.values


class _Page:
    def __init__(self, primary, turns):
        self.primary = primary
        self.turns = turns

    def locator(self, selector):
        if selector == "[data-message-author-role]":
            return _Locator(self.primary)
        return _Locator(self.turns)


def test_current_turn_container_form_is_parsed():
    ns = load_helpers()
    page = _Page(
        [],
        [
            {"role": "user", "text": "Bootstrap: CONTROL READY"},
            {"role": "assistant", "text": "CONTROL READY"},
            {"role": "user", "text": "wake-57"},
        ],
    )
    assert ns["chatgpt_messages"](page) == page.turns
    assert ns["chatgpt_user_message_exists"](page, "wake-57") is True
    assert "[data-testid^='conversation-turn-']" in ns["TURN_SELECTOR"]


def test_composer_without_messages_stays_empty():
    ns = load_helpers()
    assert ns["chatgpt_messages"](_Page([], [])) == []


def test_control_ready_requires_assistant_role_after_bootstrap():
    ns = load_helpers()
    source = CORE.read_text(encoding="utf-8")
    assert "def assistant_has_control_ready" in source
    assistant_ready = [
        {"role": "user", "text": "Bootstrap: CONTROL READY"},
        {"role": "assistant", "text": "CONTROL READY"},
    ]
    quoted_ready = [
        {"role": "user", "text": "Bootstrap: CONTROL READY"},
        {"role": "user", "text": "CONTROL READY"},
    ]
    assert ns["assistant_has_control_ready"](assistant_ready) is True
    assert ns["assistant_has_control_ready"](quoted_ready) is False


def test_wake_user_message_is_found_exactly():
    ns = load_helpers()
    page = _Page([], [{"role": "user", "text": "wake-57"}])
    assert ns["chatgpt_user_message_exists"](page, "wake-57") is True
    assert ns["chatgpt_user_message_exists"](page, "wake-58") is False
