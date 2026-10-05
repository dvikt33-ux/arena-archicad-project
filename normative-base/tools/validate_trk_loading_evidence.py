from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
RULE = ROOT / "rules" / "89_trk_loading_logistics_2027.yaml"
MAP = ROOT / "library" / "change_maps" / "SP_464_1325800_2019.yaml"


def load(path: Path) -> Any:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def walk(node: Any):
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from walk(value)
    elif isinstance(node, list):
        for value in node:
            yield from walk(value)


def by_id(doc: Any) -> dict[str, dict[str, Any]]:
    return {
        row["id"]: row
        for row in walk(doc)
        if isinstance(row, dict) and isinstance(row.get("id"), str)
    }


def fail(message: str) -> None:
    raise SystemExit(f"TRK loading evidence validation failed: {message}")


def main() -> None:
    rule = load(RULE)
    cmap = load(MAP)
    ids = by_id(rule)

    evidence = cmap.get("public_current_appendix_V_corroboration") or {}
    if evidence.get("production_promotion_allowed") is not False:
        fail("public Appendix V corroboration must remain non-promoting")
    rows = {
        row.get("locator"): row
        for row in (evidence.get("locators") or [])
        if isinstance(row, dict) and row.get("locator")
    }
    v1 = rows.get("Appendix V; V.1") or {}
    v2 = rows.get("Appendix V; V.2") or {}
    pending = "public_current_text_corroborated_authorized_attestation_pending"
    if v1.get("state") != pending or v2.get("state") != pending:
        fail("Appendix V.1/V.2 must remain corroborated but authorization-pending")

    reduction = ids.get("trk.loading.shared_places_reduction_cap") or {}
    if reduction.get("max_reduction_percent") != v1.get("shared_loading_reduction_cap_percent"):
        fail("V.1 shared-loading reduction differs between active rule and evidence map")

    cargo = ids.get("trk.loading.cargo_turnover_alternative_calculation") or {}
    cargo_source = cargo.get("source") or {}
    if cargo_source.get("table") != "В.1 note 2, Change 1":
        fail("cargo-turnover alternative lost its explicit Change-1 note traceability")
    if v1.get("change1_alternative_cargo_turnover_note_state") != "exact_authorized_change1_note_re_read_pending":
        fail("V.1 Change-1 cargo-turnover note must stay pending exact authorized re-read")

    values = v2.get("values") or {}
    expected = {
        "trk.loading.platform_standard_height": ("platform_above_vehicle_area_m", values.get("standard_platform_height_above_vehicle_area_m")),
        "trk.loading.platform_light_vehicle_height": ("platform_above_vehicle_area_m", values.get("light_vehicle_platform_height_above_vehicle_area_m")),
        "trk.loading.platform_rectangular_depth": ("min_depth_m", values.get("rectangular_platform_min_depth_m")),
        "trk.loading.platform_sawtooth_depth": ("min_depth_at_narrowest_m", values.get("sawtooth_platform_min_depth_at_narrowest_m")),
    }
    for rule_id, (field, expected_value) in expected.items():
        row = ids.get(rule_id)
        if not isinstance(row, dict):
            fail(f"missing active rule {rule_id}")
        if row.get(field) != expected_value:
            fail(f"{rule_id}: active value {row.get(field)!r} != evidence-map value {expected_value!r}")

    lift = ids.get("trk.loading.platform_lifting_equipment_level") or {}
    if lift.get("platform_relation") != values.get("lifting_equipment_platform_relation"):
        fail("V.2 lifting-equipment platform relation differs between rule and evidence map")

    migration = cmap.get("existing_rule_migration") or {}
    verified = set(migration.get("current_verified_existing_rule_locators") or [])
    public_pending = set(migration.get("public_corroborated_but_not_authorized_existing_rule_locators") or [])
    if {"Appendix V; V.1", "Appendix V; V.2"} & verified:
        fail("V.1/V.2 must not be listed as verified existing-rule locators")
    if not {"Appendix V; V.1", "Appendix V; V.2"}.issubset(public_pending):
        fail("V.1/V.2 must stay explicit in the public-corroborated pending set")

    print("TRK loading evidence validation: PASS")


if __name__ == "__main__":
    main()
