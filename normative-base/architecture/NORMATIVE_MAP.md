# Architectural normative map for a BIM/model-generation agent

**Verified baseline date:** 2026-09-30  
This map tells the agent which normative families must be resolved before drawing. It does **not** turn every document into an unconditional rule.

## 1. Resolution order before geometry is generated

For every design action:

1. Identify object type and project stage.
2. Identify project date and jurisdiction.
3. Resolve functional fire class / building function / occupancy / height / responsibility level / seismicity / climate / accessibility scope as applicable.
4. Check requirement status in the State Register of Requirements.
5. Check the current document and amendment status in the official Rosstandart/legal source.
6. Retrieve the exact clause/table.
7. Classify the datum as `hard_rule`, `conditional_rule`, `preferred_coordination`, `catalog_value`, or `requires_calculation`.
8. Resolve dimensional semantics: coordination / constructive / nominal product / rough opening / clear / finish.
9. Generate geometry only if all required conditions are known.
10. Run cross-discipline checks (KR, fire, MEP, accessibility, thermal, acoustic, daylight, sanitary).

If a required condition is missing, the correct action is `BLOCK_AND_REQUEST_INPUT`, not guessing.

---

## 2. Legal and project-documentation layer

Use:

- Federal Law No. 384-FZ — technical safety of buildings and structures.
- Federal Law No. 123-FZ — fire safety technical regulation.
- State Register of Requirements in ЕИС «Стройкомплекс.РФ» — current applicability/check source.
- PP RF No. 87 — composition/content of design documentation.
- ГОСТ Р 21.101-2026 — current SPDS baseline for design and working documentation (effective 2026-04-01; replaces 2020 edition).
- ГОСТ 21.501-2018 — architectural/construction working documentation.
- ГОСТ 21.201-2011 — conventional graphical symbols.

Do not use PP RF No. 815 as the current list of mandatory requirements; it lost force on 2024-09-01.

---

## 3. General dimensional system

Primary documents:

- ГОСТ 28984-2011 — modular coordination.
- ГОСТ Р 58938-2020 — general geometric accuracy.
- ГОСТ Р 58942-2020 — technological tolerances.
- ГОСТ Р 58944-2020 — functional tolerances.
- ГОСТ 21780-2006 — accuracy calculation.

Agent responsibilities:

- choose/validate coordination grids;
- prefer defined M/3M/6M/... modules where the standard says “preferably”;
- keep coordination and constructive dimensions distinct;
- never convert a modular preference into a false absolute ban on non-modular geometry;
- resolve current Russian replacements when an old standard cites obsolete accuracy documents.

Implemented machine rules: `rules/core-dimensional-rules.yaml`.

---

## 4. Structural grid, spans, slabs and load-bearing geometry

Primary documents:

- СП 20.13330.2016 — loads and actions;
- СП 22.13330.2016 — soil bases;
- СП 63.13330.2018 — reinforced concrete;
- СП 15.13330.2020 — masonry;
- СП 16.13330.2017 — steel structures;
- СП 64.13330.2017 — timber structures;
- СП 14.13330.2018 — seismic construction when applicable;
- СП 70.13330.2012 — load-bearing/enclosing construction execution;
- ГОСТ 9561-2025 — hollow-core floor slab product geometry.

### Slab layout engine

The architectural layout engine may use ГОСТ 9561-2025 type/coordination-size catalogues as candidate geometry, but final acceptance requires:

- support scheme;
- span/coordination geometry;
- actual constructive slab length/width and joints;
- design loads;
- openings/penetrations;
- bearing/support detail;
- seismic conditions if applicable;
- manufacturer working drawings for PB/other manufacturer-dependent products;
- structural engineer/calculation where required.

**Prohibited shortcut:** a single universal slab bearing depth.

Implemented product series: `rules/core-dimensional-rules.yaml`.

---

## 5. Masonry, wall thickness, openings, piers, lintels

Primary documents:

