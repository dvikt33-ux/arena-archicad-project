# Normative Base for Architectural Model Generation

**Audit date:** 2026-09-30  
**Jurisdiction:** Russian Federation  
**Purpose:** source-backed constraints for architectural/BIM model generation and checking.

This directory is intentionally conservative. A rule is admitted only when its document status, effective date and source clause have been checked. “Typical practice”, catalogue habits and remembered values are not hard rules.

## Source priority

1. State Register of Requirements (ЕИС «Стройкомплекс.РФ») — applicability of requirements in construction/expertise.
2. Official Rosstandart fund — status/effective dates of GOST/SP and amendments.
3. Official legal publication / registered sanitary acts — laws, Government decrees, SanPiN/sanitary SP.
4. Full text of the current normative document — exact clause/table used by a rule.
5. Manufacturer working drawings/catalogues — only for product-specific geometry and only after the normative layer permits it.

> PP RF No. 815 is **not** used as a current mandatory-list source: it lost force on 2024-09-01. Current applicability is checked through the State Register of Requirements.

## Rule classes

- `hard_rule` — exact requirement may be checked automatically when all applicability conditions are known.
- `conditional_rule` — exact requirement, but project properties/classification are required before applying it.
- `preferred_coordination` — normative preferred modular coordination; non-compliance is not automatically a legal violation.
- `catalog_value` — standardized product/type/size; availability or structural adequacy is not implied.
- `requires_calculation` — must be selected/verified by structural, thermal, fire, acoustic, lighting or other calculation.
- `do_not_infer` — explicit guard against converting a common practice or incomplete datum into a design rule.
- `draft_not_effective` — draft or approved future change; must never affect current model generation.

## Mandatory dimensional separation

The agent must keep different dimensions as different semantic fields:

- `coordination_dimension` — modular/axis coordination size;
- `constructive_dimension` — actual design size of an element after joints/gaps/bearings are resolved;
- `product_nominal_dimension` — standardized/catalogue product dimension;
- `rough_opening_dimension` — wall opening prepared for installation;
- `clear_dimension` — clear passage/clear room/clear opening dimension;
- `finish_dimension` — dimension between finished surfaces.

These values must never be silently substituted for one another.

## Non-negotiable agent policy

1. Every automatic rule must contain `source_document`, `source_clause`, `effective_from`, `verified_as_of` and a source URL.
2. If a rule depends on building function, fire class, responsibility level, height, seismicity, climate, accessibility, load, material strength, manufacturer system or another missing project property, do **not** guess it.
3. A GOST product size is not proof that the product is structurally suitable.
4. A modular preference is not a universal prohibition on non-modular dimensions.
5. Do not auto-select slab bearing depth, lintel, masonry pier width, wall thickness, reinforcement, fire resistance, insulation thickness, stair width, evacuation width or opening size from a single “typical” number.
6. Before a project audit, re-check the document status and effective dates. Future amendments and drafts are quarantined.
7. Where an older standard cited by a still-current document has been replaced in the Russian Federation, use the current Russian replacement after checking the reference type and applicability.
8. If two sources conflict or the current wording cannot be verified, classification is `blocked_pending_audit`; no geometry may be generated from that datum.

## Directory

- `sources/VERIFIED_DOCUMENTS.md` — current verified document map and status traps.
- `rules/core-dimensional-rules.yaml` — machine-readable high-confidence rules for modular coordination, slabs, masonry products and openings.
- `audit/AUDIT-2026-09-30.md` — audit passes, rejected assumptions and future/draft quarantine.
- `architecture/NORMATIVE_MAP.md` — which normative families an architectural agent must consult by design task.

## Current scope

The first verified core covers:

- modular coordination and dimensional semantics;
- geometric accuracy/tolerances;
- hollow-core floor slab types and coordination dimensions;
- ceramic brick product dimensions;
- masonry/lintel guardrails;
- windows/opening installation guardrails;
- current document families for AR/KR, residential/public buildings, accessibility, fire safety, thermal protection, climate, daylight, noise, roofs, floors, parking, sanitary requirements and SPDS.

Detailed numeric extraction for functional room heights, stairs/ramps, evacuation, sanitary rooms, accessibility clearances, daylight/insolation and fire compartments is deliberately **not** hard-coded until each conditional clause has been extracted and tested against its applicability conditions.