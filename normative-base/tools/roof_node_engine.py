from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
NODES = ROOT / "nodes"


class RoofEngineError(RuntimeError):
    pass


@dataclass(frozen=True)
class VentilationResult:
    plane_id: str
    status: str
    channel_height_mm: int | None
    eaves_inlet_cm2_per_m: int | None
    ridge_outlet_cm2_per_m: int | None
    reason: str | None = None


@dataclass
class RoofPlan:
    status: str
    intent: str
    node_ids: list[str]
    node_families: list[str]
    structural_node_ids: list[str]
    blockers: list[str]
    warnings: list[str]
    ventilation: list[dict[str, Any]]
    operations: list[dict[str, Any]]
    source_files: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def load_yaml(name: str) -> dict[str, Any]:
    path = NODES / name
    if not path.exists():
        raise RoofEngineError(f"missing node data file: {name}")
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RoofEngineError(f"invalid mapping root: {name}")
    return value


def require(context: dict[str, Any], keys: list[str], blockers: list[str]) -> None:
    for key in keys:
        value = context.get(key)
        if value is None or value == "" or value == [] or value == {}:
            blockers.append(f"missing:{key}")


def catalog_index(catalog: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(node["node_id"]): node
        for node in catalog.get("nodes", [])
        if isinstance(node, dict) and node.get("node_id")
    }


def exact_or_conservative_vent_height(length_m: float, slope_percent: float) -> tuple[str, int | None, str | None]:
    lengths = [5.0, 10.0, 15.0, 20.0, 25.0]
    slopes = [18.0, 27.0, 36.0, 47.0, 56.0]
    heights = {
        5.0: [50, 50, 50, 50, 50],
        10.0: [80, 60, 50, 50, 50],
        15.0: [100, 80, 60, 50, 50],
        20.0: [100, 100, 80, 60, 50],
        25.0: [100, 100, 100, 80, 60],
    }
    if length_m > 25 or slope_percent < 18 or slope_percent > 56:
        return "blocked", None, "outside_SP17_Appendix_A_Table_A2_verified_matrix"

    exact_length = length_m in lengths
    exact_slope = slope_percent in slopes
    if exact_length and exact_slope:
        return "verified_exact", heights[length_m][slopes.index(slope_percent)], None

    conservative_length = next((x for x in lengths if x >= length_m), None)
    conservative_slope = next((x for x in reversed(slopes) if x <= slope_percent), None)
    if conservative_length is None or conservative_slope is None:
        return "blocked", None, "cannot_resolve_conservative_table_cell"
    return (
        "conservative_precheck_not_final",
        heights[conservative_length][slopes.index(conservative_slope)],
        "non_grid_value_requires_designer_confirmation_before_approved_for_model",
    )


def ventilation_results(context: dict[str, Any], blockers: list[str], warnings: list[str]) -> list[dict[str, Any]]:
    if context.get("ventilation_mode") != "ventilated_channel":
        return []

    planes = context.get("roof_planes") or []
    if not isinstance(planes, list) or not planes:
        blockers.append("missing:roof_planes_for_ventilation")
        return []

    ridge_present = (context.get("topology") or {}).get("ridge_count", 0) > 0
    out: list[dict[str, Any]] = []
    for plane in planes:
        if not isinstance(plane, dict):
            blockers.append("invalid:roof_plane_record")
            continue
        plane_id = str(plane.get("id") or "unknown")
        try:
            length_m = float(plane["slope_length_m"])
            slope = float(plane["slope_percent"])
        except (KeyError, TypeError, ValueError):
            blockers.append(f"missing:ventilation_geometry:{plane_id}")
            continue
        status, height, reason = exact_or_conservative_vent_height(length_m, slope)
        if status == "blocked":
            blockers.append(f"roof_ventilation_input_outside_verified_matrix:{plane_id}")
        elif status != "verified_exact":
            warnings.append(f"ventilation_precheck_only:{plane_id}")
        result = VentilationResult(
            plane_id=plane_id,
            status=status,
            channel_height_mm=height,
            eaves_inlet_cm2_per_m=200 if height is not None else None,
            ridge_outlet_cm2_per_m=100 if height is not None and ridge_present else None,
            reason=reason,
        )
        out.append(asdict(result))
    return out


