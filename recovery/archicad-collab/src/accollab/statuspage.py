"""Локальная страница статуса: кнопка «Синхронизировать» + состояние.

Настраиваемая панель: вкладки Статус/Блоки/Конфликты/Чекпоинты можно прятать
в меню «⋯» (открывается кликом, работает без JS через <details>) и возвращать
кнопками «⋯ в меню» / «📌 на панель» в заголовке каждой вкладки. Раскладка
живёт в ui.json рядом с конфигом. Настройки — только колесико ⚙ (редкая
операция), прямой URL /settings сохранён.
Стиль — в духе Archicad: тёмно-синяя шапка, фирменный синий акцент, карточки.
Только localhost (127.0.0.1). Проверяются Host/Origin (анти-DNS-rebinding),
все формы несут CSRF-токен, заголовки no-store/nosniff/DENY/CSP.
GET /[?tab=...] — страница (русская, UTF-8, стили inline, SVG-логотип inline,
внешних ресурсов нет; вкладки щёлкаются мгновенно через JS, без JS —
обычными ссылками). POST /sync — тик демона в фоне; POST /checkpoint —
чекпоинт; POST /resolve — закрыть конфликт; POST /show — зум к элементу
на экране Archicad (FitInWindow + подсветка); POST /ask — спросить выбор
по конфликту диалогом в Archicad (ShowAlert); «Чужое» РЕАЛЬНО применяет
чужую операцию (force, base check пропущен, остальное проверяется), а не
просто закрывает строку; POST /layout — переложить вкладку (панель ↔ меню);
GET/POST /settings — настройка accollab.json.
Демона получает готовым (открытый Store), ничего из daemon не импортирует
наверху (отложенные импорты внутри обработчиков — нет цикла).
Только stdlib.
"""
import html
import json
import os
import re
import secrets
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread
from urllib.parse import parse_qs, urlsplit

from .runtime import atomic_json

PANES = (("status", "📊 Статус"), ("locks", "🔒 Блоки"),
         ("conflicts", "⚡ Конфликты"), ("checkpoints", "📦 Чекпоинты"))

_FORMS_RE = re.compile(r"(<form\b[^>]*>)")

