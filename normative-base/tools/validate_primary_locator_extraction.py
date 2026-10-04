from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "library" / "profile_primary_locator_extraction_registry.yaml"
COVERAGE = ROOT / "library" / "profile_rule_coverage_registry.yaml"
SP158_CARD = ROOT / "library" / "documents" / "SP_158_13330_2014.yaml"
SP251_CARD = ROOT / "library" / "documents" / "SP_251_1325800_2016.yaml"
SP252_CARD = ROOT / "library" / "documents" / "SP_252_1325800_2016.yaml"
SP257_CARD = ROOT / "library" / "documents" / "SP_257_1325800_2020.yaml"
SP56_CARD = ROOT / "library" / "documents" / "SP_56_13330_2021.yaml"

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
    "authorized_GARANT_root_stale",
    "direct_public_GARANT_change3_read_consolidated_locator_pending",
    "direct_public_GARANT_change1_read_other_current_locators_pending",
    "public_GARANT_base_read_authorized_or_primary_attestation_pending",
}


def load(path: Path) -> Any:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def main() -> int:
    errors: list[str] = []
    try:
        registry = load(REGISTRY)
        coverage = load(COVERAGE)
        sp158_card = load(SP158_CARD)
        sp251_card = load(SP251_CARD)
        sp252_card = load(SP252_CARD)
        sp257_card = load(SP257_CARD)
        sp56_card = load(SP56_CARD)
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
        "official_provider_review_is_corroboration_not_direct_locator_proof",
        "direct_amendment_text_does_not_automatically_equal_consolidated_current_locator_PASS",
        "official_no_change_status_does_not_automatically_convert_public_text_to_library_PASS",
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
        if row.get("state") not in {"source_chain_ready_locator_pending", "blocked_pending_direct_current_locator"}:
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

    # School / SP251.
    school = profiles.get("SCHOOL_GENERAL_EDUCATION") or {}
    if school.get("state") != "blocked_pending_direct_current_locator":
        errors.append("SCHOOL must remain blocked pending direct Change-7/current locator text")
    if school.get("root_renderer_state") != "stale_or_mixed_revision_not_current_consolidated":
        errors.append("SCHOOL must keep SP251 GARANT root marked stale/mixed")
    if set((school.get("current_locator_priority") or {}).get("first_pass") or []) != {"6.3", "Table 6.1 note 4"}:
        errors.append("SCHOOL first-pass locator queue must remain 6.3 + Table 6.1 note 4")
    if (school.get("change7_provider_corroboration") or {}).get("reported_values_are_not_locator_PASS") is not True:
        errors.append("SCHOOL provider-review numeric values must remain non-PASS corroboration")

    school_render = (sp251_card if isinstance(sp251_card, dict) else {}).get("source_render_state") or {}
    if school_render.get("root_renderer_state") != "stale_or_mixed_revision_not_current_consolidated":
        errors.append("SP251 document card must flag GARANT root as stale/mixed")
    if school_render.get("root_renderer_must_not_prove_current_locator_text") is not True:
        errors.append("SP251 GARANT root must be forbidden as sole current-text proof")
    school_locators = {row.get("locator"): row.get("state") for row in (sp251_card.get("locators") or []) if isinstance(row, dict)}
    if school_locators.get("6.3") != "official_provider_change7_corroborated_direct_locator_pending":
        errors.append("SP251 6.3 must remain provider-corroborated and direct-locator pending")
    if school_locators.get("Table 6.1 note 4") != "provider_review_numeric_values_corroborated_direct_amendment_locator_pending":
        errors.append("SP251 Table 6.1 note 4 values must remain direct-amendment pending")

    # Preschool / SP252. Change 3 is the latest revision. A locator fully replaced by Change 3
    # may be attested from the directly read replacement text; partial edits remain pending.
    preschool = profiles.get("PRESCHOOL") or {}
    if preschool.get("state") != "blocked_pending_direct_current_locator":
        errors.append("PRESCHOOL profile must remain blocked until the full dedicated rule layer is built")
    if preschool.get("direct_change3_text_read") is not True:
        errors.append("PRESCHOOL must record direct Change 3 text as read")
    if preschool.get("change3_amendment_candidate_values_are_not_PASS") is not True:
        errors.append("PRESCHOOL registry must not treat all Change 3 candidate values as automatic PASS")

    required_preschool_priority = {
        "1.1", "1.2", "4.1-4.7", "5.2", "5.3", "6.1", "6.2.3", "6.2.4", "6.2.8",
        "7.1.1", "7.1.2", "7.1.7", "7.1.8", "7.2.2.1", "7.2.2.7",
    }
    if set((preschool.get("current_locator_priority") or {}).get("first_pass") or []) != required_preschool_priority:
        errors.append("PRESCHOOL first-pass locator queue mismatch")

    preschool_evidence = (sp252_card if isinstance(sp252_card, dict) else {}).get("source_evidence") or {}
    if preschool_evidence.get("direct_change3_text_state") != "authorized_GARANT_amendment_text_read_directly":
        errors.append("SP252 card must record directly read GARANT Change 3 text")
    if preschool_evidence.get("latest_change_is_change3") is not True:
        errors.append("SP252 exact-replacement evidence requires Change 3 to be the latest revision")
    if preschool_evidence.get("production_authority") is not False:
        errors.append("SP252 evidence must remain non-production authority")

    preschool_states = {row.get("locator"): row.get("state") for row in (sp252_card.get("locators") or []) if isinstance(row, dict)}
    verified_exact = {"1.1", "1.2", "6.2.4", "6.2.8", "7.1.2", "7.2.2.7"}
    pending_context = required_preschool_priority - verified_exact
    for locator in verified_exact:
        if preschool_states.get(locator) != "authorized_latest_amendment_exact_text_verified":
            errors.append(f"SP252 {locator} must remain latest-amendment exact-text verified")
    for locator in pending_context:
        if preschool_states.get(locator) != "amendment_text_verified_current_context_pending":
            errors.append(f"SP252 {locator} must remain amendment-verified/current-context pending")

    # Medical / SP158.
    medical = profiles.get("MEDICAL") or {}
    if medical.get("state") != "blocked_pending_direct_current_locator":
        errors.append("MEDICAL must remain blocked pending consolidated current locator text")
    if medical.get("direct_change7_text_read") is not True:
        errors.append("MEDICAL must record direct Change 7 text as read")
    if medical.get("root_renderer_state") != "mixed_revision_not_current_consolidated":
        errors.append("MEDICAL must keep SP158 GARANT root marked mixed-revision")
    required_medical_priority = {
        "1.1", "5.2", "5.5", "5.6", "5.7", "5.8", "5.11", "6.2.11", "6.2.18", "6.2.19",
        "6.2.22", "6.3.1", "6.3.4 Table 6.3 notes", "Appendix V high-impact room-area rows",
    }
    if not required_medical_priority.issubset(set((medical.get("current_locator_priority") or {}).get("first_pass") or [])):
        errors.append("MEDICAL first-pass locator queue lost one or more Change-7 high-impact locators")
    render = (sp158_card if isinstance(sp158_card, dict) else {}).get("source_render_state") or {}
    if render.get("root_renderer_state") != "mixed_revision_not_current_consolidated":
        errors.append("SP158 document card must flag GARANT root as mixed revision")
    if render.get("root_renderer_must_not_prove_current_locator_text") is not True:
        errors.append("SP158 root renderer must be forbidden as sole current-text proof")
    conflicts = render.get("verified_conflicts") or []
    for locator in {"5.2", "5.6", "5.7", "5.11", "6.2.11", "6.2.18", "6.2.19", "6.3.1"}:
        if not any(row.get("locator") == locator for row in conflicts if isinstance(row, dict)):
            errors.append(f"SP158 document card missing verified root-render conflict for {locator}")
    state_by_locator = {row.get("locator"): row.get("state") for row in (sp158_card.get("locators") or []) if isinstance(row, dict)}
    for locator in {"5.2", "5.6", "5.7", "5.8", "5.11", "6.2.11", "6.2.18", "6.2.19", "6.2.22", "6.3.1", "6.3.4 Table 6.3 notes"}:
        if state_by_locator.get(locator) != "authorized_amendment_text_verified_current_consolidated_locator_pending":
            errors.append(f"SP158 {locator} must remain amendment-verified but current-locator pending")

    # Hotel / SP257.
    hotel = profiles.get("HOTEL") or {}
    if hotel.get("state") != "blocked_pending_direct_current_locator":
        errors.append("HOTEL must remain blocked pending current hotel locators")
    if hotel.get("direct_change1_text_read") is not True or hotel.get("change1_affected_locator") != "5.3":
        errors.append("HOTEL must record direct Change 1 effect at 5.3")
    if hotel.get("change1_EV_parking_route_is_not_complete_hotel_profile_coverage") is not True:
        errors.append("HOTEL 5.3 EV change must not close the hotel profile gap")
    hotel_priority = set((hotel.get("current_locator_priority") or {}).get("first_pass") or [])
    required_hotel_priority = {"5.3", "4.2", "6.1.4-6.1.15", "6.2.3-6.2.11", "6.3.2-6.3.9", "6.4.1-6.4.9", "Appendix B", "Appendix G"}
    if hotel_priority != required_hotel_priority:
        errors.append("HOTEL locator priority mismatch")
    hotel_evidence = (sp257_card if isinstance(sp257_card, dict) else {}).get("source_evidence") or {}
    if hotel_evidence.get("direct_change1_text_state") != "amendment_text_read_directly_public_GARANT":
        errors.append("SP257 card must record direct Change 1 text")
    hotel_states = {row.get("locator"): row.get("state") for row in (sp257_card.get("locators") or []) if isinstance(row, dict)}
    if hotel_states.get("5.3") != "amendment_text_verified_current_consolidated_locator_pending":
        errors.append("SP257 5.3 must remain amendment-verified/current-locator pending")

    # Industrial / SP56.
    industrial = profiles.get("INDUSTRIAL_PRODUCTION_STORAGE") or {}
    if industrial.get("state") != "blocked_pending_direct_current_locator":
        errors.append("INDUSTRIAL must remain blocked pending accepted exact locator evidence")
    if industrial.get("official_no_registered_changes") is not True:
        errors.append("INDUSTRIAL must preserve official no-registered-change metadata")
    if industrial.get("public_GARANT_candidate_values_are_not_PASS") is not True:
        errors.append("INDUSTRIAL public GARANT values must remain non-PASS")
    required_industrial_priority = {
        "scope_and_exclusions", "5.1.1", "5.1.2", "5.1.3", "5.1.4", "5.1.5", "5.4.4.5", "5.4.4.9",
        "5.4.4.11", "6.2.2", "6.2.18; Table 6.3", "6.2.22", "Appendix A.1-A.4",
    }
    if set((industrial.get("current_locator_priority") or {}).get("first_pass") or []) != required_industrial_priority:
        errors.append("INDUSTRIAL first-pass locator queue mismatch")
    industrial_evidence = (sp56_card if isinstance(sp56_card, dict) else {}).get("source_evidence") or {}
    if industrial_evidence.get("accepted_locator_PASS") is not False or industrial_evidence.get("production_promotion_allowed") is not False:
        errors.append("SP56 public base text must not count as accepted locator PASS")
    industrial_states = {row.get("locator"): row.get("state") for row in (sp56_card.get("locators") or []) if isinstance(row, dict)}
    for locator in {"5.1.1", "5.1.2", "5.1.3", "5.1.4", "5.1.5", "5.4.4.5", "5.4.4.9", "5.4.4.11", "6.2.2", "6.2.18; Table 6.3", "6.2.22", "Appendix A.1", "Appendix A.2", "Appendix A.4"}:
        if industrial_states.get(locator) != "public_current_text_corroborated_accepted_locator_pending":
            errors.append(f"SP56 {locator} must remain public-corroborated/accepted-locator pending")

    # Parking SP113/SP551 split.
    parking = registry.get("parking_reaudit")
    if not isinstance(parking, dict):
        errors.append("parking_reaudit row missing")
    else:
        if parking.get("planning_document") != "SP_113_13330_2023": errors.append("parking_reaudit planning document mismatch")
        if parking.get("planning_change_map") != "change_maps/SP_113_13330_2023.yaml": errors.append("parking_reaudit planning change_map mismatch")
        if parking.get("fire_document") != "SP_551_1311500_2026": errors.append("parking_reaudit fire document mismatch")
        if parking.get("fire_change_map") != "change_maps/SP_551_1311500_2026.yaml": errors.append("parking_reaudit fire change_map mismatch")
        if parking.get("state") != "blocked_pending_direct_current_locator": errors.append("parking_reaudit must remain blocked pending direct current locator")
        if parking.get("production_promotion_allowed") is not False: errors.append("parking_reaudit production promotion must remain false")
        forbidden = {"6.2.12", "6.2.30", "7.10.2"}
        if set(parking.get("planning_priority_locators") or []) & forbidden:
            errors.append("deleted SP113 fire locators must not remain planning extraction targets")
        expected_fire_targets = {"SP551 7.3", "SP551 7.4", "SP551 7.5", "SP551 7.6", "SP551 12.6", "SP551 12.7"}
        if set(parking.get("fire_priority_locators") or []) != expected_fire_targets:
            errors.append("parking_reaudit SP551 fire target set mismatch")
        superseded = parking.get("superseded_not_current_targets") or []
        for locator in forbidden:
            if not any(row.get("locator") == locator and row.get("state") == "deleted_by_change4" for row in superseded):
                errors.append(f"parking_reaudit missing superseded state for SP113 {locator}")

    summary = registry.get("summary")
    if not isinstance(summary, dict):
        errors.append("summary missing")
    else:
        expected_zero = [
            "school_current_consolidated_locator_PASS",
            "preschool_current_consolidated_locator_PASS",
            "medical_current_consolidated_locator_PASS",
            "hotel_current_consolidated_locator_PASS",
            "industrial_accepted_locator_PASS",
        ]
        if summary.get("P0_profiles_in_primary_extraction_queue") != 5: errors.append("summary P0 profile count must be 5")
        if summary.get("P0_profiles_with_exact_locator_priority_lists") != 5: errors.append("summary exact locator queue count must be 5")
        if summary.get("profiles_with_numeric_promotion") != 0: errors.append("summary must declare zero numeric promotions")
        if summary.get("unresolved_profiles_fail_closed") is not True: errors.append("unresolved profiles must fail closed")
        if summary.get("parking_fire_route_current_document") != "SP_551_1311500_2026": errors.append("summary must route current parking fire extraction to SP551")
        for key in expected_zero:
            if summary.get(key) != 0: errors.append(f"summary {key} must remain zero")

    if errors:
        print("PRIMARY LOCATOR EXTRACTION VALIDATION FAILED")
        for error in errors:
            print(f"- {error}")
        return 1

    print(
        "OK: all 5 P0 special profiles keep fail-closed rule coverage; SP252 permits only six directly read latest-amendment "
        "full-replacement locator attestations, while partial edits and all machine-rule creation remain gated; parking remains split SP113/SP551."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
