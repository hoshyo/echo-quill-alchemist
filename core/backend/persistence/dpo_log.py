"""DPO training-log replay — per-corpus.

Each corpus has its own append-only `dpo.jsonl`. On corpus switch (or server
restart) `load_pairs(corpus_id)` rebuilds the in-memory list used by /infer's
few-shot selector.

Malformed lines are tolerated: skipped with a stderr note rather than aborting.
"""
from __future__ import annotations

from typing import List

from backend.models import DPOPair
from backend.persistence import paths


def load_pairs(corpus_id: str) -> List[DPOPair]:
    """Replay `corpora/<id>/dpo.jsonl` into a list. Returns [] if absent."""
    f = paths.corpus_dpo(corpus_id)
    if not f.exists():
        return []

    pairs: List[DPOPair] = []
    skipped = 0
    with f.open("r", encoding="utf-8") as h:
        for lineno, raw in enumerate(h, 1):
            line = raw.strip()
            if not line:
                continue
            try:
                pairs.append(DPOPair.model_validate_json(line))
            except Exception as e:
                skipped += 1
                print(f"[dpo_log] skipped {f}:{lineno} — {e!r}")
    if skipped:
        print(f"[dpo_log] {corpus_id}: replayed {len(pairs)}, skipped {skipped} malformed")
    return pairs


def append_pair(corpus_id: str, pair: DPOPair) -> None:
    """Append a single DPO pair to this corpus's log."""
    paths.ensure_corpus_dir(corpus_id)
    f = paths.corpus_dpo(corpus_id)
    with f.open("a", encoding="utf-8") as h:
        h.write(pair.model_dump_json() + "\n")
