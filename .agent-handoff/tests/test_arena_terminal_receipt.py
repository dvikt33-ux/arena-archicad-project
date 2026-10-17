"""Arena final-result receipts: one GPT CONTROL ACK, no return handoff."""
import ast
import time
import unittest
from pathlib import Path

SOURCE=Path(__file__).resolve().parents[1]/"dispatcher.py"
TREE=ast.parse(SOURCE.read_text(encoding="utf-8"))

def load(name,context):
    (node,)=[n for n in TREE.body if isinstance(n,ast.FunctionDef) and n.name==name]
    exec(compile(ast.fix_missing_locations(ast.Module(body=[node],type_ignores=[])),
                 str(SOURCE),"exec"),context)
    return context[name]

def environment():
    events=[]
    def consume(state,turn,reason):
        events.append(("consume",turn,reason))
        state["last_turn_id"]=turn
        state["inflight"]=None
    env={
        "time":time,
        "wake_text":lambda n:f"Проверь GitHub. turn_id={n}",
        "TERMINAL_STATUSES":{"done","cancelled","canceled"},
        "HOLD_STATUSES":{"blocked","paused","idle"},
        "log":lambda s:None,
        "consume_turn":consume,
        "save_state":lambda s:events.append(("save",s.get("last_turn_id"))),
    }
    for name in ("signal_is_closed_ack_loop","is_arena_terminal_report","create_inflight",
                 "current_signal_cancels_inflight","handle_signal_without_action"):
        load(name,env)
    return env,events

DONE={"protocol":1,"turn_id":83,"source":"ARENA","target":"NONE",
      "status":"done","message":"VERIFIED\n- Result ready",
      "requires_codex":False}

class RoutingTests(unittest.TestCase):
    def test_arena_final_creates_one_pending_gpt_receipt(self):
        env,events=environment()
        state={"last_turn_id":82,"inflight":None}
        self.assertTrue(env["is_arena_terminal_report"](DONE))
        self.assertFalse(env["handle_signal_without_action"](state,DONE))
        pending=env["create_inflight"](state,DONE)
        self.assertEqual((pending["turn_id"],pending["target"],pending["terminal_report"]),
                         (83,"GPT",True))
        self.assertEqual(pending["wake"],"Проверь GitHub. turn_id=83")
        self.assertEqual(state["last_turn_id"],82)
        self.assertFalse(env["current_signal_cancels_inflight"](DONE,pending))
        self.assertFalse(any(event[0]=="consume" for event in events))

    def test_generic_none_and_cancelled_continue_to_close(self):
        env,events=environment()
        state={"last_turn_id":82}
        self.assertTrue(env["handle_signal_without_action"](
            state,{**DONE,"source":"GPT"}))
        self.assertEqual(state["last_turn_id"],83)
        self.assertEqual(events[-1][0],"consume")

    def test_empty_or_codex_final_report_never_wakes_gpt(self):
        env,_=environment()
        for changed in ({"message":""},{"requires_codex":True},
                        {"status":"cancelled"},{"target":"GPT"},
                        {"source":"GPT"}):
            with self.subTest(changed=changed):
                self.assertFalse(env["is_arena_terminal_report"]({**DONE,**changed}))

    def test_control_reply_finishes_terminal_without_github_publication(self):
        events=[]
        env={
            "ensure_control_ready":lambda *_:(object(),True),
            "chatgpt_response_complete":lambda *_:True,
            "chatgpt_messages":lambda *_:[{"role":"assistant","text":"ok"}],
            "parse_control_reply":lambda *_:"full report received",
            "publish_next_signal":lambda *_:events.append("BAD_GITHUB_PUBLISH"),
            "consume_turn":lambda st,n,why:events.append(("consume",n,why)),
            "log":lambda *_:None,
        }
        load("submitted_gpt_wake_needs_read_only_wait",env)
        process=load("process_gpt",env)
        state={"last_turn_id":82}
        pending={"turn_id":83,"wake":"Проверь GitHub. turn_id=83",
                 "target":"GPT","terminal_report":True}
        process(None,state,pending)
        self.assertEqual(events[0][0],"consume")
        self.assertIn("no GitHub follow-up",events[0][2])
        self.assertFalse(any(e=="BAD_GITHUB_PUBLISH" for e in events))

    def test_no_control_ack_keeps_final_report_pending(self):
        events=[]
        env={
            "ensure_control_ready":lambda *_:(object(),True),
            "chatgpt_response_complete":lambda *_:True,
            "chatgpt_messages":lambda *_:[],
            "parse_control_reply":lambda *_:None,
            "publish_next_signal":lambda *_:events.append("BAD_GITHUB_PUBLISH"),
            "consume_turn":lambda *_:events.append("BAD_CONSUME"),
            "log":lambda *_:None,
        }
        load("submitted_gpt_wake_needs_read_only_wait",env)
        process=load("process_gpt",env)
        state={"last_turn_id":82,"inflight":{"turn_id":83}}
        process(None,state,{"turn_id":83,"wake":"Проверь GitHub. turn_id=83",
                             "target":"GPT","terminal_report":True})
        self.assertEqual(events,[])
        self.assertEqual(state["last_turn_id"],82)

    def test_ordinary_gpt_reply_still_publishes_successor(self):
        events=[]
        env={
            "ensure_control_ready":lambda *_:(object(),True),
            "chatgpt_response_complete":lambda *_:True,
            "chatgpt_messages":lambda *_:[],
            "parse_control_reply":lambda *_:"continuation",
            "publish_next_signal":lambda n,reply:events.append(("publish",n,reply)) or True,
            "consume_turn":lambda st,n,reason:events.append(("consume",n)),
            "log":lambda *_:None,
        }
        load("submitted_gpt_wake_needs_read_only_wait",env)
        process=load("process_gpt",env)
        process(None,{},{"turn_id":80,"wake":"Проверь GitHub. turn_id=80"})
        self.assertEqual(events,[("publish",80,"continuation"),("consume",80)])

if __name__=="__main__":
    unittest.main()
