# Verified normative document register

**State date:** 2026-09-30.  
This is a status/index layer, not a substitute for reading the exact clause. Before converting a document into geometry, the exact clause/table must also be stored in a rule record.

## Legal/applicability layer

| Document/source | Verified state | Use in the agent |
|---|---|---|
| Federal Law No. 384-FZ, Technical Regulations on Safety of Buildings and Structures | governing technical-regulation layer | top-level building safety framework; verify current requirements through the State Register |
| State Register of Requirements, ЕИС «Стройкомплекс.РФ» | current mechanism | verify whether a requirement is included/applicable for expertise/design |
| PP RF No. 815 of 28.05.2021 | **lost force 2024-09-01** | never use as the current mandatory-list source |
| PP RF No. 87 of 16.02.2008, composition/content of project documentation | current edition checked to 21.10.2025; validity limited to 2028-09-01 | structure/content of project documentation; not a dimensional design catalogue |

State Register: https://xn--e1ajkj.xn--80ajpfhbgomfh1b.xn--p1ai/  
PP No. 87 current legal text: https://www.consultant.ru/document/cons_doc_LAW_75048/

## Dimensional coordination and accuracy

| Document | Status on 2026-09-30 | Notes |
|---|---|---|
| ГОСТ 28984-2011 — Modular coordination of dimensions | **active**; correction IUS 6-2022 | core M/3M/6M/... coordination rules |
| ГОСТ Р 58938-2020 — Geometrical accuracy, general | **active** from 2021-01-01 | Russian replacement to use instead of ГОСТ 21778-81 |
| ГОСТ Р 58942-2020 — Technological tolerances | **active** from 2021-01-01 | Russian replacement to use instead of ГОСТ 21779-82 |
| ГОСТ Р 58944-2020 — Functional tolerances | **active** from 2021-01-01 | Russian replacement to use instead of ГОСТ 26607-85 |
| ГОСТ 21780-2006 — Accuracy calculation | **active** | calculation of geometric accuracy |

Official cards:
- https://protect.gost.ru/gost/details/1c17643f-bf43-456f-a27c-dab6875a1514
- https://protect.gost.ru/gost/details/37cb81b5-7a3e-400f-98e9-768de84639fb
- https://protect.gost.ru/gost/details/542935c4-f5f6-457d-803e-c8110ae4dd59
- https://protect.gost.ru/gost/details/c6384f52-fbfb-4273-808c-0ca40a51d02b
- https://protect.gost.ru/gost/details/91b1293a-88a8-40b7-8899-0998ca1ea057

### Important cross-reference trap

ГОСТ 28984-2011 clause 6.11 still names older accuracy standards. In the Russian Federation, ГОСТ 21778-81, ГОСТ 21779-82 and ГОСТ 26607-85 have been superseded for use by ГОСТ Р 58938-2020, ГОСТ Р 58942-2020 and ГОСТ Р 58944-2020 respectively. The agent must resolve such national replacements instead of blindly following a stale reference list.

## Structures / products affecting architectural geometry

| Document | Status on 2026-09-30 | Model-use boundary |
|---|---|---|
| СП 15.13330.2020 — Stone and reinforced masonry structures | **active**, Amendment No. 1 effective 2024-01-22 | masonry structural checks; pier/wall adequacy is calculation-dependent |
| ГОСТ 530-2012 — Ceramic brick and stone | **active** | product nominal dimensions only; does not by itself prove wall/pier adequacy |
| СП 63.13330.2018 — Concrete and reinforced concrete structures | **active**, Amendments 1–2 shown by official card | structural calculation/detailing boundary |
| СП 20.13330.2016 — Loads and actions | **active**, Amendments 1–6 shown by official card | input to structural selection |
| СП 22.13330.2016 — Soil bases | **active**, Amendments 1–5 shown by official card | foundations require geotechnical/calculation data |
| СП 70.13330.2012 — Load-bearing and enclosing structures | **active** | execution/tolerances; see future-change quarantine below |
| ГОСТ 9561-2025 — Hollow-core RC floor slabs | **active from 2026-01-01**, replaces ГОСТ 9561-2016; correction IUS 6-2026 | slab types + coordination/product geometry; structural selection still requires loads/support scheme |
| ГОСТ 948-2016 — RC lintels for brick walls | **active**; Amendment No. 1 effective 2025-06-01; correction listed in 2026 | standardized lintel family; do not choose by opening width alone |

