"""Applier (Фаза A-4+): применение операций из журнала через API.

Поддержано: op='modify' со сдвигом (вектор из дельты begCoordinate/zCoordinate),
kind=lock/unlock (через apply_with_report).
Безопасность:
- элемент обязан существовать (иначе MissingError, не применяем);
- base check: текущий checksum обязан совпасть с before (иначе BaseMismatchError);
- свежий hard-блок чужого holder'а запрещает применение (LockedError);
- неподдержанные op — UnsupportedOpError (статус UNSUPPORTED, в журнал не пишем).
- верим только явному success от MoveElements + перечитываем элемент (read-back);
  чексумма обязана совпасть с after (иначе ArchicadError, квитанции нет).
- повторная подача уже применённого (смерть между движением и квитанцией) —
  дописываем receipt, не конфликт.
После применения: квитанция + baseline элемента одним махом (без эха).
  (Живой тест 2026-09-18, фиксы Codex.)
apply_with_report: диспетчер без исключений + запись конфликтов в журнал.
"""
import json as _json

from . import locks as _locks
from . import comments as _comments
from .store import element_checksum
from .connector import ArchicadError


class ConflictError(Exception):
    pass


class MissingError(ConflictError):
    pass


class BaseMismatchError(ConflictError):
    pass


class LockedError(ConflictError):
    pass


class UnsupportedOpError(ConflictError):
    """Неподдержанный op — тоже Conflict: пишется в журнал и пропускается,
    а не роняет весь тик. Никогда не применяется автоматически."""


def _coords_inner(item):
    """Координатный словарь: работает и с сырой деталью Tapir
    ({"details": {...}}), и с обёрткой Watcher ({"details": {"details": {...}}})."""
    d = item.get("details") or {}
    if "begCoordinate" not in d and isinstance(d.get("details"), dict):
        d = d["details"]
    return d


def compute_move_vector(before_item, after_item):
    """Дельта координат балки. Возвращает {'x','y','z'} или None."""
    bd = _coords_inner(before_item)
    ad = _coords_inner(after_item)
    b = bd.get("begCoordinate") or {}
    a = ad.get("begCoordinate") or {}
    if not b or not a:
        return None
    return {"x": a.get("x", 0) - b.get("x", 0),
            "y": a.get("y", 0) - b.get("y", 0),
            "z": (ad.get("zCoordinate", 0) or 0) - (bd.get("zCoordinate", 0) or 0)}


def _conflict_code(exc):
    if isinstance(exc, MissingError):
        return "CONFLICT-missing"
    if isinstance(exc, BaseMismatchError):
        return "CONFLICT-base"
    if isinstance(exc, LockedError):
        return "CONFLICT-locked"
    return "CONFLICT"


