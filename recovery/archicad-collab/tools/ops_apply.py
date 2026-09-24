"""Primenenie operaciy s drugoy mashiny (mashina B). Versiya 1.0.

Chitaet ops.json (konvert iz ops_export.py), proveryaet kazhduyu operaciyu
(element est? base sovpal? est vektor sdviga?), pokazyvaet plan,
sprashivaet Y/N i primenyaet tolko bezopasnye. Konflikty proekt NE trogayut.

Povtornyy zapusk togo zhe fayla bezopasen (uzhe primenennye propuskayutsya).

VNIMANIE: menyayuschiy skript. Pered zapuskom sohranite kopiyu proekta!
Otmena: Ctrl+Z v Archicad (po chislu primenennyh operaciy).

Zapusk:  py ops_apply.py [ops.json]
Peremennaya okruzheniya ACCOLLAB_PORT - prinuditelnyy port (dlya otladki).
Tolko standartnaya biblioteka Python 3.
"""

import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.request

PORTS = [19723, 19724, 19725, 19726, 19727]
PROTOCOL = "1.0"
REPORT_FILE = "ops_report.json"
BATCH = 200
EPS = 1e-3


def ports():
    ov = os.environ.get("ACCOLLAB_PORT")
    if ov:
        return [int(ov)]
    return PORTS


