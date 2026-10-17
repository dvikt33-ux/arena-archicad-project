"""Regression coverage for CONTROL reply extraction and CAS signal publication."""
from __future__ import annotations
import ast, base64, json, unittest
import sys
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
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


class DomProvenanceTests(unittest.TestCase):
    """The real-browser DOM scanner must never accept an unproven ACK."""
    class ProbePage:
        url = "https://chatgpt.com/c/known"
        def __init__(self, pair=None, raise_error=False):
            self.pair, self.raise_error, self.scripts = pair, raise_error, []
        def evaluate(self, script):
            self.scripts.append(script)
            if self.raise_error:
                raise RuntimeError("browser detached")
            if "return metrics" in script:
                return {"pairs": [] if self.pair is None else [self.pair], "reason":"verified" if self.pair else "wake-not-matched", "userBubbles":1, "wakeBubbles":1 if self.pair else 0, "markdownBlocks":1, "headingMatches":1 if self.pair else 0, "replyBodies":1 if self.pair else 0}
            return {"boot": True, "ready": True,
                    "wakes": ["Проверь GitHub. turn_id=76"],
                    "turns": [{"role": "user", "text": "Проверь GitHub. turn_id=76"}]}

    def test_dom_proven_ack_preserves_payload_and_order(self):
        page = self.ProbePage({
            "wake": "Проверь GitHub. turn_id=76",
            "answer": "CONTROL ACK — turn_id=76\nRELEASE_NOT_PROVEN\n- Provenance pair: INCOMPLETE.\n- GUID: 261 → 261.",
        })
        msgs = handoff.read_control_marker_fallback(
            page, {"chatgpt_control_url":page.url},
            lambda value: "/c/" in value, lambda first,second:first==second,
            "Служебный чат 01 — CONTROL & BRIDGE", "CONTROL READY", lambda _:None
        )
        self.assertEqual([m["role"] for m in msgs], ["user","assistant","user","assistant"])
        self.assertEqual(handoff.parse_control_reply(msgs,76),
                         "RELEASE_NOT_PROVEN\n- Provenance pair: INCOMPLETE.\n- GUID: 261 → 261.")
        # 2026-10-17 real DOM: user bubble bg-user-message and the
        # MarkdownRoot-* answer. ACK heading is a <p> with split inline spans.
        self.assertTrue(any('[class~="bg-user-message"]' in x for x in page.scripts))
        self.assertTrue(any('[class*="MarkdownRoot-"]' in x for x in page.scripts))
        self.assertTrue(any('el.innerText' in x for x in page.scripts))
        self.assertTrue(any('after(wake.el,reply.el)' in x for x in page.scripts))
        self.assertTrue(any('el.closest(userScope)' in x for x in page.scripts))
        self.assertTrue(any('stop-button' in x for x in page.scripts))

    def test_dom_proven_ack_wrong_turn_rejected(self):
        page = self.ProbePage({
            "wake": "Проверь GitHub. turn_id=76",
            "answer": "CONTROL ACK — turn_id=75\nRELEASE_NOT_PROVEN",
        })
        self.assertEqual(handoff._read_verified_ack_pair(page), [])
        self.assertIsNone(handoff.parse_control_reply(
            [{"role":"user","text":"Проверь GitHub. turn_id=76"},
             {"role":"assistant","text":"CONTROL ACK — turn_id=75\nRELEASE_NOT_PROVEN"}],76))

    def test_absent_or_ambiguous_reply_fails_closed(self):
        self.assertEqual(handoff._read_verified_ack_pair(self.ProbePage()), [])
        page = self.ProbePage(raise_error=True)
        self.assertEqual(handoff._read_verified_ack_pair(page), [])
        self.assertEqual(handoff.read_control_marker_fallback(
            page, {"chatgpt_control_url":page.url},
            lambda value:True, lambda a,b:a==b,"bootstrap","ready",lambda _:None
        ), [])

    def test_split_span_heading_is_evaluated_from_bounded_block(self):
        # The real ACK paragraph has four inline children, so the scanner
        # must not demand an entire CONTROL ACK in one NodeFilter text node.
        p = self.ProbePage({
            "wake": "Проверь GitHub. turn_id=76",
            "answer": "CONTROL ACK — turn_id=76\nRELEASE_NOT_PROVEN",
        })
        self.assertEqual(len(handoff._read_verified_ack_pair(p)), 2)
        probe = next(x for x in p.scripts if "return metrics" in x)
        self.assertIn("MarkdownRoot-", probe)
        self.assertIn("first.innerText", probe)
        self.assertNotIn("NodeFilter.SHOW_TEXT", probe)
        self.assertIn("const m=raw.match(", probe)
        self.assertIn("first.textContent", probe)
        self.assertIn("userScope", probe)
        # Earlier bootstrap may be virtualized; wake and its reply suffice.
        self.assertNotIn("Служебный чат 01 — CONTROL & BRIDGE", probe)
        self.assertIn("headingMatches", probe)

    def test_same_reader_exposes_redacted_preflight_reason(self):
        page = self.ProbePage()
        diagnostic = {}
        self.assertEqual(handoff._read_verified_ack_pair(page, diagnostic), [])
        self.assertEqual(diagnostic["reason"], "wake-not-matched")
        self.assertEqual(diagnostic["wakeBubbles"], 0)
        self.assertNotIn("answer", diagnostic)
        self.assertNotIn("wake", diagnostic)

    def test_shared_reader_accepts_proven_pair_with_diagnostics(self):
        page = self.ProbePage({
            "wake": "Проверь GitHub. turn_id=76",
            "answer": "CONTROL ACK — turn_id=76\\nRELEASE_NOT_PROVEN".replace("\\n", "\n")
        })
        diagnostic = {}
        actual = handoff._read_verified_ack_pair(page, diagnostic)
        self.assertEqual(len(actual), 2)
        self.assertEqual(diagnostic["reason"], "verified")
        self.assertEqual(handoff.parse_control_reply(actual, 76), "RELEASE_NOT_PROVEN")

    def test_missing_ack_is_not_synthesized(self):
        page = self.ProbePage()
        messages=handoff.read_control_marker_fallback(
            page, {"chatgpt_control_url":page.url},
            lambda value:True, lambda a,b:a==b,
            "Служебный чат 01 — CONTROL & BRIDGE","CONTROL READY",lambda _:None)
        self.assertEqual(sum(m["role"]=="assistant" for m in messages),1)
        self.assertIsNone(handoff.parse_control_reply(messages,76))

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

