"""Резервные копии файла проекта: verify-then-rotate.

Копия → сверка хэша (исходник == копия) → ротация (лишнее удаляется).
Каталог назначает пользователь; если он внутри папки Яндекс Диска —
копии сами уедут в облако (отдельной интеграции не нужно).
Ничего не удаляет кроме своих старых копий. Только stdlib.
"""
import hashlib
import os
import shutil
import time


class BackupError(Exception):
    pass


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def backup_file(src, backup_dir, keep=5, prefix="project"):
    """Скопировать src с проверкой и ротацией. Возвращает отчёт."""
    if not os.path.isfile(src):
        raise BackupError("net fayla: %s" % src)
    size = os.path.getsize(src)
    if size == 0:
        raise BackupError("pustoy fayl: %s" % src)
    os.makedirs(backup_dir, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    dst = os.path.join(backup_dir, "%s-%s.pln" % (prefix, stamp))
    n = 1
    while os.path.exists(dst):
        n += 1
        dst = os.path.join(backup_dir, "%s-%s-%d.pln" % (prefix, stamp, n))
    shutil.copy2(src, dst)
    src_hash = sha256_file(src)
    if sha256_file(dst) != src_hash:
        try:
            os.remove(dst)
        except OSError:
            pass
        raise BackupError("kontrolnaya summa kopii ne soshlas (kopiya udalena)")
    copies = sorted(f for f in os.listdir(backup_dir)
                    if f.startswith(prefix + "-") and f.endswith(".pln"))
    removed = []
    while len(copies) > max(1, keep):
        old = copies.pop(0)
        try:
            os.remove(os.path.join(backup_dir, old))
            removed.append(old)
        except OSError:
            pass
    return {"path": dst, "bytes": size, "sha256": src_hash,
            "kept": copies, "removed": removed}
