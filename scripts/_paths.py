"""Shared path constants for skill scripts. Import as `from _paths import ...`.

Layout:
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
          dpo.jsonl
          logs/
            backend.log
            frontend.log
        scripts/
          feeder.py         ← internal feeder used by scripts/train.py
"""
from __future__ import annotations

from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPTS_DIR.parent

CORE_DIR = REPO_ROOT / "core"
BACKEND_DIR = CORE_DIR / "backend"
FRONTEND_DIR = CORE_DIR / "frontend"
DATA_DIR = CORE_DIR / "data"
LOGS_DIR = DATA_DIR / "logs"
INNER_SCRIPTS_DIR = CORE_DIR / "scripts"

DPO_FILE = DATA_DIR / "dpo.jsonl"
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
