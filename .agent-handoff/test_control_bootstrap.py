"""Decision tests for Dispatcher control-chat bootstrap. No Playwright required."""
from __future__ import annotations

import ast
import subprocess
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
    "conversation_identity",
    "same_conversation",
    "_last_bootstrap_index",
    "is_usable_control_url",
    "infer_turn_role",
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
    "normalize_conversation_url",
    "positive_control_identity",
    "canonicalization_eligible",
    "submitted_bootstrap_idle_ready",
    "canonicalize_control_url",
    "hard_unavailable_text",
    "hard_control_unavailable",
    "rebind_target",
    "rebind_bound",
    "rebind_completed",
    "rebind_cooldown_active",
    "rebind_allowed",
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
                "INFER_TURN_ROLE_JS",
                "TURN_SELECTOR",
                "CONTROL_RECOVERY_CHECKS",
                "CONTROL_READY_GRACE_SECONDS",
                "CONTROL_ERROR_MARKERS",
                "CONTROL_UNAVAILABLE_MARKERS",
                "CONTROL_REBIND_COOLDOWN_SECONDS",
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
    assert version_of(CORE) == "2.2.13"
    assert version_of(RUNTIME) == "2.2.13"
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
        assert saved["dispatcher_version"] == "2.2.13"

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

        web = "https://chatgpt.com/c/WEB:54f304f1-2f88-4e38-a4ff-b566975e3d41"
        web_record = {
            "chatgpt_control_url": web,
            "bootstrap_sent": True,
            "bootstrap_migrated_from": "2.2.5",
        }
        assert ns["is_usable_control_url"](web) is True
        assert ns["diagnose_control"](web_record, []) == "zero_messages"
        assert ns["diagnose_control"](web_record, [], page_url=web) == "zero_messages"
        assert ns["next_control_action"](web_record, [], checks=0) == "wait"
        assert ns["next_control_action"](web_record, [], checks=3) == "recover"
        home = "https://chatgpt.com/"
        assert ns["diagnose_control"](web_record, [], page_url=home) == "stale_url"
        assert ns["next_control_action"](web_record, [], page_url=home, checks=0) == "recover"
        web_done = dict(web_record)
        web_done["recovery_used"] = True
        assert ns["next_control_action"](web_done, [], page_url=home, checks=9) == "wait"
        assert ns["control_bootstrap_decision"](web_done, []) != "send"

        latch = Path(tmp) / "latch.json"
        ns["CONTROL_PATH"] = latch
        latch.write_text(json.dumps({
            "chatgpt_control_url": web,
            "bootstrap_sent": True,
            "recovery_used": True,
            "recovery_reason": "stale_url",
            "recovered_from": web,
            "unready_checks": 3,
        }), encoding="utf-8")
        ns["save_control_url"](url, bootstrap_sent=True)
        replaced = json.loads(latch.read_text(encoding="utf-8"))
        assert replaced["chatgpt_control_url"] == url
        assert replaced["recovery_used"] is True
        assert replaced["recovery_reason"] == "stale_url"
        assert replaced["recovered_from"] == web

        assert ns["infer_turn_role"]("assistant", "") == "assistant"
        assert ns["infer_turn_role"]("user", "") == "user"
        assert ns["infer_turn_role"]("", "You said:") == "user"
        assert ns["infer_turn_role"]("", "Вы сказали:") == "user"
        assert ns["infer_turn_role"]("", "ChatGPT said:") == "assistant"
        assert ns["infer_turn_role"]("conversation-turn-3", "ChatGPT") == ""
        assert "conversation-turn-" in ns["TURN_SELECTOR"]
        assert "[data-testid='conversation-turn']" not in ns["TURN_SELECTOR"]
        script = ns["INFER_TURN_ROLE_JS"] + """
const cases = [
  [['assistant', ''], 'assistant'],
  [['user', ''], 'user'],
  [['', 'You said:'], 'user'],
  [['', 'Вы сказали:'], 'user'],
  [['', 'ChatGPT said:'], 'assistant'],
  [['conversation-turn-3', 'ChatGPT'], '']
];
for (const [args, expected] of cases) {
  const got = inferTurnRole(args[0], args[1]);
  if (got !== expected) {
    console.error(JSON.stringify({args, expected, got}));
    process.exit(1);
  }
}
console.log('inferTurnRole: OK');
"""
        proc = subprocess.run(["node", "-e", script], check=True, capture_output=True, text=True)
        assert proc.stdout.strip() == "inferTurnRole: OK"

        alias = "https://chatgpt.com/c/WEB:4f943fa5-39fa-4b25-95f8-e06ea1ffabed"
        observed = "https://chatgpt.com/c/4f943fa5-39fa-4b25-95f8-e06ea1ffabed"
        boot_msgs = [{"role": "user", "text": bootstrap}]
        alias_record = {
            "chatgpt_control_url": alias,
            "bootstrap_sent": True,
            "bootstrap_sent_at": 1000.0,
            "recovery_used": True,
            "recovery_reason": "stale_url",
            "recovered_from": web,
            "unready_checks": 3,
        }
        assert ns["canonicalization_eligible"](alias_record, boot_msgs, observed) is True
        assert ns["canonicalization_eligible"](alias_record, [], observed) is True
        other = "https://chatgpt.com/c/11111111-1111-1111-1111-111111111111"
        assert ns["same_conversation"](alias, observed) is True
        assert ns["same_conversation"](alias, other) is False
        assert ns["canonicalization_eligible"](alias_record, [], other) is False
        assert ns["diagnose_control"](alias_record, [], page_url=observed) == "zero_messages"
        assert ns["next_control_action"](alias_record, [], observed, checks=9) == "wait"
        assert ns["canonicalization_eligible"](alias_record, boot_msgs, "https://chatgpt.com/") is False
        assert ns["canonicalization_eligible"](alias_record, boot_msgs, alias) is False
        ready_msgs = [{"role": "assistant", "text": ready}]
        assert ns["canonicalization_eligible"](alias_record, ready_msgs, observed) is True
        wake = "Проверь GitHub. turn_id=33"
        wake_msgs = [{"role": "user", "text": wake}]
        assert ns["canonicalization_eligible"](alias_record, wake_msgs, observed, wake) is True
        assert ns["diagnose_control"](alias_record, boot_msgs, page_url=observed) != "stale_url"
        assert ns["next_control_action"](alias_record, boot_msgs, observed, checks=9) != "recover"
        assert ns["next_control_action"](alias_record, boot_msgs, observed, checks=9) != "send"
        fresh = dict(alias_record)
        fresh["recovery_used"] = False
        assert ns["next_control_action"](fresh, boot_msgs, observed, checks=9) == "wait"

        grace = ns["CONTROL_READY_GRACE_SECONDS"]
        assert ns["submitted_bootstrap_idle_ready"](alias_record, False, True, now=1000 + grace) is True
        assert ns["submitted_bootstrap_idle_ready"](alias_record, True, True, now=1000 + grace) is False
        assert ns["submitted_bootstrap_idle_ready"](alias_record, False, False, now=1000 + grace) is False
        assert ns["submitted_bootstrap_idle_ready"](alias_record, False, True, now=1000 + grace - 1) is False
        assert ns["submitted_bootstrap_idle_ready"]({}, False, True, now=1000 + grace) is False
        assert ns["next_control_action"](
            alias_record, boot_msgs, alias, generation_active=False, composer_ready=True, now=1000 + grace
        ) == "ready"
        assert ns["diagnose_control"](
            alias_record, boot_msgs, alias, generation_active=True, composer_ready=True, now=1000 + grace
        ) == "bootstrap_without_response"
        assert ns["next_control_action"](
            alias_record, boot_msgs, alias, generation_active=True, composer_ready=True, now=1000 + grace
        ) == "wait"
        inflight = {"send_attempts": 0, "retry_after": 0, "wake_seen": False}
        assert ns["pending_wake_action"]("ready", inflight, now=10) == "send_wake"
        inflight["wake_seen"] = True
        assert ns["pending_wake_action"]("ready", inflight, now=10) == "already_sent"

        canon = Path(tmp) / "canon.json"
        ns["CONTROL_PATH"] = canon
        canon.write_text(json.dumps(alias_record), encoding="utf-8")
        ns["canonicalize_control_url"](observed + "?ref=1")
        stored = json.loads(canon.read_text(encoding="utf-8"))
        assert stored["chatgpt_control_url"] == observed
        assert stored["recovery_used"] is True
        assert stored["recovery_reason"] == "stale_url"
        assert stored["recovered_from"] == web
        assert stored["bootstrap_sent_at"] == 1000.0
        assert stored["bootstrap_sent"] is True

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
