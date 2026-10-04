from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "library" / "multi_profile_dependency_catalog.yaml"
DOCS = ROOT / "library" / "documents"
EXPECTED_PROFILE = "RU_2027_PLUS"

REQUIRED_PROFILES = {
    "MKD",
    "PUBLIC_GENERAL",
    "TRK",
    "MIXED_USE",
    "SCHOOL_GENERAL_EDUCATION",
    "PRESCHOOL",
    "HIGHER_EDUCATION",
    "VOCATIONAL_EDUCATION",
    "MEDICAL",
    "HOTEL",
    "SPORTS",
    "THEATRE_CINEMA_CONCERT",
    "PARKING",
    "INDUSTRIAL_PRODUCTION_STORAGE",
    "INDUSTRIAL_ADMIN_AMENITY",
    "HIGH_RISE_OVERLAY",
    "CHILDREN_HEALTH_CAMP",
}

P0_REQUIRED = {
    "MKD",
    "PUBLIC_GENERAL",
    "TRK",
    "PARKING",
    "SCHOOL_GENERAL_EDUCATION",
    "PRESCHOOL",
    "MEDICAL",
    "HOTEL",
    "SPORTS",
    "INDUSTRIAL_PRODUCTION_STORAGE",
}

# Explicit allow-list only. Stronger combined evidence states are accepted only when they are
# intentionally added here; arbitrary strings ending in "verified" must never pass by convention.
ACCEPTABLE_PRIMARY_EVIDENCE_STATES = {
    "official_card_verified",
    "official_clause_verified",
    "authorized_locator_verified",
    "official_card_verified_plus_authorized_change_text",
    "official_card_verified_plus_authorized_amendment_chain",
}


def load(path: Path) -> Any:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def card_name(document_id: str) -> str:
    return f"{document_id}.yaml"


def main() -> int:
    errors: list[str] = []
    try:
        doc = load(CATALOG)
    except Exception as exc:
        print(f"MULTI-PROFILE CATALOG VALIDATION FAILED\n- cannot read catalog: {exc}")
        return 1

    if not isinstance(doc, dict):
        errors.append("catalog root must be a mapping")
        doc = {}

    if doc.get("target_profile") != EXPECTED_PROFILE:
        errors.append("target_profile mismatch")
    if doc.get("production_authority") is not False:
        errors.append("multi-profile catalog must remain production_authority: false")

    profiles = doc.get("profiles")
    if not isinstance(profiles, dict):
        errors.append("profiles must be a mapping")
        profiles = {}

    missing = sorted(REQUIRED_PROFILES - set(profiles))
    if missing:
        errors.append(f"required functional profiles missing: {missing}")

    primary_docs: dict[str, str] = {}
    for profile_id in REQUIRED_PROFILES:
        row = profiles.get(profile_id)
        if not isinstance(row, dict):
            continue
        primary = row.get("primary_document")
        if not isinstance(primary, str) or not primary:
            errors.append(f"{profile_id} missing primary_document")
            continue
        primary_docs[profile_id] = primary
        card = DOCS / card_name(primary)
        if not card.exists():
            errors.append(f"{profile_id} primary document card missing: {card.name}")
            continue
        try:
            card_doc = load(card)
        except Exception as exc:
            errors.append(f"cannot read {card.name}: {exc}")
            continue
        if not isinstance(card_doc, dict):
            errors.append(f"{card.name} root must be a mapping")
            continue
        if card_doc.get("document_id") != primary:
            errors.append(f"{card.name} document_id mismatch")
        if card_doc.get("production_authority") is not False:
            errors.append(f"{card.name} must remain production_authority: false")
        proof = card_doc.get("proof")
        if not isinstance(proof, dict) or proof.get("state") not in ACCEPTABLE_PRIMARY_EVIDENCE_STATES:
            errors.append(f"{card.name} lacks acceptable primary evidence state")

    priority = doc.get("research_priority")
    if not isinstance(priority, dict):
        errors.append("research_priority must be a mapping")
        priority = {}
    p0 = set(priority.get("P0") or [])
    if not P0_REQUIRED.issubset(p0):
        errors.append(f"P0 research coverage missing: {sorted(P0_REQUIRED - p0)}")
    all_priority = p0 | set(priority.get("P1") or [])
    if not REQUIRED_PROFILES.issubset(all_priority):
        errors.append(f"profiles absent from P0/P1 research plan: {sorted(REQUIRED_PROFILES - all_priority)}")

    parking = profiles.get("PARKING")
    if isinstance(parking, dict):
        if parking.get("primary_document") != "SP_113_13330_2023":
            errors.append("PARKING must route to SP_113_13330_2023")
        if 4 not in (parking.get("verified_changes") or []):
            errors.append("PARKING must include SP113 Change 4 for target date 2026-10-04")

    industrial = profiles.get("INDUSTRIAL_PRODUCTION_STORAGE")
    if isinstance(industrial, dict) and industrial.get("primary_document") != "SP_56_13330_2021":
        errors.append("INDUSTRIAL_PRODUCTION_STORAGE must route to SP_56_13330_2021")

    highrise = profiles.get("HIGH_RISE_OVERLAY")
    if isinstance(highrise, dict):
        rule = str(highrise.get("rule", ""))
        if "does not replace" not in rule:
            errors.append("HIGH_RISE_OVERLAY must explicitly preserve underlying functional profile")

    if errors:
        print("MULTI-PROFILE CATALOG VALIDATION FAILED")
        for error in errors:
            print(f"- {error}")
        return 1

    print(
        f"OK: {len(REQUIRED_PROFILES)} functional profiles have primary document cards and P0/P1 research coverage."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