CSS = (
    ":root{--navy:#0b2545;--navy2:#13315c;--blue:#0079c1;--blue2:#005d96;"
    "--sky:#4cc2ff;--bg:#e9edf2;--card:#fff;--ink:#1c2733;--muted:#64748b;"
    "--green:#1e9e6a;--red:#d64545;--amber:#b7791f}"
    "*{box-sizing:border-box}"
    "body{font-family:'Segoe UI',system-ui,Roboto,Arial,sans-serif;margin:0;"
    "background:var(--bg);color:var(--ink)}"
    "header{background:linear-gradient(135deg,var(--navy),var(--navy2));"
    "color:#fff;box-shadow:0 2px 8px #0004;position:sticky;top:0;z-index:5}"
    ".wrap{max-width:960px;margin:0 auto;padding:0 16px}"
    ".head{display:flex;align-items:center;justify-content:space-between;"
    "padding:12px 16px;gap:12px;flex-wrap:wrap}"
    ".brand{display:flex;align-items:center;gap:12px}"
    ".brand .t{font-size:20px;font-weight:700;letter-spacing:2px}"
    ".brand .s{font-size:12px;color:var(--sky)}"
    ".hact{display:flex;gap:10px;align-items:center}"
    ".gear{color:#fff;text-decoration:none;font-size:22px;opacity:.85}"
    ".gear:hover{opacity:1}"
    ".btn{background:var(--blue);color:#fff;border:0;border-radius:8px;"
    "font-size:16px;font-weight:600;padding:10px 26px;cursor:pointer}"
    ".btn:hover{background:var(--blue2)}"
    ".btn.big{font-size:17px;padding:12px 30px;box-shadow:0 0 0 2px #ffffff33}"
    ".btn.small{font-size:13px;padding:5px 14px}"
    ".btn.tiny{font-size:11px;padding:2px 10px;font-weight:400}"
    ".tabs{display:flex;gap:6px;margin:14px 0 0;flex-wrap:wrap;align-items:flex-end}"
    ".tabs a{padding:8px 16px;background:#cfd7e0;color:var(--navy);"
    "text-decoration:none;border-radius:8px 8px 0 0;font-size:14px;font-weight:600}"
    ".tabs a.on{background:var(--card);box-shadow:0 -1px 4px #0001}"
    ".more{display:inline-block;position:relative}"
    ".more summary{list-style:none;cursor:pointer;padding:8px 14px;background:#cfd7e0;"
    "color:var(--navy);border-radius:8px 8px 0 0;font-size:14px;font-weight:600}"
    ".more summary::-webkit-details-marker{display:none}"
    ".more-menu{position:absolute;left:0;top:100%;background:var(--card);"
    "border-radius:0 8px 8px 8px;box-shadow:0 4px 14px #0003;padding:6px;"
    "min-width:180px;z-index:10}"
    ".more-menu a{display:block;padding:7px 10px;color:var(--navy);text-decoration:none;"
    "font-size:13px;border-radius:6px;font-weight:400}"
    ".more-menu a:hover{background:var(--bg)}"
    ".pane{display:none}"
    ".pane.on{display:block}"
    ".pin{float:right}"
    ".pinrow{text-align:right;margin:10px 0 0}"
    ".grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));"
    "gap:10px;margin:16px 0}"
    ".card{background:var(--card);border-radius:10px;padding:12px 16px;"
    "box-shadow:0 1px 4px #0001;border-top:3px solid var(--blue)}"
    ".card span{font-size:11px;text-transform:uppercase;letter-spacing:1px;"
    "color:var(--muted)}"
    ".card b{font-size:26px;display:block;margin-top:2px}"
    ".card.bad{border-top-color:var(--red)}.card.warn{border-top-color:var(--amber)}"
    "section{background:var(--card);border-radius:10px;padding:4px 16px 14px;"
    "margin:14px 0;box-shadow:0 1px 4px #0001}"
    "h2{font-size:15px;text-transform:uppercase;letter-spacing:1px;"
    "color:var(--navy);border-bottom:2px solid var(--sky);padding-bottom:6px}"
    "h3{font-size:13px;color:var(--navy);margin:14px 0 4px}"
    "table{border-collapse:collapse;width:100%}"
    "td,th{border-bottom:1px solid #e5eaf0;padding:7px 8px;font-size:13px;"
    "text-align:left}"
    "th{color:var(--muted);font-weight:600;font-size:11px;text-transform:uppercase;"
    "letter-spacing:1px}"
    ".pill{display:inline-block;padding:2px 10px;border-radius:20px;font-size:12px;"
    "font-weight:600;color:#fff;background:var(--muted)}"
    ".pill.hard{background:var(--red)}.pill.soft{background:var(--blue)}"
    ".note{padding:10px 14px;border-radius:8px;margin:10px 0;font-size:14px}"
    ".note.ok{background:#d9f2e6}.note.warn{background:#fff3cd}"
    ".note.err{background:#f8d7da}"
    ".pulse{animation:pl 1.2s infinite}"
    "@keyframes pl{0%,100%{opacity:1}50%{opacity:.45}}"
    "input[type=text],input[type=password]{padding:6px 8px;border:1px solid #cbd5e1;"
    "border-radius:6px;width:200px;font-size:13px}"
    "input[type=text].wide{width:340px;max-width:100%}"
    "input[type=checkbox]{width:18px;height:18px;vertical-align:middle}"
    "form.inline{display:inline}"
    "footer{color:var(--muted);font-size:12px;text-align:center;padding:18px 0 26px}"
    "footer a{color:var(--blue)}"
    ".empty{color:var(--muted);font-size:13px;padding:6px 0}"
    ".frow{display:flex;gap:10px;align-items:center;margin:8px 0;flex-wrap:wrap}"
    ".frow label{width:230px;font-size:13px;color:var(--muted)}"
    ".hint{font-size:12px;color:var(--muted)}"
)

LOGO = ('<svg width="38" height="38" viewBox="0 0 36 36">'
        '<path d="M18 3 32 11v14L18 33 4 25V11z" fill="#4cc2ff"/>'
        '<path d="M18 3 32 11 18 19 4 11z" fill="#d8f1ff"/>'
        '<path d="M18 19v14L4 25V11z" fill="#0079c1"/></svg>')

