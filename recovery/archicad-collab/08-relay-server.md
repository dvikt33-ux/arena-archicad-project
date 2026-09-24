# ACCOLLAB — свой ретранслятор на бесплатном сервере

Машины А и Б видят только интернет, поэтому операции едут через
ретранслятор — тупой склад на нашем сервере (хранит, отдаёт, в конфликты
не лезет). Сервер: 1 файл relay.py, только Python, ~50 МБ памяти.

## 0. Заказ сервера (по скриншоту — всё верно)

- Образ: Ubuntu 24.04 LTS (оставить как выбрано).
- Тариф: Free Tier C1-M1-D10 (1 CPU / 1 ГБ / 10 ГБ — ретранслятору хватит
  с огромным запасом).
- Регион: любой российский (Москва — ок).
- Публичный IP x1 — ОБЯЗАТЕЛЬНО (без него машины не достучатся).
- "Резервное копирование" — если платное, НЕ включать (наш файл весит
  килобайты, скопируем вручную).
- Мелкий шрифт: бесплатно 3 месяца, нужна идентификация аккаунта и
  положительный баланс (киньте рублей 100). Через 3 месяца — переезд
  копированием одного файла (шаг 7).

Заказали → в панели сервера нашли **публичный IP** и кнопку веб-консоли
(или SSH). Дальше все команды — в консоли сервера под root.

## 1. Данные (вписать IP!)

- IP сервера: 195.19.202.100 (Magenta Seaborgium, ID 7982241)
- Адрес ретранслятора: http://195.19.202.100:8471
- Общий секрет проекта: b8fe90f8543f419ce6b1b28ad68bce7b
  (потом вписать его в настройки на ОБЕИХ машинах).

## 2. Установка файла (два варианта)

Вариант А — быстрый (ссылка живёт около часа, ставить СРАЗУ):

    mkdir -p /root/accollab && cd /root/accollab
    curl -sL "https://tmpfiles.org/dl/1789214145.6ef54443ebbb86cf/wzwDPlnLkxL1/accollab-relay.py" -o relay.py
    sha256sum relay.py
    # должно быть: c76fb03ade2d642342be623896a3b64cf8e0f48b4cf39ae0912a3e343a1f7a6b

Вариант Б — вечный (если ссылка протухла): вставить файл целиком.
Скопируйте ВЕСЬ текст между строками PYEOF ниже и выполните в консоли:

    mkdir -p /root/accollab && cd /root/accollab
    cat > relay.py << 'PYEOF'
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
PYEOF
    python3 relay.py --help > /dev/null && echo "relay.py na meste"

## 3. Автозапуск (переживёт перезагрузку сервера)

    cat > /etc/systemd/system/accollab-relay.service << 'SVCEOF'
    [Unit]
    Description=ACCOLLAB relay
    After=network-online.target
    Wants=network-online.target

    [Service]
    ExecStart=/usr/bin/python3 /root/accollab/relay.py --port 8471 --secret b8fe90f8543f419ce6b1b28ad68bce7b --data /root/accollab/relay.jsonl
    Restart=always
    RestartSec=5

    [Install]
    WantedBy=multi-user.target
    SVCEOF
    systemctl daemon-reload
    systemctl enable --now accollab-relay
    sleep 2
    curl -s localhost:8471/status; echo
    # должно быть: {"ok": true, "projects": {}}

## 4. Открыть порт наружу

- В панели провайдера (раздел "Сеть"/"Firewall") разрешить TCP 8471.
- Если на сервере включён ufw:  ufw allow 8471/tcp
- Проверка С ДОМА (в браузере): http://195.19.202.100:8471/status
  Должно показать: {"ok": true, "projects": {}}

## 5. Настройки на машинах А и Б (обе!)

На странице статуса (serve) → колесико → раздел Relay:

- relay_url = http://195.19.202.100:8471
- relay_secret = b8fe90f8543f419ce6b1b28ad68bce7b  (тот же секрет!)
- Сохранить, перезапустить serve/демона.

## 6. Сквозная проверка

1. На А: сделать маленькую правку в Archicad, тик (кнопка / once).
2. В браузере: http://195.19.202.100:8471/status — в projects.tropa должно быть > 0.
3. На Б: тик → чужая правка применилась (APPLIED).
4. Обратно так же.

## 7. Важно

- Лог операций: /root/accollab/relay.jsonl (дописывается, переживает
  рестарт). Иногда копируйте его себе: scp root@IP:/root/accollab/relay.jsonl .
- Если сервер умер до того, как Б забрал операции — они потеряны
  (машина А свою очередь уже очистила). Для старта acceptable, дальше
  добавим подтверждения доставки.
- Через 3 месяца: поднять новый сервер, перенести relay.py + relay.jsonl,
  поменять relay_url на машинах. Всё.
- Смена секрета: поменять --secret в service-файле + на обеих машинах,
  systemctl restart accollab-relay.

Файл: relay.py (sha256 c76fb03a..., 8038 байт, только stdlib).
Инструкция сгенерена 2026-09-12, годна пока не поменялся протокол relay.