- СП 15.13330.2020 + current amendment — masonry structural design;
- ГОСТ 530-2012 — ceramic brick/stone product dimensions;
- ГОСТ 948-2016 + current amendment/correction — RC lintel products;
- СП 70.13330.2012 — execution layer.

Agent must distinguish:

- modular pier/opening coordination (ГОСТ 28984);
- masonry-unit dimensions (ГОСТ 530);
- actual bond/joint geometry;
- structural pier capacity/stability (СП 15 + loads);
- lintel product geometry vs lintel structural selection.

**Never accept a pier only because it fits a brick module.**  
**Never select a lintel only from opening width.**

Current baseline intentionally does not hard-code a universal mortar-joint thickness until the exact current execution clause/tolerance is extracted and audited.

---

## 6. Windows, doors, rough openings and façade interfaces

Primary verified documents:

- ГОСТ 23166-2024 — window and balcony blocks;
- ГОСТ 30971-2012 — window-to-wall installation joints;
- ГОСТ 28984-2011 — coordination of openings;
- relevant thermal, fire, daylight, acoustic and accessibility SPs.

Data model must have separate fields for:

`window_product_size`, `rough_opening_size`, `installation_joint`, `clear_opening`, `finish_opening`.

A window product size is not the wall rough opening.

Future extraction tasks:

- exact installation-gap ranges/conditions by joint system;
- door clear-opening rules by function/accessibility/fire;
- façade fire cutoffs and interface conditions.

---

## 7. Floor-to-floor and clear room heights

Three different concepts must remain separate:

1. coordination floor height — ГОСТ 28984;
2. clear room height — functional SP;
3. service/plenum depth — MEP + coordination requirements.

Verified clear-height rules are in `rules/functional-height-rules.yaml` for:

- multifamily residential rooms/kitchens and internal apartment circulation;
- general public rooms with permanent/mass occupancy;
- selected public-building exceptions with explicit conditions.

Special buildings (schools, preschools, medical, hotels, etc.) must resolve their dedicated SP/sanitary document before height generation.

---

## 8. Residential architecture

Primary:

- СП 54.13330.2022 — multifamily residential buildings;
- СП 59.13330.2020 — accessibility;
- СП 1/2/4.13130 — fire;
- СП 50.13330.2024 — thermal protection;
- СП 131.13330.2025 — climate;
- СП 52.13330.2016 — lighting/daylight;
- СП 51.13330.2011 — noise;
- sanitary rules/norms current on project date.

High-priority future extraction:

- apartment room-area minima and geometry conditions;
- entrance/tambour/corridor requirements;
- balconies/loggias;
- lifts and lift halls;
- refuse/service rooms;
- basement/technical-floor limits;
- daylight/insolation and acoustic adjacency checks.

---

## 9. Public buildings

Primary:

- СП 118.13330.2022 — public buildings;
- dedicated functional SP for the actual building type;
- СП 59.13330.2020 — accessibility;
- fire SPs;
- sanitary rules relevant to the function;
- MEP standards.

The general public-building SP is not allowed to override a dedicated school, preschool, medical, hotel, sports, cinema, retail, transport or other specialized rule when that rule applies.

---

## 10. Accessibility

Primary:

- СП 59.13330.2020 with current amendments;
- relevant functional SP and fire requirements.

Future machine-check families:

- accessible route continuity;
- clear widths/turning spaces;
- ramps and landings;
- entrance thresholds;
- elevators/platforms;
- accessible sanitary rooms;
- parking spaces and routes;
- signage/tactile requirements where geometry-relevant.

These must be clause-conditional; generic “wheelchair template dimensions” are not sufficient.

---

## 11. Fire safety architecture

Primary:

- Federal Law No. 123-FZ;
- СП 1.13130.2020 — evacuation routes/exits;
- СП 2.13130.2020 — fire resistance;
- СП 4.13130.2013 — limitation of fire spread and spatial/constructive solutions;
- other fire SPs depending on systems/function.

Before any fire-dimensional rule is executed, resolve at least:

