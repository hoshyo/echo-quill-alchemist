"""Start backend (FastAPI) and frontend (Vite) as detached background processes.

Idempotent: if a service is already responding on its port, we skip the spawn and reuse it.
PIDs + log paths are written to .echo-quill.state.json so other skill scripts (and
stop_services.py) can find them.

Usage:
  python scripts/start_services.py             # both
  python scripts/start_services.py --backend
  python scripts/start_services.py --frontend
  python scripts/start_services.py --no-wait   # don't poll for readiness; return immediately
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone

from _paths import (
    BACKEND_DIR,
    BACKEND_PORT,
    BACKEND_URL,
    CORE_DIR,
    FRONTEND_DIR,
    FRONTEND_PORT,
    FRONTEND_URL,
    LOGS_DIR,
    REPO_ROOT,
    STATE_FILE,
    ensure_dirs,
)


IS_WIN = platform.system() == "Windows"


def _read_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _write_state(state: dict) -> None:
    STATE_FILE.write_text(
        json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _is_up(url: str, timeout: float = 1.5) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return r.status == 200
    except Exception:
        return False


def _spawn(cmd: list[str], cwd: str, log_path) -> int:
    """Spawn a detached child. Returns PID. stdout/stderr → log file."""
    log = open(log_path, "ab")
    kwargs: dict = dict(stdout=log, stderr=subprocess.STDOUT, cwd=cwd, env=os.environ.copy())
    if IS_WIN:
        kwargs["creationflags"] = (
            subprocess.CREATE_NEW_PROCESS_GROUP | 0x00000008  # DETACHED_PROCESS
        )
        # On Windows we need shell=True for `npm` (it's npm.cmd, found via PATHEXT)
        kwargs["shell"] = True
    else:
        kwargs["start_new_session"] = True
    proc = subprocess.Popen(cmd, **kwargs)
    return proc.pid


def _wait_until(url: str, label: str, timeout: float = 120.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if _is_up(url):
            return True
        time.sleep(1.0)
    print(f"[start_services] {label} did not become ready within {timeout:.0f}s",
          file=sys.stderr)
    return False


def start_backend(state: dict, wait: bool) -> dict:
    if _is_up(f"{BACKEND_URL}/healthz"):
        existing = state.get("backend") or {}
        existing["up"] = True
        existing.setdefault("port", BACKEND_PORT)
        existing.setdefault("started_at", datetime.now(timezone.utc).isoformat())
        existing.setdefault("reused", True)
        return existing

    log_path = LOGS_DIR / "backend.log"
    cmd = [sys.executable, str(BACKEND_DIR / "server.py")]
    pid = _spawn(cmd, cwd=str(CORE_DIR), log_path=log_path)
    rec = {
        "pid": pid,
        "port": BACKEND_PORT,
        "url": BACKEND_URL,
        "log_file": str(log_path),
        "started_at": datetime.now(timezone.utc).isoformat(),
        "up": False,
    }
    if wait:
        rec["up"] = _wait_until(f"{BACKEND_URL}/healthz", "backend", timeout=180.0)
    return rec


def start_frontend(state: dict, wait: bool) -> dict:
    if _is_up(FRONTEND_URL):
        existing = state.get("frontend") or {}
        existing["up"] = True
        existing.setdefault("port", FRONTEND_PORT)
        existing.setdefault("started_at", datetime.now(timezone.utc).isoformat())
        existing.setdefault("reused", True)
        return existing

    log_path = LOGS_DIR / "frontend.log"
    # `npm run dev` resolves vite from frontend/node_modules/.bin
    cmd = ["npm", "run", "dev"] if IS_WIN else ["npm", "run", "dev"]
    pid = _spawn(cmd, cwd=str(FRONTEND_DIR), log_path=log_path)
    rec = {
        "pid": pid,
        "port": FRONTEND_PORT,
        "url": FRONTEND_URL,
        "log_file": str(log_path),
        "started_at": datetime.now(timezone.utc).isoformat(),
        "up": False,
    }
    if wait:
        rec["up"] = _wait_until(FRONTEND_URL, "frontend", timeout=120.0)
    return rec


def main() -> int:
    ensure_dirs()
    ap = argparse.ArgumentParser()
    ap.add_argument("--backend", action="store_true")
    ap.add_argument("--frontend", action="store_true")
    ap.add_argument("--no-wait", action="store_true")
    args = ap.parse_args()
    do_b = args.backend or not (args.backend or args.frontend)
    do_f = args.frontend or not (args.backend or args.frontend)
    wait = not args.no_wait

    state = _read_state()
    if do_b:
        state["backend"] = start_backend(state, wait=wait)
    if do_f:
        state["frontend"] = start_frontend(state, wait=wait)
    _write_state(state)
    print(json.dumps(state, ensure_ascii=False, indent=2))

    failed = []
    if do_b and not state.get("backend", {}).get("up"):
        failed.append("backend")
    if do_f and not state.get("frontend", {}).get("up"):
        failed.append("frontend")
    return 0 if not failed else 3


if __name__ == "__main__":
    raise SystemExit(main())
