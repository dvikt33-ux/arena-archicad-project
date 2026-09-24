"""Аудит-2, батч 1: PLN-гард, durable чекпоинты, broadcast отката, preshift.

Критическое ядро: чужой PLN не пишется, чекпоинты переживают ротацию,
откат уезжает соседям, не-жёсткий сдвиг не трогает модель.
"""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import accollab.daemon as daemon_mod  # noqa: E402
from accollab import checkpoints as cp_mod  # noqa: E402
from accollab.applier import (  # noqa: E402
    UnsupportedOpError, apply_operation, apply_with_report)
from accollab.connector import ArchicadError  # noqa: E402
from accollab.daemon import Daemon  # noqa: E402
from accollab.store import Store, element_checksum  # noqa: E402
from test_daemon import make_cfg  # noqa: E402
from test_sync import FakeConn, G1, beam_detail  # noqa: E402

PLN_A = {"projectPath": "C:\\mock\\a.pln", "projectName": "a",
         "isUntitled": False, "isTeamwork": False}
PLN_B = {"projectPath": "C:\\mock\\b.pln", "projectName": "b",
         "isUntitled": False, "isTeamwork": False}


def _item(x, bid):
    full = beam_detail(x, bid)
    return {"type": "Beam", "checksum": element_checksum(full), "details": full}


def _mkop(cid, guid, before_full, after_full):
    return {"change_id": cid, "project_id": "tropa", "element_guid": guid,
            "author": "boris", "wall_time": "t", "lamport": 1,
            "kind": "primary", "op": "modify",
            "before_json": json.dumps(
                {"type": "Beam", "checksum": element_checksum(before_full),
                 "details": before_full}),
            "after_json": json.dumps(
                {"type": "Beam", "checksum": element_checksum(after_full),
                 "details": after_full})}


