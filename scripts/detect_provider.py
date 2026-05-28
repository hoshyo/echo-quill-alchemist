"""Print where Echo-Quill would pick up its LLM credentials.

Resolution order: shell env > .env at repo root > ~/.claude/settings.json (CC Switch).

Output (JSON):
{
  "source":  "shell_env" | ".env" | "claude_code" | "none",
  "provider": "anthropic" | "openai" | null,
  "auth_style": "auth_token" | "api_key" | null,
  "base_url": "...",
  "model":    "...",
  "has_credentials": bool,
  "masked_key": "abcd…wxyz",
  "notes": [...]
}

The skill router calls this after `doctor.py`. If `has_credentials` is true, no
.env-writing flow is needed — start_services.py can go straight ahead.
"""
from __future__ import annotations

import json
import sys

from _paths import CORE_DIR

# Reach into the backend's resolver so we have a single source of truth.
sys.path.insert(0, str(CORE_DIR))
from backend.auth_resolver import resolve  # noqa: E402


def main() -> int:
    print(json.dumps(resolve(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
