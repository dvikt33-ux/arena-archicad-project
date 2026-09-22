"""Демон ACCOLLAB: единый цикл синхронизации.

Каждый тик: watcher (снимок→diff→операции) → экспорт outbox в файлы →
push/fetch ретранслятора → импорт inbox → применение чужих операций →
heartbeat своих локов → status.json.

Без Archicad на проводе тик не падает: чтение/применение пропускаются,
экспорт/ретранслятор/импорт-в-журнал продолжают работать (офлайн-очередь).

CLI: python -m accollab.daemon init|once|run|status|export|import|lock|unlock|
     locks|checkpoint|rollback|conflicts|resolve|comment|comments|comment-reply|
     comment-resolve|history|backup|show|serve|bim-check|relay-serve
Только stdlib.
"""
import argparse
import glob
import json
import os
import sys
import time
import uuid

from . import PROTOCOL_VERSION
from .applier import apply_with_report
from .checkpoints import create as cp_create, rollback_plan, rollback_apply
from .connector import ArchicadConnection, ArchicadError
from . import backup as backup_mod
from . import comments as comments_mod
from . import locks as locks_mod
from . import presence as presence_mod
from .relay import RelayClient, RelayError
from .runtime import atomic_json, sync_guard
from .store import Store
from .telegram_transport import (TelegramError, TelegramTransport, check_body,
                                 merge_parts, prune_pending)
from .transfer import export_envelope, import_envelope, validate_op
from .watcher import Watcher

PORTS = [19723, 19724, 19725, 19726, 19727]
DEFAULT_CONFIG = {
    "project_id": "tropa",
    "author": "mashina-A",
    "store": "accollab.db",
    "poll_s": 5,
    "outbox_dir": "outbox",
    "inbox_dir": "inbox",
    "relay_url": "",
    "relay_secret": "",
    "telegram_bot_token": "",
    "telegram_chat_id": "",
    "telegram_secret": "",
    "telegram_api_base": "https://api.telegram.org",
    "backup_dir": "",
    "backup_keep": 5,
    "archicad_timeout": 60,
    "archicad_port": 0,
    "serve_port": 8472,
    "relay_timeout": 30,
    "telegram_timeout": 30,
    "lock_ttl_s": 20,
    "bim_rules": "all",
    "own_color": "",
    "presence_enabled": True,
    "auto_checkpoint": False,
    "telegram_notify": False,
}

CONFIG_INT_RANGES = {
    "poll_s": (1, 86400), "archicad_port": (0, 65535),
    "serve_port": (1, 65535), "archicad_timeout": (1, 3600),
    "relay_timeout": (1, 3600), "telegram_timeout": (1, 3600),
    "backup_keep": (1, 10000), "lock_ttl_s": (1, 86400),
}


def validate_config(cfg):
    """Проверить конфиг до использования. Бросает ValueError с причиной."""
    if not isinstance(cfg, dict):
        raise ValueError("Configuration must be a JSON object")
    for key, (low, high) in CONFIG_INT_RANGES.items():
        value = cfg.get(key, DEFAULT_CONFIG[key])
        if type(value) is not int or not low <= value <= high:
            raise ValueError("%s must be an integer in %d..%d" % (key, low, high))
    for key in ("project_id", "author", "store", "outbox_dir", "inbox_dir"):
        if not isinstance(cfg.get(key), str) or not cfg[key].strip():
            raise ValueError("%s must be a non-empty string" % key)
    for key, default in DEFAULT_CONFIG.items():
        if isinstance(default, bool) and type(cfg.get(key, default)) is not bool:
            raise ValueError("%s must be boolean" % key)
        if isinstance(default, str) and not isinstance(cfg.get(key, default), str):
            raise ValueError("%s must be a string" % key)


def load_config(path):
    cfg = dict(DEFAULT_CONFIG)
    if os.path.exists(path):
        with open(path, encoding="utf-8-sig") as f:  # BOM от Блокнота — молча
            data = json.load(f)
        if not isinstance(data, dict):
            raise ValueError("Configuration must be a JSON object")
        cfg.update(data)
    validate_config(cfg)
    return cfg


def save_config(path, cfg):
    validate_config({**DEFAULT_CONFIG, **cfg})
    atomic_json(path, cfg)


def scan_archicad(timeout_each=5, timeout=60, ports=None):
    """Найти живой Archicad. Возвращает (conn, port) или (None, None)."""
    for p in (ports or PORTS):
        try:
            probe = ArchicadConnection(port=p, timeout=timeout_each)
            probe.official("GetProductInfo")
        except ArchicadError:
            continue
        return ArchicadConnection(port=p, timeout=timeout), p
    return None, None