Official cards:
- СП 15 change: https://protect.gost.ru/sp/changesdetails/f73de534-f2be-416e-9ae9-2ac67ceee5e8
- ГОСТ 530: https://protect.gost.ru/gost/details/e3f3ca57-13cb-493c-a047-21814635e7fc
- СП 63: https://protect.gost.ru/sp/details/8b67e228-0c9f-4a62-b562-964b3a58c667
- СП 20: https://protect.gost.ru/sp/details/bac9e1fe-45f1-401b-8e32-949f4ee27821
- СП 22: https://protect.gost.ru/sp/details/71e96332-a446-4a15-87a0-2db895479f61
- СП 70: https://protect.gost.ru/sp/details/2239acf1-711f-4f1f-aaa7-902fa06a8a60
- ГОСТ 9561: https://protect.gost.ru/gost/details/2cad8d31-5b41-45ad-9eb6-0e0125c69b15
- ГОСТ 948: https://protect.gost.ru/gost/details/33107f24-da2a-4700-8d8e-a3fdcba7ffb4

## Building function / architecture

| Document | Status on 2026-09-30 | Scope used by architecture agent |
|---|---|---|
| СП 54.13330.2022 — Multifamily residential buildings | **active** | residential functional/planning constraints; never apply to public building blindly |
| СП 118.13330.2022 — Public buildings and structures | **active** | public building functional/planning constraints |
| СП 59.13330.2020 — Accessibility for persons with reduced mobility | **active** | accessible routes, clearances, sanitary/accessibility constraints |
| СП 113.13330.2023 — Car parks | **active** | parking geometry and safety conditions |
| СП 42.13330.2026 — Urban planning | **active from 2026-07-12**, replaces СП 42.13330.2016 | site/territorial planning; do not use 2016 edition as current baseline |

Official cards:
- СП 54: https://protect.gost.ru/sp/details/c8b00dd7-7c13-4f17-ac0c-d9cf70311263
- СП 118: https://protect.gost.ru/sp/details/ced01945-2f53-47c9-bdb8-4875c2b9800e
- СП 59: https://protect.gost.ru/sp/details/9a314146-2e12-458d-a3dc-914eaa364d51
- СП 113: https://protect.gost.ru/sp/details/c8580ef4-7e8e-4694-808f-11f5696cb131
- СП 42: https://protect.gost.ru/sp/details/f6917ab4-63d8-4ecb-9794-0b4990ba3b99

## Fire architecture

| Document | Status on 2026-09-30 | Architectural use |
|---|---|---|
| СП 1.13130.2020 — Evacuation routes and exits | **active**, Amendments 1–3 listed | exits, stairs, paths; dimensions are conditional on use/occupancy and must be clause-driven |
| СП 2.13130.2020 — Fire resistance of protected objects | **active**; Amendment No. 2 effective 2026-01-01 | fire resistance / structural fire constraints |
| СП 4.13130.2013 — Restriction of fire spread | **active**, Amendments 1–4 listed | fire separations, spatial/planning and constructive decisions |

Official cards:
- СП 1: https://protect.gost.ru/sp/details/9fdcb635-708c-4c67-81a7-83e6baad9ab3
- СП 2 Amendment 2: https://protect.gost.ru/sp/changesdetails/fd8720c4-ae0b-496f-8796-eec45a151fbf
- СП 4: https://protect.gost.ru/sp/details/fe915813-95ec-43a6-ab1c-91027e06bf1c

## Envelope / climate / comfort

| Document | Status on 2026-09-30 | Use |
|---|---|---|
| СП 50.13330.2024 — Thermal protection of buildings | **active** | wall/roof/floor thermal calculations; insulation thickness is calculated, not guessed |
| СП 131.13330.2025 — Building climatology | **active** | current climatic inputs; replaces older climate baseline |
| СП 52.13330.2016 — Natural and artificial lighting | **active**, Amendments 1–2 listed | daylight/artificial-light requirements |
| СП 51.13330.2011 — Noise protection | **active**, Amendments 1–4 listed | acoustic requirements and planning constraints |
| СП 17.13330.2017 — Roofs | **active** | roof systems/slopes/layers subject to system and climate conditions |
| СП 29.13330.2011 — Floors | **active**, Amendments 1–4 listed | floor assemblies by operating conditions |

