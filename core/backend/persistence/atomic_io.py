"""Crash-safe file IO primitives.

Atomicity model: write-to-temp + fsync + `os.replace`. On both POSIX and Windows
`os.replace` is an atomic rename within the same filesystem, so a reader either
sees the previous full file or the new full file — never a half-written one.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional


def write_text_atomic(path: Path, text: str) -> None:
    """Write `text` to `path` atomically. Parent dir created if missing."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8", newline="\n") as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def read_text_safe(path: Path) -> Optional[str]:
    """Read text or return None if the file is missing / unreadable.

    Deliberately swallows IO and decode errors — callers are expected to fall
    back to a backup or a fresh-start state.
    """
    if not path.exists():
        return None
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return None
