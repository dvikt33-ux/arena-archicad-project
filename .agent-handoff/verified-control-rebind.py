"""One-time fail-closed CONTROL URL rebind for the already-running AI Dispatcher.

Modes:
  --probe: read-only CDP proof that the screenshot's target chat exists and
           contains a visible bootstrap and separate standalone CONTROL READY.
  --apply: change only .ai-dispatcher-control.json, with verified backup,
           while the dispatcher mutex is NOT held.
Never sends messages, modifies the GitHub signal, or clears inflight/latches.
"""
from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import os
from pathlib import Path
import sys
import time
from urllib.parse import urlsplit

OLD = "https://chatgpt.com/c/6ab69cd1-9334-83eb-b03a-9e1b4b23c91a"
NEW = "https://chatgpt.com/c/6ad27341-1ea4-83eb-8238-5ce1cada094a"
CDP = "http://127.0.0.1:9223"
HOME = Path.home()
CONTROL = HOME / ".ai-dispatcher-control.json"
STATE = HOME / ".ai-dispatcher-state.json"

# This is run as JavaScript in a read-only page.evaluate call. We intentionally
# avoid any response transcription and require a STANDALONE ready text node.
PROBE_JS = r"""() => {
    const nodes = document.querySelectorAll("main, [role='main']");
    const main = [...nodes].find(el =>
       el.getClientRects().length &&
       (el.innerText || "").includes("Служебный чат 01 — CONTROL & BRIDGE"));
    if (!main) return {bootstrap: false, assistant_ready: false, composer: false};
    let assistant_ready = false, bootstrap = false;
    const walker = document.createTreeWalker(main, NodeFilter.SHOW_TEXT);
    while (walker.nextNode()) {
       const node = walker.currentNode, parent = node.parentElement;
       if (!parent || !parent.getClientRects().length ||
           parent.closest('nav, aside, textarea, [contenteditable="true"], script, style')) continue;
       const text = (node.textContent || "").replace(/\u00a0/g," ").trim();
       if (text.includes("Служебный чат 01 — CONTROL & BRIDGE")) bootstrap = true;
       if (/^CONTROL READY\.?$/.test(text)) assistant_ready = true;
    }
    const field = document.querySelector('#prompt-textarea, [contenteditable="true"][role="textbox"]');
    const composer = !!(field && field.getClientRects().length);
    return {bootstrap, assistant_ready, composer};
}"""

def fail(message: str, code: int = 2) -> int:
    print("STOP:", message)
    return code

def read_json(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(data, dict):
        raise ValueError(f"Invalid JSON object: {path.name}")
    return data

def expected_state():
    record = read_json(CONTROL)
    state = read_json(STATE)
    saved = str(record.get("chatgpt_control_url", ""))
    if saved != OLD:
        raise RuntimeError("CONTROL_URL_CHANGED_OR_ALREADY_REBOUND")
    inflight = state.get("inflight")
    if not isinstance(inflight, dict) or int(inflight.get("turn_id", -1)) != 76:
        raise RuntimeError("EXPECTED_INFLIGHT_76_MISSING")
    if str(inflight.get("target", "")).upper() != "GPT":
        raise RuntimeError("EXPECTED_GPT_TARGET_MISSING")
    if int(state.get("last_turn_id", 0)) != 75:
        raise RuntimeError("UNEXPECTED_LAST_TURN")
    for field in ("rebind_status", "rebind_replacement_status",
                  "rebind_finalize_status", "rebind_reprovision_status"):
        if str(record.get(field, "")).lower() in {"pending", "started", "submitted"}:
            raise RuntimeError("CONCURRENT_REBIND_IN_PROGRESS")
    return record, state

def one_dispatcher_mutex_held() -> bool:
    if os.name != "nt":
        raise RuntimeError("WINDOWS_REQUIRED")
    kernel = ctypes.windll.kernel32
    kernel.OpenMutexW.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_wchar_p]
    kernel.OpenMutexW.restype = ctypes.c_void_p
    handle = kernel.OpenMutexW(0x00100000, 0, "Local\\AI_Dispatcher_22")
    if handle:
        kernel.CloseHandle.argtypes = [ctypes.c_void_p]
        kernel.CloseHandle(handle)
        return True
    return False

def probe() -> int:
    try:
        expected_state()
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.connect_over_cdp(CDP, timeout=8000)
            pages = [
                page
                for ctx in browser.contexts
                for page in ctx.pages
                if (page.url or "").split("?",1)[0].split("#",1)[0] == NEW
            ]
            if len(pages) != 1:
                return fail("TARGET_CHAT_NOT_UNIQUELY_OPEN_IN_DISPATCHER_CHROME")
            evidence = pages[0].evaluate(PROBE_JS)
            if not isinstance(evidence, dict) or not all(
                evidence.get(k) is True for k in ("bootstrap", "assistant_ready", "composer")
            ):
                print("PROBE_FLAGS:", json.dumps({
                    k: bool(evidence.get(k)) if isinstance(evidence, dict) else False
                    for k in ("bootstrap", "assistant_ready", "composer")
                }))
                return fail("TARGET_CHAT_IDENTITY_NOT_PROVEN")
            print("PROBE PASS: target is an open, hydrated, initialized CONTROL conversation.")
            print("No message submitted; no browser tab changed.")
            return 0
    except Exception as exc:
        return fail(f"PROBE_{type(exc).__name__}: {str(exc)[:100]}")

def apply() -> int:
    try:
        record, state = expected_state()
        if one_dispatcher_mutex_held():
            return fail("DISPATCHER_STILL_RUNNING_REFUSE_CONCURRENT_WRITE")
        # Reread immediately before committing to avoid stale state.
        record, state = expected_state()
        raw = CONTROL.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        backup = CONTROL.with_name(CONTROL.name + ".before-rebind-76-" + digest[:12] + ".bak")
        if backup.exists():
            if backup.read_bytes() != raw:
                return fail("BACKUP_PATH_COLLISION")
        else:
            with backup.open("xb") as fh:
                fh.write(raw)
            if backup.read_bytes() != raw:
                return fail("BACKUP_VERIFICATION_FAILED")
        record["chatgpt_control_url"] = NEW
        # Preserve bootstrap_sent, recovery_used, control_rescue_used,
        # all cooldowns, and every field of the persisted CONTROL record.
        temp = CONTROL.with_name(CONTROL.name + ".turn76-rebind.tmp")
        if temp.exists():
            return fail("STALE_TMP_FILE_EXISTS")
        payload = json.dumps(record, ensure_ascii=False, indent=2) + "\n"
        with temp.open("x", encoding="utf-8") as fh:
            fh.write(payload)
        if read_json(temp).get("chatgpt_control_url") != NEW:
            return fail("STAGED_URL_MISMATCH")
        if CONTROL.read_bytes() != raw:
            return fail("CONTROL_RECORD_CHANGED_DURING_REBIND")
        os.replace(temp, CONTROL)
        if read_json(CONTROL).get("chatgpt_control_url") != NEW:
            return fail("COMMIT_URL_MISMATCH")
        print("REBIND PASS: URL changed in CONTROL only; backup verified.")
        print("State/turn 76 and one-shot rescue latch unchanged.")
        return 0
    except Exception as exc:
        return fail(f"APPLY_{type(exc).__name__}: {str(exc)[:100]}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--probe", action="store_true")
    group.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    raise SystemExit(probe() if args.probe else apply())
