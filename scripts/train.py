"""High-level: feed a novel into a running backend.

This is the script the skill calls when the user says "train on novel X". It assumes the
SKILL has already verified prerequisites (deps installed, .env present, services up) by
running doctor.py + start_services.py before this. If those preconditions aren't met,
this script fails fast with a precise reason — it does NOT try to fix them itself.

Usage:
  python scripts/train.py --path D:/novels/三体.txt
  python scripts/train.py --path X.txt --chunk_size 600 --ctx 1200 --limit 10
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import urllib.request

from _paths import BACKEND_URL, INNER_SCRIPTS_DIR


def _backend_alive() -> bool:
    try:
        with urllib.request.urlopen(f"{BACKEND_URL}/healthz", timeout=2.0) as r:
            return r.status == 200
    except Exception:
        return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--path", required=True, help="path to novel .txt (utf-8)")
    ap.add_argument("--chunk_size", type=int, default=500)
    ap.add_argument("--ctx", type=int, default=800)
    ap.add_argument("--overlap", type=int, default=0)
    ap.add_argument("--gap", type=float, default=0.5)
    ap.add_argument("--max_queue", type=int, default=1)
    ap.add_argument("--start", type=int, default=0)
    ap.add_argument("--limit", type=int, default=0, help="max chunks to send (0=all)")
    args = ap.parse_args()

    if not _backend_alive():
        print(
            "[train] backend not responding at "
            f"{BACKEND_URL} — run scripts/start_services.py first",
            file=sys.stderr,
        )
        return 2

    feeder = INNER_SCRIPTS_DIR / "feeder.py"
    if not feeder.exists():
        print(f"[train] internal feeder missing: {feeder}", file=sys.stderr)
        return 3

    cmd = [
        sys.executable, str(feeder),
        "--path", args.path,
        "--chunk_size", str(args.chunk_size),
        "--ctx", str(args.ctx),
        "--overlap", str(args.overlap),
        "--gap", str(args.gap),
        "--max_queue", str(args.max_queue),
        "--start", str(args.start),
        "--limit", str(args.limit),
        "--url", BACKEND_URL,
    ]
    return subprocess.run(cmd).returncode


if __name__ == "__main__":
    raise SystemExit(main())
