"""Тесты Telegram-транспорта: roundtrip, куски, курсор, 429, ошибки."""
import json
import os
import sys
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from accollab.telegram_transport import (  # noqa: E402
    TelegramError, TelegramTransport, check_body, merge_parts, prune_pending,
    sign_body)


class FakeBotAPI(BaseHTTPRequestHandler):
    token = "TESTTOKEN"
    messages = []  # тексты
    fail_429_once = False

    def log_message(self, *a):
        pass

    def _send(self, obj, code=200):
        data = json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        parts = self.path.strip("/").split("/")
        if len(parts) != 2 or parts[0] != "botTESTTOKEN":
            return self._send({"ok": False, "description": "bad token"}, 401)
        method = parts[1]
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
        if method == "sendMessage":
            if FakeBotAPI.fail_429_once:
                FakeBotAPI.fail_429_once = False
                return self._send({"ok": False, "description": "slow down",
                                   "parameters": {"retry_after": 0}}, 429)
            FakeBotAPI.messages.append(body.get("text", ""))
            return self._send({"ok": True, "result": {"message_id": len(FakeBotAPI.messages)}})
        if method == "getUpdates":
            off = body.get("offset", 0)
            ups = [{"update_id": i + 1,
                    "channel_post": {"message_id": i + 1, "text": m}}
                   for i, m in enumerate(FakeBotAPI.messages) if i + 1 >= off]
            return self._send({"ok": True, "result": ups})
        return self._send({"ok": False, "description": "unknown"}, 404)


def start_fake():
    FakeBotAPI.messages = []
    FakeBotAPI.fail_429_once = False
    srv = ThreadingHTTPServer(("127.0.0.1", 0), FakeBotAPI)
    Thread(target=srv.serve_forever, daemon=True).start()
    return srv, "http://127.0.0.1:%d" % srv.server_address[1]


def op(cid):
    return {"change_id": cid, "author": "anna", "op": "modify", "kind": "primary",
            "after_json": "x" * 100}


class TelegramTest(unittest.TestCase):
    def test_roundtrip(self):
        srv, base = start_fake()
        try:
            a = TelegramTransport("TESTTOKEN", "@chan", "anna", api_base=base)
            b = TelegramTransport("TESTTOKEN", "@chan", "boris", api_base=base)
            r = a.push([op("c1"), op("c2")])
            self.assertEqual(r["messages"], 1)
            texts, cursor = b.fetch_raw(0)
            self.assertEqual(len(texts), 1)
            pending = {}
            ready = merge_parts(pending, texts)
            self.assertEqual(len(ready), 1)
            batch = json.loads(ready[0][1])
            self.assertEqual(batch["from"], "anna")
            self.assertEqual([o["change_id"] for o in batch["ops"]], ["c1", "c2"])
            # курсор: повторный fetch с курсором пуст
            texts2, _ = b.fetch_raw(cursor)
            self.assertEqual(texts2, [])
        finally:
            srv.shutdown()
            srv.server_close()

    def test_chunking(self):
        srv, base = start_fake()
        try:
            a = TelegramTransport("TESTTOKEN", "@chan", "anna", api_base=base)
            big = {"change_id": "big", "after_json": "y" * 8000}
            r = a.push([big])
            self.assertGreater(r["messages"], 1)
            # эмулируем приём по частям вразбивку
            texts, _ = a.fetch_raw(0)
            pending = {}
            first = merge_parts(pending, texts[:1])
            self.assertEqual(first, [])  # неполная партия не готова
            rest = merge_parts(pending, texts[1:])
            self.assertEqual(len(rest), 1)
            batch = json.loads(rest[0][1])
            self.assertEqual(batch["ops"][0]["after_json"], "y" * 8000)
        finally:
            srv.shutdown()
            srv.server_close()

    def test_retry_429(self):
        srv, base = start_fake()
        try:
            FakeBotAPI.fail_429_once = True
            a = TelegramTransport("TESTTOKEN", "@chan", "anna", api_base=base)
            r = a.push([op("c1")])  # первый вызов 429, повтор успех
            self.assertEqual(r["messages"], 1)
            self.assertEqual(len(FakeBotAPI.messages), 1)
        finally:
            srv.shutdown()
            srv.server_close()

    def test_bad_token(self):
        srv, base = start_fake()
        try:
            a = TelegramTransport("WRONG", "@chan", "anna", api_base=base)
            with self.assertRaises(TelegramError):
                a.push([op("c1")])
        finally:
            srv.shutdown()
            srv.server_close()

    def test_garbage_ignored(self):
        pending = {}
        ready = merge_parts(pending, ["privet", "ACCOLLAB broken", "ACCOLLAB b x/y\nz"])
        self.assertEqual(ready, [])
        self.assertEqual(pending, {})

    def test_team_interleaved_writers(self):
        srv, base = start_fake()
        try:
            writers = [TelegramTransport("TESTTOKEN", "@chan", "dev%d" % i, api_base=base)
                       for i in range(4)]
            for i, w in enumerate(writers):
                w.push([{"change_id": "t%d" % i, "pad": "z" * 4000}])  # 2 куска каждый
            reader = TelegramTransport("TESTTOKEN", "@chan", "reader", api_base=base)
            texts, _ = reader.fetch_raw(0)
            self.assertEqual(len(texts), 8)  # 4 партии × 2 куска, вперемешку
            pending = {}
            ready = merge_parts(pending, texts)
            self.assertEqual(len(ready), 4)
            authors = sorted(json.loads(b)["from"] for _, b in ready)
            self.assertEqual(authors, ["dev0", "dev1", "dev2", "dev3"])
            self.assertEqual(pending, {})
        finally:
            srv.shutdown()
            srv.server_close()

    def test_prune_stale_partials(self):
        pending = {"stuck": {"n": 3, "parts": {1: "a"}, "ts": 1000.0}}
        self.assertEqual(prune_pending(pending, max_age_s=3600, now=2000.0), 0)
        self.assertEqual(prune_pending(pending, max_age_s=3600, now=5000.0), 1)
        self.assertEqual(pending, {})

    def test_signing(self):
        body = {"from": "anna", "ops": [{"change_id": "c1"}]}
        signed = sign_body(body, "sekret")
        import json as _json
        self.assertTrue(check_body(_json.dumps(signed), "sekret"))
        forged = dict(signed)
        forged["ops"] = [{"change_id": "evil"}]
        self.assertFalse(check_body(_json.dumps(forged), "sekret"))  # подмена видна
        self.assertFalse(check_body(_json.dumps(body), "sekret"))  # без подписи нельзя
        self.assertTrue(check_body(_json.dumps(body), ""))  # без секрета всё можно
        # конец в конец через транспорт
        srv, base = start_fake()
        try:
            a = TelegramTransport("TESTTOKEN", "@chan", "anna", api_base=base)
            a.push([{"change_id": "c1"}], secret="sekret")
            texts, _ = a.fetch_raw(0)
            pending = {}
            ready = merge_parts(pending, texts)
            self.assertTrue(check_body(ready[0][1], "sekret"))
            self.assertFalse(check_body(ready[0][1], "chuzhoy"))
        finally:
            srv.shutdown()
            srv.server_close()


if __name__ == "__main__":
    unittest.main()
