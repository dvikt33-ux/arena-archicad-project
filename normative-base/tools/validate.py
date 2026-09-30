from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
RULES = ROOT / "rules"
EXPECTED_PROFILE = "RU_2027_PLUS"


def walk_ids(node: Any, path: str = ""):
    if isinstance(node, dict):
        if isinstance(node.get("id"), str):
            yield node["id"], path
        for key, value in node.items():
            child = f"{path}.{key}" if path else str(key)
            yield from walk_ids(value, child)
    elif isinstance(node, list):
        for i, value in enumerate(node):
            yield from walk_ids(value, f"{path}[{i}]")


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

    seen_ids: dict[str, tuple[Path, str]] = {}
    for file, doc in parsed.items():
        if file.parent == RULES:
            if not isinstance(doc, dict):
                errors.append(f"rule file must have mapping root: {file.relative_to(ROOT)}")
                continue
            profile = doc.get("target_profile")
            if profile is not None and profile != EXPECTED_PROFILE:
                errors.append(
                    f"wrong target_profile in {file.relative_to(ROOT)}: {profile!r}"
                )
            if "checked_at" not in doc:
                errors.append(f"missing checked_at: {file.relative_to(ROOT)}")

        for rule_id, node_path in walk_ids(doc):
            previous = seen_ids.get(rule_id)
            if previous:
                p_file, p_path = previous
                errors.append(
                    "duplicate id "
                    f"{rule_id!r}: {p_file.relative_to(ROOT)}:{p_path} and "
                    f"{file.relative_to(ROOT)}:{node_path}"
                )
            else:
                seen_ids[rule_id] = (file, node_path)

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

    if errors:
        print("NORMATIVE BASE VALIDATION FAILED")
        for error in errors:
            print(f"- {error}")
        return 1

    print(
        f"OK: {len(yaml_files)} YAML files parsed; "
        f"{len(seen_ids)} unique rule ids; manifest synchronized."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
