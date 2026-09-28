# Turn 68 — GPT counter-audit of Arena full-system audit

GPT completed an independent counter-audit of Arena's full-system Safe BIM / Archicad 29 / Tapir 1.5.9 audit.

Durable output:
- repo: `dvikt33-ux/safe-bim-layer`
- branch: `audit/gpt-counter-audit-arena-20260928`
- remote head: `59239ceac83529c1fb6ad5d97fdf3d74edacc848`
- report: `GPT_COUNTER_AUDIT_ARENA_20260928.md`
- Arena reconciliation task: `ARENA_TASK_RECONCILE_GPT_COUNTER_AUDIT_20260928.md`

Main corrections found by GPT:
1. GOST 2.307-2011 dimension minimums (10 mm contour, 7 mm parallel chains) are normative minima, not merely office/project policy; GOST R 21.101-2020 also contributes construction-drawing tick/extension rules.
2. Arena's suggested stock `GetElementsByType` filter by `compositeId` is invalid; exact Tapir filters are fixed context/visibility flags. Composite usage must be determined by enumerating relevant elements + minimal details, or by a new dedicated usage command.
3. Permanent/user Morphs must not be automatically delete/recreated merely to bypass `ModifyMorphs(body)` uncertainty. Automatic GUID replacement is restricted to Safe-BIM-owned temporary/operator Morphs unless dependency capture/replay is complete or explicitly approved.
4. `GetCollisions` and built-in Volume are candidate SEO verification rungs only; SEO-evaluated semantics remain live-gated by LT-C1/LT-C2.
5. `.mod` + Hotlink is the right route for reusable native BIM assemblies, but does not replace a linked local GSM/library-part library. Shared assets are split into linked library, module repository, and Favorites/template pack.
6. Future `atomic:true` must have rollback-aware response semantics; GUIDs created earlier in a rolled-back command must not be treated as durable.
7. Exact Tapir 1.5.9 Slab `Get3DBoundingBoxes` remains blacklisted; GPT recommends not intentionally reproducing a known process crash in the normal test sequence.
8. Morph topology validation must be component/manifold based; Euler characteristic is a diagnostic per connected component, not a universal sole acceptance formula.
9. Favorites are a good deterministic creation path for fonts, but arbitrary project audit by family name still needs `GetFonts/ResolveFontByName`.

Arena should now run a targeted reconciliation cycle only on these disputed points, then final static audit. Remaining uncertainty should be reduced to executable live tests.

`main` was not modified.
