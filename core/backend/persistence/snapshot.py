"""State snapshot — minimal-set persistence for crash recovery.

What goes in
------------
Only the fields whose loss would change the alchemist's behavior on restart:

  - `rules`             : LLM-extracted style rules with lifecycle counters.
                          Not reconstructable from `dpo.jsonl` (extraction is
                          stochastic and the lifespan/hit_count history is gone
                          the moment the process dies).
  - `chunks_processed`  : the canonical chunk_index counter. Without it the
                          dashboard restarts at #1 even though `dpo.jsonl`
                          already contains earlier chunks' pairs.

What stays out
--------------
  - `dpo_pairs`            — already appended to core/data/dpo.jsonl per chunk.
  - `arena_*`              — transient inspection state, regenerated next chunk.
  - `logs`                 — also captured in core/data/logs/backend.log.
  - `current_phase`        — meaningless without an in-flight chunk.
  - `last_*_preview`       — UI cosmetics.

When to call
------------
`save()` is called by the engine **after** dpo.jsonl is appended and **before**
`chunk_done` is broadcast. This guarantees the dashboard's reported progress is
always ≤ what's been persisted.
"""
from __future__ import annotations

import shutil
from datetime import datetime, timezone
from typing import List, Optional

from pydantic import BaseModel, Field

from backend.models import StyleRule
from backend.persistence import paths
from backend.persistence.atomic_io import read_text_safe, write_text_atomic

SNAPSHOT_SCHEMA: int = 1


class AlchemistSnapshot(BaseModel):
    """Persisted slice of `AlchemistState`. Versioned for forward evolution."""

    schema_version: int = SNAPSHOT_SCHEMA
    rules: List[StyleRule] = Field(default_factory=list)
    chunks_processed: int = 0
    saved_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


def save(rules: List[StyleRule], chunks_processed: int) -> None:
    """Atomically persist a snapshot. Best-effort `.bak` of the previous file."""
    paths.ensure_dirs()

    if paths.SNAPSHOT_FILE.exists():
        try:
            shutil.copyfile(paths.SNAPSHOT_FILE, paths.SNAPSHOT_BAK)
        except OSError:
            # backup is paranoia; primary write below is the source of truth
            pass

    snap = AlchemistSnapshot(rules=rules, chunks_processed=chunks_processed)
    write_text_atomic(paths.SNAPSHOT_FILE, snap.model_dump_json(indent=2))


def load() -> Optional[AlchemistSnapshot]:
    """Restore the most recent valid snapshot, or None if no readable file exists.

    Tries the live file first, then falls back to `.bak` if the live file is
    missing or fails schema validation (e.g. partial write that somehow slipped
    past the atomic rename, or a stale schema from an older build).
    """
    for p in (paths.SNAPSHOT_FILE, paths.SNAPSHOT_BAK):
        text = read_text_safe(p)
        if text is None:
            continue
        try:
            return AlchemistSnapshot.model_validate_json(text)
        except Exception:
            continue
    return None
