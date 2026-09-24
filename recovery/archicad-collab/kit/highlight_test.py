"""Живой тест №1: подсветить первые 3 элемента цветом. Версия 1.0.

Безопасно: только чтение + ВРЕМЕННАЯ подсветка (проект, слои, перья,
материалы НЕ меняются). Подсветка слетает при следующей подсветке,
переключении вида или перезапуске Archicad.

Запуск (образец «тропа» открыт в Archicad 29, вид — план или 3D):
    py highlight_test.py
Ожидаем: 3 объекта окрасятся синим + в консоли появятся их ID (БЛК-00x).
Пришлите скрин результата.

Только стандартная библиотека Python 3.
"""
import json
import sys
import urllib.request

PORT = 19723
N = 3
COLOR = (77, 163, 255)  # синий участника


def post(command, parameters):
    req = urllib.request.Request(
        f"http://127.0.0.1:{PORT}",
        data=json.dumps({"command": command, "parameters": parameters}).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=60) as resp:
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


def main():
    print("highlight_test v1.0: читаю элементы...", file=sys.stderr)
    guids = [e["elementId"]["guid"]
             for e in official("GetAllElements").get("elements", [])][:N]
    if not guids:
        print("Элементов нет — нечего подсвечивать.")
        return 1
    dets = tapir("GetDetailsOfElements",
                 {"elements": [{"elementId": {"guid": g}} for g in guids]})
    for d in dets.get("detailsOfElements", []):
        print(f'  - {d.get("type")} id="{d.get("id")}"')
    r, g, b = COLOR
    tapir("HighlightElements", {
        "elements": [{"elementId": {"guid": x}} for x in guids],
        "highlightedColors": [[r, g, b, 128] for _ in guids],
        "wireframe3D": True,
        "nonHighlightedColor": [200, 200, 200, 64]})
    print(f"OK: подсвечено {len(guids)} элемента. Смотрите план/3D в Archicad.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
