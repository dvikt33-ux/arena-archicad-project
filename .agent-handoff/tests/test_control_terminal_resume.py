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
            "terminal_resume_observation":lambda page,turn:{
                "wake_seen":True,"resume_seen":True,"ack":None},
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

class TerminalReceiptDomContract(unittest.TestCase):
    def test_matching_resume_ack_from_correct_page(self):
        class Page:
            def evaluate(self, javascript, turn_id):
                return {"wake_seen":True,"resume_seen":True,
                        "ack":"CONTROL ACK — turn_id=87\\nBRIDGE_SMOKE_86_87_RECEIVED".replace("\\n","\\n")}
        environment={
            "parse_control_reply":lambda messages,number:
                "BRIDGE_SMOKE_86_87_RECEIVED" if number==87 and
                messages[0]["text"]=="Проверь GitHub. turn_id=87"
                and messages[1]["text"].startswith("CONTROL ACK — turn_id=87") else None,
            "wake_text":lambda number:f"Проверь GitHub. turn_id={number}",
        }
        reader=load("terminal_resume_observation",environment)
        result=reader(Page(),87)
        self.assertTrue(result["resume_seen"])
        self.assertTrue(result["ack"])

    def test_missing_resume_or_wrong_ack_is_not_accepted(self):
        class Page:
            def __init__(self,payload):self.payload=payload
            def evaluate(self,javascript,turn_id):return self.payload
        environment={
            "parse_control_reply":lambda messages,number:(
                "accepted" if messages[1]["text"].startswith(
                  "CONTROL ACK — turn_id="+str(number)+"\\n") else None),
            "wake_text":lambda number:f"Проверь GitHub. turn_id={number}",
        }
        reader=load("terminal_resume_observation",environment)
        for facts in (
            {"wake_seen":True,"resume_seen":False,"ack":"CONTROL ACK — turn_id=87\\nbody"},
            {"wake_seen":False,"resume_seen":True,"ack":"CONTROL ACK — turn_id=87\\nbody"},
            {"wake_seen":True,"resume_seen":True,"ack":"CONTROL ACK — turn_id=86\\nbody"},
        ):
            with self.subTest(facts=facts):
                self.assertIsNone(reader(Page(facts),87)["ack"])

    def test_no_backend_publication_in_terminal_resume_consume_path(self):
        dispatcher=SRC.read_text(encoding="utf-8")
        self.assertIn('if observed["ack"]:',dispatcher)
        self.assertIn('ARENA final report acknowledged after CONTROL resume; no GitHub follow-up',dispatcher)
        reader=next(n for n in TREE.body if isinstance(n,ast.FunctionDef)
                    and n.name=="terminal_resume_observation")
        self.assertNotIn("publish_next_signal",ast.get_source_segment(dispatcher,reader))
