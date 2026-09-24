# Review turn 41 — Dispatcher 2.2.12

Status: approved for bounded live Windows validation only.

Confirmed from commit 643b72a05fd73dacb7ebeff57a5ec869cc0a98a8:

- WEB:<uuid> restore candidates are ordered canonical /c/<uuid> first, then saved WEB alias.
- Restore uses one marked page and does not navigate unrelated ChatGPT conversations.
- Failed restore records restore_attempted_at / restore_failures and enters a 60-second cooldown.
- During cooldown, an existing restore page is reused; if none exists, the dispatcher waits instead of creating another page.
- Successful restore canonicalizes only the control URL and preserves bootstrap_sent_at, recovery_used, recovery_reason, recovered_from, and bootstrap_sent.
- Bootstrap resend remains prohibited; wake de-duplication and 2.2.10 raw->api GitHub failover remain unchanged.
- Tests reported: py_compile OK; test_control_restore OK; test_control_page OK; test_control_bootstrap OK / inferTurnRole OK; test_signal_fetch OK.

Residual live-validation risk:

- restore_observation_accepted accepts a page solely from same conversation identity even if messages/composer are not ready. This avoids blocking on UI hydration, but a live test is still required to prove the restored conversation actually hydrates and pending turn 41 is delivered exactly once.

Do not declare the bridge complete until live Windows proves turn 41 -> GPT without unbounded tab creation and without bootstrap resend.
