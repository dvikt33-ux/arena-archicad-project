# Archicad Python backend for Arena Bridge v2

This directory adds a safe read-only Archicad 29 backend to the existing Arena Bridge v2.

## Architecture

`Arena/ChatGPT -> mailbox/action ID -> arena-bridge-v2.ps1 -> actions.ps1 -> run-archicad.ps1 -> archicad_runner.py -> Archicad JSON API`

The remote task can select only a fixed action ID. It cannot send Python source, a shell command, an executable path, a module name, or an arbitrary Archicad JSON command.

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

- `ARCHICAD_PING`
- `ARCHICAD_PRODUCT_INFO`
- `ARCHICAD_WALL_COUNT`
- `ARCHICAD_SELECTION`

These actions are read-only and therefore `Critical = false`.

A local mailbox producer can queue one of them using the existing producer, for example:

```powershell
.\arena-mailbox-put.ps1 -Action ARCHICAD_PING -DryRun
```

The normal Bridge v2 state machine still provides sequence fencing, replay protection, durable results and fail-closed repo identity checks.

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

This phase proves the end-to-end transport without changing the BIM model.

The Archicad 29 Python/JSON API supports additional mutating operations such as setting element properties. It also supports `ExecuteAddOnCommand`, which is the planned escalation path for full Safe BIM control: Python remains the transport/backend, while a trusted Archicad Add-On exposes narrowly scoped model-edit commands that the JSON API can invoke.

Do not add an action that executes arbitrary Python or arbitrary shell text. Future write actions must have a typed schema, fixed allowlist entry, validation and `Critical = true` until an explicit write policy is approved.
