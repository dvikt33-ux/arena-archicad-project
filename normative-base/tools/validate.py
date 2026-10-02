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

    validate_node_test_references(parsed, set(seen_node_ids), errors)

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
        f"{len(seen_node_ids)} unique construction node ids; manifests synchronized."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
