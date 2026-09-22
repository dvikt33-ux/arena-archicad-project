"""Коннектор к Archicad 29 + Tapir 1.5.x. Только стандартная библиотека.

Протокол проверен живыми тестами 2026-09-11 (см. evidence/diag-2026-09-11-v2.json):
- POST на корень http://127.0.0.1:PORT (19723, 19724, ...), тело
  {"command": ..., "parameters": {...}}, ответ {"succeeded": bool, ...}.
- Официальные команды: "API.<Name>".
- Команды Tapir: "API.ExecuteAddOnCommand" c addOnCommandId
  {"commandNamespace": "TapirCommand", "commandName": <Name>},
  полезный ответ — в result.addOnCommandResponse.
"""
import json
import urllib.request
import urllib.error

TAPIR_NAMESPACE = "TapirCommand"


class ArchicadError(Exception):
    def __init__(self, code, message, command=""):
        self.code = code
        super().__init__(f"[{command}] error {code}: {message}")


class ArchicadConnection:
    def __init__(self, port=19723, host="127.0.0.1", timeout=60):
        self.url = f"http://{host}:{port}"
        self.timeout = timeout

    def call(self, command, parameters=None):
        envelope = {"command": command, "parameters": parameters or {}}
        req = urllib.request.Request(
            self.url, data=json.dumps(envelope).encode("utf-8"),
            headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            try:
                e.read()
            except OSError:
                pass
            finally:
                e.close()
            raise ArchicadError(e.code, f"HTTP {e.code}", command) from e
        except Exception as e:  # noqa: BLE001 - сеть: заворачиваем всё
            raise ArchicadError(-1, str(e)[:300], command) from e
        if not data.get("succeeded"):
            err = data.get("error", {})
            raise ArchicadError(err.get("code"), err.get("message", "unknown"), command)
        return data.get("result", {})

    # ---- официальные команды ----
    def official(self, name, parameters=None):
        return self.call(f"API.{name}", parameters)

    def get_product_info(self):
        """{'version': 29, 'buildNumber': 3000, 'languageCode': 'RUS'}"""
        return self.official("GetProductInfo")

    def get_all_guids(self):
        res = self.official("GetAllElements")
        return [e["elementId"]["guid"] for e in res.get("elements", []) if "elementId" in e]

    def get_types_of_elements(self, guids):
        """Возвращает {guid: elementType}."""
        res = self.official(
            "GetTypesOfElements",
            {"elements": [{"elementId": {"guid": g}} for g in guids]})
        out = {}
        for item in res.get("typesOfElements", []):
            inner = item.get("typeOfElement", item)
            eid = (inner.get("elementId") or {}).get("guid")
            if eid:
                out[eid] = inner.get("elementType", "?")
        return out

    def get_selected_guids(self):
        res = self.official("GetSelectedElements")
        return [e["elementId"]["guid"] for e in res.get("elements", []) if "elementId" in e]

    def get_bbox2d(self, guids):
        return self.official(
            "Get2DBoundingBoxes",
            {"elements": [{"elementId": {"guid": g}} for g in guids]})

    # ---- команды Tapir ----
    def tapir(self, name, parameters=None):
        res = self.official("ExecuteAddOnCommand", {
            "addOnCommandId": {"commandNamespace": TAPIR_NAMESPACE, "commandName": name},
            "addOnCommandParameters": parameters or {},
        })
        inner = res.get("addOnCommandResponse", {})
        if isinstance(inner, dict) and inner.get("error"):
            err = inner["error"]
            raise ArchicadError(err.get("code"), err.get("message", "unknown"),
                                f"TapirCommand.{name}")
        return inner

    def get_tapir_version(self):
        return self.tapir("GetAddOnVersion").get("version", "?")

    def get_project_info(self):
        try:
            return self.tapir("GetProjectInfo")
        except ArchicadError:
            return self.official("GetProjectInfo")  # запасной путь

    def get_details(self, guids):
        """Детали элементов через Tapir (официальной команды нет!)."""
        res = self.tapir(
            "GetDetailsOfElements",
            {"elements": [{"elementId": {"guid": g}} for g in guids]})
        return res.get("detailsOfElements", [])

    def highlight(self, guids, rgb=(77, 163, 255), wireframe3d=True):
        """Временная подсветка цветом (проект НЕ меняется)."""
        r, g, b = rgb
        return self.tapir("HighlightElements", {
            "elements": [{"elementId": {"guid": x}} for x in guids],
            "highlightedColors": [[r, g, b, 128] for _ in guids],
            "wireframe3D": wireframe3d,
            "nonHighlightedColor": [200, 200, 200, 64],
        })

    def ping(self):
        """Жива ли связка: Tapir-версия + число элементов."""
        return {"tapir": self.get_tapir_version(),
                "elements": len(self.get_all_guids())}

    def fit_in_window(self, guids):
        """Зум к элементам прямо на экране Archicad (Tapir 1.3.1+)."""
        return self.tapir("FitInWindow", {
            "elements": [{"elementId": {"guid": x}} for x in guids]})

    def show_alert(self, title, message, button1, button2="", button3="",
                   alert_type="information", sub_message=""):
        """Диалог в Archicad с кнопками (Tapir 1.5.6+). Возвращает номер кнопки."""
        params = {"alertType": alert_type, "title": title,
                  "message": message, "button1": button1}
        if sub_message:
            params["subMessage"] = sub_message
        if button2:
            params["button2"] = button2
        if button3:
            params["button3"] = button3
        return self.tapir("ShowAlert", params).get("clickedButton", 0)
