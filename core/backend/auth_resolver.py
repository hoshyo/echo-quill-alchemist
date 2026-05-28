"""LLM credential resolution.

Resolution order (highest priority first):

  1. shell environment   — anything already in os.environ when this runs
  2. .env at repo root   — picked up via load_dotenv() in server.py
  3. ~/.claude/settings.json `env` block  — what CC Switch / Claude Code is currently using

The first one that yields a usable Anthropic AUTH_TOKEN/API_KEY or OpenAI API_KEY wins.
This means a project-local `.env` always overrides CC Switch (so you can isolate a project
to a specific provider), but if `.env` is empty we silently inherit the user's CC Switch
selection — no duplicated config.

Two auth styles for Anthropic (and Claude-Code-compatible relays):

  - `ANTHROPIC_API_KEY`  → sent as `x-api-key` header  (Anthropic SDK style, sk-ant-…)
  - `ANTHROPIC_AUTH_TOKEN` → sent as `Authorization: Bearer …`  (Claude Code style)

Plus optional `ANTHROPIC_BASE_URL` to point at a self-hosted relay.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional, TypedDict

CLAUDE_SETTINGS = Path.home() / ".claude" / "settings.json"


class Resolved(TypedDict, total=False):
    source: str          # "shell_env" | ".env" | "claude_code" | "none"
    provider: Optional[str]   # "anthropic" | "openai" | None
    auth_style: Optional[str] # "auth_token" | "api_key" | None
    base_url: str
    model: str
    has_credentials: bool
    masked_key: str
    notes: list[str]


def _read_claude_settings() -> dict:
    if not CLAUDE_SETTINGS.exists():
        return {}
    try:
        return json.loads(CLAUDE_SETTINGS.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _parse_dotenv(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if not path.exists():
        return out
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        k, v = s.split("=", 1)
        # strip optional quotes
        v = v.strip().strip('"').strip("'")
        out[k.strip()] = v
    return out


def _mask(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 8:
        return "*" * len(value)
    return value[:4] + "…" + value[-4:]


def resolve(repo_root: Path | None = None) -> Resolved:
    """Return what credentials Echo-Quill will actually use.

    Caller is responsible for setting them into os.environ before LLMClient runs.
    The `LLMClient.__init__` calls `apply()` which does exactly that.
    """
    notes: list[str] = []

    # ---- 1. shell environment ----
    if os.getenv("ANTHROPIC_AUTH_TOKEN"):
        return Resolved(
            source="shell_env",
            provider="anthropic",
            auth_style="auth_token",
            base_url=os.getenv("ANTHROPIC_BASE_URL", "https://api.anthropic.com"),
            model=os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-6"),
            has_credentials=True,
            masked_key=_mask(os.environ["ANTHROPIC_AUTH_TOKEN"]),
            notes=notes,
        )
    if os.getenv("ANTHROPIC_API_KEY"):
        return Resolved(
            source="shell_env",
            provider="anthropic",
            auth_style="api_key",
            base_url=os.getenv("ANTHROPIC_BASE_URL", "https://api.anthropic.com"),
            model=os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-6"),
            has_credentials=True,
            masked_key=_mask(os.environ["ANTHROPIC_API_KEY"]),
            notes=notes,
        )
    if os.getenv("OPENAI_API_KEY"):
        return Resolved(
            source="shell_env",
            provider="openai",
            auth_style="api_key",
            base_url=os.getenv("OPENAI_BASE_URL", "https://api.openai.com"),
            model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
            has_credentials=True,
            masked_key=_mask(os.environ["OPENAI_API_KEY"]),
            notes=notes,
        )

    # ---- 2. .env at repo root (skill is usually invoked from there) ----
    if repo_root is None:
        # core/backend/auth_resolver.py → core/backend → core → repo_root
        repo_root = Path(__file__).resolve().parents[2]
    env_vars = _parse_dotenv(repo_root / ".env")
    if env_vars.get("ANTHROPIC_AUTH_TOKEN"):
        return Resolved(
            source=".env",
            provider="anthropic",
            auth_style="auth_token",
            base_url=env_vars.get("ANTHROPIC_BASE_URL", "https://api.anthropic.com"),
            model=env_vars.get("ANTHROPIC_MODEL", "claude-sonnet-4-6"),
            has_credentials=True,
            masked_key=_mask(env_vars["ANTHROPIC_AUTH_TOKEN"]),
            notes=notes,
        )
    if env_vars.get("ANTHROPIC_API_KEY"):
        return Resolved(
            source=".env",
            provider="anthropic",
            auth_style="api_key",
            base_url=env_vars.get("ANTHROPIC_BASE_URL", "https://api.anthropic.com"),
            model=env_vars.get("ANTHROPIC_MODEL", "claude-sonnet-4-6"),
            has_credentials=True,
            masked_key=_mask(env_vars["ANTHROPIC_API_KEY"]),
            notes=notes,
        )
    if env_vars.get("OPENAI_API_KEY"):
        return Resolved(
            source=".env",
            provider="openai",
            auth_style="api_key",
            base_url=env_vars.get("OPENAI_BASE_URL", "https://api.openai.com"),
            model=env_vars.get("OPENAI_MODEL", "gpt-4o-mini"),
            has_credentials=True,
            masked_key=_mask(env_vars["OPENAI_API_KEY"]),
            notes=notes,
        )

    # ---- 3. ~/.claude/settings.json (CC Switch / Claude Code active provider) ----
    cc = _read_claude_settings()
    cc_env = (cc.get("env") or {}) if isinstance(cc, dict) else {}
    if cc_env.get("ANTHROPIC_AUTH_TOKEN"):
        notes.append(f"inherited from {CLAUDE_SETTINGS} (CC Switch active provider)")
        return Resolved(
            source="claude_code",
            provider="anthropic",
            auth_style="auth_token",
            base_url=cc_env.get("ANTHROPIC_BASE_URL", "https://api.anthropic.com"),
            # We deliberately DO NOT use the friendly model name from claude settings
            # ("opus[1m]" etc.) — relays may or may not understand it. The user can pin
            # ANTHROPIC_MODEL in .env if they care.
            model=os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-6"),
            has_credentials=True,
            masked_key=_mask(cc_env["ANTHROPIC_AUTH_TOKEN"]),
            notes=notes,
        )
    if cc_env.get("ANTHROPIC_API_KEY"):
        notes.append(f"inherited from {CLAUDE_SETTINGS} (CC Switch active provider)")
        return Resolved(
            source="claude_code",
            provider="anthropic",
            auth_style="api_key",
            base_url=cc_env.get("ANTHROPIC_BASE_URL", "https://api.anthropic.com"),
            model=os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-6"),
            has_credentials=True,
            masked_key=_mask(cc_env["ANTHROPIC_API_KEY"]),
            notes=notes,
        )

    # nothing
    return Resolved(
        source="none",
        provider=None,
        auth_style=None,
        base_url="",
        model="",
        has_credentials=False,
        masked_key="",
        notes=notes,
    )


def apply(resolved: Resolved) -> None:
    """Inject resolved values into os.environ so the rest of the backend can read
    them with plain os.getenv calls. Idempotent."""
    if not resolved.get("has_credentials"):
        return
    provider = resolved.get("provider")
    if provider == "anthropic":
        if resolved.get("auth_style") == "auth_token":
            os.environ["ANTHROPIC_AUTH_TOKEN"] = os.environ.get(
                "ANTHROPIC_AUTH_TOKEN", _undo_mask(resolved)
            )
        else:
            os.environ["ANTHROPIC_API_KEY"] = os.environ.get(
                "ANTHROPIC_API_KEY", _undo_mask(resolved)
            )
        os.environ["ANTHROPIC_BASE_URL"] = resolved.get("base_url", "https://api.anthropic.com")
        os.environ["ANTHROPIC_MODEL"] = resolved.get("model", "claude-sonnet-4-6")
        os.environ["LLM_PROVIDER"] = "anthropic"
    elif provider == "openai":
        os.environ["OPENAI_API_KEY"] = os.environ.get("OPENAI_API_KEY", _undo_mask(resolved))
        os.environ["OPENAI_BASE_URL"] = resolved.get("base_url", "https://api.openai.com")
        os.environ["OPENAI_MODEL"] = resolved.get("model", "gpt-4o-mini")
        os.environ["LLM_PROVIDER"] = "openai"


def _undo_mask(_resolved: Resolved) -> str:
    """Sentinel so callers know not to call apply() with only a masked Resolved.

    `apply` only injects real values from os.environ; if a value isn't present, we
    can't recover it from the masked form. Resolution + injection happens in one
    pass inside LLMClient (see backend.engine), so this is never actually exercised.
    """
    raise RuntimeError(
        "auth_resolver.apply() must be called with a Resolved that already has its "
        "underlying credentials in os.environ. Call resolve_and_inject() instead."
    )


def resolve_and_inject(repo_root: Path | None = None) -> Resolved:
    """One-shot convenience: read every source, push the winning one into os.environ.

    This is what backend code should call at startup. After this, plain os.getenv
    works for ANTHROPIC_AUTH_TOKEN / API_KEY / BASE_URL / MODEL or the OPENAI variants.
    """
    if repo_root is None:
        repo_root = Path(__file__).resolve().parents[2]

    # If shell already has creds, no-op
    if (
        os.getenv("ANTHROPIC_AUTH_TOKEN")
        or os.getenv("ANTHROPIC_API_KEY")
        or os.getenv("OPENAI_API_KEY")
    ):
        return resolve(repo_root)

    # try .env
    env_vars = _parse_dotenv(repo_root / ".env")
    if env_vars.get("ANTHROPIC_AUTH_TOKEN"):
        os.environ["ANTHROPIC_AUTH_TOKEN"] = env_vars["ANTHROPIC_AUTH_TOKEN"]
        if env_vars.get("ANTHROPIC_BASE_URL"):
            os.environ["ANTHROPIC_BASE_URL"] = env_vars["ANTHROPIC_BASE_URL"]
        if env_vars.get("ANTHROPIC_MODEL"):
            os.environ["ANTHROPIC_MODEL"] = env_vars["ANTHROPIC_MODEL"]
        return resolve(repo_root)
    if env_vars.get("ANTHROPIC_API_KEY"):
        os.environ["ANTHROPIC_API_KEY"] = env_vars["ANTHROPIC_API_KEY"]
        if env_vars.get("ANTHROPIC_BASE_URL"):
            os.environ["ANTHROPIC_BASE_URL"] = env_vars["ANTHROPIC_BASE_URL"]
        if env_vars.get("ANTHROPIC_MODEL"):
            os.environ["ANTHROPIC_MODEL"] = env_vars["ANTHROPIC_MODEL"]
        return resolve(repo_root)
    if env_vars.get("OPENAI_API_KEY"):
        os.environ["OPENAI_API_KEY"] = env_vars["OPENAI_API_KEY"]
        if env_vars.get("OPENAI_BASE_URL"):
            os.environ["OPENAI_BASE_URL"] = env_vars["OPENAI_BASE_URL"]
        if env_vars.get("OPENAI_MODEL"):
            os.environ["OPENAI_MODEL"] = env_vars["OPENAI_MODEL"]
        return resolve(repo_root)

    # fall back to ~/.claude/settings.json
    cc = _read_claude_settings()
    cc_env = (cc.get("env") or {}) if isinstance(cc, dict) else {}
    if cc_env.get("ANTHROPIC_AUTH_TOKEN"):
        os.environ["ANTHROPIC_AUTH_TOKEN"] = cc_env["ANTHROPIC_AUTH_TOKEN"]
        if cc_env.get("ANTHROPIC_BASE_URL"):
            os.environ["ANTHROPIC_BASE_URL"] = cc_env["ANTHROPIC_BASE_URL"]
        return resolve(repo_root)
    if cc_env.get("ANTHROPIC_API_KEY"):
        os.environ["ANTHROPIC_API_KEY"] = cc_env["ANTHROPIC_API_KEY"]
        if cc_env.get("ANTHROPIC_BASE_URL"):
            os.environ["ANTHROPIC_BASE_URL"] = cc_env["ANTHROPIC_BASE_URL"]
        return resolve(repo_root)

    return resolve(repo_root)
