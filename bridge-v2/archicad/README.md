# Archicad Python backend for Arena Bridge v2

This directory adds a safe read-only Archicad 29 backend to the existing Arena Bridge v2.

## Architecture

`Arena/ChatGPT -> mailbox/action ID -> arena-bridge-v2.ps1 -> actions.ps1 -> run-archicad.ps1 -> archicad_runner.py -> Archicad JSON API`

The remote task must ultimately select only a fixed action ID. It must never send Python source, a shell command, an executable path, a module name, or an arbitrary Archicad JSON command.

## Requirements

- Windows with Archicad 29 running.
- Python 3.7+.
- Official Graphisoft Python package for Archicad 29.

Install once from PowerShell:

```powershell
py -3 -m pip install --upgrade "archicad==29.3000"
```

The Python Palette is not required. The official Python package connects to the JSON interface of a running Archicad instance.

If the bridge must use a specific Python executable, configure it locally once:

```powershell
$env:ARENA_ARCHICAD_PYTHON = 'C:\Path\To\python.exe'
```

For persistence, set the environment variable in Windows rather than placing the path in a remote task.

## Direct local tests

Open Archicad 29 and a project, then from `bridge-v2` run:

```powershell
.\archicad\run-archicad.ps1 -Action ping
.\archicad\run-archicad.ps1 -Action product_info
.\archicad\run-archicad.ps1 -Action wall_count
.\archicad\run-archicad.ps1 -Action selection
```

Expected success format:

```json
{"protocol":1,"backend":"archicad-python-json","action":"ping","ok":true,"result":{"alive":true}}
```

`selection` returns GUIDs and element types only for the current Archicad selection. Raw output is kept local by Bridge v2 and is not published to the public Issue.

## Bridge action IDs

The action table now contains these read-only actions:

- `ARCHICAD_PING`
- `ARCHICAD_PRODUCT_INFO`
- `ARCHICAD_WALL_COUNT`
- `ARCHICAD_SELECTION`

They are `Critical = false` because they do not modify the BIM model.

## Important: GitHub mailbox gate is still closed

The existing `arena-common.ps1` keeps a separate `$script:ActionIds` allowlist used by the mailbox policy and producer. At the moment that list still contains only the original Git actions. Therefore:

- direct local tests of the Archicad backend are ready;
- `arena-bridge-v2.ps1` has executable handlers for the `ARCHICAD_*` IDs;
- the live GitHub mailbox must **not** be considered enabled for `ARCHICAD_*` yet;
- `arena-mailbox-put.ps1 -Action ARCHICAD_PING` will remain blocked until the dedicated transport allowlist is intentionally extended and re-audited.

This is deliberate fail-closed behavior. Do not bypass the mailbox policy by accepting arbitrary commands or arguments.

## Exit codes

- `0` success
- `2` unsupported action
- `10` official `archicad` Python package missing
- `11` Archicad not running / connection failed
- `12` Archicad command failed
- `13` runner file missing
- `14` configured Python executable missing
- `15` Python not found

## Scope of phase 1

This phase proves the local transport/backend without changing the BIM model.

The Archicad 29 Python/JSON API supports additional mutating operations such as setting element properties. It also supports `ExecuteAddOnCommand`, which is the planned escalation path for full Safe BIM control: Python remains the transport/backend, while a trusted Archicad Add-On exposes narrowly scoped model-edit commands that the JSON API can invoke.

Do not add an action that executes arbitrary Python or arbitrary shell text. Future write actions must have a typed schema, fixed allowlist entry, validation, immediate read-back and an explicit write policy before they are enabled.
