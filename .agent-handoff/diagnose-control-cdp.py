"""Read-only local CDP diagnostics for the Arena ChatGPT CONTROL recovery.
No browser navigation, clicks, message contents, user prompts, window names, or
conversation UUIDs are emitted. Does not import dispatcher or modify state.
"""
from __future__ import annotations

import json
import sys
import time
import urllib.request
from urllib.parse import urlparse

CDP = "http://127.0.0.1:9223"
def safe_kind(url):
    try:
        parsed = urlparse(str(url or ""))
    except Exception:
        return "invalid_url"
    if parsed.netloc.lower() != "chatgpt.com":
        return "other"
    path = parsed.path.strip("/")
    if not path:
        return "home"
    if path.startswith("c/"):
        ident = path[2:].lower()
        if ident.startswith("local-chatgpt:"):
            return "provisional_local_conversation"
        if ident.startswith("web:"):
            return "WEB_conversation_alias"
        return "durable_conversation"
    return "chatgpt_other_route"

def main():
    try:
        with urllib.request.urlopen(CDP + "/json/list", timeout=3) as response:
            tabs = json.load(response)
    except Exception as exc:
        print("CDP_HTTP_ERROR:", type(exc).__name__)
        return 2
    pages = [t for t in tabs if t.get("type") == "page"]
    print("CDP_PAGE_COUNT:", len(pages))
    print("CHATGPT_ROUTES:", [safe_kind(t.get("url")) for t in pages if "chatgpt.com" in t.get("url", "")])
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.connect_over_cdp(CDP, timeout=7500)
            info = []
            for context in browser.contexts:
                for page in context.pages:
                    url = str(page.url or "")
                    if "chatgpt.com" not in url:
                        continue
                    kind = safe_kind(url)
                    try:
                        snapshot = page.evaluate(
                            """() => {
                              const q = s => document.querySelectorAll(s).length;
                              const txt = ((document.body && document.body.innerText) || '');
                              const bootstrap = txt.includes('Служебный чат 01') && txt.includes('CONTROL & BRIDGE');
                              const ready = txt.includes('CONTROL READY');
                              const error = /unable to load conversation|couldn't load this conversation|не удалось загрузить этот разговор|something went wrong/i.test(txt);
                              const unsent = !!document.querySelector('#prompt-textarea') &&
                                (document.querySelector('#prompt-textarea').innerText || '').trim().length > 0;
                              return {
                                 message_role_nodes:q('[data-message-author-role]'),
                                 turns:q('[data-testid^="conversation-turn"]'),
                                 composer_nodes:q('#prompt-textarea, [contenteditable="true"][role="textbox"]'),
                                 ready_marker:ready, bootstrap_marker:bootstrap,
                                 visible_error_marker:error,
                                 unsent_composer:unsent,
                                 text_present:txt.trim().length > 50,
                                 document_ready:document.readyState
                              };
                            }"""
                        )
                    except Exception as exc:
                        snapshot = {"read_error": type(exc).__name__}
                    info.append({"route": kind, **snapshot})
            print("CHATGPT_PAGE_OBSERVATIONS:", json.dumps(info, ensure_ascii=False))
            # Deliberately do not call browser.close(): the dispatcher owns Chrome.
    except Exception as exc:
        print("CDP_ATTACH_ERROR:", type(exc).__name__)
        return 3
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