class CompletionIntegrationTests(unittest.TestCase):
    def process(self, published):
        events=[]
        env={"ensure_control_ready":lambda browser,wake:(object(),True),
             "chatgpt_response_complete":lambda page,wake:True,
             "chatgpt_messages":lambda page:[{"role":"assistant","text":"answer"}],
             "parse_control_reply":lambda messages,turn_id:"reply",
             "publish_next_signal":lambda turn_id,reply:(events.append(("publish",turn_id,reply)) or published),
             "consume_turn":lambda state,turn_id,reason:events.append(("consume",turn_id,reason)),
             "log":lambda _:None}
        fn=only_dispatcher_function("process_gpt",env)
        state={"inflight":{"turn_id":76}}
        fn(None,state,{"turn_id":76,"wake":"Проверь GitHub. turn_id=76"})
        return events,state
    def test_consume_follows_successful_publish_readback(self):
        events,state=self.process(True)
        self.assertEqual([e[0] for e in events],["publish","consume"])
        self.assertEqual(state["inflight"]["turn_id"],76)
    def test_publish_failure_does_not_consume_turn(self):
        events,state=self.process(False)
        self.assertEqual([e[0] for e in events],["publish"])
        self.assertEqual(state["inflight"]["turn_id"],76)

class DirectResumeTests(unittest.TestCase):
    """Previously submitted wake can finish even when bootstrap is virtualized."""
    def test_real_ack_resumes_from_existing_control_without_duplicate_send(self):
        events = []
        class Browser:
            contexts = [type("Context", (), {"pages": [
                type("Page", (), {"url": "https://chatgpt.com/c/known"})()
            ]})()]
        env = {
            "load_control_record": lambda: {
                "chatgpt_control_url":"https://chatgpt.com/c/known"},
            "is_durable_control_url": lambda u: "/c/" in u,
            "same_conversation": lambda a,b:a==b,
            "generation_is_active": lambda page:False,
            "_read_verified_ack_pair":lambda page:[
                {"role":"user","text":"Проверь GitHub. turn_id=76"},
                {"role":"assistant","text":"CONTROL ACK — turn_id=76\nRELEASE_NOT_PROVEN"},
            ],
            "parse_control_reply": handoff.parse_control_reply,
            "publish_next_signal": lambda n,p:
                (events.append(("publish",n,p)) or True),
            "consume_turn":lambda state,n,reason:
                events.append(("consume",n,reason)),
            "log":lambda value:events.append(("log",value)),
            "ensure_control_ready":lambda b,w:
                self.fail("completed reply must not call ensure_control_ready"),
            "send_to_chatgpt":lambda p,w:
                self.fail("completed wake must not be sent again"),
        }
        fn=only_dispatcher_function("process_gpt",env)
        state={"inflight":{"turn_id":76,"wake":"Проверь GitHub. turn_id=76"}}
        fn(Browser(),state,state["inflight"])
        self.assertEqual([event[0] for event in events],["publish","consume"])
        self.assertEqual(events[0],("publish",76,"RELEASE_NOT_PROVEN"))

    def test_github_write_failure_keeps_pending_turn(self):
        events=[]
        class Browser:
            contexts=[type("Context",(),{"pages":[
                type("Page",(),{"url":"https://chatgpt.com/c/known"})()
            ]})()]
        env={
            "load_control_record":lambda:{"chatgpt_control_url":"https://chatgpt.com/c/known"},
            "is_durable_control_url":lambda u:True,
            "same_conversation":lambda a,b:a==b,
            "generation_is_active":lambda page:False,
            "_read_verified_ack_pair":lambda page:[
                {"role":"user","text":"Проверь GitHub. turn_id=76"},
                {"role":"assistant","text":"CONTROL ACK — turn_id=76\nbody"}],
            "parse_control_reply":handoff.parse_control_reply,
            "publish_next_signal":lambda n,p:(events.append("publish") or False),
            "consume_turn":lambda *args:events.append("consume"),
            "log":lambda _:None,
            "ensure_control_ready":lambda b,w:
                self.fail("should return before other flow"),
        }
        fn=only_dispatcher_function("process_gpt",env)
        fn(Browser(),{},{"turn_id":76,"wake":"Проверь GitHub. turn_id=76"})
        self.assertEqual(events,["publish"])

def only_dispatcher_function(name,env):
    source=Path(__file__).resolve().parents[1]/"dispatcher.py"
    tree=ast.parse(source.read_text(encoding="utf-8"))
    (node,)=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name==name]
    exec(compile(ast.fix_missing_locations(ast.Module(body=[node],type_ignores=[])),str(source),"exec"),env)
    return env[name]
if __name__ == "__main__": unittest.main()
