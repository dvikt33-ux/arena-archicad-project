"""Pure control-restore tests. No Playwright and no network."""
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
    "assistant_has_control_ready",
    "user_has_bootstrap_marker",
    "positive_control_identity",
    "restore_candidates",
    "restore_observation_accepted",
    "restore_cooldown_active",
    "restore_page_action",
    "canonicalize_control_url",
    "save_control_record",
    "_read_control_file",
    "note_restore_failure",
    "clear_restore_latch",
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
                "CONTROL_RESTORE_WAIT_SECONDS",
                "CONTROL_RESTORE_COOLDOWN_SECONDS",
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


def main() -> None:
    web = "https://chatgpt.com/c/WEB:4f943fa5-39fa-4b25-95f8-e06ea1ffabed"
    canonical = "https://chatgpt.com/c/4f943fa5-39fa-4b25-95f8-e06ea1ffabed"
    normal = "https://chatgpt.com/c/6ab457e5-237c-83eb-a463-df52d23fd58f"
    other = "https://chatgpt.com/c/11111111-1111-1111-1111-111111111111"
    with tempfile.TemporaryDirectory() as tmp:
        ns = load_helpers(Path(tmp) / "control.json")
        assert ns["VERSION"] == "2.2.18"
        assert ns["CHECK_INTERVAL"] == 5
        assert ns["restore_candidates"](web) == [canonical, web]
        assert ns["restore_candidates"](normal) == [normal]
        assert ns["restore_candidates"](canonical) == [canonical]
        assert ns["restore_candidates"](web + "?ref=1") == [canonical, web]

        assert ns["restore_observation_accepted"](web, canonical, [], False) is True
        assert ns["restore_observation_accepted"](web, "https://chatgpt.com/", [], True) is False
        assert ns["restore_observation_accepted"](normal, normal, [], False) is True
        marker = ns["CONTROL_BOOTSTRAP_MARKER"]
        assert ns["restore_observation_accepted"](
            web,
            other,
            [{"role": "user", "text": marker}],
            False,
        ) is True

        record = {
            "chatgpt_control_url": web,
            "bootstrap_sent": True,
            "bootstrap_sent_at": 1000.0,
            "recovery_used": True,
            "recovery_reason": "stale_url",
            "recovered_from": "https://chatgpt.com/c/old",
        }
        cool = ns["CONTROL_RESTORE_COOLDOWN_SECONDS"]
        failed = dict(record)
        failed["restore_attempted_at"] = 2000.0
        failed["restore_failures"] = 1
        assert ns["restore_page_action"](failed, 2000 + cool - 1, True) == "reuse_idle"
        assert ns["restore_page_action"](failed, 2000 + cool - 1, False) == "wait"
        assert ns["restore_page_action"](failed, 2000 + cool, True) == "reuse_attempt"
        assert ns["restore_page_action"](failed, 2000 + cool, False) == "create"
        assert ns["restore_page_action"](record, 3000, False) == "create"

        path = Path(tmp) / "control.json"
        path.write_text(json.dumps(record), encoding="utf-8")
        ns["canonicalize_control_url"](canonical + "#top")
        stored = json.loads(path.read_text(encoding="utf-8"))
        assert stored["chatgpt_control_url"] == canonical
        assert stored["bootstrap_sent_at"] == 1000.0
        assert stored["recovery_used"] is True
        assert stored["recovery_reason"] == "stale_url"
        assert stored["recovered_from"] == "https://chatgpt.com/c/old"
        assert stored["bootstrap_sent"] is True

        path.write_text(json.dumps(record), encoding="utf-8")
        ns["note_restore_failure"]()
        failed_file = json.loads(path.read_text(encoding="utf-8"))
        assert failed_file["recovery_used"] is True
        assert failed_file["bootstrap_sent_at"] == 1000.0
        assert failed_file["recovered_from"] == "https://chatgpt.com/c/old"
        assert failed_file["chatgpt_control_url"] == web
        assert failed_file["restore_failures"] == 1
        assert failed_file["restore_attempted_at"]
        ns["note_restore_failure"]()
        again = json.loads(path.read_text(encoding="utf-8"))
        assert again["restore_failures"] == 2
        assert again["recovery_used"] is True
        ns["clear_restore_latch"]()
        cleared = json.loads(path.read_text(encoding="utf-8"))
        assert "restore_attempted_at" not in cleared
        assert "restore_failures" not in cleared
        assert cleared["recovery_used"] is True
        assert cleared["bootstrap_sent_at"] == 1000.0

    print("test_control_restore: OK")


if __name__ == "__main__":
    main()
