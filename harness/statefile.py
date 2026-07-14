"""Atomic, lock-guarded JSON state files.

The harness keeps small JSON state (memory, todos, checkpoint index) in the state
dir. Two risks the naive ``write_text`` had: a crash mid-write leaves a truncated
file (corruption), and two sessions writing at once lose one update. This module
fixes both with an atomic tmp+os.replace and a best-effort cross-platform lock.

(Phase 1's SQLite task store supersedes this for task/session metadata; this
keeps the remaining file-based state safe in the meantime.)
"""

from __future__ import annotations

import json
import os
import time
from contextlib import contextmanager
from pathlib import Path


@contextmanager
def locked(path, timeout: float = 5.0):
    """Best-effort exclusive lock via an O_EXCL lock file next to ``path``.
    Breaks a stale lock after ``timeout`` so a crashed writer can't wedge state."""
    lock = Path(str(path) + ".lock")
    start = time.monotonic()
    while True:
        try:
            fd = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.close(fd)
            break
        except FileExistsError:
            if time.monotonic() - start > timeout:
                try:
                    lock.unlink()
                except OSError:
                    pass
                continue
            time.sleep(0.02)
    try:
        yield
    finally:
        try:
            lock.unlink()
        except OSError:
            pass


def read_json(path, default):
    p = Path(path)
    if not p.exists():
        return default
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return default


def write_json_atomic(path, data) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(f"{p.name}.tmp{os.getpid()}")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(str(tmp), str(p))  # atomic on POSIX and Windows
