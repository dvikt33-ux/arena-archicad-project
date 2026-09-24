"""Чекпоинты (Time Machine): именованный снимок + откат компенсирующими операциями.

Данные чекпоинта лежат в checkpoint_data и НЕ зависят от ротации обычных
снимков (раньше чекпоинт умирал через ~20 тиков — баг живого аудита).
Откат НЕ дёргает Ctrl+Z и НЕ переписывает историю: он строит обычные
modify-операции «вернуть как было», гонит их через штатный applier и
кладёт в outbox соседям. Что нельзя компенсировать (create/delete после
чекпоинта, изменения без координат) — честно попадает в skipped, проект
при этом не трогается. Только stdlib.
"""
import json
import time
import uuid

from . import watcher as _watcher
from .applier import apply_with_report, compute_move_vector


def create(store, items, name, author, description=""):
    """Сохранить чекпоинт текущего состояния items. Возвращает checkpoint_id."""
    cpid = "cp-%d-%s" % (int(time.time()), uuid.uuid4().hex[:8])
    store.save_checkpoint(cpid, name, author,
                          json.dumps({"count": len(items)}),
                          description=description)
    store.save_checkpoint_data(cpid, json.dumps(items, ensure_ascii=False))
    return cpid


def _target_items(store, checkpoint_id):
    cp = store.get_checkpoint(checkpoint_id)
    if cp is None:
        raise KeyError("чекпоинт %s не найден" % checkpoint_id)
    row = store.load_checkpoint_data(checkpoint_id)
    if row is not None:
        return json.loads(row["data_json"] or "{}")
    # Legacy (до схемы v3): ссылка на обычный снимок — мог погибнуть при ротации.
    vector = json.loads(cp["vector_json"] or "{}")
    snap = store.load_snapshot(vector.get("snapshot_id"))
    if snap is None:
        raise KeyError("снимок чекпоинта %s потерян (ротация?)" % checkpoint_id)
    return json.loads(snap["data_json"] or "{}")


def rollback_plan(store, checkpoint_id, current_items, author, project_id=None):
    """Построить план отката. Возвращает {'ops': [...], 'skipped': [...]}.
    project_id подписывает операции проектом (карантин чужих их пропустит)."""
    target = _target_items(store, checkpoint_id)
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
    """Применить план отката через штатный applier + разослать соседям.
    Без outbox соседи об откате не узнают (баг живого аудита)."""
    results = []
    for op in plan["ops"]:
        if store.insert_operation(op):
            store.enqueue_outbox(op["change_id"], op.get("wall_time", ""))
            results.append(apply_with_report(conn, store, op))
        else:
            results.append({"change_id": op["change_id"], "status": "SKIP-dubl"})
    return {"checkpoint_id": plan["checkpoint_id"], "tx_id": plan["tx_id"],
            "results": results, "skipped": plan["skipped"]}