TEXT_FIELDS = (("project_id", "Проект (project_id)"),
               ("author", "Автор (author)"),
               ("store", "Файл базы (store)"),
               ("outbox_dir", "Исходящие (outbox_dir)"),
               ("inbox_dir", "Входящие (inbox_dir)"),
               ("poll_s", "Опрос, сек (poll_s)"),
               ("archicad_port", "Порт Archicad, 0=авто (archicad_port)"),
               ("archicad_timeout", "Таймаут команд, сек (archicad_timeout)"),
               ("serve_port", "Порт этой страницы (serve_port)"),
               ("relay_url", "Relay URL (пусто = нет)"),
               ("relay_timeout", "Таймаут relay, сек (relay_timeout)"),
               ("telegram_chat_id", "Telegram chat_id (пусто = нет)"),
               ("telegram_api_base", "Telegram API base"),
               ("telegram_timeout", "Таймаут Telegram, сек (telegram_timeout)"),
               ("backup_dir", "Каталог бэкапов (пусто = нет)"),
               ("backup_keep", "Сколько бэкапов хранить (backup_keep)"),
               ("lock_ttl_s", "Лок по умолчанию, сек (lock_ttl_s)"),
               ("bim_rules", "Правила BIM, all/коды (bim_rules)"),
               ("own_color", "Мой цвет подсветки, hex (own_color)"))
FIELD_GROUPS = {"project_id": "Проект", "store": "Пути",
                "poll_s": "Демон и Archicad", "relay_url": "Relay",
                "telegram_chat_id": "Telegram", "backup_dir": "Бэкапы",
                "lock_ttl_s": "Поведение"}
SECRET_FIELDS = (("relay_secret", "Секрет relay"),
                 ("telegram_bot_token", "Токен Telegram-бота"),
                 ("telegram_secret", "Подпись Telegram"))
BOOL_FIELDS = (("presence_enabled", "Подсветка присутствия (presence_enabled)"),
               ("auto_checkpoint", "Авто-чекпоинт перед чужими (auto_checkpoint)"),
               ("telegram_notify", "Уведомлять о конфликтах в Telegram (telegram_notify)"))
INT_FIELDS = {"poll_s", "archicad_port", "archicad_timeout", "serve_port",
              "relay_timeout", "telegram_timeout", "backup_keep", "lock_ttl_s"}


def _esc(v):
    return html.escape(str(v), quote=True)


def _ui_path(config_path):
    d = os.path.dirname(config_path)
    return os.path.join(d, "ui.json") if d else "ui.json"


def load_layout(config_path):
    """Какие вкладки на панели. Нет файла/мусор — все; пустой список — уважаем."""
    try:
        with open(_ui_path(config_path), encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data.get("pinned"), list):
            return [t for t, _label in PANES if t in data["pinned"]]
    except (OSError, ValueError, AttributeError):
        pass
    return [t for t, _label in PANES]


def save_layout(config_path, pinned):
    atomic_json(_ui_path(config_path),
                {"pinned": [t for t, _label in PANES if t in pinned]})


