"""Fail-closed restart and terminal acknowledgement-loop regression.

No browser, no GitHub writes, no user queue mutation.
"""
from __future__ import annotations
import ast
import json
import os
import re
import tempfile
import unittest
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[1] / "dispatcher.py"
TREE = ast.parse(SOURCE.read_text(encoding="utf-8"))

def isolated(name, env):
    matches = [n for n in TREE.body if isinstance(n, ast.FunctionDef) and n.name == name]
    assert len(matches) == 1, name
    exec(compile(ast.fix_missing_locations(
        ast.Module(body=[matches[0]], type_ignores=[])), str(SOURCE), "exec"), env)
    return env[name]

def env_for(state_path, control_path):
    env = {"STATE_PATH":state_path, "CONTROL_PATH":control_path,
           "json":json, "os":os, "re":re, "log":lambda _:None,
           "wake_text":lambda n:f"Проверь GitHub. turn_id={n}",
           "HOLD_STATUSES":{"blocked", "paused", "idle"},
           "READY_STATUSES":{"ready", "pending", "queued"},
           "TERMINAL_STATUSES":{"done", "cancelled", "canceled"}}
    for name in ("default_state", "load_state", "save_state",
                 "signal_is_closed_ack_loop", "handle_signal_without_action",
                 "newer_signal_supersedes_inflight"):
        isolated(name, env)
    return env

CLOSED = {
    "source":"GPT","target":"ARENA","status":"ready",
    "turn_id":81,"requires_codex":False,
    "message":"""RELEASE_NOT_PROVEN

Turn 79: accepted.

Report: 4ace04e560ecfb232ec0a92a1b37650df3c3d30a.

Review: .agent-handoff/review-turn-79-arena-close.md.

Installed Git SHA: not established.

backupSHA256 is not the installed Git SHA.

Commit e0bd739354d771acc9945883cfdb5cf7f8f8b5d2 changed signal.json.

A2 PDF: deferred.

PR #3 (0dfc67d6b568): separate open draft.

Acknowledgement loop closed until new evidence exists.

No further handoff published. No rescan, push, save, export, or Codex/Work invocation performed."""
}

