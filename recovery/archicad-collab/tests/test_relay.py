"""Тесты ретранслятора: push/fetch, курсоры, дедуп, секрет, персистентность."""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from accollab.relay import RelayClient, RelayError, start_server  # noqa: E402


def op(cid, author="anna"):
    return {"change_id": cid, "author": author, "op": "modify", "kind": "primary"}


class RelayTest(unittest.TestCase):
    def test_push_fetch_cursor_dedup(self):
        srv, port = start_server()
        try:
            a = RelayClient("http://127.0.0.1:%d" % port, "tropa", "anna")
            b = RelayClient("http://127.0.0.1:%d" % port, "tropa", "boris")
            r = a.push([op("c1"), op("c2")])
            self.assertTrue(r["ok"])
            self.assertEqual(r["stored"], 2)
            f = b.fetch(0)
            self.assertEqual([o["change_id"] for o in f["ops"]], ["c1", "c2"])
            self.assertEqual(f["cursor"], 2)
            self.assertEqual(b.fetch(2)["ops"], [])
            # повторный push тех же — дедуп
            r2 = a.push([op("c1"), op("c2"), op("c3")])
            self.assertEqual(r2["stored"], 1)
            self.assertEqual([o["change_id"] for o in b.fetch(2)["ops"]], ["c3"])
            st = a.status()
            self.assertEqual(st["projects"]["tropa"], 3)
        finally:
            srv.shutdown(); srv.server_close()

    def test_secret(self):
        srv, port = start_server(secret="shhh")
        try:
            good = RelayClient("http://127.0.0.1:%d" % port, "tropa", "anna", secret="shhh")
            bad = RelayClient("http://127.0.0.1:%d" % port, "tropa", "boris",
                              secret="ne-ugadal")
            good.push([op("c1")])
            with self.assertRaises(RelayError):
                bad.push([op("c2")])
            with self.assertRaises(RelayError):
                bad.fetch(0)
            self.assertEqual(len(good.fetch(0)["ops"]), 1)
        finally:
            srv.shutdown(); srv.server_close()

    def test_persistence(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = os.path.join(tmp, "relay.jsonl")
            srv, port = start_server(data_path=data)
            try:
                c = RelayClient("http://127.0.0.1:%d" % port, "tropa", "anna")
                c.push([op("c1")])
            finally:
                srv.shutdown(); srv.server_close()
            srv2, port2 = start_server(data_path=data)
            try:
                c2 = RelayClient("http://127.0.0.1:%d" % port2, "tropa", "boris")
                self.assertEqual([o["change_id"] for o in c2.fetch(0)["ops"]], ["c1"])
            finally:
                srv2.shutdown(); srv2.server_close()

    def test_unreachable(self):
        c = RelayClient("http://127.0.0.1:9", "tropa", "anna", timeout=2)
        with self.assertRaises(RelayError):
            c.push([op("c1")])


if __name__ == "__main__":
    unittest.main()
