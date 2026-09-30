# Turn 58 — Arena dispatcher audit

Audited dispatcher code at `6a7b4e3e9334ea4375acc83e6283610f3f2ae1a5`.
`2f90e26` only routes this audit; `dispatcher.py` is unchanged between those commits.
No Windows process was observed. The live evidence is the log quoted in the turn 58 signal.
No dispatcher code was changed.

## Verdict

The reported deadlock is confirmed end to end, not only in the blank predicate.

Saved CONTROL `https://chatgpt.com/c/6ab69cd1-9334-83eb-b03a-9e1b4b23c91a`
with `messages=0`, `composer=1`, `unavailable=0`, and `recovery_used=1`
stays on `page=equivalent`, `diag=zero_messages`, `action=wait`.
`blank_checks` stays 0, so `blank_rebind` never starts.
The wait tail is the only line that prints
`bootstrap не повторяю и новый чат не создаю`.
Reaching that line means the earlier reprovision, failed-closed, finalize,
replacement, rebind, and resume gates all returned false on that poll.

`checks=259/260` is only the unbounded wait counter.
`CONTROL_RECOVERY_CHECKS` is 3, but `recovery_used` closes recover first.

## Why it cannot escape

1. `find_control_page` keeps the saved conversation when
   `page_shows_unavailable` is false. A composer-ready empty page is
   `use` / `equivalent`. No restore page and no new tab are created.
2. `blank_control_match` returns false when `composer_ready` is true.
   `apply_blank_observation` then deletes `blank_for_url`, `blank_checks`,
   and `blank_since`. One composer-ready observation wipes any earlier count.
3. `diagnose_control` returns `zero_messages`. Composer readiness does not
   change that diagnosis, and a ready marker is absent.
4. `next_control_action` does not render rebind: the page is not unavailable,
   the diagnosis is not `unavailable`, and `blank_rebind` is false.
   Empty messages do not trip `hard_control_unavailable`.
   `rebind_allowed` requires unavailable. `recovery_allowed` is false because
   `recovery_used` is set. `send` is also false: a saved URL makes
   `bootstrap_was_sent` true, and recovery is already used.
5. The wait branch increments `unready_checks` and returns not ready.
   `process_gpt` therefore never reaches wake binding or a send.

The predicates were executed against the live inputs:
`blank_control_match` false, blank counters cleared, diagnosis
`zero_messages`, action `wait`, recovery closed, rebind closed.

`messages=0` means all three parsers returned nothing on that poll.
It does not by itself prove the DOM transcript is empty.
The deadlock holds either way.

## Recent fixes

Confirmed and not the cause of this stall:

- Encoded `local-chatgpt%3A` and `%3a` are provisional.
  `conversation_id` unquotes the path segment.
  `canonicalization_eligible` and `restore_observation_accepted` reject them.
  The follow-up test covers both spellings.
- Page-level deletion detection does not treat
  `Не удалось загрузить историю` or `Unable to load history` as unavailable.
  `Чат был удален` and `Chat was deleted` still match, including a marker
  beyond the first 6000 characters. The live `unavailable=0` agrees.
- `_inspect_restore` rejects a page when `page_shows_unavailable` is true,
  even if the parsed messages still contain `CONTROL READY`.
  `diagnose_control` also lets the page flag beat a cached ready marker.
- This live poll cannot grow tabs. `page=equivalent` returns the existing
  page, and `action=wait` never enters rebind or restore creation.
  Those creators still make at most one marked page and wait while cooling
  or failed. That was read, not executed against a browser.
- `wake_seen` is cleared when the bound control identity differs from the
  page returned by `ensure_control_ready`. The wake test covers old to new.
  The current stall returns not ready before that code runs, so the fix is
  unreachable until the deadlock is removed.

## Confirmed residuals

These are code facts. They are not the quoted stall.

- `hard_unavailable_text` still uses `CONTROL_UNAVAILABLE_MARKERS`.
  `не удалось загрузить` is a substring of `Не удалось загрузить историю`,
  and that call returns true. If that text is later parsed as a message and
  no bootstrap marker is present, `next_control_action` can set rendered and
  allow rebind. The page detector was narrowed; the message detector was not.
- A page whose deleted wording misses `CONTROL_PAGE_UNAVAILABLE_MARKERS`
  can still be accepted by restore when the composer is ready and the
  conversation matches. History-load text is intentionally not a page marker,
  so it does not block restore.
- `local-chatgpt%253A` unquotes once to `local-chatgpt%3A` and is not
  provisional. Single encoding is handled. Double encoding is not observed
  in this log.
- The accessibility fallback is third and only keeps headings whose label
  contains `you said`, `вы сказали`, `chatgpt said`, or `assistant`.
  Its regression test stubs `evaluate`; it does not run the role script.
  A heading outside those phrases is dropped. That may explain `messages=0`,
  but the log does not prove it.

## Unchanged

`review-turn-56-arena-debate.md` was not edited.
BIBIM remains the Phase 0/1 probe, not a proven fast path.
No Archicad stack, `main`, or `arena/local-agent-v0` change belongs in this fix.

## What to check next

Fix only the CONTROL stall, then show a regression for this exact record:
saved durable URL, zero parsed messages, composer ready, page not unavailable,
`recovery_used=1`, no rebind latch.

A sustained `zero_messages` observation must not be erased only because the
composer is ready, and it must not wait forever. One bounded rebind of that
saved URL is enough. Do not repeat bootstrap, do not create a chat on every
poll, and do not open a second rebind or restore tab.

Keep `Не удалось загрузить историю` from being treated as a deleted page.
If the message-level substring is narrowed, add that assertion too.
After the new page is durable, confirm `wake_seen` is bound to the new
identity and the pending wake is sent once.

Do not start the Archicad download or change the Phase 0/1 gates.
