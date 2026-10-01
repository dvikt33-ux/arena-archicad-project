from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
RULES = ROOT / "rules"
IZH = ROOT / "izh"
EXPECTED_PROFILE = "RU_2027_PLUS"


def is_machine_rule(node: dict[str, Any]) -> bool:
    """Distinguish machine-rule identifiers from repeated document/node catalog IDs."""
    rule_markers = {
        "automation",
        "auto_rule",
        "statement",
        "dimension_semantics",
        "requires_calculation",
        "requires_manufacturer_data",
        "agent_action",
        "result",
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


def validate_profile_file(file: Path, doc: Any, errors: list[str]) -> None:
    if not isinstance(doc, dict):
        errors.append(f"profile file must have mapping root: {file.relative_to(ROOT)}")
        return
    profile = doc.get("target_profile")
    if profile is not None and profile != EXPECTED_PROFILE:
        errors.append(f"wrong target_profile in {file.relative_to(ROOT)}: {profile!r}")
    if "checked_at" not in doc:
        errors.append(f"missing checked_at: {file.relative_to(ROOT)}")


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
        if not (in_rules or in_izh):
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

    izh_manifest = parsed.get(IZH / "manifest.yaml")
    if isinstance(izh_manifest, dict):
        listed = set(izh_manifest.get("load_order") or [])
        actual = {p.name for p in IZH.glob("*.yaml") if p.name != "manifest.yaml"}
        missing = sorted(actual - listed)
        stale = sorted(listed - actual)
        if missing:
            errors.append(f"IZH manifest missing YAML files: {missing}")
        if stale:
            errors.append(f"IZH manifest lists absent YAML files: {stale}")
        if izh_manifest.get("target_profile") != EXPECTED_PROFILE:
            errors.append("IZH manifest target_profile mismatch")
    else:
        errors.append("izh/manifest.yaml missing or invalid")

    if errors:
        print("NORMATIVE BASE VALIDATION FAILED")
        for error in errors:
            print(f"- {error}")
        return 1

    print(
        f"OK: {len(yaml_files)} YAML files parsed; "
        f"{len(seen_rule_ids)} unique machine rule ids; manifests synchronized."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
