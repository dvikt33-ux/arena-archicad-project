"""Persistent blank-control evidence tests. No Playwright and no network."""
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
    "normalize_conversation_url",
    "url_matches",
    "assistant_has_control_ready",
    "user_has_bootstrap_marker",
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
    "blank_control_match",
    "apply_blank_observation",
    "blank_rebind_ready",
    "next_control_action",
    "positive_control_identity",
    "canonicalization_eligible",
    "submitted_bootstrap_idle_ready",
    "_last_bootstrap_index",
    "assistant_after_bootstrap",
    "assistant_error_after_bootstrap",
    "bootstrap_was_sent",
    "save_control_record",
    "commit_rebind",
    "_read_control_file",
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
                "CONTROL_ERROR_MARKERS",
                "CONTROL_UNAVAILABLE_MARKERS",
                "BLANK_REBIND_POLLS",
                "BLANK_REBIND_SECONDS",
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


def observe(ns, record, saved, page, blank, now):
    return ns["apply_blank_observation"](record, saved, blank, now)


def main() -> None:
    saved = "https://chatgpt.com/c/WEB:4f943fa5-39fa-4b25-95f8-e06ea1ffabed"
    canonical = "https://chatgpt.com/c/4f943fa5-39fa-4b25-95f8-e06ea1ffabed"
    other = "https://chatgpt.com/c/11111111-1111-1111-1111-111111111111"
    with tempfile.TemporaryDirectory() as tmp:
        ns = load_helpers(Path(tmp) / "control.json")
        assert ns["VERSION"] == "2.2.18"
        assert ns["CHECK_INTERVAL"] == 5
        polls = ns["BLANK_REBIND_POLLS"]
        seconds = ns["BLANK_REBIND_SECONDS"]
        assert polls >= 3
        assert seconds >= 30

        record = {
            "chatgpt_control_url": saved,
            "bootstrap_sent": True,
            "bootstrap_sent_at": 1000.0,
            "recovery_used": True,
            "recovery_reason": "stale_url",
            "recovered_from": "https://chatgpt.com/c/old",
            "unready_checks": 100,
        }
        assert ns["blank_control_match"](record, canonical, [], False, False, False, False) is True
        assert ns["blank_control_match"](record, canonical, [], True, False, False, False) is False
        assert ns["blank_control_match"](record, canonical, [{"role": "user", "text": "x"}], False, False, False, False) is False
        assert ns["blank_control_match"](record, other, [], False, False, False, False) is False
        assert ns["blank_control_match"](record, canonical, [], False, False, True, False) is False
        assert ns["blank_rebind_ready"](record, saved, 5000) is False
        assert ns["next_control_action"](record, [], canonical, checks=100, now=5000) == "wait"

        state = dict(record)
        start = 10000.0
        state = observe(ns, state, saved, canonical, True, start)
        assert state["blank_checks"] == 1
        assert ns["blank_rebind_ready"](state, saved, start) is False
        assert ns["next_control_action"](state, [], canonical, now=start, blank_rebind=False) == "wait"
        state = observe(ns, state, saved, canonical, True, start + 5)
        assert state["blank_checks"] == 2
        assert ns["blank_rebind_ready"](state, saved, start + 5) is False

        for step in range(3, polls + 1):
            state = observe(ns, state, saved, canonical, True, start + step * 5)
        assert state["blank_checks"] == polls
        assert state["blank_for_url"] == saved
        assert ns["blank_rebind_ready"](state, saved, start + 10) is False
        assert ns["blank_rebind_ready"](state, saved, start + seconds) is True
        assert ns["next_control_action"](
            state, [], canonical, checks=100, now=start + seconds, blank_rebind=True
        ) == "rebind"

        changed = observe(ns, state, other, other, True, start + seconds + 5)
        assert changed["blank_for_url"] == other
        assert changed["blank_checks"] == 1
        assert ns["blank_rebind_ready"](changed, saved, start + seconds + 5) is False

        reset = observe(ns, state, saved, canonical, False, start + seconds + 5)
        assert "blank_for_url" not in reset
        assert "blank_checks" not in reset
        assert ns["blank_rebind_ready"](reset, saved, start + seconds + 5) is False

        failed = dict(state)
        failed.update({
            "rebind_for_url": saved,
            "rebind_count": 1,
            "rebind_status": "failed",
            "rebind_attempted_at": start,
        })
        assert ns["next_control_action"](
            failed, [], canonical, now=start + seconds, blank_rebind=True, page_unavailable=True
        ) == "wait"
        done = dict(failed)
        done["rebind_status"] = "done"
        assert ns["rebind_allowed"](done, saved, True, start + seconds) is False

        fresh = dict(record)
        assert ns["next_control_action"](fresh, [], canonical, page_unavailable=True, now=start) == "rebind"
        assert ns["diagnose_control"](fresh, [], page_unavailable=True) == "unavailable"
        assert ns["hard_unavailable_text"]("Не удалось загрузить этот разговор ChatGPT") is True

        path = Path(tmp) / "control.json"
        persisted = dict(record)
        persisted["blank_for_url"] = saved
        persisted["blank_checks"] = polls
        persisted["blank_since"] = start
        path.write_text(json.dumps(persisted), encoding="utf-8")
        ns["commit_rebind"](other, saved)
        stored = json.loads(path.read_text(encoding="utf-8"))
        assert stored["chatgpt_control_url"] == other
        assert stored["replaced_from"] == saved
        assert stored["recovery_used"] is True
        assert stored["recovery_reason"] == "stale_url"
        assert stored["recovered_from"] == "https://chatgpt.com/c/old"
        assert "blank_for_url" not in stored
        assert "blank_checks" not in stored
        assert stored["rebind_status"] == "done"

    print("test_control_blank: OK")


if __name__ == "__main__":
    main()
