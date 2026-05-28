"""CanonStore — per-corpus persistent canon of characters / places / items / terms.

Storage
-------
- `corpora/<corpus_id>/canon.jsonl`  : one CanonEntity per line; replaced on
  each ingest via atomic full-rewrite (entities mutate when aliases merge).
- `embeddings/<corpus_id_safe>.canon.npz` : parallel 1024-d bge-m3 embeddings,
  keyed by entity id. Recomputable from the jsonl — safe to delete.

Dedup
-----
v1 uses **alias-overlap dedup**: a newly extracted entity with any name in
{canonical_name, *aliases} matching an existing entity's name set is treated
as the same entity, attributes merged. This handles the dominant case
(同一角色多个别名) without depending on embedding similarity tuning.

Embeddings are computed at ingest time so that PR-3.5's retrieval layer has
them ready. They're not used for dedup in v1.

Provenance
----------
Every entity carries `source` (training | approved | llm_inferred), `corpus_id`,
and `confidence`. Rollback works by deleting (archiving) the entire bundle dir.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Set

import numpy as np

from backend.models import CanonEntity
from backend.persistence import paths
from backend.persistence.atomic_io import write_text_atomic


class CanonStore:
    """In-memory mirror of one corpus's canon.jsonl + embeddings npz."""

    def __init__(self, corpus_id: str):
        self.corpus_id = corpus_id
        self.entities: List[CanonEntity] = []
        self.embeddings: Dict[str, np.ndarray] = {}  # id → 1024-d
        self._load()

    # ----- load / save -----

    def _load(self) -> None:
        f = paths.corpus_canon(self.corpus_id)
        if f.exists():
            with f.open("r", encoding="utf-8") as h:
                for line in h:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        self.entities.append(CanonEntity.model_validate_json(line))
                    except Exception:
                        continue

        emb_f = paths.corpus_canon_emb(self.corpus_id)
        if emb_f.exists():
            try:
                data = np.load(emb_f, allow_pickle=False)
                ids = data["ids"]
                vecs = data["vecs"]
                for i, eid in enumerate(ids):
                    self.embeddings[str(eid)] = vecs[i]
            except Exception:
                # embeddings are recomputable — fall back to empty cache
                self.embeddings = {}

    def _persist(self) -> None:
        paths.ensure_corpus_dir(self.corpus_id)
        # jsonl: atomic full-rewrite (entries mutate on merge)
        lines = [e.model_dump_json() for e in self.entities]
        write_text_atomic(paths.corpus_canon(self.corpus_id), "\n".join(lines) + ("\n" if lines else ""))

        # embeddings: save as npz; parallel ids[] and vecs[]
        paths.EMBEDDINGS_DIR.mkdir(parents=True, exist_ok=True)
        if self.embeddings:
            ids = np.array(list(self.embeddings.keys()))
            vecs = np.stack([self.embeddings[i] for i in ids])
            np.savez(paths.corpus_canon_emb(self.corpus_id), ids=ids, vecs=vecs)

    # ----- ingest -----

    def _index_by_name(self) -> Dict[str, CanonEntity]:
        """name → entity index for fast alias-overlap dedup."""
        ix: Dict[str, CanonEntity] = {}
        for e in self.entities:
            for n in {e.canonical_name, *e.aliases}:
                ix[n] = e
        return ix

    def ingest_records(
        self,
        records: List[dict],
        *,
        source: str = "training",
        chunk_index: int = 0,
        confidence: float = 1.0,
    ) -> List[CanonEntity]:
        """Merge LLM-extracted records into the store. Returns the deltas
        (new + updated entities) so the engine can broadcast them."""
        if not records:
            return []

        # alias-based dedup: any name overlap = same entity
        ix = self._index_by_name()
        deltas: List[CanonEntity] = []
        new_for_embed: List[CanonEntity] = []
        now = datetime.now(timezone.utc)

        for rec in records:
            names: Set[str] = {rec["canonical_name"], *rec.get("aliases", [])}
            match = None
            for n in names:
                if n in ix:
                    match = ix[n]
                    break

            if match is not None:
                # merge: union aliases, fill in missing attributes, bump counts
                existing_names = {match.canonical_name, *match.aliases}
                added_aliases = [a for a in names if a and a != match.canonical_name and a not in existing_names]
                if added_aliases:
                    match.aliases = list(match.aliases) + added_aliases
                for k, v in rec.get("attributes", {}).items():
                    if k not in match.attributes and v:
                        match.attributes[k] = v
                match.hit_count += 1
                match.last_seen_at = now
                match.last_seen_chunk = chunk_index
                # confidence: keep the higher (training > approved > inferred)
                if confidence > match.confidence:
                    match.confidence = confidence
                deltas.append(match)
            else:
                ent = CanonEntity(
                    type=rec["type"],
                    canonical_name=rec["canonical_name"],
                    aliases=list(rec.get("aliases", [])),
                    attributes=dict(rec.get("attributes", {})),
                    source=source,
                    corpus_id=self.corpus_id,
                    confidence=confidence,
                    last_seen_chunk=chunk_index,
                )
                self.entities.append(ent)
                # refresh the index so later records in this same batch can dedup
                for n in {ent.canonical_name, *ent.aliases}:
                    ix[n] = ent
                deltas.append(ent)
                new_for_embed.append(ent)

        # Compute embeddings for genuinely new entities only (merges reuse old vec)
        if new_for_embed:
            try:
                from backend.embedding.canon_embedder import CanonEmbedder
                texts = [self._embed_text(e) for e in new_for_embed]
                vecs = CanonEmbedder.encode(texts)
                for e, v in zip(new_for_embed, vecs):
                    self.embeddings[e.id] = v
            except Exception as ex:
                # bge-m3 unavailable (offline / first download failure). Skip
                # embeddings — retrieval falls back to alias-only matching.
                print(f"[canon] embedding skipped: {ex!r}")

        self._persist()
        return deltas

    @staticmethod
    def _embed_text(e: CanonEntity) -> str:
        """One short string per entity used as its retrievable representation."""
        parts = [e.canonical_name]
        if e.aliases:
            parts.append("/".join(e.aliases))
        for k, v in e.attributes.items():
            parts.append(f"{k}:{v}")
        return " | ".join(parts)


# ---------------------------------------------------------------------------
# Module-level cache: one store per corpus_id, lazy
# ---------------------------------------------------------------------------

_stores: Dict[str, CanonStore] = {}


def get(corpus_id: str) -> CanonStore:
    s = _stores.get(corpus_id)
    if s is None:
        s = CanonStore(corpus_id)
        _stores[corpus_id] = s
    return s


def drop_cache(corpus_id: str) -> None:
    _stores.pop(corpus_id, None)
