"""Read-only structural diagnosis of an EXISTING ChatGPT CONTROL conversation.

Safeguards:
- No navigation, sending, clicks, page closures, or dispatcher state changes.
- Only inspects the conversation URL already saved in the local control JSON.
- Does not print URLs, messages, full DOM, cookies, account identifiers, or text.
- Outputs structural metadata around exact CONTROL bootstrap/READY markers.
"""
from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urlsplit

CDP = "http://127.0.0.1:9223"
CONTROL_PATH = Path.home() / ".ai-dispatcher-control.json"

def conversation_id(url: str) -> str:
    try:
        parsed = urlsplit(str(url))
        if parsed.hostname != "chatgpt.com" or not parsed.path.startswith("/c/"):
            return ""
        ident = parsed.path[3:]
        if ident.lower().startswith("web:"):
            ident = ident[4:]
        return ident.lower()
    except Exception:
        return ""

JS = r"""() => {
  const ROOT = document.body;
  if (!ROOT) return {status:"BODY_ABSENT"};
  const labels = [
    ["bootstrap", "Служебный чат 01 — CONTROL & BRIDGE"],
    ["ready", "CONTROL READY"],
    ["wake", "Проверь GitHub. turn_id="],
  ];
  const normalize = s => String(s || "").replace(/\u00a0/g," ").trim();
  const main = [...document.querySelectorAll('main, [role="main"]')];
  const mainHasBootstrap = main.some(n => normalize(n.innerText).includes(labels[0][1]));
  const body = normalize(ROOT.innerText);
  const matched = [];
  const counts = {bootstrap:0, ready:0, wake:0, ready_exact:0};
  const walker = document.createTreeWalker(ROOT, NodeFilter.SHOW_TEXT);
  let inspected = 0;
  while (walker.nextNode() && inspected < 100000) {
    inspected++;
    const n = walker.currentNode, p = n.parentElement;
    if (!p || p.closest("script, style, textarea, [contenteditable=true]")) continue;
    const t = normalize(n.textContent);
    let kind = "";
    if (t.includes(labels[0][1])) kind = "bootstrap";
    else if (t.includes(labels[2][1])) kind = "wake";
    else if (t.includes(labels[1][1])) kind = "ready";
    if (!kind) continue;
    counts[kind]++;
    if (kind === "ready" && /^CONTROL READY\.?$/.test(t)) counts.ready_exact++;
    if (matched.length >= 14) continue;
    const chain = [];
    let ancestor = p;
    while (ancestor && chain.length < 9) {
      const testid = ancestor.getAttribute("data-testid") || "";
      chain.push({
        tag: ancestor.tagName.toLowerCase(),
        role: (ancestor.getAttribute("role") || "").slice(0,30),
        testKind: testid.startsWith("conversation-turn") ? "conversation-turn" :
                  testid.startsWith("message") ? "message" :
                  testid ? "other" : "",
        main: ancestor.tagName.toLowerCase() === "main",
        visible: !!ancestor.getClientRects().length
      });
      ancestor = ancestor.parentElement;
    }
    matched.push({
      kind,
      exact: kind === "ready" ? /^CONTROL READY\.?$/.test(t) :
        kind === "wake" ? /^Проверь GitHub\. turn_id=[0-9]+$/.test(t) : false,
      length: t.length,
      visible: !!p.getClientRects().length,
      inMain: !!p.closest('main, [role="main"]'),
      chain
    });
  }
  return {
    status:"OBSERVED",
    readyState:document.readyState,
    mainCount:main.length,
    mainHasBootstrap,
    bodyHasBootstrap:body.includes(labels[0][1]),
    bodyHasReady:body.includes(labels[1][1]),
    messageRoles:document.querySelectorAll("[data-message-author-role]").length,
    dataMessageIds:document.querySelectorAll("[data-message-id]").length,
    conversationTurns:document.querySelectorAll('[data-testid^="conversation-turn"]').length,
    headingCount:document.querySelectorAll("h1,h2,h3,h4,h5,h6,[role=heading]").length,
    textNodesInspected:inspected,
    counts,
    matched
  };
}"""

def main() -> int:
    try:
        record = json.loads(CONTROL_PATH.read_text(encoding="utf-8"))
    except Exception as e:
        print(json.dumps({"status":"CONTROL_RECORD_UNREADABLE", "error":type(e).__name__}))
        return 2
    expected = conversation_id(str(record.get("chatgpt_control_url") or ""))
    if not expected:
        print('{"status":"CONTROL_URL_MISSING"}')
        return 2
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            browser = pw.chromium.connect_over_cdp(CDP, timeout=8000)
            matches = [
                page
                for ctx in browser.contexts
                for page in ctx.pages
                if conversation_id(page.url) == expected
            ]
            if not matches:
                print('{"status":"CONTROL_TAB_NOT_OPEN"}')
                return 3
            for page in matches[:2]:
                try:
                    result = page.evaluate(JS)
                except Exception as e:
                    result = {"status":"EVALUATE_FAILED","error":type(e).__name__}
                print(json.dumps(result, ensure_ascii=False, separators=(",",":")))
            # Never browser.close(): Chrome belongs to the local dispatcher.
        return 0
    except Exception as e:
        print(json.dumps({"status":"CDP_UNAVAILABLE","error":type(e).__name__}))
        return 3

if __name__ == "__main__":
    raise SystemExit(main())
