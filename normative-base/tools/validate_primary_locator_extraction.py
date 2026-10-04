from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "library" / "profile_primary_locator_extraction_registry.yaml"
COVERAGE = ROOT / "library" / "profile_rule_coverage_registry.yaml"
LOCATOR_REGISTRY = ROOT / "library" / "locator_registry.yaml"
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
    "direct_GARANT_base_plus_change1_chain_read",
    "direct_GARANT_exact_locators_read_no_registered_changes",
}


def load(path: Path) -> Any:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def locator_states(card: dict[str, Any]) -> dict[str, str]:
    return {
        row.get("locator"): row.get("state")
        for row in (card.get("locators") or [])
        if isinstance(row, dict) and row.get("locator")
    }


def main() -> int:
    errors: list[str] = []
    try:
        registry = load(REGISTRY)
        coverage = load(COVERAGE)
        locator_registry = load(LOCATOR_REGISTRY)
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
        "exact_base_text_plus_complete_latest_amendment_chain_may_verify_one_locator_without_closing_profile_gap",
        "exact_base_locator_with_officially_verified_no_registered_changes_may_be_attested_when_directly_read",
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
        if not isinstance(row.get("target_topics"), list) or not row.get("target_topics"):
            errors.append(f"{profile}: target_topics must be non-empty")
        if not (ROOT / "library" / EXPECTED_MAPS[profile]).exists():
            errors.append(f"{profile}: missing change map file {EXPECTED_MAPS[profile]}")

        coverage_row = coverage_profiles.get(profile)
        if not isinstance(coverage_row, dict):
            errors.append(f"{profile}: missing coverage row")
        else:
            if coverage_row.get("coverage_state") != "coverage_gap_no_dedicated_rules":
                errors.append(f"{profile}: evidence research must not silently close dedicated rule gap")
            if coverage_row.get("hard_gap") is not True:
                errors.append(f"{profile}: dedicated rule gap must remain hard_gap: true")

    # School / SP251 stays blocked until full acceptable Change 7/current locator evidence is read.
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

    # Preschool / SP252: exactly six full replacements in latest Change 3 are attested.
    preschool = profiles.get("PRESCHOOL") or {}
    if preschool.get("state") != "blocked_pending_direct_current_locator":
        errors.append("PRESCHOOL profile must remain blocked until dedicated rule layer is built")
    if preschool.get("direct_change3_text_read") is not True:
        errors.append("PRESCHOOL must record direct Change 3 text as read")
    verified_preschool = {"1.1", "1.2", "6.2.4", "6.2.8", "7.1.2", "7.2.2.7"}
    if set(preschool.get("verified_latest_amendment_exact_locators") or []) != verified_preschool:
        errors.append("PRESCHOOL verified locator set mismatch")
    preschool_evidence = (sp252_card if isinstance(sp252_card, dict) else {}).get("source_evidence") or {}
    if preschool_evidence.get("direct_change3_text_state") != "authorized_GARANT_amendment_text_read_directly":
        errors.append("SP252 card must record directly read GARANT Change 3 text")
    if preschool_evidence.get("latest_change_is_change3") is not True:
        errors.append("SP252 exact-replacement evidence requires Change 3 to be latest")
    if preschool_evidence.get("production_authority") is not False:
        errors.append("SP252 evidence must remain non-production authority")
    preschool_states = locator_states(sp252_card if isinstance(sp252_card, dict) else {})
    for locator in verified_preschool:
        if preschool_states.get(locator) != "authorized_latest_amendment_exact_text_verified":
            errors.append(f"SP252 {locator} must remain latest-amendment exact-text verified")

    # Medical / SP158: latest amendment is directly read but mixed root prevents broad current PASS.
    medical = profiles.get("MEDICAL") or {}
    if medical.get("state") != "blocked_pending_direct_current_locator":
        errors.append("MEDICAL must remain blocked pending accepted current locator evidence")
    if medical.get("direct_change7_text_read") is not True:
        errors.append("MEDICAL must record direct Change 7 text as read")
    if medical.get("root_renderer_state") != "mixed_revision_not_current_consolidated":
        errors.append("MEDICAL must keep SP158 GARANT root marked mixed-revision")
    render = (sp158_card if isinstance(sp158_card, dict) else {}).get("source_render_state") or {}
    if render.get("root_renderer_state") != "mixed_revision_not_current_consolidated":
        errors.append("SP158 document card must flag GARANT root as mixed revision")
    if render.get("root_renderer_must_not_prove_current_locator_text") is not True:
        errors.append("SP158 root renderer must be forbidden as sole current-text proof")

    # Hotel / SP257: only clause 5.3 is current-verified by base + sole latest amendment reconstruction.
    hotel = profiles.get("HOTEL") or {}
    if hotel.get("state") != "blocked_pending_direct_current_locator":
        errors.append("HOTEL must remain blocked despite verified 5.3")
    if hotel.get("direct_locator_access") != "direct_GARANT_base_plus_change1_chain_read":
        errors.append("HOTEL must record direct base+Change1 chain access")
    if hotel.get("direct_change1_text_read") is not True or hotel.get("change1_affected_locator") != "5.3":
        errors.append("HOTEL must record direct Change 1 effect at 5.3")
    if set(hotel.get("verified_locators") or []) != {"5.3"}:
        errors.append("HOTEL verified locator set must contain only 5.3")
    if hotel.get("change1_EV_parking_route_is_not_complete_hotel_profile_coverage") is not True:
        errors.append("HOTEL 5.3 evidence must not close hotel profile gap")
    hotel_evidence = (sp257_card if isinstance(sp257_card, dict) else {}).get("source_evidence") or {}
    required_hotel_evidence = {
        "base_5_3_text_read_directly": True,
        "direct_change1_text_read_directly": True,
        "latest_change_is_change1": True,
        "production_authority": False,
    }
    for key, value in required_hotel_evidence.items():
        if hotel_evidence.get(key) is not value:
            errors.append(f"SP257 source_evidence {key} mismatch")
    hotel_states = locator_states(sp257_card if isinstance(sp257_card, dict) else {})
    if hotel_states.get("5.3") != "authorized_locator_verified_by_base_plus_latest_amendment_reconstruction":
        errors.append("SP257 5.3 must be verified by base+latest-amendment reconstruction")

    # Industrial / SP56: 13 directly read current locators are attested; table matrices remain blocked.
    industrial = profiles.get("INDUSTRIAL_PRODUCTION_STORAGE") or {}
    expected_industrial_verified = {
        "5.1.1", "5.1.2", "5.1.3", "5.1.4", "5.1.5",
        "5.4.4.5", "5.4.4.9", "5.4.4.11",
        "6.2.2", "6.2.18", "6.2.22", "Appendix A.1", "Appendix A.2",
    }
    if industrial.get("state") != "blocked_pending_direct_current_locator":
        errors.append("INDUSTRIAL profile must remain blocked until remaining tables/scope are closed")
    if industrial.get("direct_locator_access") != "direct_GARANT_exact_locators_read_no_registered_changes":
        errors.append("INDUSTRIAL must record direct GARANT exact-locator access")
    if industrial.get("official_no_registered_changes") is not True:
        errors.append("INDUSTRIAL must preserve official no-registered-change metadata")
    if set(industrial.get("verified_locators") or []) != expected_industrial_verified:
        errors.append("INDUSTRIAL verified locator set mismatch")
    if set((industrial.get("current_locator_priority") or {}).get("first_pass_remaining") or []) != {
        "scope_and_exclusions", "Table 6.3", "Tables 6.5-6.6", "Appendix A.4"
    }:
        errors.append("INDUSTRIAL remaining locator queue mismatch")
    industrial_evidence = (sp56_card if isinstance(sp56_card, dict) else {}).get("source_evidence") or {}
    if industrial_evidence.get("exact_text_read_directly") is not True:
        errors.append("SP56 card must record exact direct text read")
    if industrial_evidence.get("official_card_registered_changes") != []:
        errors.append("SP56 card must preserve zero registered amendments")
    if industrial_evidence.get("production_authority") is not False:
        errors.append("SP56 evidence must remain non-production authority")
    industrial_states = locator_states(sp56_card if isinstance(sp56_card, dict) else {})
    for locator in expected_industrial_verified:
        if industrial_states.get(locator) != "authorized_locator_verified":
            errors.append(f"SP56 {locator} must remain authorized_locator_verified")
    if industrial_states.get("Table 6.3") != "blocked_pending_full_table_extraction":
        errors.append("SP56 Table 6.3 must remain blocked pending full table extraction")
    if industrial_states.get("Appendix A.4") != "blocked_pending_complete_locator_read":
        errors.append("SP56 Appendix A.4 must remain blocked pending complete locator read")

    # Parking SP113/SP551 split remains immutable.
    parking = registry.get("parking_reaudit")
    if not isinstance(parking, dict):
        errors.append("parking_reaudit row missing")
    else:
        if parking.get("planning_document") != "SP_113_13330_2023":
            errors.append("parking_reaudit planning document mismatch")
        if parking.get("fire_document") != "SP_551_1311500_2026":
            errors.append("parking_reaudit fire document mismatch")
        if parking.get("state") != "blocked_pending_direct_current_locator":
            errors.append("parking_reaudit must remain blocked pending direct current locator")
        if parking.get("production_promotion_allowed") is not False:
            errors.append("parking_reaudit production promotion must remain false")
        forbidden = {"6.2.12", "6.2.30", "7.10.2"}
        if set(parking.get("planning_priority_locators") or []) & forbidden:
            errors.append("deleted SP113 fire locators must not remain planning extraction targets")
        expected_fire_targets = {"SP551 7.3", "SP551 7.4", "SP551 7.5", "SP551 7.6", "SP551 12.6", "SP551 12.7"}
        if set(parking.get("fire_priority_locators") or []) != expected_fire_targets:
            errors.append("parking_reaudit SP551 fire target set mismatch")
        superseded = parking.get("superseded_not_current_targets") or []
        for locator in forbidden:
            if not any(isinstance(row, dict) and row.get("locator") == locator and row.get("state") == "deleted_by_change4" for row in superseded):
                errors.append(f"parking_reaudit missing superseded state for SP113 {locator}")

    summary = registry.get("summary") or {}
    expected_summary = {
        "P0_profiles_in_primary_extraction_queue": 5,
        "P0_profiles_with_exact_locator_priority_lists": 5,
        "profiles_with_numeric_production_promotion": 0,
        "parking_fire_route_current_document": "SP_551_1311500_2026",
        "school_verified_current_locator_count": 0,
        "preschool_verified_locator_count": 6,
        "medical_current_consolidated_locator_count": 0,
        "hotel_verified_locator_count": 1,
        "industrial_verified_locator_count": 13,
        "P0_special_profile_verified_locator_total": 20,
        "unresolved_profiles_fail_closed": True,
    }
    for key, expected in expected_summary.items():
        if summary.get(key) != expected:
            errors.append(f"summary {key} mismatch: expected {expected!r}, got {summary.get(key)!r}")

    # Central locator registry must agree with the profile evidence layer and remain non-production.
    if not isinstance(locator_registry, dict):
        errors.append("locator registry must be a mapping")
        locator_registry = {}
    if locator_registry.get("production_authority") is not False:
        errors.append("locator registry must remain production_authority: false")
    locator_summary = locator_registry.get("summary") or {}
    if locator_summary.get("authorized_locator_verified") != 26:
        errors.append("locator registry authorized_locator_verified must equal 26")
    expected_by_document = {
        "SP_20_13330_2016": 1,
        "SP_54_13330_2022": 5,
        "SP_252_1325800_2016": 6,
        "SP_257_1325800_2020": 1,
        "SP_56_13330_2021": 13,
    }
    if locator_summary.get("authorized_locator_verified_by_document") != expected_by_document:
        errors.append("locator registry per-document verified counts mismatch")
    if locator_summary.get("production_numeric_promotions_from_this_registry") != 0:
        errors.append("locator registry must not promote numeric production rules")

    if errors:
        print("PRIMARY LOCATOR EXTRACTION VALIDATION FAILED")
        for error in errors:
            print(f"- {error}")
        return 1

    print(
        "OK: all 5 P0 profiles remain fail-closed at rule coverage; 20 special-profile locator attestations "
        "are evidence-only (SP252=6, SP257=1, SP56=13), central verified locator total=26, and parking remains split SP113/SP551."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