class Daemon:
    def __init__(self, config_path):
        self.config_path = config_path
        self.cfg = load_config(config_path)
        self.base = os.path.dirname(os.path.abspath(config_path))
        self.store = Store(self._p(self.cfg["store"]))
        try:
            self._bind_identity()
        except Exception:
            self.store.close()
            raise
        os.makedirs(self._p(self.cfg["outbox_dir"]), exist_ok=True)
        os.makedirs(self._p(self.cfg["inbox_dir"]), exist_ok=True)
        self.status_path = os.path.join(self.base, "status.json")
        self.errors = []
        self._hb_sent = {}

    def _bind_identity(self):
        """База принадлежит одному проекту+автору. Чужая/использованная
        под другим проектом — ValueError (нужна отдельная база)."""
        identity = json.dumps([self.cfg["project_id"], self.cfg["author"]])
        with self.store.db:
            self.store.db.execute(
                "INSERT OR IGNORE INTO meta(key,value) VALUES('daemon_identity',?)",
                (identity,))
            previous = self.store.db.execute(
                "SELECT value FROM meta WHERE key='daemon_identity'").fetchone()[0]
            used = self.store.db.execute(
                "SELECT EXISTS(SELECT 1 FROM operations) OR EXISTS(SELECT 1 FROM snapshots)"
            ).fetchone()[0]
            foreign = self.store.db.execute(
                "SELECT 1 FROM operations WHERE project_id NOT IN ('',?) LIMIT 1",
                (self.cfg["project_id"],)).fetchone()
            if foreign or (used and previous != identity):
                raise ValueError("Database belongs to another project/author;"
                                 " use a separate database")
            self.store.db.execute("UPDATE meta SET value=? WHERE key='daemon_identity'",
                                  (identity,))

    def _p(self, rel):
        return rel if os.path.isabs(rel) else os.path.join(self.base, rel)

    def _err(self, where, msg):
        self.errors.append({"tick": time.time(), "where": where, "msg": str(msg)[:300]})
        self.errors = self.errors[-20:]

    def scan(self):
        """Сканирование с учётом пина: archicad_port=0 — авто, иначе один порт."""
        pinned = self.cfg.get("archicad_port", 0)
        return scan_archicad(timeout=self.cfg["archicad_timeout"],
                             ports=[pinned] if pinned else None)

    # ---- тик ----

    def tick(self):
        with sync_guard(self.store.path):
            return self._tick()

    def _tick(self):
        try:
            fresh = load_config(self.config_path)
        except (ValueError, OSError) as e:
            self._err("config", e)
        else:
            for key in ("store", "project_id", "author"):
                fresh[key] = self.cfg[key]  # личность — только через рестарт
            self.cfg = fresh
        self.errors = []
        rep = {"tick_at": time.time(), "archicad_port": None, "watch": {},
               "exported_files": [], "imported": 0, "applied": [],
               "relay": {}, "locks_swept": 0, "errors": []}
        conn, port = self.scan()
        rep["archicad_port"] = port
        if conn is not None:
            watcher = Watcher(conn, self.store, self.cfg["project_id"], self.cfg["author"])
            try:
                rep["watch"] = watcher.poll_and_record()
            except ArchicadError as e:
                self._err("watch", e)
                conn = None  # дальше без чтения/применения
        else:
            self._err("archicad", "ne nayden (ports %s)" % PORTS)
        rep["warnings"] = self.lock_warnings(rep["watch"].get("ops", []))
        net_transport = bool(self.cfg["relay_url"]) or self._telegram_on()
        try:
            rep["exported_files"] = self.export_outbox_files(dequeue=not net_transport)
        except OSError as e:
            self._err("export", e)
        if self.cfg["relay_url"]:
            try:
                rep["relay"] = self.relay_sync(conn)
            except (RelayError, ValueError) as e:
                self._err("relay", e)
                rep["relay"] = {"error": str(e)[:200]}
        if self._telegram_on():
            try:
                rep["telegram"] = self.telegram_sync()
            except (TelegramError, ValueError) as e:
                self._err("telegram", e)
                rep["telegram"] = {"error": str(e)[:200]}
        try:
            fresh = self.import_inbox_files()
            rep["imported"] = fresh
        except OSError as e:
            self._err("import", e)
        if conn is not None:
            try:
                if self.cfg.get("auto_checkpoint"):
                    rep["auto_checkpoint"] = self._auto_checkpoint(conn)
                rep["applied"] = self.apply_pending(conn)
                if self.cfg.get("telegram_notify") and self._telegram_on():
                    try:
                        rep["notified"] = self._notify_conflicts(rep["applied"])
                    except Exception as e:  # noqa: BLE001 - уведомления не роняют тик
                        self._err("notify", e)
                        rep["notified"] = 0
            except (ArchicadError, RuntimeError) as e:
                self._err("apply", e)
        try:
            self.heartbeat_own_locks()
            rep["locks_swept"] = locks_mod.sweep(self.store)
        except Exception as e:  # noqa: BLE001 - локи не должны ронять тик
            self._err("locks", e)
        try:
            rep["presence"] = self.maybe_refresh_presence(conn)
        except ArchicadError as e:
            self._err("presence", e)
            rep["presence"] = {}
        rep["errors"] = list(self.errors[-5:])
        self.write_status(rep)
        return rep

    def write_status(self, rep):
        conflicts = self.store.list_conflicts(status="open")
        st = {"tick_at": rep["tick_at"], "archicad_port": rep["archicad_port"],
              "author": self.cfg["author"], "project_id": self.cfg["project_id"],
              "outbox_pending": len(self.store.list_outbox()),
              "conflicts_open": len(conflicts),
              "locks": [{"guid": r["element_guid"], "holder": r["holder"],
                         "mode": r["mode"]} for r in locks_mod.list_locks(self.store)],
              "relay": rep.get("relay", {}),
              "telegram": rep.get("telegram", {}),
              "warnings": rep.get("warnings", []),
              "last_errors": rep["errors"]}
        atomic_json(self.status_path, st)
        return st

    # ---- транспорты ----

    def export_outbox_files(self, dequeue=True):
        """Выгрузить outbox в файл. Если dequeue=False — только аудит-копия,
        очередь гасит другой транспорт (ретранслятор)."""
        ids = self.store.list_outbox()
        if not ids:
            return []
        env = export_envelope(self.store, self.cfg["project_id"], self.cfg["author"], ids)
        name = "ops-%s.json" % uuid.uuid4().hex
        path = os.path.join(self._p(self.cfg["outbox_dir"]), name)
        atomic_json(path, env)
        if dequeue:
            for cid in ids:
                self.store.mark_applied(cid)
            self.store.dequeue_outbox(ids)
        return [path]

    def import_inbox_files(self):
        fresh = 0
        for path in sorted(glob.glob(os.path.join(self._p(self.cfg["inbox_dir"]), "*.json"))):
            if path.endswith(".done.json") or path.endswith(".bad.json"):
                continue
            try:
                with open(path, encoding="utf-8") as f:
                    env = json.load(f)
                fresh += import_envelope(self.store, env,
                                         project_id=self.cfg["project_id"])
                os.rename(path, path + ".done.json")
            except ValueError as e:
                self._err("import", "%s: %s" % (os.path.basename(path), e))
                os.rename(path, path + ".bad.json")
        return fresh

    def apply_pending(self, conn=None):
        """Применить все неприменённые чужие операции. Возвращает отчёты.

        Порядок детерминированный внутри этой очереди (lamport, change_id).
        Порядок доставки между машинами может отличаться — это не консенсус:
        разошедшиеся состояния видны как конфликты и разбираются людьми.
        """
        if conn is None:
            conn = self._conn_for_apply()
        rows = self.store.db.execute(
            "SELECT * FROM operations WHERE applied=0 AND author!=?",
            (self.cfg["author"],))
        ordered = sorted([dict(r) for r in rows],
                         key=lambda r: (r["lamport"] or 0, r["change_id"]))
        out = []
        for op in ordered:
            try:
                report = apply_with_report(conn, self.store, op)
            except ArchicadError as exc:
                self._err("apply", exc)
                report = {"change_id": op["change_id"], "status": "ERROR-archicad",
                          "note": str(exc)[:200]}
            out.append(report)
            if report["status"] == "ERROR-archicad":
                break  # транзиент: остальное следующим тиком, порядок цел
            if report["status"] == "UNSUPPORTED":
                continue  # не умею и не скрываю: ни квитанции, ни спама
            self.store.mark_applied(op["change_id"])
        return out

    def _auto_checkpoint(self, conn):
        """Страховочный чекпоинт перед применением чужих (None — нечего)."""
        try:
            row = self.store.db.execute(
                "SELECT COUNT(*) FROM operations WHERE applied=0 AND author!=?",
                (self.cfg["author"],)).fetchone()
            if not row or not row[0]:
                return None
            snap = Watcher(conn, self.store, self.cfg["project_id"],
                           self.cfg["author"]).take_snapshot()
            return cp_create(self.store, snap["items"],
                             "auto-%d" % int(time.time()),
                             self.cfg["author"], "pered primeneniem chuzhikh")
        except Exception as e:
            # Запрошенная страховка не молчит: без чекпоинта чужие не применяем.
            self._err("auto-checkpoint", e)
            raise RuntimeError("Checkpoint failed; remote changes were not applied") from e

    def _notify_conflicts(self, applied):
        """Человеческие строки о конфликтах тика в Telegram-чат. Возвращает n."""
        from .telegram_transport import TelegramTransport as _TG
        tg = _TG(self.cfg["telegram_bot_token"], self.cfg["telegram_chat_id"],
                 self.cfg["author"],
                 timeout=self.cfg.get("telegram_timeout", 30),
                 api_base=self.cfg.get("telegram_api_base", "https://api.telegram.org"))
        n = 0
        for r in applied or []:
            if not str(r.get("status", "")).startswith("CONFLICT"):
                continue
            op = self.store.get_operation(r.get("change_id", "")) or {}
            guid = (op.get("element_guid") or "?")[:8]
            tg._call("sendMessage", {"chat_id": self.cfg["telegram_chat_id"],
                                     "text": "⚡ ACCOLLAB %s: konflikt %s po elementu %s" % (
                                         self.cfg["project_id"], r.get("status"), guid)})
            n += 1
        return n

    def lock_warnings(self, change_ids):
        """Свежие локальные операции по элементам под чужим hard-блоком."""
        out = []
        for cid in change_ids or []:
            row = self.store.get_operation(cid)
            if row is None or row["kind"] != "primary":
                continue
            lock = locks_mod.get(self.store, row["element_guid"])
            if lock is not None and lock["mode"] == "hard" \
                    and lock["holder"] != self.cfg["author"]:
                out.append({"change_id": cid, "guid": row["element_guid"][:8],
                            "holder": lock["holder"],
                            "msg": "pravka pod chuzhim hard-blokom"})
        return out

    def _conn_for_apply(self):
        conn, _ = self.scan()
        if conn is None:
            raise ArchicadError(-1, "Archicad не найден", "scan")
        return conn

    def relay_sync(self, conn):
        client = RelayClient(self.cfg["relay_url"], self.cfg["project_id"],
                             self.cfg["author"], self.cfg["relay_secret"],
                             timeout=self.cfg.get("relay_timeout", 30))
        rep = {}
        ids = self.store.list_outbox()
        if ids:
            env = export_envelope(self.store, self.cfg["project_id"], self.cfg["author"], ids)
            pushed = client.push(env["ops"])
            for cid in ids:
                self.store.mark_applied(cid)
            self.store.dequeue_outbox(ids)
            rep["pushed"] = pushed.get("stored", 0)
        else:
            rep["pushed"] = 0
        st = self.store.get_sync_state("relay")
        cursor = 0
        if st is not None:
            try:
                cursor = json.loads(st["last_vector"] or "{}").get("cursor", 0)
            except ValueError:
                cursor = 0
        fetched = client.fetch(cursor)
        fresh, skipped = 0, 0
        for op in fetched.get("ops", []):
            if validate_op(op, self.cfg["project_id"]) is not None:
                skipped += 1  # битая пропускается, курсор всё равно едет
                continue
            if self.store.insert_operation(op):
                fresh += 1
        rep["fetched"] = len(fetched.get("ops", []))
        rep["fresh"] = fresh
        rep["skipped"] = skipped
        rep["cursor"] = fetched.get("cursor", cursor)
        self.store.update_sync_state("relay", last_vector=json.dumps({"cursor": rep["cursor"]}),
                                     last_sync=time.strftime("%Y-%m-%dT%H:%M:%S"))
        return rep

    def _telegram_on(self):
        return bool(self.cfg["telegram_bot_token"] and self.cfg["telegram_chat_id"])

    def telegram_sync(self):
        tg = TelegramTransport(self.cfg["telegram_bot_token"], self.cfg["telegram_chat_id"],
                               self.cfg["author"],
                               timeout=self.cfg.get("telegram_timeout", 30),
                               api_base=self.cfg.get("telegram_api_base",
                                                     "https://api.telegram.org"))
        secret = self.cfg.get("telegram_secret", "")
        rep = {}
        ids = self.store.list_outbox()
        if ids:
            env = export_envelope(self.store, self.cfg["project_id"], self.cfg["author"], ids)
            pushed = tg.push(env["ops"], secret=secret)
            for cid in ids:
                self.store.mark_applied(cid)
            self.store.dequeue_outbox(ids)
            rep["pushed"] = len(ids)
            rep["messages"] = pushed["messages"]
        else:
            rep["pushed"] = 0
        st = self.store.get_sync_state("telegram")
        offset = 0
        if st is not None:
            try:
                offset = json.loads(st["last_vector"] or "{}").get("update_id", 0)
            except ValueError:
                offset = 0
        pend_path = os.path.join(self.base, "telegram_pending.json")
        pending = {}
        if os.path.exists(pend_path):
            try:
                with open(pend_path, encoding="utf-8") as f:
                    raw = json.load(f)
                pending = {b: {"n": v["n"], "ts": v.get("ts", time.time()),
                               "parts": {int(k): t for k, t in v["parts"].items()}}
                           for b, v in raw.items()}
            except (ValueError, KeyError):
                pending = {}
        texts, max_id = tg.fetch_raw(offset)
        fresh, forged, skipped = 0, 0, 0
        for _, body in merge_parts(pending, texts):
            if not check_body(body, secret):
                forged += 1
                continue
            try:
                batch = json.loads(body)
            except ValueError:
                continue
            if not isinstance(batch, dict):
                continue
            for op in batch.get("ops", []):
                if validate_op(op, self.cfg["project_id"]) is not None:
                    skipped += 1
                    continue
                if self.store.insert_operation(op):
                    fresh += 1
        rep["pruned"] = prune_pending(pending)
        atomic_json(pend_path, pending)
        rep["fetched_msgs"] = len(texts)
        rep["fresh"] = fresh
        rep["skipped"] = skipped
        rep["forged_dropped"] = forged
        rep["update_id"] = max_id
        self.store.update_sync_state("telegram",
                                     last_vector=json.dumps({"update_id": max_id}),
                                     last_sync=time.strftime("%Y-%m-%dT%H:%M:%S"))
        return rep

    def make_checkpoint(self, name, desc=""):
        """Создать чекпоинт текущего состояния. Возвращает id.
        Бросает RuntimeError, если Archicad недоступен."""
        conn, _ = self.scan()
        if conn is None:
            raise RuntimeError("Archicad ne nayden")
        snap = Watcher(conn, self.store, self.cfg["project_id"],
                       self.cfg["author"]).take_snapshot()
        return cp_create(self.store, snap["items"], name, self.cfg["author"], desc)

    def heartbeat_own_locks(self):
        n = 0
        now_ts = time.time()
        for row in list(self.store.db.execute("SELECT * FROM locks WHERE holder=?",
                                              (self.cfg["author"],))):
            if not locks_mod.heartbeat(self.store, row["element_guid"], row["lease_id"]):
                continue
            n += 1
            # Соседи узнают о продлении операцией, иначе их копия протухнет
            # через ttl. Рассылка throttled: не чаще половины ttl.
            ttl = row["expires_in_s"] or locks_mod.DEFAULT_TTL_S
            key = (row["element_guid"], row["lease_id"])
            if now_ts - self._hb_sent.get(key, 0) < max(5, ttl / 2):
                continue
            op = locks_mod.make_lock_op(row["element_guid"], self.cfg["author"],
                                        row["mode"], ttl, row["lease_id"])
            op["project_id"] = self.cfg["project_id"]
            with self.store.transaction():
                self.store.insert_operation(op)
                self.store.enqueue_outbox(op["change_id"])
            self._hb_sent[key] = now_ts
        return n

    def maybe_refresh_presence(self, conn):
        """Подсветить локи, если их набор изменился (иначе — тихо, без вызовов)."""
        if conn is None:
            return {}
        if not self.cfg.get("presence_enabled", True):
            return {"disabled": True}
        rows = locks_mod.list_locks(self.store)
        sig = json.dumps([(r["element_guid"], r["holder"]) for r in rows])
        if sig == getattr(self, "_presence_sig", None):
            return {"unchanged": True}
        res = presence_mod.refresh(conn, self.store, own=self.cfg["author"],
                                           own_color=self.cfg.get("own_color", ""))
        self._presence_sig = sig
        return res

    def run(self):
        print("daemon %s@%s: poll %ss, Ctrl+C — stop"
              % (self.cfg["author"], self.cfg["project_id"], self.cfg["poll_s"]))
        try:
            while True:
                try:
                    rep = self.tick()
                except RuntimeError as exc:
                    print("STOP: %s" % exc)
                    return 1
                print("tick: port=%s ops=%d imported=%d applied=%s errors=%d" % (
                    rep["archicad_port"], len(rep["watch"].get("ops", [])),
                    rep["imported"], [r["status"] for r in rep["applied"]],
                    len(rep["errors"])))
                time.sleep(self.cfg["poll_s"])
        except KeyboardInterrupt:
            print("stop.")
        finally:
            self.store.close()
        return 0


