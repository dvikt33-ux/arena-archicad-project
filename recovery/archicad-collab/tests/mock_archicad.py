"""Фейковый Archicad HTTP-сервер для тестов (формат ответов — как живой AC29).

Мутации для тестов Watcher: Handler.mutations = {guid: {поле: значение}}
накладываются на детали элемента. Handler.calls копит (имя, параметры) вызовов
FitInWindow/ShowAlert; Handler.alert_button — какую кнопку «нажимает
пользователь» в диалоге ShowAlert.

Использование:
    server, port = start_mock()
    ... тесты через ArchicadConnection(port) ...
    server.shutdown()
"""
import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread

FAKE_GUIDS = ["11111111-1111-1111-1111-111111111111",
              "22222222-2222-2222-2222-222222222222",
              "33333333-3333-3333-3333-333333333333"]


def _ok(result):
    return {"succeeded": True, "result": result}


def _fail(code, message):
    return {"succeeded": False, "error": {"code": code, "message": message}}


def _fresh_state():
    """Начальные координаты балок (одинаковые на любом порту)."""
    beg, end = {}, {}
    for g in FAKE_GUIDS:
        x = round((int(g[:8], 16) % 10000) / 100.0, 2)
        beg[g] = {"x": x, "y": 0.0, "z": 0.0}
        end[g] = {"x": round(x + 1.0, 2), "y": 0.0, "z": 0.0}
    return {"beg": beg, "end": end}


class Handler(BaseHTTPRequestHandler):
    mutations = {}
    state = {}  # порт -> {"beg": {guid: xyz}, "end": {...}} (независимые «машины»)
    calls = []  # [(имя, параметры)] FitInWindow/ShowAlert — для проверок тестов
    alert_button = 1  # какую кнопку «нажимает пользователь» в ShowAlert

    def log_message(self, *a):  # тихо
        pass

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        try:
            body = json.loads(self.rfile.read(length).decode("utf-8"))
        except Exception:
            return self._send(_fail(4000, "bad json"))
        cmd, params = body.get("command", ""), body.get("parameters", {})
        if cmd == "API.GetProductInfo":
            return self._send(_ok({"version": 29, "buildNumber": 3000,
                                   "languageCode": "RUS"}))
        if cmd == "API.GetAllElements":
            return self._send(_ok({"elements": [{"elementId": {"guid": g}}
                                             for g in FAKE_GUIDS]}))
        if cmd == "API.GetTypesOfElements":
            items = [{"typeOfElement": {
                "elementId": e.get("elementId", {}), "elementType": "Beam"}}
                for e in params.get("elements", [])]
            return self._send(_ok({"typesOfElements": items}))
        if cmd == "API.GetSelectedElements":
            return self._send(_ok({"elements": []}))
        if cmd == "API.Get2DBoundingBoxes":
            return self._send(_ok({"boundingBoxes2D": []}))
        if cmd == "API.ExecuteAddOnCommand":
            cid = params.get("addOnCommandId", {})
            if cid.get("commandNamespace") != "TapirCommand":
                return self._send(_ok({"addOnCommandResponse":
                                       {"error": {"code": 4010, "message": "no namespace"}}}))
            name = cid.get("commandName", "")
            tapir_params = params.get("addOnCommandParameters", {})
            if name == "GetAddOnVersion":
                return self._send(_ok({"addOnCommandResponse": {"version": "1.5.9"}}))
            if name == "GetProjectInfo":
                return self._send(_ok({"addOnCommandResponse": {
                    "isUntitled": False, "isTeamwork": False,
                    "projectLocation": "C:\\mock\\mock.pln",
                    "projectPath": "C:\\mock\\mock.pln", "projectName": "mock"}}))
            if name == "GetDetailsOfElements":
                els = tapir_params.get("elements", [])
                st = Handler.state.setdefault(self.server.server_address[1],
                                              _fresh_state())
                dets = []
                for e in els:
                    g = e.get("elementId", {}).get("guid", "?")
                    base = {"x": round((int(g[:8], 16) % 10000) / 100.0, 2), "n": 1,
                            "begCoordinate": dict(st["beg"].get(g, {"x": 0, "y": 0, "z": 0})),
                            "endCoordinate": dict(st["end"].get(g, {"x": 0, "y": 0, "z": 0}))}
                    base.update(Handler.mutations.get(g, {}))
                    dets.append({"type": "Beam", "floorIndex": 1, "layerIndex": 1,
                                 "drawIndex": 1, "id": f"BEAM-{g[:8]}", "details": base})
                return self._send(_ok({"addOnCommandResponse":
                                       {"detailsOfElements": dets}}))
            if name == "MoveElements":
                st = Handler.state.setdefault(self.server.server_address[1],
                                              _fresh_state())
                els = tapir_params.get("elementsWithMoveVectors", [])
                moved = 0
                for e in els:
                    g = e.get("elementId", {}).get("guid")
                    v = e.get("moveVector", {})
                    if g in st["beg"]:
                        for pt in ("beg", "end"):
                            for ax in ("x", "y", "z"):
                                st[pt][g][ax] = round(st[pt][g][ax] + v.get(ax, 0), 4)
                        moved += 1
                return self._send(_ok({"addOnCommandResponse":
                                       {"success": True, "moved": moved}}))
            if name == "HighlightElements":
                return self._send(_ok({"addOnCommandResponse": {"success": True}}))
            if name == "FitInWindow":
                Handler.calls.append(("FitInWindow", tapir_params))
                return self._send(_ok({"addOnCommandResponse": {"success": True}}))
            if name == "ShowAlert":
                Handler.calls.append(("ShowAlert", tapir_params))
                return self._send(_ok({"addOnCommandResponse":
                                       {"clickedButton": Handler.alert_button}}))
            return self._send(_ok({"addOnCommandResponse":
                                   {"error": {"code": 5000, "message": f"unknown {name}"}}}))
        return self._send(_fail(2002, f"Command '{cmd}' not found"))

    def _send(self, obj):
        data = json.dumps(obj).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def start_mock():
    server = HTTPServer(("127.0.0.1", 0), Handler)
    Thread(target=server.serve_forever, daemon=True).start()
    return server, server.server_address[1]
