"""Репетиция понедельника: две «машины» = два mock Archicad на разных портах.

Сценарий: baseline на A → сдвиг на A → export → перенос ops.json →
применение на B (Y) → сверка координат A==B → повтор (дубль) →
конфликт base → отмена по N.

Запуск:  cd <root> && python3 tests/sim_two_machines.py
"""
import json
import os
import shutil
import subprocess
import sys
import urllib.request

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__))))
from mock_archicad import start_mock  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
A = "/tmp/simA"
B = "/tmp/simB"
G1 = "11111111-1111-1111-1111-111111111111"
G2 = "22222222-2222-2222-2222-222222222222"
G3 = "33333333-3333-3333-3333-333333333333"


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


def move(port, guid, v):
    r = tapir(port, "MoveElements", {"elementsWithMoveVectors": [
        {"elementId": {"guid": guid}, "moveVector": v, "copy": False}]})
    assert r["result"]["addOnCommandResponse"].get("success") is True, r
    return r


def beg(port, guid):
    r = tapir(port, "GetDetailsOfElements", {"elements": [{"elementId": {"guid": guid}}]})
    d = r["result"]["addOnCommandResponse"]["detailsOfElements"][0]
    return d["details"]["begCoordinate"]


def run(tool, cwd, port, args=(), inp=None):
    e = dict(os.environ, ACCOLLAB_PORT=str(port))
    p = subprocess.run([sys.executable, os.path.join(ROOT, "tools", tool), *args],
                       cwd=cwd, env=e, input=inp, capture_output=True, text=True)
    print("--- %s (port %d, cwd %s) rc=%d ---" % (tool, port, cwd, p.returncode))
    print(p.stdout)
    if p.returncode not in (0, 2):
        print("STDERR:", p.stderr)
    return p


def main():
    shutil.rmtree(A, ignore_errors=True)
    shutil.rmtree(B, ignore_errors=True)
    os.makedirs(A)
    os.makedirs(B)
    srvA, portA = start_mock()
    srvB, portB = start_mock()
    try:
        # 1. baseline на A
        r = run("ops_export.py", A, portA, ("testerA",))
        assert r.returncode == 0 and "BASELINE" in r.stdout, r.stdout
        # 2. сдвиг балки 1 на A (+0.5 по X)
        move(portA, G1, {"x": 0.5, "y": 0, "z": 0})
        # 3. export на A → 1 операция
        r = run("ops_export.py", A, portA, ("testerA",))
        assert r.returncode == 0 and "operaciy 1" in r.stdout, r.stdout
        # 4. перенос файла на B
        shutil.copy(os.path.join(A, "ops.json"), os.path.join(B, "ops.json"))
        # 5. применение на B (Y)
        r = run("ops_apply.py", B, portB, ("ops.json",), inp="Y\n")
        assert r.returncode == 0 and "APPLIED" in r.stdout, r.stdout + r.stderr
        # 6. сверка координат A == B
        ba, bb = beg(portA, G1), beg(portB, G1)
        assert ba == bb, (ba, bb)
        print("SVERKA: A == B (%s)" % (ba,))
        # 7. повтор того же файла → дубль, ничего не меняется
        r = run("ops_apply.py", B, portB, ("ops.json",), inp="Y\n")
        assert "SKIP-dubl" in r.stdout, r.stdout
        assert beg(portB, G1) == ba
        # 8. конфликт base: на A сдвиг балки 2, на B ту же балку увели вбок
        move(portA, G2, {"x": 1.0, "y": 0, "z": 0})
        r = run("ops_export.py", A, portA, ("testerA",))
        assert "operaciy 1" in r.stdout, r.stdout
        shutil.copy(os.path.join(A, "ops.json"), os.path.join(B, "ops.json"))
        move(portB, G2, {"x": 9.0, "y": 0, "z": 0})  # ручное изменение на B
        before_b = beg(portB, G2)
        r = run("ops_apply.py", B, portB, ("ops.json",), inp="Y\n")
        assert "CONFLICT-base" in r.stdout, r.stdout
        assert beg(portB, G2) == before_b, "konflikt potrogal proekt!"
        print("KONFLIKT: proekt B ne tronut, kak i dolzhno.")
        # 9. отмена по N: сдвиг балки 3 на A, на B отвечаем N
        move(portA, G3, {"x": 2.0, "y": 0, "z": 0})
        r = run("ops_export.py", A, portA, ("testerA",))
        assert "operaciy 1" in r.stdout, r.stdout
        shutil.copy(os.path.join(A, "ops.json"), os.path.join(B, "ops.json"))
        before_b3 = beg(portB, G3)
        r = run("ops_apply.py", B, portB, ("ops.json",), inp="N\n")
        assert r.returncode == 2 and "Otmeneno" in r.stdout, r.stdout
        assert beg(portB, G3) == before_b3, "otmena potrogala proekt!"
        print("OTMENA: proekt B ne tronut.")
    finally:
        srvA.shutdown()
        srvB.shutdown()
    print("SIM OK: vse 9 shagov proshli.")


if __name__ == "__main__":
    main()
