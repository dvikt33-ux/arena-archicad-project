# Normative Base — current status

**Branch:** `norms/architectural-core-2026-09-30`  
**Baseline date:** 2026-09-30  
**Base branch:** `agent-handoff`  
**Main project code modified:** no

## What is currently safe to consume

The current baseline provides source-backed, fail-closed rule packs for:

- modular coordination and dimensional semantics;
- current hollow-core slab product geometry/coordination series;
- ceramic brick nominal sizes;
- regular masonry joints/bonding/execution constraints valid on 2026-09-30;
- structural handoff for masonry piers weakened by openings;
- seismic masonry pier/opening overlay for 7/8/9-point conditions;
- window product / rough-opening / installation-joint separation and verified installation-gap rules;
- residential and general-public clear-height core rules;
- fire egress core geometry;
- accessibility core geometry;
- document-status registry and current/obsolete replacements;
- rule schema and guardrail regression cases.

## Mandatory load order

1. Read `sources/VERIFIED_DOCUMENTS.md` and project rule date.
2. Read `rules/core-dimensional-rules.yaml`.
3. Apply topic-specific rule packs; topic-specific packs supersede conservative placeholders explicitly named through `supersedes_rule_ids`.
4. Apply functional overlays (fire, accessibility, seismic, specialized building function).
5. Apply project-specific inputs: climate, site/seismicity, loads, materials, occupancy, fire class, manufacturer system, local planning documents.
6. If an applicability condition or required calculation is unresolved, block the geometry rather than guessing.

## Important date gate

**2027-03-01** — mandatory re-audit of СП 70.13330.2012 Amendment No. 8 deferred clauses, including multiple masonry clauses. Current 2026-09-30 masonry values that carry `valid_until_current_wording: 2027-02-28` must not be silently used after this date.

## CI / automated validation state

GitHub currently reports no commit status checks for this branch. `tests/guardrail-cases.yaml` is a stored regression specification, not evidence of an executed CI suite.

Before merging into a production model-generation path, add a runner that:

- parses all YAML/JSON files;
- rejects duplicate rule IDs;
- validates rule records against the schema where applicable;
- verifies `supersedes_rule_ids` references;
- executes arithmetic/conditional guardrail cases;
- blocks expired `valid_until_current_wording` records;
- flags current-date rules whose source status has not been refreshed within the chosen review interval.

## Not yet complete enough for unrestricted automatic generation

The following remain intentionally incomplete or calculation-dependent and must fail closed:

- full structural masonry calculation formulas and material tables;
- reinforced-concrete/steel/timber member sizing;
- foundations/geotechnical design;
- complete fire rules for every functional class;
- complete accessibility rules for every object/use case;
- specialized building packs (schools, preschool, healthcare, hotels, sports, retail/cinema, etc.);
- daylight/insolation calculation packs;
- acoustic calculation/adjacency packs;
- thermal-envelope calculation engine;
- complete parking/site/local-planning packs;
- roofs/floors/waterproofing assemblies;
- full MEP spatial reservation rules;
- full SPDS drawing/annotation production rules;
- manufacturer-specific product libraries and working drawings.

## Quality statement

This branch is a **conservative verified core**, not a claim that the entire Russian architectural normative system has been exhaustively encoded. The database is designed so that missing knowledge produces a block/request for inputs rather than a plausible-looking invented design decision.
