"""Style-conditioned continuation using the running backend's /infer endpoint.

This is the script the skill calls when the user says "write something in the trained
style" or "continue this passage in [last novel]'s voice". The backend pulls top
style rules + best DPO chosen examples and prompts the LLM with them.

Usage:
  python scripts/infer.py --context "夜半，他推开窗。"
  python scripts/infer.py --context-file ./prompt.txt --top_rules 8 --few_shot 3
  python scripts/infer.py --context "..."  --json    # emit machine-readable JSON
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request

from _paths import BACKEND_URL


def _post(url: str, payload: dict, timeout: float = 180.0) -> dict:
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=body, headers={"Content-Type": "application/json"}, method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8", errors="ignore"))
    except urllib.error.HTTPError as e:
        msg = e.read().decode("utf-8", errors="ignore")
        raise SystemExit(f"[infer] backend HTTP {e.code}: {msg}")
    except urllib.error.URLError as e:
        raise SystemExit(f"[infer] backend not reachable at {url}: {e}")


def main() -> int:
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--context", help="upstream text to continue")
    g.add_argument("--context-file", help="path to a utf-8 file containing the context")
    ap.add_argument("--top_rules", type=int, default=5)
    ap.add_argument("--few_shot", type=int, default=2)
    ap.add_argument("--max_tokens", type=int, default=600)
    ap.add_argument("--temperature", type=float, default=0.85)
    ap.add_argument("--json", action="store_true", help="emit JSON instead of just the continuation text")
    args = ap.parse_args()

    if args.context_file:
        from pathlib import Path
        ctx = Path(args.context_file).read_text(encoding="utf-8", errors="ignore")
    else:
        ctx = args.context

    payload = {
        "context": ctx,
        "top_rules": args.top_rules,
        "few_shot": args.few_shot,
        "max_tokens": args.max_tokens,
        "temperature": args.temperature,
    }
    out = _post(f"{BACKEND_URL}/infer", payload)

    if args.json:
        print(json.dumps(out, ensure_ascii=False, indent=2))
    else:
        print(out.get("continuation", ""))
        print(
            f"\n[infer] used {out.get('rules_used', 0)} rules + "
            f"{out.get('fewshot_used', 0)} few-shot examples",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
