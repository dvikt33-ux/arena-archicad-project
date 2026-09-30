# Legal applicability guard

Verified baseline: **2026-09-30**.

This repository separates two questions that must not be conflated:

1. **Is the technical document/edition current?** — checked against Rosstandart / the competent authority.
2. **Is a specific requirement legally applicable to this project and verification procedure?** — checked through the current statutory requirements framework.

## Current legal framework used by the rules engine

- Federal Law No. 384-FZ, Article 6: national standards and codes of practice containing building-safety requirements are applied from the date the relevant requirements are included in the statutory requirements register.
- Urban Planning Code of the Russian Federation, Article 57.4: the requirements register is a public state information resource maintained using the unified information system.
- Government Resolution No. 1417 of 2023-08-31, as amended: establishes the rules for forming and maintaining that register and resolving contradictions between registered requirements.

## Engine behavior

A current GOST/SP is **not automatically labelled legally mandatory in full** merely because the document itself is current. Clause-level legal applicability is a separate field/check.

For every rule intended for an expertise/compliance conclusion, the engine should store or request:

- project verification date;
- object/building scope;
- document and edition;
- clause;
- whether the relevant requirement is present in the requirements register for the applicable process;
- any special technical conditions or project-specific regulatory basis;
- conflicts or exceptions.

If the register status has not been checked, the rule may still be used as a technical design/reference rule where appropriate, but the engine must **not** state that it is legally mandatory solely from the GOST/SP status.

## Legacy guard

Do not use a historical static list of standards/clauses as a substitute for the current requirements-register mechanism. Legacy project documentation may still cite older mechanisms, but a new compliance check must use the legal framework valid on the verification date.
