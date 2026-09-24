"""Zhivoy test N3: sdvig balki ChEREZ API + sverka koordinat. Versiya 1.2.

V1.2: ispravlen put k koordinatam (details.begCoordinate, a ne koren) —
      v1.1 chital pustotu i lozhno rugalsya; poisk celi po suffiksu "200"
      (ne zavisit ot BLK/BKL/translita); pechat vsex klyuchey details.

VNIMANIE: skript IZMENYAET proekt (dvigaet odnu balku na +0.5 m po X).
Pered zapuskom soxranite kopiyu proekta! Otmena: Ctrl+Z v Archicad.
Skript trebuet yavnogo podtverzhdeniya slovom MOVE.

Zapusk:  py api_move_test.py
Tolko standartnaya biblioteka Python 3.
"""
import json
import sys
import urllib.request
import urllib.error
import socket

PORTS = [19723, 19724, 19725, 19726, 19727]
BATCH = 200
TARGET_SUFFIX = "200"
FALLBACK_INDEX = 200
VECTOR = {"x": 0.5, "y": 0.0, "z": 0.0}

PORT = None


class Busy(RuntimeError):
    pass


def post(command, parameters, timeout):
    req = urllib.request.Request(
        f"http://127.0.0.1:{PORT}",
        data=json.dumps({"command": command, "parameters": parameters}).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except (socket.timeout, TimeoutError):
        raise Busy(f"port {PORT}: Archicad prinyal soedinenie, no ne otvetil za {timeout} s")
    except urllib.error.URLError as e:
        raise Busy(f"port {PORT}: net svyazi ({e.reason})")


def official(name, params=None, timeout=60):
    data = post(f"API.{name}", params or {}, timeout)
    if not data.get("succeeded"):
        raise RuntimeError(f"{name}: {data.get('error')}")
    return data.get("result", {})


def tapir(name, params=None, timeout=60):
    res = official("ExecuteAddOnCommand", {
        "addOnCommandId": {"commandNamespace": "TapirCommand", "commandName": name},
        "addOnCommandParameters": params or {}}, timeout)
    inner = res.get("addOnCommandResponse", {})
    if isinstance(inner, dict) and inner.get("error"):
        raise RuntimeError(f"Tapir.{name}: {inner['error']}")
    return inner


def scan():
    global PORT
    report = []
    for p in PORTS:
        PORT = p
        try:
            info = official("GetProductInfo", timeout=8)
            print(f"  port {p}: OK (AC {info.get('version')}.{info.get('buildNumber')} "
                  f"{info.get('languageCode')})")
            return p
        except Busy as e:
            report.append(str(e))
            print(f"  port {p}: MOLChIT")
        except RuntimeError as e:
            report.append(f"port {p}: {e}")
            print(f"  port {p}: OShIBKA")
    raise Busy("Net otvechayushchego Archicad. Detali:\n  " + "\n  ".join(report))


def all_details():
    guids = [e["elementId"]["guid"]
             for e in official("GetAllElements").get("elements", [])]
    out = {}
    for i in range(0, len(guids), BATCH):
        chunk = guids[i:i + BATCH]
        dets = tapir("GetDetailsOfElements",
                     {"elements": [{"elementId": {"guid": g}} for g in chunk]})
        for g, d in zip(chunk, dets.get("detailsOfElements", [])):
            out[g] = d
    return out


def coords(d):
    inner = d.get("details", {}) if isinstance(d.get("details"), dict) else {}
    return inner.get("begCoordinate", {}), inner.get("endCoordinate", {})


def main():
    print("api_move_test v1.2: skaniruyu porty...", file=sys.stderr)
    try:
        scan()
    except Busy as e:
        print(f"\nSTOP: {e}")
        print("\nChto proverit v Archicad:")
        print("  1. Okno Archicad otvechaet na kliki? Net li dialoga/okna poverx proekta?")
        print("  2. Zapushchen li lish odin Archicad? (esli neskolko — ostavte odin 29-y)")
        print("  3. Ne idet li soxranenie/avtosohranenie (status vnizu okna)?")
        print("  4. Esli vse chisto, a molchit — perezapustite Archicad i povtorite.")
        return 3
    print("api_move_test v1.2: ischu cel...", file=sys.stderr)
    dets = all_details()
    target = next((g for g, d in dets.items()
                   if str(d.get("id", "")).strip().endswith(TARGET_SUFFIX)), None)
    if target is None:
        target = list(dets)[FALLBACK_INDEX]
        print(f"ID s suffiksom {TARGET_SUFFIX} ne nayden — beru element #{FALLBACK_INDEX}.")
    before = dets[target]
    print(f"  klyuchi details: {sorted((before.get('details') or {}).keys())[:12]}")
    bb, be = coords(before)
    print(f'Cel: type="{before.get("type")}" id="{before.get("id")}" guid={target[:8]}...')
    print(f"  bylo: beg={bb} end={be}")
    print(f"  vektor: {VECTOR} (copy=false — peremeschenie, ne kopiya)")
    if input('Dlya prodolzheniya vvedite MOVE (otmena — Ctrl+Z v Archicad): ').strip() != "MOVE":
        print("Otmeneno polzovatelem. Proekt ne izmenen.")
        return 2
    resp = tapir("MoveElements", {"elementsWithMoveVectors": [
        {"elementId": {"guid": target}, "moveVector": VECTOR, "copy": False}]})
    print(f"  otvet Tapir: {json.dumps(resp, ensure_ascii=False)[:300]}")
    after = all_details()[target]
    ab, ae = coords(after)
    print(f"  stalo: beg={ab} end={ae}")
    dx = (ab.get("x", 0) - bb.get("x", 0))
    dy = (ab.get("y", 0) - bb.get("y", 0))
    print(f"  delta: dx={dx:.4f} dy={dy:.4f} (ozhidalos dx=0.5 dy=0.0)")
    if abs(dx - 0.5) < 0.001 and abs(dy) < 0.001:
        print("OK: sdvig cherez API podtverzhden.")
        return 0
    print("RASKHOZHDENIE: fakticheskiy sdvig ne sovpal s zadannym!")
    return 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Busy as e:
        print(f"\nSTOP vo vremya raboty: {e}")
        print("Archicad perestal otvechat. Zakroyte dialogi / dozhdites soxraneniya / perezapustite.")
        sys.exit(3)
