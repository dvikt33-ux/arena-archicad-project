# GPT review — turn 35

Reviewed commit: `f6afaa01cfdb785329937b8862b5b69dc4bdeb15`
Dispatcher: 2.2.9
Branch: `agent-handoff`

## Result

Approved for live Windows validation.

Confirmed by code review:

- `/c/WEB:<id>` remains a valid conversation URL;
- positive identity evidence (bootstrap marker, CONTROL READY, or the pending wake) prevents a differing live conversation URL from being classified stale;
- canonicalization writes the observed normalized conversation URL while preserving `bootstrap_sent_at`, `recovery_used`, `recovery_reason`, and `recovered_from`;
- `ready_idle` requires the bootstrap message to be visible, generation to be inactive, the composer to be visible/enabled, and the grace period to have elapsed;
- `ready_idle` does not fire while a stop/generation control is visible;
- a recovered record with `recovery_used=true` cannot start another recovery;
- existing wake de-duplication remains unchanged;
- tests directly cover alias canonicalization, recovery metadata preservation, idle-composer readiness, generation-active rejection, and single-wake decision behavior.

Live validation still required on the actual Windows host after installing 2.2.9. Do not modify `main` or `arena/local-agent-v0`. Do not enable Phase 2/live mailbox.
