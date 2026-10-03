from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
RULES = ROOT / "rules"
REGISTRY = ROOT / "library" / "profile_rule_coverage_registry.yaml"
CATALOG = ROOT / "library" / "multi_profile_dependency_catalog.yaml"
EXPECTED_PROFILE = "RU_2027_PLUS"
EXPECTED_PROFILES = {
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
KNOWN_STATES = {
    "substantive_existing",
    "partial_special_function",
    "shared_general_only",
    "coverage_gap_no_dedicated_rules",
    "overlay_existing",
}
MUST_REMAIN_GAPS_UNTIL_DEDICATED_RULE_EXISTS = {
    "SCHOOL_GENERAL_EDUCATION",
    "PRESCHOOL",
    "HIGHER_EDUCATION",
    "VOCATIONAL_EDUCATION",
    "MEDICAL",
    "HOTEL",
    "INDUSTRIAL_PRODUCTION_STORAGE",
    "INDUSTRIAL_ADMIN_AMENITY",
    "CHILDREN_HEALTH_CAMP",
}


def load(path: Path) -> Any:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def listed_rule_files(row: dict[str, Any]) -> set[str]:
    out: set[str] = set()
    for key in ("dedicated_rule_files", "shared_rule_files", "shared_general_files", "related_overlay_files"):
        value = row.get(key) or []
        if isinstance(value, list):
            out.update(str(item) for item in value)
    return out


def main() -> int:
    errors: list[str] = []
    try:
        registry = load(REGISTRY)
        catalog = load(CATALOG)
    except Exception as exc:
        print(f"PROFILE RULE COVERAGE VALIDATION FAILED\n- cannot load inputs: {exc}")
        return 1

    if not isinstance(registry, dict):
        errors.append("coverage registry root must be a mapping")
        registry = {}
    if not isinstance(catalog, dict):
        errors.append("multi-profile catalog root must be a mapping")
        catalog = {}

    if registry.get("target_profile") != EXPECTED_PROFILE:
        errors.append("coverage registry target_profile mismatch")
    if registry.get("production_authority") is not False:
        errors.append("coverage registry must remain production_authority: false")

    profiles = registry.get("profiles")
    if not isinstance(profiles, dict):
        errors.append("coverage registry profiles must be a mapping")
        profiles = {}
    catalog_profiles = catalog.get("profiles")
    if not isinstance(catalog_profiles, dict):
        catalog_profiles = {}

    actual = set(profiles)
    if actual != EXPECTED_PROFILES:
        errors.append(f"coverage registry profile set mismatch: missing={sorted(EXPECTED_PROFILES-actual)}, extra={sorted(actual-EXPECTED_PROFILES)}")
    if not EXPECTED_PROFILES.issubset(set(catalog_profiles)):
        errors.append("coverage registry contains profiles not fully backed by multi-profile dependency catalog")

    gap_count = 0
    for name in EXPECTED_PROFILES:
        row = profiles.get(name)
        if not isinstance(row, dict):
            continue
        state = row.get("coverage_state")
        if state not in KNOWN_STATES:
            errors.append(f"{name}: unknown coverage_state {state!r}")
        primary = row.get("primary_document")
        catalog_row = catalog_profiles.get(name)
        if isinstance(catalog_row, dict) and primary != catalog_row.get("primary_document"):
            errors.append(f"{name}: primary_document differs from multi-profile catalog")

        dedicated = row.get("dedicated_rule_files") or []
        if not isinstance(dedicated, list):
            errors.append(f"{name}: dedicated_rule_files must be a list")
            dedicated = []

        for filename in listed_rule_files(row):
            if not (RULES / filename).exists():
                errors.append(f"{name}: referenced rule file does not exist: {filename}")

        if state == "coverage_gap_no_dedicated_rules":
            gap_count += 1
            if dedicated:
                errors.append(f"{name}: gap state cannot have dedicated rule files")
            if row.get("hard_gap") is not True:
                errors.append(f"{name}: coverage gap must be explicitly hard_gap: true")
        elif state in {"substantive_existing", "partial_special_function", "overlay_existing"} and not dedicated:
            errors.append(f"{name}: {state} requires at least one dedicated rule file")

        if name in MUST_REMAIN_GAPS_UNTIL_DEDICATED_RULE_EXISTS and not dedicated:
            if state != "coverage_gap_no_dedicated_rules":
                errors.append(f"{name}: cannot be marked covered without a dedicated rule file")

        if name in {"SCHOOL_GENERAL_EDUCATION", "PRESCHOOL", "MEDICAL", "HOTEL"}:
            if state == "substantive_existing" and not dedicated:
                errors.append(f"{name}: generic SP118 files cannot count as substantive special-profile coverage")

    summary = registry.get("summary")
    if not isinstance(summary, dict):
        errors.append("coverage registry missing summary")
    else:
        if summary.get("profiles_total") != 17:
            errors.append("coverage summary profiles_total must be 17")
        if summary.get("gap_count") != gap_count:
            errors.append(f"coverage summary gap_count mismatch: declared={summary.get('gap_count')} actual={gap_count}")

    invariants = set(registry.get("invariants") or [])
    required_invariants = {
        "shared_SP118_rules_never_count_as_complete_special_profile_coverage",
        "coverage_state_never_counts_as_locator_evidence_PASS",
        "coverage_gap_is_fail_closed_for_missing_special_requirement",
    }
    missing = required_invariants - invariants
    if missing:
        errors.append(f"coverage registry missing invariants: {sorted(missing)}")

    if errors:
        print("PROFILE RULE COVERAGE VALIDATION FAILED")
        for error in errors:
            print(f"- {error}")
        return 1

    print(f"OK: 17 profiles inventoried; {gap_count} explicit dedicated-rule coverage gaps remain fail-closed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
