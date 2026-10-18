"""One-time externally verified receipt 87 recovery; strictly offline."""
from __future__ import annotations
import ast
import unittest
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "dispatcher.py"
AST = ast.parse(SRC.read_text(encoding="utf-8"))

def load(name, env):
    matches=[x for x in AST.body if isinstance(x,ast.FunctionDef) and x.name==name]
    if len(matches)!=1: raise AssertionError(name)
    exec(compile(ast.fix_missing_locations(
        ast.Module(body=[matches[0]],type_ignores=[])),str(SRC),"exec"),env)
    return env[name]

OLD="https://chatgpt.com/c/6ad27341-1ea4-83eb-8238-5ce1cada094a"
OTHER="https://chatgpt.com/c/6ad3e97f-5980-83eb-babf-d34379e0df0c"
MARKER="BRIDGE_SMOKE_86_87_RECEIVED"
SHA="c6ed9fc52437e4c2f78d472eb25cd53620132fcd"

SIGNAL={
    "protocol":1,"turn_id":87,"source":"ARENA",
    "target":"NONE","status":"done","message":MARKER+"\nshort report",
    "requires_codex":False
}
RECEIPT={
    "protocol":1,"kind":"terminal_ack","turn_id":87,
    "source":"VERIFIED_CONTROL_RECOVERY",
    "method":"read_only_opera_connector_accessibility_tree",
    "control_url":OLD,"reply_header":"CONTROL ACK — turn_id=87",
    "report_marker":MARKER,"signal_blob_sha":SHA,
    "signal_source":"ARENA","signal_target":"NONE","signal_status":"done",
    "ack_verified":True,"repeat_instruction":False
}
PENDING={
    "turn_id":87,"target":"GPT","wake":"Проверь GitHub. turn_id=87",
    "terminal_report":True,"submitted":True,"send_attempts":1,
    "wake_seen":True,"terminal_resume_intent":True,
    "wake_seen_control_url":OLD,
    "wake_seen_control_identity":OLD.rsplit("/",1)[-1]
}

def env():
    context={
        "conversation_identity":lambda value:value.rsplit("/",1)[-1].lower(),
        "GitHubSignalError":type("GitHubSignalError",(RuntimeError,),{}),
        "log":lambda msg:None,
        "parse_signal":lambda obj:obj,
    }
    load("terminal_receipt_matches",context)
    load("verified_terminal_receipt_from_github",context)
    return context

class ExactRecovery(unittest.TestCase):
    def test_legitimate_receipt_matches_only_the_original_chat(self):
        fn=env()["terminal_receipt_matches"]
        self.assertTrue(fn(RECEIPT,SIGNAL,SHA,PENDING))
        variants=[
            ({**RECEIPT,"control_url":OTHER}, SIGNAL, SHA, PENDING),
            ({**RECEIPT,"signal_blob_sha":"deadbeef"}, SIGNAL, SHA, PENDING),
            ({**RECEIPT,"turn_id":88}, SIGNAL, SHA, PENDING),
            ({**RECEIPT,"method":"unverified"}, SIGNAL, SHA, PENDING),
            ({**RECEIPT,"report_marker":"wrong"}, SIGNAL, SHA, PENDING),
            ({**RECEIPT,"ack_verified":False}, SIGNAL, SHA, PENDING),
            (RECEIPT, {**SIGNAL,"requires_codex":True},SHA,PENDING),
            (RECEIPT,{**SIGNAL,"message":"wrong"},SHA,PENDING),
            (RECEIPT,{**SIGNAL,"source":"GPT"},SHA,PENDING),
            (RECEIPT,SIGNAL,SHA,{**PENDING,"submitted":False}),
            (RECEIPT,SIGNAL,SHA,{**PENDING,"send_attempts":2}),
            (RECEIPT,SIGNAL,SHA,{**PENDING,"wake_seen_control_identity":"wrong"}),
        ]
        for args in variants:
            with self.subTest(args=args):
                self.assertFalse(fn(*args))

    def test_missing_or_changed_receipt_does_not_close(self):
        e=env()
        def fake(url):
            if url.endswith("receipts/87.json?ref=agent-handoff"):
                return RECEIPT,SHA
            return {**SIGNAL,"message":"changed"},SHA
        e["_github_contents_with_sha"]=fake
        fn=load("verified_terminal_receipt_from_github",e)
        self.assertFalse(fn(SIGNAL,PENDING))
        e["_github_contents_with_sha"]=lambda url:({},SHA)
        self.assertFalse(fn(SIGNAL,PENDING))
        self.assertFalse(fn({**SIGNAL,"turn_id":88},PENDING))

    def test_valid_receipt_closes_87_once_without_control_or_signal_write(self):
        e=env()
        e["_github_contents_with_sha"]=lambda url:(
            (RECEIPT,SHA) if "receipts/87.json" in url else (SIGNAL,SHA)
        )
        load("verified_terminal_receipt_from_github",e)
        events=[]
        def consume(state,turn,reason):
            state["last_turn_id"]=turn
            state["inflight"]=None
            events.append(("consumed",turn,reason))
        e.update({
            "consume_turn":consume,
            "ensure_control_ready":lambda *a:events.append(("BAD_REBIND",)),
            "publish_next_signal":lambda *a:events.append(("BAD_SIGNAL",)),
            "send_to_chatgpt":lambda *a:events.append(("BAD_WAKE",)),
        })
        process=load("process_gpt",e)
        state={"last_turn_id":86,"inflight":PENDING.copy()}
        process(None,state,state["inflight"],SIGNAL)
        self.assertEqual(state["last_turn_id"],87)
        self.assertIsNone(state["inflight"])
        self.assertEqual(len(events),1)
        self.assertEqual(events[0][:2],("consumed",87))
        self.assertIn("not Chrome E2E proof",events[0][2])

    def test_watch_supplies_exact_signal_to_receipt_checker(self):
        source=SRC.read_text(encoding="utf-8")
        self.assertIn("process_gpt(browser, state, inflight, signal)",source)
        self.assertNotIn("process_gpt(browser, state, inflight)\n",source)

if __name__=="__main__":
    unittest.main()
