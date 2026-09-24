# Agent handoff protocol

Branch: `agent-handoff`

Control file: `.agent-handoff/signal.json`

## Wake command

When either agent receives the short message `Проверь GitHub`, it must read this protocol and then read `.agent-handoff/signal.json` from the `agent-handoff` branch before doing anything else.

Do not inspect only `main` and do not infer the current turn from the latest main-branch commit.

## Signal schema

```json
{
  "protocol": 1,
  "turn_id": 1,
  "target": "GPT",
  "source": "ARENA",
  "status": "ready",
  "message": "short human-readable summary"
}
```

Valid targets: `GPT`, `ARENA`, `NONE`.

The dispatcher wakes an agent only when `status` is `ready` and the `turn_id` is newer than the locally processed turn.

## GPT turn

If `target` is `GPT` and `status` is `ready`:

1. Read the current task/result material from GitHub that the signal refers to.
2. Perform the requested review, coding, test analysis, or other work.
3. Write durable output to GitHub. Prefer a normal feature branch or review artifact; do not put substantive code into this control branch.
4. When Arena should continue, update `.agent-handoff/signal.json` on `agent-handoff` with:
   - `turn_id`: previous value + 1
   - `target`: `ARENA`
   - `source`: `GPT`
   - `status`: `ready`
   - `message`: concise summary of what Arena should inspect/do
5. If no further agent action is needed, set `target` to `NONE` and `status` to `idle` instead.

## Arena turn

If `target` is `ARENA` and `status` is `ready`:

1. Read the current GitHub task/result material referenced by the signal.
2. Perform the requested coding, changes, tests, or analysis.
3. Commit durable work to the appropriate feature branch/repository location.
4. When GPT should review or continue, update `.agent-handoff/signal.json` on `agent-handoff` with:
   - `turn_id`: previous value + 1
   - `target`: `GPT`
   - `source`: `ARENA`
   - `status`: `ready`
   - `message`: concise summary of what GPT should inspect/do
5. If no further agent action is needed, set `target` to `NONE` and `status` to `idle` instead.

## Safety / loop rules

- Never decrement or reuse `turn_id`.
- Never emit the next handoff before durable GitHub output for the current turn exists.
- Never modify `main` merely to signal another agent.
- Never treat the wake message itself as the task; GitHub is the source of truth.
- If the signal targets the other agent, do not act on that turn.
- If the same `turn_id` is seen again, do not repeat the work.
- If the control file is malformed or inconsistent, stop and report the error instead of guessing.
