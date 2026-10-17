"""CONTROL assistant reply parsing and fail-closed Arena handoff publication."""
from __future__ import annotations
import base64, json, os, re, subprocess, urllib.request
from pathlib import Path
from typing import Callable
API_URL = "https://api.github.com/repos/dvikt33-ux/arena-archicad-project/contents/.agent-handoff/signal.json"
BRANCH = "agent-handoff"
TIMEOUT = 8
_ACK = re.compile(r"CONTROL ACK\s*[—–-]\s*turn_id=(\d+)\Z")
def _clean(value: object) -> str:
    return str(value or "").replace("\u00a0", " ").strip()
def _visible_turns(page) -> dict | None:
    """Read visible message containers and exact CONTROL markers from the active page."""
    return page.evaluate(r"""() => {
      const roots=[...document.querySelectorAll('main,[role="main"]')].filter(el=>!!el.getClientRects().length);
      const root=roots.find(el=>(el.innerText||'').includes('Служебный чат 01 — CONTROL & BRIDGE'));
      if(!root)return null;
      const clean=s=>String(s||'').replace(/\u00a0/g,' ').trim(), texts=[], walker=document.createTreeWalker(root,NodeFilter.SHOW_TEXT);
      while(walker.nextNode()){const n=walker.currentNode,p=n.parentElement;if(!p||p.closest('nav,aside,textarea,[contenteditable="true"],script,style')||!p.getClientRects().length)continue;const t=clean(n.textContent).replace(/\s+/g,' ');if(t)texts.push(t);}
      const turns=[],seen=new Set();
      for(const box of root.querySelectorAll('[data-testid*="conversation-turn"],article')){
        if(!box.getClientRects().length)continue;
        const rn=box.matches('[data-message-author-role],[data-message-author]')?box:box.querySelector('[data-message-author-role],[data-message-author]');
        let role=rn&&(rn.getAttribute('data-message-author-role')||rn.getAttribute('data-message-author')||'');
        const labels=[box.getAttribute('aria-label')||'',...[...box.querySelectorAll('h1,h2,h3,h4,h5,h6,[class*="sr-only"]')].map(x=>x.innerText||x.textContent||'')].join(' ').toLowerCase();
        if(!role){if(labels.includes('chatgpt said')||labels.includes('assistant'))role='assistant';else if(labels.includes('you said')||labels.includes('вы сказали'))role='user';}
        role=String(role||'').toLowerCase();role=role.includes('assistant')?'assistant':(role==='user'||role==='human'||role.endsWith(':user')?'user':'');
        const labelNode=box.querySelector('h1,h2,h3,h4,h5,h6,[class*="sr-only"]');
        const labelText=labelNode&&clean(labelNode.innerText||labelNode.textContent||'');
        const rawText=box.innerText||box.textContent||'';
        const text=clean(labelText?rawText.replace(labelText,''):rawText);
        const key=role+'\\n'+text;
        if(role&&text&&!seen.has(key)){seen.add(key);turns.push({role,text});}
      }
      return {boot:texts.some(t=>t.includes('Служебный чат 01 — CONTROL & BRIDGE')),ready:texts.some(t=>/^CONTROL READY\.?$/.test(t)),wakes:texts.filter(t=>/^Проверь GitHub\. turn_id=\d+$/.test(t)).slice(-8),turns};
    }""")
