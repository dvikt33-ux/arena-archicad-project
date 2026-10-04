from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "library" / "profile_primary_locator_extraction_registry.yaml"
COVERAGE = ROOT / "library" / "profile_rule_coverage_registry.yaml"
SP158_CARD = ROOT / "library" / "documents" / "SP_158_13330_2014.yaml"

EXPECTED_P0 = {
    "SCHOOL_GENERAL_EDUCATION": "SP_251_1325800_2016",
    "PRESCHOOL": "SP_252_1325800_2016",
    "MEDICAL": "SP_158_13330_2014",
    "HOTEL": "SP_257_1325800_2020",
    "INDUSTRIAL_PRODUCTION_STORAGE": "SP_56_13330_2021",
}
EXPECTED_MAPS = {
    "SCHOOL_GENERAL_EDUCATION": "change_maps/SP_251_1325800_2016.yaml",
    "PRESCHOOL": "change_maps/SP_252_1325800_2016.yaml",
    "MEDICAL": "change_maps/SP_158_13330_2014.yaml",
    "HOTEL": "change_maps/SP_257_1325800_2020.yaml",
    "INDUSTRIAL_PRODUCTION_STORAGE": "change_maps/SP_56_13330_2021.yaml",
}
ALLOWED_ACCESS_STATES = {
    "unavailable_in_current_session",
    "not_yet_read_in_connected_session",
    "authorized_GARANT_available_root_mixed_revision",
}