def select_architectural_nodes(context: dict[str, Any], blockers: list[str]) -> tuple[list[str], list[str]]:
    form = context.get("roof_form")
    topology = context.get("topology") or {}
    nodes: set[str] = set()
    families: set[str] = set()

    if form == "mono_pitch":
        nodes.update(["ROOF_AR_001_WALL_SUPPORT", "ROOF_AR_002_EAVES"])
        families.update(["roof_wall_support", "eaves"])
        if topology.get("vertical_abutment_count", 0):
            nodes.add("ROOF_AR_006_WALL_ABUTMENT")
            families.add("wall_abutment")
    elif form == "gable":
        nodes.update(["ROOF_AR_001_WALL_SUPPORT", "ROOF_AR_002_EAVES", "ROOF_AR_003_RIDGE", "ROOF_AR_007_GABLE_VERGE"])
        families.update(["roof_wall_support", "eaves", "ridge", "gable_verge"])
    elif form == "hip":
        nodes.update(["ROOF_AR_001_WALL_SUPPORT", "ROOF_AR_002_EAVES", "ROOF_AR_004_HIP"])
        families.update(["roof_wall_support", "eaves", "hip"])
        if topology.get("ridge_count", 0):
            nodes.add("ROOF_AR_003_RIDGE")
            families.add("ridge")
    else:
        blockers.append("roof_node_scope_unresolved:roof_form")

    if topology.get("valley_count", 0):
        nodes.add("ROOF_AR_005_VALLEY")
        families.add("valley")
    if topology.get("vertical_abutment_count", 0):
        nodes.add("ROOF_AR_006_WALL_ABUTMENT")
        families.add("wall_abutment")
    if topology.get("penetration_count", 0):
        nodes.add("ROOF_AR_008_PENETRATION")
        families.add("roof_penetration")
    return sorted(nodes), sorted(families)


def select_structural_nodes(context: dict[str, Any], blockers: list[str]) -> list[str]:
    variant = context.get("structural_variant_id")
    topology = context.get("topology") or {}
    result: set[str] = set()
    if not variant:
        blockers.append("roof_structural_scheme_missing")
        return []

    result.add("ROOF_KR_001_RAFTER_TO_WALL_SUPPORT")
    if variant == "roof.structure.rafter_pair_nonstructural_ridge":
        result.add("ROOF_KR_002_RAFTER_PAIR_APEX")
    elif variant == "roof.structure.structural_ridge_beam":
        result.add("ROOF_KR_003_RAFTER_TO_STRUCTURAL_RIDGE_BEAM")
    elif variant == "roof.structure.purlin_post_system":
        result.update(["ROOF_KR_004_RAFTER_TO_PURLIN", "ROOF_KR_005_PURLIN_TO_POST"])
    elif variant == "roof.structure.prefabricated_truss":
        result = {"ROOF_KR_007_TRUSS_TO_SUPPORT"}
    elif variant in {"roof.structure.hip_valley_rafter_system", "roof.structure.structural_ridge_beam"} and (
        topology.get("hip_count", 0) or topology.get("valley_count", 0)
    ):
        result.add("ROOF_KR_006_JACK_TO_HIP_OR_VALLEY")
    elif variant in {"roof.structure.LSTK", "roof.structure.panel_CLT_or_engineered_timber"}:
        # Exact joint families belong to KR/product system; keep architectural nodes but do not invent a timber joint.
        result.clear()
    else:
        blockers.append(f"unresolved_structural_variant:{variant}")
    if topology.get("hip_count", 0) or topology.get("valley_count", 0):
        if variant == "roof.structure.hip_valley_rafter_system":
            result.add("ROOF_KR_006_JACK_TO_HIP_OR_VALLEY")
    return sorted(result)


def structural_execution_gate(context: dict[str, Any], mode: str, blockers: list[str]) -> None:
    if mode not in {"execute_geometry", "approved_for_model"}:
        return
    require(context, ["KR_revision", "structural_roof_scheme_reference"], blockers)
    kr = context.get("KR_data")
    if not isinstance(kr, dict):
        blockers.append("roof_KR_input_missing:KR_data")
        return
    require(kr, ["member_schedule", "member_axis_geometry", "support_graph", "connection_schedule", "bracing_graph"], blockers)