def _read_verified_ack_pair(page) -> list[dict]:
    """Read one response with distinct user/assistant provenance from the 2026 UI.

    Real ChatGPT DOM uses bg-user-message and MarkdownRoot-*; no article,
    .markdown, .prose or data-message-author-role nodes exist. The ACK <p>
    is split into inline child elements, so matching whole text nodes fails.
    """
    try:
        facts = page.evaluate(r"""() => {
          const clean = s => String(s || '').replace(/\u00a0/g, ' ').trim();
          const visible = el => !!(el && el.getClientRects().length);
          const main = [...document.querySelectorAll('main,[role="main"]')]
            .find(el => visible(el) &&
              clean(el.innerText).includes('Служебный чат 01 — CONTROL & BRIDGE') &&
              clean(el.innerText).includes('CONTROL READY'));
          if (!main) return null;
          const generating = [...document.querySelectorAll(
            '[data-testid="stop-button"],button[aria-label*="Stop"],' +
            'button[aria-label*="Останов"]'
          )].some(visible);
          if (generating) return null;
          const wakeRE = /^Проверь GitHub\. turn_id=(\d+)$/;
          const ackRE = /^CONTROL ACK\s*[—–-]\s*turn_id=(\d+)$/;
          const after = (a,b) => !!(a.compareDocumentPosition(b) &
            Node.DOCUMENT_POSITION_FOLLOWING);
          const userScope = '[class~="bg-user-message"],[class*="group/user-message"],' +
            '[data-message-author-role="user"],[data-message-author="user"],' +
            '[data-testid*="user-message"],[data-testid*="user-turn"]';
          const users = [...main.querySelectorAll(
            '[class~="bg-user-message"],[data-message-author-role="user"]'
          )].filter(visible).map(el => ({
            el, text:clean(el.innerText), match:clean(el.innerText).match(wakeRE)
          }));
          const wakes = users.filter(item => item.match);
          // The actual assistant body is a MarkdownRoot-* block. Its first
          // paragraph contains multiple child spans forming the ACK heading.
          const markdowns = [...main.querySelectorAll(
            '[class*="MarkdownRoot-"],.markdown,[class~="prose"],' +
            '[data-testid="assistant-message"]'
          )].filter(visible);
          const answers = [];
          for (const el of markdowns) {
            if (el.closest(userScope)) continue;
            const labelled = el.closest('[data-message-author-role],[data-message-author]');
            if (labelled) {
              const role = String(labelled.getAttribute('data-message-author-role') ||
                labelled.getAttribute('data-message-author') || '').toLowerCase();
              if (role !== 'assistant') continue;
            }
            const body = clean(el.innerText);
            const lines = body.split(/\r?\n/);
            const match = clean(lines[0]).match(ackRE);
            if (!match || lines.length < 2 || !lines.slice(1).join('\n').trim()) continue;
            answers.push({el,body,match});
          }
          const pairs = [];
          for (const wake of wakes) {
            const nextUser = users.find(item => item.el !== wake.el &&
              after(wake.el,item.el));
            const matches = answers.filter(item =>
              item.match[1] === wake.match[1] &&
              after(wake.el,item.el) &&
              (!nextUser || after(item.el,nextUser.el)) &&
              !item.el.contains(wake.el));
            if (matches.length === 1)
              pairs.push({wake:wake.text,answer:matches[0].body});
          }
          return {pairs};
        }""")
    except Exception:
        return []
    if not isinstance(facts, dict):
        return []
    pairs = facts.get("pairs")
    if not isinstance(pairs, list) or len(pairs) != 1:
        return []
    pair = pairs[0]
    if not isinstance(pair, dict):
        return []
    wake, answer = _clean(pair.get("wake")), _clean(pair.get("answer"))
    matched_wake = re.fullmatch(r"Проверь GitHub\. turn_id=(\d+)", wake)
    head = answer.splitlines()[0].strip() if answer else ""
    matched_ack = _ACK.fullmatch(head)
    if not matched_wake or not matched_ack or matched_wake.group(1) != matched_ack.group(1):
        return []
    if len(answer.splitlines()) < 2 or not "\n".join(answer.splitlines()[1:]).strip():
        return []
    return [{"role":"user","text":wake},{"role":"assistant","text":answer}]


def read_control_marker_fallback(page, record: dict, is_durable_control_url: Callable[[str],bool], same_conversation: Callable[[str,str],bool], bootstrap_marker: str, ready_marker: str, log: Callable[[str],None]) -> list[dict]:
    """Return only visible, role-labelled turns from the persisted CONTROL chat."""
    page_url=str(getattr(page,"url","") or ""); saved=str((record or {}).get("chatgpt_control_url") or "")
    if not is_durable_control_url(page_url) or not same_conversation(page_url,saved): return []
    try: facts=_visible_turns(page)
    except Exception: return []
    if not isinstance(facts,dict) or not facts.get("boot") or not facts.get("ready"): return []
    messages=[]
    # Prefer DOM-proven wake/answer pairs. Never invent an assistant ACK.
    verified = _read_verified_ack_pair(page)
    for item in (verified or facts.get("turns") or []):
        if not isinstance(item,dict): continue
        role=str(item.get("role") or "").lower(); text=_clean(item.get("text"))
        if role in {"user","assistant"} and text: messages.append({"role":role,"text":text})
    if not any(m["role"]=="user" and bootstrap_marker in m["text"] for m in messages):
        messages.insert(0,{"role":"user","text":bootstrap_marker})
    if not any(m["role"]=="assistant" and ready_marker in m["text"] for m in messages):
        messages.insert(1,{"role":"assistant","text":ready_marker})
    for wake in facts.get("wakes") or []:
        wake=_clean(wake)
        if re.fullmatch(r"Проверь GitHub\. turn_id=\d+",wake) and not any(m["role"]=="user" and m["text"]==wake for m in messages):
            # Preserve chronology if a role-labelled ACK precedes fallback wake.
            expected = wake.rsplit("=", 1)[-1]
            position = next((i for i, item in enumerate(messages)
                if item["role"] == "assistant"
                and _ACK.fullmatch(item["text"].splitlines()[0].strip())
                and _ACK.fullmatch(item["text"].splitlines()[0].strip()).group(1) == expected),
                len(messages))
            messages.insert(position, {"role":"user","text":wake})
    log("CONTROL: visible text fallback users={} assistants={}".format(sum(m["role"]=="user" for m in messages),sum(m["role"]=="assistant" for m in messages)))
    return messages