def load(path: Path) -> Any:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def main() -> int:
    errors: list[str] = []
    try:
        registry = load(REGISTRY)
        coverage = load(COVERAGE)
        sp158_card = load(SP158_CARD)
    except Exception as exc:
        print(f"PRIMARY LOCATOR EXTRACTION VALIDATION FAILED\n- unreadable YAML: {exc}")
        return 1

    if not isinstance(registry, dict):
        errors.append("extraction registry must be a mapping")
        registry = {}
    if registry.get("production_authority") is not False:
        errors.append("extraction registry must remain production_authority: false")
    if registry.get("policy") != "fail_closed":
        errors.append("extraction registry policy must remain fail_closed")

    invariants = set(registry.get("invariants") or [])
    required_invariants = {
        "extraction_target_never_counts_as_rule_coverage",
        "official_card_never_proves_clause_or_table_text",
        "amendment_card_summary_never_proves_unchanged_locator_text",
        "no_numeric_value_without_direct_current_locator",
        "general_SP118_or_host_building_rules_never_fill_missing_special_profile_requirement",
        "deleted_locator_is_not_a_current_extraction_target",
        "browser_connection_state_never_changes_evidence_state_by_itself",
        "mixed_revision_root_renderer_is_not_current_consolidated_locator_evidence",
    }
    missing_invariants = sorted(required_invariants - invariants)
    if missing_invariants:
        errors.append(f"missing extraction invariants: {missing_invariants}")

    profiles = registry.get("profiles")
    if not isinstance(profiles, dict):
        errors.append("registry profiles must be a mapping")
        profiles = {}

    if set(profiles) != set(EXPECTED_P0):
        errors.append(f"P0 extraction profile set mismatch: {sorted(profiles)}")

    coverage_profiles = coverage.get("profiles") if isinstance(coverage, dict) else None
    if not isinstance(coverage_profiles, dict):
        errors.append("coverage registry profiles must be a mapping")
        coverage_profiles = {}

    for profile, document in EXPECTED_P0.items():
        row = profiles.get(profile)
        if not isinstance(row, dict):
            errors.append(f"{profile}: missing extraction row")
            continue
        if row.get("primary_document") != document:
            errors.append(f"{profile}: primary_document mismatch")
        if row.get("change_map") != EXPECTED_MAPS[profile]:
            errors.append(f"{profile}: change_map mismatch")
        if row.get("state") not in {
            "source_chain_ready_locator_pending",
            "blocked_pending_direct_current_locator",
        }:
            errors.append(f"{profile}: unsafe extraction state {row.get('state')!r}")
        if row.get("production_promotion_allowed") is not False:
            errors.append(f"{profile}: production promotion must remain false")
        if row.get("direct_locator_access") not in ALLOWED_ACCESS_STATES:
            errors.append(f"{profile}: unsupported direct locator access state {row.get('direct_locator_access')!r}")
        topics = row.get("target_topics")
        if not isinstance(topics, list) or not topics:
            errors.append(f"{profile}: target_topics must be non-empty")
        cmap = ROOT / "library" / EXPECTED_MAPS[profile]
        if not cmap.exists():
            errors.append(f"{profile}: missing change map file {EXPECTED_MAPS[profile]}")

        coverage_row = coverage_profiles.get(profile)
        if not isinstance(coverage_row, dict):
            errors.append(f"{profile}: missing coverage row")
        else:
            if coverage_row.get("coverage_state") != "coverage_gap_no_dedicated_rules":
                errors.append(f"{profile}: extraction research must not silently close dedicated rule gap")
            if coverage_row.get("hard_gap") is not True:
                errors.append(f"{profile}: dedicated rule gap must remain hard_gap: true")

    # SP158 Change 7: direct amendment text is usable for impact mapping, but the GARANT root
    # renderer is mixed-revision and must never count as consolidated current locator evidence.
    medical = profiles.get("MEDICAL") or {}
    if medical.get("state") != "blocked_pending_direct_current_locator":
        errors.append("MEDICAL must remain blocked pending consolidated current locator text")
    if medical.get("direct_change7_text_read") is not True:
        errors.append("MEDICAL must record direct Change 7 text as read")
    if medical.get("root_renderer_state") != "mixed_revision_not_current_consolidated":
        errors.append("MEDICAL must keep SP158 GARANT root marked mixed-revision")
    priority = (medical.get("current_locator_priority") or {}).get("first_pass") or []
    required_medical_priority = {
        "1.1", "5.2", "5.5", "5.6", "5.7", "5.8", "5.11",
        "6.2.11", "6.2.18", "6.2.19", "6.2.22", "6.3.1",
        "6.3.4 Table 6.3 notes", "Appendix V high-impact room-area rows",
    }
    if not required_medical_priority.issubset(set(priority)):
        errors.append("MEDICAL first-pass locator queue lost one or more Change-7 high-impact locators")

    if not isinstance(sp158_card, dict):
        errors.append("SP158 document card must be a mapping")
        sp158_card = {}
    render = sp158_card.get("source_render_state") or {}
    if render.get("root_renderer_state") != "mixed_revision_not_current_consolidated":
        errors.append("SP158 document card must flag GARANT root as mixed revision")
    if render.get("root_renderer_must_not_prove_current_locator_text") is not True:
        errors.append("SP158 root renderer must be forbidden as sole current-text proof")
    conflicts = render.get("verified_conflicts") or []
    for locator in {"5.2", "6.2.18", "6.2.19"}:
        if not any(row.get("locator") == locator for row in conflicts if isinstance(row, dict)):
            errors.append(f"SP158 document card missing verified root-render conflict for {locator}")
    locators = sp158_card.get("locators") or []
    state_by_locator = {
        row.get("locator"): row.get("state")
        for row in locators
        if isinstance(row, dict) and isinstance(row.get("locator"), str)
    }
    for locator in {"5.2", "6.2.18", "6.2.19", "6.2.22", "6.3.4 Table 6.3 notes"}:
        if state_by_locator.get(locator) != "authorized_amendment_text_verified_current_consolidated_locator_pending":
            errors.append(f"SP158 {locator} must remain amendment-verified but current-locator pending")

    parking = registry.get("parking_reaudit")
    if not isinstance(parking, dict):
        errors.append("parking_reaudit row missing")
    else:
        if parking.get("planning_document") != "SP_113_13330_2023":
            errors.append("parking_reaudit planning document mismatch")
        if parking.get("planning_change_map") != "change_maps/SP_113_13330_2023.yaml":
            errors.append("parking_reaudit planning change_map mismatch")
        if parking.get("fire_document") != "SP_551_1311500_2026":
            errors.append("parking_reaudit fire document mismatch")
        if parking.get("fire_change_map") != "change_maps/SP_551_1311500_2026.yaml":
            errors.append("parking_reaudit fire change_map mismatch")
        if parking.get("state") != "blocked_pending_direct_current_locator":
            errors.append("parking_reaudit must remain blocked pending direct current locator")
        if parking.get("production_promotion_allowed") is not False:
            errors.append("parking_reaudit production promotion must remain false")

        forbidden = {"6.2.12", "6.2.30", "7.10.2"}
        planning_targets = set(parking.get("planning_priority_locators") or [])
        if planning_targets & forbidden:
            errors.append("deleted SP113 fire locators must not remain planning extraction targets")
        expected_fire_targets = {"SP551 7.3", "SP551 7.4", "SP551 7.5", "SP551 7.6", "SP551 12.6", "SP551 12.7"}
        if set(parking.get("fire_priority_locators") or []) != expected_fire_targets:
            errors.append("parking_reaudit SP551 fire target set mismatch")
        superseded = parking.get("superseded_not_current_targets") or []
        for locator in forbidden:
            if not any(row.get("locator") == locator and row.get("state") == "deleted_by_change4" for row in superseded):
                errors.append(f"parking_reaudit missing superseded state for SP113 {locator}")

        if not (ROOT / "library" / "change_maps" / "SP_113_13330_2023.yaml").exists():
            errors.append("SP113 Change 4 map missing")
        if not (ROOT / "library" / "change_maps" / "SP_551_1311500_2026.yaml").exists():
            errors.append("SP551 map missing")

    summary = registry.get("summary")
    if not isinstance(summary, dict):
        errors.append("summary missing")
    else:
        if summary.get("P0_profiles_in_primary_extraction_queue") != 5:
            errors.append("summary P0 profile count must be 5")
        if summary.get("profiles_with_numeric_promotion") != 0:
            errors.append("summary must declare zero numeric promotions")
        if summary.get("unresolved_profiles_fail_closed") is not True:
            errors.append("unresolved profiles must fail closed")
        if summary.get("parking_fire_route_current_document") != "SP_551_1311500_2026":
            errors.append("summary must route current parking fire extraction to SP551")
        if summary.get("medical_current_consolidated_locator_PASS") != 0:
            errors.append("summary must keep zero SP158 consolidated locator PASS")

    if errors:
        print("PRIMARY LOCATOR EXTRACTION VALIDATION FAILED")
        for error in errors:
            print(f"- {error}")
        return 1

    print(
        "OK: 5 P0 special profiles remain fail-closed; SP158 Change 7 amendment evidence is tracked "
        "without treating the mixed GARANT root renderer as consolidated current text; parking reaudit "
        "remains split into SP113 planning and SP551 fire targets."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
