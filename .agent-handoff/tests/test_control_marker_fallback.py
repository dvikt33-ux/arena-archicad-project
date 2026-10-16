"""Dispatcher wiring for the extracted CONTROL reply reader."""
from __future__ import annotations
import ast
import unittest
from pathlib import Path
SOURCE=Path(__file__).resolve().parents[1]/"dispatcher.py"
TREE=ast.parse(SOURCE.read_text(encoding="utf-8"))
def only_function(name,env):
    (node,)=[n for n in TREE.body if isinstance(n,ast.FunctionDef) and n.name==name]
    exec(compile(ast.fix_missing_locations(ast.Module(body=[node],type_ignores=[])),str(SOURCE),"exec"),env)
    return env[name]
def context():
    calls=[]
    record={"chatgpt_control_url":"https://chatgpt.com/c/known"}
    durable=lambda url:url.startswith("https://chatgpt.com/c/")
    same=lambda a,b:a.rstrip("/") == b.rstrip("/")
    def delegated(page,*args):
        calls.append((page,args))
        return [{"role":"user","text":"Проверь GitHub. turn_id=76"},
                {"role":"assistant","text":"CONTROL ACK — turn_id=76\nreply"}]
    return calls,{"load_control_record":lambda:record,"is_durable_control_url":durable,
        "same_conversation":same,"CONTROL_BOOTSTRAP_MARKER":"Служебный чат 01 — CONTROL & BRIDGE",
        "CONTROL_READY_MARKER":"CONTROL READY","log":lambda _:None,
        "read_control_marker_fallback":delegated}
class DispatcherFallbackWiringTests(unittest.TestCase):
    def test_fallback_delegates_using_saved_control_identity(self):
        calls,env=context(); page=object()
        result=only_function("_read_control_marker_fallback",env)(page)
        self.assertEqual(result[1]["text"],"CONTROL ACK — turn_id=76\nreply")
        self.assertEqual(calls[0][0],page)
        args=calls[0][1]
        self.assertEqual(args[0],{"chatgpt_control_url":"https://chatgpt.com/c/known"})
        self.assertTrue(args[1]("https://chatgpt.com/c/known"))
        self.assertTrue(args[2]("https://chatgpt.com/c/known","https://chatgpt.com/c/known"))
        self.assertEqual(args[3],"Служебный чат 01 — CONTROL & BRIDGE")
        self.assertEqual(args[4],"CONTROL READY")
    def test_chatgpt_message_fallback_runs_after_other_parsers(self):
        calls,env=context(); env.update({"_read_message_nodes":lambda p,s:[],
            "_read_turn_nodes":lambda p:[],"_read_accessible_turn_nodes":lambda p:[],
            "_normalize_message":lambda x:x})
        env["_read_control_marker_fallback"]=only_function("_read_control_marker_fallback",env)
        read=only_function("chatgpt_messages",env)
        result=read(object())
        self.assertEqual(result[0]["text"],"Проверь GitHub. turn_id=76")
        self.assertEqual(len(calls),1)
if __name__=="__main__": unittest.main()
