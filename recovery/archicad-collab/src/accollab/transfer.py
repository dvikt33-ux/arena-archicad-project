"""Перенос операций файлом (Фаза A-4, предшественник P2P).

Сценарий понедельника: машина A пишет ops.json → файл на машину B (флешка/Яндекс) →
машина B импортирует и применяет. Идемпотентно: повторный импорт — no-op.
Валидация строгая структурная: битая операция не попадает в журнал ни через
файл (весь конверт в карантин), ни через relay/Telegram (поштучный пропуск).
"""
import datetime
import json

from . import PROTOCOL_VERSION

_OP_JSON_FIELDS = ("before_json", "after_json", "deps_json", "base_vector")


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
    """Проверить чужую операцию ДО вставки. None — годна, иначе текст причины.

    Проверяется структура целиком (shape каждого поля + парсинг JSON-полей),
    а не только change_id: иначе битая строка роняет каждый тик применения.
    Неизвестные kind/op отклоняются (fail closed на входах)."""
    if not isinstance(op, dict):
        return "ne dict"
    cid = op.get("change_id")
    if not cid or not isinstance(cid, str):
        return "net change_id"
    if project_id is not None and op.get("project_id", "") not in ("", project_id):
        return "chuzhoy project_id"
    kind = op.get("kind", "primary")
    if kind not in ("primary", "lock", "unlock", "comment"):
        return "neizvestnyy kind"
    code = op.get("op", "")
    if kind == "primary" and code not in ("modify", "create", "delete"):
        return "neizvestnyy primary op"
    if kind in ("lock", "unlock") and code != kind:
        return "lock/unlock op ne sovpadaet s kind"
    if kind == "comment" and code not in ("comment.add", "comment.reply",
                                          "comment.resolve"):
        return "neizvestnyy comment op"
    if not op.get("author") or not isinstance(op.get("author"), str):
        return "net author"
    if not isinstance(op.get("element_guid", ""), str):
        return "element_guid ne stroka"
    if not isinstance(op.get("wall_time", ""), (str, int)):
        return "wall_time ne stroka/chislo"
    lamp = op.get("lamport", 0)
    if not isinstance(lamp, int) or isinstance(lamp, bool):
        return "lamport ne int"
    for key in _OP_JSON_FIELDS:
        val = op.get(key, "{}")
        if not isinstance(val, str):
            return "%s ne stroka" % key
        try:
            json.loads(val or "{}")
        except ValueError:
            return "%s bityy JSON" % key
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
