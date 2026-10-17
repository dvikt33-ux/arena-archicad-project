"""Offline fault-injection tests for at-most-once wake delivery.

No network, UI, GitHub signal, queue file or browser is modified.
"""
from __future__ import annotations
import ast
import base64
import json
import re
import time
import unittest
from pathlib import Path

SOURCE=Path(__file__).resolve().parents[1]/"dispatcher.py"
TREE=ast.parse(SOURCE.read_text(encoding="utf-8"))

def attach(env,*names):
    for name in names:
        (node,)=[n for n in TREE.body if isinstance(n,ast.FunctionDef) and n.name==name]
        exec(compile(ast.fix_missing_locations(
            ast.Module(body=[node],type_ignores=[])),str(SOURCE),"exec"),env)
    return env

def ctx():
    writes=[]
    env={"time":time,"MAX_WAKE_ATTEMPTS":3,"WAKE_CONFIRM_SECONDS":90,
         "save_state":lambda state:writes.append(dict(state["inflight"])),
         "log":lambda text:None}
    attach(env,"wake_attempt_count","wake_send_allowed",
           "mark_wake_send_intent","mark_unobserved_wake")
    return env,writes

class WakeIntentTests(unittest.TestCase):
    def test_journal_persists_before_enter_and_blocks_retry(self):
        env,writes=ctx()
        inflight={"turn_id":82,"target":"GPT","wake":"Проверь GitHub. turn_id=82",
                  "send_attempts":0,"submitted":False,"retry_after":0}
        state={"last_turn_id":81,"inflight":inflight}
        self.assertTrue(env["wake_send_allowed"](inflight))
        env["mark_wake_send_intent"](state,inflight,82,"GPT")
        self.assertTrue(writes[0]["send_intent"])
        self.assertEqual(writes[0]["send_attempts"],1)
        self.assertFalse(env["wake_send_allowed"](inflight,now=time.time()+36000))
        with self.assertRaisesRegex(RuntimeError,"WAKE_ALREADY_ATTEMPTED"):
            env["mark_wake_send_intent"](state,inflight,82,"GPT")

    def test_unknown_enter_result_never_auto_retries(self):
        env,writes=ctx()
        inflight={"turn_id":82,"target":"ARENA","wake":"Проверь GitHub. turn_id=82"}
        state={"last_turn_id":81,"inflight":inflight}
        env["mark_wake_send_intent"](state,inflight,82,"ARENA")
        env["mark_unobserved_wake"](state,inflight,82,"ARENA")
        self.assertEqual(inflight["send_attempts"],1)
        self.assertEqual(inflight["last_error"],"UNCONFIRMED_WAKE_DELIVERY")
        self.assertFalse(env["wake_send_allowed"](inflight,now=time.time()+99999))

    def test_input_unavailable_before_enter_still_allows_later_attempt(self):
        env,_=ctx()
        inflight={"turn_id":82,"target":"ARENA","retry_after":time.time()+60}
        self.assertFalse(env["wake_send_allowed"](inflight))
        self.assertTrue(env["wake_send_allowed"](inflight,now=time.time()+61))

    def test_legacy_submitted_state_does_not_repeat(self):
        env,_=ctx()
        self.assertFalse(env["wake_send_allowed"]({
            "submitted":True,"send_attempts":1,"submitted_at":time.time()-86400
        }))
        self.assertFalse(env["wake_send_allowed"]({
            "submitted":False,"send_attempts":1,"last_error":"old wake not observed"
        }))