class QueueFailClosed(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.addCleanup(self.td.cleanup)
        base = Path(self.td.name)
        self.state = base / "queue.json"
        self.control = base / "control.json"
        self.e = env_for(self.state,self.control)

    def test_fresh_missing_queue_is_default_only_if_no_control(self):
        self.assertEqual(self.e["load_state"](), {"last_turn_id":0,"inflight":None})

    def test_existing_control_and_missing_state_fails_closed(self):
        self.control.write_text("{}",encoding="utf-8")
        with self.assertRaisesRegex(RuntimeError,"STATE_MISSING_STOP"):
            self.e["load_state"]()

    def test_corrupted_json_does_not_reset_turn(self):
        self.state.write_text('{ "last_turn_id": 80,', encoding="utf-8")
        with self.assertRaisesRegex(RuntimeError,"STATE_INVALID_STOP"):
            self.e["load_state"]()

    def test_unknown_shape_rejected(self):
        for data in ([], "text", {"last_turn_id":"81","inflight":None},
                     {"last_turn_id":-1,"inflight":None},
                     {"last_turn_id":81,"inflight":"broken"}):
            self.state.write_text(json.dumps(data),encoding="utf-8")
            with self.subTest(data=data), self.assertRaisesRegex(RuntimeError,"STATE_INVALID_STOP"):
                self.e["load_state"]()

    def test_inflight_must_own_valid_future_turn_and_wake(self):
        for pending in (
            {"turn_id":81,"target":"GPT","wake":"Проверь GitHub. turn_id=81"},
            {"turn_id":82,"target":"WRONG","wake":"Проверь GitHub. turn_id=82"},
            {"turn_id":82,"target":"ARENA","wake":"Проверь GitHub. turn_id=80"},
            {"turn_id":"82","target":"ARENA","wake":"Проверь GitHub. turn_id=82"},
        ):
            self.state.write_text(json.dumps({"last_turn_id":81,"inflight":pending}),encoding="utf-8")
            with self.subTest(pending=pending), self.assertRaisesRegex(RuntimeError,"STATE_INVALID_STOP"):
                self.e["load_state"]()

    def test_valid_pending_turn_survives_atomic_persistence(self):
        pending = {"turn_id":82,"target":"GPT","wake":"Проверь GitHub. turn_id=82",
                   "submitted":True,"wake_seen":True,"send_attempts":1}
        desired = {"last_turn_id":81,"inflight":pending}
        self.e["save_state"](desired)
        self.assertEqual(self.e["load_state"](),desired)
        self.assertFalse(self.state.with_suffix(".tmp").exists())

    def test_valid_completed_state_survives_restart(self):
        desired = {"last_turn_id":81,"inflight":None}
        self.e["save_state"](desired)
        self.assertEqual(self.e["load_state"](),desired)

class LoopClosureGuard(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.addCleanup(self.td.cleanup)
        base = Path(self.td.name)
        self.e = env_for(base/"queue.json", base/"control.json")
        self.events = []
        self.e["consume_turn"] = lambda state,tid,why:self.events.append((tid,why))

    def test_known_terminal_echo_is_not_relayed(self):
        state = {"last_turn_id":80,"inflight":None}
        self.assertTrue(self.e["signal_is_closed_ack_loop"](CLOSED))
        self.assertTrue(self.e["handle_signal_without_action"](state,CLOSED))
        self.assertEqual(self.events[0][0],81)
        self.assertIn("terminal",self.events[0][1])

    def test_new_user_instruction_after_closed_footer_is_not_dropped(self):
        data = {**CLOSED, "message":CLOSED["message"]+"\nNEW TASK: inspect logs"}
        self.assertFalse(self.e["signal_is_closed_ack_loop"](data))
        self.assertFalse(self.e["handle_signal_without_action"]({"last_turn_id":80},data))
        self.assertFalse(self.events)

    def test_no_loop_misclassification_of_real_tasks(self):
        variants = [
            {**CLOSED,"message":"RELEASE_NOT_PROVEN\nDo a new live test"},
            {**CLOSED,"source":"ARENA"},
            {**CLOSED,"target":"GPT"},
            {**CLOSED,"status":"pending"},
            {**CLOSED,"requires_codex":True},
            {**CLOSED,"message":CLOSED["message"].replace("Turn 79: accepted.","Turn none: accepted.")},
        ]
        for signal in variants:
            with self.subTest(signal=signal):
                self.assertFalse(self.e["signal_is_closed_ack_loop"](signal))

    def test_hold_and_terminal_status_still_take_priority(self):
        state={"last_turn_id":80}
        paused={**CLOSED,"status":"paused"}
        self.assertTrue(self.e["handle_signal_without_action"](state,paused))
        self.assertFalse(self.events)
        finished={**CLOSED,"status":"done","target":"NONE"}
        self.assertTrue(self.e["handle_signal_without_action"](state,finished))
        self.assertEqual(self.events[0][0],81)

    def test_already_consumed_turn_is_not_reconsumed(self):
        self.assertTrue(self.e["handle_signal_without_action"](
            {"last_turn_id":81},CLOSED))
        self.assertEqual(self.events,[])


class SuccessorIntegrity(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.addCleanup(self.td.cleanup)
        p = Path(self.td.name)
        self.e = env_for(p/"queue.json",p/"control.json")
        self.check = self.e["newer_signal_supersedes_inflight"]

    def test_adjacent_reply_from_actual_recipient_is_proven(self):
        examples = [
            ({"turn_id":78,"target":"GPT"},
             {"turn_id":79,"source":"GPT","target":"ARENA","status":"ready"}),
            ({"turn_id":79,"target":"ARENA"},
             {"turn_id":80,"source":"ARENA","target":"GPT","status":"ready"}),
            ({"turn_id":80,"target":"GPT"},
             {"turn_id":81,"source":"GPT","target":"NONE","status":"done"}),
        ]
        for pending,new in examples:
            with self.subTest(pending=pending,new=new):
                self.assertTrue(self.check(new,pending))

    def test_gaps_wrong_source_or_nonterminal_status_do_not_consume(self):
        pending={"turn_id":78,"target":"GPT"}
        candidates=[
            {"turn_id":80,"source":"GPT","target":"ARENA","status":"ready"},
            {"turn_id":79,"source":"ARENA","target":"GPT","status":"ready"},
            {"turn_id":79,"source":"GPT","target":"GPT","status":"ready"},
            {"turn_id":79,"source":"GPT","target":"NONE","status":"ready"},
            {"turn_id":79,"source":"GPT","target":"ARENA","status":"paused"},
        ]
        for new in candidates:
            with self.subTest(new=new):
                self.assertFalse(self.check(new,pending))
        self.assertFalse(self.check(candidates[0],None))

    def test_watch_quarantines_unverified_successor_without_consume(self):
        source=SOURCE.read_text(encoding="utf-8")
        watch=source[source.index("def watch() -> None:"):
                     source.index("# Manual diagnostics")]
        self.assertIn('inflight["last_error"] = "UNVERIFIED_SUCCESSOR"',watch)
        self.assertIn("save_state(state)",watch)
        self.assertIn("if not newer_signal_supersedes_inflight",watch)
        self.assertIn("time.sleep(CHECK_INTERVAL)",watch)

if __name__ == "__main__":
    unittest.main()