# ---- CLI ----

def _daemon(args):
    return Daemon(args.config)


def cmd_init(args):
    if os.path.exists(args.config) and not args.force:
        print("uzhe est: %s (s --force perezapisat)" % args.config)
        return 1
    cfg = dict(DEFAULT_CONFIG)
    cfg["author"] = args.author
    save_config(args.config, cfg)
    print("config zapisan: %s" % args.config)
    return 0


def cmd_once(args):
    d = _daemon(args)
    try:
        try:
            rep = d.tick()
        except RuntimeError as e:
            print("STOP: %s" % e)
            return 1
    finally:
        d.store.close()
    print(json.dumps(rep, ensure_ascii=False, indent=2)[:2000])
    return 0


def cmd_run(args):
    return _daemon(args).run()


def cmd_status(args):
    d = _daemon(args)
    d.store.close()
    if not os.path.exists(d.status_path):
        print("status.json net — daemon eshche ne tikal (once/run).")
        return 1
    with open(d.status_path, encoding="utf-8") as f:
        print(f.read())
    return 0


def cmd_lock(args):
    d = _daemon(args)
    ttl = args.ttl if args.ttl else d.cfg.get("lock_ttl_s", 20)
    try:
        lease = locks_mod.acquire(d.store, args.guid, d.cfg["author"],
                                  mode=args.mode, ttl_s=ttl)
        if lease is None:
            print("ZANYATO drugim. Sm. locks.")
            return 1
        op = locks_mod.make_lock_op(args.guid, d.cfg["author"], args.mode, ttl, lease)
        d.store.insert_operation(op)
        d.store.enqueue_outbox(op["change_id"])
        print("LOCK %s %s lease=%s (razoshletsya sosedyam)" % (args.guid[:8], args.mode, lease))
    finally:
        d.store.close()
    return 0


