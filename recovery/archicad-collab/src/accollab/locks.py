"""Блокировки элементов: soft (предупреждение) / hard (запрет применения чужих опов).

Аренда с heartbeat: holder обязан продлевать (heartbeat), иначе блок
протухает через expires_in_s и любой может перехватить элемент.
Один элемент — один holder. Распространение — операциями kind=lock/unlock.
Только stdlib.
"""
import datetime
import time
import uuid

DEFAULT_TTL_S = 20
_TTL_MIN_S = 1
_TTL_MAX_S = 86400


def utcnow():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _parse(ts):
    try:
        return datetime.datetime.fromisoformat(ts)
    except (ValueError, TypeError):
        return datetime.datetime.fromtimestamp(0, tz=datetime.timezone.utc)


def _expired(row, now):
    hb = _parse(row["heartbeat"])
    try:
        return (now - hb).total_seconds() > row["expires_in_s"]
    except TypeError:
        return True  # битая строка (ttl не число) — протухла, sweep/get снесут


def sweep(store, now=None):
    """Удалить протухшие блоки. Возвращает число удалённых."""
    now = now or datetime.datetime.now(datetime.timezone.utc)
    n = 0
    for row in store.db.execute("SELECT * FROM locks"):
        if _expired(row, now):
            store.db.execute("DELETE FROM locks WHERE element_guid=?",
                             (row["element_guid"],))
            n += 1
    if n:
        store._commit()
    return n


def get(store, guid, now=None):
    now = now or datetime.datetime.now(datetime.timezone.utc)
    row = store.db.execute("SELECT * FROM locks WHERE element_guid=?", (guid,)).fetchone()
    if row is None:
        return None
    if _expired(row, now):
        store.db.execute("DELETE FROM locks WHERE element_guid=?", (guid,))
        store._commit()
        return None
    return row


def acquire(store, guid, holder, mode="soft", ttl_s=DEFAULT_TTL_S, now=None):
    """Занять элемент. Возвращает lease_id или None (занято другим)."""
    if mode not in ("soft", "hard"):
        raise ValueError("mode должен быть soft/hard")
    if (not isinstance(ttl_s, (int, float)) or isinstance(ttl_s, bool)
            or not _TTL_MIN_S <= ttl_s <= _TTL_MAX_S):
        raise ValueError("ttl_s должен быть числом %d..%d" % (_TTL_MIN_S, _TTL_MAX_S))
    now = now or datetime.datetime.now(datetime.timezone.utc)
    cur = get(store, guid, now)
    if cur is not None and cur["holder"] != holder:
        return None  # занято другим (soft и hard одинаково держат слот)
    lease_id = "%s-%s" % (holder, uuid.uuid4().hex[:8])
    store.db.execute(
        "INSERT OR REPLACE INTO locks(element_guid,holder,lease_id,since,heartbeat,"
        " expires_in_s,mode) VALUES(?,?,?,?,?,?,?)",
        (guid, holder, lease_id, now.isoformat(), now.isoformat(), ttl_s, mode))
    store._commit()
    return lease_id


def heartbeat(store, guid, lease_id, now=None):
    """Продлить аренду. True — продлена, False — нет такой/чужая/протухла."""
    now = now or datetime.datetime.now(datetime.timezone.utc)
    row = store.db.execute("SELECT * FROM locks WHERE element_guid=?", (guid,)).fetchone()
    if row is None or row["lease_id"] != lease_id:
        return False
    if _expired(row, now):
        store.db.execute("DELETE FROM locks WHERE element_guid=?", (guid,))
        store._commit()
        return False
    store.db.execute("UPDATE locks SET heartbeat=? WHERE element_guid=?",
                     (now.isoformat(), guid))
    store._commit()
    return True


def release(store, guid, lease_id):
    """Снять блок. True — снят, False — нет такой/чужой lease."""
    row = store.db.execute("SELECT * FROM locks WHERE element_guid=?", (guid,)).fetchone()
    if row is None or row["lease_id"] != lease_id:
        return False
    store.db.execute("DELETE FROM locks WHERE element_guid=?", (guid,))
    store._commit()
    return True


def is_hard_locked_by_other(store, guid, holder, now=None):
    """True — свежий hard-блок чужого holder'а (применение чужих опов запрещено)."""
    row = get(store, guid, now)
    return row is not None and row["mode"] == "hard" and row["holder"] != holder


def list_locks(store, now=None):
    sweep(store, now)
    return list(store.db.execute("SELECT * FROM locks ORDER BY since"))


# ---- распространение операциями ----

def _base_op(kind, guid, author, payload):
    ms = int(time.time() * 1000)
    import json as _json
    return {"change_id": "%013d-%s" % (ms, uuid.uuid4().hex[:12]),
            "element_guid": guid, "author": author, "wall_time": utcnow(),
            "lamport": ms, "op": kind, "kind": kind,
            "before_json": "{}",
            "after_json": _json.dumps(payload, ensure_ascii=False),
            "tx_id": uuid.uuid4().hex, "applied": 0}


def make_lock_op(guid, holder, mode="soft", ttl_s=DEFAULT_TTL_S, lease_id=""):
    return _base_op("lock", guid, holder,
                    {"mode": mode, "ttl_s": ttl_s, "lease_id": lease_id or holder})


def make_unlock_op(guid, holder, lease_id=""):
    return _base_op("unlock", guid, holder, {"lease_id": lease_id or holder})


def apply_remote(store, op, now=None):
    """Применить чужую lock/unlock операцию. Возвращает статус-строку.

    Правила против старых/битых сообщений: unlock требует совпадения lease,
    lock того же holder с другим lease считается stale (не перезаписывает),
    ttl/mode валилируются до записи (битые не травят таблицу).
    """
    import json as _json
    now = now or datetime.datetime.now(datetime.timezone.utc)
    kind, guid = op.get("kind"), op.get("element_guid")
    try:
        payload = _json.loads(op.get("after_json") or "{}")
    except ValueError:
        return "SKIP-lock-badjson"
    if not isinstance(payload, dict):
        return "SKIP-lock-badjson"
    lease = payload.get("lease_id", "")
    if kind == "unlock":
        row = store.db.execute("SELECT * FROM locks WHERE element_guid=?",
                               (guid,)).fetchone()
        if (row is not None and row["holder"] == op.get("author")
                and isinstance(lease, str) and lease
                and row["lease_id"] == lease):
            store.db.execute("DELETE FROM locks WHERE element_guid=?", (guid,))
            store._commit()
            return "UNLOCKED"
        return "SKIP-unlock-chuzhoy"
    if kind == "lock":
        mode = payload.get("mode", "soft")
        ttl = payload.get("ttl_s", DEFAULT_TTL_S)
        if (not guid or not isinstance(lease, str) or not lease
                or mode not in ("soft", "hard")
                or not isinstance(ttl, (int, float)) or isinstance(ttl, bool)
                or not _TTL_MIN_S <= ttl <= _TTL_MAX_S):
            return "SKIP-lock-badpayload"
        cur = get(store, guid, now)
        if cur is not None:
            if cur["holder"] != op.get("author"):
                return "SKIP-lock-zanyato"
            if cur["lease_id"] != lease:
                return "SKIP-lock-stale"
        store.db.execute(
            "INSERT OR REPLACE INTO locks(element_guid,holder,lease_id,since,heartbeat,"
            " expires_in_s,mode) VALUES(?,?,?,?,?,?,?)",
            (guid, op.get("author"), lease,
             op.get("wall_time", now.isoformat()), now.isoformat(), ttl, mode))
        store._commit()
        return "LOCKED"
    return "SKIP-ne-lock"
