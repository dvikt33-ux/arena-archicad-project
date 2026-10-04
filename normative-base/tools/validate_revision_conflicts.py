from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
RULES = ROOT / "rules"
LIB = ROOT / "library"


def load_yaml(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def walk(node: Any):
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from walk(value)
    elif isinstance(node, list):
        for value in node:
            yield from walk(value)


def machine_rules(node: Any):
    for row in walk(node):
        if isinstance(row.get("id"), str):
            yield row


def fail(message: str) -> None:
    raise SystemExit(f"revision-conflict validation failed: {message}")


def main() -> None:
    rule70_path = RULES / "70_trk_multifunctional_planning_2027.yaml"
    rule89_path = RULES / "89_trk_loading_logistics_2027.yaml"
    rule102_path = RULES / "102_ev_charging_parking_architectural_interfaces_2027.yaml"
    rule64_path = RULES / "64_parking_fire_safety_2026.yaml"
    rule14_path = RULES / "14_parking_geometry.yaml"
    sp464_map_path = LIB / "change_maps" / "SP_464_1325800_2019.yaml"
    sp118_map_path = LIB / "change_maps" / "SP_118_13330_2022.yaml"
    sp113_map_path = LIB / "change_maps" / "SP_113_13330_2023.yaml"
    sp551_map_path = LIB / "change_maps" / "SP_551_1311500_2026.yaml"
    engineering_path = LIB / "engineering_system_scope_registry.yaml"
    backlog_path = LIB / "multi_profile_locator_backlog.yaml"
    primary_queue_path = LIB / "profile_primary_locator_extraction_registry.yaml"

    rule70 = load_yaml(rule70_path)
    rule89 = load_yaml(rule89_path)
    rule102 = load_yaml(rule102_path)
    rule64 = load_yaml(rule64_path)
    rule14 = load_yaml(rule14_path)
    sp464 = load_yaml(sp464_map_path)
    sp118 = load_yaml(sp118_map_path)
    sp113 = load_yaml(sp113_map_path)
    sp551 = load_yaml(sp551_map_path)
    engineering = load_yaml(engineering_path)
    backlog = load_yaml(backlog_path)
    primary_queue = load_yaml(primary_queue_path)

    # SP464 mixed-revision renderer protection.
    rule70_text = rule70_path.read_text(encoding="utf-8")
    if "trk.loading.closed_dock_trade_food" in rule70_text:
        fail("superseded SP464 6.21 rule id returned to rules/70")
    if "закрытые дебаркадеры" in rule70_text.lower():
        fail("pre-Change-1 SP464 6.21 closed-debarkader text returned to rules/70")

    canopy_rules = [node for node in walk(rule89) if node.get("id") == "trk.loading.open_places_canopy"]
    if len(canopy_rules) != 1:
        fail("rules/89 must contain exactly one current SP464 open-loading canopy rule")
    canopy = canopy_rules[0]
    if canopy.get("source_clause") != "6.21, Change 1" or canopy.get("requirement") != "canopy":
        fail("rules/89 SP464 6.21 canopy rule lost Change-1 traceability")

    public = sp464.get("public_GARANT_corroboration") or {}
    if public.get("root_renderer_state") != "mixed_revision_not_current_consolidated":
        fail("SP464 root GARANT renderer must stay marked mixed-revision")
    if public.get("root_renderer_must_not_prove_current_locator_text") is not True:
        fail("SP464 root GARANT renderer must be forbidden as sole current-text proof")

    stale = sp464.get("stale_rule_audit") or {}
    if stale.get("stale_rule_found") is not True or stale.get("resolution") != "removed_superseded_rule_and_route_current_loading_typology_to_rule_89":
        fail("SP464 stale 6.21 rule resolution is missing from change map")

    # SP118 renderer/date conflict protection.
    rev118 = sp118.get("revision") or {}
    if str(rev118.get("latest_change_effective_from")) != "2025-02-25":
        fail("SP118 Change 5 effective date must follow Rosstandart 2025-02-25")
    if rev118.get("effective_date_authority") != "Rosstandart" or rev118.get("metadata_conflict") is not True:
        fail("SP118 GARANT/Rosstandart effective-date conflict must remain explicit")

    current118 = sp118.get("public_GARANT_current_text_corroboration") or {}
    locator_516 = next((row for row in current118.get("directly_visible_current_locators", []) if row.get("locator") == "5.16"), None)
    if not isinstance(locator_516, dict) or locator_516.get("public_root_render_conflict") is not True:
        fail("SP118 5.16 root-render conflict must remain explicit")
    if locator_516.get("direct_change_1_text_for_cabin_depth_over_2m") != "1,3 глубины лифта":
        fail("SP118 5.16 Change-1 multiplier semantics changed unexpectedly")

    # SP113 Change 4 -> SP551 parking-fire transition.
    forbidden_sp113_fire_clauses = {"6.2.12", "6.2.30", "7.10.2"}
    for rule in machine_rules(rule102):
        source = rule.get("source")
        if not isinstance(source, dict):
            continue
        if source.get("document") == "SP_113_13330_2023" and str(source.get("clause")) in forbidden_sp113_fire_clauses:
            fail(f"rules/102 still activates deleted SP113 fire locator {source.get('clause')}")

    legacy_rule_ids = {
        "ev.parking.fire_section_trigger",
        "ev.parking.fire_section_separation",
        "ev.parking.fire_section_exception_room_up_to_1200",
        "ev.parking.fire_section_exception_up_to_10_spaces",
        "ev.parking.aup_required",
        "ev.parking.allowed_scope",
        "ev.parking.deep_underground_slow_charge_only",
    }
    active_ids = {row.get("id") for row in machine_rules(rule102)}
    returned = sorted(legacy_rule_ids & active_ids)
    if returned:
        fail(f"legacy SP113 EV-fire rules returned to rules/102: {returned}")

    route = next((row for row in machine_rules(rule102) if row.get("id") == "ev.parking.fire_requirements.route_to_SP551"), None)
    if not isinstance(route, dict):
        fail("rules/102 missing mandatory EV fire route to SP551")
    route_source = route.get("source") or {}
    if route_source.get("document") != "SP_551_1311500_2026":
        fail("rules/102 EV fire route must use SP551")
    required_ev_locators = {"7.3", "7.4", "7.5", "7.6", "12.6", "12.7"}
    if set(route_source.get("locators") or []) != required_ev_locators:
        fail("rules/102 EV fire route does not list the current SP551 locator set")
    if route.get("result_on_unverified_locator_state") != "blocked_pending_current_SP551_locator_verification":
        fail("rules/102 must fail closed while SP551 EV locators are pending")

    gate = next((row for row in machine_rules(rule64) if row.get("id") == "parking.fire.ev_phev.current_SP551_locator_gate"), None)
    if not isinstance(gate, dict) or gate.get("required_document") != "SP_551_1311500_2026":
        fail("rules/64 missing SP551 EV/PHEV fire evidence gate")
    if set(gate.get("required_locators") or []) != required_ev_locators:
        fail("rules/64 SP551 EV/PHEV gate locator set mismatch")

    change4 = sp113.get("change_4_substantive_effects") or {}
    fire_transition = change4.get("fire_role_transition") or []
    if not any(row.get("locator_range") == "6.2.2-6.2.36" and row.get("effect") == "deleted" for row in fire_transition):
        fail("SP113 change map must record deletion of 6.2.2-6.2.36")
    ev_changes = change4.get("EV_section_7_10") or []
    if not any(row.get("locator") == "7.10.2" and row.get("effect") == "deleted" for row in ev_changes):
        fail("SP113 change map must record deletion of 7.10.2")

    ev_migration = sp551.get("EV_PHEV_locator_migration") or {}
    if ev_migration.get("state") != "current_public_text_corroborated_locator_migration_pending":
        fail("SP551 EV locators must remain pending rather than promoted from public text")
    if ev_migration.get("production_promotion_allowed") is not False:
        fail("SP551 EV public corroboration must not grant production promotion")

    ev_scope = (engineering.get("file_scopes") or {}).get("102_ev_charging_parking_architectural_interfaces_2027.yaml") or {}
    basis = set(ev_scope.get("normative_basis") or [])
    if not {"SP_113_13330_2023", "SP_551_1311500_2026", "SP_256_1325800_2016"}.issubset(basis):
        fail("engineering scope for rules/102 must include SP113 + SP551 + SP256")
    if ev_scope.get("required_fire_scope") != "parking_object_or_parking_zone_within_SP551_scope":
        fail("engineering scope for rules/102 missing independent SP551 fire scope")

    parking = ((backlog.get("profiles") or {}).get("PARKING") or {})
    planning = parking.get("planning_locators") or []
    if any(row.get("locator") in forbidden_sp113_fire_clauses for row in planning):
        fail("deleted SP113 fire locator remains in current planning locator backlog")
    superseded = parking.get("superseded_SP113_fire_locators") or []
    for locator in forbidden_sp113_fire_clauses:
        if not any(row.get("locator") == locator and row.get("state") == "deleted_by_change4" for row in superseded):
            fail(f"parking backlog missing deleted state for SP113 {locator}")

    queue = primary_queue.get("parking_reaudit") or {}
    if queue.get("planning_document") != "SP_113_13330_2023" or queue.get("fire_document") != "SP_551_1311500_2026":
        fail("P0 parking extraction queue must split SP113 planning and SP551 fire roles")
    queue_planning = set(queue.get("planning_priority_locators") or [])
    if queue_planning & forbidden_sp113_fire_clauses:
        fail("deleted SP113 fire locator remains a current P0 extraction target")
    queue_superseded = queue.get("superseded_not_current_targets") or []
    for locator in forbidden_sp113_fire_clauses:
        if not any(row.get("locator") == locator and row.get("state") == "deleted_by_change4" for row in queue_superseded):
            fail(f"P0 extraction queue missing superseded state for SP113 {locator}")
    expected_fire_targets = {f"SP551 {locator}" for locator in required_ev_locators}
    if set(queue.get("fire_priority_locators") or []) != expected_fire_targets:
        fail("P0 parking extraction queue SP551 EV locator set mismatch")

    rev14 = rule14.get("revision_note") or {}
    if rev14.get("change_kind") != "textual_and_reference_updates":
        fail("rules/14 must not describe SP113 Change 4 as reference-only")

    print("revision-conflict validation: PASS")


if __name__ == "__main__":
    main()