def cmd_unlock(args):
    d = _daemon(args)
    try:
        row = locks_mod.get(d.store, args.guid)
        if row is None or row["holder"] != d.cfg["author"]:
            print("net vashego bloka na %s" % args.guid[:8])
            return 1
        locks_mod.release(d.store, args.guid, row["lease_id"])
        op = locks_mod.make_unlock_op(args.guid, d.cfg["author"], row["lease_id"])
        d.store.insert_operation(op)
        d.store.enqueue_outbox(op["change_id"])
        print("UNLOCK %s (razoshletsya sosedyam)" % args.guid[:8])
    finally:
        d.store.close()
    return 0


def cmd_locks(args):
    d = _daemon(args)
    try:
        rows = locks_mod.list_locks(d.store)
        if not rows:
            print("(net aktivnyh blokov)")
        for r in rows:
            print("%s %s %s do %s" % (r["element_guid"][:8], r["mode"], r["holder"],
                                      r["heartbeat"]))
    finally:
        d.store.close()
    return 0


def cmd_checkpoint(args):
    d = _daemon(args)
    try:
        try:
            cpid = d.make_checkpoint(args.name, args.desc)
        except RuntimeError as e:
            print("STOP: %s." % e)
            return 1
        print("CHECKPOINT %s" % cpid)
    finally:
        d.store.close()
    return 0


