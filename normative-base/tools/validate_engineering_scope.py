from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
RULES = ROOT / "rules"
REGISTRY = ROOT / "library" / "engineering_system_scope_registry.yaml"
EXPECTED_PROFILE = "RU_2027_PLUS"
OBJECT_CLASSES = {"IZHS", "MKD", "PUBLIC", "TRK", "INDUSTRIAL"}
EXPECTED_FILES = {
    "91_engineering_architectural_interfaces_2027.yaml",
    "92_ventilation_exhaust_facade_roof_2027.yaml",
    "93_smoke_control_architectural_interfaces_2027.yaml",
    "94_fire_suppression_pump_room_interfaces_2027.yaml",
    "95_internal_fire_water_architectural_interfaces_2027.yaml",
    "96_fire_electrical_routing_architectural_interfaces_2027.yaml",
    "97_fire_alarm_post_architectural_interfaces_2027.yaml",
    "98_external_fire_water_site_interfaces_2027.yaml",
    "99_heat_point_architectural_interfaces_2027.yaml",
    "101_transformer_substation_architectural_interfaces_2027.yaml",
    "102_ev_charging_parking_architectural_interfaces_2027.yaml",
    "104_integrated_heat_generator_100_360kw_2027.yaml",
    "107_diesel_generator_architectural_interfaces_2027.yaml",
    "108_refrigeration_machine_room_interfaces_2027.yaml",
    "109_domestic_water_meter_pump_interfaces_2027.yaml",
    "110_drainage_sumps_underground_rooms_2027.yaml",
}