class SenderOrderingTests(unittest.TestCase):
    def test_arena_journal_callback_precedes_enter(self):
        events=[]
        class FakeEditor:
            def click(self):events.append("click")
            def fill(self,text):events.append("fill")
            def press(self,key,**kwargs):events.append("press:"+key)
        editor=FakeEditor()
        env={"dismiss_arena_completion":lambda page:None,
             "arena_feedback_visible":lambda page:False,
             "arena_editor":lambda page:editor,
             "editor_text":lambda ed:"wake",
             "arena_wake_exists":lambda page,wake:True}
        attach(env,"send_to_arena")
        class Page:
            def wait_for_timeout(self,ms):pass
        env["send_to_arena"](Page(),"wake",on_before_submit=lambda:events.append("journal"))
        self.assertLess(events.index("journal"),events.index("press:Enter"))

    def test_arena_preflight_failure_never_journals(self):
        events=[]
        env={"dismiss_arena_completion":lambda page:None,
             "arena_feedback_visible":lambda page:True,
             "arena_editor":lambda page:None}
        attach(env,"send_to_arena")
        with self.assertRaisesRegex(RuntimeError,"ARENA_INPUT_UNAVAILABLE"):
            env["send_to_arena"](object(),"wake",
                                 on_before_submit=lambda:events.append("journal"))
        self.assertEqual(events,[])

    def test_gpt_journal_before_enter_without_unconfirmed_retry(self):
        events=[]
        class Prompt:
            def evaluate(self,script):return None
            def fill(self,text):events.append("fill")
            def press(self,key):events.append("press:"+key)
        env={"chatgpt_prompt":lambda page:Prompt(),
             "_submit_confirmed":lambda *args:False,
             "submit_confirmation_action":lambda *args:events.append("retry") or "retry",
             "composer_has_exact_text":lambda *args:True,
             "submit_composer_only":lambda *args:events.append("resend"),
             "log":lambda text:None}
        attach(env,"send_to_chatgpt")
        class Page:
            url="https://chatgpt.com/c/persisted"
        self.assertFalse(env["send_to_chatgpt"](
            Page(),"wake",on_before_submit=lambda:events.append("journal"),
            allow_retry=False))
        self.assertEqual(events,["fill","journal","press:Enter"])

    def test_gpt_crash_before_enter_avoids_post_journal_input(self):
        events=[]
        class Prompt:
            def evaluate(self,script):pass
            def fill(self,text):events.append("fill")
            def press(self,key):events.append("ENTER")
        env={"chatgpt_prompt":lambda page:Prompt(),
             "_submit_confirmed":lambda *args:True,
             "log":lambda text:None}
        attach(env,"send_to_chatgpt")
        class Page: url="https://chatgpt.com/c/persisted"
        with self.assertRaisesRegex(RuntimeError,"disk failure"):
            env["send_to_chatgpt"](Page(),"wake",
                on_before_submit=lambda: (_ for _ in ()).throw(RuntimeError("disk failure")),
                allow_retry=False)
        self.assertNotIn("ENTER",events)

class NetworkFallbackTests(unittest.TestCase):
    def env(self, responses):
        events=[]
        class NetworkError(RuntimeError):pass
        class SignalError(RuntimeError):pass
        env={"json":json,"base64":base64,"time":time,"SIGNAL_URL":"https://raw.example/signal",
             "SIGNAL_API_URL":"https://api.example/contents","SIGNAL_FETCH_TIMEOUT":8,
             "GitHubNetworkError":NetworkError,"GitHubSignalError":SignalError,
             "_is_network_exception":lambda exc:isinstance(exc,TimeoutError),
             "log":lambda message:events.append(message)}
        def read(url,timeout,opener=None):
            events.append("GET "+("api" if "api.example" in url else "raw"))
            result=responses.pop(0)
            if isinstance(result,Exception):raise result
            return result
        env["_read_response"]=read
        attach(env,"parse_signal","parse_signal_text","parse_api_contents","fetch_signal")
        return env,events,NetworkError,SignalError

    def test_raw_failure_api_readback_succeeds(self):
        msg={"protocol":1,"turn_id":81,"target":"ARENA","source":"GPT",
             "status":"ready","message":"historical closed notice","requires_codex":False}
        body={"encoding":"base64","content":base64.b64encode(
            json.dumps(msg).encode("utf-8")).decode("ascii")}
        env,events,*_=self.env([TimeoutError("raw timeout"),json.dumps(body)])
        self.assertEqual(env["fetch_signal"]()["turn_id"],81)
        self.assertEqual([x for x in events if x.startswith("GET ")],["GET raw","GET api"])

    def test_both_endpoints_unavailable_fail_closed(self):
        env,events,NetworkError,_=self.env([TimeoutError("raw"),TimeoutError("api")])
        with self.assertRaises(NetworkError):
            env["fetch_signal"]()
        self.assertEqual(sum(x.startswith("GET ") for x in events),2)

    def test_malformed_raw_signal_not_silently_replaced_by_api(self):
        env,events,_,SignalError=self.env(['{"protocol":1,"requires_codex":"yes"}'])
        with self.assertRaises(SignalError):env["fetch_signal"]()
        self.assertEqual(sum(x.startswith("GET ") for x in events),1)

    def test_bad_api_after_network_error_fails_closed(self):
        env,events,_,SignalError=self.env([TimeoutError("raw"),'{"encoding":"plain"}'])
        with self.assertRaises(SignalError):env["fetch_signal"]()
        self.assertEqual(sum(x.startswith("GET ") for x in events),2)

if __name__=="__main__":
    unittest.main()