def cmd_rollback(args):
    d = _daemon(args)
    try:
        conn, port = d.scan()
        if conn is None:
            print("STOP: Archicad ne nayden.")
            return 1
        watcher = Watcher(conn, d.store, d.cfg["project_id"], d.cfg["author"])
        snap = watcher.take_snapshot()
        plan = rollback_plan(d.store, args.checkpoint_id, snap["items"], d.cfg["author"],
                             project_id=d.cfg["project_id"])
        print("plan otkata %s: operaciy %d, propushcheno %d"
              % (args.checkpoint_id, len(plan["ops"]), len(plan["skipped"])))
        for s in plan["skipped"]:
            print("  SKIP %s: %s" % (s["guid"][:8], s["reason"]))
        if not args.yes:
            print("dlya primeneniya povtorite s --yes (proekt POKA ne tronut).")
            return 2
        rep = rollback_apply(conn, d.store, plan)
        n_ok = sum(1 for r in rep["results"] if r["status"] == "APPLIED")
        print("otkat: primeneno %d iz %d" % (n_ok, len(rep["results"])))
    finally:
        d.store.close()
    return 0


def cmd_conflicts(args):
    d = _daemon(args)
    try:
        rows = d.store.list_conflicts()
        if not rows:
            print("(konfliktov net)")
        for r in rows:
            print("%s [%s] el=%s ours=%s theirs=%s %s"
                  % (r["conflict_id"][:13], r["status"], r["element_guid"][:8],
                     r["ours_change"][:13], r["theirs_change"][:13], r["resolution"]))
    finally:
        d.store.close()
    return 0


