"""Regression coverage for CONTROL reply extraction and CAS signal publication."""
from __future__ import annotations
import base64, json, unittest
from unittest.mock import patch
import control_reply_handoff as handoff

class FakePage:
    url = "https://chatgpt.com/c/known"
    def __init__(self, facts): self.facts=facts; self.calls=0
    def evaluate(self, script): self.calls+=1; return self.facts

class FallbackTests(unittest.TestCase):
    def facts(self):
        return {"boot":True,"ready":True,"wakes":["Проверь GitHub. turn_id=76"],"turns":[
            {"role":"user","text":"Проверь GitHub. turn_id=76"},
            {"role":"assistant","text":"CONTROL ACK — turn_id=76\nRELEASE_NOT_PROVEN"},
        ]}
    def read(self,page):
        return handoff.read_control_marker_fallback(
            page,{"chatgpt_control_url":FakePage.url},
            lambda u:"/c/" in u,lambda a,b:a==b,
            "Служебный чат 01 — CONTROL & BRIDGE","CONTROL READY",lambda _:None)
    def test_reads_role_labelled_assistant_response_after_wake(self):
        page=FakePage(self.facts())
        messages=self.read(page)
        self.assertIn({"role":"assistant","text":"CONTROL ACK — turn_id=76\nRELEASE_NOT_PROVEN"},messages)
        self.assertEqual(handoff.parse_control_reply(messages,76),"RELEASE_NOT_PROVEN")
    def test_wrong_chat_and_missing_markers_fail_closed(self):
        page=FakePage(self.facts()); page.url="https://chatgpt.com/c/other"
        self.assertEqual(self.read(page),[]); self.assertEqual(page.calls,0)
        self.assertEqual(self.read(FakePage({"boot":True,"ready":False,"wakes":[],"turns":[]})),[])
    def test_reply_requires_exact_ack_for_pending_wake(self):
        valid=[{"role":"user","text":"Проверь GitHub. turn_id=76"},
               {"role":"assistant","text":"CONTROL ACK — turn_id=76\nbody"}]
        self.assertEqual(handoff.parse_control_reply(valid,76),"body")
        for bad in (
            [{"role":"user","text":"Проверь GitHub. turn_id=76"},{"role":"assistant","text":"CONTROL ACK — turn_id=75\nbody"}],
            [{"role":"user","text":"Проверь GitHub. turn_id=75"},{"role":"assistant","text":"CONTROL ACK — turn_id=76\nbody"}],
            [{"role":"user","text":"Проверь GitHub. turn_id=76"},{"role":"assistant","text":"reply without ack"}],
        ): self.assertIsNone(handoff.parse_control_reply(bad,76))

class PublishTests(unittest.TestCase):
    def encoded(self,obj,sha="blob76"):
        raw=json.dumps(obj,ensure_ascii=False,indent=2).encode()
        return {"encoding":"base64","content":base64.b64encode(raw).decode(),"sha":sha}
    def test_turn76_cas_put_and_readback(self):
        current={"protocol":1,"turn_id":76,"target":"GPT","source":"ARENA","status":"ready","message":"source","requires_codex":False}
        state={"doc":self.encoded(current),"puts":0}
        def api(method,token,payload=None):
            if method=="GET": return state["doc"]
            self.assertEqual(method,"PUT"); self.assertEqual(payload["sha"],"blob76")
            self.assertEqual(payload["branch"],"agent-handoff"); state["puts"]+=1
            desired=json.loads(base64.b64decode(payload["content"]))
            state["doc"]=self.encoded(desired,"blob77"); return {}
        with patch.object(handoff,"_api_request",side_effect=api):
            self.assertTrue(handoff.publish_next_signal(76,"GPT answer",token="test"))
        self.assertEqual(state["puts"],1)
        self.assertEqual(handoff._decode_contents(state["doc"]),{
            "protocol":1,"turn_id":77,"target":"ARENA","source":"GPT","status":"ready",
            "message":"GPT answer","requires_codex":False})
    def test_wrong_turn_is_not_written(self):
        current={"protocol":1,"turn_id":75,"target":"GPT","source":"ARENA","status":"ready"}
        calls=[]
        with patch.object(handoff,"_api_request",side_effect=lambda method,token,payload=None:(calls.append(method) or self.encoded(current))):
            self.assertFalse(handoff.publish_next_signal(76,"reply",token="test"))
        self.assertEqual(calls,["GET"])
    def test_retry_after_write_is_idempotent(self):
        wanted={"protocol":1,"turn_id":77,"target":"ARENA","source":"GPT","status":"ready","message":"reply","requires_codex":False}
        calls=[]
        with patch.object(handoff,"_api_request",side_effect=lambda method,token,payload=None:(calls.append(method) or self.encoded(wanted,"blob77"))):
            self.assertTrue(handoff.publish_next_signal(76,"reply",token="test"))
        self.assertEqual(calls,["GET","GET"])
    def test_missing_credential_fails_closed(self):
        with patch.object(handoff,"_api_request") as api:
            self.assertFalse(handoff.publish_next_signal(76,"reply",token=""))
        api.assert_not_called()

if __name__ == "__main__": unittest.main()
