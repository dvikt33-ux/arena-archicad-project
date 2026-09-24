# Workspace cleanup, turn 6

Date: 2026-09-24. Recovery tip before this commit: `6c770c1a980945e07b9b794edf1e3638a0be4a4d`. `main` was not changed. `arena/local-agent-v0` was not committed, pushed, or reset. Nothing was deleted from the recovery branch.

## Verification before deletion

`recovery/AUDIT.md`, `recovery/SHA256SUMS.txt`, `recovery/archicad-collab.bundle`, and `recovery/archicad-collab-uncommitted.patch` are present on `6c770c1`. The tree is not truncated, 218 entries.

Local files corresponding to 148 `SHA256SUMS.txt` rows matched size and SHA-256. The two skipped rows are the bundle and patch, which exist only in that GitHub commit. Every `samples/`, `vendor/`, and `evidence/` row matched. Every file in `/home/user/uploads` matched either `uploads-unique/` or an evidence hash in that file. All 27 `repo-audit` blobs and all 7 `/home/user/bridge-v2` blobs exist in the GitHub object store. The three root markdown copies also exist there.

## Before

- `/home/user`: 919 files, 119,781,225 bytes, 114.23 MB. `du` 117 MB.
- `arena-archicad-project` HEAD `38097d7ffd7b4dcb91e4ff4d883e1f3b8c857980`, status: six modified Local Agent files. Those files were not part of the cleanup.
- `archicad-collab` HEAD `724ea981ce7bb864803c1cb41a5a1ff57ea5ecf5`, status: 12 modified files and 2 untracked tests.

## Deleted locally

| Path | Files | MB | Why |
|---|---:|---:|---|
| `arena-archicad-project/local-agent/**/bin` and `obj` | 217 | 70.58 | Generated. Gitignored. |
| `/home/user/.dotnet` | 107 | 0.45 | SDK cache. |
| `/home/user/repo-audit` | 27 | 0.18 | Every blob already on GitHub. |
| `/home/user/bridge-v2` | 7 | 0.06 | Duplicate of blobs already on GitHub. The repository copy `arena-archicad-project/bridge-v2` was kept. |
| `/home/user/uploads` | 16 | 0.98 | Every file matched recovery hashes. |
| `archicad-collab/samples` | 1 | 28.13 | SHA-256 matched recovery. Gitignored. |
| `archicad-collab/vendor` | 3 | 8.10 | Both Tapir `.apx` copies had the same recovery hash. Gitignored. |
| ignored files in `archicad-collab/evidence` | 17 | 2.19 | PNG and HTML matched recovery and were gitignored. |
| root copies of `LOCAL_AGENT_AUDIT.md`, `bridge-v2-design.md`, `bridge-audit-report.md` | 3 | 0.10 | Blobs already on GitHub. |

Five tracked evidence files were removed with the directory and immediately restored from local git: `apimove-v11-output.txt`, `diag-2026-09-11-first.json`, `diag-2026-09-11-v1-rerun.json`, `diag-2026-09-11-v2.json`, and `tapir-commands.txt`. `.gitignore` ignores `evidence/*` but re-includes `*.txt`, `*.json`, and `*.md`, so those five are tracked. After restore, their SHA-256 matches the pre-cleanup snapshot.

## After

- `/home/user`: 521 files, 3,627,551 bytes, 3.46 MB. `du` 4.8 MB.
- Freed: 398 files, 116,153,674 bytes, 110.77 MB.
- `git fsck --full` for both repositories: exit 0.
- All 67 tracked files in `arena-archicad-project` and all 114 tracked files in `archicad-collab` have the same SHA-256 as before cleanup.
- Arena status is still only the same six modified Local Agent files. Collab status is still the same 12 modifications and 2 untracked tests. No new deletion remains.

## Left, and why

- `arena-archicad-project` source and `.git`: active repository. Branch not moved.
- `arena-archicad-project/bridge-v2`: repository copy, not the duplicate under `/home/user`.
- `archicad-collab` source, tests, docs, `.git`, and the uncommitted edits: working tree, not a regenerable cache.
- Tracked evidence text/JSON and `refs/tapir-1.5.8.json`: tracked files. The JSON is 660,670 bytes and is also on the recovery branch and in `safe-bim-layer`, but deleting it would change the Collab worktree. Left in place.
- `/home/user/.config`: credentials needed for GitHub access. Not copied and not deleted.

The workspace is below 20 MB and far below 80 MB. `main` remains `df4427bb087c08fe19c2d23d50a6cfc588f621d5`. Remote `arena/local-agent-v0` remains `91c816b72dd8e91f9b349c9c99bb4a868ed03ded` and is not accepted.
