"""Echo-Quill Alchemist feeder.

Reads a novel `.txt`, slides a window over it, and feeds successive
(context, truth) pairs into the running backend at /trigger_training.

Each chunk:
  - context = preceding `--ctx` characters
  - truth   = the next `--chunk_size` characters

By default the feeder waits for the backend queue to drain below `--max_queue`
before sending the next chunk. This keeps memory bounded and makes the
dashboard readable. To go full throttle: `--max_queue 999`.

Usage:
  python scripts/feeder.py --path my_novel.txt
  python scripts/feeder.py --path my_novel.txt --chunk_size 600 --ctx 1200 --gap 0.5
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import httpx


def slide(text: str, chunk_size: int, ctx_size: int, overlap: int):
    n = len(text)
    i = 0
    step = max(1, chunk_size - overlap)
    while i + chunk_size <= n:
        ctx_start = max(0, i - ctx_size)
        ctx = text[ctx_start:i]
        truth = text[i : i + chunk_size]
        if ctx.strip() and truth.strip():
            yield ctx, truth
        i += step


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--path", required=True, help="path to novel .txt (utf-8)")
    ap.add_argument("--chunk_size", type=int, default=500, help="chars per truth chunk")
    ap.add_argument("--ctx", type=int, default=800, help="chars of preceding context")
    ap.add_argument("--overlap", type=int, default=0, help="overlap between successive chunks")
    ap.add_argument("--gap", type=float, default=0.5, help="hard sleep after each send (s)")
    ap.add_argument("--max_queue", type=int, default=1, help="back-pressure: wait until backend queue<this")
    ap.add_argument("--start", type=int, default=0, help="skip first N chars of the novel")
    ap.add_argument("--limit", type=int, default=0, help="max chunks to send (0 = all)")
    ap.add_argument("--url", default="http://localhost:8000")
    args = ap.parse_args()

    p = Path(args.path)
    if not p.exists():
        print(f"[feeder] file not found: {p}", file=sys.stderr)
        sys.exit(2)

    raw = p.read_text(encoding="utf-8", errors="ignore")
    if args.start:
        raw = raw[args.start:]
    print(f"[feeder] loaded {len(raw):,} chars from {p}")

    sent = 0
    with httpx.Client(timeout=30.0) as cli:
        # health check first
        try:
            h = cli.get(f"{args.url}/healthz")
            h.raise_for_status()
            print(f"[feeder] backend healthy: {h.json()}")
        except Exception as e:
            print(f"[feeder] backend not reachable at {args.url}: {e}", file=sys.stderr)
            sys.exit(3)

        for ctx, truth in slide(raw, args.chunk_size, args.ctx, args.overlap):
            if args.limit and sent >= args.limit:
                break

            # back-pressure: wait until queue drains
            while True:
                try:
                    q = cli.get(f"{args.url}/healthz", timeout=5.0).json().get("queued", 0)
                except Exception:
                    q = 0
                if q < args.max_queue:
                    break
                time.sleep(0.5)

            payload = {"context": ctx, "truth": truth}
            try:
                r = cli.post(f"{args.url}/trigger_training", json=payload)
                r.raise_for_status()
                info = r.json()
                head = truth[:24].replace("\n", " ")
                print(f"[feeder] +chunk #{info.get('chunk_index')} truth: {head!r}…")
                sent += 1
            except Exception as e:
                print(f"[feeder] ! send failed: {e}", file=sys.stderr)

            if args.gap > 0:
                time.sleep(args.gap)

    print(f"[feeder] done. sent {sent} chunks.")


if __name__ == "__main__":
    main()