def main() -> int:
    errors: list[str] = []
    try:
        doc: Any = yaml.safe_load(REGISTRY.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"ENGINEERING SCOPE VALIDATION FAILED\n- cannot read registry: {exc}")
        return 1

    if not isinstance(doc, dict):
        errors.append("engineering system scope registry root must be a mapping")
        doc = {}
    if doc.get("target_profile") != EXPECTED_PROFILE:
        errors.append("engineering system scope registry target_profile mismatch")

    semantics = doc.get("scope_semantics")
    if not isinstance(semantics, dict):
        errors.append("engineering registry missing scope_semantics")
    else:
        order = semantics.get("evaluation_order") or []
        if not isinstance(order, list) or not order or order[0] != "confirm_system_or_equipment_presence":
            errors.append("engineering scope must check system/equipment presence first")
        if semantics.get("missing_system_result") != "not_applicable":
            errors.append("missing engineering system must resolve to not_applicable")
        if semantics.get("unknown_system_requirement_result") != "engineering_design_required":
            errors.append("unknown engineering system requirement must fail to engineering_design_required")

    rows = doc.get("file_scopes")
    if not isinstance(rows, dict):
        errors.append("engineering registry file_scopes must be a mapping")
        rows = {}

    actual = set(rows)
    missing = sorted(EXPECTED_FILES - actual)
    if missing:
        errors.append(f"engineering registry missing expected files: {missing}")

    allowed_gate_types = {"system_presence", "system_and_special_scope", "equipment_scope"}
    for filename in EXPECTED_FILES:
        row = rows.get(filename)
        if not isinstance(row, dict):
            continue
        if not (RULES / filename).exists():
            errors.append(f"engineering registry references absent rule file: {filename}")

        gate_type = row.get("gate_type")
        if gate_type not in allowed_gate_types:
            errors.append(f"{filename} has unsupported gate_type {gate_type!r}")

        has_presence = any(
            key in row
            for key in (
                "required_system",
                "required_system_any",
                "required_condition",
            )
        )
        if not has_presence:
            errors.append(f"{filename} lacks system/equipment presence condition")

        allowed = set(row.get("allowed_object_classes") or [])
        forbidden = set(row.get("forbidden_object_classes") or [])
        unknown = (allowed | forbidden) - OBJECT_CLASSES
        if unknown:
            errors.append(f"{filename} has unknown object classes: {sorted(unknown)}")
        if not allowed:
            errors.append(f"{filename} has no allowed object classes")
        if allowed & forbidden:
            errors.append(f"{filename} both allows and forbids: {sorted(allowed & forbidden)}")

        if not row.get("normative_basis"):
            errors.append(f"{filename} missing normative_basis")

    smoke = rows.get("93_smoke_control_architectural_interfaces_2027.yaml")
    if isinstance(smoke, dict):
        if smoke.get("required_system") != "smoke_control_ventilation_system":
            errors.append("smoke-control rule file must require smoke-control system presence")
        if not smoke.get("applicability_gate"):
            errors.append("smoke-control rule file must require independent fire-rule applicability gate")

    exhaust = rows.get("92_ventilation_exhaust_facade_roof_2027.yaml")
    if isinstance(exhaust, dict):
        overrides = exhaust.get("section_overrides")
        embedded = overrides.get("clean_exhaust_embedded_public_in_residential") if isinstance(overrides, dict) else None
        if not isinstance(embedded, dict):
            errors.append("ventilation exhaust scope must protect embedded PUBLIC-in-residential branch")
        else:
            if embedded.get("active_zone_class") != "PUBLIC":
                errors.append("embedded public ventilation branch must be evaluated as PUBLIC functional zone")
            if set(embedded.get("allowed_host_object_classes") or []) != {"MKD"}:
                errors.append("embedded public ventilation branch host must remain MKD-only")

    tp = rows.get("101_transformer_substation_architectural_interfaces_2027.yaml")
    if isinstance(tp, dict):
        if "INDUSTRIAL" not in set(tp.get("forbidden_object_classes") or []):
            errors.append("residential/public transformer-substation route must not silently cover INDUSTRIAL")

    refrigeration = rows.get("108_refrigeration_machine_room_interfaces_2027.yaml")
    if isinstance(refrigeration, dict):
        expected = {"PUBLIC", "TRK"}
        if set(refrigeration.get("allowed_object_classes") or []) != expected:
            errors.append("public refrigeration-machine-room route must remain PUBLIC/TRK only")

    heatgen = rows.get("104_integrated_heat_generator_100_360kw_2027.yaml")
    if isinstance(heatgen, dict):
        if heatgen.get("required_special_profile") != "SP_281_1325800_2016":
            errors.append("100-360 kW heat generator route must require SP281 profile")
        if "100" not in str(heatgen.get("required_condition")) or "360" not in str(heatgen.get("required_condition")):
            errors.append("SP281 heat generator route must retain explicit >100..<=360 kW gate")
        overrides = heatgen.get("section_overrides")
        public = overrides.get("public_buildings") if isinstance(overrides, dict) else None
        if not isinstance(public, dict) or set(public.get("allowed_object_classes") or []) != {"PUBLIC", "TRK"}:
            errors.append("SP281 public_buildings subsection must be PUBLIC/TRK scoped")

    ev = rows.get("102_ev_charging_parking_architectural_interfaces_2027.yaml")
    if isinstance(ev, dict):
        if not ev.get("required_scope"):
            errors.append("EV charging route must require independent SP113 parking scope")
        if not ev.get("IZHS_note"):
            errors.append("EV charging route must protect ordinary IZHS driveway/garage from SP113 auto-application")

    drainage = rows.get("110_drainage_sumps_underground_rooms_2027.yaml")
    if isinstance(drainage, dict):
        overrides = drainage.get("section_overrides")
        parking = overrides.get("underground_parking_fire_water_collection") if isinstance(overrides, dict) else None
        if not isinstance(parking, dict) or parking.get("required_function") != "underground_vehicle_storage":
            errors.append("underground parking drainage subsection must require vehicle-storage function")

    if errors:
        print("ENGINEERING SCOPE VALIDATION FAILED")
        for error in errors:
            print(f"- {error}")
        return 1

    print(
        f"OK: {len(EXPECTED_FILES)} engineering/fire system rule files require system/equipment presence and scope gates."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
