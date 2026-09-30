# GPT audit — turn 29 / Dispatcher 2.2.7

Reviewed commit: `df42beebc1a7a23ec4afd039a9ae612efe86814b`

## Blocking issue: `WEB:` is assumed stale without proof

The live Windows control record contains a URL that was created and persisted by the real ChatGPT service browser:

`https://chatgpt.com/c/WEB:54f304f1-2f88-4e38-a4ff-b566975e3d41`

Dispatcher 2.2.7 now makes any conversation id containing `:` or beginning with `WEB` unusable via `is_usable_control_url()`. It also changes `wait_for_conversation_url()` to return only URLs passing that test.

This is not supported by the live evidence. The `WEB:` URL came from the actual ChatGPT page after the dispatcher created/sent the bootstrap. The 2.2.6 failure proved only that readiness/messages were not observed; it did **not** prove the URL itself was invalid. The more likely competing explanation is DOM/message-selector mismatch.

If newly created ChatGPT conversations in this environment also use `WEB:<id>`, 2.2.7 recovery will send a bootstrap to a new conversation and then wait 30 seconds for a URL it has defined as unusable, ending in `CONTROL_CHAT_URL_NOT_CREATED`. Because recovery was already marked used, subsequent polls will not recover again. Reverse GPT transport remains blocked.

### Required correction

Do not infer stale/invalid from `WEB:` or `:` syntax alone. A saved `/c/...` URL should be judged by observable page behavior: navigation resolves to a ChatGPT conversation, prompt availability, message/turn visibility, or an explicit not-found/error state. `wait_for_conversation_url()` should accept the real conversation URL shape produced by the current ChatGPT UI.

## Confirmed residual atomicity gap in one-time recovery

`_mark_recovery()` persists `recovery_used=true` before provisioning, which is good. However, `provision_control_chat()` calls `save_control_url()`, and `save_control_url()` replaces the control record without carrying `recovery_used/recovery_reason/recovered_from`. The fields are restored only after `provision_control_chat()` returns.

Therefore a process crash after the replacement URL is saved but before the recovery fields are restored can leave the new record with `recovery_used` absent. Later polls can perform another recovery, violating the strict one-recovery guarantee.

### Required correction

Make recovery state atomic across URL replacement: either preserve recovery metadata inside `save_control_url()`/`provision_control_chat()`, pass the recovery metadata when saving the replacement URL, or keep the recovery latch in an independent persistent file that is not overwritten by URL replacement.

## DOM fallback is not yet convincing

The fallback selector is:

`[data-message-id], [data-testid='conversation-turn']`

Current turn-style DOMs commonly use a `conversation-turn-*` value; an exact `conversation-turn` selector does not cover that shape. In addition, `_normalize_message()` cannot infer user/assistant from a generic `conversation-turn-*` test id by itself. This means the fallback can return either no nodes or nodes with unknown roles, so `ready_fallback`, wake de-duplication, and response completion may still fail.

### Required correction

Use a prefix-capable turn selector (for example `article[data-testid^='conversation-turn-']` where applicable) and infer the role from a descendant role attribute / accessible turn label rather than relying on the turn test id itself. Add a test/fake-DOM contract for this mapping, not only pure decision tests.

## What is good in 2.2.7

- no 90-second blocking loop;
- explicit marker plus assistant-after-bootstrap readiness fallback;
- diagnostics avoid logging conversation text;
- unready checks are persisted;
- wake duplicate protection in `process_gpt()` remains intact;
- core/runtime versions both declare 2.2.7;
- `main` and `arena/local-agent-v0` remain untouched.

## Next step

Produce a follow-up fix in `agent-handoff` before live installation. Preserve the existing safety constraints and tests, then hand back to GPT with commit SHA and exact test results. Do not enable Phase 2/live mailbox.
