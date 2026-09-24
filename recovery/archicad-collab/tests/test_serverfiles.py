"""Генератор писем с сервера: файлы годные, демон применяет их в мок.

Сквозная репетиция живого теста: письма строятся из мок-Archicad,
демон тикает baseline, письма по одному уходят в inbox и применяются
(APPLIED, координаты едут, конфликтов нет).
"""
import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))

import mock_archicad as mock_mod  # noqa: E402
from accollab.daemon import Daemon  # noqa: E402
from coords import main as coords_main  # noqa: E402
from make_server_files import main as gen_main  # noqa: E402
from test_daemon import make_cfg  # noqa: E402


class ServerFilesTest(unittest.TestCase):
    def test_generate_and_apply_three_letters(self):
        mock_srv, mock_port = mock_mod.start_mock()
        self.addCleanup(mock_srv.shutdown)
        self.addCleanup(mock_srv.server_close)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        home = os.path.join(tmp.name, "a")
        os.makedirs(home)
        cfg_path = make_cfg(home, "anna", archicad_port=mock_port,
                            archicad_timeout=10)
        out = os.path.join(home, "server-files")
        code = gen_main(["--config", cfg_path, "--out", out,
                         "--moves", "3", "--step", "0.5"])
        self.assertEqual(code, 0)
        files = sorted(f for f in os.listdir(out) if f.endswith(".json"))
        self.assertEqual(files, ["server-01.json", "server-02.json",
                                 "server-03.json"])
        guids = []
        for name in files:
            with open(os.path.join(out, name), encoding="utf-8") as f:
                env = json.load(f)
            self.assertEqual(env["protocol"], "1.0")
            self.assertEqual(env["project_id"], "tropa")
            self.assertEqual(len(env["ops"]), 1)
            self.assertEqual(env["ops"][0]["author"], "boris")
            guids.append(env["ops"][0]["element_guid"])
        self.assertEqual(len(set(guids)), 3)  # каждый двигает свой

        d = Daemon(cfg_path)
        self.addCleanup(d.store.close)
        inbox = os.path.join(home, "inbox")
        rep = d.tick()
        self.assertEqual(rep["watch"].get("ops", []), [])  # baseline
        state = mock_mod.Handler.state[mock_port]
        for name, guid in zip(files, guids):
            before = dict(state["beg"][guid])
            shutil.copy(os.path.join(out, name), os.path.join(inbox, name))
            rep = d.tick()
            applied = [r for r in rep["applied"] if r["status"] == "APPLIED"]
            self.assertEqual(len(applied), 1, rep)
            self.assertAlmostEqual(state["beg"][guid]["x"], before["x"] + 0.5)
        self.assertEqual(d.store.list_conflicts(status="open"), [])

    def test_coords_probe_save_diff(self):
        mock_srv, mock_port = mock_mod.start_mock()
        self.addCleanup(mock_srv.shutdown)
        self.addCleanup(mock_srv.server_close)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        home = os.path.join(tmp.name, "a")
        os.makedirs(home)
        cfg_path = make_cfg(home, "anna", archicad_port=mock_port,
                            archicad_timeout=10)
        self.assertEqual(coords_main(["--probe", "--config", cfg_path]), 0)
        g1 = mock_mod.FAKE_GUIDS[0]
        a = os.path.join(home, "a.json")
        b = os.path.join(home, "b.json")
        self.assertEqual(coords_main(["--save", a, "--config", cfg_path,
                                      "--guids", g1]), 0)
        with open(a, encoding="utf-8") as f:
            self.assertEqual(list(json.load(f)), [g1])
        mock_mod.Handler.state[mock_port]["beg"][g1]["x"] += 0.5
        self.assertEqual(coords_main(["--save", b, "--config", cfg_path,
                                      "--guids", g1]), 0)
        import io
        from contextlib import redirect_stdout
        buf = io.StringIO()
        with redirect_stdout(buf):
            self.assertEqual(coords_main(["--diff", a, b]), 0)
        self.assertIn("dx=0.5", buf.getvalue())


if __name__ == "__main__":
    unittest.main()
