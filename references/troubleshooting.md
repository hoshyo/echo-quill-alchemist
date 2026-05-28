# Troubleshooting

Load this when `doctor.py` shows a problem, a script returns non-zero, or the user reports
something is broken. Find the symptom; the fix is right under it.

## Doctor says `python.ok = false` or `node.ok = false`

The runtime itself is missing. Don't try to install Python or Node from this skill — tell
the user, point to python.org / nodejs.org, and stop. We assume Python ≥3.10 and Node ≥18.

## Doctor says `npm.ok = false` on Windows but Node is installed

Known: `shutil.which("npm")` finds `npm.cmd` but `subprocess.run` chokes on `.cmd` files
without `shell=True`. `doctor.py` has the workaround already (see `_which_version`). If you
see this anyway, run `where npm` from the user's shell and confirm `npm.cmd` exists —
update `doctor.py` if a new edge case turned up.

## `pip install` fails with "To modify pip, please run …"

On Windows, pip refuses to upgrade itself in-place. `install_deps.py` already avoids
self-upgrading; if you call pip directly, use `python -m pip install …` not `pip install
--upgrade pip`.

## Backend never becomes ready (start_services hangs)

Likely causes, check the backend log (`core/data/logs/backend.log`):

- **Model weight download stalled.** Server startup loads MiniLM (~90 MB), and
  the first training chunk that emits a canon entity loads bge-m3 (~2.3 GB)
  if it wasn't prefetched. If a download window has been open for >5 min with
  no progress, the user's HuggingFace connection is the problem — kill the
  backend, ask them to check connectivity, retry. To avoid hitting this in
  the middle of a training run, run `prefetch_models.py` BEFORE start_services
  (the standard workflow gate does this).
- **Port 8000 already taken** by something else. `lsof -iTCP:8000 -sTCP:LISTEN` (mac/linux)
  or `Get-NetTCPConnection -LocalPort 8000` (Windows). Either kill the squatter or change
  `PORT=` in `.env` (and the dashboard's `VITE_WS_URL` to match — easier to free 8000).
- **Missing API key** is *not* the cause here — the backend starts fine without one. The
  worker only fails when chunks arrive.

## Doctor says `models_cached.ok = false`

One or both HF model snapshots are not in the local cache yet. Fix:

```
python scripts/prefetch_models.py            # both
python scripts/prefetch_models.py --minilm   # only MiniLM
python scripts/prefetch_models.py --bge-m3   # only bge-m3
```

`doctor.py` does a filesystem probe via `huggingface_hub.try_to_load_from_cache`;
it returns `false` if the user has a non-default `HF_HOME` / `TRANSFORMERS_CACHE`
that we can't see, or if the cache was cleared. Running `prefetch_models.py`
under the same shell as the backend should always make it green again.

## Worker logs `[FATAL] no Anthropic credentials …` (or `OPENAI_API_KEY not set`)

Run `python scripts/detect_provider.py`. If it says `"source": "none"`, no credentials are
visible to the backend in *any* of: shell env, `.env`, or `~/.claude/settings.json`. Three
ways to fix:

1. The user activates a CC Switch profile (their normal workflow), then restart backend.
2. `ensure_env.py --provider X --key Y` (only if they hand you the key in chat).
3. Tell them to fill `.env` themselves.

If `detect_provider.py` says `"source": "claude_code"` but the worker still complains, the
backend was started **before** the CC Switch profile was activated — it has stale env. Fix:
`stop_services.py --backend && start_services.py --backend`.

## CC Switch swap didn't take effect

`detect_provider.py` shows the new profile, but the backend is still talking to the old one.
This is by design — credentials are loaded once at startup. After any CC Switch change run:

```
python scripts/stop_services.py --backend
python scripts/start_services.py --backend
```

The `data/dpo.jsonl` artifact survives; in-memory rules and DPO history reset.

## Backend startup line shows `creds=shell_env` but you expected `claude_code`

Same thing in disguise. When Claude Code (and CC Switch through it) sets
`ANTHROPIC_AUTH_TOKEN` into the shell environment, our resolver legitimately reports it as
`shell_env` (it really is *in* the shell now). Compare the `base_url` and `masked_key` in
the startup line against `~/.claude/settings.json`'s `env` block — if they match, you have
the CC Switch profile, just labeled by its more specific source.

## Custom relay (`ANTHROPIC_BASE_URL=https://your-host`) returns 404 on /v1/messages

Your relay doesn't implement Anthropic's Messages API at the standard path. Options:

- Check the relay's docs — it may need a different path or version header.
- Some relays expect `x-api-key` only (no Bearer); others want Bearer only. The backend
  picks based on which env var is set: `ANTHROPIC_AUTH_TOKEN` → Bearer,
  `ANTHROPIC_API_KEY` → x-api-key. Set the one your relay accepts.
- If the relay is OpenAI-compatible instead of Anthropic-compatible, set
  `OPENAI_API_KEY` + `OPENAI_BASE_URL` in `.env` and let `LLM_PROVIDER=openai`.

## `trigger_training` returns `400 Bad Request: error parsing the body`

UTF-8 / curl quoting bug — almost always reproduces when curling Chinese characters from
Git Bash on Windows. The actual feeder (`core/scripts/feeder.py`) uses `httpx` and handles
this correctly. Don't blame the backend; reproduce with the feeder.

## Frontend shows `WS down` (red pill, top-right)

- Backend is down — check `doctor.py`.
- Backend is up but on a non-default port — `frontend/src/store.ts` reads `VITE_WS_URL`
  (default `ws://localhost:8000/ws/alchemist`). If the user changed `PORT`, set
  `VITE_WS_URL` accordingly and restart the dashboard.
- Browser is still on a stale tab from a previous crash — `Ctrl+Shift+R` reloads.

## Dashboard shows no rules / no candidates after several chunks

The worker is silently failing per-chunk. Check `core/data/logs/backend.log` for `[FATAL]`
or `! 候选生成失败`. Most common: API key is invalid, or the model name is wrong (e.g.
`OPENAI_MODEL=gpt-5o` typo). Fix `.env`, restart backend.

## `data/dpo.jsonl` keeps growing across runs

Intentional. The file is append-only across the whole project's lifetime. If the user
wants a fresh start, ask them whether to:

- Move it: `mv core/data/dpo.jsonl core/data/dpo.<date>.jsonl.bak`
- Or delete it: only after confirming.

Never delete it without asking.

## "How do I uninstall this?"

Stop services (`stop_services.py`), then the user removes the directory. There are no
installed services / system packages this skill registers. Heavy disk usage lives in:
- `core/frontend/node_modules/` (~300 MB)
- `~/.cache/huggingface/` (MiniLM ~90 MB + bge-m3 ~2.3 GB, total ~2.4 GB) — shared
  across other HF-based tools, don't blanket-delete without asking.
- pip-installed `torch` in the user's site-packages (~2 GB) — **don't remove without
  asking**, other projects may share it.
