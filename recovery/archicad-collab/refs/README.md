# Эталонные схемы API (только для разработки, в установщик НЕ едут)

| Файл | Что это | Источник |
|---|---|---|
| `tapir-1.5.8.json` | Снапшот 236 команд TapirCommand (схемы входов/выходов) | Пакет `archicad-mcp` 0.2.2 (схемы Tapir, MIT, апстрим-тег 1.5.8). У заказчика стоит 1.5.9 — расхождение минорное, перед сборкой обновить снапшот |
| `builtin-1.5.8.json` | Схемы встроенного API из того же пакета | Тот же источник |
| `official-ac29-b3000-commands.txt` | 73 официальные команды `API.*` для AC29 b3000 (имена) | PyPI-пакет `archicad` 29.3000 (`releases/ac29/b3000commands.py`) |

Проверенные факты (2026-09-11, живые тесты + исходники):
- `GetDetailsOfElements` — это команда **Tapir**, официальной `API.GetDetailsOfElements` **нет** (2002).
- Официальные команды требуют префикс `API.`; вызов Tapir — через `API.ExecuteAddOnCommand`
  с `{"commandNamespace": "TapirCommand", "commandName": ...}`.
- `GetElementsByType(elementType: str)` — официальная, параметр `elementType`.
- Типы элементов уточнять через `API.GetTypesOfElements(elements)`.
