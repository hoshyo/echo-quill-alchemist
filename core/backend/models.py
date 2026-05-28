"""Echo-Quill Alchemist — Pydantic black-boxes.

Every state mutation in the system flows through these models. The point isn't validation
for its own sake — it's that *every* state object carries lifespan / hit_count semantics
so the engine cannot accidentally produce unbounded memory growth or unscored candidates.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, List, Literal, Optional

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


class AlchemistState(BaseModel):
    rules: List[StyleRule] = Field(default_factory=list)
    arena_candidates: List[Candidate] = Field(default_factory=list)
    arena_hard_negative: Optional[Candidate] = None
    dpo_pairs: List[DPOPair] = Field(default_factory=list)
    logs: List[str] = Field(default_factory=list)
    current_phase: str = "idle"
    chunks_processed: int = 0
    last_context_preview: str = ""
    last_truth_preview: str = ""


# ---------------------------------------------------------------------------
# Wire formats
# ---------------------------------------------------------------------------

WSMessageType = Literal[
    "snapshot",      # full state on (re)connect
    "log",           # append a log line
    "phase",         # phase transition
    "rules",         # rule list mutation
    "arena",         # candidate update
    "dpo",           # one new DPO pair
    "chunk_start",   # starting a chunk
    "chunk_done",    # finished a chunk
]


class WSMessage(BaseModel):
    type: WSMessageType
    payload: Any
    ts: datetime = Field(default_factory=_utcnow)


class TrainingRequest(BaseModel):
    context: str
    truth: str

    # PR-2: idempotency + cursor metadata. All optional so manual /trigger_training
    # callers (e.g. curl) still work. The feeder always populates them.
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