def parse_control_reply(messages: list[dict], turn_id: int) -> str | None:
    """Extract an ACKed assistant payload only when it follows this exact wake."""
    wake=f"Проверь GitHub. turn_id={int(turn_id)}"
    idx=next((i for i in range(len(messages)-1,-1,-1) if messages[i].get("role")=="user" and _clean(messages[i].get("text"))==wake),None)
    if idx is None:return None
    assistant=next((m for m in messages[idx+1:] if m.get("role")=="assistant" and _clean(m.get("text"))),None)
    if assistant is None:return None
    lines=_clean(assistant.get("text")).splitlines(); match=_ACK.fullmatch(lines[0].strip()) if lines else None
    if not match or int(match.group(1))!=int(turn_id):return None
    payload="\n".join(lines[1:]).strip()
    return payload or None
def _api_request(method: str, token: str, payload: dict|None=None) -> dict:
    data=json.dumps(payload,ensure_ascii=False).encode("utf-8") if payload is not None else None
    req=urllib.request.Request(API_URL+"?ref="+BRANCH,data=data,method=method,headers={
      "Accept":"application/vnd.github+json","Authorization":"Bearer "+token,"User-Agent":"AI-Dispatcher-2.2.19",
      "X-GitHub-Api-Version":"2022-11-28",**({"Content-Type":"application/json"} if data is not None else {})})
    with urllib.request.urlopen(req,timeout=TIMEOUT) as response:return json.loads(response.read().decode("utf-8"))
def _decode_contents(response: dict) -> dict:
    if response.get("encoding")!="base64":raise ValueError("signal encoding is not base64")
    data=json.loads(base64.b64decode("".join(str(response.get("content") or "").split()),validate=True).decode("utf-8"))
    if not isinstance(data,dict):raise ValueError("signal is not an object")
    return data
def _load_token() -> str:
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    if token:
        return token
    local = os.environ.get("LOCALAPPDATA", "").strip()
    if not local:
        return ""
    path = Path(local) / "AI-Dispatcher" / "github-token.dpapi"
    if not path.is_file():
        return ""
    safe_path = str(path).replace("'", "''")
    script = f"""
$p='{safe_path}'
$s=ConvertTo-SecureString (Get-Content -LiteralPath $p -Raw)
$b=[Runtime.InteropServices.Marshal]::SecureStringToBSTR($s)
try {{ [Runtime.InteropServices.Marshal]::PtrToStringBSTR($b) }}
finally {{ [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($b) }}
"""
    try:
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True, text=True, timeout=5, check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        return result.stdout.strip() if result.returncode == 0 else ""
    except Exception:
        return ""
def publish_next_signal(turn_id: int, reply: str, token: str|None=None) -> bool:
    """CAS turn N to N+1, verify persisted content, then allow local consume."""
    token=str(token if token is not None else _load_token()).strip()
    if not token:return False
    n=int(turn_id); wanted={"protocol":1,"turn_id":n+1,"target":"ARENA","source":"GPT","status":"ready","message":str(reply),"requires_codex":False}
    try:
        before=_api_request("GET",token); current=_decode_contents(before)
        if current!=wanted:
            if (int(current.get("turn_id",-1))!=n or str(current.get("target","")).upper()!="GPT" or str(current.get("source","")).upper()!="ARENA" or str(current.get("status","")).lower()!="ready" or current.get("requires_codex",False) is not False):return False
            sha=str(before.get("sha") or "")
            if not sha:return False
            body=json.dumps(wanted,ensure_ascii=False,indent=2)+"\n"
            _api_request("PUT",token,{"message":f"Publish CONTROL reply for turn_id={n}","content":base64.b64encode(body.encode("utf-8")).decode("ascii"),"sha":sha,"branch":BRANCH})
        after=_api_request("GET",token)
        return _decode_contents(after)==wanted and bool(after.get("sha"))
    except Exception:return False
