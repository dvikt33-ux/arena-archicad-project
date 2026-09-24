"""Тесты чекпоинтов: создание, план отката, применение, skipped-ветки."""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from accollab import checkpoints  # noqa: E402
from accollab.store import Store, element_checksum  # noqa: E402
from accollab.watcher import Watcher  # noqa: E402
from test_sync import FakeConn, G1, G2, beam_detail  # noqa: E402

G3 = "cccccccc-cccc-cccc-cccc-cccccccccccc"


class CheckpointsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(os.path.join(self.tmp.name, "t.db"))
        self.conn = FakeConn({G1: 10.0, G2: 20.0})
        self.watcher = Watcher(self.conn, self.store, "tropa", "anna")

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def test_rollback_restores_coords(self):
        snap0 = self.watcher.take_snapshot()
        cpid = checkpoints.create(self.store, snap0["items"], "do-sdviga", "anna")
        self.assertTrue(cpid.startswith("cp-"))
        self.conn.coords[G1] += 0.5
        cur = self.watcher.take_snapshot()["items"]
        plan = checkpoints.rollback_plan(self.store, cpid, cur, "anna")
        self.assertEqual(len(plan["ops"]), 1)
        self.assertEqual(plan["skipped"], [])
        rep = checkpoints.rollback_apply(self.conn, self.store, plan)
        self.assertEqual(rep["results"][0]["status"], "APPLIED")
        self.assertAlmostEqual(self.conn.coords[G1], 10.0)
        # повторный план после отката пуст
        cur2 = self.watcher.take_snapshot()["items"]
        plan2 = checkpoints.rollback_plan(self.store, cpid, cur2, "anna")
        self.assertEqual(plan2["ops"], [])

    def test_skipped_branches(self):
        snap0 = self.watcher.take_snapshot()
        cpid = checkpoints.create(self.store, snap0["items"], "cp", "anna")
        self.conn.coords[G3] = 30.0  # создан после чекпоинта
        del self.conn.coords[G2]  # удалён после чекпоинта
        cur = self.watcher.take_snapshot()["items"]
        # изменение без сдвига координат: тот же beg, другой мусор
        cur[G1] = {"type": "Beam",
                   "checksum": element_checksum({"type": "Beam", "details": {"other": 1}}),
                   "details": {"type": "Beam", "details": {"other": 1}}}
        plan = checkpoints.rollback_plan(self.store, cpid, cur, "anna")
        reasons = sorted(s["reason"] for s in plan["skipped"])
        self.assertEqual(reasons, ["created-after-checkpoint", "deleted-after-checkpoint",
                                   "no-coords-vector"])
        self.assertEqual(plan["ops"], [])

    def test_missing_checkpoint(self):
        with self.assertRaises(KeyError):
            checkpoints.rollback_plan(self.store, "cp-net", {}, "anna")


if __name__ == "__main__":
    unittest.main()
