# Recovery audit, turn 4

Date checked: 2026-09-24. Source of the task: `.agent-handoff/signal.json` on `agent-handoff` at `771b30736420b4755ae94966efd53f80007363ab`, `turn_id` 4, `target` ARENA. Nothing was deleted. `main` was not modified.

## What GitHub has

Repository `dvikt33-ux/arena-archicad-project`, public. Branches verified through the API and a fetch:

| Branch | SHA | Note |
|---|---|---|
| `main` | `df4427bb087c08fe19c2d23d50a6cfc588f621d5` | Unchanged. 41 blobs. |
| `arena/local-agent-v0` | `91c816b72dd8e91f9b349c9c99bb4a868ed03ded` | Parent `38097d7`. Not accepted. |
| `agent-handoff` | `771b30736420b4755ae94966efd53f80007363ab` | Control branch only. |
| `chatgpt/write-access-test` | `07dc9893b0a6017477c8d7f9371c611b9978afb4` | Old write probe. |

`safe-bim-layer` is a separate repository. It is not this workspace. Issue #1 has 10 comments, last update `2026-09-22T18:37:12Z`. No pull requests. No commit comments or check runs on `91c816b`.

Every tracked file in the local `arena-archicad-project` worktree matches the GitHub tree of `91c816b` by git blob SHA. Zero missing tracked files, zero content mismatches. The local object store in this sandbox did not contain `91c816b` until this audit fetched it; the file bytes were already present and identical.

The committed Archicad Collab baseline is already in GitHub history: commit `3af75fd` (`Initial import from Arena`), reachable from `main`.

## What was only in the workspace

Current `/home/user` snapshot candidates: 919 files, 114.2 MB. `du` reports 117 MB. The over-budget report was 211.8 MB, 1320 files, 401 files not saved. `1320 - 401 = 919`, so this sandbox is the saved remainder. There is no manifest of the 401 omitted files. They are not on disk and cannot be listed or restored from here.

Still only local before this recovery commit:

- Uncommitted Archicad Collab edits: 12 modified files, +419/-76, plus new `tests/test_audit2.py` and `tests/test_audit2b.py`. None of those blobs are in `arena-archicad-project` history.
- Archicad Collab gitignored data, 38.4 MB: `samples/tropa-archicad-s-kartinkami.pln` (28.13 MB), two identical Tapir 1.5.9 `.apx` files (4.05 MB each, same SHA-256), and evidence screenshots.
- `/home/user/bridge-audit-report.md` (52,478 bytes). Not in git history.
- Unique uploads: `REPORT.md`, `accollab.json`, `status.json`, `image-1.png`, and `server-01` through `server-03` including `.done.json`. Token fields in `accollab.json` are empty. Other upload images duplicate `archicad-collab/evidence/`.
- Generated and cache data that must not be treated as source: `local-agent/**/bin` and `obj`, 217 files, 70.6 MB; `/home/user/.dotnet`, 0.4 MB; `/home/user/.config` credentials. Those credentials were not copied here.

Copies already on GitHub, so not unique:

- `/home/user/bridge-v2` matches older blobs already in this repository.
- `/home/user/bridge-v2-design.md` is `bridge-v2/DESIGN.md`.
- `/home/user/LOCAL_AGENT_AUDIT.md` is `bridge-v2/LOCAL_AGENT_AUDIT.md`.
- `/home/user/repo-audit/` matches blobs already in history, including `main` files and the initial Collab import.

`archicad-collab` has no GitHub remote. `fsck` of both local repositories was clean. No tracked file is missing from either worktree.

## What this commit restores

This branch saves the unique workspace data that was not on GitHub:

- `recovery/archicad-collab/` — current Collab worktree, excluding `.git` and `__pycache__`.
- `recovery/archicad-collab.bundle` — local Collab history (`724ea981ce7bb864803c1cb41a5a1ff57ea5ecf5`).
- `recovery/archicad-collab-uncommitted.patch` — the uncommitted diff.
- `recovery/uploads-unique/` — uploads that are not byte copies of evidence images.
- `recovery/bridge-audit-report.md`.
- `recovery/SHA256SUMS.txt`.

No `bin/`, `obj/`, `.dotnet`, or credential file is included. `main` is not updated.

## What used the space

| Path | Size | Files | Fate |
|---|---:|---:|---|
| `arena-archicad-project/local-agent/**/bin` and `obj` | 70.6 MB | 217 | Generated. Gitignored, but the snapshot still stores them because `bin` and `obj` are not in the platform exclusion list. |
| `archicad-collab/samples`, `vendor`, `evidence` | 38.4 MB | 21 | Gitignored user/vendor artifacts. Not on GitHub before this recovery. |
| Rest of Collab, including `.git` | about 2 MB | | Source. Baseline already in history; edits saved here. |
| `arena-archicad-project` tracked tree and `.git` | about 2.4 MB | 67 tracked | On GitHub. |
| `uploads` | 1.0 MB | 16 | Mostly duplicate evidence images. |
| `.dotnet` | 0.4 MB | 107 | SDK cache, not source. |
| `repo-audit`, root copies of `bridge-v2`, docs | under 0.5 MB | | Already in GitHub history. |

The earlier 211.8 MB figure is 97.6 MB above this sandbox. That difference left with the 401 unsaved files. The likely contents are additional generated outputs or caches from the previous sandbox. That is an inference, not a file list. It is not proof that source was among them.

## Data loss

- No loss of `arena-archicad-project` source. `91c816b` is on GitHub and matches the worktree.
- No loss of the committed Collab baseline. It is in `3af75fd` on `main`.
- Uncommitted Collab work and the gitignored PLN, addon, and evidence were only local. They are in this recovery commit.
- The 401 files omitted from the over-budget snapshot are absent. If any of them were unique and never committed, they are lost and cannot be named from this sandbox. Nothing in the surviving 919 files indicates a missing tracked source file.

## How to stay under 128 MB

Do not delete this until the recovery commit is confirmed. After that, a new workspace stays far under 128 MB, and under 80 MB, if:

1. Snapshot or workspace policy excludes `bin/` and `obj/` the same way it excludes `build/` and `dist/`. That removes 70.6 MB of regenerable output. `.gitignore` alone does not keep them out of the snapshot.
2. Keep `samples/`, `vendor/`, and `evidence/` out of the agent workspace once this recovery branch exists. That is another 38.4 MB. Do not keep a second copy of the Tapir `.apx`.
3. Do not keep `/home/user/repo-audit`, `/home/user/bridge-v2`, or duplicate uploads beside the repository. They are already in GitHub history or in this recovery tree.
4. Do not put the .NET SDK, PowerShell, NuGet caches, or installers under `/home/user`.
5. Do not commit credentials from `/home/user/.config`.

Applying 1 and 2 to the current tree leaves roughly 8 MB of source, docs, and git metadata.

## Not done

Nothing was deleted or cleaned. `main` was not merged. The live mailbox was not enabled. `91c816b` is still not accepted. Windows platform acceptance was not requested.