def compile_operations(
    context: dict[str, Any], mode: str, architectural_nodes: list[str], structural_nodes: list[str], blockers: list[str]
) -> list[dict[str, Any]]:
    ops: list[dict[str, Any]] = [
        {"op": "classify_roof_topology", "write": False},
        {"op": "validate_covering_slope", "write": False},
        {"op": "resolve_roof_node_instances", "write": False, "node_ids": architectural_nodes},
        {"op": "resolve_structural_joint_instances", "write": False, "node_ids": structural_nodes},
    ]
    if blockers or mode in {"classify_only", "coordinate"}:
        return ops
    ops.extend(
        [
            {"op": "CreateRoofs", "write": True, "source": "approved_project_roof_geometry"},
            {"op": "CreateBeams", "write": True, "source": "KR_data", "conditional": bool(structural_nodes)},
            {"op": "TrimElements", "write": True, "source": "verified_host_relationships"},
            {"op": "CreateProfiles/CreateObjects/CreateDetails", "write": True, "source": "node_recipe_and_covering_adapter"},
            {"op": "readback", "write": False, "required": True},
            {"op": "validate_contours", "write": False, "required": True},
        ]
    )
    return ops


def compile_roof_plan(payload: dict[str, Any]) -> RoofPlan:
    intent = str(payload.get("intent") or "")
    if intent not in {"build_pitched_roof", "rebuild_roof_nodes", "validate_roof_nodes"}:
        raise RoofEngineError(f"unsupported intent: {intent!r}")
    context = payload.get("context")
    if not isinstance(context, dict):
        raise RoofEngineError("context must be an object")
    mode = str(payload.get("mode") or "coordinate")
    if mode not in {"classify_only", "coordinate", "execute_geometry", "approved_for_model"}:
        raise RoofEngineError(f"unsupported mode: {mode}")

    blockers: list[str] = []
    warnings: list[str] = []
    require(context, ["roof_form", "covering_system_id", "thermal_boundary_mode", "ventilation_mode"], blockers)
    if context.get("covering_system_id") in {None, "", "unknown"}:
        blockers.append("roof_covering_system_missing")

    catalog = load_yaml("roof_canonical_node_catalog.yaml")
    idx = catalog_index(catalog)
    arch_nodes, families = select_architectural_nodes(context, blockers)
    structural_nodes = select_structural_nodes(context, blockers)

    for node_id in arch_nodes + structural_nodes:
        if node_id not in idx:
            blockers.append(f"catalog_missing:{node_id}")

    ventilation = ventilation_results(context, blockers, warnings)
    structural_execution_gate(context, mode, blockers)

    if context.get("topology", {}).get("penetration_count", 0) and mode in {"execute_geometry", "approved_for_model"}:
        if not context.get("penetrations"):
            blockers.append("structural_penetration_not_approved:penetration_records_missing")

    blockers = sorted(set(blockers))
    warnings = sorted(set(warnings))
    operations = compile_operations(context, mode, arch_nodes, structural_nodes, blockers)
    status = "blocked" if blockers else ("coordination_ready" if mode in {"classify_only", "coordinate"} else "execution_ready")
    return RoofPlan(
        status=status,
        intent=intent,
        node_ids=arch_nodes,
        node_families=families,
        structural_node_ids=structural_nodes,
        blockers=blockers,
        warnings=warnings,
        ventilation=ventilation,
        operations=operations,
        source_files=[
            "08_roof_execution_contract.yaml",
            "09_roof_node_router.yaml",
            "10_roof_ventilation_matrix.yaml",
            "11_rafter_system_topology.yaml",
            "roof_canonical_node_catalog.yaml",
            "roof_rafter_connection_nodes.yaml",
            "roof_rafter_member_graph.yaml",
        ],
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Compile high-level roof intent into a fail-closed roof node execution plan.")
    parser.add_argument("input", nargs="?", help="JSON file. If omitted, JSON is read from stdin.")
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args()
    try:
        if args.input:
            payload = json.loads(Path(args.input).read_text(encoding="utf-8"))
        else:
            payload = json.load(sys.stdin)
        plan = compile_roof_plan(payload)
        json.dump(plan.to_dict(), sys.stdout, ensure_ascii=False, indent=2 if args.pretty else None, sort_keys=True)
        sys.stdout.write("\n")
        return 2 if plan.status == "blocked" else 0
    except (RoofEngineError, json.JSONDecodeError, OSError) as exc:
        json.dump({"status": "error", "error": str(exc)}, sys.stdout, ensure_ascii=False)
        sys.stdout.write("\n")
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
