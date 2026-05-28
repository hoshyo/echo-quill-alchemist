"""State snapshot — minimal-set persistence for crash recovery (per-corpus).

Saved fields are restricted to what's needed to resume the alchemist's behavior
for a specific corpus:

  - `rules`             : LLM-extracted style rules with lifecycle counters.
  - `chunks_processed`  : the canonical chunk_index counter for THIS corpus.

DPO pairs live in `corpora/<id>/dpo.jsonl`, replayed separately by `dpo_log`.
Canon/plot live in their own jsonl files, loaded by `memory.canon` / `memory.plot`.
Transient fields (arena candidates, logs, current phase, previews) are not
persisted — losing them across restart costs nothing.

Each corpus owns its own `snapshot.json` + `snapshot.json.bak`. Switching
between corpora flushes the outgoing one's snapshot before loading the next.
"""
from __future__ import annotations

import shutil
from datetime import datetime, timezone
from typing import List, Optional

from pydantic import BaseModel, Field

from backend.models import StyleRule
from backend.persistence import paths
from backend.persistence.atomic_io import read_text_safe, write_text_atomic

SNAPSHOT_SCHEMA: int = 2  # v2: per-corpus


class AlchemistSnapshot(BaseModel):
    schema_version: int = SNAPSHOT_SCHEMA
    corpus_id: str
    rules: List[StyleRule] = Field(default_factory=list)
    chunks_processed: int = 0
    saved_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


def save(corpus_id: str, rules: List[StyleRule], chunks_processed: int) -> None:
    """Atomically persist a snapshot for `corpus_id`."""
    paths.ensure_corpus_dir(corpus_id)
    snap_file = paths.corpus_snapshot(corpus_id)
    bak_file = paths.corpus_snapshot_bak(corpus_id)

    if snap_file.exists():
        try:
            shutil.copyfile(snap_file, bak_file)
        except OSError:
            pass

    snap = AlchemistSnapshot(
        corpus_id=corpus_id,
        rules=rules,
        chunks_processed=chunks_processed,
    )
    write_text_atomic(snap_file, snap.model_dump_json(indent=2))


def load(corpus_id: str) -> Optional[AlchemistSnapshot]:
    """Restore the most recent valid snapshot for `corpus_id`, or None."""
    for p in (paths.corpus_snapshot(corpus_id), paths.corpus_snapshot_bak(corpus_id)):
        text = read_text_safe(p)
        if text is None:
            continue
        try:
            return AlchemistSnapshot.model_validate_json(text)
        except Exception:
            continue
    return None
