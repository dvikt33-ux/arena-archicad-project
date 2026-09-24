"""Тесты блокировок: аренда, heartbeat, протухание, удалённые lock/unlock."""
import datetime
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from accollab import locks  # noqa: E402
from accollab.applier import apply_with_report  # noqa: E402
from accollab.store import Store  # noqa: E402
from test_sync import G1  # noqa: E402

T0 = datetime.datetime(2026, 9, 12, 0, 0, tzinfo=datetime.timezone.utc)


def t(dt, s):
    return dt + datetime.timedelta(seconds=s)


class LocksTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(os.path.join(self.tmp.name, "t.db"))

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def test_cycle(self):
        lease = locks.acquire(self.store, G1, "anna", mode="hard", ttl_s=20, now=T0)
        self.assertTrue(lease)
        row = locks.get(self.store, G1, now=t(T0, 5))
        self.assertEqual(row["holder"], "anna")
        self.assertEqual(row["mode"], "hard")
        self.assertTrue(locks.heartbeat(self.store, G1, lease, now=t(T0, 10)))
        self.assertTrue(locks.release(self.store, G1, lease))
        self.assertIsNone(locks.get(self.store, G1, now=t(T0, 11)))

    def test_second_holder_denied_then_expiry(self):
        locks.acquire(self.store, G1, "anna", now=T0)
        self.assertIsNone(locks.acquire(self.store, G1, "boris", now=t(T0, 5)))
        # протух (ttl 20) — boris перехватывает
        lease = locks.acquire(self.store, G1, "boris", now=t(T0, 25))
        self.assertTrue(lease)
        self.assertEqual(locks.get(self.store, G1, now=t(T0, 26))["holder"], "boris")

    def test_wrong_lease(self):
        lease = locks.acquire(self.store, G1, "anna", now=T0)
        self.assertFalse(locks.heartbeat(self.store, G1, "chuzhoy", now=t(T0, 1)))
        self.assertFalse(locks.release(self.store, G1, "chuzhoy"))
        self.assertTrue(locks.release(self.store, G1, lease))

    def test_hard_blocks_others_only(self):
        locks.acquire(self.store, G1, "anna", mode="hard", now=T0)
        self.assertTrue(locks.is_hard_locked_by_other(self.store, G1, "boris", now=t(T0, 1)))
        self.assertFalse(locks.is_hard_locked_by_other(self.store, G1, "anna", now=t(T0, 1)))
        locks.release(self.store, G1, locks.get(self.store, G1, now=T0)["lease_id"])
        locks.acquire(self.store, G1, "anna", mode="soft", now=T0)
        self.assertFalse(locks.is_hard_locked_by_other(self.store, G1, "boris", now=t(T0, 1)))

    def test_remote_roundtrip(self):
        op = locks.make_lock_op(G1, "anna", mode="hard", ttl_s=30, lease_id="L1")
        self.assertEqual(op["kind"], "lock")
        self.assertEqual(locks.apply_remote(self.store, op, now=T0), "LOCKED")
        row = locks.get(self.store, G1, now=t(T0, 1))
        self.assertEqual((row["holder"], row["mode"], row["lease_id"]), ("anna", "hard", "L1"))
        # чужой unlock не снимает
        bad = locks.make_unlock_op(G1, "boris")
        self.assertEqual(locks.apply_remote(self.store, bad, now=t(T0, 2)), "SKIP-unlock-chuzhoy")
        self.assertIsNotNone(locks.get(self.store, G1, now=t(T0, 2)))
        # свой снимает
        good = locks.make_unlock_op(G1, "anna", lease_id="L1")
        self.assertEqual(locks.apply_remote(self.store, good, now=t(T0, 3)), "UNLOCKED")
        self.assertIsNone(locks.get(self.store, G1, now=t(T0, 3)))

    def test_lock_op_via_applier(self):
        op = locks.make_lock_op(G1, "anna", mode="soft")
        rep = apply_with_report(None, self.store, op)
        self.assertEqual(rep["status"], "LOCKED")
        self.assertIsNotNone(locks.get(self.store, G1))
        row = self.store.get_operation(op["change_id"])
        self.assertEqual(row["applied"], 1)


if __name__ == "__main__":
    unittest.main()
