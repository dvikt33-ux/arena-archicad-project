"""Снимки координат через Tapir: --probe / --save / --diff.

Для живого теста: зафиксировать «как было», после каждого письма сверить
сдвиг программно (глазами смотреть не нужно).
  coords.py --probe [--config C]              — Archicad жив? сколько элементов?
  coords.py --save FILE [--config C] [--guids g1,g2]  — снимок в JSON
  coords.py --diff A B                        — кто сдвинулся и на сколько
Только stdlib + пакет accollab.
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "src"))

from accollab.daemon import load_config, scan_archicad  # noqa: E402

EPS = 1e-6


def _conn(config):
    pin = 0
    if config:
        pin = load_config(config).get("archicad_port", 0)
    return scan_archicad(ports=[pin] if pin else None)


def _snap(conn, only):
    guids = conn.get_all_guids()
    if only:
        want = set(only)
        guids = [g for g in guids if g in want]
    out = {}
    for i in range(0, len(guids), 100):
        chunk = guids[i:i + 100]
        for g, d in zip(chunk, conn.get_details(chunk)):
            inner = d.get("details") or {}
            out[g] = {
                "type": d.get("type", "?"),
                "beg": [(inner.get("begCoordinate") or {}).get(a) for a in "xyz"],
                "end": [(inner.get("endCoordinate") or {}).get(a) for a in "xyz"],
            }
    return out


def _delta(a, b):
    if a is None or b is None:
        return None
    return round(b - a, 4)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Snimki koordinat cherez Tapir")
    ap.add_argument("--config", default="")
    ap.add_argument("--probe", action="store_true")
    ap.add_argument("--save", default="")
    ap.add_argument("--diff", nargs=2, metavar=("A", "B"))
    ap.add_argument("--guids", default="")
    args = ap.parse_args(argv)

    if args.diff:
        a = json.load(open(args.diff[0], encoding="utf-8"))
        b = json.load(open(args.diff[1], encoding="utf-8"))
        n = 0
        for g in sorted(set(a) | set(b)):
            if g not in a or g not in b:
                print("%s  propal/poyavilsya" % g)
                n += 1
                continue
            dx = _delta(a[g]["beg"][0], b[g]["beg"][0])
            dy = _delta(a[g]["beg"][1], b[g]["beg"][1])
            dz = _delta(a[g]["beg"][2], b[g]["beg"][2])
            if dx is None:
                continue
            if abs(dx) > EPS or abs(dy or 0) > EPS or abs(dz or 0) > EPS:
                print("%s  dx=%s dy=%s dz=%s" % (g, dx, dy, dz))
                n += 1
        print("izmenilos: %d" % n)
        return 0

    conn, port = _conn(args.config or None)
    if conn is None:
        print("STOP: Archicad ne nayden.")
        return 2
    if args.probe:
        guids = conn.get_all_guids()
        print("Archicad: port %d, elementov: %d" % (port, len(guids)))
        return 0
    if args.save:
        only = [g.strip() for g in args.guids.split(",") if g.strip()]
        snap = _snap(conn, only or None)
        with open(args.save, "w", encoding="utf-8") as f:
            json.dump(snap, f, ensure_ascii=False, indent=1)
        print("snimok: %d elementov -> %s" % (len(snap), args.save))
        return 0
    ap.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
