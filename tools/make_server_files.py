"""Генератор «писем с сервера» для живого теста в Archicad.

Читает РЕАЛЬНЫЙ открытый проект через Tapir, выбирает несколько элементов
(сначала балки) и пишет пронумерованные файлы server-01.json, server-02.json...
Каждый файл — одно движение от имени удалённого коллеги («boris»).
Файлы кладутся в каталог server-files (НЕ в inbox!): тестировщик переносит
их в inbox по одному и после каждого делает тик демона.

before-чексуммы берутся из живого проекта — base check при применении
пройдёт. Каждый файл двигает СВОЙ элемент (без цепочек — надёжно).

Запуск (из корня кита):
  daemon.bat init --author ya            (один раз — создать конфиг)
  make-server-files.bat                  (создать письма)
Только stdlib + пакет accollab.
"""
import argparse
import copy
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "src"))

from accollab import PROTOCOL_VERSION  # noqa: E402
from accollab.applier import compute_move_vector  # noqa: E402
from accollab.daemon import load_config, scan_archicad  # noqa: E402
from accollab.store import element_checksum  # noqa: E402
from accollab.watcher import new_change_id, new_tx_id, utcnow  # noqa: E402

REMOTE_AUTHOR = "boris"  # «удалённый коллега», от чьего имени письма


def _shifted(details, step):
    """Копия details со сдвигом начал/концов по X. None — двигать нечего.

    Нативная точность БЕЗ округления: живой Archicad хранит больше 4 знаков,
    округление ломало бы сверку чексумм (живой тест 2026-09-18)."""
    try:
        dup = copy.deepcopy(details)
        touched = False
        for pt in ("begCoordinate", "endCoordinate"):
            node = dup.get(pt)
            if isinstance(node, dict) and isinstance(node.get("x"), (int, float)):
                node["x"] = node["x"] + step
                touched = True
        return dup if touched else None
    except (TypeError, ValueError):
        return None


def _make_remote_op(project_id, guid, before_item, after_item, lamport):
    now = utcnow()
    return {
        "change_id": new_change_id(),
        "project_id": project_id,
        "element_guid": guid,
        "author": REMOTE_AUTHOR,
        "wall_time": now,
        "lamport": lamport,
        "base_vector": "{}",
        "seq": 0,
        "op": "modify",
        "before_json": json.dumps(before_item, ensure_ascii=False),
        "after_json": json.dumps(after_item, ensure_ascii=False),
        "tx_id": new_tx_id(),
        "kind": "primary",
        "deps_json": "[]",
        "signature": "",
        "applied": 0,
        "_type": before_item.get("type", "?"),
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description="Pisma s servera dlya zhivogo testa")
    ap.add_argument("--config", default="accollab.json")
    ap.add_argument("--out", default="server-files")
    ap.add_argument("--moves", type=int, default=3)
    ap.add_argument("--step", type=float, default=0.5)
    args = ap.parse_args(argv)

    try:
        cfg = load_config(args.config)
    except (ValueError, OSError) as e:
        print("STOP: config %s: %s" % (args.config, e))
        return 2
    pin = cfg.get("archicad_port", 0)
    conn, port = scan_archicad(timeout=cfg.get("archicad_timeout", 60),
                               ports=[pin] if pin else None)
    if conn is None:
        print("STOP: Archicad ne nayden. Otkroyte proekt v Archicad 29 + Tapir.")
        return 2
    print("Archicad nayden: port %d" % port)

    guids = conn.get_all_guids()
    if not guids:
        print("STOP: v proekte net elementov.")
        return 2
    types = conn.get_types_of_elements(guids)
    beams = [g for g in guids if types.get(g) == "Beam"]
    others = [g for g in guids if types.get(g) != "Beam"]
    ordered = beams + others
    print("elementov: %d (balok: %d)" % (len(guids), len(beams)))

    os.makedirs(args.out, exist_ok=True)
    lamport = int(__import__("time").time() * 1000)
    made, skipped = [], 0
    for guid in ordered:
        if len(made) >= max(1, args.moves):
            break
        try:
            dets = conn.get_details([guid])
        except Exception as e:  # noqa: BLE001 - один битый не стопает всех
            print("propusk %s: details ne otdalis (%s)" % (guid[:8], e))
            skipped += 1
            continue
        if not dets:
            continue
        full = dets[0]
        inner = full.get("details") or {}
        moved_inner = _shifted(inner, args.step)
        if moved_inner is None:
            skipped += 1
            continue
        moved_full = copy.deepcopy(full)
        moved_full["details"] = moved_inner
        before_item = {"type": full.get("type", types.get(guid, "?")),
                       "checksum": element_checksum(full),
                       "details": full}
        after_item = {"type": before_item["type"],
                      "checksum": element_checksum(moved_full),
                      "details": moved_full}
        vec = compute_move_vector(before_item, after_item)
        if vec is None or (vec["x"] == 0 and vec["y"] == 0 and vec["z"] == 0):
            skipped += 1
            continue
        lamport += 1
        op = _make_remote_op(cfg["project_id"], guid, before_item, after_item,
                             lamport)
        env = {"protocol": PROTOCOL_VERSION,
               "project_id": cfg["project_id"],
               "from": "server",
               "exported_at": utcnow(),
               "ops": [op]}
        name = "server-%02d.json" % (len(made) + 1)
        with open(os.path.join(args.out, name), "w", encoding="utf-8") as f:
            json.dump(env, f, ensure_ascii=False, indent=1)
        made.append((name, guid, before_item["type"], vec))
    if not made:
        print("STOP: ni odin element ne sdvinulsya (propushcheno: %d)." % skipped)
        return 2
    print("pisem zapisano: %d -> %s" % (len(made), os.path.abspath(args.out)))
    for name, guid, typ, vec in made:
        print("  %s  %s  %s  dx=%s" % (name, guid, typ, vec["x"]))
    print("dalshe: po odnomu v inbox + `daemon.bat once` posle kazhdogo.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
