"""Чекпоинты (Time Machine): именованный снимок + откат компенсирующими операциями.

Откат НЕ дёргает Ctrl+Z и НЕ переписывает историю: он строит обычные
modify-операции «вернуть как было» и гонит их через штатный applier
(со всеми base check, локами и записью в журнал). Что нельзя компенсировать
(create/delete после чекпоинта, изменения без координат) — честно попадает
в skipped, проект при этом не трогается. Только stdlib.
"""
import json
import time
import uuid

from . import watcher as _watcher
from .applier import apply_with_report, compute_move_vector


def create(store, items, name, author, description=""):
    """Сохранить чекпоинт текущего состояния items. Возвращает checkpoint_id."""
    taken = _watcher.utcnow()
    sid = store.save_snapshot(taken, len(items), json.dumps(items, ensure_ascii=False))
    cpid = "cp-%d-%s" % (int(time.time()), uuid.uuid4().hex[:8])
    store.save_checkpoint(cpid, name, author,
                          json.dumps({"snapshot_id": sid, "count": len(items)}),
                          description=description)
    return cpid


def rollback_plan(store, checkpoint_id, current_items, author, project_id=None):
    """Построить план отката. Возвращает {'ops': [...], 'skipped': [...]}.
    project_id подписывает операции проектом (карантин чужих их пропустит)."""
    cp = store.get_checkpoint(checkpoint_id)
    if cp is None:
        raise KeyError("чекпоинт %s не найден" % checkpoint_id)
    vector = json.loads(cp["vector_json"] or "{}")
    snap = store.load_snapshot(vector.get("snapshot_id"))
    if snap is None:
        raise KeyError("снимок чекпоинта %s потерян (ротация?)" % checkpoint_id)
    target = json.loads(snap["data_json"] or "{}")
    tx_id = uuid.uuid4().hex
    ops, skipped = [], []
    for guid, cur in current_items.items():
        if guid not in target:
            skipped.append({"guid": guid, "reason": "created-after-checkpoint"})
            continue
        if cur.get("checksum") == target[guid].get("checksum"):
            continue
        op = {"change_id": _watcher.new_change_id(),
              "project_id": project_id or "",
              "element_guid": guid, "author": author,
              "wall_time": _watcher.utcnow(), "lamport": int(time.time() * 1000),
              "op": "modify", "kind": "primary",
              "before_json": json.dumps(cur, ensure_ascii=False),
              "after_json": json.dumps(target[guid], ensure_ascii=False),
              "tx_id": tx_id, "applied": 0,
              "_type": cur.get("type", "?")}
        if compute_move_vector(cur, target[guid]) is None:
            skipped.append({"guid": guid, "reason": "no-coords-vector"})
            continue
        ops.append(op)
    for guid in target:
        if guid not in current_items:
            skipped.append({"guid": guid, "reason": "deleted-after-checkpoint"})
    return {"checkpoint_id": checkpoint_id, "tx_id": tx_id, "ops": ops, "skipped": skipped}


def rollback_apply(conn, store, plan):
    """Применить план отката через штатный applier. Возвращает отчёт."""
    results = []
    for op in plan["ops"]:
        if store.insert_operation(op):
            results.append(apply_with_report(conn, store, op))
        else:
            results.append({"change_id": op["change_id"], "status": "SKIP-dubl"})
    return {"checkpoint_id": plan["checkpoint_id"], "tx_id": plan["tx_id"],
            "results": results, "skipped": plan["skipped"]}
