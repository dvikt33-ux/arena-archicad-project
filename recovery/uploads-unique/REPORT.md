# ACCOLLAB — live test report

Date: 2026-09-18

## Result

Validated rerun passed against Archicad 29.0.0.3000 RUS on port 19724.
The project contained 393 elements (all 393 reported as beams). Three server
messages were imported one by one. Every operation returned `APPLIED` with a
move vector of exactly `x=0.5, y=0.0, z=0.0`. A final independent checksum
read from Archicad matched the expected `after` state for every operation:

| File | Element GUID | Result |
|---|---|---|
| server-01.json | 3E760DF0-A6BB-4D44-80BA-E267ECC04F1D | MATCH |
| server-02.json | 18AFDD91-F25A-4610-AEE4-AB08BAD9A93F | MATCH |
| server-03.json | A8F481C3-8D50-4082-A567-AA6EC811478F | MATCH |

Final status: `outbox_pending=0`, `conflicts_open=0`, no warnings and no
errors. `conflicts` returned `(konfliktov net)`.

## Defects found and fixed during the test

1. A remote move was recorded as a local change by the following watcher tick.
   Cause: applying an operation did not advance that element in the watcher
   baseline. Fix: `Store.complete_application()` atomically advances the
   baseline when it still equals the operation's declared `before` checksum,
   and the applier calls it only after a confirmed movement.

2. The test-letter generator rounded all X coordinates to four decimal places.
   Archicad preserved greater precision for a beam end coordinate, so the
   expected checksum could differ despite the correct physical move. Fix:
   preserve native coordinate precision in `tools/make_server_files.py`.

3. `MoveElements` was accepted based on the request response alone. Fix: the
   applier now requires an explicit successful execution result and reads the
   element back to verify its expected checksum. It also recovers safely if a
   previous process died after Archicad completed a move but before the local
   receipt was saved.

The first diagnostic run produced one false outgoing operation before the
baseline defect was corrected. It was removed from the local database and its
file was retained as `outbox/*.false-echo.json` for evidence. The validated
rerun uses the separate `validated-run/` directory and is clean.

## Artifacts

- `validated-run/status.json`
- `validated-run/server-files/`
- `validated-run/inbox/*.done.json`
- `outbox/*.false-echo.json` (first-run diagnostic evidence only)

## Project composition probe

The final live probe on port 19724 returned 393 elements: `Beam=393`.
There were no `Line` elements and no elements of any other type in this test
project. The generator selected the first three movable beams and skipped
zero elements before producing its three test letters. This beam-only project
is not representative of a mixed production model and should be recorded as
a test limitation for the next run.