- functional fire hazard class;
- building height / floor / underground status;
- occupancy and people count where required;
- fire compartment;
- room category where relevant;
- number/type of exits;
- accessibility interaction;
- sprinkler/smoke-control conditions when the clause depends on them.

**Prohibited:** hard-coded universal stair width, exit width, travel distance, fire-compartment area or door swing rule without clause conditions.

---

## 12. Site planning, access, parking

Primary:

- СП 42.13330.2026 — current urban-planning baseline from 2026-07-12;
- СП 113.13330.2023 — parking;
- СП 59.13330.2020 — accessible parking/routes;
- fire access requirements;
- local PZZ / GPZU / planning documentation / regional-local rules as applicable.

Do not use СП 42.13330.2016 as the current general baseline for a 2026-09-30 project.

Future extraction:

- setbacks and site planning conditions where nationally standardized;
- fire appliance access geometry;
- parking stall/aisle/ramp rules by parking type;
- pedestrian routes and accessible parking;
- refuse/service/loading zones.

Local planning documents remain project inputs and cannot be inferred from federal SPs.

---

## 13. Envelope, climate, daylight, noise, roofs and floors

Primary:

- СП 50.13330.2024 — thermal protection;
- СП 131.13330.2025 — building climatology;
- СП 52.13330.2016 — natural/artificial lighting;
- СП 51.13330.2011 — noise protection;
- СП 17.13330.2017 — roofs;
- СП 29.13330.2011 — floors.

Architecture-agent policy:

- insulation thickness = calculation, not template;
- glazing area = not chosen only from façade aesthetics;
- room adjacency must be checked acoustically where applicable;
- roof slope/layers/drainage depend on roof system, material and climate;
- floor assembly depends on use, moisture, loads, acoustic/thermal/fire conditions.

---

## 14. Sanitary layer (important 2026 cutover)

Current on 2026-09-30:

- СП 2.1.4284-26 — replaces СП 2.1.3678-20 from 2026-09-01;
- СП 2.4.2.4283-26 — replaces СП 2.4.3648-20 from 2026-09-01;
- СанПиН 2.1.3684-21 with current 2026 amendments;
- СанПиН 1.2.3685-21 current edition for hygienic norms.

This layer is critical for schools/preschools, service functions, sanitary conditions, microclimate/light/noise and other use-specific requirements.

---

## 15. MEP coordination relevant to architecture

At minimum track current:

- СП 60.13330.2020 — heating, ventilation and air conditioning (current amendments must be checked by project date);
- СП 256.1325800.2016 — electrical installations of residential/public buildings (current amendments must be checked by project date);
- water/sewer, smoke control, fire systems and other dedicated systems as applicable.

The architectural agent may reserve shafts/plenums/rooms only from actual engineering requirements or verified preliminary assignments. It must not invent shaft dimensions.

---

## 16. Planned rule packs

Priority order for clause-level extraction and tests:

1. `fire-egress.yaml` — exits, stairs, corridors, travel distances, fire compartments.
2. `accessibility.yaml` — accessible route, ramps, doors, sanitary rooms, parking.
3. `residential-planning.yaml` — room areas, widths, corridors, lifts, balconies/loggias.
4. `public-planning.yaml` — general public-building dimensional rules + special-function dispatch.
5. `masonry-layout.yaml` — verified joint/bond/execution tolerances + pier structural handoff.
6. `openings-lintels.yaml` — product/rough-opening/joint/lintel selection workflow.
7. `parking-site.yaml` — stalls, aisles, ramps, fire/access routes.
8. `daylight-insolation.yaml` — calculation inputs and geometry constraints.
9. `thermal-envelope.yaml` — climate/material/calculation workflow.
10. `roof-floor.yaml` — roof/floor rule dispatch by assembly/use.
11. `spds-drawings.yaml` — dimensions, marks, plans, sections, schedules, annotation output.

Each pack must ship with positive tests, negative tests and at least one “missing condition -> block” test.
