from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
RULES = ROOT / "rules"
REGISTRY_FILE = ROOT / "library" / "functional_scope_registry.yaml"
EXPECTED_PROFILE = "RU_2027_PLUS"
OBJECT_CLASSES = {"IZHS", "MKD", "PUBLIC", "TRK", "INDUSTRIAL"}

EXPECTED: dict[str, dict[str, Any]] = {
    "43_public_sanitary_facilities.yaml": {
        "allowed": {"PUBLIC", "TRK"},
        "gate_type": "functional_zone",
    },
    "59_public_lift_lobby_exceptions.yaml": {
        "allowed": {"PUBLIC", "TRK"},
        "gate_type": "functional_zone",
    },
    "70_trk_multifunctional_planning_2027.yaml": {
        "allowed": {"PUBLIC", "TRK"},
        "gate_type": "special_profile",
        "profiles_any": {"SP_464_1325800_2019", "SP_160_1325800_2014"},
    },
    "71_public_special_functions_2027.yaml": {
        "allowed": {"PUBLIC", "TRK"},
        "gate_type": "functional_zone",
    },
    "87_trk_children_foodservice_2027.yaml": {
        "allowed": {"PUBLIC", "TRK"},
        "gate_type": "functional_zone",
    },
    "88_food_retail_sanitary_2027.yaml": {
        "allowed": {"PUBLIC", "TRK"},
        "gate_type": "functional_zone",
    },
    "89_trk_loading_logistics_2027.yaml": {
        "allowed": {"TRK"},
        "gate_type": "special_profile",
        "required_profile": "SP_464_1325800_2019",
    },
    "103_public_gas_architectural_interfaces_2027.yaml": {
        "allowed": {"PUBLIC", "TRK"},
        "gate_type": "functional_zone",
    },
    "105_foodservice_wastewater_grease_interfaces_2027.yaml": {
        "allowed": {"PUBLIC", "TRK"},
        "gate_type": "functional_zone",
    },
    "106_trk_waste_collection_interfaces_2027.yaml": {
        "allowed": {"PUBLIC", "TRK"},
        "gate_type": "functional_zone",
    },
}


def load_yaml(path: Path) -> Any:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def main() -> int:
    errors: list[str] = []
    if not REGISTRY_FILE.exists():
        errors.append("functional scope registry missing")
        doc = None
    else:
        try:
            doc = load_yaml(REGISTRY_FILE)
        except Exception as exc:
            errors.append(f"functional scope registry YAML parse error: {exc}")
            doc = None

    if isinstance(doc, dict):
        if doc.get("target_profile") != EXPECTED_PROFILE:
            errors.append("functional scope registry target_profile mismatch")
        semantics = doc.get("scope_semantics")
        if not isinstance(semantics, dict):
            errors.append("functional scope registry missing scope_semantics")
        else:
            if semantics.get("mismatch_result") != "not_applicable":
                errors.append("functional scope mismatch_result must be not_applicable")
            if semantics.get("missing_required_functional_zone") != "object_classification_required":
                errors.append("missing functional-zone classification must fail closed")
            if semantics.get("missing_required_special_profile") != "object_classification_required":
                errors.append("missing special-profile classification must fail closed")

        files = doc.get("file_scopes")
        if not isinstance(files, dict):
            errors.append("functional scope registry file_scopes must be a mapping")
            files = {}

        for filename, expected in EXPECTED.items():
            row = files.get(filename)
            if not isinstance(row, dict):
                errors.append(f"functional scope registry missing {filename}")
                continue
            if not (RULES / filename).exists():
                errors.append(f"functional scope registry references absent rule file {filename}")

            allowed = set(row.get("allowed_active_zone_classes") or [])
            forbidden = set(row.get("forbidden_active_zone_classes") or [])
            unknown = (allowed | forbidden) - OBJECT_CLASSES
            if unknown:
                errors.append(f"{filename} has unknown object classes: {sorted(unknown)}")
            if allowed != expected["allowed"]:
                errors.append(
                    f"{filename} allowed classes {sorted(allowed)} != expected {sorted(expected['allowed'])}"
                )
            if allowed & forbidden:
                errors.append(f"{filename} both allows and forbids {sorted(allowed & forbidden)}")
            if "IZHS" in allowed:
                errors.append(f"{filename} must not allow IZHS")
            if row.get("gate_type") != expected["gate_type"]:
                errors.append(f"{filename} gate_type mismatch")

            if expected["gate_type"] == "functional_zone":
                has_context = any(
                    key in row
                    for key in ("required_context", "required_function", "required_functions_any")
                )
                if not has_context:
                    errors.append(f"{filename} functional-zone gate lacks explicit required function/context")

            required_profile = expected.get("required_profile")
            if required_profile and row.get("required_special_profile") != required_profile:
                errors.append(f"{filename} missing required special profile {required_profile}")

            profiles_any = expected.get("profiles_any")
            if profiles_any:
                actual_profiles = set(row.get("required_special_profiles_any") or [])
                if actual_profiles != profiles_any:
                    errors.append(
                        f"{filename} special profiles {sorted(actual_profiles)} != expected {sorted(profiles_any)}"
                    )

        food_retail = files.get("88_food_retail_sanitary_2027.yaml")
        if isinstance(food_retail, dict) and not food_retail.get("embedded_in_MKD_rule"):
            errors.append("food-retail scope must explicitly protect residential zones in embedded MKD")

        foodservice = files.get("105_foodservice_wastewater_grease_interfaces_2027.yaml")
        if isinstance(foodservice, dict) and not foodservice.get("embedded_in_MKD_rule"):
            errors.append("foodservice scope must explicitly protect residential zones in embedded MKD")

        trk_loading = files.get("89_trk_loading_logistics_2027.yaml")
        if isinstance(trk_loading, dict) and set(trk_loading.get("allowed_active_zone_classes") or []) != {"TRK"}:
            errors.append("SP464 loading logistics must remain TRK-only")

        waste = files.get("106_trk_waste_collection_interfaces_2027.yaml")
        if isinstance(waste, dict):
            overrides = waste.get("section_overrides")
            if not isinstance(overrides, dict):
                errors.append("waste scope must define section_overrides")
            else:
                trk20 = overrides.get("waste.trk.container_site_20m_sensitive_neighbors")
                if not isinstance(trk20, dict):
                    errors.append("waste TRK 20m rule scope override missing")
                else:
                    if set(trk20.get("allowed_active_zone_classes") or []) != {"TRK"}:
                        errors.append("SP464 waste 20m rule must be TRK-only")
                    if trk20.get("required_special_profile") != "SP_464_1325800_2019":
                        errors.append("SP464 waste 20m rule must require SP464 profile")
    elif doc is not None:
        errors.append("functional scope registry root must be a mapping")

    if errors:
        print("FUNCTIONAL SCOPE VALIDATION FAILED")
        for error in errors:
            print(f"- {error}")
        return 1

    print(
        f"OK: {len(EXPECTED)} PUBLIC/TRK functional/special rule files have fail-closed scope gates; "
        "IZHS leakage blocked; embedded public functions require explicit functional-zone classification."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
