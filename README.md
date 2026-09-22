# arena-archicad-project

## Arena Bridge

- v1 (audit snapshot, kept for rollback): `bridge-audit/`
- v2 (current executor + router): `bridge-v2/`

First check on Windows, no network and no GitHub:

```
cd bridge-v2\tests
powershell -NoProfile -File .\smoke-test.ps1
```

Expected last line: `ALL SMOKE TESTS PASSED`. Run instructions for the live bridge are in `bridge-v2/README.md`.
