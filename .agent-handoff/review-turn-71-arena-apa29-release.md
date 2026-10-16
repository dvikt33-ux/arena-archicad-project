# Turn 71 — APA Archicad 29 release review

BLOCKED_LOCAL_SOURCES.

No baseline is selected. No integration is claimed. No release is approved. Nothing was built or opened in Archicad 29 from this session, and no readback was proven here. No code, branch, PLN, or APX was changed. Nothing was pushed from a local checkout.

This is the existing Arena / ChatGPT counter-audit only. It is not StudyArena and not a new bridge. The September 28 audit branches are the method, not a release artifact. Turn 69 already recorded that no Archicad session was run for that reconciliation.

## What was seen

Remote `dvikt33-ux/safe-bim-layer` only. These are starting leads, not a proven latest baseline.

- PR #48, draft, not merged, head `976c19cecebe`, base `feature/apa-authored-spatial-clearance-20261011`.
- PR #53, draft, not merged, head `286b1ae86144`.
- PR #73, draft, not merged, head `93557ed0cd59`. Its text describes a native A2 layout with plan, section, and elevation. That is not a proven same-model release: the PR is unmerged, later remote text does not close it, and the PDF was not opened here.
- PR #111, draft, not merged, head `61f56376e377`. Its own text says recovery `BLOCKED/NOT_RESTORED`, persistence `PARTIAL`, the test-copy bytes changed after UI exit, the source PLN was unchanged, and `A11.S03` remains `PARTIAL`.
- `research/apa-verified-results-hub-20261010` is `5c9b30402bb8c7993274dab1bf80b81c338ff4c6`, five minutes newer than the #111 head. Its message is a no-workflow readback proof, not a release.
- `main` is `d5695f435a58`, dated 2026-10-06, older than this feature chain. It is not the release tip.
- Remote drafts newer than the named chain already exist: #112–#119, updated 2026-10-16. #113 head `8f3d13d0ab10` says `NOT_LIVE_TESTED`. #116 head `af48fdd62e4e` records a saved working-PLN readback of 125 parents and says geometrical fidelity is still pending. #119 head `6f9611cabe4f` is a further draft modify. None is merged. None was opened here. Their existence contradicts treating #111 as the remote tip, and still does not make any of them the local baseline.

`arena-archicad-project` `agent-handoff` `be56c08914` only clarifies that the Archicad mailbox gate remains disabled. That bridge is not this release path.

## What is unseen

Local-only, and required before any baseline choice:

- Every Windows git root that contains APA or Archicad code, not only `C:\Users\Admin\Documents\arena-archicad-project`.
- Worktrees, HEAD SHAs, dirty state, and commits that are not on a remote.
- Which of those commits, if any, was installed, started, and opened in Archicad 29.
- The editable native PLN and the A2 PDF produced from that same model, plus the readback already on disk.

This sandbox cannot see those checkouts. `/home/user/arena-archicad-project` and `/home/user/archicad-collab` are not that inventory. The dispatcher cannot list arbitrary local git repositories, and this review does not claim that it can.

## Minimum release, not yet decidable

The smallest acceptable release remains one already existing path that can be installed and started, then opened in Archicad 29 as one editable native PLN, with one saved A2 PDF from that same model and a readback. No new MCP, router, registry, or research program. That decision waits on the local inventory below. Do not push local branches, do not write a PLN, and do not touch `main`, protected branches, or the current APX/PLN to answer it.

## Local data needed

Read-only, from the Windows machine, for each APA/Archicad git root: absolute path, `git rev-parse --show-toplevel`, `git worktree list`, branch, HEAD, `git status -sb`, and `git log --branches --not --remotes --oneline`. If one commit was already opened in Archicad 29, name that SHA, the install/start command already used, the PLN path, the A2 PDF path from that same model, and the existing readback path. If none, say none. Do not create files to answer.
