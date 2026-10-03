from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
RULES = ROOT / "rules"
IZH = ROOT / "izh"
NODES = ROOT / "nodes"
EXPECTED_PROFILE = "RU_2027_PLUS"
FUNCTIONAL_ROUTER = RULES / "28_functional_code_router.yaml"
ALLOWED_OBJECT_CLASSES = {"IZHS", "MKD", "PUBLIC", "TRK", "INDUSTRIAL"}
EXPECTED_FILE_SCOPES: dict[str, set[str]] = {
    "35_residential_planning_minima.yaml": {"MKD"},
    "36_residential_wet_zone_stacking.yaml": {"MKD"},
    "37_residential_balconies_loggias.yaml": {"MKD"},
    "40_residential_vertical_transport.yaml": {"MKD"},
    "53_garant_residential_planning_verification.yaml": {"MKD"},
    "61_residential_entrance_vestibules_climate.yaml": {"MKD"},
    "65_timber_apartment_fire_2026.yaml": {"MKD"},
    "100_residential_gas_architectural_interfaces_2027.yaml": {"IZHS", "MKD"},
    "07_guardrails_roofs.yaml": {"IZHS", "MKD", "PUBLIC", "TRK", "INDUSTRIAL"},
    "04_architectural_baseline.yaml": {"IZHS", "MKD", "PUBLIC", "TRK", "INDUSTRIAL"},
}


def is_machine_rule(node: dict[str, Any]) -> bool:
    rule_markers = {
        "automation",
        "auto_rule",
        "statement",
        "dimension_semantics",
        "requires_calculation",
        "requires_manufacturer_data",
        "agent_action",
        "result",
        "result_on_missing",
        "result_on_violation",
    }
    return isinstance(node.get("id"), str) and bool(rule_markers.intersection(node))


def walk_rule_ids(node: Any, path: str = ""):
    if isinstance(node, dict):
        if is_machine_rule(node):
            yield node["id"], path
        for key, value in node.items():
            child = f"{path}.{key}" if path else str(key)
            yield from walk_rule_ids(value, child)
    elif isinstance(node, list):
        for i, value in enumerate(node):
            yield from walk_rule_ids(value, f"{path}[{i}]")


def is_node_definition(node: dict[str, Any]) -> bool:
    node_id = node.get("node_id")
    if not isinstance(node_id, str):
        return False
    definition_markers = {"hosts", "family", "recipe", "applies_if", "geometry_actions"}
    return bool(definition_markers.intersection(node))


def walk_node_definitions(node: Any, path: str = ""):
    if isinstance(node, dict):
        if is_node_definition(node):
            yield node["node_id"], path
        for key, value in node.items():
            child = f"{path}.{key}" if path else str(key)
            yield from walk_node_definitions(value, child)
    elif isinstance(node, list):
        for i, value in enumerate(node):
            yield from walk_node_definitions(value, f"{path}[{i}]")


def validate_profile_file(file: Path, doc: Any, errors: list[str]) -> None:
    if not isinstance(doc, dict):
        errors.append(f"profile file must have mapping root: {file.relative_to(ROOT)}")
        return
    profile = doc.get("target_profile")
    if profile is not None and profile != EXPECTED_PROFILE:
        errors.append(f"wrong target_profile in {file.relative_to(ROOT)}: {profile!r}")
    if "checked_at" not in doc:
        errors.append(f"missing checked_at: {file.relative_to(ROOT)}")


def validate_package_manifest(
    parsed: dict[Path, Any], directory: Path, name: str, errors: list[str]
) -> None:
    manifest = parsed.get(directory / "manifest.yaml")
    if not isinstance(manifest, dict):
        errors.append(f"{name} manifest.yaml missing or invalid")
        return
    listed = set(manifest.get("load_order") or [])
    actual = {p.name for p in directory.glob("*.yaml") if p.name != "manifest.yaml"}
    missing = sorted(actual - listed)
    stale = sorted(listed - actual)
    if missing:
        errors.append(f"{name} manifest missing YAML files: {missing}")
    if stale:
        errors.append(f"{name} manifest lists absent YAML files: {stale}")
    if manifest.get("target_profile") != EXPECTED_PROFILE:
        errors.append(f"{name} manifest target_profile mismatch")


