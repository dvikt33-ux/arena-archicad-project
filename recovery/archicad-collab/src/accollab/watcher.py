"""Watcher (Фаза A-2): снимки проекта, diff, запись операций в Store + outbox.

Логика polling (Tapir-only, без C++ Add-On):
1. take_snapshot(): GUID всех элементов + типы + детали (Tapir, батчами).
2. diff(): created / deleted / modified по изменению checksum деталей.
3. poll_and_record(): diff против прошлого снимка → операции modify/create/delete
   с before/after → Store + outbox.

Проверяемое предположение A-2.1: Tapir GetDetailsOfElements возвращает детали
в том же порядке, что запрошенные GUID (позиционное соответствие).
Живой тест №2 это подтверждает/опровергает (сверка ID БЛК-00x).
"""
import datetime
import json
import time
import uuid

from .store import element_checksum

DETAILS_BATCH = 200


def new_change_id():
    ms = int(time.time() * 1000)
    return f"{ms:013d}-{uuid.uuid4().hex[:12]}"


def new_tx_id():
    return uuid.uuid4().hex


def utcnow():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def diff_items(old, new):
    """old/new: {guid: {'type','checksum','details'}}."""
    created = [g for g in new if g not in old]
    deleted = [g for g in old if g not in new]
    modified = [g for g in new
                if g in old and new[g]["checksum"] != old[g]["checksum"]]
    return {"created": created, "deleted": deleted, "modified": modified}


class Watcher:
    def __init__(self, conn, store, project_id, author):
        self.conn = conn
        self.store = store
        self.project_id = project_id
        self.author = author

    def take_snapshot(self):
        guids = self.conn.get_all_guids()
        types = self.conn.get_types_of_elements(guids) if guids else {}
        details = {}
        for i in range(0, len(guids), DETAILS_BATCH):
            chunk = guids[i:i + DETAILS_BATCH]
            dets = self.conn.get_details(chunk)
            if len(dets) != len(chunk):
                raise RuntimeError(
                    f"details count {len(dets)} != requested {len(chunk)}"
                    " (нарушено предположение A-2.1?)")
            for g, d in zip(chunk, dets):
                details[g] = d
        items = {}
        for g in guids:
            d = details.get(g, {})
            items[g] = {"type": types.get(g, "?"),
                        "checksum": element_checksum(d),
                        "details": d}
        return {"taken_at": utcnow(), "count": len(items), "items": items}

    def poll_and_record(self):
        """Один цикл: снимок → diff → операции. Возвращает отчёт."""
        snap = self.take_snapshot()
        last = self.store.load_last_snapshot()
        report = {"taken_at": snap["taken_at"], "count": snap["count"],
                  "created": [], "deleted": [], "modified": [], "ops": []}
        if last is None:
            self.store.save_snapshot(snap["taken_at"], snap["count"],
                                     json.dumps(snap["items"], ensure_ascii=False))
            report["baseline"] = True
            return report  # первый прогон — только база, операций нет
        old = json.loads(last["data_json"])
        diff = diff_items(old, snap["items"])
        report.update({k: diff[k] for k in ("created", "deleted", "modified")})
        tx_id = new_tx_id()
        ops = []
        for g in diff["created"]:
            ops.append(self._make_op("create", g, None, snap["items"][g], tx_id))
        for g in diff["deleted"]:
            ops.append(self._make_op("delete", g, old[g], None, tx_id))
        for g in diff["modified"]:
            ops.append(self._make_op("modify", g, old[g], snap["items"][g], tx_id))
        with self.store.transaction():
            for op in ops:
                if not self.store.insert_operation(op):
                    continue
                if op["op"] in ("create", "delete"):
                    # История — да, рассылка — нет: applier их не умеет
                    # (UNSUPPORTED), соседям слать нечего. См. доки.
                    report["not_synced"] = report.get("not_synced", 0) + 1
                    continue
                self.store.enqueue_outbox(op["change_id"], op["wall_time"])
                report["ops"].append(op["change_id"])
            self.store.save_snapshot(snap["taken_at"], snap["count"],
                                     json.dumps(snap["items"], ensure_ascii=False))
        return report

    def _make_op(self, op, guid, before, after, tx_id):
        now = utcnow()
        item = after if after is not None else before
        return {
            "change_id": new_change_id(),
            "project_id": self.project_id,
            "element_guid": guid,
            "author": self.author,
            "wall_time": now,
            "lamport": int(time.time() * 1000),
            "base_vector": "{}",
            "seq": 0,
            "op": op,
            "before_json": json.dumps(before or {}, ensure_ascii=False),
            "after_json": json.dumps(after or {}, ensure_ascii=False),
            "tx_id": tx_id,
            "kind": "primary",
            "deps_json": "[]",
            "signature": "",
            "applied": 0,
            "_type": (item or {}).get("type", "?"),
        }