def render(status, conflicts, checkpoints, msg="", syncing=False,
           tab="status", pinned=None):
    pane_ids = [t for t, _label in PANES]
    labels = dict(PANES)
    if tab not in pane_ids:
        tab = "status"
    pinned = [t for t in pane_ids if t in (pane_ids if pinned is None else pinned)]
    port = status.get("archicad_port") or "—"
    outbox = status.get("outbox_pending", 0)
    n_conf = status.get("conflicts_open", len(conflicts))
    n_locks = len(status.get("locks", []))
    n_warn = len(status.get("warnings", []))

    def card(label, value, cls=""):
        return '<div class="card %s"><span>%s</span><b>%s</b></div>' % (
            cls, _esc(label), _esc(value))

    cards = (card("Archicad · порт", port)
             + card("Очередь outbox", outbox, "warn" if outbox else "")
             + card("Конфликты", n_conf, "bad" if n_conf else "")
             + card("Блокировки", n_locks)
             + card("Предупреждения", n_warn, "warn" if n_warn else ""))
    notes = ""
    if msg:
        notes += '<div class="note ok">%s</div>' % _esc(msg)
    if syncing:
        notes += ('<div class="note ok pulse" id="syncing">↻ Синхронизация идёт '
                  'в фоне... страница обновится сама.</div>')
    for w in status.get("warnings", []):
        notes += '<div class="note warn">⚠ %s: элемент %s держит %s</div>' % (
            _esc(w.get("msg")), _esc(w.get("guid")), _esc(w.get("holder")))
    for e in status.get("last_errors", [])[:5]:
        notes += '<div class="note err">✖ %s: %s</div>' % (
            _esc(e.get("where")), _esc(e.get("msg")))

    if status.get("locks"):
        rows = ""
        for r in status.get("locks", []):
            rows += ("<tr><td><b>%s</b></td>"
                     '<td><span class="pill %s">%s</span></td><td>%s</td>'
                     '<td><form class="inline" method="post" action="/show">'
                     '<input type="hidden" name="guid" value="%s">'
                     '<input type="hidden" name="from" value="locks">'
                     '<input type="submit" class="btn small" value="👁 Показать">'
                     "</form></td></tr>") % (
                         _esc(r.get("guid")), _esc(r.get("mode")),
                         _esc(r.get("mode")), _esc(r.get("holder")),
                         _esc(r.get("guid")))
        locks_html = ("<table><tr><th>Элемент</th><th>Режим</th><th>Держит</th>"
                      "<th></th></tr>%s</table>") % rows
    else:
        locks_html = '<div class="empty">Нет активных блокировок.</div>'

    if conflicts:
        rows = ""
        for c in conflicts:
            rows += ('<tr><td>%s</td><td><b>%s</b></td><td>%s</td><td>%s</td>'
                     '<td><form class="inline" method="post" action="/show">'
                     '<input type="hidden" name="guid" value="%s">'
                     '<input type="hidden" name="from" value="conflicts">'
                     '<input type="submit" class="btn small" value="👁">'
                     '</form> <form class="inline" method="post" action="/ask">'
                     '<input type="hidden" name="conflict_id" value="%s">'
                     '<input type="submit" class="btn small" value="❓ В Archicad">'
                     '</form><br><form class="inline" method="post" action="/resolve">'
                     '<input type="hidden" name="conflict_id" value="%s">'
                     '<input type="text" name="text" placeholder="решение"> '
                     '<input type="submit" class="btn small" value="Закрыть">'
                     '</form></td></tr>'
                     ) % (_esc(c["conflict_id"][:13]), _esc(c["element_guid"][:8]),
                          _esc(c["theirs_change"][:13]), _esc(c["resolution"]),
                          _esc(c["element_guid"]), _esc(c["conflict_id"]),
                          _esc(c["conflict_id"]))
        conf_html = ("<table><tr><th>ID</th><th>Элемент</th><th>Чужой оп</th>"
                     "<th>Код</th><th></th></tr>%s</table>") % rows
    else:
        conf_html = '<div class="empty">Открытых конфликтов нет. Так держать!</div>'

    if checkpoints:
        rows = "".join("<tr><td>%s</td><td>%s</td><td>%s</td></tr>" % (
            _esc(c["checkpoint_id"]), _esc(c["name"]), _esc(c["created_at"])[:19])
            for c in checkpoints)
        cp_html = ("<table><tr><th>ID</th><th>Имя</th><th>Создан</th></tr>%s"
                   "</table>") % rows
    else:
        cp_html = '<div class="empty">Чекпоинтов пока нет.</div>'
    cp_html += ('<form method="post" action="/checkpoint" style="margin-top:8px">'
                '<input type="text" name="name" placeholder="имя чекпоинта"> '
                '<input type="submit" class="btn small" value="Создать чекпоинт">'
                '</form>')

    def pin_btn(name):
        to, text = ("menu", "⋯ в меню") if name in pinned else ("main", "📌 на панель")
        return ('<form class="inline pin" method="post" action="/layout">'
                '<input type="hidden" name="tab" value="%s">'
                '<input type="hidden" name="to" value="%s">'
                '<input type="submit" class="btn tiny" value="%s"></form>') % (name, to, text)

    tabs_html = "".join(
        '<a href="/?tab=%s" data-tab="%s"%s>%s</a>'
        % (t, t, ' class="on"' if t == tab else "", _esc(labels[t]))
        for t in pane_ids if t in pinned)
    hidden = [t for t in pane_ids if t not in pinned]
    if hidden:
        tabs_html += ('<details class="more" id="more"><summary title="Ещё">⋯</summary>'
                      '<div class="more-menu">%s</div></details>') % "".join(
                          '<a href="/?tab=%s">%s</a>' % (t, _esc(labels[t])) for t in hidden)

    def pane(name, inner):
        return '<div class="pane%s" id="pane-%s">%s</div>' % (
            " on" if name == tab else "", name, inner)

    panes = (pane("status", '<div class="pinrow">%s</div><div class="grid">%s</div>'
                  % (pin_btn("status"), cards))
             + pane("locks", "<section><h2>🔒 Блокировки %s</h2>%s</section>"
                    % (pin_btn("locks"), locks_html))
             + pane("conflicts", "<section><h2>⚡ Конфликты %s</h2>%s</section>"
                    % (pin_btn("conflicts"), conf_html))
             + pane("checkpoints", "<section><h2>📦 Чекпоинты %s</h2>%s</section>"
                    % (pin_btn("checkpoints"), cp_html)))

    return ("""<!DOCTYPE html><html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>ACCOLLAB — статус</title><style>%s</style></head><body>
<header><div class="wrap head"><div class="brand">%s
<div><div class="t">ACCOLLAB</div><div class="s">%s @ %s</div></div></div>
<div class="hact"><a class="gear" href="/settings" title="Настройки">⚙</a>
<form method="post" action="/sync"><button class="btn big" type="submit">↻ Синхронизировать</button></form>
</div></div></header>
<div class="wrap">%s<div class="tabs">%s</div>%s
<footer><a href="/status.json">status.json</a> · <a href="/settings">настройки</a> · страница только этого компьютера</footer>
</div>
<script>
(function(){var l=document.querySelectorAll('.tabs > a');for(var i=0;i<l.length;i++){
l[i].onclick=function(e){e.preventDefault();var t=this.getAttribute('data-tab');
for(var j=0;j<l.length;j++){l[j].className=l[j]===this?'on':'';}
var panes=document.querySelectorAll('.pane');for(var k=0;k<panes.length;k++){
panes[k].className='pane'+(panes[k].id==='pane-'+t?' on':'');}}}})();
if (document.getElementById('syncing')) { setTimeout(function(){location.reload()}, 3000); }
</script>
</body></html>""") % (CSS, LOGO, _esc(status.get("author", "?")),
                      _esc(status.get("project_id", "?")), notes, tabs_html, panes)


