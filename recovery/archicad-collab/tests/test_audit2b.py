"""Аудит-2, батч 2: строгий ingest, транзакции, lease-правила, SKIP-ретраи."""
import json
import os
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import accollab.daemon as daemon_mod  # noqa: E402
from accollab import comments as comments_mod  # noqa: E402
from accollab import locks as locks_mod  # noqa: E402
from accollab.daemon import Daemon  # noqa: E402
from accollab.transfer import import_envelope, validate_op  # noqa: E402
from accollab.watcher import Watcher  # noqa: E402
from test_daemon import make_cfg  # noqa: E402
from test_sync import FakeConn, G1, G2, beam_detail  # noqa: E402


def _full_op(**kw):
    op = {"change_id": "c1", "project_id": "tropa", "element_guid": G1,
          "author": "boris", "wall_time": "t", "lamport": 1,
          "kind": "primary", "op": "modify",
          "before_json": "{}", "after_json": "{}",
          "tx_id": "", "applied": 0}
    op.update(kw)
    return op


class Audit2Batch2Test(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = os.path.join(self.tmp.name, "a")
        os.makedirs(self.home)
        self.real_scan = daemon_mod.scan_archicad
        self.addCleanup(setattr, daemon_mod, "scan_archicad", self.real_scan)
        daemon_mod.scan_archicad = lambda **kw: (None, None)
        self.d = Daemon(make_cfg(self.home, "anna"))
        self.addCleanup(self.d.store.close)

    # --- строгая валидация ---

    def test_validate_op_shapes(self):
        self.assertIsNone(validate_op(_full_op(), "tropa"))
        bad = dict(_full_op(), before_json="{oops")
        self.assertEqual(validate_op(bad, "tropa"), "before_json bityy JSON")
        bad = dict(_full_op(), kind="teleport")
        self.assertEqual(validate_op(bad, "tropa"), "neizvestnyy kind")
        bad = dict(_full_op(), author="")
        self.assertEqual(validate_op(bad, "tropa"), "net author")
        bad = dict(_full_op(), lamport="1")
        self.assertEqual(validate_op(bad, "tropa"), "lamport ne int")
        bad = dict(_full_op(), kind="lock", op="lock")
        self.assertIsNone(validate_op(bad, "tropa"))
        bad = dict(_full_op(), kind="lock", op="unlock")
        self.assertIsNotNone(validate_op(bad, "tropa"))
        # lock/comment фабрики дают валидные опs (со штампом проекта)
        lop = locks_mod.make_lock_op(G1, "boris", "soft", 20, "boris-1")
        lop["project_id"] = "tropa"
        self.assertIsNone(validate_op(lop, "tropa"))
        _cid, cop = comments_mod.add_local(self.d.store, G1, "boris", "privet")
        cop["project_id"] = "tropa"
        self.assertIsNone(validate_op(cop, "tropa"))

    def test_bad_file_rejected_nothing_inserted(self):
        env = {"protocol": "1.0", "project_id": "tropa",
               "ops": [_full_op(change_id="good"),
                       dict(_full_op(change_id="bad"), after_json="{oops")]}
        with self.assertRaises(ValueError):
            import_envelope(self.d.store, env, project_id="tropa")
        self.assertIsNone(self.d.store.get_operation("good"))
        self.assertIsNone(self.d.store.get_operation("bad"))

    # --- локи: валидация и lease ---

    def test_lock_bad_payload_rejected_table_clean(self):
        op = locks_mod.make_lock_op(G1, "boris", "soft", 20, "boris-1")
        heads = json.loads(op["after_json"])
        heads["ttl_s"] = "oops"
        op["after_json"] = json.dumps(heads)
        self.assertEqual(locks_mod.apply_remote(self.d.store, op),
                         "SKIP-lock-badpayload")
        self.assertIsNone(locks_mod.get(self.d.store, G1))  # не упало, пусто
        heads["ttl_s"] = 20
        heads["mode"] = "evil"
        op["after_json"] = json.dumps(heads)
        self.assertEqual(locks_mod.apply_remote(self.d.store, op),
                         "SKIP-lock-badpayload")

    def test_unlock_requires_lease(self):
        lease1 = locks_mod.acquire(self.d.store, G1, "boris", "soft", 60)
        locks_mod.release(self.d.store, G1, lease1)
        lease2 = locks_mod.acquire(self.d.store, G1, "boris", "soft", 60)
        stale = locks_mod.make_unlock_op(G1, "boris", lease1)
        self.assertEqual(locks_mod.apply_remote(self.d.store, stale),
                         "SKIP-unlock-chuzhoy")
        self.assertEqual(locks_mod.get(self.d.store, G1)["lease_id"], lease2)
        fresh = locks_mod.make_unlock_op(G1, "boris", lease2)
        self.assertEqual(locks_mod.apply_remote(self.d.store, fresh), "UNLOCKED")
        self.assertIsNone(locks_mod.get(self.d.store, G1))

    def test_stale_lock_same_holder_ignored(self):
        lease1 = locks_mod.acquire(self.d.store, G1, "boris", "soft", 60)
        op = locks_mod.make_lock_op(G1, "boris", "soft", 60, "boris-stale")
        self.assertEqual(locks_mod.apply_remote(self.d.store, op), "SKIP-lock-stale")
        self.assertEqual(locks_mod.get(self.d.store, G1)["lease_id"], lease1)
        renew = locks_mod.make_lock_op(G1, "boris", "soft", 60, lease1)
        self.assertEqual(locks_mod.apply_remote(self.d.store, renew), "LOCKED")

    def test_poisoned_row_self_cleans(self):
        self.d.store.db.execute(
            "INSERT INTO locks(element_guid,holder,lease_id,since,heartbeat,"
            " expires_in_s,mode) VALUES(?,?,?,?,?,?,?)",
            (G1, "boris", "b-1", "t", "t", "oops", "soft"))
        self.d.store.db.commit()
        self.assertIsNone(locks_mod.get(self.d.store, G1))  # не упало, снесло
        self.assertIsNone(self.d.store.db.execute(
            "SELECT * FROM locks WHERE element_guid=?", (G1,)).fetchone())

    # --- транзакции ---

    def test_integrity_narrow(self):
        self.assertTrue(self.d.store.insert_operation(_full_op()))
        self.assertFalse(self.d.store.insert_operation(_full_op()))  # дубль
        bad = _full_op(change_id="c2")
        bad["project_id"] = None
        with self.assertRaises(sqlite3.IntegrityError):
            self.d.store.insert_operation(bad)

    def test_transaction_rolls_back(self):
        with self.assertRaises(RuntimeError):
            with self.d.store.transaction():
                self.d.store.insert_operation(_full_op())
                raise RuntimeError("boom")
        self.assertIsNone(self.d.store.get_operation("c1"))

    def test_watcher_atomic(self):
        conn = FakeConn({G1: 10.0, G2: 20.0})
        w = Watcher(conn, self.d.store, "tropa", "anna")
        w.poll_and_record()  # baseline
        conn.coords[G1] += 1.0
        conn.coords[G2] += 1.0
        snap_before = self.d.store.load_last_snapshot()["data_json"]
        real_enqueue = self.d.store.enqueue_outbox

        def _boom(*a, **k):
            raise RuntimeError("obryv")
        self.d.store.enqueue_outbox = _boom
        try:
            with self.assertRaises(RuntimeError):
                w.poll_and_record()
        finally:
            self.d.store.enqueue_outbox = real_enqueue
        self.assertEqual(self.d.store.ops_for_element(G1), [])  # откат
        self.assertEqual(self.d.store.load_last_snapshot()["data_json"],
                         snap_before)  # baseline цел

    # --- SKIP-ретраи и auto-checkpoint ---

    def test_skip_comment_unknown_retries(self):
        conn = FakeConn({G1: 10.0})
        op = {"change_id": "r1", "project_id": "tropa", "element_guid": G1,
              "author": "boris", "wall_time": 1, "lamport": 1,
              "kind": "comment", "op": "comment.reply",
              "before_json": "{}",
              "after_json": json.dumps({"comment_id": "cm-mama",
                                         "reply": {"author": "b", "text": "da"}})}
        self.d.store.insert_operation(op)
        out = self.d.apply_pending(conn)
        self.assertEqual(out[0]["status"], "SKIP-comment-unknown")
        self.assertEqual(self.d.store.get_operation("r1")["applied"], 0)
        self.d.store.db.execute(
            "INSERT INTO comments(comment_id,target_json,author,created_at,text,"
            " status,replies_json,mentions_json) VALUES(?,?,?,?,?,?,?,?)",
            ("cm-mama", "{}", "boris", "t", "mama", "open", "[]", "[]"))
        self.d.store.db.commit()
        out = self.d.apply_pending(conn)
        self.assertIn("COMMENT", out[0]["status"])

    def test_auto_checkpoint_skips_unsupported(self):
        self.d.store.insert_operation(_full_op(op="create"))
        self.assertIsNone(self.d._auto_checkpoint(None))
        self.assertEqual(self.d.store.list_checkpoints(), [])

    def test_create_not_enqueued(self):
        conn = FakeConn({G1: 10.0})
        w = Watcher(conn, self.d.store, "tropa", "anna")
        w.poll_and_record()
        conn.coords[G2] = 5.0
        rep = w.poll_and_record()
        self.assertEqual(rep["created"], [G2])
        self.assertEqual(rep.get("not_synced"), 1)
        self.assertEqual(self.d.store.list_outbox(), [])
        self.assertNotEqual(self.d.store.ops_for_element(G2), [])  # история есть

    def test_config_error_visible(self):
        with open(os.path.join(self.home, "accollab.json"), "w",
                  encoding="utf-8") as f:
            f.write("{oops")
        rep = self.d.tick()
        self.assertTrue(any(e["where"] == "config" for e in rep["errors"]))


if __name__ == "__main__":
    unittest.main()
