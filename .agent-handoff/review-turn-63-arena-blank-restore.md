# Turn 63 — Arena dialogue round 2

No dispatcher code was changed. Audited published `a89580f` as contained in `e60eb0e`.
The Windows process was not observed. The live evidence is the log quoted in the turn 63 signal.
Turn 61 was the retry of round 1 and is already answered by the published turn 62 signal `25073d1`. This does not replace that answer.

## Verdict

Yes. This is a second confirmed deadlock. `BLANK_REBIND_POLLS` is 6 and `BLANK_REBIND_SECONDS` is 30, and that pair is unreachable while `restore_wait` / `stale_url` alternates with `restore_failed`.

`recovery_used=1` still closes recover, including for `stale_url`. `action` stays `wait`. The initial `blank_checks` 1→2→3 happened while the saved page was still a matching observation. Once restore takes over, the streak cannot finish.

## Exact reset

`apply_blank_observation` deletes `blank_for_url`, `blank_checks`, and `blank_since` whenever `blank` is false. `blank_control_match` is false when `page_url` is empty or is not the saved conversation.

`note_restore_failure` does not pop those fields. `save_control_record` preserves them. `commit_rebind` also pops them, but this log never reaches a commit. The clear on this path is only the false blank observation.

There are two `restore_wait` forms:

- No restore page during the 60s cooldown logs `page=restore_wait` and returns `None`. `page_url` stays empty, so the diagnosis is `zero_messages`, not `stale_url`. The counter is still cleared.
- An existing restore page during cooldown is `reuse_idle`. It logs `page=restore_wait accepted=...` and returns that page. If its URL is not the saved conversation and is not canonicalization-eligible, the diagnosis is `stale_url`, the blank match fails, and the counter is cleared.

The quoted pairing `restore_wait` + `stale_url` + `blank_checks=0` is the second form. Both forms use the same clear.

`restore_failed` returns the page. When that URL is still the saved conversation, messages are empty, and the composer is often ready, `a89580f` counts one blank observation. The previous clear makes it `blank_checks=1` and `diag=zero_messages`. `note_restore_failure` then starts another 60s cooldown. Later polls are `reuse_idle`; the quoted ones no longer match the saved URL, so they clear the counter again.

`CHECK_INTERVAL` is 5 seconds. One matching poll per 60s cooldown cannot reach 6 polls or a continuous 30s streak. Executed against the published predicates: a match followed by a non-match never leaves `blank_checks` above 1.

## Minimal safe change

Do not implement it here. Do not treat absence of the saved page as proof that the page is not blank.

Use three outcomes, and do not lower 6 polls or 30 seconds:

- Increment only when the observed page is the saved durable URL, bootstrap was already sent, parsed messages are empty, no unresolved turn or heading DOM is present, and the page is not unavailable, signed out, or generating. A ready composer may still match. That is the `a89580f` case.
- Clear only on a positive disproof of that same saved page: parsed messages, unresolved turn or heading DOM, generation, unavailable, or signed out.
- Hold when `page` is `None` or the URL is not the saved conversation. That covers both `restore_wait` forms, `stale_url`, and a failed candidate on another URL. Do not increment and do not pop the counters.

Do not count `restore_wait` as a blank poll. Do not clear `recovery_used`. Do not send bootstrap from the counter.

In the quoted cycle, `restore_failed` lands on the saved URL with `zero_messages` once per cooldown. Holding lets those positive observations accumulate. If that landing has unresolved DOM, it clears instead, so the turn 62 parser-miss guard still wins. Restore failure alone must not start rebind.

When the streak later completes, `begin_control_rebind` must not call `new_page` if a restore page already exists. Remark and reuse that page as the one service page. Leave the saved URL before the single rebind bootstrap. If the page is still that conversation, do not send. `rebind_bootstrap_sent` remains the one-send latch.

## Blank page versus parser miss

A genuinely blank established page is the saved durable URL, already bootstrapped, with all three queries empty: `[data-message-author-role]`, `TURN_SELECTOR`, and `h1–h6, [role=heading]`. The composer may be ready. The page is not unavailable, signed out, or generating.

A transcript that is present but unparsed has at least one of those nodes, while `chatgpt_messages` is empty because `infer_turn_role` returned `""`. `ChatGPT сказал:` does not contain `chatgpt said`, `вы сказали`, `you said`, or `assistant`. That page must clear, not increment.

Composer readiness and `messages==0` do not distinguish these cases. DOM presence with an unrecognized role does. This is the same condition required in turn 62. The hold rule does not weaken it.

## Unchanged

`review-turn-56-arena-debate.md` was not edited. BIBIM remains the Phase 0/1 probe. No Archicad, `main`, or `arena/local-agent-v0` change belongs in this fix.

## What to check next

Implement only the three-way observation and the restore-page reuse guard. Show a regression for this cycle: three matching blank polls, then `restore_wait` / `stale_url` leaves `blank_checks` unchanged, then a later matching `restore_failed` continues the same streak. A heading `ChatGPT сказал:` with `messages=[]` clears and does not increment. No second service tab, no second bootstrap, and `recovery_used` stays closed.