def settings_form(cfg):
    rows = ""
    for key, label in TEXT_FIELDS:
        if key in FIELD_GROUPS:
            rows += "<h3>%s</h3>" % _esc(FIELD_GROUPS[key])
        rows += ('<div class="frow"><label>%s</label>'
                 '<input type="text" class="wide" name="%s" value="%s"></div>'
                 ) % (_esc(label), key, _esc(cfg.get(key, "")))
    rows += "<h3>Галки</h3>"
    for key, label in BOOL_FIELDS:
        checked = " checked" if cfg.get(key, key == "presence_enabled") else ""
        rows += ('<div class="frow"><label>%s</label>'
                 '<input type="hidden" name="%s" value="0">'
                 '<input type="checkbox" name="%s" value="1"%s></div>'
                 ) % (_esc(label), key, key, checked)
    rows += "<h3>Секреты (пусто = не менять)</h3>"
    for key, label in SECRET_FIELDS:
        state = "задан" if cfg.get(key) else "пуст"
        rows += ('<div class="frow"><label>%s (%s)</label>'
                 '<input type="password" class="wide" name="%s" value="">'
                 "</div>") % (_esc(label), state, key)
    return ('<form method="post" action="/settings">%s'
            '<p><input type="submit" class="btn" value="Сохранить"></p></form>'
            '<p class="hint">Пути и порты вступают после перезапуска serve/демона, '
            "галки — сразу со следующим тиком. Файл лежит рядом с базой.</p>") % rows


def render_settings(cfg, msg=""):
    note = '<div class="note ok">%s</div>' % _esc(msg) if msg else ""
    return ("""<!DOCTYPE html><html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>ACCOLLAB — настройки</title><style>%s</style></head><body>
<header><div class="wrap head"><div class="brand">%s
<div><div class="t">ACCOLLAB</div><div class="s">настройки</div></div></div>
<div class="hact"><a class="gear" href="/" title="Назад">←</a></div>
</div></header>
<div class="wrap">%s<section><h2>⚙ accollab.json</h2>%s</section>
</div></body></html>""") % (CSS, LOGO, note, settings_form(cfg))


