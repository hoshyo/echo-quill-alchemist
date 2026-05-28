"""Stop services tracked in .echo-quill.state.json.

If the state file is missing or stale (PID gone), we fall back to killing whatever
is bound to the canonical ports (8000, 5173).

Usage:
  python scripts/stop_services.py             # both
  python scripts/stop_services.py --backend
  python scripts/stop_services.py --frontend
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import signal
import subprocess
import sys

from _paths import BACKEND_PORT, FRONTEND_PORT, STATE_FILE

IS_WIN = platform.system() == "Windows"


def _kill_pid(pid: int) -> bool:
    if not pid:
        return False
    try:
        if IS_WIN:
            rc = subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(pid)],
                capture_output=True, text=True
            ).returncode
            return rc == 0
        os.kill(pid, signal.SIGTERM)
        return True
    except Exception:
        return False


def _kill_port(port: int) -> int:
    """Kill whatever owns `port`. Returns count killed."""
    killed = 0
    if IS_WIN:
        # PowerShell: Get-NetTCPConnection -LocalPort N
        ps = (
            f"$ids = (Get-NetTCPConnection -LocalPort {port} -State Listen "
            "-ErrorAction SilentlyContinue).OwningProcess; "
            "if ($ids) { foreach ($id in $ids) { Stop-Process -Id $id -Force "
            "-ErrorAction SilentlyContinue; Write-Host $id } }"
        )
        out = subprocess.run(
            ["powershell.exe", "-NoProfile", "-Command", ps],
            capture_output=True, text=True
        )
        for line in out.stdout.splitlines():
            line = line.strip()
            if line.isdigit():
                killed += 1
    else:
        out = subprocess.run(
            ["lsof", "-tiTCP:" + str(port), "-sTCP:LISTEN"],
            capture_output=True, text=True
        )
        for line in out.stdout.splitlines():
            line = line.strip()
            if line.isdigit():
                if _kill_pid(int(line)):
                    killed += 1
    return killed


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--backend", action="store_true")
    ap.add_argument("--frontend", action="store_true")
    args = ap.parse_args()
    do_b = args.backend or not (args.backend or args.frontend)
    do_f = args.frontend or not (args.backend or args.frontend)

    state: dict = {}
    if STATE_FILE.exists():
        try:
            state = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            state = {}

    report = {"backend": None, "frontend": None}

    if do_b:
        rec = state.get("backend") or {}
        ok = _kill_pid(rec.get("pid", 0))
        leftover = _kill_port(BACKEND_PORT)
        report["backend"] = {"pid_kill": ok, "port_kill": leftover}
        state.pop("backend", None)
    if do_f:
        rec = state.get("frontend") or {}
        ok = _kill_pid(rec.get("pid", 0))
        leftover = _kill_port(FRONTEND_PORT)
        report["frontend"] = {"pid_kill": ok, "port_kill": leftover}
        state.pop("frontend", None)

    if state:
        STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2),
                              encoding="utf-8")
    elif STATE_FILE.exists():
        STATE_FILE.unlink()

    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