def validate_rule_file_scope_registry(parsed: dict[Path, Any], errors: list[str]) -> None:
    router = parsed.get(FUNCTIONAL_ROUTER)
    if not isinstance(router, dict):
        errors.append("functional router missing or invalid for object-class scope validation")
        return
    registry = router.get("rule_file_scope_registry")
    if not isinstance(registry, dict):
        errors.append("functional router missing rule_file_scope_registry")
        return
    if registry.get("mode") != "hard_gate_before_rule_evaluation":
        errors.append("rule_file_scope_registry must use hard_gate_before_rule_evaluation")
    files = registry.get("files")
    if not isinstance(files, dict):
        errors.append("rule_file_scope_registry.files must be a mapping")
        return

    for filename, expected_allowed in EXPECTED_FILE_SCOPES.items():
        row = files.get(filename)
        if not isinstance(row, dict):
            errors.append(f"scope registry missing required rule file: {filename}")
            continue
        if not (RULES / filename).exists():
            errors.append(f"scope registry references absent rule file: {filename}")
        allowed = set(row.get("allowed_object_classes") or [])
        forbidden = set(row.get("forbidden_object_classes") or [])
        unknown = (allowed | forbidden) - ALLOWED_OBJECT_CLASSES
        if unknown:
            errors.append(f"scope registry {filename} has unknown object classes: {sorted(unknown)}")
        if allowed != expected_allowed:
            errors.append(
                f"scope registry {filename} allowed classes {sorted(allowed)} do not match expected {sorted(expected_allowed)}"
            )
        overlap = allowed & forbidden
        if overlap:
            errors.append(f"scope registry {filename} both allows and forbids: {sorted(overlap)}")
        hard_gate = row.get("hard_gate")
        if hard_gate not in (True, "section_scoped"):
            errors.append(f"scope registry {filename} must have a hard gate")

    mkd_only = {
        "35_residential_planning_minima.yaml",
        "36_residential_wet_zone_stacking.yaml",
        "37_residential_balconies_loggias.yaml",
        "40_residential_vertical_transport.yaml",
        "53_garant_residential_planning_verification.yaml",
        "61_residential_entrance_vestibules_climate.yaml",
        "65_timber_apartment_fire_2026.yaml",
    }
    for filename in mkd_only:
        row = files.get(filename)
        if isinstance(row, dict):
            allowed = set(row.get("allowed_object_classes") or [])
            forbidden = set(row.get("forbidden_object_classes") or [])
            if "IZHS" in allowed or "IZHS" not in forbidden:
                errors.append(f"MKD-only rule file {filename} must hard-forbid IZHS")

    gas = files.get("100_residential_gas_architectural_interfaces_2027.yaml")
    if isinstance(gas, dict):
        overrides = gas.get("section_overrides")
        if not isinstance(overrides, dict):
            errors.append("SP402 scope registry must define section_overrides")
        else:
            for section in ("multifamily_residential", "locator_5_16"):
                row = overrides.get(section)
                if not isinstance(row, dict):
                    errors.append(f"SP402 scope registry missing section override {section}")
                    continue
                allowed = set(row.get("allowed_object_classes") or [])
                forbidden = set(row.get("forbidden_object_classes") or [])
                if allowed != {"MKD"} or "IZHS" not in forbidden:
                    errors.append(f"SP402 section {section} must be MKD-only and forbid IZHS")

    guardrails = files.get("07_guardrails_roofs.yaml")
    if isinstance(guardrails, dict):
        overrides = guardrails.get("section_overrides")
        if not isinstance(overrides, dict):
            errors.append("guardrails scope registry must define section_overrides")
        else:
            residential = overrides.get("residential_project_requirements")
            public = overrides.get("public_project_requirements")
            if not isinstance(residential, dict) or set(residential.get("allowed_object_classes") or []) != {"MKD"}:
                errors.append("guardrails residential_project_requirements must be MKD-only")
            if isinstance(residential, dict) and "IZHS" not in set(residential.get("forbidden_object_classes") or []):
                errors.append("guardrails residential_project_requirements must forbid IZHS")
            if not isinstance(public, dict) or set(public.get("allowed_object_classes") or []) != {"PUBLIC"}:
                errors.append("guardrails public_project_requirements must be PUBLIC-only")

    baseline = files.get("04_architectural_baseline.yaml")
    if isinstance(baseline, dict):
        overrides = baseline.get("section_overrides")
        if not isinstance(overrides, dict):
            errors.append("architectural baseline scope registry must define section_overrides")
        else:
            residential = overrides.get("building_height_rules.residential_apartments")
            public = overrides.get("building_height_rules.public_buildings")
            if not isinstance(residential, dict) or set(residential.get("allowed_object_classes") or []) != {"MKD"}:
                errors.append("architectural baseline residential heights must be MKD-only")
            if isinstance(residential, dict) and "IZHS" not in set(residential.get("forbidden_object_classes") or []):
                errors.append("architectural baseline residential heights must forbid IZHS")
            if not isinstance(public, dict) or set(public.get("allowed_object_classes") or []) != {"PUBLIC"}:
                errors.append("architectural baseline public heights must be PUBLIC-only")


