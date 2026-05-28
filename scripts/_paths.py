"""Shared path constants for skill scripts. Import as `from _paths import ...`.

Layout (PR-3+):
    repo_root/
      .env                  ← LLM keys (skill level)
      .env.example
      .echo-quill.state.json ← runtime PIDs (written by start_services.py)
      SKILL.md
      scripts/              ← these skill scripts (this file lives here)
      references/
      core/
        backend/
        frontend/
        data/
          corpora/<layer>/<bundle>/    ← one self-contained training bundle each
          archive/<layer>/<bundle>_<ts>/
          drafts/<ts>.txt
          embeddings/<corpus>.npz
          logs/
"""
from __future__ import annotations

from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPTS_DIR.parent

CORE_DIR = REPO_ROOT / "core"
BACKEND_DIR = CORE_DIR / "backend"
FRONTEND_DIR = CORE_DIR / "frontend"
DATA_DIR = CORE_DIR / "data"
CORPORA_DIR = DATA_DIR / "corpora"
ARCHIVE_DIR = DATA_DIR / "archive"
DRAFTS_DIR = DATA_DIR / "drafts"
LOGS_DIR = DATA_DIR / "logs"
INNER_SCRIPTS_DIR = CORE_DIR / "scripts"

ENV_FILE = REPO_ROOT / ".env"
ENV_EXAMPLE = REPO_ROOT / ".env.example"
STATE_FILE = REPO_ROOT / ".echo-quill.state.json"

BACKEND_PORT = 8000
FRONTEND_PORT = 5173
BACKEND_URL = f"http://localhost:{BACKEND_PORT}"
FRONTEND_URL = f"http://localhost:{FRONTEND_PORT}"
WS_URL = f"ws://localhost:{BACKEND_PORT}/ws/alchemist"


def ensure_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    LOGS_DIR.mkdir(parents=True, exist_ok=True)


def count_dpo_pairs_on_disk() -> int:
    """Sum DPO pair counts across every corpus bundle. Replaces the old
    single-file `DPO_FILE` line counter — under the corpus-scoped layout the
    DPO log is partitioned by bundle."""
    if not CORPORA_DIR.exists():
        return 0
    total = 0
    for layer_dir in CORPORA_DIR.iterdir():
        if not layer_dir.is_dir():
            continue
        for bundle in layer_dir.iterdir():
            f = bundle / "dpo.jsonl"
            if f.exists():
                try:
                    with f.open("r", encoding="utf-8") as h:
                        total += sum(1 for line in h if line.strip())
                except OSError:
                    pass
    return total


def list_corpora() -> list[str]:
    """Discover all `<layer>/<bundle>` corpus ids on disk, newest-mtime first."""
    if not CORPORA_DIR.exists():
        return []
    pairs: list[tuple[float, str]] = []
    for layer_dir in CORPORA_DIR.iterdir():
        if not layer_dir.is_dir():
            continue
        for bundle in layer_dir.iterdir():
            if not bundle.is_dir():
                continue
            try:
                mtime = bundle.stat().st_mtime
            except OSError:
                mtime = 0.0
            pairs.append((mtime, f"{layer_dir.name}/{bundle.name}"))
    pairs.sort(reverse=True)
    return [cid for _, cid in pairs]

