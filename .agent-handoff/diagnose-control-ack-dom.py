"""Read-only structural probe for the EXISTING ChatGPT CONTROL tab.

No message contents, tokens, URLs or cookies are printed. Does not navigate,
click, send, edit files, or mutate dispatcher/GitHub state.
"""
import json
import sys
from playwright.sync_api import sync_playwright

CONTROL = "https://chatgpt.com/c/6ad27341-1ea4-83eb-8238-5ce1cada094a"
JS = r"""() => {
  const marker = {
    boot:'Служебный чат 01 — CONTROL & BRIDGE',
    ready:'CONTROL READY',
    wake:'Проверь GitHub. turn_id=76',
    ack:'CONTROL ACK'
  };
  const visible = e => !!(e && e.getClientRects().length);
  const main = [...document.querySelectorAll('main,[role="main"]')];
  const clean = x => String(x||'').replace(/\u00a0/g,' ').trim();
  const bodyText = clean(document.body.innerText || '');
  const data = {
    body: Object.fromEntries(Object.entries(marker).map(([k,v])=>[k,bodyText.includes(v)])),
    scopes: main.map(m => ({
      visible:visible(m), length:clean(m.innerText).length,
      flags:Object.fromEntries(Object.entries(marker).map(([k,v])=>[k,clean(m.innerText).includes(v)]))
    })),
    selectorCounts:Object.fromEntries([
      '[data-message-author-role]','[data-message-author]',
      '[data-testid*="conversation-turn"]','article',
      'main .markdown','main .prose',
      '[data-testid*="message"]','[role="article"]',
      '[data-testid="stop-button"]'
    ].map(sel=>[sel,document.querySelectorAll(sel).length])),
    hits:{wake:[],ack:[]}, candidateElements:{wake:[],ack:[]}
  };
  const meta = el => ({
    tag:el.tagName.toLowerCase(),
    role:el.getAttribute('role'),
    testid:(el.getAttribute('data-testid')||'').slice(0,70),
    author:el.getAttribute('data-message-author-role')||el.getAttribute('data-message-author'),
    aria:el.getAttribute('aria-label') ? '[present]' : null,
    classes:String(el.className && typeof el.className==='string' ? el.className:'').split(/\s+/).slice(0,7),
    chars:clean(el.innerText||el.textContent).length,
    lines:clean(el.innerText||el.textContent).split(/\r?\n/).length,
    children:el.children.length,
    flags:Object.fromEntries(Object.entries(marker).map(([k,v])=>[k,clean(el.innerText||el.textContent).includes(v)]))
  });
  const walker = document.createTreeWalker(document.body,NodeFilter.SHOW_TEXT);
  while(walker.nextNode()) {
    const n=walker.currentNode,p=n.parentElement;
    if(!p || !visible(p) || p.closest('script,style,textarea,[contenteditable="true"],nav,aside'))continue;
    const text=clean(n.textContent);
    for(const k of ['wake','ack']) {
      if(!text.includes(marker[k]) || data.hits[k].length>=4)continue;
      let a=p, chain=[];
      for(let i=0;i<11&&a;i++,a=a.parentElement)chain.push(meta(a));
      data.hits[k].push({length:text.length,exact:text===marker[k],ancestors:chain});
    }
  }
  for (const key of ['wake','ack']) {
    const matches=[];
    for (const e of document.querySelectorAll('main *,[role="main"] *')) {
      if(!visible(e))continue;
      const t=clean(e.innerText||'');
      if(t.includes(marker[key]) && t.length < 20000)matches.push({el:e,len:t.length});
    }
    matches.sort((a,b)=>a.len-b.len);
    data.candidateElements[key]=matches.slice(0,6).map(v=>meta(v.el));
  }
  return data;
}"""

def main():
    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp("http://127.0.0.1:9223", timeout=8000)
        pages = [page for ctx in browser.contexts for page in ctx.pages
                 if page.url.split("?",1)[0].split("#",1)[0] == CONTROL]
        if len(pages) != 1:
            print(json.dumps({"status":"STOP_WRONG_TAB_COUNT","tabs":len(pages)},ensure_ascii=False))
            return 2
        result = pages[0].evaluate(JS)
        print(json.dumps({"status":"READ_ONLY_DOM_DIAG","data":result},
                         ensure_ascii=False,indent=2))
        return 0

if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        print(json.dumps({"status":"STOP_DIAG_ERROR","type":type(e).__name__},ensure_ascii=False))
        sys.exit(3)
