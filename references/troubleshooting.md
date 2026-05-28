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

- **MiniLM download stalled.** First-run downloads `all-MiniLM-L6-v2` (~90 MB). If the
  download window has been open for >5 min and there's no progress, the user's HuggingFace
  connection is the problem — kill the backend, ask them to check connectivity, retry.
- **Port 8000 already taken** by something else. `lsof -iTCP:8000 -sTCP:LISTEN` (mac/linux)
  or `Get-NetTCPConnection -LocalPort 8000` (Windows). Either kill the squatter or change
  `PORT=` in `.env` (and the dashboard's `VITE_WS_URL` to match — easier to free 8000).
- **Missing API key** is *not* the cause here — the backend starts fine without one. The
  worker only fails when chunks arrive.

## Worker logs `[FATAL] OPENAI_API_KEY not set` (or ANTHROPIC_API_KEY)

The user has no key in `.env`, or `.env` was modified after the backend started. Two fixes:

1. `ensure_env.py --provider X --key Y` (only if the user hands you the key in chat)
2. Tell them to fill `.env` themselves.

Either way, **restart the backend** (`stop_services.py --backend && start_services.py
--backend`) — it reads `.env` once at startup.

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
- `~/.cache/huggingface/` (the MiniLM cache, ~100 MB)
- pip-installed `torch` in the user's site-packages (~2 GB) — **don't remove without
  asking**, other projects may share it.
