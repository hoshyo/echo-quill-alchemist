"""Per-corpus feed cursor — where to resume from on the next training run.

Storage: `corpora/<corpus_id>/progress.json`. Atomic full-rewrite each chunk.
Resume semantics unchanged from PR-2: feeder GETs `/progress?corpus_id=...`,
jumps `--start` forward to `next_char_offset` if slicing params match.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel, Field

from backend.persistence import paths
from backend.persistence.atomic_io import read_text_safe, write_text_atomic


class FeedProgress(BaseModel):
    corpus_id: str
    novel_sha256: str = ""
    novel_path: str = ""
    chunk_size: int = 0
    ctx: int = 0
    overlap: int = 0

    last_committed_char_offset: int = 0
    next_char_offset: int = 0
    last_committed_chunk_index: int = 0

    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


def load(corpus_id: str) -> Optional[FeedProgress]:
    text = read_text_safe(paths.corpus_progress(corpus_id))
    if text is None:
        return None
    try:
        return FeedProgress.model_validate_json(text)
    except Exception:
        return None


def update(
    *,
    corpus_id: str,
    novel_sha256: str,
    novel_path: str,
    chunk_size: int,
    ctx: int,
    overlap: int,
    char_offset: int,
    chunk_index: int,
) -> None:
    paths.ensure_corpus_dir(corpus_id)
    step = max(1, chunk_size - overlap)
    p = FeedProgress(
        corpus_id=corpus_id,
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
    write_text_atomic(paths.corpus_progress(corpus_id), p.model_dump_json(indent=2))
