"""Ретранслятор операций для синхронизации через интернет (Фаза A-5).

Машины без общей сети гонят операции через этот сервер: push (отдать свои)
и fetch (забрать чужие, курсором since). Сервер тупой: хранит лог операций
по project_id, дедуплицирует по change_id, в конфликты не лезет.
Авторизация — общий секрет проекта (X-ACCOLLAB-SECRET), пустой = без защиты.

Запуск сервера:  python -m accollab.relay --port 8471 --secret XXX --data relay.jsonl
Только stdlib.
"""
import argparse
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from urllib.parse import urlparse, parse_qs
import urllib.request
import urllib.error


class RelayError(Exception):
    pass


class RelayLog:
    """Лог операций по проектам + курсоры. Потокобезопасность — GIL + короткие ops."""

    def __init__(self, data_path=""):
        self.data_path = data_path
        self.projects = {}  # project_id -> [op, ...]
        self.seen = {}  # project_id -> set(change_id)
        if data_path and os.path.exists(data_path):
            self._load()

    def push(self, project_id, ops):
        log = self.projects.setdefault(project_id, [])
        seen = self.seen.setdefault(project_id, set())
        fresh = 0
        for op in ops or []:
            cid = op.get("change_id")
            if not cid or cid in seen:
                continue
            seen.add(cid)
            log.append(op)
            fresh += 1
            if self.data_path:
                with open(self.data_path, "a", encoding="utf-8") as f:
                    f.write(json.dumps({"project_id": project_id, "op": op},
                                       ensure_ascii=False) + "\n")
        return {"stored": fresh, "cursor": len(log)}

    def fetch(self, project_id, since=0):
        log = self.projects.get(project_id, [])
        since = max(0, int(since))
        return {"ops": log[since:], "cursor": len(log)}

    def _load(self):
        with open(self.data_path, encoding="utf-8") as f:
            for line in f:
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                self.push(row.get("project_id", ""), [row.get("op", {})])


class _Handler(BaseHTTPRequestHandler):
    relay = None  # RelayLog
    secret = ""

    def log_message(self, *a):
        pass

    def _send(self, obj, code=200):
        data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _auth(self):
        if not _Handler.secret:
            return True
        return self.headers.get("X-ACCOLLAB-SECRET") == _Handler.secret

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/status":
            return self._send({"ok": True,
                               "projects": {k: len(v) for k, v in _Handler.relay.projects.items()}})
        if parsed.path == "/fetch":
            if not self._auth():
                return self._send({"ok": False, "error": "bad secret"}, 403)
            qs = parse_qs(parsed.query)
            project = qs.get("project", [""])[0]
            since = qs.get("since", ["0"])[0]
            try:
                res = _Handler.relay.fetch(project, since)
            except (ValueError, TypeError):
                return self._send({"ok": False, "error": "bad since"}, 400)
            res["ok"] = True
            return self._send(res)
        return self._send({"ok": False, "error": "unknown path"}, 404)

    def do_POST(self):
        if self.path != "/push":
            return self._send({"ok": False, "error": "unknown path"}, 404)
        if not self._auth():
            return self._send({"ok": False, "error": "bad secret"}, 403)
        try:
            length = int(self.headers.get("Content-Length", 0))
        except ValueError:
            length = 0
        if length > 50 * 1024 * 1024:
            return self._send({"ok": False, "error": "body too large"}, 413)
        try:
            body = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
        except ValueError:
            return self._send({"ok": False, "error": "bad json"}, 400)
        res = _Handler.relay.push(body.get("project_id", ""), body.get("ops", []))
        res["ok"] = True
        res["from"] = body.get("from", "")
        return self._send(res)


def start_server(port=0, secret="", data_path=""):
    """Поднять сервер в фоне. Возвращает (server, port). Порт 0 = случайный."""
    relay = RelayLog(data_path)
    _Handler.relay = relay
    _Handler.secret = secret
    server = ThreadingHTTPServer(("127.0.0.1", port), _Handler)
    Thread(target=server.serve_forever, daemon=True).start()
    return server, server.server_address[1]


class RelayClient:
    def __init__(self, base_url, project_id, author, secret="", timeout=30):
        self.base_url = base_url.rstrip("/")
        self.project_id = project_id
        self.author = author
        self.secret = secret
        self.timeout = timeout

    def _call(self, method, path, body=None):
        data = None
        headers = {"X-ACCOLLAB-SECRET": self.secret} if self.secret else {}
        if body is not None:
            data = json.dumps(body, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(self.base_url + path, data=data,
                                     headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            try:
                try:
                    err = json.loads(e.read().decode("utf-8"))
                except (ValueError, OSError):
                    err = {"error": "HTTP %d" % e.code}
            finally:
                e.close()
            raise RelayError("relay %s: %s" % (e.code, err.get("error", "?")))
        except Exception as e:  # noqa: BLE001 - сеть: заворачиваем всё
            raise RelayError("relay unreachable: %s" % str(e)[:150])

    def push(self, ops):
        res = self._call("POST", "/push", {"project_id": self.project_id,
                                           "from": self.author, "ops": ops or []})
        if not res.get("ok"):
            raise RelayError("push: %s" % res.get("error", "?"))
        return res

    def fetch(self, since=0):
        res = self._call("GET", "/fetch?project=%s&since=%d" % (self.project_id, since))
        if not res.get("ok"):
            raise RelayError("fetch: %s" % res.get("error", "?"))
        return res

    def status(self):
        return self._call("GET", "/status")


def main(argv=None):
    ap = argparse.ArgumentParser(description="ACCOLLAB relay server")
    ap.add_argument("--port", type=int, default=8471)
    ap.add_argument("--secret", default="")
    ap.add_argument("--data", default="relay.jsonl")
    ap.add_argument("--host", default="0.0.0.0")
    args = ap.parse_args(argv)
    relay = RelayLog(args.data)
    _Handler.relay = relay
    _Handler.secret = args.secret
    server = ThreadingHTTPServer((args.host, args.port), _Handler)
    print("relay on %s:%d (secret %s, data %s)" % (
        args.host, args.port, "ON" if args.secret else "OFF", args.data or "memory"))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
