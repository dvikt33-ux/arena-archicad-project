"""SQLite-хранилище демона: схема, миграции, базовые операции. Только stdlib."""
import hashlib
import json
import os
import sqlite3
import time
import uuid

SCHEMA_PATH = os.path.join(os.path.dirname(__file__), "store_schema.sql")
SCHEMA_VERSION = 3


def canonical(obj):
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_text(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def element_checksum(details):
    return sha256_text(canonical(details))


def utcnow():
    import datetime
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


class Store:
    def __init__(self, path):
        self.path = path
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        # check_same_thread=False: страницу статуса обслуживает другой поток.
        # timeout=30: фоновый /sync идёт своим соединением, SQLite сериализует
        # писателей файловыми блокировками. Одно соединение — один поток.
        self.db = sqlite3.connect(path, check_same_thread=False, timeout=30)
        self.db.row_factory = sqlite3.Row
        self._tx_depth = 0
        self._migrate()

    def _migrate(self):
        with open(SCHEMA_PATH, encoding="utf-8") as f:
            self.db.executescript(f.read())
        row = self.db.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
        ver = int(row["value"]) if row else 0
        if ver < 2:
            cols = [r[1] for r in self.db.execute("PRAGMA table_info(locks)")]
            if "mode" not in cols:
                self.db.execute("ALTER TABLE locks ADD COLUMN mode TEXT NOT NULL DEFAULT 'soft'")
            ver = 2
        if ver < 3:
            # Durable чекпоинты: данные отдельно от ротируемых снимков.
            self.db.execute("CREATE TABLE IF NOT EXISTS checkpoint_data("
                            "checkpoint_id TEXT PRIMARY KEY,"
                            " data_json TEXT NOT NULL DEFAULT '{}')")
            for cp in self.db.execute("SELECT checkpoint_id, vector_json FROM checkpoints"):
                try:
                    sid = json.loads(cp["vector_json"] or "{}").get("snapshot_id")
                except ValueError:
                    continue
                if sid is None:
                    continue
                snap = self.db.execute("SELECT data_json FROM snapshots WHERE id=?",
                                       (sid,)).fetchone()
                if snap is not None:
                    self.db.execute("INSERT OR IGNORE INTO checkpoint_data(checkpoint_id,data_json)"
                                    " VALUES(?,?)", (cp["checkpoint_id"], snap["data_json"]))
            ver = 3
        self.db.execute("INSERT OR REPLACE INTO meta(key,value) VALUES('schema_version',?)",
                        (str(max(ver, SCHEMA_VERSION)),))
        self._commit()

    def _commit(self):
        """Коммит, если не внутри transaction() (иначе коммитит она)."""
        if self._tx_depth == 0:
            self.db.commit()

    def transaction(self):
        """Настоящая групповая запись: внутренние _commit() молчат, в конце
        один commit, при исключении — rollback всего. Вложенные транзакции:
        внутренняя ошибка откатывает всё и всплывает наружу."""
        from contextlib import contextmanager as _cm

        @_cm
        def _tx():
            self._tx_depth += 1
            try:
                yield self.db
            except Exception:
                self._tx_depth -= 1
                if self._tx_depth == 0:
                    self.db.rollback()
                raise
            else:
                self._tx_depth -= 1
                if self._tx_depth == 0:
                    self.db.commit()
        return _tx()

    # ---- elements_cache ----
    def upsert_element(self, guid, etype, checksum, last_change_id="", updated_at=""):
        self.db.execute(
            "INSERT INTO elements_cache(guid,type,checksum,last_change_id,updated_at)"
            " VALUES(?,?,?,?,?)"
            " ON CONFLICT(guid) DO UPDATE SET type=excluded.type, checksum=excluded.checksum,"
            " last_change_id=excluded.last_change_id, updated_at=excluded.updated_at",
            (guid, etype, checksum, last_change_id, updated_at))
        self._commit()

    def get_element(self, guid):
        return self.db.execute("SELECT * FROM elements_cache WHERE guid=?", (guid,)).fetchone()

    def element_count(self):
        return self.db.execute("SELECT COUNT(*) c FROM elements_cache").fetchone()["c"]

    # ---- operations (идемпотентно по change_id) ----
    def insert_operation(self, op):
        """Вставка операции; повторная вставка того же change_id — no-op (True/False)."""
        try:
            self.db.execute(
                "INSERT INTO operations(change_id,project_id,element_guid,author,wall_time,"
                " lamport,base_vector,seq,op,before_json,after_json,tx_id,kind,deps_json,"
                " signature,applied) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (op["change_id"], op.get("project_id", ""), op.get("element_guid", ""),
                 op.get("author", ""), op.get("wall_time", ""), op.get("lamport", 0),
                 op.get("base_vector", "{}"), op.get("seq", 0), op.get("op", ""),
                 op.get("before_json", "{}"), op.get("after_json", "{}"),
                 op.get("tx_id", ""), op.get("kind", "primary"),
                 op.get("deps_json", "[]"), op.get("signature", ""),
                 op.get("applied", 0)))
            self._commit()
            return True
        except sqlite3.IntegrityError as e:
            if "UNIQUE" not in str(e).upper():
                raise  # не дубль, а битая строка — не прячем
            return False  # дубль — идемпотентность

    def get_operation(self, change_id):
        return self.db.execute("SELECT * FROM operations WHERE change_id=?",
                               (change_id,)).fetchone()

    def last_op_for_element(self, guid, author=None):
        q = "SELECT * FROM operations WHERE element_guid=? AND kind='primary'"
        args = [guid]
        if author is not None:
            q += " AND author=?"
            args.append(author)
        q += " ORDER BY rowid DESC LIMIT 1"
        return self.db.execute(q, args).fetchone()

    def ops_for_element(self, guid, limit=50):
        return list(self.db.execute(
            "SELECT * FROM operations WHERE element_guid=? ORDER BY rowid DESC LIMIT ?",
            (guid, limit)))

    # ---- outbox ----
    def enqueue_outbox(self, change_id, enqueued_at=""):
        self.db.execute("INSERT OR IGNORE INTO outbox(change_id,enqueued_at)"
                        " VALUES(?,?)", (change_id, enqueued_at or utcnow()))
        self._commit()

    def list_outbox(self):
        return [r["change_id"] for r in
                self.db.execute("SELECT change_id FROM outbox ORDER BY enqueued_at")]

    def dequeue_outbox(self, change_ids):
        if not change_ids:
            return 0
        cur = self.db.execute(
            "DELETE FROM outbox WHERE change_id IN (%s)" % ",".join("?" * len(change_ids)),
            list(change_ids))
        self._commit()
        return cur.rowcount

    def mark_applied(self, change_id):
        self.db.execute("UPDATE operations SET applied=1 WHERE change_id=?",
                        (change_id,))
        self._commit()

    def complete_application(self, change_id, guid, before, after):
        """Отметить входящую операцию применённой + подтянуть baseline элемента.

        Без этого следующий тик вотчера принимает чужое движение за локальную
        правку и экспортирует её обратно (эхо). Baseline двигаем только если он
        ещё равен заявленному before — незамеченную локальную правку не трём.
        Всё атомарно: либо квитанция + baseline, либо ничего.
        (Живой тест 2026-09-18, фикс Codex.)"""
        with self.transaction():
            last = self.load_last_snapshot()
            if last is not None:
                items = json.loads(last["data_json"])
                if items.get(guid, {}).get("checksum") == before.get("checksum"):
                    items[guid] = after
                    self.db.execute("UPDATE snapshots SET data_json=? WHERE id=?",
                                    (json.dumps(items, ensure_ascii=False), last["id"]))
            self.db.execute("UPDATE operations SET applied=1 WHERE change_id=?", (change_id,))

    # ---- snapshots ----
    def save_snapshot(self, taken_at, count, data_json, keep=20):
        cur = self.db.execute(
            "INSERT INTO snapshots(taken_at,count,data_json) VALUES(?,?,?)",
            (taken_at, count, data_json))
        self.db.execute(
            "DELETE FROM snapshots WHERE id NOT IN"
            " (SELECT id FROM snapshots ORDER BY id DESC LIMIT ?)", (keep,))
        self._commit()
        return cur.lastrowid

    def load_last_snapshot(self):
        return self.db.execute(
            "SELECT * FROM snapshots ORDER BY id DESC LIMIT 1").fetchone()

    def load_snapshot(self, snap_id):
        return self.db.execute("SELECT * FROM snapshots WHERE id=?", (snap_id,)).fetchone()

    # ---- checkpoint_data (ротация снимков не трогает) ----
    def save_checkpoint_data(self, checkpoint_id, data_json):
        self.db.execute("INSERT OR REPLACE INTO checkpoint_data(checkpoint_id,data_json)"
                        " VALUES(?,?)", (checkpoint_id, data_json))
        self._commit()

    def load_checkpoint_data(self, checkpoint_id):
        return self.db.execute("SELECT * FROM checkpoint_data WHERE checkpoint_id=?",
                               (checkpoint_id,)).fetchone()

    # ---- conflicts ----
    def record_conflict(self, element_guid, ours_change, theirs_change, note=""):
        cid = "%013d-%s" % (int(time.time() * 1000), uuid.uuid4().hex[:12])
        self.db.execute(
            "INSERT INTO conflicts(conflict_id,element_guid,ours_change,theirs_change,"
            " detected_at,status,resolution) VALUES(?,?,?,?,?,'open',?)",
            (cid, element_guid, ours_change, theirs_change, utcnow(), note))
        self._commit()
        return cid

    def list_conflicts(self, status=None):
        q = "SELECT * FROM conflicts"
        args = []
        if status is not None:
            q += " WHERE status=?"
            args.append(status)
        q += " ORDER BY detected_at"
        return list(self.db.execute(q, args))

    def resolve_conflict(self, conflict_id, resolution):
        cur = self.db.execute(
            "UPDATE conflicts SET status='resolved', resolution=? WHERE conflict_id=?",
            (resolution, conflict_id))
        self._commit()
        return cur.rowcount

    # ---- checkpoints ----
    def save_checkpoint(self, checkpoint_id, name, author, vector_json,
                        oplog_offset=0, pln_backup="", description=""):
        self.db.execute(
            "INSERT OR REPLACE INTO checkpoints(checkpoint_id,name,author,created_at,"
            " vector_json,oplog_offset,pln_backup,description)"
            " VALUES(?,?,?,?,?,?,?,?)",
            (checkpoint_id, name, author, utcnow(), vector_json, oplog_offset,
             pln_backup, description))
        self._commit()

    def get_checkpoint(self, checkpoint_id):
        return self.db.execute("SELECT * FROM checkpoints WHERE checkpoint_id=?",
                               (checkpoint_id,)).fetchone()

    def list_checkpoints(self):
        return list(self.db.execute("SELECT * FROM checkpoints ORDER BY created_at"))

    # ---- sync_state ----
    def get_sync_state(self, peer):
        return self.db.execute("SELECT * FROM sync_state WHERE peer=?", (peer,)).fetchone()

    def update_sync_state(self, peer, **kw):
        row = self.get_sync_state(peer)
        if row is None:
            self.db.execute(
                "INSERT INTO sync_state(peer,last_vector,pending_out,pending_in,"
                " last_sync,errors_json) VALUES(?,'{}',0,0,'','[]')", (peer,))
        sets = ", ".join("%s=?" % k for k in kw)
        if sets:
            self.db.execute("UPDATE sync_state SET %s WHERE peer=?" % sets,
                            (list(kw.values()) + [peer]))
        self._commit()

    def close(self):
        self.db.close()
