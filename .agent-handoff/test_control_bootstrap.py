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
    "url_matches",
    "assistant_has_control_ready",
    "user_has_bootstrap_marker",
    "bootstrap_was_sent",
    "conversation_id",
    "_last_bootstrap_index",
    "is_usable_control_url",
    "assistant_after_bootstrap",
    "assistant_error_after_bootstrap",
    "diagnose_control",
    "control_is_ready",
    "recovery_allowed",
    "next_control_action",
    "control_bootstrap_decision",
    "pending_wake_action",
    "wake_attempt_count",
    "wake_send_allowed",
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
                "CONTROL_RECOVERY_CHECKS",
                "CONTROL_ERROR_MARKERS",
                "MAX_WAKE_ATTEMPTS",
                "WAKE_CONFIRM_SECONDS",
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
    assert version_of(CORE) == "2.2.7"
    assert version_of(RUNTIME) == "2.2.7"
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
        assert saved["dispatcher_version"] == "2.2.7"

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

        assert ns["next_control_action"](legacy, [], checks=0) == "wait"
        assert ns["next_control_action"](legacy, [], checks=2) == "wait"
        assert ns["next_control_action"](legacy, [], checks=3) == "recover"
        recovered = dict(legacy)
        recovered["bootstrap_sent"] = True
        recovered["recovery_used"] = True
        assert ns["next_control_action"](recovered, [], checks=9) == "wait"

        stale = {
            "chatgpt_control_url": "https://chatgpt.com/c/WEB:54f304f1-2f88-4e38-a4ff-b566975e3d41",
            "bootstrap_sent": True,
            "bootstrap_migrated_from": "2.2.5",
        }
        assert ns["is_usable_control_url"](stale["chatgpt_control_url"]) is False
        assert ns["diagnose_control"](stale, []) == "stale_url"
        assert ns["next_control_action"](stale, [], checks=0) == "recover"
        stale_done = dict(stale)
        stale_done["recovery_used"] = True
        assert ns["next_control_action"](stale_done, [], checks=0) == "wait"
        assert ns["control_bootstrap_decision"](stale_done, []) != "send"

        fallback = [
            {"role": "user", "text": marker + " init"},
            {"role": "assistant", "text": "Готово, канал открыт."},
        ]
        assert ns["diagnose_control"](legacy, fallback) == "ready_fallback"
        assert ns["next_control_action"](legacy, fallback) == "ready"

        errored = [
            {"role": "user", "text": marker + " init"},
            {"role": "assistant", "text": "Something went wrong"},
        ]
        assert ns["diagnose_control"](legacy, errored) == "assistant_error"
        assert ns["next_control_action"](legacy, errored, checks=0) == "wait"

        inflight = {"wake_seen": False, "send_attempts": 0, "retry_after": 0}
        assert ns["pending_wake_action"]("ready", inflight, 1000.0) == "send_wake"
        inflight["wake_seen"] = True
        assert ns["pending_wake_action"]("ready", inflight, 1000.0) == "already_sent"
        assert ns["pending_wake_action"]("wait", {"wake_seen": False, "send_attempts": 0}, 1000.0) == "hold"
        assert ns["pending_wake_action"]("recover", {"wake_seen": False, "send_attempts": 0}, 1000.0) == "hold"

    print("test_control_bootstrap: OK")


if __name__ == "__main__":
    main()