class Audit2Batch1Test(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = os.path.join(self.tmp.name, "a")
        os.makedirs(self.home)
        self.real_scan = daemon_mod.scan_archicad
        self.addCleanup(setattr, daemon_mod, "scan_archicad", self.real_scan)
        self.conn = FakeConn({G1: 10.0})
        self.conn.pln = dict(PLN_A)
        daemon_mod.scan_archicad = lambda **kw: (self.conn, 19723)
        self.d = Daemon(make_cfg(self.home, "anna"))
        self.addCleanup(self.d.store.close)
        self.cfg_path = os.path.join(self.home, "accollab.json")

    def test_pln_pins_then_blocks_other(self):
        rep = self.d.tick()
        self.assertIn("baseline", rep["watch"])
        row = self.d.store.db.execute(
            "SELECT value FROM meta WHERE key='pln_identity'").fetchone()
        self.assertIn('"name": "a"', row["value"])
        self.conn.pln = dict(PLN_B)
        rep = self.d.tick()
        self.assertEqual(rep["watch"], {})
        self.assertTrue(any(e["where"] == "pln" for e in rep["errors"]))
        # транспорты идут: импорт файла работает при заблокированной модели
        env = {"protocol": "1.0", "project_id": "tropa", "ops": []}
        with open(os.path.join(self.home, "inbox", "ops-x.json"), "w",
                  encoding="utf-8") as f:
            json.dump(env, f)
        rep = self.d.tick()
        self.assertEqual(rep["watch"], {})
        self.assertTrue(os.path.exists(
            os.path.join(self.home, "inbox", "ops-x.json.done.json")))

    def test_pln_unknown_blocks(self):
        self.d.tick()
        self.conn.pln = {}  # Archicad без проекта
        rep = self.d.tick()
        self.assertEqual(rep["watch"], {})
        self.assertTrue(any(e["where"] == "pln" for e in rep["errors"]))

    def test_pln_cli_and_repin(self):
        self.d.tick()  # pin A
        self.assertEqual(daemon_mod.main(["--config", self.cfg_path, "pln"]), 0)
        self.conn.pln = dict(PLN_B)
        self.assertEqual(daemon_mod.main(
            ["--config", self.cfg_path, "pln", "--repin"]), 0)
        rep = self.d.tick()  # теперь B свой
        self.assertNotEqual(rep["watch"], {})

    def test_checkpoint_survives_rotation(self):
        items = {G1: _item(10.0, "БЛК - a")}
        cpid = cp_mod.create(self.d.store, items, "t1", "anna")
        for i in range(25):
            self.d.store.save_snapshot("t%d" % i, 1, "{}")
        plan = cp_mod.rollback_plan(self.d.store, cpid, {G1: _item(12.0, "БЛК - a")},
                                    "anna", project_id="tropa")
        self.assertEqual(len(plan["ops"]), 1)
        self.assertEqual(plan["skipped"], [])

    def test_legacy_checkpoint_migrated(self):
        sid = self.d.store.save_snapshot(
            "t0", 1, json.dumps({G1: _item(10.0, "БЛК - a")}))
        self.d.store.save_checkpoint("cp-old", "old", "anna",
                                     json.dumps({"snapshot_id": sid, "count": 1}))
        self.d.store.close()
        # «старая» база: сбрасываем версию, переоткрываем — миграция копирует данные
        db_path = os.path.join(self.home, "db.sqlite")
        probe = Store(db_path)
        probe.db.execute("UPDATE meta SET value='2' WHERE key='schema_version'")
        probe.db.commit()
        probe.close()
        s2 = Store(db_path)
        self.addCleanup(s2.close)
        self.assertIsNotNone(s2.load_checkpoint_data("cp-old"))
        s2.db.execute("DELETE FROM snapshots")  # ротация съела всё
        s2.db.commit()
        plan = cp_mod.rollback_plan(s2, "cp-old", {G1: _item(12.0, "БЛК - a")}, "anna")
        self.assertEqual(len(plan["ops"]), 1)

    def test_rollback_broadcasts(self):
        bid = "БЛК - a"
        old, new = {G1: _item(10.0, bid)}, {G1: _item(12.0, bid)}
        cpid = cp_mod.create(self.d.store, old, "t1", "anna")
        self.conn.coords[G1] = 12.0  # живьём сейчас new
        plan = cp_mod.rollback_plan(self.d.store, cpid, new, "anna",
                                    project_id="tropa")
        rep = cp_mod.rollback_apply(self.conn, self.d.store, plan)
        self.assertEqual(rep["results"][0]["status"], "APPLIED")
        self.assertEqual(self.d.store.list_outbox(), [plan["ops"][0]["change_id"]])

    def test_length_change_untouched(self):
        bid = "БЛК - a"
        before_full = beam_detail(10.0, bid)
        after_full = beam_detail(12.0, bid)
        after_full["details"]["endCoordinate"]["x"] = 17.0  # длина +1
        op = _mkop("cx", G1, before_full, after_full)
        with self.assertRaises(UnsupportedOpError):
            apply_operation(self.conn, self.d.store, dict(op))
        self.assertEqual(self.conn.moves, [])  # модель не тронута
        rep = apply_with_report(self.conn, self.d.store, dict(op))
        self.assertEqual(rep["status"], "UNSUPPORTED")

    def test_compensation_attempted(self):
        class _Crooked(FakeConn):
            def tapir(self, name, params=None):
                for item in params["elementsWithMoveVectors"]:
                    g = item["elementId"]["guid"]
                    self.coords[g] += 999.0
                    self.moves.append((g, {"x": 999.0}))
                return {"executionResults": [{"success": True}]}

        conn = _Crooked({G1: 10.0})
        bid = "БЛК - a"
        op = _mkop("c1", G1, beam_detail(10.0, bid), beam_detail(12.0, bid))
        with self.assertRaises(ArchicadError):
            apply_operation(conn, self.d.store, dict(op))
        self.assertEqual(len(conn.moves), 2)  # движение + компенсация


if __name__ == "__main__":
    unittest.main()
