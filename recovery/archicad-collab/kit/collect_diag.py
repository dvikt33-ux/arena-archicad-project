"""Сбор read-only диагностики из открытого Archicad 29 + Tapir. Версия 2.1.

Ничего НЕ меняет в проекте, только читает и пишет JSON в ФАЙЛ (UTF-8).
Запуск (Archicad 29 открыт, проект-образец загружен, Tapir загружен):
    py collect_diag.py diag_output.json
Флаг -X utf8 больше НЕ нужен: файл всегда пишется в UTF-8.
Если имя файла не указано — JSON печатается в консоль (старое поведение).

Протокол (проверен живыми тестами 2026-09-11 + исходники пакетов):
- Один HTTP-порт на инстанс (19723, 19724, ...), POST на КОРЕНЬ (без /api).
- Официальные команды: {"command": "API.<Name>", "parameters": {...}}.
  Список 73 команд AC29 b3000 — в refs/official-ac29-b3000-commands.txt.
- Команды Tapir: через {"command": "API.ExecuteAddOnCommand",
  "parameters": {"addOnCommandId": {"commandNamespace": "TapirCommand",
  "commandName": "<Name>"}, "addOnCommandParameters": {...}}}.
  Ответ Tapir лежит в result.addOnCommandResponse.
  ВАЖНО: GetDetailsOfElements существует ТОЛЬКО в Tapir (официальной нет).

Без внешних зависимостей (только стандартная библиотека Python 3).
"""
import json
import sys
import urllib.request
import urllib.error

SCRIPT_VERSION = "2.1"
PORTS = [19723, 19724, 19725, 19726, 19727]
MAX_TYPES_PROBE = 2000   # не дёргаем типы, если элементов больше (защита от гигантов)
MAX_BBOX_PROBE = 10
DETAILS_SAMPLE = 3


def post(port, command, params=None):
    url = f"http://127.0.0.1:{port}"
    envelope = {"command": command, "parameters": params or {}}
    req = urllib.request.Request(
        url, data=json.dumps(envelope).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return {"succeeded": False, "error": {"code": e.code, "message": f"HTTP {e.code}"}}
    except Exception as e:  # noqa: BLE001 - диагностика, собираем всё
        return {"succeeded": False, "error": {"code": -1, "message": str(e)[:300]}}


def official(port, name, params=None):
    """Официальная команда API.<Name>. Возвращает (ok, result-or-error)."""
    data = post(port, f"API.{name}", params)
    if data.get("succeeded"):
        return True, data.get("result", {})
    return False, data.get("error", {})


def tapir(port, name, params=None):
    """Команда TapirCommand.<Name> через ExecuteAddOnCommand."""
    ok, res = official(port, "ExecuteAddOnCommand", {
        "addOnCommandId": {"commandNamespace": "TapirCommand", "commandName": name},
        "addOnCommandParameters": params or {},
    })
    if not ok:
        return False, res
    inner = res.get("addOnCommandResponse", {})
    if isinstance(inner, dict) and inner.get("error"):
        return False, inner["error"]
    return True, inner


def collect():
    out = {"diag_version": SCRIPT_VERSION, "ports": {}, "summary": {}}
    for port in PORTS:
        ok_ver, res_ver = tapir(port, "GetAddOnVersion")
        ok_all, res_all = official(port, "GetAllElements")
        if not ok_ver and not ok_all:
            continue  # порт молчит — не наш инстанс
        entry = {}
        entry["tapirVersion"] = {"succeeded": ok_ver, "data": res_ver}
        ok_prod, res_prod = official(port, "GetProductInfo")
        entry["productInfo"] = {"succeeded": ok_prod, "data": res_prod}
        ok_p, res_p = tapir(port, "GetProjectInfo")
        if not ok_p:
            ok_p, res_p = official(port, "GetProjectInfo")
        entry["projectInfo"] = {"succeeded": ok_p, "data": res_p}
        elements = res_all.get("elements", []) if ok_all else []
        guids = [e["elementId"]["guid"] for e in elements if "elementId" in e]
        entry["allElements"] = {"succeeded": ok_all, "count": len(guids),
                                "sample": elements[:3] if ok_all else res_all}
        # Точные типы ВСЕХ элементов (один запрос) — главный ответ на «что в проекте»
        if guids and len(guids) <= MAX_TYPES_PROBE:
            ok_t, res_t = official(
                port, "GetTypesOfElements",
                {"elements": [{"elementId": {"guid": g}} for g in guids]})
            if ok_t:
                hist = {}
                for item in res_t.get("typesOfElements", res_t.get("typeOfElements", [])):
                    t = item.get("type", item) if isinstance(item, dict) else str(item)
                    t = t if isinstance(t, str) else json.dumps(t, ensure_ascii=False)
                    hist[t] = hist.get(t, 0) + 1
                entry["typesHistogram"] = {"succeeded": True, "histogram": hist}
            else:
                entry["typesHistogram"] = {"succeeded": False, "error": res_t}
        else:
            entry["typesHistogram"] = {"succeeded": False, "error": "skipped: too many elements"}
        # Детали первых N через TAPIR (официальной команды нет)
        if guids:
            ok_d, res_d = tapir(
                port, "GetDetailsOfElements",
                {"elements": [{"elementId": {"guid": g}} for g in guids[:DETAILS_SAMPLE]]})
            entry["detailsSampleTapir"] = {"succeeded": ok_d, "data": res_d}
        # 2D-габариты первых элементов (дешёвый способ увидеть геометрию)
        if guids:
            ok_b, res_b = official(
                port, "Get2DBoundingBoxes",
                {"elements": [{"elementId": {"guid": g}} for g in guids[:MAX_BBOX_PROBE]]})
            entry["bbox2DSample"] = {"succeeded": ok_b, "data": res_b}
        # Выбранное сейчас (для понимания selection-API)
        ok_s, res_s = official(port, "GetSelectedElements")
        entry["selected"] = {"succeeded": ok_s, "data": res_s}
        # Имена свойств (для будущего контроля стандартов): только счётчик + первые 20
        ok_n, res_n = official(port, "GetAllPropertyNames")
        if ok_n:
            names = res_n.get("propertyNames", res_n if isinstance(res_n, list) else [])
            entry["propertyNames"] = {"succeeded": True, "count": len(names), "sample": names[:20]}
        else:
            entry["propertyNames"] = {"succeeded": False, "error": res_n}
        out["ports"][port] = entry
    out["summary"] = {
        p: {"tapir": e["tapirVersion"].get("data") if e["tapirVersion"]["succeeded"] else None,
            "product": e.get("productInfo", {}).get("data"),
            "project": e.get("projectInfo", {}).get("data"),
            "elements": e["allElements"]["count"],
            "typesHistogram": e.get("typesHistogram")}
        for p, e in out["ports"].items()}
    return out


def main(argv):
    print(f"collect_diag v{SCRIPT_VERSION}: опрашиваю порты {PORTS}...", file=sys.stderr)
    try:
        out = collect()
    except Exception:  # noqa: BLE001 - показать ошибку в консоли, а не молча
        import traceback
        traceback.print_exc()
        print("FAILED: см. ошибку выше", file=sys.stderr)
        return 1
    text = json.dumps(out, ensure_ascii=False, indent=2)
    if len(argv) > 1:
        with open(argv[1], "w", encoding="utf-8") as f:
            f.write(text)
        n = sum(1 for _ in out["ports"])
        print(f"OK: опрошено портов: {n}, записано в {argv[1]}", file=sys.stderr)
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
