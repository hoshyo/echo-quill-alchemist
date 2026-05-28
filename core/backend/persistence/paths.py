"""Centralized filesystem layout — corpus-scoped (PR-3).

Every training bundle lives at `core/data/corpora/<layer>/<bundle_id>/` and is
fully self-contained: deleting that directory rolls back the bundle's effect on
canon/plot/rules/dpo. Reads at retrieve time union all bundles.

`corpus_id` is the relative path under `corpora/`, e.g. "original/abc123def456"
or "user/20260528_x7k2". One field encodes both layer and bundle identity.
"""
from __future__ import annotations

from pathlib import Path

# core/backend/persistence/paths.py → core
_CORE_DIR = Path(__file__).resolve().parent.parent.parent

DATA_DIR: Path = _CORE_DIR / "data"

# Top-level subtrees
CORPORA_DIR: Path = DATA_DIR / "corpora"
ARCHIVE_DIR: Path = DATA_DIR / "archive"
DRAFTS_DIR: Path = DATA_DIR / "drafts"
EMBEDDINGS_DIR: Path = DATA_DIR / "embeddings"
LOGS_DIR: Path = DATA_DIR / "logs"

# ---------------------------------------------------------------------------
# Per-corpus layout
# ---------------------------------------------------------------------------

def corpus_dir(corpus_id: str) -> Path:
    """`corpora/<layer>/<bundle>/` — every persisted file for one bundle."""
    return CORPORA_DIR / corpus_id


def corpus_meta(corpus_id: str) -> Path:
    return corpus_dir(corpus_id) / "meta.json"


def corpus_text(corpus_id: str) -> Path:
    """Source text — `novel.txt` for original layer, `text.txt` for user layer.
    Caller decides which name; we just resolve to the canonical filename."""
    layer = corpus_id.split("/", 1)[0] if "/" in corpus_id else ""
    name = "text.txt" if layer == "user" else "novel.txt"
    return corpus_dir(corpus_id) / name


def corpus_snapshot(corpus_id: str) -> Path:
    return corpus_dir(corpus_id) / "snapshot.json"


def corpus_snapshot_bak(corpus_id: str) -> Path:
    return corpus_dir(corpus_id) / "snapshot.json.bak"


def corpus_dpo(corpus_id: str) -> Path:
    return corpus_dir(corpus_id) / "dpo.jsonl"


def corpus_progress(corpus_id: str) -> Path:
    return corpus_dir(corpus_id) / "progress.json"


def corpus_seen(corpus_id: str) -> Path:
    return corpus_dir(corpus_id) / "seen.txt"


def corpus_canon(corpus_id: str) -> Path:
    return corpus_dir(corpus_id) / "canon.jsonl"


def corpus_plot(corpus_id: str) -> Path:
    return corpus_dir(corpus_id) / "plot.jsonl"


def corpus_canon_emb(corpus_id: str) -> Path:
    """Cached numpy embeddings for this corpus's canon entities (1024-d, bge-m3).
    Re-buildable from canon.jsonl, so safe to delete to reclaim space."""
    safe = corpus_id.replace("/", "_")
    return EMBEDDINGS_DIR / f"{safe}.canon.npz"


# ---------------------------------------------------------------------------
# Discovery helpers (used by /infer fallback + rollback CLI)
# ---------------------------------------------------------------------------

def list_corpora() -> list[str]:
    """All corpus_ids on disk, sorted by mtime descending (newest first)."""
    if not CORPORA_DIR.exists():
        return []
    out: list[tuple[float, str]] = []
    for layer_dir in CORPORA_DIR.iterdir():
        if not layer_dir.is_dir():
            continue
        for bundle in layer_dir.iterdir():
            if not bundle.is_dir():
                continue
            cid = f"{layer_dir.name}/{bundle.name}"
            try:
                mtime = bundle.stat().st_mtime
            except OSError:
                mtime = 0.0
            out.append((mtime, cid))
    out.sort(reverse=True)
    return [cid for _, cid in out]


def most_recent_corpus() -> str | None:
    """The corpus modified most recently — used by /infer when no corpus is given."""
    cs = list_corpora()
    return cs[0] if cs else None


def ensure_corpus_dir(corpus_id: str) -> None:
    corpus_dir(corpus_id).mkdir(parents=True, exist_ok=True)


def ensure_top_dirs() -> None:
    """Idempotent. Top-level scaffolding that doesn't depend on a corpus_id."""
    DRAFTS_DIR.mkdir(parents=True, exist_ok=True)
    EMBEDDINGS_DIR.mkdir(parents=True, exist_ok=True)
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
