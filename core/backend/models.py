"""Echo-Quill Alchemist — Pydantic black-boxes.

Every state mutation in the system flows through these models. The point isn't validation
for its own sake — it's that *every* state object carries lifespan / hit_count semantics
so the engine cannot accidentally produce unbounded memory growth or unscored candidates.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _short_id() -> str:
    return uuid.uuid4().hex[:8]


# ---------------------------------------------------------------------------
# Core domain
# ---------------------------------------------------------------------------

class StyleRule(BaseModel):
    """A self-extracted style/voice rule with mandatory lifecycle counters."""

    id: str = Field(default_factory=_short_id)
    description: str
    lifespan: int = 15            # ticks remaining before forced retirement
    initial_lifespan: int = 15    # for UI heatmap normalization
    hit_count: int = 0            # cumulative number of passages that exhibited this rule
    born_at: datetime = Field(default_factory=_utcnow)
    last_hit_at: Optional[datetime] = None


class Candidate(BaseModel):
    text: str
    semantic_score: float = 0.0    # MiniLM cosine vs ground truth
    rouge_score: float = 0.0       # ROUGE-L F1 vs ground truth
    composite_score: float = 0.0   # alpha * semantic + beta * rouge
    is_hard_negative: bool = False


class DPOPair(BaseModel):
    """A direct preference pair, persisted both in-memory and to data/dpo.jsonl."""

    id: str = Field(default_factory=_short_id)
    prompt: str
    chosen: str
    rejected: str
    chosen_score: float
    rejected_score: float
    margin: float
    reason: str = "best_vs_hard_negative"
    created_at: datetime = Field(default_factory=_utcnow)


class CanonEntity(BaseModel):
    """A character / place / item / term extracted from training text.

    Lives in `corpora/<corpus_id>/canon.jsonl`. Embedding is stored separately
    in `embeddings/<corpus_id>.canon.npz`, keyed by `id`, so the jsonl stays
    compact and human-readable.
    """

    id: str = Field(default_factory=_short_id)
    type: Literal["character", "place", "item", "term"]
    canonical_name: str
    aliases: List[str] = Field(default_factory=list)
    attributes: Dict[str, str] = Field(default_factory=dict)

    # provenance — every entry is tagged so rollback / confidence weighting works
    source: Literal["training", "approved", "llm_inferred"] = "training"
    corpus_id: str
    confidence: float = 1.0  # 1.0 training, 0.7 approved, 0.5 inferred

    hit_count: int = 0
    born_at: datetime = Field(default_factory=_utcnow)
    last_seen_at: datetime = Field(default_factory=_utcnow)
    last_seen_chunk: int = 0


class PlotEvent(BaseModel):
    """A discrete narrative event extracted from training text.

    Append-only — events are never mutated or culled (lifespan = ∞). Rollback
    happens at the corpus-bundle level, not per event.
    """

    id: str = Field(default_factory=_short_id)
    summary: str
    primary_actors: List[str] = Field(default_factory=list)
    location: Optional[str] = None
    chapter_marker: Optional[str] = None

    source: Literal["training", "approved", "llm_inferred"] = "training"
    corpus_id: str
    confidence: float = 1.0

    born_at: datetime = Field(default_factory=_utcnow)
    chunk_index: int = 0


class AlchemistState(BaseModel):
    """Runtime state for ONE corpus. Engine swaps between states on corpus switch."""

    corpus_id: Optional[str] = None
    rules: List[StyleRule] = Field(default_factory=list)
    arena_candidates: List[Candidate] = Field(default_factory=list)
    arena_hard_negative: Optional[Candidate] = None
    dpo_pairs: List[DPOPair] = Field(default_factory=list)
    logs: List[str] = Field(default_factory=list)
    current_phase: str = "idle"
    chunks_processed: int = 0
    last_context_preview: str = ""
    last_truth_preview: str = ""
    canon_count: int = 0  # quick UI summary; full canon lives in CanonStore
    plot_count: int = 0


# ---------------------------------------------------------------------------
# Wire formats
# ---------------------------------------------------------------------------

WSMessageType = Literal[
    "snapshot",      # full state on (re)connect
    "log",           # append a log line
    "phase",         # phase transition (now also: canon, plot)
    "rules",         # rule list mutation
    "arena",         # candidate update
    "dpo",           # one new DPO pair
    "canon",         # canon delta (new/updated entities)
    "plot",          # plot delta (new events)
    "chunk_start",   # starting a chunk
    "chunk_done",    # finished a chunk
    "corpus_switch", # active corpus changed
]


class WSMessage(BaseModel):
    type: WSMessageType
    payload: Any
    ts: datetime = Field(default_factory=_utcnow)


class TrainingRequest(BaseModel):
    context: str
    truth: str

    # PR-3: corpus binding. `corpus_id` is "<layer>/<bundle>" e.g.
    # "original/abc123def456" or "user/20260528_x7k2". Required for new
    # callers; older callers (manual curl) get a default mapping in the engine.
    corpus_id: Optional[str] = None
    layer: Optional[Literal["original", "user"]] = None

    # PR-2: idempotency + cursor metadata. All optional for manual callers.
    chunk_id: Optional[str] = None
    novel_sha256: Optional[str] = None
    novel_path: Optional[str] = None
    chunk_size: Optional[int] = None
    ctx_size: Optional[int] = None
    overlap: Optional[int] = None
    char_offset: Optional[int] = None


class TrainingResponse(BaseModel):
    accepted: bool
    chunk_index: int
    note: str = ""
