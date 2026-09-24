"""BIM-контроль: советы по снимку модели. Только stdlib.

Проверки СОВЕТУЮТ, а не блокируют: синхронизация идёт всегда,
отчёт показывает, что поправить. v1: дубли ID и пустые ID
(классика бардака в «тропе»). Расширяется добавлением функций check_*.
"""
from .watcher import Watcher


def _el_id(item):
    d = (item or {}).get("details") or {}
    return d.get("id", "")


def _inner(item):
    """Внутренний details: держит и сырую деталь Tapir, и обёртку Watcher."""
    d = (item or {}).get("details") or {}
    if "buildingMaterialId" not in d and isinstance(d.get("details"), dict):
        d = d["details"]
    return d


def check_missing_material(items):
    """Нет buildingMaterialId (поле подтверждено живым diag v2).
    Возвращает issues [{code,guid}]."""
    return [{"code": "NO_MATERIAL", "guid": guid[:8]}
            for guid, item in sorted((items or {}).items())
            if "buildingMaterialId" not in _inner(item)]


def check_duplicate_ids(items):
    """Одинаковый ID у разных GUID. Возвращает issues [{code,id,guids}]."""
    seen = {}
    for guid, item in (items or {}).items():
        el_id = _el_id(item)
        if el_id:
            seen.setdefault(el_id, []).append(guid)
    return [{"code": "DUP_ID", "id": el_id, "guids": [g[:8] for g in guids]}
            for el_id, guids in sorted(seen.items()) if len(guids) > 1]


def check_empty_ids(items):
    """Пустые ID. Возвращает issues [{code,guid}]."""
    return [{"code": "EMPTY_ID", "guid": guid[:8]}
            for guid, item in sorted((items or {}).items()) if not _el_id(item)]


def run_all(items, rules="all"):
    """rules: 'all' или коды через запятую ('DUP_ID,NO_MATERIAL')."""
    want = None
    if rules not in (None, "", "all"):
        want = {c.strip().upper() for c in str(rules).split(",") if c.strip()}
    issues = (check_duplicate_ids(items) + check_empty_ids(items)
              + check_missing_material(items))
    if want is not None:
        issues = [i for i in issues if i["code"] in want]
    counts = {}
    for i in issues:
        counts[i["code"]] = counts.get(i["code"], 0) + 1
    return {"issues": issues, "counts": counts}


def check_live(conn, store, project_id, author, rules="all"):
    """Снять снимок и прогнать проверки. Возвращает (count, report)."""
    snap = Watcher(conn, store, project_id, author).take_snapshot()
    return snap["count"], run_all(snap["items"], rules)
