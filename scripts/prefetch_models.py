"""Pre-fetch MiniLM and bge-m3 weights into the local HuggingFace cache.

Called after `install_deps.py --backend` so the heavy ~2.4 GB of model weights
download happens up-front behind a single user-consent gate, instead of being
split between server startup (MiniLM) and the first canon-emitting chunk of
the first training run (bge-m3).

Idempotent: if the weights are already cached, the second call is a fast
no-op (SentenceTransformer just loads from disk and we encode one warmup
string to surface any half-downloaded snapshot now rather than mid-training).

Examples:
  python scripts/prefetch_models.py            # both
  python scripts/prefetch_models.py --minilm   # only MiniLM (~90 MB)
  python scripts/prefetch_models.py --bge-m3   # only bge-m3 (~2.3 GB)
"""
from __future__ import annotations

import argparse
import sys

MODELS = {
    "minilm": ("sentence-transformers/all-MiniLM-L6-v2", "~90 MB"),
    "bge_m3": ("BAAI/bge-m3", "~2.3 GB"),
}


def _prefetch(repo_id: str, size_hint: str) -> int:
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError as e:
        print(f"[prefetch_models] sentence-transformers not installed: {e}",
              file=sys.stderr)
        print("[prefetch_models] run `python scripts/install_deps.py --backend` first.",
              file=sys.stderr)
        return 2

    print(f"[prefetch_models] {repo_id} ({size_hint}) — downloading or loading from cache...",
          flush=True)
    try:
        m = SentenceTransformer(repo_id)
        # encode() exercises the forward path so a half-downloaded snapshot
        # surfaces here, not at the first chunk of a real training run.
        m.encode(["warmup"], normalize_embeddings=True)
    except Exception as e:
        print(f"[prefetch_models] {repo_id} failed: {e!r}", file=sys.stderr)
        return 1
    print(f"[prefetch_models] {repo_id} cached.", flush=True)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--minilm", action="store_true",
                    help="only prefetch all-MiniLM-L6-v2 (~90 MB)")
    ap.add_argument("--bge-m3", dest="bge_m3", action="store_true",
                    help="only prefetch BAAI/bge-m3 (~2.3 GB)")
    args = ap.parse_args()

    selected = []
    if args.minilm:
        selected.append("minilm")
    if args.bge_m3:
        selected.append("bge_m3")
    if not selected:
        selected = list(MODELS.keys())

    rc = 0
    for label in selected:
        repo_id, size = MODELS[label]
        rc |= _prefetch(repo_id, size)
    if rc == 0:
        print("[prefetch_models] done.")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
