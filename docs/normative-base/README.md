# Normative Base for BIM / Architectural Model Generation

Verified baseline: **2026-09-30**.

Purpose: a conservative, machine-readable knowledge base for generating and auditing architectural/BIM geometry against Russian construction standards. It is intentionally narrower than a general reference library: a rule is promoted to `active` only when its document status, scope, clause and numerical value have been checked.

## Core policy

1. Never infer a normative number from common practice.
2. Never use a replaced edition when a replacing edition is already effective.
3. Keep `coordination dimensions`, `constructive dimensions` and `actual dimensions` distinct.
4. Modular coordination is a coordination system, not a command that every real dimension must be divisible by 100 mm.
5. Product geometry does not replace structural, fire, accessibility, thermal, acoustic or daylight calculations.
6. If a dimension depends on building use, climate, fire class, accessibility, structural material, load, seismicity or manufacturer system, the rule is `conditional` or `manual_check`, never unconditional.
7. A generated model must report the rule ID and source clause for each automatic normative decision.
8. A conflict between documents is not resolved by blindly choosing the smaller/larger number. The applicable special rule and legal context must be identified.

## Rule states

- `active`: verified and safe for the stated scope.
- `conditional`: verified but only when the listed trigger/scope is known.
- `manual_check`: source is verified, but the result requires engineering/design calculation or project-specific selection.
- `future_effective`: approved but not yet effective on the baseline date.
- `replaced`: retained only to prevent accidental use.
- `quarantine`: found in a secondary source but not sufficiently verified for automation.

## Automation levels

- `auto_apply`: may set/model geometry when all explicit triggers are satisfied.
- `auto_check`: may validate an already selected/modelled value.
- `suggest_only`: may offer a coordinated option, but must not change the model automatically.
- `manual_check`: do not choose the value; require calculation/project decision.

## Directory layout

- `_meta/` — schema, status and source/version catalog.
- `rules/` — verified machine-readable design rules.

## Units

Unless a rule explicitly states otherwise, linear dimensions in machine-readable rules are in **millimetres**.

## Mandatory version check

Before a production modelling session, source statuses should be revalidated against Rosstandart / the relevant authority. Legal applicability of mandatory requirements must be checked separately from the technical status of a GOST/SP.
