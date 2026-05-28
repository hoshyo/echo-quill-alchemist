"""Per-novel chunk_id idempotency log.

Why this exists
---------------
A feeder restart races against a backend restart: the feeder may resend chunks
that the backend already processed (because the feeder doesn't know exactly
how far the backend got, or because the user manually re-ran train.py). The
fix is to make `/trigger_training` idempotent — if `chunk_id` was already
processed, the engine bails before incrementing counters or spending tokens.

Storage model
-------------
One append-only text file per novel: `data/seen/<novel_sha256>.txt`, one
chunk_id per line. On first access for a given novel, the file is loaded into
an in-memory `set[str]` for O(1) `contains()`. New chunk_ids are written
through to disk on every `add()` so the guarantee holds across crashes.

The set is bounded by the number of chunks in the novel — a 1000-chunk novel
yields ~30 KB on disk and a 1000-element set in memory. Negligible.
"""
from __future__ import annotations

from typing import Dict, Set

from backend.persistence import paths

_caches: Dict[str, Set[str]] = {}


def _load(novel_sha256: str) -> Set[str]:
    """Load (or return cached) chunk_id set for this novel."""
    cached = _caches.get(novel_sha256)
    if cached is not None:
        return cached
    s: Set[str] = set()
    f = paths.seen_file(novel_sha256)
    if f.exists():
        try:
            for line in f.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line:
                    s.add(line)
        except OSError:
            pass
    _caches[novel_sha256] = s
    return s


def contains(novel_sha256: str, chunk_id: str) -> bool:
    return chunk_id in _load(novel_sha256)


def add(novel_sha256: str, chunk_id: str) -> None:
    """Append `chunk_id` to the seen set + log file. Idempotent."""
    s = _load(novel_sha256)
    if chunk_id in s:
        return
    s.add(chunk_id)
    paths.SEEN_DIR.mkdir(parents=True, exist_ok=True)
    f = paths.seen_file(novel_sha256)
    with f.open("a", encoding="utf-8") as h:
        h.write(chunk_id + "\n")
