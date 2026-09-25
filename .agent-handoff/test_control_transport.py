"""Fail-closed CONTROL routing tests. No network and no Playwright."""
from __future__ import annotations

import ast
import json
from pathlib import Path

CORE = Path(__file__).with_name("dispatcher.py")


def load_helpers():
    tree = ast.parse(CORE.read_text(encoding="utf-8"))
    keep = []
    for node in tree.body:
        if isinstance(node, ast.Assign):
            names = [target.id for target in node.targets if isinstance(target, ast.Name)]
            if names and names[0] in {"VERSION", "CONTROL_BOOTSTRAP"}:
                keep.append(node)
        elif isinstance(node, ast.ClassDef) and node.name == "GitHubSignalError":
            keep.append(node)
        elif isinstance(node, ast.FunctionDef) and node.name in {"parse_signal", "wake_text", "create_inflight"}:
            keep.append(node)
    ns = {"time": __import__("time"), "save_state": lambda _state: None}
    exec(compile(ast.Module(keep, []), str(CORE), "exec"), ns)
    return ns


def signal(**overrides):
    data = {
        "protocol": 1,
        "turn_id": 58,
        "target": "GPT",
        "source": "ARENA",
        "status": "ready",
        "message": "transport only",
    }
    data.update(overrides)
    return data


def main() -> None:
    ns = load_helpers()
    assert ns["VERSION"] == "2.2.19"
    bootstrap = ns["CONTROL_BOOTSTRAP"]
    assert "ChatGPT" in bootstrap
    assert "Codex/Work" in bootstrap
    assert "requires_codex=true" in bootstrap

    default = ns["parse_signal"](signal())
    assert default["requires_codex"] is False
    authorized = ns["parse_signal"](signal(requires_codex=True))
    state = {}
    inflight = ns["create_inflight"](state, authorized)
    assert inflight["requires_codex"] is True
    assert inflight["wake"] == "Проверь GitHub. turn_id=58"
    assert state["inflight"] is inflight

    for invalid in ("false", 0, [], {}):
        try:
            ns["parse_signal"](signal(requires_codex=invalid))
        except ns["GitHubSignalError"] as exc:
            assert str(exc) == "requires_codex_invalid"
        else:
            raise AssertionError(f"requires_codex={invalid!r} was accepted")

    protocol = Path(__file__).with_name("PROTOCOL.md").read_text(encoding="utf-8")
    assert '"requires_codex": false' in protocol
    assert "sole authorization" in protocol
    assert "dispatcher itself never opens Codex/Work" in protocol
    print("test_control_transport: OK")


if __name__ == "__main__":
    main()
