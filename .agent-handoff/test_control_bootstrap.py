"""Decision tests for Dispatcher control-chat bootstrap. No Playwright required."""
from __future__ import annotations

import ast
import json
import os
import tempfile
import time
from pathlib import Path

CORE = Path(__file__).with_name("dispatcher.py")
RUNTIME = Path(__file__).with_name("dispatcher-runtime.py")

WANTED = {
    "is_chatgpt_conversation_url",
    "assistant_has_control_ready",
    "user_has_bootstrap_marker",
    "bootstrap_was_sent",
    "control_bootstrap_decision",
    "load_control_record",
    "save_control_record",
    "save_control_url",
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
                "CONTROL_BOOTSTRAP",
            }:
                keep.append(node)
        elif isinstance(node, ast.FunctionDef) and node.name in WANTED:
            keep.append(node)
    ns = {
        "json": json,
        "os": os,
        "time": time,
        "log": lambda message: None,
        "CONTROL_PATH": control_path,
    }
    exec(compile(ast.Module(keep, []), str(CORE), "exec"), ns)
    return ns


def version_of(path: Path) -> str:
    for node in ast.parse(path.read_text(encoding="utf-8")).body:
        if isinstance(node, ast.Assign):
            names = [t.id for t in node.targets if isinstance(t, ast.Name)]
            if names == ["VERSION"]:
                return ast.literal_eval(node.value)
    raise AssertionError(f"VERSION missing in {path}")


def main() -> None:
    assert version_of(CORE) == "2.2.6"
    assert version_of(RUNTIME) == "2.2.6"
    source = CORE.read_text(encoding="utf-8")
    assert "CONTROL_BOOTSTRAP_WAIT" not in source
    assert "time.sleep(1)" not in source

    url = "https://chatgpt.com/c/6ab457e5-237c-83eb-a463-df52d23fd58f"
    with tempfile.TemporaryDirectory() as tmp:
        ns = load_helpers(Path(tmp) / "control.json")
        marker = ns["CONTROL_BOOTSTRAP_MARKER"]
        ready = ns["CONTROL_READY_MARKER"]
        bootstrap = ns["CONTROL_BOOTSTRAP"]
        assert bootstrap.startswith(marker)
        assert ready in bootstrap

        legacy = {"chatgpt_control_url": url, "dispatcher_version": "2.2.5"}
        assert ns["bootstrap_was_sent"](legacy) is True
        assert ns["control_bootstrap_decision"](legacy, []) == "wait"

        explicit_false = {"chatgpt_control_url": url, "bootstrap_sent": False}
        assert ns["control_bootstrap_decision"](explicit_false, []) == "send"

        truncated = [{"role": "user", "text": marker + " …truncated"}]
        assert ns["user_has_bootstrap_marker"](truncated) is True
        assert ns["control_bootstrap_decision"]({}, truncated) == "wait"

        quoted = [{"role": "user", "text": bootstrap}]
        assert ns["assistant_has_control_ready"](quoted) is False
        assert ns["control_bootstrap_decision"]({}, quoted) == "wait"

        assistant = [
            {"role": "user", "text": "unrelated wake"},
            {"role": "assistant", "text": "CONTROL READY"},
        ]
        assert ns["control_bootstrap_decision"](legacy, assistant) == "ready"

        ns["save_control_url"](url, bootstrap_sent=True)
        saved = json.loads((Path(tmp) / "control.json").read_text(encoding="utf-8"))
        assert saved["bootstrap_sent"] is True
        assert saved["dispatcher_version"] == "2.2.6"

        legacy_path = Path(tmp) / "control.json"
        legacy_path.write_text(
            json.dumps({"chatgpt_control_url": url, "dispatcher_version": "2.2.5"}),
            encoding="utf-8",
        )
        loaded = ns["load_control_record"]()
        assert loaded["bootstrap_sent"] is True
        assert loaded["bootstrap_migrated_from"] == "2.2.5"
        persisted = json.loads(legacy_path.read_text(encoding="utf-8"))
        assert persisted["bootstrap_sent"] is True

    print("test_control_bootstrap: OK")


if __name__ == "__main__":
    main()
