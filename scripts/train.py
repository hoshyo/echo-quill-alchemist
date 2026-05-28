"""High-level: feed a novel into a running backend.

This is the script the skill calls when the user says "train on novel X".
It computes a corpus_id from the layer + novel hash, ensures the corpus
bundle dir exists, writes meta.json, and delegates the actual chunk-by-chunk
training to core/scripts/feeder.py.

Layers
------
- `original` (default) : training the source novel. corpus_id = "original/<sha[:12]>"
- `user`               : training a user-written continuation. corpus_id =
                         "user/<YYYYMMDDhhmmss>_<rand4>". Created fresh each call
                         so each "train this continuation" produces a separate,
                         independently-rollbackable bundle.

Usage:
  python scripts/train.py --path D:/novels/三体.txt
  python scripts/train.py --path my_continuation.txt --layer user
  python scripts/train.py --path X.txt --chunk_size 600 --ctx 1200 --limit 10
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
import shutil
import string
import subprocess
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from _paths import BACKEND_URL, INNER_SCRIPTS_DIR


def _backend_alive() -> bool:
    try:
        with urllib.request.urlopen(f"{BACKEND_URL}/healthz", timeout=2.0) as r:
            return r.status == 200
    except Exception:
        return False


def _sha256(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for buf in iter(lambda: f.read(65536), b""):
            h.update(buf)
    return h.hexdigest()


def _allocate_corpus_id(layer: str, sha: str) -> str:
    if layer == "original":
        return f"original/{sha[:12]}"
    # user: timestamp + 4 random chars; collisions astronomically unlikely
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    rnd = "".join(random.choices(string.ascii_lowercase + string.digits, k=4))
    return f"user/{ts}_{rnd}"


def _corpora_root() -> Path:
    """Mirror persistence.paths.CORPORA_DIR without importing the backend package."""
    return Path(__file__).resolve().parent.parent / "core" / "data" / "corpora"


def _ensure_bundle(corpus_id: str, novel_path: Path, sha: str, layer: str) -> Path:
    """Create corpora/<corpus_id>/ with meta.json + a copy of the source text."""
    bundle = _corpora_root() / corpus_id
    bundle.mkdir(parents=True, exist_ok=True)

    meta_path = bundle / "meta.json"
    if not meta_path.exists():
        meta = {
            "corpus_id": corpus_id,
            "layer": layer,
            "source_path": str(novel_path.resolve()),
            "source_sha256": sha,
            "source_size": novel_path.stat().st_size,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

        # Snapshot the source text into the bundle so rollback can re-train.
        # original layer → novel.txt, user layer → text.txt.
        dest_name = "text.txt" if layer == "user" else "novel.txt"
        try:
            shutil.copyfile(novel_path, bundle / dest_name)
        except Exception as e:
            print(f"[train] warning: could not copy source into bundle: {e!r}", file=sys.stderr)

    return bundle


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--path", required=True, help="path to source .txt (utf-8)")
    ap.add_argument("--layer", choices=["original", "user"], default="original",
                    help="original = source novel; user = continuation to layer on top")
    ap.add_argument("--chunk_size", type=int, default=500)
    ap.add_argument("--ctx", type=int, default=800)
    ap.add_argument("--overlap", type=int, default=0)
    ap.add_argument("--gap", type=float, default=0.5)
    ap.add_argument("--max_queue", type=int, default=1)
    ap.add_argument("--start", type=int, default=0)
    ap.add_argument("--limit", type=int, default=0, help="max chunks to send (0=all)")
    ap.add_argument("--no-resume", action="store_true",
                    help="ignore saved cursor for this corpus")
    args = ap.parse_args()

    if not _backend_alive():
        print(
            "[train] backend not responding at "
            f"{BACKEND_URL} — run scripts/start_services.py first",
            file=sys.stderr,
        )
        return 2

    src = Path(args.path)
    if not src.exists():
        print(f"[train] source file not found: {src}", file=sys.stderr)
        return 4

    sha = _sha256(src)
    corpus_id = _allocate_corpus_id(args.layer, sha)
    bundle = _ensure_bundle(corpus_id, src, sha, args.layer)
    print(f"[train] corpus_id = {corpus_id}  (bundle = {bundle})")

    feeder = INNER_SCRIPTS_DIR / "feeder.py"
    if not feeder.exists():
        print(f"[train] internal feeder missing: {feeder}", file=sys.stderr)
        return 3

    cmd = [
        sys.executable, str(feeder),
        "--path", str(src),
        "--corpus_id", corpus_id,
        "--chunk_size", str(args.chunk_size),
        "--ctx", str(args.ctx),
        "--overlap", str(args.overlap),
        "--gap", str(args.gap),
        "--max_queue", str(args.max_queue),
        "--start", str(args.start),
        "--limit", str(args.limit),
        "--url", BACKEND_URL,
    ]
    if args.no_resume:
        cmd.append("--no-resume")
    return subprocess.run(cmd).returncode


if __name__ == "__main__":
    raise SystemExit(main())