def apply_settings(cfg, form):
    """Наложить форму на конфиг. Возвращает (новый cfg, замечания)."""
    from .daemon import CONFIG_INT_RANGES  # отложенно: нет цикла импорта
    out, notes = dict(cfg), []
    for key, _label in TEXT_FIELDS:
        if key not in form:
            continue
        raw = form[key]
        val = (raw[0] if isinstance(raw, list) else raw).strip()
        if key in INT_FIELDS:
            try:
                number = int(val)
                low, high = CONFIG_INT_RANGES[key]
                if not low <= number <= high:
                    notes.append("%s: dopustimo %d..%d" % (key, low, high))
                    continue
                out[key] = number
            except ValueError:
                notes.append("%s: '%s' ne chislo - ostavleno %s" % (key, val, cfg.get(key)))
        elif key in ("project_id", "author") and not val:
            notes.append("%s: pusto - ostavleno '%s'" % (key, cfg.get(key)))
        else:
            out[key] = val
    for key, _label in BOOL_FIELDS:
        if key not in form:
            continue
        raw = form[key]
        val = raw[-1] if isinstance(raw, list) else raw  # hidden 0 + checkbox 1
        out[key] = str(val).strip().lower() in ("1", "on", "true", "yes")
    for key, _label in SECRET_FIELDS:
        if key not in form:
            continue
        raw = form[key]
        val = raw[0] if isinstance(raw, list) else raw
        if val:
            out[key] = val  # пусто = не менять
    return out, notes


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, data, ctype="text/html; charset=utf-8", code=200):
        if isinstance(data, str) and ctype.startswith("text/html"):
            data = _FORMS_RE.sub(
                lambda m: m.group(1) + '<input type="hidden" name="csrf" value="%s">'
                                       % self.server.csrf, data)
        raw = data.encode("utf-8") if isinstance(data, str) else data
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Content-Security-Policy",
                         "frame-ancestors 'none'; form-action 'self'")
        self.end_headers()
        self.wfile.write(raw)

    def _consume_msg(self, msg=""):
        if not msg:
            msg = self.server.last_msg
            self.server.last_msg = ""
        return msg

    def _page(self, msg="", tab="status"):
        d = self.server.daemon
        msg = self._consume_msg(msg)
        status = {}
        if os.path.exists(d.status_path):
            try:
                with open(d.status_path, encoding="utf-8") as f:
                    status = json.load(f)
            except ValueError:
                status = {}
        status.setdefault("author", d.cfg["author"])
        status.setdefault("project_id", d.cfg["project_id"])
        conflicts = [dict(r) for r in d.store.list_conflicts(status="open")]
        checkpoints = [dict(r) for r in d.store.list_checkpoints()]
        t = self.server.sync_thread
        syncing = t is not None and t.is_alive()
        self._send(render(status, conflicts, checkpoints, msg, syncing,
                           tab, load_layout(d.config_path)))

    def _settings_page(self, msg=""):
        msg = self._consume_msg(msg)
        self._send(render_settings(self.server.daemon.cfg, msg))

    def _live_conn(self, timeout=None):
        """Соединение с Archicad с учётом пина порта (отложенный импорт)."""
        from .daemon import scan_archicad  # отложенно: нет цикла импорта
        d = self.server.daemon
        pin = d.cfg.get("archicad_port", 0)
        conn, _port = scan_archicad(timeout=d.cfg.get("archicad_timeout", 60),
                                    ports=[pin] if pin else None)
        if conn is None:
            raise RuntimeError("Archicad ne nayden")
        if timeout:
            conn.timeout = timeout
        return conn

    def do_GET(self):
        if not self._local_request():
            return self._send("Forbidden host", code=403)
        parts = urlsplit(self.path)
        if parts.path == "/status.json" and os.path.exists(self.server.daemon.status_path):
            with open(self.server.daemon.status_path, "rb") as f:
                return self._send(f.read(), "application/json")
        if parts.path in ("/", "/index.html"):
            query = parse_qs(parts.query)
            return self._page(tab=query.get("tab", ["status"])[0])
        if parts.path == "/settings":
            return self._settings_page()
        return self._send("net takoy stranitsy", code=404)

    def _form(self):
        return getattr(self, "form", {})

    def _local_request(self):
        allowed = {"127.0.0.1:%d" % self.server.server_port,
                   "localhost:%d" % self.server.server_port}
        host = self.headers.get("Host", "").lower()
        if host not in allowed:
            return False
        origin = self.headers.get("Origin")
        return origin is None or origin == "http://" + host

    def _redirect(self, where="/"):
        self.send_response(303)
        self.send_header("Location", where)
        self.end_headers()

    def do_POST(self):
        if not self._local_request():
            return self._send("Forbidden origin", code=403)
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length < 0 or length > 100000 or self.headers.get("Transfer-Encoding"):
                return self._send("Invalid request size", code=413)
            self.form = parse_qs(self.rfile.read(length).decode("utf-8"),
                                 max_num_fields=100)
        except (ValueError, UnicodeError):
            return self._send("Invalid form", code=400)
        if not secrets.compare_digest(self.form.get("csrf", [""])[0], self.server.csrf):
            return self._send("Reload this page before submitting the form", code=403)
        d = self.server.daemon
        if self.path == "/sync":
            t = self.server.sync_thread
            if t is not None and t.is_alive():
                self.server.last_msg = "sinhronizatsiya uzhe idet..."
                return self._redirect()
            cfg_path = d.config_path

            def _run():
                from .daemon import Daemon as _D  # отложенно: нет цикла импорта
                dd = None
                try:
                    dd = _D(cfg_path)  # своё соединение: SQLite сериализует сам
                    rep = dd.tick()
                except Exception as e:  # noqa: BLE001 - страница не должна висеть
                    self.server.last_msg = "STOP: %s" % str(e)[:200]
                else:
                    applied = [r["status"] for r in rep.get("applied", [])]
                    self.server.last_msg = "tik zavershen: primeneno %s, oshibok %d" % (
                        applied or "nichego", len(rep.get("errors", [])))
                finally:
                    if dd is not None:
                        dd.store.close()
                    self.server.sync_thread = None

            self.server.sync_thread = Thread(target=_run, daemon=True)
            self.server.sync_thread.start()
            self.server.last_msg = "sinhronizatsiya zapushchena (fon)..."
            return self._redirect()
        if self.path == "/checkpoint":
            name = (self._form().get("name", ["bez-imeni"])[0] or "bez-imeni").strip()
            try:
                cpid = d.make_checkpoint(name)
                self.server.last_msg = "chekpoint %s sozdan" % cpid
            except Exception as e:  # noqa: BLE001 - страница не должна падать
                self.server.last_msg = "STOP: %s" % e
            return self._redirect("/?tab=checkpoints")
        if self.path == "/resolve":
            form = self._form()
            cid = (form.get("conflict_id", [""])[0] or "").strip()
            text = (form.get("text", [""])[0] or "").strip() or "(bez kommentariya)"
            n = d.store.resolve_conflict(cid, text) if cid else 0
            self.server.last_msg = "zakryto konfliktov: %d" % n
            return self._redirect("/?tab=conflicts")
        if self.path == "/show":
            form = self._form()
            guid = (form.get("guid", [""])[0] or "").strip()
            back = (form.get("from", ["locks"])[0] or "locks").strip()
            where = "/?tab=%s" % (back if back in ("locks", "conflicts") else "locks")
            if not guid:
                self.server.last_msg = "STOP: pustoy guid"
                return self._redirect(where)
            try:
                conn = self._live_conn()
                conn.fit_in_window([guid])
                conn.highlight([guid], (255, 180, 0))
                self.server.last_msg = "pokazan v Archicad: %s" % guid[:8]
            except Exception as e:  # noqa: BLE001 - Archicad может спать
                self.server.last_msg = "STOP: %s" % str(e)[:200]
            return self._redirect(where)
        if self.path == "/ask":
            cid = (self._form().get("conflict_id", [""])[0] or "").strip()
            rows = [dict(r) for r in d.store.list_conflicts(status="open")]
            row = next((r for r in rows if r["conflict_id"] == cid), None)
            if row is None:
                self.server.last_msg = "konflikt ne nayden (uzhe zakryt?)"
                return self._redirect("/?tab=conflicts")
            try:
                conn = self._live_conn(timeout=600)  # диалог ждёт человека
                btn = conn.show_alert(
                    "ACCOLLAB: konflikt",
                    "Element %s. Chuzhoe izmenenie %s. Vash vybor zapishetsya v zhurnal."
                    % (row["element_guid"][:8], row["theirs_change"][:13]),
                    "Moyo verno", "Chuzhoe verno", "Pozzhe",
                    alert_type="warning")
            except Exception as e:  # noqa: BLE001 - Archicad может спать
                self.server.last_msg = "STOP: %s" % str(e)[:200]
                return self._redirect("/?tab=conflicts")
            if btn == 1:
                d.store.resolve_conflict(cid, "vybor v Archicad: MOYO")
                self.server.last_msg = "konflikt zakryt: vybrano MOYO"
            elif btn == 2:
                self._take_theirs(d, conn, row, cid)
            else:
                self.server.last_msg = "otlozheno (knopka %s)" % btn
            return self._redirect("/?tab=conflicts")
        if self.path == "/layout":
            form = self._form()
            name = (form.get("tab", [""])[0] or "").strip()
            to = (form.get("to", [""])[0] or "").strip()
            pane_ids = [t for t, _label in PANES]
            if name in pane_ids and to in ("main", "menu"):
                pinned = load_layout(d.config_path)
                if to == "menu" and name in pinned:
                    pinned.remove(name)
                if to == "main" and name not in pinned:
                    pinned.append(name)
                try:
                    save_layout(d.config_path, pinned)
                except OSError as e:
                    self.server.last_msg = "STOP: %s" % str(e)[:200]
            return self._redirect("/?tab=%s" % (name if name in pane_ids else "status"))
        if self.path == "/settings":
            from .daemon import save_config  # отложенно: нет цикла импорта
            if self.server.sync_thread is not None and self.server.sync_thread.is_alive():
                self.server.last_msg = "STOP: dozhdites zaversheniya sinhronizatsii"
                return self._redirect("/settings")
            new_cfg, notes = apply_settings(d.cfg, self._form())
            for key in ("store", "project_id", "author"):
                if new_cfg[key] != d.cfg[key] and d.store.db.execute(
                        "SELECT EXISTS(SELECT 1 FROM operations)"
                        " OR EXISTS(SELECT 1 FROM snapshots)").fetchone()[0]:
                    notes.append("%s: dlya drugogo proekta/avtora nuzhna otdelnaya baza"
                                 % key)
                    new_cfg[key] = d.cfg[key]
            # Открытое соединение не переключает базу через форму.
            if new_cfg["store"] != d.cfg["store"]:
                notes.append("store: izmenite put v config i perezapustite prilozhenie")
                new_cfg["store"] = d.cfg["store"]
            try:
                save_config(d.config_path, new_cfg)
                d.cfg.update(new_cfg)
                self.server.last_msg = "nastroyki sohraneny" + (
                    " (%s)" % "; ".join(notes) if notes else "")
            except (OSError, ValueError) as e:
                self.server.last_msg = "STOP: %s" % str(e)[:200]
            return self._redirect("/settings")
        return self._send("net takogo deystviya", code=404)

    def _take_theirs(self, d, conn, row, cid):
        """«Взять чужое» по-настоящему: force-применение чужой операции.
        Base check пропущен (человек решил), отсутствие элемента и чужой
        hard-блок проверяются. Не вышло — конфликт остаётся открытым."""
        from .applier import ConflictError as _CE, apply_operation as _apply  # отложенно
        from .connector import ArchicadError as _AE  # отложенно
        op = d.store.get_operation(row["theirs_change"])
        if op is None:
            self.server.last_msg = "CHUZHOE ne naydeno v zhurnale; konflikt ostavlen"
            return
        try:
            _apply(conn, d.store, dict(op), force=True)
            d.store.mark_applied(op["change_id"])
        except _CE as e:
            self.server.last_msg = "ne primeneno (%s); konflikt ostavlen otkrytym" % (
                str(e)[:150],)
        except _AE as e:
            self.server.last_msg = "STOP: %s" % str(e)[:200]
        else:
            d.store.resolve_conflict(cid, "primeneno CHUZHOE (vybor v Archicad)")
            self.server.last_msg = "konflikt zakryt: CHUZHOE primeneno"


# Однопоточный сервер: запросы сериализованы → SQLite в безопасности.
class _Server(HTTPServer):
    def __init__(self, addr, daemon):
        self.daemon = daemon
        self.last_msg = ""
        self.sync_thread = None
        self.csrf = secrets.token_hex(32)
        super().__init__(addr, _Handler)

    def get_request(self):
        sock, address = super().get_request()
        sock.settimeout(10)
        return sock, address

    def server_close(self):
        super().server_close()
        worker = self.sync_thread
        if worker is not None:
            worker.join(timeout=5)


def start_server(daemon, port=0, background=True):
    """Поднять страницу. background=True — в потоке (тесты); False — вызывающий
    сам крутит serve_forever (serve: один accept-цикл, иначе SQLite по потокам)."""
    server = _Server(("127.0.0.1", port), daemon)
    if background:
        Thread(target=server.serve_forever, daemon=True).start()
    return server, server.server_address[1]