def cmd_resolve(args):
    d = _daemon(args)
    try:
        n = d.store.resolve_conflict(args.conflict_id, args.text)
        print("resolved: %d" % n)
    finally:
        d.store.close()
    return 0


def cmd_comment(args):
    d = _daemon(args)
    try:
        cid, op = comments_mod.add_local(d.store, args.guid, d.cfg["author"],
                                         " ".join(args.text))
        d.store.insert_operation(op)
        d.store.enqueue_outbox(op["change_id"])
        print("COMMENT %s (ujdet sosedyam)" % cid)
    except ValueError as e:
        print("STOP: %s" % e)
        return 1
    finally:
        d.store.close()
    return 0


def cmd_comments(args):
    d = _daemon(args)
    try:
        rows = comments_mod.list_for_element(d.store, args.guid) if args.guid \
            else comments_mod.list_open(d.store)
        if not rows:
            print("(kommentariev net)")
        for r in rows:
            try:
                guid = json.loads(r["target_json"] or "{}").get("element_guid", "?")[:8]
            except ValueError:
                guid = "?"
            print("%s [%s] el=%s %s: %s" % (r["comment_id"], r["status"], guid,
                                            r["author"], r["text"][:120]))
            for rep in json.loads(r["replies_json"] or "[]"):
                print("    otvet %s: %s" % (rep.get("author"), rep.get("text", "")[:120]))
    finally:
        d.store.close()
    return 0


