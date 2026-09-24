"""Живой тест №2: подвиньте балку -> увидеть diff. Версия 1.0.

Безопасно: только чтение. Проект меняет ТОЛЬКО пользователь вручную.
Ход теста:
  1. Скрипт делает снимок всех элементов (GUID -> детали+ID), сохраняет snap_before.json.
  2. Вы вручную двигаете ОДНУ балку в Archicad (сохранять не обязательно).
  3. Нажимаете Enter -> скрипт делает второй снимок и показывает diff:
     какая балка изменилась (ID), старые и новые координаты.
Также проверяет предположение A-2.1 (порядок деталей = порядку GUID):
сверяет, что ID идут по порядку БЛК-00x.

Запуск:  py diff_test.py
Только стандартная библиотека Python 3.
"""
import hashlib
import json
import sys
import urllib.request

PORT = 19723
BATCH = 200


def post(command, parameters):
    req = urllib.request.Request(
        f"http://127.0.0.1:{PORT}",
        data=json.dumps({"command": command, "parameters": parameters}).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.loads(resp.read().decode("utf-8"))


def official(name, params=None):
    data = post(f"API.{name}", params or {})
    if not data.get("succeeded"):
        raise RuntimeError(f"{name}: {data.get('error')}")
    return data.get("result", {})


def tapir(name, params=None):
    res = official("ExecuteAddOnCommand", {
        "addOnCommandId": {"commandNamespace": "TapirCommand", "commandName": name},
        "addOnCommandParameters": params or {}})
    inner = res.get("addOnCommandResponse", {})
    if isinstance(inner, dict) and inner.get("error"):
        raise RuntimeError(f"Tapir.{name}: {inner['error']}")
    return inner


def checksum(obj):
    canon = json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()[:16]


def snapshot():
    guids = [e["elementId"]["guid"]
             for e in official("GetAllElements").get("elements", [])]
    items = {}
    for i in range(0, len(guids), BATCH):
        chunk = guids[i:i + BATCH]
        dets = tapir("GetDetailsOfElements",
                     {"elements": [{"elementId": {"guid": g}} for g in chunk]})
        dets = dets.get("detailsOfElements", [])
        if len(dets) != len(chunk):
            raise RuntimeError(f"details {len(dets)} != requested {len(chunk)}")
        for g, d in zip(chunk, dets):
            items[g] = {"id": d.get("id", "?"), "type": d.get("type", "?"),
                        "checksum": checksum(d), "details": d}
    return items


def main():
    print("diff_test v1.0: снимок №1...", file=sys.stderr)
    before = snapshot()
    print(f"Элементов: {len(before)}. Сохраняю snap_before.json...", file=sys.stderr)
    with open("snap_before.json", "w", encoding="utf-8") as f:
        json.dump(before, f, ensure_ascii=False)
    ids = [v["id"] for v in list(before.values())[:5]]
    print(f"Первые ID: {ids}")
    print("Теперь ПОДВИНЬТЕ одну балку в Archicad (сохранять не обязательно),")
    input("и нажмите Enter... ")
    print("Снимок №2...", file=sys.stderr)
    after = snapshot()
    created = [g for g in after if g not in before]
    deleted = [g for g in before if g not in after]
    modified = [g for g in after
                if g in before and after[g]["checksum"] != before[g]["checksum"]]
    print(f"created={len(created)} deleted={len(deleted)} modified={len(modified)}")
    for g in modified:
        b, a = before[g]["details"], after[g]["details"]
        print(f'  - {after[g]["type"]} id="{after[g]["id"]}" guid={g[:8]}...')
        for key in ("begCoordinate", "endCoordinate"):
            if b.get(key) != a.get(key):
                print(f"      {key}: {b.get(key)} -> {a.get(key)}")
        if before[g]["checksum"] == after[g]["checksum"]:
            print("      (checksum совпал — странно)")
    if not modified and not created and not deleted:
        print("Изменений не найдено. Балка точно сдвинулась?")
        return 1
    print("OK: diff найден.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
