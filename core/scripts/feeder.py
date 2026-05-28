"""Echo-Quill Alchemist feeder.

Reads a novel `.txt`, slides a window over it, and feeds successive
(context, truth) pairs into the running backend at /trigger_training.

Each chunk:
  - context = preceding `--ctx` characters
  - truth   = the next `--chunk_size` characters

Resume semantics (PR-2)
-----------------------
On startup the feeder hashes the novel (sha256), GETs `/progress?novel_sha256=...`,
and if the backend already has a cursor with matching slicing parameters it
auto-jumps to the next un-processed chunk. The feeder also tags every chunk
with a deterministic `chunk_id` so the backend can short-circuit duplicates
even if the feeder forgets — belt-and-braces.

By default the feeder waits for the backend queue to drain below `--max_queue`
before sending the next chunk. To go full throttle: `--max_queue 999`.
Pass `--no-resume` to ignore any saved cursor and start fresh.

Usage:
  python scripts/feeder.py --path my_novel.txt
  python scripts/feeder.py --path my_novel.txt --chunk_size 600 --ctx 1200 --gap 0.5
  python scripts/feeder.py --path my_novel.txt --no-resume
"""
from __future__ import annotations

import argparse
import hashlib
import sys
import time
from pathlib import Path
from typing import Iterator, Tuple

import httpx


def file_sha256(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for buf in iter(lambda: f.read(65536), b""):
            h.update(buf)
    return h.hexdigest()


def make_chunk_id(
    novel_sha256: str,
    chunk_size: int,
    ctx_size: int,
    overlap: int,
    char_offset: int,
) -> str:
    """Deterministic, human-readable id. Embeds slicing params so changing any
    of them yields a fresh id-space and previous progress doesn't apply."""
    return (
        f"{novel_sha256[:12]}:cs{chunk_size}:ctx{ctx_size}"
        f":ov{overlap}:off{char_offset}"
    )


def slide(
    text: str,
    chunk_size: int,
    ctx_size: int,
    overlap: int,
    base_offset: int = 0,
) -> Iterator[Tuple[int, str, str]]:
    """Yield (absolute_char_offset, ctx, truth) tuples.

    `base_offset` is added to the local index so the absolute offset reflects
    position in the *original* file, not in the post-`--start` slice.
    """
    n = len(text)
    i = 0
    step = max(1, chunk_size - overlap)
    while i + chunk_size <= n:
        ctx_start = max(0, i - ctx_size)
        ctx = text[ctx_start:i]
        truth = text[i : i + chunk_size]
        if ctx.strip() and truth.strip():
            yield (base_offset + i, ctx, truth)
        i += step


def resolve_resume_offset(
    cli: httpx.Client,
    url: str,
    novel_sha256: str,
    chunk_size: int,
    ctx_size: int,
    overlap: int,
    user_start: int,
) -> int:
    """Look up the per-novel cursor and return the resolved start offset.

    Returns user_start if no progress is found, params don't match, or the
    saved next_char_offset is behind user_start. Never returns < user_start.
    """
    try:
        r = cli.get(f"{url}/progress", params={"novel_sha256": novel_sha256}, timeout=5.0)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        print(f"[feeder] progress lookup failed ({e!r}); starting at --start={user_start}")
        return user_start

    if not data.get("found"):
        print(f"[feeder] no prior progress for this novel; starting at --start={user_start}")
        return user_start

    same = (
        data.get("chunk_size") == chunk_size
        and data.get("ctx") == ctx_size
        and data.get("overlap") == overlap
    )
    if not same:
        print(
            f"[feeder] progress exists but slicing params differ "
            f"(saved chunk_size/ctx/overlap = {data.get('chunk_size')}/"
            f"{data.get('ctx')}/{data.get('overlap')}). Starting from "
            f"--start={user_start}; pass --no-resume to silence this."
        )
        return user_start

    next_off = int(data.get("next_char_offset", 0))
    if next_off > user_start:
        print(
            f"[feeder] resuming at char_offset={next_off} "
            f"(committed up to {data.get('last_committed_char_offset')}, "
            f"chunk #{data.get('last_committed_chunk_index')})"
        )
        return next_off
    return user_start


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
    ap.add_argument("--no-resume", action="store_true",
                    help="ignore any saved cursor for this novel and start at --start")
    args = ap.parse_args()

    p = Path(args.path)
    if not p.exists():
        print(f"[feeder] file not found: {p}", file=sys.stderr)
        sys.exit(2)

    sha = file_sha256(p)
    print(f"[feeder] novel sha256[:12] = {sha[:12]}  ({p.name}, {p.stat().st_size:,} bytes)")

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

        # resume cursor
        start_offset = args.start
        if not args.no_resume:
            start_offset = resolve_resume_offset(
                cli, args.url, sha, args.chunk_size, args.ctx, args.overlap, args.start
            )

        raw = p.read_text(encoding="utf-8", errors="ignore")
        total = len(raw)
        if start_offset >= total:
            print(f"[feeder] start_offset ({start_offset}) >= file length ({total}); nothing to do.")
            return

        # Iterate the full slide and skip past `start_offset` rather than
        # slicing `raw` — this avoids losing the chunk at exactly `start_offset`
        # when ctx_size and step don't align nicely (e.g. chunk_size=500 ctx=800).
        print(f"[feeder] feeding from offset {start_offset:,} / {total:,} "
              f"({total - start_offset:,} chars remaining)")

        for char_offset, ctx, truth in slide(
            raw, args.chunk_size, args.ctx, args.overlap
        ):
            if char_offset < start_offset:
                continue
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

            chunk_id = make_chunk_id(sha, args.chunk_size, args.ctx, args.overlap, char_offset)
            payload = {
                "context": ctx,
                "truth": truth,
                "chunk_id": chunk_id,
                "novel_sha256": sha,
                "novel_path": str(p.resolve()),
                "chunk_size": args.chunk_size,
                "ctx_size": args.ctx,
                "overlap": args.overlap,
                "char_offset": char_offset,
            }
            try:
                r = cli.post(f"{args.url}/trigger_training", json=payload)
                r.raise_for_status()
                info = r.json()
            except Exception as e:
                print(f"[feeder] ! send failed: {e}", file=sys.stderr)
            else:
                # POST already succeeded — count it before the (possibly
                # encoding-fragile) preview print, so a Windows GBK terminal
                # choking on ▸ in truth can't fake a send failure.
                sent += 1
                try:
                    head = truth[:24].replace("\n", " ")
                    print(f"[feeder] +chunk @off={char_offset} "
                          f"#{info.get('chunk_index')} truth: {head!r}")
                except Exception as e:
                    print(f"[feeder] (preview print failed: {e!r})", file=sys.stderr)

            if args.gap > 0:
                time.sleep(args.gap)

    print(f"[feeder] done. sent {sent} chunks.")


if __name__ == "__main__":
    main()
