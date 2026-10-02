from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
ENGINE_PATH = ROOT / "tools" / "roof_node_engine.py"
VECTORS_PATH = ROOT / "nodes" / "roof_test_vectors.yaml"


def load_engine():
    spec = importlib.util.spec_from_file_location("roof_node_engine", ENGINE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load roof_node_engine")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def has_prefix(items: list[str], prefix: str) -> bool:
    return any(item == prefix or item.startswith(prefix + ":") for item in items)


def main() -> int:
    engine = load_engine()
    doc = yaml.safe_load(VECTORS_PATH.read_text(encoding="utf-8"))
    vectors = doc.get("vectors", []) if isinstance(doc, dict) else []
    failures: list[str] = []

    for vector in vectors:
        vector_id = vector.get("id", "unknown")
        plan = engine.compile_roof_plan(vector["payload"]).to_dict()
        expect: dict[str, Any] = vector.get("expect", {})

        if "status" in expect and plan["status"] != expect["status"]:
            failures.append(f"{vector_id}: status {plan['status']!r} != {expect['status']!r}")

        for node_id in expect.get("contains_node_ids", []):
            if node_id not in plan["node_ids"]:
                failures.append(f"{vector_id}: missing node_id {node_id}")
        for node_id in expect.get("contains_structural_node_ids", []):
            if node_id not in plan["structural_node_ids"]:
                failures.append(f"{vector_id}: missing structural node_id {node_id}")

        for prefix in expect.get("blocker_prefixes", []):
            if not has_prefix(plan["blockers"], prefix):
                failures.append(f"{vector_id}: missing blocker prefix {prefix}; got {plan['blockers']}")
        for prefix in expect.get("warning_prefixes", []):
            if not has_prefix(plan["warnings"], prefix):
                failures.append(f"{vector_id}: missing warning prefix {prefix}; got {plan['warnings']}")

        if "vent_status" in expect:
            statuses = {item.get("status") for item in plan["ventilation"]}
            if expect["vent_status"] not in statuses:
                failures.append(f"{vector_id}: vent status {expect['vent_status']} not in {sorted(statuses)}")
        if "vent_height_mm" in expect:
            heights = {item.get("channel_height_mm") for item in plan["ventilation"]}
            if expect["vent_height_mm"] not in heights:
                failures.append(f"{vector_id}: vent height {expect['vent_height_mm']} not in {sorted(h for h in heights if h is not None)}")

    if failures:
        print("ROOF NODE ENGINE TESTS FAILED")
        for failure in failures:
            print(f"- {failure}")
        return 1

    print(f"OK: {len(vectors)} roof node engine vectors passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
