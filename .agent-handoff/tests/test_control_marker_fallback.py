"""Fail-closed checks for CONTROL text-node fallback after ChatGPT DOM changes."""
from __future__ import annotations

import ast
import unittest
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[1] / "dispatcher.py"
TREE = ast.parse(SOURCE.read_text(encoding="utf-8"))

def only_function(name, env):
    (node,) = [n for n in TREE.body if isinstance(n, ast.FunctionDef) and n.name == name]
    exec(compile(ast.fix_missing_locations(ast.Module(body=[node], type_ignores=[])),
                 str(SOURCE), "exec"), env)
    return env[name]

class Page:
    def __init__(self, route="https://chatgpt.com/c/known", facts=None, fails=False):
        self.url, self.facts, self.fails = route, facts, fails
        self.calls = 0
    def evaluate(self, script):
        self.calls += 1
        if self.fails:
            raise RuntimeError("browser unavailable")
        return self.facts

def context():
    logs = []
    env = {
        "load_control_record": lambda: {"chatgpt_control_url": "https://chatgpt.com/c/known"},
        "is_durable_control_url": lambda s: s.startswith("https://chatgpt.com/c/") and "local-chatgpt:" not in s,
        "same_conversation": lambda a,b: a.rstrip("/") == b.rstrip("/"),
        "CONTROL_BOOTSTRAP_MARKER": "Служебный чат 01 — CONTROL & BRIDGE",
        "CONTROL_READY_MARKER": "CONTROL READY",
        "log": logs.append,
    }
    return env, logs

class CONTROLMarkerFallbackTests(unittest.TestCase):
    def setUp(self):
        self.env, self.logs = context()
        self.read = only_function("_read_control_marker_fallback", self.env)

    def test_ready_identity_and_exact_wake(self):
        page = Page(facts={"boot":True, "ready":True,
                           "wakes":["Проверь GitHub. turn_id=76"]})
        result = self.read(page)
        self.assertEqual([x["role"] for x in result], ["user","assistant","user"])
        self.assertEqual(result[1]["text"], "CONTROL READY")
        self.assertEqual(result[2]["text"], "Проверь GitHub. turn_id=76")
        self.assertTrue(self.logs)

    def test_missing_standalone_ready_fails_closed(self):
        # 'CONTROL READY' appears inside bootstrap instructions as substring,
        # which is insufficient to prove an assistant reply.
        self.assertEqual(self.read(Page(facts={"boot":True,"ready":False,"wakes":[]})), [])
        self.assertEqual(self.read(Page(facts={"boot":False,"ready":True,"wakes":[]})), [])

    def test_other_chat_does_not_get_control_identity(self):
        page = Page(route="https://chatgpt.com/c/unrelated",
                    facts={"boot":True,"ready":True,"wakes":[]})
        self.assertEqual(self.read(page), [])
        self.assertEqual(page.calls, 0)

    def test_provisional_route_rejected(self):
        page = Page(route="https://chatgpt.com/c/local-chatgpt:uuid",
                    facts={"boot":True,"ready":True,"wakes":[]})
        self.assertEqual(self.read(page), [])
        self.assertEqual(page.calls, 0)

    def test_errors_and_untrusted_results_fail_closed(self):
        self.assertEqual(self.read(Page(fails=True)), [])
        self.assertEqual(self.read(Page(facts=None)), [])
        self.assertEqual(self.read(Page(facts={"boot":True,"ready":True,"wakes":[12,{}]})),
                         [{"role":"user","text":"Служебный чат 01 — CONTROL & BRIDGE"},
                          {"role":"assistant","text":"CONTROL READY"}])

    def test_chatgpt_messages_uses_fallback_only_after_all_parsers_empty(self):
        page = Page(facts={"boot":True, "ready":True,"wakes":[]})
        self.env.update({
            "_read_message_nodes": lambda p,sel: [],
            "_read_turn_nodes": lambda p: [],
            "_read_accessible_turn_nodes": lambda p: [],
            "_normalize_message": lambda item: item,
        })
        read_messages = only_function("chatgpt_messages", self.env)
        result = read_messages(page)
        self.assertEqual([x["role"] for x in result], ["user","assistant"])
        self.assertEqual(page.calls, 1)

    def test_no_document_body_text_heuristic(self):
        src = SOURCE.read_text(encoding="utf-8")
        block = src.split("def _read_control_marker_fallback(",1)[1].split("def chatgpt_messages(",1)[0]
        self.assertIn("document.createTreeWalker", block)
        self.assertIn("main, [role=", block)
        self.assertIn("NodeFilter.SHOW_TEXT", block)
        self.assertNotIn("document.body.innerText", block)

if __name__ == "__main__":
    unittest.main()
