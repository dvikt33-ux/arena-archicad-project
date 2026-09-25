# Turn 65 — Arena dialogue round 3

No dispatcher code was changed. The proposed design is the turn 63 hold/reuse rule, checked against published dispatcher `a89580f` as contained in `4426965`.
Rounds 1 and 2 still stand. This does not replace them.

## Verdict

The three-way observation is the right direction, but it is not safe to implement as previously stated. Four gaps have to be invariants, not follow-up cleanup.

## 1. Hold can preserve a stale streak

Hold must not clear on `page=None` or a non-saved URL. That part is required, or the 60s restore cooldown still erases the streak.

It must also not keep `blank_checks` and `blank_since` forever. `blank_rebind_ready` is already true on time once `blank_since` is 30s old. A streak of 5, held for minutes or hours, then one empty observation of the saved URL, becomes rebind. That late observation may be a loading shell, not a blank chat.

Required rule: record `blank_last_at` on each increment. Hold does not move it. If the next matching observation is farther than one restore cooldown plus one restore attempt, start a new streak at 1 and a new `blank_since`. Do not rebind on that poll. A gap inside that bound continues the same streak, so the quoted 60s cycle can still reach 6. A positive disproof still clears at any age.

URL match with no mounted transcript root is hold, not an increment. A redirect shell can show the saved URL before the transcript exists.

## 2. The heading guard is not sufficient

Do not treat every `h1–h6` as unresolved DOM. A blank ChatGPT page still has chrome headings. That test would make a genuinely blank page never increment, and the deadlock returns.

Do not treat `composer_ready` plus `messages=[]` as blank either. `infer_turn_role` still returns `""` for `ChatGPT сказал:`. The same miss applies to any short label outside `you said`, `вы сказали`, `chatgpt said`, and `assistant`.

Required probe, scoped to the transcript root:

- Root mounted, no turn nodes, no non-empty heading inside it, composer may be ready: genuine blank, may increment.
- A turn node with text and an unrecognized role: clear.
- A heading inside the root with non-empty text and an unrecognized role: clear. This includes `ChatGPT сказал:` and unexpected labels such as `Du sagtest:` or `Vous avez dit :`. No language list is enough.
- A chrome heading outside the root, including `ChatGPT`, does not count.
- Root absent: hold. Do not increment and do not clear.

Unstructured text with no turn node and no heading still cannot be distinguished. That case must fail closed as hold, not as blank. The implementation must not claim it is solved.

## 3. Reuse conflicts with the current markers

`window.name` holds one mark. The registry is keyed by role and is the ownership that survives navigation, because ChatGPT can clear `window.name`.

A safe transfer is one assignment, before any `goto` or send: pop the restore registry entry, register that same page as rebind, and set `window.name` to the rebind mark only. After that, `find_restore_page` must not return it.

`find_control_page` calls `begin_control_restore` before `next_control_action`. If the cooldown has expired and the restore entry is already gone, restore action is `create` even while a rebind page exists. That is a second service tab. While `rebind_status` is `pending`, or bootstrap was sent and the URL is not committed, restore must not create a page.

`commit_rebind` ends at `save_control_record`. It does not close the old tab. The cleanup lines below `delete_retired_control_chat` are not part of `commit_rebind` and do not run on its return paths. Reuse must not assume that commit leaves one tab.

`rebind_completed` is true for the old URL and false for the new one. `blank_control_match` on the freshly committed URL with an empty parse and a ready composer is true. Without a grace hold, the new chat starts another streak and a second bootstrap. After commit, do not increment blank on that new URL until a parsed bootstrap or `CONTROL READY` has been seen, or until unresolved DOM clears the streak. A recent commit with an empty parse is hold.

Send `CONTROL_BOOTSTRAP` only after the page has left the saved conversation, and only when `rebind_bootstrap_sent` is false. A second entry to rebind must not send again.

## 4. Wake is not exactly once after commit

Current `process_gpt` sends only after `ensure_control_ready` returns ready, and it clears `wake_seen` when the bound identity differs. That is necessary, but it is not a guarantee.

Executed against `plan_control_page`: if the committed page is not open and the retired page still shows `CONTROL READY`, the plan is `use` / `identity` on the retired URL. `canonicalization_eligible` is true, and `rebind_status` is `done` rather than `pending`, so `find_control_page` canonicalizes back to the old chat. The pending wake can then be sent there. If a wake was already sent to the new identity, the flip clears the binding and sends a second wake.

Required wake invariants:

- Send only when the current page identity is the committed durable control, and the page is ready.
- Do not send on an empty identity, a provisional URL, or the retired URL.
- After commit, a retired page with `CONTROL READY` must not be selected and must not be canonicalized back.
- Identity change clears the binding once. It must not clear again after the binding matches the committed identity.
- One observed wake on that identity means no further send. If the parser never shows the wake, at most `MAX_WAKE_ATTEMPTS` (3), and the attempt counter is not reset while the identity stays the same. The inflight turn is not consumed.
- Do not promise exactly one network send if the wake text cannot be parsed. Promise no send to the wrong chat, no reset of a bound acknowledgement, and no second send after the wake is visible on the committed identity.

## Tests the implementation must include

1. Three matching blank polls, a `restore_wait` / `stale_url` hold inside the cooldown, then a matching poll continues the streak. A hold longer than one cooldown plus one restore attempt makes the next blank poll start at 1 and does not rebind.
2. Saved URL, transcript root absent: hold, even with `composer_ready`.
3. Empty mounted root and a chrome `h1` `ChatGPT`: may increment. `ChatGPT сказал:` inside the root, or a turn node with an empty role, clears. An unexpected in-root label clears too.
4. Transfer leaves one page object. Restore lookup misses it. Rebind lookup finds it after `window.name` is cleared. Pending rebind does not call `new_page`. Still on the saved URL: no bootstrap send. Second entry: no second send.
5. After commit, blank parse of the new URL does not increment. Retired page alone does not win `plan_control_page` and does not canonicalize. Ready new identity gets one wake; the next poll sends none. Unparsed wake does not reset attempts or consume the turn.

## Unchanged

`review-turn-56-arena-debate.md` was not edited. No Archicad Phase 0/1, `main`, or `arena/local-agent-v0` change belongs in this fix.
