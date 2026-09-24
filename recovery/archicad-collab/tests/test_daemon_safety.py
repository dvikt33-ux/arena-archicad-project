"""Безопасность демона: замок тика, личность базы, валидация, heartbeat.

Покрывают триаж внешнего ревью: второй тик по той же базе запрещён,
чужая база/проект не открываются молча, битые файлы уходят в карантин,
сердцебиение локов уезжает соседям (throttled), авто-чекпоинт fail-closed.
"""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import accollab.daemon as daemon_mod  # noqa: E402
from accollab import PROTOCOL_VERSION  # noqa: E402
from accollab import locks as locks_mod  # noqa: E402
from accollab.applier import apply_operation, BaseMismatchError  # noqa: E402
from accollab.connector import ArchicadError  # noqa: E402
from accollab.daemon import Daemon, load_config, save_config  # noqa: E402
from accollab.runtime import sync_guard  # noqa: E402
from accollab.store import element_checksum  # noqa: E402
from accollab.transfer import import_envelope, validate_op  # noqa: E402
from test_daemon import make_cfg  # noqa: E402
import mock_archicad as mock_mod  # noqa: E402
from test_sync import FakeConn, G1, beam_detail  # noqa: E402


def _move_op(cid, guid, author, x0, x1):
    # Форма вотчера в точности: {"type","checksum","details"} (контракт операций).
    bid = "БЛК - %s" % guid[0]  # тот же id, что отдаёт FakeConn (как живой Archicad)
    before_full, after_full = beam_detail(x0, bid), beam_detail(x1, bid)
    before = {"type": "Beam", "checksum": element_checksum(before_full),
              "details": before_full}
    after = {"type": "Beam", "checksum": element_checksum(after_full),
             "details": after_full}
    return {"change_id": cid, "project_id": "tropa", "element_guid": guid,
            "author": author, "wall_time": "2026-09-17T00:00:00+00:00",
            "lamport": 1, "kind": "primary", "op": "modify",
            "before_json": json.dumps(before), "after_json": json.dumps(after)}


class DaemonSafetyTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.real_scan = daemon_mod.scan_archicad
        daemon_mod.scan_archicad = lambda **kw: (None, None)  # Archicad нет
        self.addCleanup(setattr, daemon_mod, "scan_archicad", self.real_scan)
        self.dir = os.path.join(self.tmp.name, "a")
        os.makedirs(self.dir)
        self._daemons = []
        self.addCleanup(self._close_all)

    def _open(self, author="anna", **kw):
        d = Daemon(make_cfg(self.dir, author, **kw))
        self._daemons.append(d)
        return d

    def _close_all(self):
        for d in self._daemons:
            d.store.close()
        self._daemons = []

    # --- замок тика ---

    def test_tick_guard_blocks_second_tick(self):
        d = self._open()
        with sync_guard(d.store.path):
            with self.assertRaises(RuntimeError):
                d.tick()  # скан даже не вызывается — замок первый

    def test_guard_released_after_tick(self):
        d = self._open()
        d.tick()
        d.tick()  # второй тик не видит замок первого

    # --- личность базы ---

    def test_second_author_on_used_db_rejected(self):
        d = self._open("anna")
        d.store.insert_operation(_move_op("c1", G1, "anna", 10.0, 12.0))
        self._close_all()
        with self.assertRaises(ValueError):
            self._open("boris")

    def test_empty_db_adopts_new_identity(self):
        self._open("anna")  # операций нет — база ничья
        self._close_all()
        d = self._open("boris")  # не бросает
        d.tick()

    def test_foreign_project_op_blocks_reopen(self):
        d = self._open("anna")
        op = _move_op("cx", G1, "anna", 10.0, 12.0)
        op["project_id"] = "chuzhoy"
        d.store.insert_operation(op)  # сырая вставка — проверка при открытии
        self._close_all()
        with self.assertRaises(ValueError):
            self._open("anna")

    # --- валидация ---

    def test_config_range_rejected_and_file_intact(self):
        d = self._open()
        path = os.path.join(self.dir, "accollab.json")
        with open(path, encoding="utf-8") as f:
            good = f.read()
        bad = dict(d.cfg)
        bad["poll_s"] = 0
        with self.assertRaises(ValueError):
            save_config(path, bad)
        with open(path, encoding="utf-8") as f:
            self.assertEqual(f.read(), good)  # битое не записалось

    def test_config_bool_rejected(self):
        d = self._open()
        bad = dict(d.cfg)
        bad["presence_enabled"] = "da"
        with self.assertRaises(ValueError):
            save_config(os.path.join(self.dir, "accollab.json"), bad)

    def test_validate_op(self):
        # Строгий контракт: структура целиком, не только change_id.
        self.assertIsNotNone(validate_op([1, 2], "tropa"))
        self.assertIsNotNone(validate_op({"net-id": 1}, "tropa"))
        self.assertIsNotNone(validate_op({"change_id": "x", "project_id": "ch"},
                                          "tropa"))
        self.assertIsNotNone(validate_op({"change_id": "x"}, "tropa"))  # нет author/op
        good = {"change_id": "x", "project_id": "tropa", "author": "b",
                "op": "modify", "kind": "primary", "element_guid": "g",
                "wall_time": "t", "lamport": 1,
                "before_json": "{}", "after_json": "{}"}
        self.assertIsNone(validate_op(good, "tropa"))
        legacy = dict(good)
        del legacy["project_id"]  # legacy без проекта — пропускаем
        self.assertIsNone(validate_op(legacy, "tropa"))

    def test_bad_file_quarantined_tick_survives(self):
        d = self._open()
        inbox = os.path.join(self.dir, "inbox")
        env = {"protocol": PROTOCOL_VERSION, "project_id": "tropa",
               "ops": [{"net-id": 1}]}
        with open(os.path.join(inbox, "ops-bad.json"), "w", encoding="utf-8") as f:
            json.dump(env, f)
        rep = d.tick()  # не падает
        self.assertEqual(rep["imported"], 0)
        self.assertTrue(os.path.exists(os.path.join(inbox, "ops-bad.json.bad.json")))
        self.assertFalse(os.path.exists(os.path.join(inbox, "ops-bad.json")))

    def test_foreign_envelope_quarantined(self):
        d = self._open()
        env = {"protocol": PROTOCOL_VERSION, "project_id": "chuzhoy",
               "ops": [_move_op("cf", G1, "zed", 1.0, 2.0)]}
        with self.assertRaises(ValueError):
            import_envelope(d.store, env, project_id="tropa")
        self.assertIsNone(d.store.get_operation("cf"))  # ничего не вставлено

    # --- живая перезагрузка ---

    def test_live_reload_picks_up_poll_pins_identity(self):
        d = self._open()
        path = os.path.join(self.dir, "accollab.json")
        cfg = load_config(path)
        cfg["poll_s"] = 42
        cfg["author"] = "hacker"  # личность — только через рестарт
        save_config(path, cfg)
        d.tick()
        self.assertEqual(d.cfg["poll_s"], 42)
        self.assertEqual(d.cfg["author"], "anna")

    # --- heartbeat ---

    def test_heartbeat_broadcasts_and_throttles(self):
        d = self._open()
        locks_mod.acquire(d.store, G1, "anna", "soft", ttl_s=20)
        d.heartbeat_own_locks()
        first = d.store.list_outbox()
        self.assertEqual(len(first), 1)  # соседям уехала операция
        d.heartbeat_own_locks()
        self.assertEqual(d.store.list_outbox(), first)  # троттлинг: дубля нет

    def test_status_locks_full_guid(self):
        d = self._open()
        locks_mod.acquire(d.store, G1, "anna", "hard", ttl_s=60)
        d.tick()
        with open(os.path.join(self.dir, "status.json"), encoding="utf-8") as f:
            st = json.load(f)
        self.assertEqual(st["locks"][0]["guid"], G1)  # полный, для /show

    # --- применение ---

    def test_apply_stops_on_archicad_error_keeps_order(self):
        d = self._open()
        d.store.insert_operation(_move_op("c1", G1, "boris", 10.0, 12.0))
        d.store.insert_operation(_move_op("c2", G1, "boris", 12.0, 14.0))

        class _Dead:
            def get_details(self, guids):
                raise ArchicadError(0, "Archicad spit")

        out = d.apply_pending(_Dead())
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["status"], "ERROR-archicad")
        self.assertEqual(d.store.get_operation("c1")["applied"], 0)
        self.assertEqual(d.store.get_operation("c2")["applied"], 0)  # порядок цел

    def test_force_apply_skips_base_check_only(self):
        conn = FakeConn({G1: 999.0})  # base врёт
        d = self._open()
        d.store.insert_operation(_move_op("c1", G1, "boris", 10.0, 12.0))
        op = d.store.get_operation("c1")
        with self.assertRaises(BaseMismatchError):
            apply_operation(conn, d.store, dict(op))
        # Человек решил: чужая дельта (+2) применяется к нашему состоянию.
        rep = apply_operation(conn, d.store, dict(op), force=True)
        self.assertTrue(rep.get("forced"))
        self.assertEqual(len(conn.moves), 1)
        self.assertEqual(d.store.get_operation("c1")["applied"], 1)

    def test_no_echo_after_remote_apply(self):
        from accollab.watcher import Watcher
        conn = FakeConn({G1: 10.0})
        d = self._open()
        snap = Watcher(conn, d.store, "tropa", "anna").take_snapshot()
        d.store.save_snapshot(snap["taken_at"], snap["count"],
                              json.dumps(snap["items"]))
        d.store.insert_operation(_move_op("c1", G1, "boris", 10.0, 12.0))
        rep = apply_operation(conn, d.store, dict(d.store.get_operation("c1")))
        self.assertNotIn("already_applied", rep)
        poll = Watcher(conn, d.store, "tropa", "anna").poll_and_record()
        self.assertEqual(poll["modified"], [])  # эха нет
        self.assertEqual(poll["ops"], [])
        self.assertEqual(d.store.list_outbox(), [])

    def test_readback_mismatch_blocks_receipt(self):
        class _Crooked(FakeConn):
            def tapir(self, name, params=None):
                for item in params["elementsWithMoveVectors"]:
                    g = item["elementId"]["guid"]
                    self.coords[g] += 999.0  # сдвинул не туда
                    self.moves.append((g, {"x": 999.0}))
                return {"executionResults": [{"success": True}]}

        conn = _Crooked({G1: 10.0})
        d = self._open()
        d.store.insert_operation(_move_op("c1", G1, "boris", 10.0, 12.0))
        with self.assertRaises(ArchicadError):
            apply_operation(conn, d.store, dict(d.store.get_operation("c1")))
        self.assertEqual(d.store.get_operation("c1")["applied"], 0)  # квитанции нет

    def test_already_applied_recovery(self):
        conn = FakeConn({G1: 12.0})  # Archicad уже сдвинул, квитанция потеряна
        d = self._open()
        d.store.insert_operation(_move_op("c1", G1, "boris", 10.0, 12.0))
        rep = apply_operation(conn, d.store, dict(d.store.get_operation("c1")))
        self.assertTrue(rep.get("already_applied"))
        self.assertEqual(conn.moves, [])  # второй раз не двигаем
        self.assertEqual(d.store.get_operation("c1")["applied"], 1)
        self.assertEqual(d.store.list_conflicts(status="open"), [])

    def test_unsupported_not_consumed_no_spam(self):
        conn = FakeConn({G1: 10.0})
        d = self._open()
        op = _move_op("c9", G1, "boris", 10.0, 12.0)
        op["op"] = "create"  # applier не умеет create
        d.store.insert_operation(op)
        for _ in range(2):  # два тика подряд
            out = d.apply_pending(conn)
            self.assertEqual(out[0]["status"], "UNSUPPORTED")
        self.assertEqual(d.store.get_operation("c9")["applied"], 0)  # не съели молча
        self.assertEqual(d.store.list_conflicts(status="open"), [])  # и не заспамили

    def test_checkpoint_failure_blocks_apply(self):
        mock_srv, mock_port = mock_mod.start_mock()
        self.addCleanup(mock_srv.shutdown)
        self.addCleanup(mock_srv.server_close)
        daemon_mod.scan_archicad = self.real_scan  # Archicad ЕСТЬ (мок)
        d = self._open()
        d.store.insert_operation(_move_op("c1", G1, "boris", 10.0, 12.0))
        path = os.path.join(self.dir, "accollab.json")
        cfg = load_config(path)
        cfg["auto_checkpoint"] = True
        cfg["archicad_port"] = mock_port  # пин: живой релоад читает файл
        save_config(path, cfg)

        real_cp = daemon_mod.cp_create
        def _boom(*a, **k):
            raise RuntimeError("disk poln")
        daemon_mod.cp_create = _boom
        self.addCleanup(setattr, daemon_mod, "cp_create", real_cp)
        rep = d.tick()  # страховка сломана → чужие НЕ применяем, ошибка видна
        self.assertEqual(rep["applied"], [])
        self.assertEqual(d.store.get_operation("c1")["applied"], 0)
        self.assertTrue(any(e["where"] == "apply" for e in rep["errors"]))


if __name__ == "__main__":
    unittest.main()