def post(port, command, params, timeout):
    url = "http://127.0.0.1:%d" % port
    envelope = {"command": command, "parameters": params or {}}
    req = urllib.request.Request(
        url, data=json.dumps(envelope).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as e:  # noqa: BLE001
        return {"succeeded": False, "error": {"message": str(e)[:200]}}


def official(port, name, params=None, timeout=60):
    data = post(port, "API." + name, params or {}, timeout)
    if data.get("succeeded"):
        return True, data.get("result", {})
    return False, data.get("error", {})


def tapir(port, name, params=None, timeout=60):
    data = post(port, "API.ExecuteAddOnCommand", {
        "addOnCommandId": {"commandNamespace": "TapirCommand", "commandName": name},
        "addOnCommandParameters": params or {},
    }, timeout)
    if not data.get("succeeded"):
        return False, data.get("error", {})
    inner = data.get("result", {}).get("addOnCommandResponse", {})
    if isinstance(inner, dict) and inner.get("error"):
        return False, inner["error"]
    return True, inner


def scan():
    for p in ports():
        ok, info = official(p, "GetProductInfo", timeout=8)
        if ok:
            print("  port %d: OK (AC %s.%s)" % (p, info.get("version"),
                                                info.get("buildNumber")))
            return p
        print("  port %d: molchit" % p)
    return None


def canonical(obj):
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def checksum(details):
    return hashlib.sha256(canonical(details).encode("utf-8")).hexdigest()


def coords_inner(item):
    d = (item or {}).get("details") or {}
    if "begCoordinate" not in d and isinstance(d.get("details"), dict):
        d = d["details"]
    return d


def move_vector(before, after):
    b = coords_inner(before).get("begCoordinate") or {}
    a = coords_inner(after).get("begCoordinate") or {}
    try:
        v = {"x": a["x"] - b["x"], "y": a["y"] - b["y"],
             "z": a.get("z", 0) - b.get("z", 0)}
    except (KeyError, TypeError):
        return None
    if v["x"] == 0 and v["y"] == 0 and v["z"] == 0:
        return None
    return v


def fetch_details(port, guids):
    out = {}
    for i in range(0, len(guids), BATCH):
        chunk = guids[i:i + BATCH]
        ok, res = tapir(port, "GetDetailsOfElements",
                        {"elements": [{"elementId": {"guid": g}} for g in chunk]})
        if not ok:
            raise RuntimeError("GetDetailsOfElements: %s" % str(res)[:200])
        dets = res.get("detailsOfElements", [])
        for g, d in zip(chunk, dets):
            out[g] = d
    return out


def main():
    print("ops_apply v1.0: primenenie operaciy")
    path = sys.argv[1] if len(sys.argv) > 1 else "ops.json"
    if not os.path.exists(path):
        print("STOP: fayl %s ne nayden. Polozhite ego ryadom so skriptom." % path)
        return 1
    with open(path, encoding="utf-8") as f:
        env = json.load(f)
    if env.get("protocol") != PROTOCOL:
        print("STOP: protocol %s != %s (chuzhoy/staryy fayl?)."
              % (env.get("protocol"), PROTOCOL))
        return 1
    ops = env.get("ops", [])
    print("Fayl: %s, ot: %s, operaciy: %d" % (path, env.get("from"), len(ops)))
    done = {}
    if os.path.exists(REPORT_FILE):
        with open(REPORT_FILE, encoding="utf-8") as f:
            for r in json.load(f).get("results", []):
                done[r["change_id"]] = r.get("status")
    port = scan()
    if port is None:
        print("STOP: Archicad ne nayden. Otkroyte proekt, zakroyte dialogi, povtorite.")
        return 1
    guids = [op["element_guid"] for op in ops if op.get("op") == "modify"]
    current = fetch_details(port, guids) if guids else {}
    plan = []
    for op in ops:
        cid, g = op["change_id"], op["element_guid"]
        if done.get(cid) == "APPLIED":
            plan.append((op, "SKIP-dubl", None, "uzhe primenena ranee"))
            continue
        if op.get("op") != "modify":
            plan.append((op, "UNSUPPORTED", None, "create/delete poka ne umeyu"))
            continue
        cur = current.get(g)
        if cur is None:
            plan.append((op, "CONFLICT-missing", None, "elementa net v proekte"))
            continue
        before = json.loads(op.get("before_json") or "{}")
        after = json.loads(op.get("after_json") or "{}")
        if checksum(cur) != before.get("checksum"):
            plan.append((op, "CONFLICT-base", None, "element uzhe menyali na B"))
            continue
        v = move_vector(before, after)
        if v is None:
            plan.append((op, "UNSUPPORTED", None, "modify bez sdviga koordinat"))
            continue
        plan.append((op, "READY", v, ""))
    print("Plan:")
    ready = [p for p in plan if p[1] == "READY"]
    for op, st, v, note in plan:
        det = json.loads(op.get("after_json") or op.get("before_json") or "{}")
        el_id = (det.get("details") or {}).get("id", "?")
        extra = (" vektor=%s" % (v,)) if v else (" (%s)" % note if note else "")
        print("  - %s %s id=%s%s" % (st, op["element_guid"][:8], el_id, extra))
    results = [{"change_id": op["change_id"], "element_guid": op["element_guid"],
                "status": st, "note": note if st != "READY" else ""}
               for op, st, v, note in plan if st != "READY"]
    if not ready:
        print("GOTOVYH K PRIMENENIYu NET. Proekt ne izmenen.")
        save_report(results)
        return 0
    ans = input("Primenit operaciy: %d? (Y/N): " % len(ready)).strip()
    if ans not in ("Y", "y"):
        print("Otmeneno polzovatelem. Proekt ne izmenen.")
        save_report(results)
        return 2
    for op, st, v, note in ready:
        g = op["element_guid"]
        after = json.loads(op.get("after_json") or "{}")
        ok, resp = tapir(port, "MoveElements", {"elementsWithMoveVectors": [
            {"elementId": {"guid": g}, "moveVector": v, "copy": False}]})
        if not ok or resp.get("success") is False:
            results.append({"change_id": op["change_id"], "element_guid": g,
                            "status": "FAIL-tapir", "note": str(resp)[:200]})
            print("  - FAIL-tapir %s: %s" % (g[:8], str(resp)[:150]))
            continue
        cur = fetch_details(port, [g]).get(g, {})
        b = (coords_inner({"details": cur}).get("begCoordinate")) or {}
        a = (coords_inner(after).get("begCoordinate")) or {}
        good = (abs(b.get("x", 0) - a.get("x", 0)) < EPS
                and abs(b.get("y", 0) - a.get("y", 0)) < EPS)
        csm = "checksum OK" if checksum(cur) == after.get("checksum") else "checksum OTlichaetsya (preduprezhdenie)"
        if good:
            results.append({"change_id": op["change_id"], "element_guid": g,
                            "status": "APPLIED", "note": csm})
            print("  - APPLIED %s (%s)" % (g[:8], csm))
        else:
            results.append({"change_id": op["change_id"], "element_guid": g,
                            "status": "FAIL-verify", "note": "koordinaty ne soshlsya"})
            print("  - FAIL-verify %s: koordinaty ne soshlsya!" % g[:8])
    save_report(results)
    n_ok = sum(1 for r in results if r["status"] == "APPLIED")
    print("Itog: primeneno %d iz %d. Otchet: %s" % (n_ok, len(ready), REPORT_FILE))
    return 0


def save_report(results):
    old = []
    if os.path.exists(REPORT_FILE):
        with open(REPORT_FILE, encoding="utf-8") as f:
            old = json.load(f).get("results", [])
    seen = {r["change_id"] for r in results}
    merged = [r for r in old if r["change_id"] not in seen] + results
    with open(REPORT_FILE, "w", encoding="utf-8") as f:
        json.dump({"applied_at": int(time.time() * 1000), "results": merged},
                  f, ensure_ascii=False)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:  # noqa: BLE001
        print("STOP: %s" % str(e)[:300])
        sys.exit(1)
