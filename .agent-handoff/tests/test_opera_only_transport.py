"""Opera-only dispatcher regression: exact CONTROL, no Chrome, no rebind."""
import ast
import unittest
from pathlib import Path

SOURCE_PATH=Path(__file__).resolve().parents[1]/"dispatcher.py"
SOURCE=SOURCE_PATH.read_text(encoding="utf-8")
TREE=ast.parse(SOURCE)

def load(name, env):
    node=next(x for x in TREE.body if isinstance(x,ast.FunctionDef) and x.name==name)
    exec(compile(ast.fix_missing_locations(ast.Module(body=[node],type_ignores=[])),
        str(SOURCE_PATH),"exec"),env)
    return env[name]

PINNED="https://chatgpt.com/c/6ad27341-1ea4-83eb-8238-5ce1cada094a"
OTHER="https://chatgpt.com/c/6ad3e97f-5980-83eb-babf-d34379e0df0c"

class Page:
    def __init__(self,url): self.url=url
    def is_closed(self): return False
    def goto(self,url,**kw): self.url=url

class Context:
    def __init__(self,pages): self.pages=pages; self.created=0
    def new_page(self):
        self.created+=1
        page=Page("about:blank")
        self.pages.append(page)
        return page

class Browser:
    def __init__(self,pages):
        self.contexts=[Context(pages)]

class OperaSafety(unittest.TestCase):
    def env(self, control=PINNED, messages=None):
        if messages is None: messages=[
            {"role":"user","text":"bootstrap"},
            {"role":"assistant","text":"CONTROL READY"}]
        events=[]
        e={
            "_OPERA_PINNED_TAB":None,
            "log":lambda *a:events.append(("log",a)),
            "load_control_record":lambda:{
                "chatgpt_control_url":control,"bootstrap_sent":True},
            "is_durable_control_url":lambda url:url.startswith("https://chatgpt.com/c/"),
            "same_conversation":lambda a,b:a==b,
            "chatgpt_messages":lambda page:messages,
            "composer_is_ready":lambda page:True,
            "generation_is_active":lambda page:False,
            "page_shows_unavailable":lambda page:False,
            "page_signed_out":lambda page:False,
            "PAGE_TIMEOUT":5000,
        }
        return e,events

    def test_connected_pinned_tab_is_reused_not_rebound(self):
        env,events=self.env()
        fn=load("existing_opera_control_only",env)
        browser=Browser([Page(OTHER),Page(PINNED)])
        page,ready=fn(browser,"Проверь GitHub. turn_id=88")
        self.assertTrue(ready)
        self.assertEqual(page.url,PINNED)
        self.assertEqual(browser.contexts[0].created,0)

    def test_missing_pinned_tab_opens_exact_same_conversation_once(self):
        env,events=self.env()
        fn=load("existing_opera_control_only",env)
        browser=Browser([Page(OTHER)])
        first,ready=fn(browser)
        second,ready2=fn(browser)
        self.assertTrue(ready and ready2)
        self.assertIs(first,second)
        self.assertEqual(browser.contexts[0].created,1)
        self.assertEqual(first.url,PINNED)

    def test_zero_messages_does_not_rebind_or_send(self):
        env,events=self.env(messages=[])
        fn=load("existing_opera_control_only",env)
        browser=Browser([Page(PINNED)])
        _,ready=fn(browser)
        self.assertFalse(ready)
        self.assertEqual(browser.contexts[0].created,0)

    def test_multiple_matching_tabs_fail_closed(self):
        env,events=self.env()
        fn=load("existing_opera_control_only",env)
        page,ready=fn(Browser([Page(PINNED),Page(PINNED)]))
        self.assertIsNone(page)
        self.assertFalse(ready)

    def test_no_old_restore_path_is_callable(self):
        fn=next(n for n in TREE.body if isinstance(n,ast.FunctionDef)
                and n.name=="ensure_control_ready")
        first=fn.body[0]
        self.assertIsInstance(first,ast.Return)
        self.assertEqual(ast.unparse(first.value),
                         "existing_opera_control_only(browser, wake)")
        self.assertNotIn("start_service_chrome",SOURCE)
        self.assertNotIn("stop_owned_chrome",SOURCE)
        self.assertNotIn("CHROME_PATH",SOURCE)

    def test_manual_runtime_and_core_are_opera_only(self):
        runtime=(SOURCE_PATH.parent/"dispatcher-runtime.py").read_text(encoding="utf-8")
        self.assertIn("core.require_opera_cdp()",runtime)
        self.assertNotIn("start_service_chrome",runtime)
        self.assertIn("CDP_PORT = 9224",SOURCE)

if __name__=="__main__":unittest.main()
