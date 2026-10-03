from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
ROOT_MANIFEST = ROOT / "manifest.yaml"
LIBRARY_MANIFEST = ROOT / "library" / "library_manifest.yaml"
REQUIRED_CATALOGS = {
    "izh_dependency_catalog.yaml",
    "multi_profile_dependency_catalog.yaml",
    "profile_rule_coverage_registry.yaml",
    "locator_registry.yaml",
    "functional_scope_registry.yaml",
    "engineering_system_scope_registry.yaml",
}
REQUIRED_HARD_FAILS = {
    "required_scope_gate_missing",
    "blocked_locator_used_for_numeric_generation",
    "engineering_system_scope_unknown_for_selected_rule",
}


def load(path: Path) -> Any:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def main() -> int:
    errors: list[str] = []
    try:
        root = load(ROOT_MANIFEST)
    except Exception as exc:
        print(f"LIBRARY INTEGRATION VALIDATION FAILED\n- root manifest unreadable: {exc}")
        return 1
    try:
        library = load(LIBRARY_MANIFEST)
    except Exception as exc:
        print(f"LIBRARY INTEGRATION VALIDATION FAILED\n- library manifest unreadable: {exc}")
        return 1

    if not isinstance(root, dict):
        errors.append("root manifest must be a mapping")
        root = {}
    if not isinstance(library, dict):
        errors.append("library manifest must be a mapping")
        library = {}

    if library.get("production_authority") is not False:
        errors.append("library must remain production_authority: false")
    if library.get("role") != "evidence_and_scope_router":
        errors.append("library role must remain evidence_and_scope_router")

    load_order = root.get("load_order")
    if not isinstance(load_order, list):
        errors.append("root manifest load_order must be a list")
        load_order = []

    library_priority = None
    rules_priority = None
    for row in load_order:
        if not isinstance(row, dict):
            continue
        if row.get("file") == "library/library_manifest.yaml":
            library_priority = row.get("priority")
        if row.get("files") == "rules/*.yaml":
            rules_priority = row.get("priority")

    if library_priority is None:
        errors.append("root manifest does not load library/library_manifest.yaml")
    if rules_priority is None:
        errors.append("root manifest does not load rules/*.yaml")
    if isinstance(library_priority, int) and isinstance(rules_priority, int):
        if library_priority >= rules_priority:
            errors.append("library must load before production rules")

    catalogs = set(library.get("catalogs") or [])
    missing_catalogs = sorted(REQUIRED_CATALOGS - catalogs)
    if missing_catalogs:
        errors.append(f"library manifest missing required catalogs: {missing_catalogs}")
    for catalog in REQUIRED_CATALOGS:
        if not (ROOT / "library" / catalog).exists():
            errors.append(f"required library catalog file missing: {catalog}")

    coverage = library.get("coverage")
    coverage_row = coverage.get("profile_rule_coverage") if isinstance(coverage, dict) else None
    if not isinstance(coverage_row, dict):
        errors.append("library manifest missing profile_rule_coverage summary")
    else:
        if coverage_row.get("source") != "profile_rule_coverage_registry.yaml":
            errors.append("profile_rule_coverage source mismatch")
        if coverage_row.get("dedicated_rule_gap_count") != 9:
            errors.append("profile_rule_coverage dedicated_rule_gap_count must reflect current explicit inventory")

    hard_fails = set(root.get("hard_fail_states") or [])
    missing_hard_fails = sorted(REQUIRED_HARD_FAILS - hard_fails)
    if missing_hard_fails:
        errors.append(f"root manifest missing library/scope hard-fail states: {missing_hard_fails}")

    release = root.get("release_gate")
    requirements = release.get("require") if isinstance(release, dict) else None
    if not isinstance(requirements, list):
        errors.append("root release_gate.require must be a list")
        requirements = []
    requirements_text = "\n".join(str(x) for x in requirements)
    required_phrases = [
        "library/library_manifest.yaml is loaded before rules/*.yaml",
        "object-class, functional-zone and engineering-system scope validators pass",
        "blocked_pending_locator never supplies a production numeric value or applicability route",
        "existing_rule_traceability_pending never counts as a new library PASS",
    ]
    for phrase in required_phrases:
        if phrase not in requirements_text:
            errors.append(f"root release gate missing requirement: {phrase}")

    if errors:
        print("LIBRARY INTEGRATION VALIDATION FAILED")
        for error in errors:
            print(f"- {error}")
        return 1

    print(
        "OK: evidence/scope library is non-production authority, loaded before rules, and all required scope/coverage catalogs are integrated."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
