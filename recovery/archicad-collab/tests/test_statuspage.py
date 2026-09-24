"""Тесты страницы статуса: GET, POST sync/checkpoint/resolve."""
import json
import os
import re
import sys
import tempfile
import unittest
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import accollab.daemon as daemon_mod  # noqa: E402
from accollab.daemon import Daemon  # noqa: E402
from accollab.store import element_checksum  # noqa: E402
from accollab.statuspage import start_server  # noqa: E402
import mock_archicad as mock_mod  # noqa: E402
from test_daemon import make_cfg  # noqa: E402
from test_sync import G1  # noqa: E402


def get(url):
    with urllib.request.urlopen(url, timeout=10) as r:
        return r.status, r.read().decode("utf-8")


def _csrf(url):
    """Токен со страницы (end-to-end: инъекция в _send тоже проверяется)."""
    base = url.rsplit("/", 1)[0] + "/"
    _, body = get(base)
    m = re.search(r'name="csrf" value="([0-9a-f]{64})"', body)
    return m.group(1) if m else ""


def post(url, fields):
    fields = dict(fields)
    fields.setdefault("csrf", _csrf(url))
    data = urllib.parse.urlencode(fields).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    with urllib.request.urlopen(req, timeout=15) as r:
        return r.status, r.read().decode("utf-8")


class StatusPageTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.real_scan = daemon_mod.scan_archicad
        daemon_mod.scan_archicad = lambda **kw: (None, None)  # Archicad нет
        self.d = Daemon(make_cfg(self.tmp.name, "anna"))
        self.srv, self.port = start_server(self.d)
        self.base = "http://127.0.0.1:%d" % self.port

    def tearDown(self):
        self.srv.shutdown()
        self.srv.server_close()
        self.d.store.close()
        daemon_mod.scan_archicad = self.real_scan
        self.tmp.cleanup()

    def test_get_root(self):
        code, body = get(self.base + "/")
        self.assertEqual(code, 200)
        self.assertIn("Синхронизировать", body)
        self.assertIn("anna", body)

    def test_post_sync_runs_tick(self):
        code, _ = post(self.base + "/sync", {})
        self.assertEqual(code, 200)  # редирект на / уже обработан
        import time as _time
        st, deadline = None, _time.time() + 30
        while _time.time() < deadline:  # тик идёт в фоне — ждём файл
            try:
                with open(os.path.join(self.tmp.name, "status.json"),
                          encoding="utf-8") as f:
                    st = json.load(f)
                break
            except (OSError, ValueError):
                _time.sleep(0.2)
        self.assertIsNotNone(st, "fonovyy tik ne zapisal status.json")
        self.assertEqual(st["author"], "anna")
        self.assertIsNone(st["archicad_port"])
        # повторный POST не роняет (single-flight или новый тик — оба ок)
        code, _ = post(self.base + "/sync", {})
        self.assertEqual(code, 200)

    def test_resolve_flow(self):
        cid = self.d.store.record_conflict(G1, "ours1", "theirs1", note="code:CONFLICT-base")
        code, body = get(self.base + "/")
        self.assertIn("CONFLICT-base", body)
        code, _ = post(self.base + "/resolve", {"conflict_id": cid, "text": "beru svoyo"})
        self.assertEqual(code, 200)
        rows = self.d.store.list_conflicts(status="open")
        self.assertEqual(rows, [])

    def test_checkpoint_without_archicad(self):
        code, _ = post(self.base + "/checkpoint", {"name": "t1"})
        self.assertEqual(code, 200)  # не падает, покажет STOP на странице
        code, body = get(self.base + "/")
        self.assertEqual(code, 200)


    def test_show_and_ask_flow(self):
        mock_srv, mock_port = mock_mod.start_mock()
        self.addCleanup(mock_srv.shutdown)
        self.addCleanup(mock_srv.server_close)
        self.d.cfg["archicad_port"] = mock_port  # пин на мок
        daemon_mod.scan_archicad = self.real_scan  # вернуть настоящий скан
        mock_mod.Handler.calls.clear()
        code, body = post(self.base + "/show", {"guid": G1})
        self.assertEqual(code, 200)
        self.assertIn("pokazan v Archicad", body)
        names = [n for n, _p in mock_mod.Handler.calls]
        self.assertIn("FitInWindow", names)
        # Вставляем НАСТОЯЩУЮ чужую операцию: /ask btn2 должен её применить.
        fg = mock_mod.FAKE_GUIDS[0]
        conn_probe, _port = self.d.scan()
        full = conn_probe.get_details([fg])[0]
        before_full = json.loads(json.dumps(full))  # живой слепок — как у вотчера
        after_full = json.loads(json.dumps(full))
        for pt in ("begCoordinate", "endCoordinate"):
            # round как у мока: мок хранит round(x,4) — after обязан совпасть бит в бит
            after_full["details"][pt]["x"] = round(
                before_full["details"][pt]["x"] + 1.0, 4)
        before = {"type": full.get("type", "Beam"),
                  "checksum": element_checksum(before_full), "details": before_full}
        after = {"type": before["type"],
                 "checksum": element_checksum(after_full), "details": after_full}
        self.d.store.insert_operation(
            {"change_id": "theirs1", "project_id": "tropa", "element_guid": fg,
             "author": "boris", "wall_time": "2026-09-17T00:00:00+00:00",
             "lamport": 1, "kind": "primary", "op": "modify",
             "before_json": json.dumps(before), "after_json": json.dumps(after)})
        cid = self.d.store.record_conflict(fg, "ours1", "theirs1",
                                           note="code:CONFLICT-base")
        mock_mod.Handler.alert_button = 2
        try:
            code, body = post(self.base + "/ask", {"conflict_id": cid})
        finally:
            mock_mod.Handler.alert_button = 1
        self.assertEqual(code, 200)
        self.assertEqual(self.d.store.list_conflicts(status="open"), [])
        self.assertIn("CHUZHOE", body)
        self.assertEqual(self.d.store.get_operation("theirs1")["applied"], 1)

    def test_settings_flow(self):
        code, body = get(self.base + "/settings")
        self.assertEqual(code, 200)
        self.assertIn("accollab.json", body)
        code, _ = post(self.base + "/settings", {"author": "boris", "poll_s": "7",
                                                 "telegram_bot_token": ""})
        self.assertEqual(code, 200)
        with open(os.path.join(self.tmp.name, "accollab.json"), encoding="utf-8") as f:
            cfg = json.load(f)
        self.assertEqual(cfg["author"], "boris")
        self.assertEqual(cfg["poll_s"], 7)


    def test_settings_bools_and_fields(self):
        code, body = get(self.base + "/settings")
        self.assertEqual(code, 200)
        for key in ("serve_port", "relay_timeout", "telegram_timeout", "lock_ttl_s",
                    "bim_rules", "own_color", "presence_enabled", "auto_checkpoint",
                    "telegram_notify", "outbox_dir", "inbox_dir"):
            self.assertIn(key, body)
        import urllib.request as _req
        # галка вкл (hidden 0 + checkbox 1) и число
        data = ("presence_enabled=0&presence_enabled=1&auto_checkpoint=0&poll_s=abc"
                "&csrf=" + _csrf(self.base + "/settings")).encode("utf-8")
        r = _req.Request(self.base + "/settings", data=data, method="POST")
        with _req.urlopen(r, timeout=15) as resp:
            body = resp.read().decode("utf-8")
        with open(os.path.join(self.tmp.name, "accollab.json"), encoding="utf-8") as f:
            cfg = json.load(f)
        self.assertTrue(cfg["presence_enabled"])
        self.assertFalse(cfg["auto_checkpoint"])
        self.assertEqual(cfg["poll_s"], 5)  # 'abc' отвергнуто, старое цело
        self.assertIn("ne chislo", body)


    def test_tabs(self):
        code, body = get(self.base + "/")
        self.assertEqual(code, 200)
        for t in ("?tab=status", "?tab=locks", "?tab=conflicts", "?tab=checkpoints"):
            self.assertIn(t, body)
        self.assertNotIn("?tab=settings", body)  # настройки — только колесико
        self.assertIn('href="/settings"', body)
        self.assertIn('id="pane-status"', body)
        self.assertNotIn('id="more"', body)  # всё на панели — меню пусто
        code, body = get(self.base + "/?tab=locks")
        self.assertEqual(code, 200)
        self.assertIn('<a href="/?tab=locks" data-tab="locks" class="on">', body)
        # мусорная вкладка -> статус
        code, body = get(self.base + "/?tab=nope")
        self.assertIn('<div class="pane on" id="pane-status">', body)

    def test_layout_pin_unpin(self):
        code, _ = post(self.base + "/layout", {"tab": "conflicts", "to": "menu"})
        self.assertEqual(code, 200)
        ui_path = os.path.join(self.tmp.name, "ui.json")
        with open(ui_path, encoding="utf-8") as f:
            self.assertNotIn("conflicts", json.load(f)["pinned"])
        code, body = get(self.base + "/")
        self.assertIn('id="more"', body)  # меню появилось
        self.assertNotIn('data-tab="conflicts"', body)  # с панели убрана
        self.assertIn('<a href="/?tab=conflicts">', body)  # но живёт в меню
        code, body = get(self.base + "/?tab=conflicts")
        self.assertIn('id="pane-conflicts"', body)  # прямая ссылка работает
        code, _ = post(self.base + "/layout", {"tab": "conflicts", "to": "main"})
        self.assertEqual(code, 200)
        code, body = get(self.base + "/")
        self.assertNotIn('id="more"', body)
        self.assertIn('data-tab="conflicts"', body)
        # мусор игнорируется
        code, _ = post(self.base + "/layout", {"tab": "nope", "to": "main"})
        self.assertEqual(code, 200)
        with open(ui_path, encoding="utf-8") as f:
            self.assertEqual(len(json.load(f)["pinned"]), 4)


if __name__ == "__main__":
    unittest.main()
