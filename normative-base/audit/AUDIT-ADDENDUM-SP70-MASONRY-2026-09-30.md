# Audit addendum — SP 70 / masonry — 2026-09-30

## Why this addendum exists

A deeper audit of Amendment No. 8 to СП 70.13330.2012 found **split effective dates**. The amendment as a whole was introduced on 2026-07-04, but a long enumerated set of clauses is explicitly deferred until **2027-03-01**. Several masonry clauses are in that deferred set.

Therefore a simplistic rule such as “Amendment 8 = entirely current” or “Amendment 8 = entirely future” is wrong.

## Effective-date resolution used by this database

### Effective on 2026-09-30

Amendment 8 wording that is not listed for deferred introduction is allowed to affect the current baseline. Example: revised clause 9.2.1 on bonding of regular masonry is current.

### Still using the prior wording on 2026-09-30

The following relevant masonry clauses are explicitly deferred by Amendment 8 until 2027-03-01 and therefore retain their previous wording on the present rule date:

- 9.2.4;
- 9.2.8;
- 9.2.12–9.2.15;
- 9.6.3;
- 9.6.5–9.6.7;
- 9.7.2;
- 9.7.4–9.7.5;
- 9.7.8;
- and other deferred clauses listed in the official amendment text.

Source: Amendment No. 8 to СП 70.13330.2012, approved by Ministry of Construction Order No. 353/pr dated 2026-06-03; general introduction 2026-07-04 with the enumerated exceptions introduced 2027-03-01.

## Verified current masonry values encoded after this pass

For regular-shaped brick/stone masonry on 2026-09-30:

- horizontal mortar joint: 12 mm;
- vertical mortar joint: 10 mm;
- execution tolerance, horizontal joint: -2/+3 mm;
- execution tolerance, vertical joint: -2/+2 mm.

These values are now in `rules/masonry-layout.yaml` and supersede the earlier conservative placeholder `MASONRY-JOINT-001` in `core-dimensional-rules.yaml` for the current rule date.

## Verified constructability rules added

The masonry pack additionally records, with their scope:

- current 9.2.1 bond ratios after the already-effective portion of Amendment 8;
- selected whole-brick condition for narrow piers/pilasters/columns and brick lintels/cornices;
- limitation on half-brick use;
- mandatory mortar filling of specified joints;
- maximum depth of raked/unfilled face joints;
- mortar continuity around ordinary brick lintels at piers <1 m;
- current ordinary brick-lintel reinforcement baseline under 9.2.8, flagged for re-audit on 2027-03-01;
- current large-format ceramic joint and slab-bearing conditions under 9.6.5/9.6.6, flagged for re-audit on 2027-03-01;
- current silicate-block joint and support-layer conditions under 9.7.4/9.7.5, flagged for re-audit on 2027-03-01.

## Structural pier boundary

СП 15.13330.2020 clause 7.5 is encoded only as a structural-calculation handoff:

- piers in walls weakened by openings are calculated with the relevant slenderness condition;
- if pier width is less than wall thickness, the pier is additionally checked in the wall plane and the design height for that check is the opening height.

The database does **not** invent a universal permissible pier width outside explicit special overlays (such as seismic requirements).

## Seismic overlay

СП 14.13330.2018 with current Amendments 2–4 is stored as a separate overlay. For masonry buildings, clause 6.14.10/Table 6.3 gives minimum pier widths, maximum opening widths and pier/opening ratios for seismicity 7/8/9, but explicitly requires the wall-element sizes to be determined by calculation as well.

The overlay is not applied until site seismicity and masonry category are resolved.

## Audit verdict

`SP70_SPLIT_EFFECTIVITY_RESOLVED = PASS`

`REGULAR_MASONRY_JOINTS_2026_09_30 = PASS`

`PIER_STRUCTURAL_BOUNDARY = PASS`

`SEISMIC_OVERLAY_SEPARATION = PASS`

`RECHECK_REQUIRED_ON_2027_03_01 = TRUE`
