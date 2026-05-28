"""Install backend (pip) and frontend (npm) deps. Idempotent.

Skill router calls this only AFTER asking the user (the install pulls torch + MiniLM, ~2GB
on first run). Use `--backend` / `--frontend` to install only one side.

Examples:
  python scripts/install_deps.py             # both
  python scripts/install_deps.py --backend
  python scripts/install_deps.py --frontend
"""
from __future__ import annotations

import argparse
import subprocess
import sys

from _paths import FRONTEND_DIR

PY_PACKAGES = [
    "fastapi",
    "uvicorn[standard]",
    "websockets",
    "pydantic",
    "sentence-transformers",
    "numpy",
    "rouge-score",
    "httpx",
    "python-dotenv",
]


def install_backend() -> int:
    print("[install_deps] pip install backend deps (this can take 5–15 min on first run)...",
          flush=True)
    cmd = [sys.executable, "-m", "pip", "install", *PY_PACKAGES]
    rc = subprocess.run(cmd).returncode
    if rc != 0:
        print(f"[install_deps] pip install failed (exit {rc})", file=sys.stderr)
    return rc


def install_frontend() -> int:
    if not FRONTEND_DIR.exists():
        print(f"[install_deps] frontend dir missing: {FRONTEND_DIR}", file=sys.stderr)
        return 2
    print("[install_deps] npm install in core/frontend...", flush=True)
    rc = subprocess.run(["npm", "install"], cwd=str(FRONTEND_DIR), shell=True).returncode
    if rc != 0:
        print(f"[install_deps] npm install failed (exit {rc})", file=sys.stderr)
    return rc


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--backend", action="store_true")
    ap.add_argument("--frontend", action="store_true")
    args = ap.parse_args()
    do_b = args.backend or not (args.backend or args.frontend)
    do_f = args.frontend or not (args.backend or args.frontend)
    rc = 0
    if do_b:
        rc |= install_backend()
    if do_f:
        rc |= install_frontend()
    if rc == 0:
        print("[install_deps] done.")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