def validate_node_test_references(
    parsed: dict[Path, Any], known_node_ids: set[str], errors: list[str]
) -> None:
    test_file = NODES / "23_node_test_vectors.yaml"
    doc = parsed.get(test_file)
    if not isinstance(doc, dict):
        return
    tests = doc.get("tests") or []
    if not isinstance(tests, list):
        errors.append("NODES test vectors 'tests' must be a list")
        return
    for test in tests:
        if not isinstance(test, dict):
            continue
        test_id = test.get("test_id", "<unknown>")
        expected = test.get("expected")
        if not isinstance(expected, dict):
            errors.append(f"node test {test_id!r} missing expected mapping")
            continue
        refs: list[str] = []
        one = expected.get("node_id")
        many = expected.get("node_ids")
        if isinstance(one, str):
            refs.append(one)
        if isinstance(many, list):
            refs.extend(ref for ref in many if isinstance(ref, str))
        for ref in refs:
            if ref not in known_node_ids:
                errors.append(f"node test {test_id!r} references unknown node_id {ref!r}")


def validate_intent_contract(parsed: dict[Path, Any], errors: list[str]) -> None:
    contract = parsed.get(NODES / "06_high_level_command_contract.yaml")
    selector = parsed.get(NODES / "22_selector_decision_graph.yaml")
    tests_doc = parsed.get(NODES / "23_node_test_vectors.yaml")

    if not isinstance(contract, dict):
        errors.append("high-level command contract missing or invalid")
        return
    intent_contract = contract.get("intent_contract")
    if not isinstance(intent_contract, dict):
        errors.append("high-level command contract missing intent_contract mapping")
        return
    supported_raw = intent_contract.get("supported_intents")
    if not isinstance(supported_raw, list):
        errors.append("high-level command supported_intents must be a list")
        return
    supported = {x for x in supported_raw if isinstance(x, str)}

    if isinstance(selector, dict):
        entrypoints = selector.get("entrypoints")
        if isinstance(entrypoints, dict):
            selector_intents = {x for x in entrypoints if isinstance(x, str)}
            missing = sorted(selector_intents - supported)
            if missing:
                errors.append(f"selector entrypoints missing from supported_intents: {missing}")

    required_release_intents = {
        "generate_working_documentation",
        "validate_working_documentation",
        "prepare_external_review_package",
        "process_external_review_comments",
    }
    missing_release = sorted(required_release_intents - supported)
    if missing_release:
        errors.append(f"working-documentation intents missing: {missing_release}")

    if isinstance(tests_doc, dict):
        tests = tests_doc.get("tests") or []
        if isinstance(tests, list):
            for test in tests:
                if not isinstance(test, dict):
                    continue
                intent = test.get("intent")
                if isinstance(intent, str) and intent not in supported:
                    errors.append(
                        f"node test {test.get('test_id', '<unknown>')!r} uses unsupported intent {intent!r}"
                    )

    release_contract = contract.get("release_status_contract")
    if not isinstance(release_contract, dict):
        errors.append("high-level command contract missing release_status_contract")
    else:
        allowed = set(release_contract.get("allowed") or [])
        forbidden = set(release_contract.get("forbidden_without_human_external_result") or [])
        if "ready_for_external_review" not in allowed:
            errors.append("release_status_contract must allow ready_for_external_review")
        if "expertise_approved" in allowed:
            errors.append("expertise_approved must never be an automatically allowed release status")
        if "expertise_approved" not in forbidden:
            errors.append("expertise_approved must be explicitly forbidden without human external result")


