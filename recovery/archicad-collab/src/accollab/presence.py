"""Присутствие команды: подсветка занятых элементов цветами участников.

Строго временная подсветка (conn.highlight) — проект, слои, перья и материалы
НЕ меняются. Один вызов на holder'а (цвета участников из таблицы participants,
новым выдаются из палитры). Без локов — молчим (чужую подсветку не трогаем).
Только stdlib.
"""
PALETTE = ["#4DA3FF", "#FF7A59", "#7ED321", "#FFCB2F", "#C484FF", "#4ECDC4"]
FALLBACK_RGB = (77, 163, 255)


def _hex_to_rgb(color):
    try:
        h = (color or "").strip().lstrip("#")
        return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))
    except (ValueError, IndexError):
        return FALLBACK_RGB


def color_for(store, holder):
    """Цвет участника (существующий или новый из палитры). Возвращает (r,g,b)."""
    row = store.db.execute("SELECT color FROM participants WHERE participant_id=?",
                           (holder,)).fetchone()
    if row is not None and row["color"]:
        return _hex_to_rgb(row["color"])
    taken = {r["color"] for r in
             store.db.execute("SELECT color FROM participants"
                              " WHERE color IS NOT NULL AND color != ''")}
    free = [c for c in PALETTE if c not in taken] or list(PALETTE)
    color = free[abs(hash(holder)) % len(free)]
    store.db.execute(
        "INSERT OR IGNORE INTO participants(participant_id,name,color) VALUES(?,?,?)",
        (holder, holder, color))
    store.db.commit()
    return _hex_to_rgb(color)


def refresh(conn, store, own=None, own_color=""):
    """Подсветить локи цветами holder'ов. Возвращает {'highlighted': {holder: n}}.

    own/own_color — переопределить свой цвет (настройка «мой цвет»).
    """
    from . import locks as _locks
    groups = {}
    for row in _locks.list_locks(store):
        groups.setdefault(row["holder"], []).append(row["element_guid"])
    out = {}
    for holder, guids in sorted(groups.items()):
        if own_color and holder == own:
            rgb = _hex_to_rgb(own_color)
        else:
            rgb = color_for(store, holder)
        conn.highlight(guids, rgb)
        out[holder] = len(guids)
    return {"highlighted": out}
