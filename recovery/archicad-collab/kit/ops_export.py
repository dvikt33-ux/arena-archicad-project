"""Eksport operaciy dlya perenosa na druguyu mashinu (mashina A). Versiya 1.0.

Tolko chtenie iz Archicad. Pervyy zapusk sohranyaet bazu (ops_base.json),
0 operaciy. Dvin'te balku -> zapustite snova -> poluchite ops.json.

Peredacha na mashinu B: lyubym kanalom (messendzher, oblako, pochta).
Tam: py ops_apply.py ops.json

Zapusk:  py ops_export.py [avtor]
Peremennaya okruzheniya ACCOLLAB_PORT - prinuditelnyy port (dlya otladki).
Tolko standartnaya biblioteka Python 3.
"""

import hashlib
import json
import os
import socket
import sys
import time
import urllib.error
import urllib.request
import uuid

PORTS = [19723, 19724, 19725, 19726, 19727]
PROTOCOL = "1.0"
PROJECT_ID = "tropa"
BASE_FILE = "ops_base.json"
OUT_FILE = "ops.json"
BATCH = 200


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


def preview_vector(before, after):
    b = coords_inner(before).get("begCoordinate") or {}
    a = coords_inner(after).get("begCoordinate") or {}
    try:
        return {"x": a["x"] - b["x"], "y": a["y"] - b["y"], "z": a.get("z", 0) - b.get("z", 0)}
    except (KeyError, TypeError):
        return None


def snapshot(port):
    ok, res = official(port, "GetAllElements")
    if not ok:
        raise RuntimeError("GetAllElements: %s" % str(res)[:200])
    guids = [e["elementId"]["guid"] for e in res.get("elements", [])]
    types = {}
    if guids:
        ok, res = official(port, "GetTypesOfElements",
                           {"elements": [{"elementId": {"guid": g}} for g in guids]})
        if not ok:
            raise RuntimeError("GetTypesOfElements: %s" % str(res)[:200])
        for t in res.get("typesOfElements", []):
            e = t.get("typeOfElement", {})
            types[e.get("elementId", {}).get("guid")] = e.get("elementType", "?")
    items = {}
    for i in range(0, len(guids), BATCH):
        chunk = guids[i:i + BATCH]
        ok, res = tapir(port, "GetDetailsOfElements",
                        {"elements": [{"elementId": {"guid": g}} for g in chunk]})
        if not ok:
            raise RuntimeError("GetDetailsOfElements: %s" % str(res)[:200])
        dets = res.get("detailsOfElements", [])
        if len(dets) != len(chunk):
            raise RuntimeError("details %d != zapros %d (A-2.1?)" % (len(dets), len(chunk)))
        for g, d in zip(chunk, dets):
            items[g] = {"type": types.get(g, "?"), "checksum": checksum(d), "details": d}
    return items


def new_change_id():
    ms = int(time.time() * 1000)
    return "%013d-%s" % (ms, uuid.uuid4().hex[:12])


def main():
    print("ops_export v1.0: snyatie operaciy")
    author = sys.argv[1] if len(sys.argv) > 1 else socket.gethostname()
    port = scan()
    if port is None:
        print("STOP: Archicad ne nayden. Otkroyte proekt, zakroyte dialogi, povtorite.")
        return 1
    print("Snimayu sostoyanie...")
    items = snapshot(port)
    print("  elementov: %d" % len(items))
    if not os.path.exists(BASE_FILE):
        with open(BASE_FILE, "w", encoding="utf-8") as f:
            json.dump({"items": items}, f, ensure_ascii=False)
        print("BASELINE SOHRANEN v %s. Operaciy: 0." % BASE_FILE)
        print("Dvin'te balku v Archicad i zapustite snova - poluchite %s." % OUT_FILE)
        return 0
    with open(BASE_FILE, encoding="utf-8") as f:
        old = json.load(f)["items"]
    created = [g for g in items if g not in old]
    deleted = [g for g in old if g not in items]
    modified = [g for g in items
                if g in old and items[g]["checksum"] != old[g]["checksum"]]
    print("  created=%d deleted=%d modified=%d" % (len(created), len(deleted), len(modified)))
    tx_id = uuid.uuid4().hex
    now_ms = int(time.time() * 1000)
    ops = []

    def make_op(op, g, before, after):
        return {"change_id": new_change_id(), "project_id": PROJECT_ID,
                "element_guid": g, "author": author, "wall_time": now_ms,
                "lamport": now_ms, "base_vector": "{}", "seq": 0, "op": op,
                "before_json": json.dumps(before or {}, ensure_ascii=False),
                "after_json": json.dumps(after or {}, ensure_ascii=False),
                "tx_id": tx_id, "kind": "primary", "deps_json": "[]",
                "signature": "", "applied": 0,
                "_type": ((after or before) or {}).get("type", "?")}

    for g in created:
        ops.append(make_op("create", g, None, items[g]))
    for g in deleted:
        ops.append(make_op("delete", g, old[g], None))
    for g in modified:
        ops.append(make_op("modify", g, old[g], items[g]))
    env = {"protocol": PROTOCOL, "project_id": PROJECT_ID, "from": author,
           "exported_at": now_ms, "ops": ops}
    with open(OUT_FILE, "w", encoding="utf-8") as f:
        json.dump(env, f, ensure_ascii=False)
    with open(BASE_FILE, "w", encoding="utf-8") as f:
        json.dump({"items": items}, f, ensure_ascii=False)
    print("Zapisano %s: operaciy %d. Baza obnovlena." % (OUT_FILE, len(ops)))
    for op in ops:
        g = op["element_guid"]
        det = json.loads(op["after_json"] or op["before_json"] or "{}")
        el_id = (det.get("details") or {}).get("id", "?")
        extra = ""
        if op["op"] == "modify":
            v = preview_vector(json.loads(op["before_json"]), json.loads(op["after_json"]))
            extra = " vektor=%s" % (v,) if v else " (bez sdviga koordinat!)"
        print("  - %s %s id=%s%s" % (op["op"], g[:8], el_id, extra))
    if any(op["op"] in ("create", "delete") for op in ops):
        print("Vnimanie: create/delete poka NE primenyayutsya na mashine B")
        print("(podderzhivaetsya tolko modify). Oni zafiksirovany v fayle.")
    print("Peredayte %s na mashinu B lyubym kanalom." % OUT_FILE)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:  # noqa: BLE001
        print("STOP: %s" % str(e)[:300])
        sys.exit(1)