def cmd_comment_reply(args):
    d = _daemon(args)
    try:
        op = comments_mod.reply_local(d.store, args.comment_id, d.cfg["author"],
                                      " ".join(args.text))
        d.store.insert_operation(op)
        d.store.enqueue_outbox(op["change_id"])
        print("REPLY ok (ujdet sosedyam)")
    except (KeyError, ValueError) as e:
        print("STOP: %s" % e)
        return 1
    finally:
        d.store.close()
    return 0


def cmd_comment_resolve(args):
    d = _daemon(args)
    try:
        op = comments_mod.resolve_local(d.store, args.comment_id, d.cfg["author"])
        d.store.insert_operation(op)
        d.store.enqueue_outbox(op["change_id"])
        print("COMMENT-RESOLVED (ujdet sosedyam)")
    except KeyError as e:
        print("STOP: %s" % e)
        return 1
    finally:
        d.store.close()
    return 0


def cmd_history(args):
    d = _daemon(args)
    try:
        rows = d.store.ops_for_element(args.guid, limit=args.limit)
        if not rows:
            print("(istorii net)")
        for r in rows:
            print("%s %s/%s %s applied=%s" % (r["change_id"][:13], r["author"],
                                              r["op"], str(r["wall_time"])[:19],
                                              r["applied"]))
    finally:
        d.store.close()
    return 0


def cmd_backup(args):
    d = _daemon(args)
    try:
        backup_dir = args.dir or d.cfg.get("backup_dir", "")
        if not backup_dir:
            print("STOP: zadaite dir (ili backup_dir v config).")
            return 1
        conn, port = d.scan()
        if conn is None:
            print("STOP: Archicad ne nayden.")
            return 1
        info = conn.tapir("GetProjectInfo")
        src = info.get("projectPath") or info.get("projectLocation") or ""
        if not src or info.get("isUntitled"):
            print("STOP: proekt bez imeni/puti — sohranite ego snachala.")
            return 1
        rep = backup_mod.backup_file(src, backup_dir, keep=args.keep,
                                     prefix=d.cfg["project_id"])
        print("BACKUP ok: %s (%d bayt, sha256 %s...)" % (
            rep["path"], rep["bytes"], rep["sha256"][:12]))
        if rep["removed"]:
            print("rotatsiya: udaleny %s" % ", ".join(rep["removed"]))
    except backup_mod.BackupError as e:
        print("STOP: %s" % e)
        return 1
    finally:
        d.store.close()
    return 0


def cmd_bimcheck(args):
    from . import bim_checks as _bim
    d = _daemon(args)
    try:
        conn, port = d.scan()
        if conn is None:
            print("STOP: Archicad ne nayden.")
            return 1
        count, rep = _bim.check_live(conn, d.store, d.cfg["project_id"],
                                         d.cfg["author"],
                                         rules=d.cfg.get("bim_rules", "all"))
        print("BIM: elementov %d, zamechaniy %d" % (count, len(rep["issues"])))
        for i in rep["issues"][:50]:
            if i["code"] == "DUP_ID":
                print("  DUP_ID %s: %s" % (i["id"], ", ".join(i["guids"])))
            elif i["code"] == "EMPTY_ID":
                print("  EMPTY_ID: %s" % i["guid"])
            else:
                print("  %s: %s" % (i["code"], i.get("guid", "?")))
        if len(rep["issues"]) > 50:
            print("  ... eshche %d" % (len(rep["issues"]) - 50))
        return 3 if rep["issues"] else 0
    finally:
        d.store.close()


def cmd_show(args):
    """Зум к элементу на экране Archicad + янтарная подсветка."""
    d = _daemon(args)
    try:
        conn, port = d.scan()
        if conn is None:
            print("STOP: Archicad ne nayden.")
            return 2
        try:
            conn.fit_in_window([args.guid])
            conn.highlight([args.guid], (255, 180, 0))
        except ArchicadError as e:
            print("STOP: %s" % e)
            return 2
        print("pokazan v Archicad (port %d): %s" % (port, args.guid[:8]))
        return 0
    finally:
        d.store.close()


