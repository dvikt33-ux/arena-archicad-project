#!/usr/bin/env python3
"""Safe Archicad JSON/Python backend for Arena Bridge v2.

The bridge passes only a fixed action name. No source code, shell command, file
path, module name or arbitrary Archicad command is accepted from the task.

Exit codes:
  0  success
  2  unsupported action / bad CLI
  10 official `archicad` package missing
  11 no running Archicad instance / connection failed
  12 Archicad command failed
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Dict, List

ALLOWED_ACTIONS = {
    "ping",
    "product_info",
    "selection",
    "wall_count",
}


def emit(action: str, ok: bool, **payload: Any) -> None:
    body: Dict[str, Any] = {
        "protocol": 1,
        "backend": "archicad-python-json",
        "action": action,
        "ok": bool(ok),
    }
    body.update(payload)
    print(json.dumps(body, ensure_ascii=False, separators=(",", ":")))


def guid_of(element: Any) -> str:
    try:
        return str(element.elementId.guid)
    except Exception:
        return ""


def connect(action: str):
    try:
        from archicad import ACConnection
    except Exception as exc:
        emit(action, False, error="archicad-package-missing", detail=type(exc).__name__)
        raise SystemExit(10)

    try:
        conn = ACConnection.connect()
    except Exception as exc:
        emit(action, False, error="archicad-connect-failed", detail=type(exc).__name__)
        raise SystemExit(11)

    if conn is None:
        emit(action, False, error="archicad-not-running")
        raise SystemExit(11)

    return conn


def run_ping(acc: Any) -> Dict[str, Any]:
    return {"alive": bool(acc.IsAlive())}


def run_product_info(acc: Any) -> Dict[str, Any]:
    version, build, language = acc.GetProductInfo()
    return {
        "version": int(version),
        "build": int(build),
        "language": str(language),
    }


def run_selection(acc: Any) -> Dict[str, Any]:
    elements = acc.GetSelectedElements(
        onlyEditable=False,
        onlySupportedTypes=True,
    )
    type_results = acc.GetTypesOfElements(elements) if elements else []

    items: List[Dict[str, Any]] = []
    for index, element in enumerate(elements):
        item: Dict[str, Any] = {"guid": guid_of(element)}
        if index < len(type_results):
            type_result = type_results[index]
            typed = getattr(type_result, "typeOfElement", None)
            error = getattr(type_result, "error", None)
            if typed is not None:
                item["type"] = str(typed.elementType)
            elif error is not None:
                item["type_error"] = True
        items.append(item)

    return {
        "count": len(items),
        "elements": items,
    }


def run_wall_count(acc: Any) -> Dict[str, Any]:
    walls = acc.GetElementsByType("Wall")
    return {"count": len(walls)}


def main() -> int:
    parser = argparse.ArgumentParser(add_help=True)
    parser.add_argument("--action", required=True)
    args = parser.parse_args()

    action = args.action.strip().lower()
    if action not in ALLOWED_ACTIONS:
        emit(action, False, error="action-not-allowed")
        return 2

    conn = connect(action)
    acc = conn.commands

    runners = {
        "ping": run_ping,
        "product_info": run_product_info,
        "selection": run_selection,
        "wall_count": run_wall_count,
    }

    try:
        result = runners[action](acc)
        emit(action, True, result=result)
        return 0
    except Exception as exc:
        # Do not expose arbitrary exception strings through the bridge; they can
        # contain local paths or project data. The exception class is enough for
        # diagnostics, while the full traceback remains a local debugging task.
        emit(action, False, error="archicad-command-failed", detail=type(exc).__name__)
        return 12


if __name__ == "__main__":
    sys.exit(main())