def validate_documentation_release_contracts(
    parsed: dict[Path, Any], errors: list[str]
) -> None:
    wd_file = NODES / "42_working_documentation_release_gate.yaml"
    exp_file = NODES / "43_expertise_readiness_contract.yaml"
    wd = parsed.get(wd_file)
    exp = parsed.get(exp_file)

    if not isinstance(wd, dict):
        errors.append("working documentation release gate missing or invalid")
    else:
        required_sections = {
            "model_release_gate",
            "working_drawing_gate",
            "cross_discipline_gate",
            "issue_register_required_fields",
            "release_receipt",
            "hard_fail",
        }
        missing = sorted(required_sections - set(wd))
        if missing:
            errors.append(f"working documentation release gate missing sections: {missing}")

    if not isinstance(exp, dict):
        errors.append("expertise readiness contract missing or invalid")
    else:
        levels = exp.get("readiness_levels") or []
        level_ids = {
            row.get("level")
            for row in levels
            if isinstance(row, dict) and isinstance(row.get("level"), str)
        }
        if "L3_EXTERNAL_REVIEW_READY" not in level_ids:
            errors.append("expertise readiness contract missing L3_EXTERNAL_REVIEW_READY")
        policy_text = str(exp.get("readiness_policy", ""))
        if "no_approval_claim" not in policy_text:
            errors.append("expertise readiness contract must prohibit approval claims")


def main() -> int:
    errors: list[str] = []
    parsed: dict[Path, Any] = {}

    yaml_files = sorted(ROOT.rglob("*.yaml"))
    if not yaml_files:
        errors.append("no YAML files found")

    for file in yaml_files:
        try:
            parsed[file] = yaml.safe_load(file.read_text(encoding="utf-8"))
        except Exception as exc:
            errors.append(f"YAML parse error: {file.relative_to(ROOT)}: {exc}")

    seen_rule_ids: dict[str, tuple[Path, str]] = {}
    for file, doc in parsed.items():
        in_rules = file.parent == RULES
        in_izh = file.parent == IZH
        in_nodes = file.parent == NODES
        if not (in_rules or in_izh or in_nodes):
            continue
        if file.name == "manifest.yaml":
            continue
        validate_profile_file(file, doc, errors)
        if not isinstance(doc, dict):
            continue
        for rule_id, node_path in walk_rule_ids(doc):
            previous = seen_rule_ids.get(rule_id)
            if previous:
                p_file, p_path = previous
                errors.append(
                    "duplicate machine rule id "
                    f"{rule_id!r}: {p_file.relative_to(ROOT)}:{p_path} and "
                    f"{file.relative_to(ROOT)}:{node_path}"
                )
            else:
                seen_rule_ids[rule_id] = (file, node_path)

    seen_node_ids: dict[str, tuple[Path, str]] = {}
    for file, doc in parsed.items():
        if file.parent != NODES or file.name == "manifest.yaml":
            continue
        for node_id, node_path in walk_node_definitions(doc):
            previous = seen_node_ids.get(node_id)
            if previous:
                p_file, p_path = previous
                errors.append(
                    "duplicate construction node_id "
                    f"{node_id!r}: {p_file.relative_to(ROOT)}:{p_path} and "
                    f"{file.relative_to(ROOT)}:{node_path}"
                )
            else:
                seen_node_ids[node_id] = (file, node_path)

    validate_rule_file_scope_registry(parsed, errors)
    validate_node_test_references(parsed, set(seen_node_ids), errors)
    validate_intent_contract(parsed, errors)
    validate_documentation_release_contracts(parsed, errors)

    manifest = parsed.get(ROOT / "manifest.yaml")
    if isinstance(manifest, dict):
        listed = set(manifest.get("rule_files") or [])
        actual = {p.name for p in RULES.glob("*.yaml")}
        missing = sorted(actual - listed)
        stale = sorted(listed - actual)
        if missing:
            errors.append(f"manifest missing rule files: {missing}")
        if stale:
            errors.append(f"manifest lists absent rule files: {stale}")
    else:
        errors.append("manifest.yaml missing or invalid")

    validate_package_manifest(parsed, IZH, "IZH", errors)
    validate_package_manifest(parsed, NODES, "NODES", errors)

    if errors:
        print("NORMATIVE BASE VALIDATION FAILED")
        for error in errors:
            print(f"- {error}")
        return 1

    print(
        f"OK: {len(yaml_files)} YAML files parsed; "
        f"{len(seen_rule_ids)} unique machine rule ids; "
        f"{len(seen_node_ids)} unique construction node ids; manifests synchronized; "
        "object-class routing, high-level intents and documentation release contracts validated."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
