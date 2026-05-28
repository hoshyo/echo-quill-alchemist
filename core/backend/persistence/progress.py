"""Per-novel feed cursor — where to resume from on the next training run.

Storage model
-------------
One JSON file per novel: `data/progress/<novel_sha256>.json`. Atomic full-rewrite
each chunk so a crashing backend never leaves a half-written cursor. The cursor
records the **start char-offset** of the last successfully processed chunk, plus
the chunking parameters that produced it. The next chunk's offset is also stored
so the feeder doesn't need to re-derive the slide step.

Resume semantics
----------------
The feeder GETs `/progress?novel_sha256=...` before slicing. If the response
exists AND the chunking params (chunk_size / ctx / overlap) match the requested
ones, the feeder jumps `args.start` forward to `next_char_offset`. Mismatched
params mean a fundamentally different slicing — we refuse to silently resume
and start from scratch instead.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel, Field

from backend.persistence import paths
from backend.persistence.atomic_io import read_text_safe, write_text_atomic


class FeedProgress(BaseModel):
    """Persistent cursor for one novel's training feed."""

    novel_sha256: str
    novel_path: str = ""
    chunk_size: int = 0
    ctx: int = 0
    overlap: int = 0

    # char_offset is the start position of the truth window in the original file.
    last_committed_char_offset: int = 0
    next_char_offset: int = 0
    last_committed_chunk_index: int = 0

    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


def load(novel_sha256: str) -> Optional[FeedProgress]:
    text = read_text_safe(paths.progress_file(novel_sha256))
    if text is None:
        return None
    try:
        return FeedProgress.model_validate_json(text)
    except Exception:
        return None


def update(
    *,
    novel_sha256: str,
    novel_path: str,
    chunk_size: int,
    ctx: int,
    overlap: int,
    char_offset: int,
    chunk_index: int,
) -> None:
    """Atomically advance the cursor after a chunk has been fully processed."""
    paths.PROGRESS_DIR.mkdir(parents=True, exist_ok=True)
    step = max(1, chunk_size - overlap)
    p = FeedProgress(
        novel_sha256=novel_sha256,
        novel_path=novel_path,
        chunk_size=chunk_size,
        ctx=ctx,
        overlap=overlap,
        last_committed_char_offset=char_offset,
        next_char_offset=char_offset + step,
        last_committed_chunk_index=chunk_index,
        updated_at=datetime.now(timezone.utc),
    )
    write_text_atomic(paths.progress_file(novel_sha256), p.model_dump_json(indent=2))
