"""Regression checks for the legacy CONTROL recovery (no Playwright/browser required)."""
from __future__ import annotations

import ast
import json
import os
import tempfile
import time
import unittest
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[1] / "dispatcher.py"
SOURCE_TEXT = SOURCE.read_text(encoding="utf-8")
TREE = ast.parse(SOURCE_TEXT)

def load_function(name, env):
    nodes = [x for x in TREE.body if isinstance(x, (ast.FunctionDef, ast.AsyncFunctionDef)) and x.name == name]
    if len(nodes) != 1:
        raise AssertionError(f"expected one definition of {name}")
    executable = ast.fix_missing_locations(ast.Module(body=[nodes[0]], type_ignores=[]))
    exec(compile(executable, str(SOURCE), "exec"), env)
    return env[name]

def base_context():
    return dict(
        normalize_conversation_url=lambda s: str(s or "").split("?")[0].rstrip("/"),
        is_durable_control_url=lambda s: str(s).startswith("https://chatgpt.com/c/"),
        is_usable_control_url=lambda s: str(s).startswith("https://chatgpt.com/c/"),
        is_chatgpt_conversation_url=lambda s: str(s).startswith("https://chatgpt.com/c/"),
        hard_control_unavailable=lambda messages: False,
        positive_control_identity=lambda messages, wake: any(
            "CONTROL READY" in str(x.get("text") or "") for x in messages
        ),
        same_conversation=lambda a, b: str(a).rstrip("/") == str(b).rstrip("/"),
    )

class RestoreIdentityTests(unittest.TestCase):
    def test_blank_composer_does_not_confirm_restoration(self):
        ctx = base_context()
        fn = load_function("restore_observation_accepted", ctx)
        url = "https://chatgpt.com/c/previous"
        self.assertFalse(fn(url, url, [], True, "Проверь GitHub. turn_id=72"))
        self.assertTrue(fn(url, url, [{"role":"assistant","text":"CONTROL READY"}], True))
        self.assertFalse(fn(url, "https://chatgpt.com/c/other", [{"role":"user","text":"hello"}], True))
        self.assertTrue(fn(url, "https://chatgpt.com/c/other", [{"role":"assistant","text":"CONTROL READY"}], True))

class OneShotRescueTests(unittest.TestCase):
    def setUp(self):
        self.env = base_context()
        self.rescue = load_function("abandoned_control_rescue_allowed", self.env)
        self.record = {
            "chatgpt_control_url": "https://chatgpt.com/c/previous",
            "recovery_used": True,
            "restore_failures": 12,
            "unready_checks": 100,
        }
        self.params = ["wait", "stale_url", [], "https://chatgpt.com/", True, False, False, False]

    def ok(self, record=None, args=None):
        return self.rescue(self.record if record is None else record, *(self.params if args is None else args))

    def test_recovers_once_from_existing_stranded_state(self):
        self.assertTrue(self.ok())
        self.assertTrue(self.ok(args=["wait", "zero_messages", [], "https://chatgpt.com/", True, False, False, False]))
        # A matching but blank tab can be reused forever without counting a
        # failed restore; the legacy guard must not strand it indefinitely.
        self.assertTrue(self.ok({**self.record, "restore_failures": 0}))
        for change in (
            {"control_rescue_used":True}, {"recovery_used":False},
            {"unready_checks":19},
            {"rebind_status":"pending"}, {"rebind_finalize_status":"submitted"},
            {"rebind_reprovision_status":"started"},
        ):
            self.assertFalse(self.ok({**self.record, **change}), change)

    def test_fail_closed_when_state_or_page_not_confirmed(self):
        edits = [
            ["ready","stale_url",[],"https://chatgpt.com/",True,False,False,False],
            ["wait","marker_mismatch",[],"https://chatgpt.com/",True,False,False,False],
            ["wait","stale_url",[{"role":"user","text":"hi"}],"https://chatgpt.com/",True,False,False,False],
            ["wait","stale_url",[],"https://chatgpt.com/",False,False,False,False],
            ["wait","stale_url",[],"https://chatgpt.com/",True,True,False,False],
            ["wait","stale_url",[],"https://chatgpt.com/",True,False,True,False],
            ["wait","stale_url",[],"https://chatgpt.com/",True,False,False,True],
            ["wait","stale_url",[],"https://example.com/",True,False,False,False],
        ]
        for args in edits:
            self.assertFalse(self.ok(args=args), args)

    def test_rescue_fence_survives_control_url_change(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td)/"control.json"
            env = {
                **base_context(), "CONTROL_PATH":path, "VERSION":"test", "json":json,
                "os":os, "time":time, "log":lambda s:None,
            }
            save_control_record = load_function("save_control_record", env)
            self.assertIsNotNone(save_control_record)
            load_function("save_control_url", env)
            state = {
                "chatgpt_control_url":"https://chatgpt.com/c/previous",
                "bootstrap_sent":True,
                "recovery_used":True,
                "control_rescue_used":True,
                "control_rescue_from":"https://chatgpt.com/c/previous",
                "unready_checks":101,
            }
            save_control_record(state)
            loaded = json.loads(path.read_text(encoding="utf-8"))
            self.assertTrue(loaded["control_rescue_used"])
            self.assertEqual(loaded["control_rescue_from"], state["control_rescue_from"])
            env["save_control_url"]("https://chatgpt.com/c/recovered")
            current = json.loads(path.read_text(encoding="utf-8"))
            self.assertTrue(current["control_rescue_used"])
            self.assertTrue(current["recovery_used"])
            self.assertEqual(current["control_rescue_from"], state["control_rescue_from"])
            self.assertEqual(current["chatgpt_control_url"], "https://chatgpt.com/c/recovered")

    def test_fence_written_before_new_chat_attempt(self):
        # Static control flow guard against retry storms after a process crash.
        guard = SOURCE_TEXT.index('record["control_rescue_used"] = True')
        write = SOURCE_TEXT.index('save_control_record(record)', guard)
        provision = SOURCE_TEXT.index('return provision_control_chat(browser), False', guard)
        self.assertLess(guard, write)
        self.assertLess(write, provision)

if __name__ == "__main__":
    unittest.main()
