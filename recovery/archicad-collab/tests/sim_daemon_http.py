"""Сквозная репетиция демона по настоящему HTTP.

Два mock Archicad на 19723/19724 (да, настоящие порты Archicad — песочница
позволяет), два демона с пином портов: baseline → сдвиг → файл → APPLIED →
сверка координат → lock-операция → комментарий → presence-подсветка.
Если порты заняты — честный SKIP (exit 2).

Запуск: cd <root> && python3 tests/sim_daemon_http.py
"""
import glob
import json
import os
import shutil
import sys
import urllib.request
from http.server import HTTPServer
from threading import Thread

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from mock_archicad import Handler  # noqa: E402
from accollab import locks  # noqa: E402
from accollab import comments  # noqa: E402
from accollab.daemon import Daemon, save_config  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
A = "/tmp/simh_A"
B = "/tmp/simh_B"
G1 = "11111111-1111-1111-1111-111111111111"
G2 = "22222222-2222-2222-2222-222222222222"


def post(port, command, params):
    env = {"command": command, "parameters": params}
    req = urllib.request.Request(
        "http://127.0.0.1:%d" % port, data=json.dumps(env).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode("utf-8"))


def tapir(port, name, params):
    return post(port, "API.ExecuteAddOnCommand", {
        "addOnCommandId": {"commandNamespace": "TapirCommand", "commandName": name},
        "addOnCommandParameters": params})


def beg(port, guid):
    r = tapir(port, "GetDetailsOfElements", {"elements": [{"elementId": {"guid": guid}}]})
    return r["result"]["addOnCommandResponse"]["detailsOfElements"][0]["details"]["begCoordinate"]


def move(port, guid, v):
    r = tapir(port, "MoveElements", {"elementsWithMoveVectors": [
        {"elementId": {"guid": guid}, "moveVector": v, "copy": False}]})
    assert r["result"]["addOnCommandResponse"].get("success") is True, r


def make_cfg(d, author, port):
    cfg = {"project_id": "tropa", "author": author, "store": "db.sqlite",
           "poll_s": 5, "outbox_dir": "outbox", "inbox_dir": "inbox",
           "relay_url": "", "relay_secret": "", "telegram_bot_token": "",
           "telegram_chat_id": "", "telegram_secret": "",
           "telegram_api_base": "https://api.telegram.org",
           "backup_dir": "", "backup_keep": 5, "archicad_port": port,
           "archicad_timeout": 10}
    path = os.path.join(d, "accollab.json")
    save_config(path, cfg)
    return path


def carry():
    files = sorted(glob.glob(os.path.join(A, "outbox", "*.json")))
    assert files, "outbox A pust!"
    for f in files:
        shutil.copy(f, os.path.join(B, "inbox", os.path.basename(f)))
        os.remove(f)  # понесли — как флешка
    return len(files)


def main():
    try:
        srvA = HTTPServer(("127.0.0.1", 19723), Handler)
        srvB = HTTPServer(("127.0.0.1", 19724), Handler)
    except OSError as e:
        print("SKIP: porty 19723/19724 zanyaty (%s)" % e)
        return 2
    Thread(target=srvA.serve_forever, daemon=True).start()
    Thread(target=srvB.serve_forever, daemon=True).start()
    shutil.rmtree(A, ignore_errors=True)
    shutil.rmtree(B, ignore_errors=True)
    os.makedirs(A, exist_ok=True)
    os.makedirs(os.path.join(B, "inbox"), exist_ok=True)
    da = Daemon(make_cfg(A, "anna", 19723))
    db = Daemon(make_cfg(B, "boris", 19724))
    try:
        # 1. baseline обоих
        assert da.tick()["watch"].get("ops", []) == []
        assert db.tick()["watch"].get("ops", []) == []
        print("1. baseline OK (oba demona, pin portov rabotaet)")
        # 2. сдвиг на A → файл → B
        move(19723, G1, {"x": 0.5, "y": 0, "z": 0})
        rep = da.tick()
        assert len(rep["watch"].get("ops", [])) == 1, rep
        assert carry() == 1
        rep = db.tick()
        assert rep["imported"] == 1, rep
        assert rep["applied"][0]["status"] == "APPLIED", rep
        assert beg(19723, G1) == beg(19724, G1)
        print("2. sdvig A->B cherez HTTP: APPLIED, koordinaty %s" % (beg(19724, G1),))
        # 3. hard-lock с A доезжает до B
        lease = locks.acquire(da.store, G2, "anna", mode="hard")
        op = locks.make_lock_op(G2, "anna", "hard", 20, lease)
        da.store.insert_operation(op)
        da.store.enqueue_outbox(op["change_id"])
        da.tick()
        carry()
        rep = db.tick()
        assert rep["applied"][0]["status"] == "LOCKED", rep
        row = locks.get(db.store, G2)
        assert row is not None and row["mode"] == "hard" and row["holder"] == "anna"
        print("3. hard-lock A->B: LOCKED")
        # 4. комментарий с A доезжает до B
        cid, cop = comments.add_local(da.store, G1, "anna", "prover kray")
        da.store.insert_operation(cop)
        da.store.enqueue_outbox(cop["change_id"])
        da.tick()
        carry()
        rep = db.tick()
        # Первым — heartbeat-продление лока из шага 3 (экспорт в тике идёт
        # раньше heartbeat, операция уехала следующим файлом — так задумано).
        assert [r["status"] for r in rep["applied"]] == ["LOCKED",
                                                         "COMMENT-APPLIED"], rep
        assert len(comments.list_for_element(db.store, G1)) == 1
        print("4. kommentariy A->B: COMMENT-APPLIED")
        # 5. presence-подсветка на B не роняет тик (мок отвечает success)
        rep = db.tick()
        assert "presence" in rep, rep
        assert rep["errors"] == [], rep["errors"]
        print("5. presence OK: %s" % (rep["presence"],))
        # 6. status.json на B боевой
        with open(os.path.join(B, "status.json"), encoding="utf-8") as f:
            st = json.load(f)
        assert st["archicad_port"] == 19724 and st["conflicts_open"] == 0
        assert any(r["holder"] == "anna" for r in st["locks"])
        print("6. status.json OK")
    finally:
        da.store.close()
        db.store.close()
        srvA.shutdown()
        srvB.shutdown()
        srvA.server_close()
        srvB.server_close()
    print("SIM-HTTP OK: demon polnostyu proshel po nastoyashchemu HTTP.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
