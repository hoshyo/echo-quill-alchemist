"""Per-corpus chunk_id idempotency log.

Storage: `corpora/<corpus_id>/seen.txt`, one chunk_id per line, append-only.
Loaded into an in-memory `set[str]` on first access for O(1) `contains()`.

Cache key is `corpus_id` (not novel_sha256), so each bundle has its own
idempotency space — the same chunk_id from different bundles won't collide.
"""
from __future__ import annotations

from typing import Dict, Set

from backend.persistence import paths

_caches: Dict[str, Set[str]] = {}


def _load(corpus_id: str) -> Set[str]:
    cached = _caches.get(corpus_id)
    if cached is not None:
        return cached
    s: Set[str] = set()
    f = paths.corpus_seen(corpus_id)
    if f.exists():
        try:
            for line in f.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line:
                    s.add(line)
        except OSError:
            pass
    _caches[corpus_id] = s
    return s


def contains(corpus_id: str, chunk_id: str) -> bool:
    return chunk_id in _load(corpus_id)


def add(corpus_id: str, chunk_id: str) -> None:
    s = _load(corpus_id)
    if chunk_id in s:
        return
    s.add(chunk_id)
    paths.ensure_corpus_dir(corpus_id)
    f = paths.corpus_seen(corpus_id)
    with f.open("a", encoding="utf-8") as h:
        h.write(chunk_id + "\n")


def drop_cache(corpus_id: str) -> None:
    """Forget the in-memory set for `corpus_id`. Used by rollback / archive."""
    _caches.pop(corpus_id, None)
