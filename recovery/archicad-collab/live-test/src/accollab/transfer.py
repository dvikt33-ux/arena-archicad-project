"""Перенос операций файлом (Фаза A-4, предшественник P2P).

Сценарий понедельника: машина A пишет ops.json → файл на машину B (флешка/Яндекс) →
машина B импортирует и применяет. Идемпотентно: повторный импорт — no-op.
Чужой проект отклоняется (карантин), битые операции — тоже, до вставки.
"""
import datetime

from . import PROTOCOL_VERSION


def export_envelope(store, project_id, author, change_ids=None):
    if change_ids is None:
        change_ids = store.list_outbox()
    ops = []
    for cid in change_ids:
        row = store.get_operation(cid)
        if row is not None:
            ops.append(dict(row))
    return {"protocol": PROTOCOL_VERSION,
            "project_id": project_id,
            "from": author,
            "exported_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "ops": ops}


def validate_op(op, project_id=None):
    """Проверить чужую операцию ДО вставки. None — годна, иначе текст причины."""
    if not isinstance(op, dict):
        return "ne dict"
    if not op.get("change_id"):
        return "net change_id"
    if project_id is not None and op.get("project_id", "") not in ("", project_id):
        return "chuzhoy project_id"
    return None


def import_envelope(store, env, project_id=None):
    """Возвращает число НОВЫХ операций (дубли пропускаются).
    project_id задан — конверт чужого проекта отклоняется целиком (ValueError),
    битая операция внутри — тоже (ничего не вставляется)."""
    if not isinstance(env, dict):
        raise ValueError("envelope ne dict")
    if env.get("protocol") != PROTOCOL_VERSION:
        raise ValueError(f"protocol {env.get('protocol')} != {PROTOCOL_VERSION}")
    if project_id is not None and env.get("project_id", "") not in ("", project_id):
        raise ValueError("envelope project %r chuzhoy (nash %r)"
                         % (env.get("project_id"), project_id))
    ops = env.get("ops", [])
    for op in ops:
        bad = validate_op(op, project_id)
        if bad is not None:
            raise ValueError("bitaya operatsiya: %s" % bad)
    fresh = 0
    for op in ops:
        if store.insert_operation(op):
            fresh += 1
    return fresh
