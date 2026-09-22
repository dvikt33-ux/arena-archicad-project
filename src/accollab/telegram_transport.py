"""Транспорт через Telegram Bot API: синхронизация без сервера, карты и админки.

Схема: приватный канал, бот — админ. Каждый демон тем же токеном постит
операции (sendMessage, JSON кусками до 3500 символов) и читает чужие
(getUpdates). Своё отсекается на применении (author == me, идемпотентность).
Курсор — update_id в sync_state (peer "telegram"), недособранные партии —
в telegram_pending.json. Лимит 4096 символов/сообщение, 429 ERR — ждём
retry_after и повторяем один раз. Только stdlib.

Командный режим (3-6+ писателей):
- партии разных авторов интерливируются — сборка по batch id, тест есть;
- fetch качает до 5 страниц по 100 апдейтов (всплески не растягиваются);
- оборванные партии протухают (prune_pending, 1 час по умолчанию);
- партии подписываются HMAC (telegram_secret): чужие/поддельные отбрасываются.

Настройка (один раз): BotFather → /newbot → токен; создать приватный канал →
добавить бота админом → chat_id канала (минус впереди) в конфиг.
"""
import hashlib
import hmac
import json
import time
import urllib.error
import urllib.request
import uuid

CHUNK = 3500
PREFIX = "ACCOLLAB"
FETCH_PAGES = 5
PENDING_TTL_S = 3600


class TelegramError(Exception):
    pass


def _canonical(obj):
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sign_body(body_dict, secret):
    """Подписать партию. Возвращает тело с полем sig (или без, если секрета нет)."""
    body = dict(body_dict)
    if secret:
        body["sig"] = hmac.new(secret.encode("utf-8"),
                               _canonical({k: v for k, v in body.items() if k != "sig"}).encode("utf-8"),
                               hashlib.sha256).hexdigest()
    return body


def check_body(body_str, secret):
    """Проверить подпись. Без секрета — пропускает всё; с секретом — только верное."""
    if not secret:
        return True
    try:
        body = json.loads(body_str)
    except ValueError:
        return False
    sig = body.get("sig", "")
    expect = hmac.new(secret.encode("utf-8"),
                      _canonical({k: v for k, v in body.items() if k != "sig"}).encode("utf-8"),
                      hashlib.sha256).hexdigest()
    return bool(sig) and hmac.compare_digest(sig, expect)


class TelegramTransport:
    def __init__(self, token, chat_id, author, timeout=30, api_base="https://api.telegram.org"):
        self.token = token
        self.chat_id = chat_id
        self.author = author
        self.timeout = timeout
        self.api_base = api_base.rstrip("/")

    def _call(self, method, payload, _retried=False):
        url = "%s/bot%s/%s" % (self.api_base, self.token, method)
        req = urllib.request.Request(
            url, data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                res = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            try:
                try:
                    body = e.read().decode("utf-8")
                except OSError:
                    body = ""
            finally:
                e.close()
            if e.code == 429 and not _retried:
                try:
                    wait = json.loads(body or "{}").get("parameters", {}).get("retry_after", 1)
                except ValueError:
                    wait = 1
                time.sleep(min(int(wait), 60))
                return self._call(method, payload, True)
            raise TelegramError("telegram %s: %s" % (e.code, body[:150]))
        except Exception as e:  # noqa: BLE001 - сеть: заворачиваем всё
            raise TelegramError("telegram unreachable: %s" % str(e)[:150])
        if not res.get("ok"):
            raise TelegramError("telegram: %s" % res.get("description", "?")[:150])
        return res.get("result")

    def push(self, ops, secret=""):
        """Отправить партию операций (подписать секретом, если задан)."""
        body = sign_body({"from": self.author, "ops": ops or []}, secret)
        text = _canonical(body)
        batch = uuid.uuid4().hex[:8]
        parts = [text[i:i + CHUNK] for i in range(0, len(text), CHUNK)] or [""]
        for i, part in enumerate(parts):
            self._call("sendMessage", {"chat_id": self.chat_id,
                                       "text": "%s %s %d/%d\n%s" % (PREFIX, batch, i + 1,
                                                                   len(parts), part)})
        return {"batch": batch, "messages": len(parts)}

    def fetch_raw(self, offset=0, pages=FETCH_PAGES):
        """Сырые тексты начиная с offset (несколько страниц). Возвращает (тексты, max_id)."""
        texts, max_id = [], offset
        for _ in range(max(1, pages)):
            res = self._call("getUpdates", {"offset": max_id, "timeout": 0}) or []
            if not res:
                break
            for upd in res:
                uid = upd.get("update_id", 0)
                if uid >= max_id:
                    max_id = uid + 1
                msg = upd.get("channel_post") or upd.get("message") or {}
                t = msg.get("text", "")
                if t.startswith(PREFIX + " "):
                    texts.append(t)
        return texts, max_id


def parse_part(text):
    """Разобрать 'ACCOLLAB <batch> <i>/<n>\\n<payload>'. Возвращает кортеж или None."""
    try:
        head, payload = text.split("\n", 1)
        _, batch, frac = head.split(" ")
        i, n = frac.split("/")
        return batch, int(i), int(n), payload
    except (ValueError, AttributeError):
        return None


def merge_parts(pending, texts, now=None):
    """Сложить куски в pending {batch: {'n','parts','ts'}}.
    Возвращает список готовых (batch, body_json)."""
    now = now if now is not None else time.time()
    ready = []
    for t in texts:
        parsed = parse_part(t)
        if parsed is None:
            continue
        batch, i, n, payload = parsed
        buf = pending.setdefault(batch, {"n": n, "parts": {}, "ts": now})
        buf["n"] = n
        buf["ts"] = now
        buf["parts"][i] = payload
        if len(buf["parts"]) == n and all(k in buf["parts"] for k in range(1, n + 1)):
            body = "".join(buf["parts"][k] for k in range(1, n + 1))
            ready.append((batch, body))
            del pending[batch]
    return ready


def prune_pending(pending, max_age_s=PENDING_TTL_S, now=None):
    """Выкинуть оборванные партии старше max_age_s. Возвращает число выкинутых."""
    now = now if now is not None else time.time()
    dead = [b for b, v in pending.items() if now - v.get("ts", now) > max_age_s]
    for b in dead:
        del pending[b]
    return len(dead)