def cmd_serve(args):
    from . import statuspage as _sp
    d = _daemon(args)
    port = args.port or d.cfg.get("serve_port", 8472)
    server, port = _sp.start_server(d, port, background=False)
    print("status: http://127.0.0.1:%d (tolko etot kompyuter, Ctrl+C — stop)" % port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        d.store.close()
    return 0


def cmd_export(args):
    d = _daemon(args)
    try:
        files = d.export_outbox_files()
        print("exported: %s" % (files or "(outbox pust)"))
    finally:
        d.store.close()
    return 0


def cmd_import(args):
    d = _daemon(args)
    try:
        n = d.import_inbox_files()
        print("imported fresh: %d" % n)
    finally:
        d.store.close()
    return 0


def cmd_relayserve(args):
    from .relay import main as relay_main
    relay_main(["--port", str(args.port), "--secret", args.secret, "--data", args.data,
                "--host", args.host])
    return 0


def build_parser():
    ap = argparse.ArgumentParser(prog="accollab", description="ACCOLLAB daemon (Faza A)")
    ap.add_argument("--config", default="accollab.json")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("init", help="sozdat config")
    p.add_argument("--author", default="mashina-A")
    p.add_argument("--force", action="store_true")
    p.set_defaults(func=cmd_init)
    p = sub.add_parser("once", help="odin tik")
    p.set_defaults(func=cmd_once)
    p = sub.add_parser("run", help="cikl do Ctrl+C")
    p.set_defaults(func=cmd_run)
    p = sub.add_parser("status", help="pokazat status.json")
    p.set_defaults(func=cmd_status)
    p = sub.add_parser("lock", help="zanyat element")
    p.add_argument("guid")
    p.add_argument("--mode", default="soft", choices=["soft", "hard"])
    p.add_argument("--ttl", type=int, default=None)
    p.set_defaults(func=cmd_lock)
    p = sub.add_parser("unlock", help="osvobodit element")
    p.add_argument("guid")
    p.set_defaults(func=cmd_unlock)
    p = sub.add_parser("locks", help="spisok blokov")
    p.set_defaults(func=cmd_locks)
    p = sub.add_parser("checkpoint", help="чекпоинт")
    p.add_argument("name")
    p.add_argument("--desc", default="")
    p.set_defaults(func=cmd_checkpoint)
    p = sub.add_parser("rollback", help="otkat k чекпоинту")
    p.add_argument("checkpoint_id")
    p.add_argument("--yes", action="store_true")
    p.set_defaults(func=cmd_rollback)
    p = sub.add_parser("conflicts", help="zhurnal konfliktov")
    p.set_defaults(func=cmd_conflicts)
    p = sub.add_parser("resolve", help="zakryt konflikt resheniem polzovatelya")
    p.add_argument("conflict_id")
    p.add_argument("text")
    p.set_defaults(func=cmd_resolve)
    p = sub.add_parser("export", help="vygnav outbox v fayly vruchnuyu")
    p.set_defaults(func=cmd_export)
    p = sub.add_parser("import", help="zabrat inbox v zhurnal vruchnuyu")
    p.set_defaults(func=cmd_import)
    p = sub.add_parser("relay-serve", help="podnyat retranslyator (dlya seti)")
    p.add_argument("--port", type=int, default=8471)
    p.add_argument("--secret", default="")
    p.add_argument("--data", default="relay.jsonl")
    p.add_argument("--host", default="0.0.0.0")
    p.set_defaults(func=cmd_relayserve)
    p = sub.add_parser("comment", help="kommentariy k elementu")
    p.add_argument("guid")
    p.add_argument("text", nargs="+")
    p.set_defaults(func=cmd_comment)
    p = sub.add_parser("comments", help="spisok kommentariev (vse/po guid)")
    p.add_argument("guid", nargs="?")
    p.set_defaults(func=cmd_comments)
    p = sub.add_parser("comment-reply", help="otvet na kommentariy")
    p.add_argument("comment_id")
    p.add_argument("text", nargs="+")
    p.set_defaults(func=cmd_comment_reply)
    p = sub.add_parser("comment-resolve", help="zakryt kommentariy")
    p.add_argument("comment_id")
    p.set_defaults(func=cmd_comment_resolve)
    p = sub.add_parser("history", help="istoriya elementa")
    p.add_argument("guid")
    p.add_argument("--limit", type=int, default=50)
    p.set_defaults(func=cmd_history)
    p = sub.add_parser("backup", help="kopiya PLN s proverkoy i rotatsiey")
    p.add_argument("--dir", default="")
    p.add_argument("--keep", type=int, default=5)
    p.set_defaults(func=cmd_backup)
    p = sub.add_parser("serve", help="stranitsa statusa (localhost)")
    p.add_argument("--port", type=int, default=None)
    p.set_defaults(func=cmd_serve)
    p = sub.add_parser("bim-check", help="BIM-kontrol po snimku")
    p.set_defaults(func=cmd_bimcheck)
    p = sub.add_parser("show", help="pokazat element na ekrane Archicad")
    p.add_argument("guid")
    p.set_defaults(func=cmd_show)
    return ap


def main(argv=None):
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
