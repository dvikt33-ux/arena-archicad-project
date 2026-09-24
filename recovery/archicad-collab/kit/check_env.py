"""Proverka gotovnosti mashiny k testam. Versiya 1.0.

Zapusk: dvoynoy klik po 00-check.bat ili: py check_env.py
Nichego NE menyaet: tolko chitaet versii Python / Archicad / Tapir.
Tolko standartnaya biblioteka Python 3.
"""

import json
import sys
import urllib.error
import urllib.request

PORTS = [19723, 19724, 19725, 19726, 19727]
NEED_PY = (3, 10)
NEED_TAPIR = "1.5.9"


def post(port, command, params, timeout):
    url = "http://127.0.0.1:%d" % port
    envelope = {"command": command, "parameters": params or {}}
    req = urllib.request.Request(
        url, data=json.dumps(envelope).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as e:  # noqa: BLE001 - diagnostika, sobiraem vsyo
        return {"succeeded": False, "error": {"message": str(e)[:150]}}


def official(port, name, timeout=8):
    data = post(port, "API." + name, {}, timeout)
    if data.get("succeeded"):
        return True, data.get("result", {})
    return False, data.get("error", {})


def tapir(port, name, timeout=8):
    data = post(port, "API.ExecuteAddOnCommand", {
        "addOnCommandId": {"commandNamespace": "TapirCommand", "commandName": name},
        "addOnCommandParameters": {},
    }, timeout)
    if not data.get("succeeded"):
        return False, data.get("error", {})
    inner = data.get("result", {}).get("addOnCommandResponse", {})
    if isinstance(inner, dict) and inner.get("error"):
        return False, inner["error"]
    return True, inner


def main():
    print("check_env v1.0: proverka okruzheniya")
    print("-" * 50)
    py_ver = sys.version.split()[0]
    ok_py = sys.version_info >= NEED_PY
    print("1) Python %s ... %s" % (py_ver, "OK" if ok_py else "STARYY (nuzhen 3.10+)"))
    found_ac = None
    tapir_ok = False
    for p in PORTS:
        ok, info = official(p, "GetProductInfo")
        if not ok:
            print("   port %d: molchit" % p)
            continue
        ver = "%s.%s" % (info.get("version"), info.get("buildNumber"))
        print("   port %d: OK (AC %s)" % (p, ver))
        if found_ac is None:
            found_ac = (p, ver)
        ok_t, tv = tapir(p, "GetAddOnVersion")
        raw = str(tv)[:150]
        if ok_t and NEED_TAPIR in raw:
            print("      Tapir %s ... OK" % NEED_TAPIR)
            tapir_ok = True
        elif ok_t:
            print("      Tapir otvetil, no versiya ne %s: %s" % (NEED_TAPIR, raw))
        else:
            print("      Tapir NE otvechaet: %s" % raw)
    print("-" * 50)
    if ok_py and found_ac and tapir_ok:
        print("GOTOVO: mashina k testam gotova (AC na portu %d)." % found_ac[0])
        print("Dalshe: 01-diag.bat, zatem 02-highlight.bat (sm. README.txt).")
    else:
        print("NE GOTOVO, chto chinit:")
        if not ok_py:
            print("  - postavte Python 3.10+ s python.org (galochka Add to PATH).")
        if not found_ac:
            print("  - otkroyte Archicad 29 s proektom; zakroyte lishnie instansy")
            print("    AC26/27/28; zakroyte vse dialogi v Archicad.")
        elif not tapir_ok:
            print("  - proverte Tapir 1.5.9: APX v Add-Ons, galochka Razblokirovat,")
            print("    perezapusk Archicad (podrobno - v README.txt).")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # noqa: BLE001
        print("STOP: %s" % str(e)[:300])
    input("Enter - zakryt okno...")
