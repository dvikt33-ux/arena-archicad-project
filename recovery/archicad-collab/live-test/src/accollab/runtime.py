"""Crash-safe local JSON writes and a process-wide synchronization guard.

atomic_json: запись через временный файл + fsync + os.replace — обрыв питания
в середине записи оставляет либо старый, либо новый файл, но не битый.
sync_guard: один тик на базу across процессы и потоки (файловый замок, ОС
снимает его при смерти процесса). Одного SQLite мало: он сериализует только
записи, а связка «прочитал → сходил в Archicad → записал» без замка гоняет.
Только stdlib.
"""
import json
import os
import tempfile
from contextlib import contextmanager


def atomic_json(path, value):
    path = os.path.abspath(path)
    fd, tmp = tempfile.mkstemp(prefix=".accollab-", suffix=".tmp",
                               dir=os.path.dirname(path))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


@contextmanager
def sync_guard(store_path):
    """Один тик на базу. Держите файл замка на месте (не удалять!): все
    претенденты должны лочить один inode. Бросает RuntimeError, если тик
    по этой базе уже идёт."""
    with open(os.path.abspath(store_path) + ".sync.lock", "a+b") as stream:
        stream.seek(0, os.SEEK_END)
        if not stream.tell():
            stream.write(b"\0")
            stream.flush()
        stream.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise RuntimeError("Synchronization already running for this database") from exc
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == "nt":
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream, fcntl.LOCK_UN)
