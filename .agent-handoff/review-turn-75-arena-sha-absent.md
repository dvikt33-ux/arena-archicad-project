# Turn 75 — installed SHA is absent

RELEASE_NOT_PROVEN. No baseline is selected. The provenance pair is incomplete. Nothing was rescanned, pushed, saved, or exported.

The cited report is on private `dvikt33-ux/safe-bim-bridge` `main`, file `safe-bim-mailbox/gpt-live/results/apa-bdd-kr6-grillage-20261016T155302Z-8450ef02.json`. It is not in public `safe-bim-layer`.

Confirmed in that file:

- `project` is `C:\LocalAI\SafeBIM_Global_Library_Test_Projects\BDD дом - по чертежам 2022.pln`.
- `status` is `KR6_GRILLAGE_CONTACT_SAVED__OTHER_HOUSE_WORK_PENDING`.
- `initialGUIDs` and `finalGUIDCount` are both 261.
- `sourcePLN` is the different file `BDD дом .pln`, and `sourcePLNUnmodifiedOnDisk` is true.
- `backupSHA256` is a file hash, not a git commit. The file contains no 40-hex commit SHA and no branch or HEAD field.

The installed source SHA for this save is absent. It must not be inferred from any branch HEAD, including the candidate HEADs already listed. Do not manufacture it with a new save or export.

The A2 PDF remains uncited and is not the next question. This PLN is also marked `OTHER_HOUSE_WORK_PENDING`, so it is not a finished release object even after a SHA is known.

`arena-archicad-project` PR #3 is a separate open draft, `0dfc67d6b568c7fcbdb0444f432483dfe70dd1c6`, base `agent-handoff`. It was not reviewed or merged here, and it does not supply the missing SHA.
