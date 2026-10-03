from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
ROOT_MANIFEST = ROOT / "manifest.yaml"
LIBRARY_MANIFEST = ROOT / "library" / "library_manifest.yaml"
LOCATOR_BACKLOG = ROOT / "library" / "multi_profile_locator_backlog.yaml"
REQUIRED_CATALOGS = {
    "izh_dependency_catalog.yaml",
    "multi_profile_dependency_catalog.yaml",
    "profile_rule_coverage_registry.yaml",
    "profile_primary_locator_extraction_registry.yaml",
    "profile_p1_locator_extraction_registry.yaml",
    "multi_profile_locator_backlog.yaml",
    "locator_registry.yaml",
    "functional_scope_registry.yaml",
    "engineering_system_scope_registry.yaml",
}
REQUIRED_HARD_FAILS = {
    "required_scope_gate_missing",
    "blocked_locator_used_for_numeric_generation",
    "engineering_system_scope_unknown_for_selected_rule",
}
REQUIRED_FIRE_CARDS = {
    "documents/SP_550_1311500_2026.yaml",
    "documents/SP_551_1311500_2026.yaml",
}


def load(path: Path) -> Any:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def main() -> int:
    errors: list[str] = []
    try:
        root = load(ROOT_MANIFEST)
    except Exception as exc:
        print(f"LIBRARY INTEGRATION VALIDATION FAILED\n- root manifest unreadable: {exc}")
        return 1
    try:
        library = load(LIBRARY_MANIFEST)
    except Exception as exc:
        print(f"LIBRARY INTEGRATION VALIDATION FAILED\n- library manifest unreadable: {exc}")
        return 1
    try:
        backlog = load(LOCATOR_BACKLOG)
    except Exception as exc:
        print(f"LIBRARY INTEGRATION VALIDATION FAILED\n- locator backlog unreadable: {exc}")
        return 1

    if not isinstance(root, dict):
        errors.append("root manifest must be a mapping")
        root = {}
    if not isinstance(library, dict):
        errors.append("library manifest must be a mapping")
        library = {}
    if not isinstance(backlog, dict):
        errors.append("locator backlog must be a mapping")
        backlog = {}

    if library.get("production_authority") is not False:
        errors.append("library must remain production_authority: false")
    if library.get("role") != "evidence_and_scope_router":
        errors.append("library role must remain evidence_and_scope_router")

    load_order = root.get("load_order")
    if not isinstance(load_order, list):
        errors.append("root manifest load_order must be a list")
        load_order = []

    library_priority = None
    rules_priority = None
    for row in load_order:
        if not isinstance(row, dict):
            continue
        if row.get("file") == "library/library_manifest.yaml":
            library_priority = row.get("priority")
        if row.get("files") == "rules/*.yaml":
            rules_priority = row.get("priority")

    if library_priority is None:
        errors.append("root manifest does not load library/library_manifest.yaml")
    if rules_priority is None:
        errors.append("root manifest does not load rules/*.yaml")
    if isinstance(library_priority, int) and isinstance(rules_priority, int):
        if library_priority >= rules_priority:
            errors.append("library must load before production rules")

    catalogs = set(library.get("catalogs") or [])
    missing_catalogs = sorted(REQUIRED_CATALOGS - catalogs)
    if missing_catalogs:
        errors.append(f"library manifest missing required catalogs: {missing_catalogs}")
    for catalog in REQUIRED_CATALOGS:
        if not (ROOT / "library" / catalog).exists():
            errors.append(f"required library catalog file missing: {catalog}")

    document_cards = set(library.get("document_cards") or [])
    missing_fire_cards = sorted(REQUIRED_FIRE_CARDS - document_cards)
    if missing_fire_cards:
        errors.append(f"library manifest missing required fire overlay document cards: {missing_fire_cards}")

    coverage = library.get("coverage")
    coverage_row = coverage.get("profile_rule_coverage") if isinstance(coverage, dict) else None
    if not isinstance(coverage_row, dict):
        errors.append("library manifest missing profile_rule_coverage summary")
    else:
        if coverage_row.get("source") != "profile_rule_coverage_registry.yaml":
            errors.append("profile_rule_coverage source mismatch")
        if coverage_row.get("dedicated_rule_gap_count") != 9:
            errors.append("profile_rule_coverage dedicated_rule_gap_count must reflect current explicit inventory")

    extraction_row = coverage.get("primary_profile_locator_extraction") if isinstance(coverage, dict) else None
    if not isinstance(extraction_row, dict):
        errors.append("library manifest missing primary_profile_locator_extraction summary")
    else:
        if extraction_row.get("source") != "profile_primary_locator_extraction_registry.yaml":
            errors.append("primary_profile_locator_extraction source mismatch")
        if extraction_row.get("P0_profiles_in_queue") != 5:
            errors.append("primary_profile_locator_extraction P0 profile count must be 5")
        if extraction_row.get("production_promotions") != 0:
            errors.append("primary profile extraction must not declare production promotions")
        if extraction_row.get("fail_closed") is not True:
            errors.append("primary profile extraction must remain fail_closed")

    p1_row = coverage.get("p1_profile_locator_extraction") if isinstance(coverage, dict) else None
    if not isinstance(p1_row, dict):
        errors.append("library manifest missing p1_profile_locator_extraction summary")
    else:
        if p1_row.get("source") != "profile_p1_locator_extraction_registry.yaml":
            errors.append("p1_profile_locator_extraction source mismatch")
        if p1_row.get("P1_profiles_in_queue") != 7:
            errors.append("p1_profile_locator_extraction P1 profile count must be 7")
        if p1_row.get("production_promotions") != 0:
            errors.append("P1 profile extraction must not declare production promotions")
        if p1_row.get("library_PASS_promotions") != 0:
            errors.append("P1 profile extraction must not declare library PASS promotions")
        if p1_row.get("fail_closed") is not True:
            errors.append("P1 profile extraction must remain fail_closed")

    backlog_row = coverage.get("multi_profile_locator_backlog") if isinstance(coverage, dict) else None
    if not isinstance(backlog_row, dict):
        errors.append("library manifest missing multi_profile_locator_backlog summary")
    else:
        if backlog_row.get("source") != "multi_profile_locator_backlog.yaml":
            errors.append("multi_profile_locator_backlog source mismatch")
        if backlog_row.get("new_library_PASS") != 0:
            errors.append("locator backlog must not declare a new library PASS")

    parking_fire = coverage.get("parking_fire_evidence") if isinstance(coverage, dict) else None
    if not isinstance(parking_fire, dict):
        errors.append("library manifest missing parking_fire_evidence summary")
    else:
        if parking_fire.get("document") != "SP_551_1311500_2026":
            errors.append("parking_fire_evidence must route to SP551")
        if parking_fire.get("paired_planning_document") != "SP_113_13330_2023":
            errors.append("SP551 parking fire evidence must remain paired with SP113 planning")
        if parking_fire.get("new_library_PASS") != 0:
            errors.append("SP551 evidence route must not declare a new library PASS")

    highrise_fire = coverage.get("highrise_fire_evidence") if isinstance(coverage, dict) else None
    if not isinstance(highrise_fire, dict):
        errors.append("library manifest missing highrise_fire_evidence summary")
    else:
        if highrise_fire.get("document") != "SP_550_1311500_2026":
            errors.append("highrise_fire_evidence must route to SP550")
        if highrise_fire.get("paired_architectural_document") != "SP_267_1325800_2016":
            errors.append("SP550 highrise fire evidence must remain paired with SP267 architecture")
        if highrise_fire.get("preserves_underlying_functional_profile") is not True:
            errors.append("SP550 fire overlay must preserve underlying functional profile")
        if highrise_fire.get("new_library_PASS") != 0:
            errors.append("SP550 evidence route must not declare a new library PASS")

    backlog_profiles = backlog.get("profiles")
    if not isinstance(backlog_profiles, dict):
        errors.append("locator backlog profiles must be a mapping")
        backlog_profiles = {}

    parking = backlog_profiles.get("PARKING")
    if not isinstance(parking, dict):
        errors.append("locator backlog missing PARKING profile")
    else:
        if parking.get("primary_document") != "SP_113_13330_2023":
            errors.append("PARKING backlog primary document must remain SP113")
        if parking.get("fire_overlay_document") != "SP_551_1311500_2026":
            errors.append("PARKING backlog fire overlay must be SP551")
        fire_locators = parking.get("fire_overlay_locators")
        if not isinstance(fire_locators, list) or not fire_locators:
            errors.append("PARKING backlog must contain SP551 fire overlay locators")
        elif not all(isinstance(row, dict) and row.get("document") == "SP_551_1311500_2026" for row in fire_locators):
            errors.append("all PARKING fire overlay backlog locators must route to SP551")

    highrise = backlog_profiles.get("HIGH_RISE_OVERLAY")
    if not isinstance(highrise, dict):
        errors.append("locator backlog missing HIGH_RISE_OVERLAY profile")
    else:
        if highrise.get("primary_document") != "SP_267_1325800_2016":
            errors.append("HIGH_RISE_OVERLAY backlog primary document must remain SP267")
        if highrise.get("fire_overlay_document") != "SP_550_1311500_2026":
            errors.append("HIGH_RISE_OVERLAY backlog fire overlay must remain SP550")
        if highrise.get("promotion_allowed") is not False:
            errors.append("HIGH_RISE_OVERLAY backlog must not allow promotion")

    hard_fails = set(root.get("hard_fail_states") or [])
    missing_hard_fails = sorted(REQUIRED_HARD_FAILS - hard_fails)
    if missing_hard_fails:
        errors.append(f"root manifest missing library/scope hard-fail states: {missing_hard_fails}")

    release = root.get("release_gate")
    requirements = release.get("require") if isinstance(release, dict) else None
    if not isinstance(requirements, list):
        errors.append("root release_gate.require must be a list")
        requirements = []
    requirements_text = "\n".join(str(x) for x in requirements)
    required_phrases = [
        "library/library_manifest.yaml is loaded before rules/*.yaml",
        "object-class, functional-zone and engineering-system scope validators pass",
        "blocked_pending_locator never supplies a production numeric value or applicability route",
        "existing_rule_traceability_pending never counts as a new library PASS",
    ]
    for phrase in required_phrases:
        if phrase not in requirements_text:
            errors.append(f"root release gate missing requirement: {phrase}")

    if errors:
        print("LIBRARY INTEGRATION VALIDATION FAILED")
        for error in errors:
            print(f"- {error}")
        return 1

    print(
        "OK: evidence/scope library is non-production authority; P0/P1 queues, SP550/SP551 overlay routes and locator backlogs are integrated without new PASS promotion."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
