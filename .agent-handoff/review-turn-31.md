# GPT review — turn 31 / Dispatcher 2.2.8

Reviewed commit: `4107cec945f774babc4d7d15a5c78b8c580c2969`

Static review result: approved for live end-to-end validation.

Confirmed in code:
- `/c/WEB:<id>` is accepted as a conversation URL; it is not stale by syntax alone.
- `stale_url` is emitted only when navigation is observed away from the saved conversation URL.
- `save_control_url()` preserves `recovery_used`, `recovery_reason`, `recovered_from`, migration metadata, and unready counters in the same replacement write.
- `wait_for_conversation_url()` accepts the live URL form via `is_usable_control_url()`.
- message fallback covers `article[data-testid^='conversation-turn-']` and `[data-message-id]` and infers role from author attributes / accessible labels rather than treating the turn test id itself as a role.
- bootstrap resend protection, bounded recovery, `CONTROL_RETRY_SECONDS`, and wake de-duplication remain present.

Live Windows evidence supplied by the user confirms 2.2.8 installed successfully and recovery started for turn 31. At the instant the log was captured, provisioning of the replacement control chat had only just begun, so successful completion of the reverse GPT wake was not yet proven.

Next validation: perform a clean protocol ping Arena -> GPT after this review. No code changes unless the live ping fails. Do not modify main or arena/local-agent-v0. Do not enable Phase 2/live mailbox.
