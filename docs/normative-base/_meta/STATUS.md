# Normative-base status

Baseline date: **2026-09-30**

State: **research / audited core v0.2**.

Only rules whose document status, scope and clause were checked are placed in `rules/`. Unknown or project-dependent values are deliberately omitted rather than guessed.

## Confirmed replacement traps

- ГОСТ 26434-2015 -> **ГОСТ 26434-2025**, effective 2026-01-01.
- ГОСТ 9561-2016 -> **ГОСТ 9561-2025**, effective 2026-01-01.
- ГОСТ 25772-2021 -> **ГОСТ 25772-2025**, effective 2026-01-01.
- ГОСТ 23166-2021 -> **ГОСТ 23166-2024**.
- ГОСТ Р 21.101-2020 -> **ГОСТ Р 21.101-2026**, effective 2026-04-01.
- СП 131.13330.2020 -> **СП 131.13330.2025**, effective 2025-09-09.
- СП 42.13330.2016 -> **СП 42.13330.2026**, effective 2026-07-12.
- ГОСТ 475-2016 is still effective on the baseline date but is scheduled to be replaced by **ГОСТ 475-2026 on 2026-10-01**.
- ГОСТ 948-2016 remains current, but Amendment 1 changes the current type designations to **ПРБ/ПРП/ПРГ/ПРФ**; old ПБ/ПП/ПГ/ПФ library naming must not be treated as current marking without mapping.

## Current high-risk areas requiring project-specific checks

- masonry pier capacity and stability;
- lintel type, length, bearing and load;
- final precast slab selection, bearing and load capacity;
- fire-evacuation geometry and fire-compartment planning;
- accessibility routes;
- thermal envelope / condensation;
- daylight and insolation;
- acoustics;
- loads and structural limit states;
- foundations/geotechnical conditions;
- seismic design;
- HVAC, smoke protection, water/sewer coordination;
- roof/floor build-ups and manufacturer systems;
- local manufacturer product ranges and technical certificates.

The database must fail closed: absence of a verified rule means `manual_check`, not permission to invent a value.
