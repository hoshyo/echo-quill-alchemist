"""Echo-Quill doctor — single source of truth for system status.

Prints JSON to stdout. The skill router consults this BEFORE running anything else, so it
doesn't have to guess what's missing. Exit code is always 0 (machine consumers read the JSON).

Output schema (stable):
{
  "python":   {"ok": bool, "version": "3.12.2"},
  "node":     {"ok": bool, "version": "v24.4.1"},
  "npm":      {"ok": bool, "version": "11.4.2"},
  "backend_deps":  {"ok": bool, "missing": [...]},
  "frontend_deps": {"ok": bool, "node_modules": bool},
  "env":      {"ok": bool, "provider": "anthropic"|"openai"|null, "has_key": bool},
  "services": {"backend": {"up": bool, "pid": int|null}, "frontend": {"up": bool, "pid": int|null}},
  "data":     {"dpo_pairs": int, "rules": int, "chunks_processed": int}
}
"""
from __future__ import annotations

import json
import platform
import shutil
import subprocess
import sys
import urllib.request

from _paths import (
    BACKEND_URL,
    CORE_DIR,
    ENV_FILE,
    FRONTEND_DIR,
    FRONTEND_URL,
    STATE_FILE,
    count_dpo_pairs_on_disk,
    list_corpora,
)

# pull the same resolver the backend uses so the JSON we emit and the env the
# backend sees agree exactly.
sys.path.insert(0, str(CORE_DIR))
from backend.auth_resolver import resolve as resolve_provider  # noqa: E402


REQUIRED_PY_PACKAGES = [
    "fastapi",
    "uvicorn",
    "websockets",
    "pydantic",
    "sentence_transformers",
    "rouge_score",
    "httpx",
    "dotenv",  # python-dotenv installs as `dotenv`
    "numpy",
]


def _which_version(cmd: str, args: list[str]) -> tuple[bool, str]:
    if shutil.which(cmd) is None:
        return False, ""
    try:
        # On Windows, npm/npx are .cmd files and require shell invocation.
        if platform.system() == "Windows":
            full = " ".join([cmd, *args])
            out = subprocess.run(full, capture_output=True, text=True, timeout=10, shell=True)
        else:
            out = subprocess.run([cmd, *args], capture_output=True, text=True, timeout=10)
        return True, (out.stdout.strip() or out.stderr.strip())
    except Exception:
        return False, ""


def _check_py_packages() -> tuple[bool, list[str]]:
    import importlib

    missing: list[str] = []
    for name in REQUIRED_PY_PACKAGES:
        try:
            importlib.import_module(name)
        except ImportError:
            missing.append(name)
    return (len(missing) == 0), missing


def _check_env() -> dict:
    """Resolve LLM credentials the same way the backend does.

    Output keeps the legacy keys (`ok`, `provider`, `has_key`) so older callers don't
    break, and adds the full resolution detail (`source`, `base_url`, etc).
    """
    r = resolve_provider()
    has = bool(r.get("has_credentials"))
    return {
        "ok": has,
        "provider": r.get("provider"),
        "has_key": has,
        "source": r.get("source"),                # "shell_env" | ".env" | "claude_code" | "none"
        "auth_style": r.get("auth_style"),        # "auth_token" | "api_key" | None
        "base_url": r.get("base_url"),
        "model": r.get("model"),
        "masked_key": r.get("masked_key"),
        "dotenv_present": ENV_FILE.exists(),
        "notes": r.get("notes", []),
    }


def _http_get(url: str, timeout: float = 1.5) -> dict | None:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            if r.status == 200:
                body = r.read().decode("utf-8", errors="ignore")
                try:
                    return json.loads(body)
                except Exception:
                    return {}
    except Exception:
        return None
    return None


def _service_status() -> dict:
    state = {}
    if STATE_FILE.exists():
        try:
            state = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            state = {}
    backend_health = _http_get(f"{BACKEND_URL}/healthz")
    backend = {
        "up": backend_health is not None,
        "pid": (state.get("backend") or {}).get("pid"),
        "healthz": backend_health,
    }
    # vite responds with HTML — just check reachability
    try:
        with urllib.request.urlopen(FRONTEND_URL, timeout=1.5) as r:
            frontend_up = r.status == 200
    except Exception:
        frontend_up = False
    frontend = {
        "up": frontend_up,
        "pid": (state.get("frontend") or {}).get("pid"),
    }
    return {"backend": backend, "frontend": frontend}


def main() -> None:
    py_ok, py_ver = _which_version(sys.executable, ["--version"])
    node_ok, node_ver = _which_version("node", ["--version"])
    npm_ok, npm_ver = _which_version("npm", ["--version"])
    pkgs_ok, pkgs_missing = _check_py_packages()
    fe_node_modules = (FRONTEND_DIR / "node_modules").exists()
    env = _check_env()
    services = _service_status()

    dpo_count = count_dpo_pairs_on_disk()
    corpora = list_corpora()

    data = {
        "dpo_pairs_on_disk": dpo_count,
        "corpora": corpora,
        "corpora_count": len(corpora),
        "rules": (services["backend"].get("healthz") or {}).get("rules", 0),
        "chunks_processed": (services["backend"].get("healthz") or {}).get("chunks_processed", 0),
        "active_corpus": (services["backend"].get("healthz") or {}).get("corpus_id"),
    }

    report = {
        "python": {"ok": py_ok, "version": py_ver},
        "node": {"ok": node_ok, "version": node_ver},
        "npm": {"ok": npm_ok, "version": npm_ver},
        "backend_deps": {"ok": pkgs_ok, "missing": pkgs_missing},
        "frontend_deps": {"ok": fe_node_modules, "node_modules": fe_node_modules},
        "env": env,
        "services": services,
        "data": data,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
