from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "library" / "profile_p1_locator_extraction_registry.yaml"
EXPECTED_PROFILES = {
    "MIXED_USE",
    "HIGH_RISE_OVERLAY",
    "HIGHER_EDUCATION",
    "VOCATIONAL_EDUCATION",
    "THEATRE_CINEMA_CONCERT",
    "INDUSTRIAL_ADMIN_AMENITY",
    "CHILDREN_HEALTH_CAMP",
}
EXPECTED_MAPS = {
    "SP_160_1325800_2014.yaml",
    "SP_267_1325800_2016.yaml",
    "SP_550_1311500_2026.yaml",
    "SP_278_1325800_2024.yaml",
    "SP_279_1325800_2016.yaml",
    "SP_309_1325800_2017.yaml",
    "SP_44_13330_2011.yaml",
    "SP_535_1325800_2024.yaml",
    "SP_332_1325800_2017.yaml",
}


def load(path: Path) -> Any:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def main() -> int:
    errors: list[str] = []
    try:
        data = load(REGISTRY)
    except Exception as exc:
        print(f"P1 LOCATOR EXTRACTION VALIDATION FAILED\n- registry unreadable: {exc}")
        return 1

    if not isinstance(data, dict):
        errors.append("registry must be a mapping")
        data = {}
    if data.get("production_authority") is not False:
        errors.append("registry must remain production_authority: false")
    if data.get("policy") != "fail_closed":
        errors.append("registry policy must remain fail_closed")

    profiles = data.get("profiles")
    if not isinstance(profiles, dict):
        errors.append("profiles must be a mapping")
        profiles = {}
    if set(profiles) != EXPECTED_PROFILES:
        errors.append(f"P1 profile set mismatch: {sorted(profiles)}")

    for name, row in profiles.items():
        if not isinstance(row, dict):
            errors.append(f"{name}: profile row must be a mapping")
            continue
        if row.get("production_promotion_allowed") is not False:
            errors.append(f"{name}: production promotion must remain false")
        fallback = str(row.get("fallback_if_locator_missing", ""))
        if "pending" not in fallback:
            errors.append(f"{name}: missing fail-closed pending fallback")
        if name == "HIGH_RISE_OVERLAY" and row.get("preserves_underlying_profile") is not True:
            errors.append("HIGH_RISE_OVERLAY must preserve underlying functional profile")

    expansions = data.get("partial_profile_expansions")
    if not isinstance(expansions, dict) or "SPORTS" not in expansions:
        errors.append("SPORTS partial-profile expansion must remain registered")
    else:
        sport = expansions["SPORTS"]
        if not isinstance(sport, dict) or sport.get("production_promotion_allowed") is not False:
            errors.append("SPORTS expansion must not allow production promotion")

    for name in EXPECTED_MAPS:
        if not (ROOT / "library" / "change_maps" / name).exists():
            errors.append(f"required P1 change map missing: {name}")

    summary = data.get("summary")
    if not isinstance(summary, dict):
        errors.append("summary must be a mapping")
    else:
        if summary.get("P1_profiles_in_queue") != 7:
            errors.append("P1_profiles_in_queue must be 7")
        if summary.get("numeric_promotions") != 0:
            errors.append("P1 queue must not declare numeric promotions")
        if summary.get("library_PASS_promotions") != 0:
            errors.append("P1 queue must not declare library PASS promotions")
        if summary.get("unresolved_profiles_fail_closed") is not True:
            errors.append("unresolved P1 profiles must remain fail closed")

    if errors:
        print("P1 LOCATOR EXTRACTION VALIDATION FAILED")
        for error in errors:
            print(f"- {error}")
        return 1

    print("OK: 7 P1 profiles plus SPORTS expansion have fail-closed locator extraction routes and revision maps.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
