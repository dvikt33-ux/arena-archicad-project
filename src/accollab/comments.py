"""Комментарии к элементам: добавление, ответы, закрытие, рассылка команде.

Хранение — таблица comments. Синхронизация — операциями kind=comment
(op: comment.add / comment.reply / comment.resolve) через общий транспорт;
применение — comments.apply_remote (идемпотентно). Только stdlib.
"""
import json
import time
import uuid

KIND = "comment"


def _now_ms():
    return int(time.time() * 1000)


def new_comment_id():
    return "cm-%d-%s" % (_now_ms(), uuid.uuid4().hex[:6])


def _base_op(op, guid, author, payload):
    ms = _now_ms()
    return {"change_id": "%013d-%s" % (ms, uuid.uuid4().hex[:12]),
            "element_guid": guid, "author": author, "wall_time": ms,
            "lamport": ms, "op": op, "kind": KIND,
            "before_json": "{}",
            "after_json": json.dumps(payload, ensure_ascii=False),
            "tx_id": uuid.uuid4().hex, "applied": 0}


def add_local(store, element_guid, author, text, mentions=()):
    """Создать комментарий локально. Возвращает (comment_id, op для рассылки)."""
    if not (text or "").strip():
        raise ValueError("pustoy kommentariy")
    cid = new_comment_id()
    payload = {"comment_id": cid, "element_guid": element_guid, "author": author,
               "created_at": _now_ms(), "text": text.strip(),
               "mentions": list(mentions or []), "status": "open", "replies": []}
    store.db.execute(
        "INSERT INTO comments(comment_id,target_json,author,created_at,text,status,"
        " replies_json,mentions_json) VALUES(?,?,?,?,?,?,?,?)",
        (cid, json.dumps({"element_guid": element_guid}, ensure_ascii=False),
         author, str(payload["created_at"]), payload["text"], "open", "[]",
         json.dumps(payload["mentions"], ensure_ascii=False)))
    store.db.commit()
    return cid, _base_op("comment.add", element_guid, author, payload)


def reply_local(store, comment_id, author, text):
    """Ответить локально. Возвращает op для рассылки."""
    row = get(store, comment_id)
    if row is None:
        raise KeyError("kommentariy %s ne nayden" % comment_id)
    if not (text or "").strip():
        raise ValueError("pustoy otvet")
    reply = {"author": author, "created_at": _now_ms(), "text": text.strip()}
    replies = json.loads(row["replies_json"] or "[]") + [reply]
    store.db.execute("UPDATE comments SET replies_json=? WHERE comment_id=?",
                     (json.dumps(replies, ensure_ascii=False), comment_id))
    store.db.commit()
    target = json.loads(row["target_json"] or "{}")
    return _base_op("comment.reply", target.get("element_guid", ""), author,
                    {"comment_id": comment_id, "reply": reply})


def resolve_local(store, comment_id, author):
    """Закрыть локально. Возвращает op для рассылки."""
    row = get(store, comment_id)
    if row is None:
        raise KeyError("kommentariy %s ne nayden" % comment_id)
    store.db.execute("UPDATE comments SET status='resolved' WHERE comment_id=?",
                     (comment_id,))
    store.db.commit()
    target = json.loads(row["target_json"] or "{}")
    return _base_op("comment.resolve", target.get("element_guid", ""), author,
                    {"comment_id": comment_id})


def apply_remote(store, op):
    """Применить чужую comment-операцию. Возвращает статус-строку."""
    kind_op = op.get("op", "")
    try:
        payload = json.loads(op.get("after_json") or "{}")
    except ValueError:
        return "SKIP-comment-badjson"
    cid = payload.get("comment_id", "")
    if not cid:
        return "SKIP-comment-noid"
    if kind_op == "comment.add":
        cur = store.db.execute("SELECT comment_id FROM comments WHERE comment_id=?",
                               (cid,)).fetchone()
        if cur is not None:
            return "COMMENT-DUP"
        store.db.execute(
            "INSERT INTO comments(comment_id,target_json,author,created_at,text,status,"
            " replies_json,mentions_json) VALUES(?,?,?,?,?,?,?,?)",
            (cid, json.dumps({"element_guid": payload.get("element_guid", "")},
                             ensure_ascii=False),
             payload.get("author", op.get("author", "")), str(payload.get("created_at", "")),
             payload.get("text", ""), payload.get("status", "open"),
             json.dumps(payload.get("replies", []), ensure_ascii=False),
             json.dumps(payload.get("mentions", []), ensure_ascii=False)))
        store.db.commit()
        return "COMMENT-APPLIED"
    if kind_op == "comment.reply":
        row = get(store, cid)
        if row is None:
            return "SKIP-comment-unknown"
        replies = json.loads(row["replies_json"] or "[]")
        if payload.get("reply") in replies:
            return "COMMENT-DUP"
        replies.append(payload.get("reply", {}))
        store.db.execute("UPDATE comments SET replies_json=? WHERE comment_id=?",
                         (json.dumps(replies, ensure_ascii=False), cid))
        store.db.commit()
        return "COMMENT-REPLIED"
    if kind_op == "comment.resolve":
        store.db.execute("UPDATE comments SET status='resolved' WHERE comment_id=?", (cid,))
        store.db.commit()
        return "COMMENT-RESOLVED"
    return "SKIP-comment-op"


def get(store, comment_id):
    return store.db.execute("SELECT * FROM comments WHERE comment_id=?",
                            (comment_id,)).fetchone()


def list_for_element(store, element_guid):
    out = []
    for row in store.db.execute("SELECT * FROM comments ORDER BY created_at"):
        try:
            target = json.loads(row["target_json"] or "{}")
        except ValueError:
            continue
        if target.get("element_guid") == element_guid:
            out.append(row)
    return out


def list_open(store):
    return list(store.db.execute("SELECT * FROM comments WHERE status='open'"
                                 " ORDER BY created_at"))
