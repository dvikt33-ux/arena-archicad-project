"""Тесты присутствия: подсветка локов цветами, без локов — тишина."""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from accollab import locks, presence  # noqa: E402
from accollab.store import Store  # noqa: E402
from test_sync import G1, G2  # noqa: E402


class HiConn:
    def __init__(self):
        self.calls = []

    def highlight(self, guids, rgb=(0, 0, 0)):
        self.calls.append((list(guids), rgb))
        return {"success": True}


class PresenceTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(os.path.join(self.tmp.name, "t.db"))
        self.conn = HiConn()

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def test_group_by_holder(self):
        locks.acquire(self.store, G1, "anna")
        locks.acquire(self.store, G2, "boris")
        res = presence.refresh(self.conn, self.store)
        self.assertEqual(res, {"highlighted": {"anna": 1, "boris": 1}})
        self.assertEqual(len(self.conn.calls), 2)
        colors = {tuple(c) for _, c in self.conn.calls}
        self.assertEqual(len(colors), 2)  # разные holder'ы — разные цвета
        for rgb in colors:
            self.assertTrue(all(0 <= v <= 255 for v in rgb))

    def test_silent_without_locks(self):
        res = presence.refresh(self.conn, self.store)
        self.assertEqual(res, {"highlighted": {}})
        self.assertEqual(self.conn.calls, [])

    def test_color_stable(self):
        c1 = presence.color_for(self.store, "anna")
        c2 = presence.color_for(self.store, "anna")
        self.assertEqual(c1, c2)
        row = self.store.db.execute(
            "SELECT * FROM participants WHERE participant_id='anna'").fetchone()
        self.assertIsNotNone(row)


    def test_own_color_override(self):
        locks.acquire(self.store, G1, "anna")
        locks.acquire(self.store, G2, "boris")
        res = presence.refresh(self.conn, self.store, own="anna", own_color="#FF0000")
        self.assertEqual(res, {"highlighted": {"anna": 1, "boris": 1}})
        mine = [rgb for guids, rgb in self.conn.calls if guids == [G1]]
        self.assertEqual(mine, [(255, 0, 0)])


if __name__ == "__main__":
    unittest.main()
