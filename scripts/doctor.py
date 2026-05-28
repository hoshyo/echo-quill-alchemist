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
    DPO_FILE,
    ENV_FILE,
    FRONTEND_DIR,
    FRONTEND_URL,
    STATE_FILE,
)


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
    if not ENV_FILE.exists():
        return {"ok": False, "provider": None, "has_key": False}
    text = ENV_FILE.read_text(encoding="utf-8", errors="ignore")
    has_anthropic = any(
        line.strip().startswith("ANTHROPIC_API_KEY=") and line.strip().split("=", 1)[1].strip()
        for line in text.splitlines()
    )
    has_openai = any(
        line.strip().startswith("OPENAI_API_KEY=") and line.strip().split("=", 1)[1].strip()
        for line in text.splitlines()
    )
    if has_anthropic:
        return {"ok": True, "provider": "anthropic", "has_key": True}
    if has_openai:
        return {"ok": True, "provider": "openai", "has_key": True}
    return {"ok": False, "provider": None, "has_key": False}


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

    dpo_count = 0
    if DPO_FILE.exists():
        with DPO_FILE.open("r", encoding="utf-8") as f:
            dpo_count = sum(1 for _ in f)

    data = {
        "dpo_pairs_on_disk": dpo_count,
        "rules": (services["backend"].get("healthz") or {}).get("rules", 0),
        "chunks_processed": (services["backend"].get("healthz") or {}).get("chunks_processed", 0),
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