def apply_operation(conn, store, op, force=False):
    """Применить одну primary/modify операцию. Возвращает отчёт. Бросает
    ConflictError (Missing/BaseMismatch/Locked/Unsupported — диспетчер
    пишет их в журнал конфликтов и идёт дальше).

    force=True — пропустить base check (осознанный выбор человека «взять чужое»
    после просмотра конфликта). Отсутствие элемента и чужой hard-блок
    проверяются всегда, даже с force."""
    op = dict(op)
    guid, kind = op["element_guid"], op["op"]
    if op.get("kind", "primary") != "primary" or kind != "modify":
        raise UnsupportedOpError(f"kind={op.get('kind')} op={kind} (здесь только primary/modify)")
    if _locks.is_hard_locked_by_other(store, guid, op.get("author", "")):
        raise LockedError(f"{guid[:8]}: элемент под hard-блоком другого участника")
    before = _json.loads(op["before_json"] or "{}")
    after = _json.loads(op["after_json"] or "{}")
    current = conn.get_details([guid])
    if not current:
        raise MissingError(f"{guid[:8]}: элемента нет в проекте")
    current_checksum = element_checksum(current[0])
    # Процесс мог умереть после того, как Archicad сдвинул, но до записи
    # квитанции. Успешное движение конфликтом не считаем — дописываем receipt.
    if current_checksum == after.get("checksum"):
        store.complete_application(op["change_id"], guid, before, after)
        return {"change_id": op["change_id"], "vector": compute_move_vector(before, after),
                "already_applied": True}
    if not force and current_checksum != before.get("checksum"):
        raise BaseMismatchError(f"{guid[:8]}: base не совпал (элемент уже меняли)")
    vec = compute_move_vector(before, after)
    if vec is None or (vec["x"] == 0 and vec["y"] == 0 and vec["z"] == 0):
        raise UnsupportedOpError("modify без сдвига координат")
    resp = conn.tapir("MoveElements", {"elementsWithMoveVectors": [
        {"elementId": {"guid": guid}, "moveVector": vec, "copy": False}]})
    # Верим только явному подтверждению (живой Tapir шлёт success в одной
    # из двух форм — принимаем обе).
    results = resp.get("executionResults") if isinstance(resp, dict) else None
    if results is None:
        success = isinstance(resp, dict) and resp.get("success") is True
    else:
        success = (isinstance(results, list) and len(results) == 1 and
                   isinstance(results[0], dict) and results[0].get("success") is True)
    if not success:
        raise ArchicadError(-1, "MoveElements did not acknowledge success",
                            "TapirCommand.MoveElements")
    actual = conn.get_details([guid])
    if len(actual) != 1:
        raise ArchicadError(-1, "MoveElements result unreadable",
                            "TapirCommand.MoveElements")
    if force:
        # «Взять чужое»: дельта применена к НАШЕМУ состоянию (дельты
        # компонуются, чужая правка нашу не затирает). Приземлились не в
        # заявленный after — квитанция и baseline честно фиксируют ФАКТ.
        live = actual[0]
        live_item = {"type": live.get("type", after.get("type", "?")),
                     "checksum": element_checksum(live), "details": live}
        store.complete_application(op["change_id"], guid, before, live_item)
        return {"change_id": op["change_id"], "vector": vec, "tapir": resp,
                "forced": True}
    if element_checksum(actual[0]) != after.get("checksum"):
        raise ArchicadError(-1, "MoveElements result differs from requested state",
                            "TapirCommand.MoveElements")
    # Квитанция + baseline одним махом: следующий тик вотчера не примет
    # чужое движение за локальное (эхо убито).
    store.complete_application(op["change_id"], guid, before, after)
    return {"change_id": op["change_id"], "vector": vec, "tapir": resp}


def apply_with_report(conn, store, op, holder="local"):
    """Диспетчер: lock/unlock/primary без исключений. Конфликты пишутся в журнал."""
    op = dict(op)
    cid = op.get("change_id", "?")
    if op.get("kind") == "comment":
        try:
            store.insert_operation(op)
        except KeyError:
            pass
        st = _comments.apply_remote(store, op)
        try:
            store.mark_applied(cid)
        except Exception:  # noqa: BLE001
            pass
        return {"change_id": cid, "status": st}
    if op.get("kind") in ("lock", "unlock"):
        try:
            store.insert_operation(op)
        except KeyError:
            pass
        st = _locks.apply_remote(store, op)
        try:
            store.mark_applied(cid)
        except Exception:  # noqa: BLE001 - нет строки (битый change_id) — отчёт всё равно
            pass
        return {"change_id": cid, "status": st}
    try:
        rep = apply_operation(conn, store, op)
        return {"change_id": cid, "status": "APPLIED", "vector": rep["vector"]}
    except UnsupportedOpError as e:
        # Не умею (create/delete/без сдвига): честный статус без строки
        # в журнале — человеку решать нечего, спамить конфликтом не надо.
        # Первым: UnsupportedOpError — наследник ConflictError.
        return {"change_id": cid, "status": "UNSUPPORTED", "note": str(e)[:200]}
    except ConflictError as e:
        ours = store.last_op_for_element(op.get("element_guid", ""))
        code = _conflict_code(e)
        store.record_conflict(op.get("element_guid", ""),
                              ours["change_id"] if ours else "(net)",
                              cid, note="code:%s" % code)
        return {"change_id": cid, "status": code, "note": str(e)[:200]}
    except UnsupportedOpError as e:
        return {"change_id": cid, "status": "UNSUPPORTED", "note": str(e)[:200]}
