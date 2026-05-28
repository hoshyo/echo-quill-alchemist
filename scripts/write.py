"""Memory-mode continuation — calls /write on the running backend.

This is the script the skill invokes when the user asks for memory-aware
continuation (knows the world, characters, recent events). For pure-style
no-memory continuation, use `scripts/infer.py` instead.

The backend reads canon + plot + rules + DPO few-shot UNION across all
corpora on disk and prompts the base LLM with a 5-block system prompt.
Each successful continuation is archived to `core/data/drafts/<ts>.txt`
so the user can later say "train on this one" → `train.py --layer user
--path <that_draft>` → the continuation enters the user-layer corpus.

Usage:
  python scripts/write.py --context "夜半，他推开窗。"
  python scripts/write.py --context-file ./prompt.txt --top_canon 8
  python scripts/write.py --context "..." --redo "把李四改成女性"   # quick redo
  python scripts/write.py --context "..." --json                    # machine-readable
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request

from _paths import BACKEND_URL


def _post(url: str, payload: dict, timeout: float = 240.0) -> dict:
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=body, headers={"Content-Type": "application/json"}, method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8", errors="ignore"))
    except urllib.error.HTTPError as e:
        msg = e.read().decode("utf-8", errors="ignore")
        raise SystemExit(f"[write] backend HTTP {e.code}: {msg}")
    except urllib.error.URLError as e:
        raise SystemExit(f"[write] backend not reachable at {url}: {e}")


def main() -> int:
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--context", help="upstream text to continue")
    g.add_argument("--context-file", help="path to a utf-8 file containing the context")
    ap.add_argument("--redo", default=None,
                    help="natural-language adjustment (e.g. '把李四改成女性，重写')")
    ap.add_argument("--top_rules", type=int, default=5)
    ap.add_argument("--top_canon", type=int, default=5)
    ap.add_argument("--top_plot", type=int, default=3)
    ap.add_argument("--few_shot", type=int, default=2)
    ap.add_argument("--max_tokens", type=int, default=1200)
    ap.add_argument("--temperature", type=float, default=0.85)
    ap.add_argument("--scope", default=None,
                    help="comma-separated corpus_ids to restrict retrieval to; "
                         "omit to use all on disk")
    ap.add_argument("--json", action="store_true", help="emit JSON instead of plain text")
    args = ap.parse_args()

    if args.context_file:
        from pathlib import Path
        ctx = Path(args.context_file).read_text(encoding="utf-8", errors="ignore")
    else:
        ctx = args.context

    payload = {
        "context": ctx,
        "extra_instruction": args.redo,
        "top_rules": args.top_rules,
        "top_canon": args.top_canon,
        "top_plot": args.top_plot,
        "few_shot": args.few_shot,
        "max_tokens": args.max_tokens,
        "temperature": args.temperature,
        "scope": [s.strip() for s in args.scope.split(",")] if args.scope else None,
    }
    out = _post(f"{BACKEND_URL}/write", payload)

    if args.json:
        print(json.dumps(out, ensure_ascii=False, indent=2))
    else:
        print(out.get("continuation", ""))
        print(
            f"\n[write] rules={out.get('rules_used',0)} "
            f"canon={out.get('canon_used',0)} "
            f"plot={out.get('plot_used',0)} "
            f"fewshot={out.get('fewshot_used',0)} "
            f"corpora={len(out.get('scope', []))}",
            file=sys.stderr,
        )
        print(f"[write] draft saved: {out.get('draft_path','')}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
