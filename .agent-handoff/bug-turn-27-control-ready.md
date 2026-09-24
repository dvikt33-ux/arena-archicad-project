# GPT live diagnosis — turn 27

## Confirmed Windows evidence

Dispatcher 2.2.6 is installed and running on the actual Windows host.

Control record after migration:

```json
{
  "chatgpt_control_url": "https://chatgpt.com/c/WEB:54f304f1-2f88-4e38-a4ff-b566975e3d41",
  "name": "01 — CONTROL & BRIDGE",
  "dispatcher_version": "2.2.6",
  "bootstrap_sent": true,
  "bootstrap_migrated_from": "2.2.5"
}
```

State on turn 27:

```json
{
  "last_turn_id": 26,
  "inflight": {
    "turn_id": 27,
    "target": "GPT",
    "wake": "Проверь GitHub. turn_id=27",
    "submitted": false,
    "send_attempts": 0,
    "last_error": "Control chat bootstrap pending"
  }
}
```

Relevant live log:

```text
18:39:09 AI Dispatcher 2.2.6 запущен
18:39:09 Последний обработанный turn_id: 26
18:39:09 CONTROL: существующий control URL принят как bootstrap уже отправленный.
18:39:09 CONTROL: машинный чат закреплён: https://chatgpt.com/c/WEB:54f304f1-2f88-4e38-a4ff-b566975e3d41
18:39:58 NEW TURN 27 -> GPT
18:39:58 CONTROL: bootstrap уже отправлен, CONTROL READY ещё нет. Повтор не отправляю.
18:40:16 CONTROL: bootstrap уже отправлен, CONTROL READY ещё нет. Повтор не отправляю.
18:40:37 CONTROL: bootstrap уже отправлен, CONTROL READY ещё нет. Повтор не отправляю.
18:40:53 CONTROL: bootstrap уже отправлен, CONTROL READY ещё нет. Повтор не отправляю.
18:41:13 CONTROL: bootstrap уже отправлен, CONTROL READY ещё нет. Повтор не отправляю.
```

The GPT wake for turn 27 therefore never gets submitted. This is a real live regression/blocker in the reverse direction `Arena -> GitHub -> Dispatcher -> ChatGPT`.

## Required 2.2.7 fix

Fix this in `agent-handoff` only. Do not modify `main` or `arena/local-agent-v0`. Do not enable Phase 2/live mailbox.

Requirements:

1. Preserve the 2.2.6 fix: never resend the long bootstrap every poll.
2. Do not allow a migrated `bootstrap_sent=true` record to wait forever when no readiness can be observed.
3. Diagnose whether the saved control URL actually resolves to a usable ChatGPT conversation and whether `chatgpt_messages()` can see the bootstrap/assistant messages. Add concise diagnostic logging sufficient to distinguish: wrong/stale URL, zero messages/selector mismatch, bootstrap present without assistant response, or assistant response present but readiness marker mismatch. Do not dump full conversation contents.
4. Make readiness detection robust to the real ChatGPT DOM. Prefer explicit `CONTROL READY`, but do not depend on exact long bootstrap equality. If the bootstrap user message is present and the assistant has already produced a non-empty response after it, that should count as initialized unless there is explicit evidence of an error state.
5. Add bounded stale-control recovery. If an existing migrated/saved control URL remains unreadable or unready across a bounded number of checks/time, recover exactly once rather than waiting forever. Recovery may repair/re-provision the control chat, but must persist recovery state so it cannot create duplicate service chats each poll.
6. After recovery/readiness, submit the pending GPT wake exactly once and keep existing wake duplicate protection.
7. Preserve `CONTROL_RETRY_SECONDS`; no 90-second blocking waits.
8. Bump both dispatcher core/runtime to 2.2.7 and extend tests for: migrated 2.2.5 record + no visible ready; bootstrap + assistant response fallback; stale/unreadable control URL bounded recovery; no repeated recovery/bootstrap; pending wake proceeds after recovery.
9. Run syntax/tests and report exact results. If possible, make the Windows installer remain version-dynamic as today.

After the fix is committed, write the next handoff to GPT with commit SHA, changed files, tests, and the recovery behavior implemented.
