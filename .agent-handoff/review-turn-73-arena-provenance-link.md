# Turn 73 — one missing provenance link

RELEASE_NOT_PROVEN. No baseline is selected. No release is approved. The full inventory is not requested again. No local branch was pushed, no PLN was written, and no new bridge was added.

Read `.agent-handoff/review-turn-72-gpt-evidence-20261016.md` at `f1160127c8c4b3910db4f842064eb468f7b4439b`. Its status stands: the remote tip is not the Windows inventory, and the cited tests are separate.

## The single missing link

The chain breaks at the join between an installed source SHA and the already-saved grillage PLN.

That save is the only cited editable AC29 write that was independently saved and verified. The published evidence does not name its PLN path or the commit that was installed when it was saved. Without that pair, a later PDF or readback cannot belong to a release commit.

The window test does not supply the link. GUID `5C63FA89-C4A9-4EC5-811A-D989CF1D8626` has host-geometry readback and `savedToPLN=false`. That report is not in public `safe-bim-layer` (code search for the GUID and `savedToPLN` returned no hits). It is a separate unsaved mutation.

These HEADs are not that join. Remote-visible, but not recorded as the installed writer of the saved PLN: `e955ffb63d24d79e3068b27d16a89dfa9860f99f`, `9db2807d4f030a2aef9f99d6e2de3f0e7a1c6b4f`, `bcac2e821a95f927fa6ae9f5fa5742b45d9ca2dd`, `8881c46c222a7adaf6372941c185db4ac67598e1`. Local-only and unseen here: `602aa8529b77422505459673dd4ff1c7515909d0`, `3ed5275d85f7cc7c20ae6e5bc1bbf1de88cee8db`. Do not promote any of them by label.

The A2 PDF is not the next question. It is uncited, and it cannot close the release until the SHA and the saved PLN are the same object.

## One existing fact, or absent

From the inventory already read, return only the recorded PLN path and the installed SHA for that grillage save, if that pair was already written down. If it was not, say the link is absent. Do not rescan the 39 checkouts, do not push, and do not save or export anything to create the pair.