Official cards:
- СП 50: https://protect.gost.ru/sp/details/5081dae9-9ee9-455f-80e8-d093d495361c
- СП 131: https://protect.gost.ru/sp/details/0634a74e-9f91-4571-82a8-b04c3a9b6c99
- СП 52: https://protect.gost.ru/sp/details/9c938e6d-bd3f-4c81-904f-ba8d4c14357b
- СП 51: https://protect.gost.ru/sp/details/04d467f1-c956-4238-8bc6-a066ecb17990
- СП 17: https://protect.gost.ru/sp/details/844352c5-dda6-4006-acd8-b6875d1ed6a8
- СП 29: https://protect.gost.ru/sp/details/a2711156-c40f-4d0f-89f1-7e3c366bc430

## Windows and installation joints

| Document | Status | Use |
|---|---|---|
| ГОСТ 23166-2024 — Window and balcony blocks | **active from 2024-04-01** | product/block requirements |
| ГОСТ 30971-2012 — Installation joints at window-to-wall openings | **active** | opening/block interface and installation-joint design |

Official cards:
- https://protect.gost.ru/gost/details/a64d7437-05ff-4621-8339-53cd7418810d
- https://protect.gost.ru/gost/details/09b731bf-531e-428b-8ef9-556ed2d1c110

The agent must not set `rough_opening = window_block_size`; the installation joint and assembly detail are separate design data.

## SPDS / drawing documentation

| Document | Status on 2026-09-30 | Use |
|---|---|---|
| ГОСТ Р 21.101-2026 — Main requirements for design/working documentation | **active from 2026-04-01**, replaces ГОСТ Р 21.101-2020 | current SPDS baseline |
| ГОСТ 21.501-2018 — Rules for architectural/construction working documentation | **active** (status verified during audit) | AR/KR drawing conventions and work documentation |
| ГОСТ 21.201-2011 — Conventional graphic symbols | **active** (status verified during audit) | graphical notation |

Official ГОСТ Р 21.101-2026 card: https://protect.gost.ru/gost/details/17bc12e8-6579-4145-b141-56855e772e7f

## Sanitary rules: 2026 replacement trap

As of **2026-09-30**:

- СП 2.1.3678-20 is no longer current; it lost force on 2026-09-01 and was replaced by **СП 2.1.4284-26**, effective 2026-09-01 through 2032-09-01.
- СП 2.4.3648-20 is no longer current; it was replaced from 2026-09-01 by **СП 2.4.2.4283-26**, effective through 2032-09-01.
- СанПиН 2.1.3684-21 remains relevant with 2026 amendments and is separately tracked.
- СанПиН 1.2.3685-21 remains a current hygienic-normative source (current edition/effective period must be checked per project date).

Current replacement legal texts:
- СП 2.1.4284-26: https://base.garant.ru/414329111/
- СП 2.4.2.4283-26: https://base.garant.ru/414329139/

## Quarantine / do not use as current baseline

- PP RF No. 815 — obsolete from 2024-09-01.
- ГОСТ 9561-2016 — replaced by ГОСТ 9561-2025 from 2026-01-01.
- ГОСТ Р 21.101-2020 — replaced by ГОСТ Р 21.101-2026 from 2026-04-01.
- СП 42.13330.2016 — replaced by СП 42.13330.2026 from 2026-07-12.
- СП 2.1.3678-20 — obsolete from 2026-09-01.
- СП 2.4.3648-20 — obsolete from 2026-09-01.
- ГОСТ 21778-81 / ГОСТ 21779-82 / ГОСТ 26607-85 — not the current Russian accuracy baseline; use the verified ГОСТ Р replacements above.
- СП 70.13330.2012 Amendment No. 8 — approved in 2026 but provisions with future introduction date must not affect a 2026-09-30 project unless their effective date has arrived.
- Draft amendments (for example drafts under public discussion) are never executable rules.
