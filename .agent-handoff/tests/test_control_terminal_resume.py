"""Offline terminal ACK recovery checks; no browser or mailbox operations."""
import ast
import unittest
from pathlib import Path
SRC=Path(__file__).resolve().parents[1]/"dispatcher.py"
TREE=ast.parse(SRC.read_text(encoding="utf-8"))

def load(name, env):
    item=next(n for n in TREE.body if isinstance(n,ast.FunctionDef) and n.name==name)
    exec(compile(ast.fix_missing_locations(ast.Module(body=[item],type_ignores=[])),
                 str(SRC),"exec"),env)
    return env[name]

class Clock:
    def __init__(self):self.now=1000
    def time(self):return self.now

class AckRecoveryTests(unittest.TestCase):
    def setup_case(self):
        times=Clock()
        events=[]
        state={"last_turn_id":86}
        pending={"turn_id":87,"terminal_report":True,
                 "wake_seen_control_identity":"known","submitted_at":800,
                 "send_attempts":1,"submitted":True}
        state["inflight"]=pending
        env={
            "time":times,
            "TERMINAL_CONTROL_ACK_GRACE_SECONDS":180,
            "TERMINAL_CONTROL_RESUME_GRACE_SECONDS":300,
            "control_wake_identity":lambda page:"known",
            "generation_is_active":lambda page:False,
            "_read_verified_ack_pair":lambda page:[],
            "parse_control_reply":lambda pair,n:None,
            "save_state":lambda state:events.append("saved"),
            "log":lambda msg:events.append("logged"),
            "chatgpt_user_message_exists":lambda page,text:True,
        }
        def send(page,text,on_before_submit=None,allow_retry=True):
            events.append("prepared")
            on_before_submit()
            events.append("entered")
        env["send_to_chatgpt"]=send
        return load("maybe_resume_terminal_control",env),state,pending,events,times

    def test_one_resume_only_and_timeout(self):
        action,state,pending,events,clock=self.setup_case()
        action(object(),state,pending,True)
        self.assertTrue(pending["terminal_resume_intent"])
        self.assertEqual(events.count("entered"),1)
        clock.now=1400
        action(object(),state,pending,True)
        self.assertEqual(events.count("entered"),1)
        self.assertEqual(pending["last_error"],"CONTROL_TERMINAL_ACK_TIMEOUT")

    def test_nonterminal_or_unseen_wake_never_resumes(self):
        action,state,pending,events,clock=self.setup_case()
        pending["terminal_report"]=False
        action(object(),state,pending,True)
        pending["terminal_report"]=True
        action(object(),state,pending,False)
        self.assertEqual(events,[])

    def test_grace_and_identity_holds(self):
        action,state,pending,events,clock=self.setup_case()
        clock.now=850
        action(object(),state,pending,True)
        clock.now=1000
        pending["wake_seen_control_identity"]="other"
        action(object(),state,pending,True)
        self.assertEqual(events,[])
