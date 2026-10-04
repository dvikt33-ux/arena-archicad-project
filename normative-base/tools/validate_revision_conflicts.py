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


def fail(message: str) -> None:
    raise SystemExit(f"revision-conflict validation failed: {message}")


def main() -> None:
    rule70_path = RULES / "70_trk_multifunctional_planning_2027.yaml"
    rule89_path = RULES / "89_trk_loading_logistics_2027.yaml"
    sp464_map_path = LIB / "change_maps" / "SP_464_1325800_2019.yaml"
    sp118_map_path = LIB / "change_maps" / "SP_118_13330_2022.yaml"

    rule70 = load_yaml(rule70_path)
    rule89 = load_yaml(rule89_path)
    sp464 = load_yaml(sp464_map_path)
    sp118 = load_yaml(sp118_map_path)

    rule70_text = rule70_path.read_text(encoding="utf-8")
    if "trk.loading.closed_dock_trade_food" in rule70_text:
        fail("superseded SP464 6.21 rule id returned to rules/70")
    if "закрытые дебаркадеры" in rule70_text.lower():
        fail("pre-Change-1 SP464 6.21 closed-debarkader text returned to rules/70")

    canopy_rules = [
        node
        for node in walk(rule89)
        if node.get("id") == "trk.loading.open_places_canopy"
    ]
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

    rev118 = sp118.get("revision") or {}
    if rev118.get("latest_change_effective_from") != "2025-02-25":
        fail("SP118 Change 5 effective date must follow Rosstandart 2025-02-25")
    if rev118.get("effective_date_authority") != "Rosstandart" or rev118.get("metadata_conflict") is not True:
        fail("SP118 GARANT/Rosstandart effective-date conflict must remain explicit")

    current118 = sp118.get("public_GARANT_current_text_corroboration") or {}
    locator_516 = next(
        (row for row in current118.get("directly_visible_current_locators", []) if row.get("locator") == "5.16"),
        None,
    )
    if not isinstance(locator_516, dict) or locator_516.get("public_root_render_conflict") is not True:
        fail("SP118 5.16 root-render conflict must remain explicit")
    if locator_516.get("direct_change_1_text_for_cabin_depth_over_2m") != "1,3 глубины лифта":
        fail("SP118 5.16 Change-1 multiplier semantics changed unexpectedly")

    print("revision-conflict validation: PASS")


if __name__ == "__main__":
    main()
