"""Centralized filesystem layout for the persistence layer.

All paths are anchored to `core/data/` regardless of the process CWD, so the
backend behaves identically whether launched from the repo root, the `core/`
dir, or detached by `scripts/start_services.py`.
"""
from __future__ import annotations

from pathlib import Path

# core/backend/persistence/paths.py → core/backend/persistence → core/backend → core
_CORE_DIR = Path(__file__).resolve().parent.parent.parent

DATA_DIR: Path = _CORE_DIR / "data"

# Append-only training log. Authoritative source for DPO pairs across restarts.
# (engine.py still owns the *append* via its own constant; this module owns reads.)
DPO_FILE: Path = DATA_DIR / "dpo.jsonl"

# PR-1: full state snapshot for crash recovery (rules + chunk counter)
SNAPSHOTS_DIR: Path = DATA_DIR / "snapshots"
SNAPSHOT_FILE: Path = SNAPSHOTS_DIR / "state.json"
SNAPSHOT_BAK: Path = SNAPSHOTS_DIR / "state.json.bak"

# PR-2: per-novel feed cursor + chunk_id idempotency log
PROGRESS_DIR: Path = DATA_DIR / "progress"
SEEN_DIR: Path = DATA_DIR / "seen"


def progress_file(novel_sha256: str) -> Path:
    """Path to the per-novel feed cursor JSON."""
    return PROGRESS_DIR / f"{novel_sha256}.json"


def seen_file(novel_sha256: str) -> Path:
    """Path to the per-novel append-only chunk_id log."""
    return SEEN_DIR / f"{novel_sha256}.txt"


def ensure_dirs() -> None:
    """Create persistence directories on demand. Idempotent."""
    SNAPSHOTS_DIR.mkdir(parents=True, exist_ok=True)
    PROGRESS_DIR.mkdir(parents=True, exist_ok=True)
    SEEN_DIR.mkdir(parents=True, exist_ok=True)
