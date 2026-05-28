"""PlotStore — per-corpus append-only log of narrative events.

Storage
-------
`corpora/<corpus_id>/plot.jsonl` — one PlotEvent per line, append-only.
Unlike CanonStore, events are never mutated. The rationale: events have an
implicit causal/temporal slot — modifying one would silently break references
from later events. Rollback is bundle-level (delete the directory), not
per-event.

Dedup
-----
Minimal: dedup on summary string equality within the in-memory list. The LLM
extractor caps each chunk at 5 events; cross-chunk duplicates are tolerated
(they're cheap and act as recency reinforcement at retrieve time).
"""
from __future__ import annotations

from typing import Dict, List

from backend.models import PlotEvent
from backend.persistence import paths


class PlotStore:
    def __init__(self, corpus_id: str):
        self.corpus_id = corpus_id
        self.events: List[PlotEvent] = []
        self._summaries: set[str] = set()
        self._load()

    def _load(self) -> None:
        f = paths.corpus_plot(self.corpus_id)
        if not f.exists():
            return
        with f.open("r", encoding="utf-8") as h:
            for line in h:
                line = line.strip()
                if not line:
                    continue
                try:
                    ev = PlotEvent.model_validate_json(line)
                    self.events.append(ev)
                    self._summaries.add(ev.summary)
                except Exception:
                    continue

    def ingest_records(
        self,
        records: List[dict],
        *,
        source: str = "training",
        chunk_index: int = 0,
        confidence: float = 1.0,
    ) -> List[PlotEvent]:
        if not records:
            return []

        paths.ensure_corpus_dir(self.corpus_id)
        f = paths.corpus_plot(self.corpus_id)
        new: List[PlotEvent] = []
        with f.open("a", encoding="utf-8") as h:
            for rec in records:
                summary = rec["summary"]
                if summary in self._summaries:
                    continue
                ev = PlotEvent(
                    summary=summary,
                    primary_actors=list(rec.get("primary_actors", [])),
                    location=rec.get("location"),
                    chapter_marker=rec.get("chapter_marker"),
                    source=source,
                    corpus_id=self.corpus_id,
                    confidence=confidence,
                    chunk_index=chunk_index,
                )
                self.events.append(ev)
                self._summaries.add(summary)
                h.write(ev.model_dump_json() + "\n")
                new.append(ev)
        return new


_stores: Dict[str, PlotStore] = {}


def get(corpus_id: str) -> PlotStore:
    s = _stores.get(corpus_id)
    if s is None:
        s = PlotStore(corpus_id)
        _stores[corpus_id] = s
    return s


def drop_cache(corpus_id: str) -> None:
    _stores.pop(corpus_id, None)
