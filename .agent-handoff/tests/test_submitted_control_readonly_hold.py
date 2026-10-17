"""Offline checks: submitted CONTROL turn cannot create a new chat."""
import ast
import time
import unittest
from pathlib import Path
FILE=Path(__file__).resolve().parents[1]/"dispatcher.py"
TREE=ast.parse(FILE.read_text(encoding="utf-8"))
def load(name,env):
    node=next(n for n in TREE.body if isinstance(n,ast.FunctionDef) and n.name==name)
    exec(compile(ast.fix_missing_locations(ast.Module(body=[node],type_ignores=[])),
                 str(FILE),"exec"),env)
    return env[name]

class NoRebindForSubmittedWake(unittest.TestCase):
    def test_pending_submitted_turn_holds_without_mutating_control(self):
        writes=[]
        def forbidden(*a,**k):raise AssertionError("CONTROL mutation forbidden")
        env={"log":lambda *a:None,"save_state":lambda state:writes.append(1),
             "ensure_control_ready":forbidden,"time":time}
        load("submitted_gpt_wake_needs_read_only_wait",env)
        process=load("process_gpt",env)
        for extra in ({"submitted":True,"wake_seen":True},
                      {"submitted":True,"wake_seen":True,"terminal_resume_intent":True},
                      {"send_intent":True}):
            pending={"turn_id":87,"target":"GPT",
                     "wake":"Проверь GitHub. turn_id=87",
                     "last_error":"Control chat bootstrap pending",
                     "retry_after":time.time()+10000,**extra}
            state={"last_turn_id":86,"inflight":pending}
            process(None,state,pending)
            self.assertEqual(state["last_turn_id"],86)
            self.assertEqual(pending["last_error"],
                             "CONTROL_SUBMITTED_ACK_UNOBSERVED_READ_ONLY")
            prior=len(writes)
            process(None,state,pending)
            self.assertEqual(len(writes),prior)

    def test_not_submitted_remains_eligible_for_first_bootstrap(self):
        fn=load("submitted_gpt_wake_needs_read_only_wait",{})
        self.assertFalse(fn({"target":"GPT","submitted":False,"wake_seen":False}))
        self.assertFalse(fn({"target":"ARENA","submitted":True}))
        self.assertTrue(fn({"target":"GPT","send_intent":True}))

    def test_late_verified_ack_can_close_without_rebind(self):
        events=[]
        class Page:
            url="https://chatgpt.com/c/existing"
        class Browser:
            contexts=[type("Context",(),{"pages":[Page()]})()]
        def forbidden(*a,**k):raise AssertionError("GitHub/rebind forbidden")
        env={
            "load_control_record":lambda:{"chatgpt_control_url":Page.url},
            "is_durable_control_url":lambda url:url.startswith("https://chatgpt.com/c/"),
            "same_conversation":lambda a,b:a==b,
            "generation_is_active":lambda page:False,
            "terminal_resume_observation":lambda page,turn:{"ack":"valid"},
            "consume_turn":lambda state,turn,reason:events.append((turn,reason)),
            "publish_next_signal":forbidden,
            "ensure_control_ready":forbidden,
            "log":lambda *a:None,
        }
        process=load("process_gpt",env)
        pending={"turn_id":87,"target":"GPT","terminal_report":True,
                 "terminal_resume_intent":True,
                 "wake":"Проверь GitHub. turn_id=87","submitted":True}
        process(Browser(),{"last_turn_id":86,"inflight":pending},pending)
        self.assertEqual(len(events),1)
        self.assertEqual(events[0][0],87)
        self.assertIn("no GitHub follow-up",events[0][1])
