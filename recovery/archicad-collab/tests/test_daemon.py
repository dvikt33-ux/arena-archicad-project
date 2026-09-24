"""Тесты демона: тик, файлы outbox/inbox, hard-блок, конфликты, ретранслятор, CLI."""
import glob
import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import accollab.daemon as daemon_mod  # noqa: E402
from accollab import locks  # noqa: E402
from accollab.daemon import Daemon, save_config  # noqa: E402
from accollab.relay import start_server  # noqa: E402
from test_sync import FakeConn, G1, G2  # noqa: E402
from test_telegram import start_fake  # noqa: E402

REAL_SCAN = daemon_mod.scan_archicad


def patch_scan(conn):
    daemon_mod.scan_archicad = lambda **kw: (conn, 19723)


def unpatch_scan():
    daemon_mod.scan_archicad = REAL_SCAN


def make_cfg(tmp, author, **kw):
    cfg = {"project_id": "tropa", "author": author, "store": "db.sqlite",
           "poll_s": 5, "outbox_dir": "outbox", "inbox_dir": "inbox",
           "relay_url": "", "relay_secret": "", "archicad_timeout": 60}
    cfg.update(kw)
    path = os.path.join(tmp, "accollab.json")
    save_config(path, cfg)
    return path


class DaemonTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.a = os.path.join(self.tmp.name, "a")
        self.b = os.path.join(self.tmp.name, "b")
        os.makedirs(self.a)
        os.makedirs(self.b)
        self.conn_a = FakeConn({G1: 10.0, G2: 20.0})
        self.conn_b = FakeConn({G1: 10.0, G2: 20.0})

    def tearDown(self):
        unpatch_scan()
        self.tmp.cleanup()

    def test_file_carry_full_loop(self):
        patch_scan(self.conn_a)
        da = Daemon(make_cfg(self.a, "anna"))
        rep = da.tick()  # baseline
        self.assertEqual(rep["watch"].get("ops", []), [])
        self.conn_a.coords[G1] += 0.5
        rep = da.tick()  # diff + экспорт в файл
        self.assertEqual(len(rep["watch"].get("ops", [])), 1)
        self.assertEqual(len(rep["exported_files"]), 1)
        da.store.close()
        # перенос файла на B
        f = glob.glob(os.path.join(self.a, "outbox", "*.json"))[0]
        os.makedirs(os.path.join(self.b, "inbox"), exist_ok=True)
        shutil.copy(f, os.path.join(self.b, "inbox", "ops.json"))
        patch_scan(self.conn_b)
        db = Daemon(make_cfg(self.b, "boris"))
        rep = db.tick()
        self.assertEqual(rep["imported"], 1)
        self.assertEqual(rep["applied"][0]["status"], "APPLIED")
        self.assertAlmostEqual(self.conn_b.coords[G1], 10.5)
        db.store.close()
        # status.json записан
        with open(os.path.join(self.b, "status.json"), encoding="utf-8") as fh:
            st = json.load(fh)
        self.assertEqual(st["conflicts_open"], 0)

    def test_hard_lock_blocks_and_records_conflict(self):
        patch_scan(self.conn_a)
        da = Daemon(make_cfg(self.a, "anna"))
        da.tick()
        self.conn_a.coords[G1] += 0.5
        da.tick()
        da.store.close()
        f = glob.glob(os.path.join(self.a, "outbox", "*.json"))[0]
        os.makedirs(os.path.join(self.b, "inbox"), exist_ok=True)
        shutil.copy(f, os.path.join(self.b, "inbox", "ops.json"))
        patch_scan(self.conn_b)
        db = Daemon(make_cfg(self.b, "boris"))
        locks.acquire(db.store, G1, "carla", mode="hard")  # чужой hard-блок на B
        rep = db.tick()
        self.assertEqual(rep["applied"][0]["status"], "CONFLICT-locked")
        self.assertAlmostEqual(self.conn_b.coords[G1], 10.0)  # проект не тронут
        conflicts = db.store.list_conflicts(status="open")
        self.assertEqual(len(conflicts), 1)
        self.assertIn("CONFLICT-locked", conflicts[0]["resolution"])
        db.store.close()

    def test_bad_protocol_goes_to_bad(self):
        patch_scan(self.conn_b)
        os.makedirs(os.path.join(self.b, "inbox"), exist_ok=True)
        with open(os.path.join(self.b, "inbox", "evil.json"), "w", encoding="utf-8") as fh:
            json.dump({"protocol": "9.9", "ops": []}, fh)
        db = Daemon(make_cfg(self.b, "boris"))
        rep = db.tick()  # не падает
        self.assertEqual(rep["imported"], 0)
        self.assertTrue(os.path.exists(os.path.join(self.b, "inbox", "evil.json.bad.json")))
        db.store.close()

    def test_relay_flow(self):
        srv, port = start_server()
        try:
            url = "http://127.0.0.1:%d" % port
            patch_scan(self.conn_a)
            da = Daemon(make_cfg(self.a, "anna", relay_url=url))
            da.tick()
            self.conn_a.coords[G2] += 1.0
            rep = da.tick()
            # outbox ушёл либо в файл, либо в relay — в любом случае очередь пуста
            self.assertEqual(da.store.list_outbox(), [])
            da.store.close()
            patch_scan(self.conn_b)
            db = Daemon(make_cfg(self.b, "boris", relay_url=url))
            rep = db.tick()
            # B мог получить оп через relay (файлы тоже экспортировались, но не переносились)
            self.assertEqual(rep["applied"][0]["status"], "APPLIED")
            self.assertAlmostEqual(self.conn_b.coords[G2], 21.0)
            st = db.store.get_sync_state("relay")
            self.assertIn("cursor", st["last_vector"])
            db.store.close()
        finally:
            srv.shutdown(); srv.server_close()

    def test_telegram_flow(self):
        srv, base = start_fake()
        try:
            patch_scan(self.conn_a)
            da = Daemon(make_cfg(self.a, "anna", telegram_bot_token="TESTTOKEN",
                                 telegram_chat_id="@chan", telegram_api_base=base))
            da.tick()
            self.conn_a.coords[G1] += 0.5
            rep = da.tick()
            self.assertEqual(rep["telegram"]["pushed"], 1)
            self.assertEqual(da.store.list_outbox(), [])
            da.store.close()
            patch_scan(self.conn_b)
            db = Daemon(make_cfg(self.b, "boris", telegram_bot_token="TESTTOKEN",
                                 telegram_chat_id="@chan", telegram_api_base=base))
            rep = db.tick()
            self.assertEqual(rep["telegram"]["fresh"], 1)
            self.assertEqual(rep["applied"][0]["status"], "APPLIED")
            self.assertAlmostEqual(self.conn_b.coords[G1], 10.5)
            db.store.close()
        finally:
            srv.shutdown()
            srv.server_close()

    def test_deterministic_order_same_winner(self):
        # две чужие РАСХОДЯЩИЕСЯ операции: побеждает меньший (lamport, change_id).
        # (Одинаковые движения теперь конвергируют через already_applied —
        #  см. test_already_applied_recovery; конфликт — только при расхождении.)
        import json as _json
        from test_sync import beam_detail
        from accollab.store import element_checksum
        patch_scan(self.conn_b)
        db = Daemon(make_cfg(self.b, "boris"))
        bid = "БЛК - %s" % G1[0]  # тот же id, что отдаёт FakeConn
        before = {"type": "Beam", "checksum": element_checksum(beam_detail(10.0, bid)),
                  "details": beam_detail(10.0, bid)}
        after = {"type": "Beam", "checksum": element_checksum(beam_detail(10.5, bid)),
                 "details": beam_detail(10.5, bid)}
        after_b = {"type": "Beam", "checksum": element_checksum(beam_detail(11.0, bid)),
                     "details": beam_detail(11.0, bid)}
        ops = []
        for cid, author, lamp, aft in (("op-B", "bob", 200, after_b),
                                       ("op-A", "anna", 100, after)):
            ops.append({"change_id": cid, "element_guid": G1, "author": author,
                        "wall_time": "", "lamport": lamp, "op": "modify", "kind": "primary",
                        "before_json": _json.dumps(before),
                        "after_json": _json.dumps(aft), "applied": 0})
        for op in ops:
            db.store.insert_operation(op)
        out = db.apply_pending(self.conn_b)
        statuses = {r["change_id"]: r["status"] for r in out}
        # порядок применения детерминированный: сначала op-A (lamport 100)
        self.assertEqual([r["change_id"] for r in out], ["op-A", "op-B"])
        self.assertEqual(statuses["op-A"], "APPLIED")
        self.assertEqual(statuses["op-B"], "CONFLICT-base")  # base уже уехал
        db.store.close()

    def test_lock_warnings_in_tick(self):
        patch_scan(self.conn_b)
        db = Daemon(make_cfg(self.b, "boris"))
        db.tick()  # baseline
        locks.acquire(db.store, G1, "anna", mode="hard")  # чужой блок
        self.conn_b.coords[G1] += 0.5  # правим под блоком
        rep = db.tick()
        self.assertEqual(len(rep["watch"].get("ops", [])), 1)
        self.assertEqual(len(rep["warnings"]), 1)
        self.assertEqual(rep["warnings"][0]["holder"], "anna")
        with open(os.path.join(self.b, "status.json"), encoding="utf-8") as fh:
            st = json.load(fh)
        self.assertEqual(len(st["warnings"]), 1)
        db.store.close()

    def test_cli_comments_history_backup(self):
        cfg = make_cfg(self.a, "anna", backup_dir=os.path.join(self.a, "bk"))
        self.assertEqual(daemon_mod.main(["--config", cfg, "comment", G1, "smotri", "suda"]), 0)
        self.assertEqual(daemon_mod.main(["--config", cfg, "comments", G1]), 0)
        self.assertEqual(daemon_mod.main(["--config", cfg, "history", G1]), 0)
        # backup: подменяем tapir у FakeConn
        pln = os.path.join(self.a, "tropa.pln")
        with open(pln, "wb") as f:
            f.write(b"PLN" * 500)
        self.conn_a.tapir = lambda name, params=None: {"projectPath": pln}
        patch_scan(self.conn_a)
        rc = daemon_mod.main(["--config", cfg, "backup", "--keep", "3"])
        self.assertEqual(rc, 0)
        copies = [f for f in os.listdir(os.path.join(self.a, "bk")) if f.endswith(".pln")]
        self.assertEqual(len(copies), 1)

    def test_cli_init_status(self):
        rc = daemon_mod.main(["--config", os.path.join(self.a, "c.json"),
                              "init", "--author", "anna"])
        self.assertEqual(rc, 0)
        rc = daemon_mod.main(["--config", os.path.join(self.a, "c.json"), "status"])
        self.assertEqual(rc, 1)  # status.json пока нет


    def test_presence_disabled(self):
        real = daemon_mod.scan_archicad
        daemon_mod.scan_archicad = lambda **kw: (self.conn_a, 19723)
        try:
            da = Daemon(make_cfg(self.a, "anna", presence_enabled=False))
            try:
                rep = da.tick()
            finally:
                da.store.close()
        finally:
            daemon_mod.scan_archicad = real
        self.assertEqual(rep["presence"], {"disabled": True})

    def test_auto_checkpoint_unit(self):
        da = Daemon(make_cfg(self.a, "anna", auto_checkpoint=True))
        try:
            op = {"change_id": "c-f1", "project_id": "tropa", "element_guid": G1,
                  "author": "boris", "wall_time": "t", "op": "modify", "kind": "primary"}
            da.store.insert_operation(op)
            cpid = da._auto_checkpoint(self.conn_a)
            self.assertTrue(cpid)
            self.assertEqual(len(da.store.list_checkpoints()), 1)
            da.store.mark_applied("c-f1")
            self.assertIsNone(da._auto_checkpoint(self.conn_a))
            self.assertEqual(len(da.store.list_checkpoints()), 1)
        finally:
            da.store.close()

    def test_notify_conflicts(self):
        from test_telegram import FakeBotAPI, start_fake
        srv, base = start_fake()
        try:
            da = Daemon(make_cfg(self.a, "anna", telegram_bot_token="TESTTOKEN",
                                 telegram_chat_id="@c", telegram_api_base=base,
                                 telegram_notify=True))
            try:
                n = da._notify_conflicts([{"status": "CONFLICT-base", "change_id": "cx"},
                                          {"status": "APPLIED", "change_id": "cy"}])
            finally:
                da.store.close()
        finally:
            srv.shutdown()
            srv.server_close()
        self.assertEqual(n, 1)
        self.assertEqual(len(FakeBotAPI.messages), 1)
        self.assertIn("konflikt", FakeBotAPI.messages[0])


if __name__ == "__main__":
    unittest.main()
