"""DPO training-log replay.

`engine.py::_persist_dpo` appends one JSON line per DPOPair to `dpo.jsonl`. That
file is the authoritative store; the in-memory list `AlchemistState.dpo_pairs`
is just a live cache used by `/infer`'s few-shot selector.

On every backend boot we replay the log into the in-memory list so that
`/infer`'s few-shot pool is non-empty after a restart. Pure recovery — no new
behavior, no rewriting, no deduping (the log is append-only and trusted).

Malformed lines (truncation, schema drift) are tolerated: they're skipped with
a stderr note rather than aborting the boot. Returning a partial list is
strictly better than refusing to start.
"""
from __future__ import annotations

from typing import List

from backend.models import DPOPair
from backend.persistence import paths


def load_pairs() -> List[DPOPair]:
    """Replay `dpo.jsonl` into a list of DPOPair. Returns [] if the file is absent."""
    f = paths.DPO_FILE
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
                # Stay on stderr; the lifespan logger isn't available here.
                print(f"[dpo_log] skipped {f.name}:{lineno} — {e!r}")
    if skipped:
        print(f"[dpo_log] replayed {len(pairs)} pairs, skipped {skipped} malformed")
    return pairs
