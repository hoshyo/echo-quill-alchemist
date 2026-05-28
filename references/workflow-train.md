# Workflow — Training a novel

Load this when the user wants to train on a new novel. It walks the agent through the
preconditions and the order of script calls. Treat it as a checklist; never skip the
"ask first" gates.

## Inputs from the user

You need exactly one thing: an absolute path to a `.txt` file (UTF-8). If they only give a
filename or a directory, ask for the full path. If they paste a URL, ask them to download it
first — this skill does not fetch novels from the internet.

Optional knobs the user might mention:
- chunk size (chars of "truth" per chunk; default 500)
- context size (chars of preceding text shown to the model; default 800)
- limit (cap chunks for a dry run; default unlimited)
- provider (`anthropic` or `openai`)

## The decision flow

```
1. doctor.py
   ├─ python/node/npm not ok      → tell the user, abort (we don't auto-install runtimes)
   ├─ backend_deps missing        → ASK to pip install (warn ~2GB / 5–15 min)
   │    on yes: install_deps.py --backend
   ├─ frontend_deps missing       → ASK to npm install
   │    on yes: install_deps.py --frontend
   ├─ env.source = "claude_code"  → CC Switch is active; SKIP ensure_env entirely.
   │                                Tell the user which base_url + masked_key + model
   │                                will be used (so they know which budget is in play).
   ├─ env.source = "shell_env"    → Same — credentials inherited from this shell.
   │                                Often this is just CC Switch propagating into the env.
   ├─ env.source = ".env"         → Project-local override; same — skip ensure_env.
   ├─ env.source = "none"         → ASK which provider + key. Three options to offer:
   │    a) "switch to a CC Switch profile and re-run" (best, no .env needed)
   │    b) "I'll fill .env myself" (tell them the path; abort)
   │    c) they paste a key here  → ensure_env.py --provider X --key Y
   ├─ services down               → start_services.py (waits for both ready)
   └─ services already up         → keep them; do not restart unless creds changed

2. open_dashboard.py
   so the user has eyes on it before chunks start landing

3. ASK the user to confirm:
   - the novel path
   - the cost shape (e.g. "this is roughly 300 chunks × ~6 LLM calls = ~1800 calls;
     keep going?") — and explicitly mention which provider/base_url will eat that cost
   - chunk_size / ctx if they specified non-defaults

4. train.py --path "<absolute/path>" [--chunk_size N] [--ctx N] [--limit N]

5. Direct the user to the dashboard. Don't tail logs. Don't recite chunks.
   If they want to know status, run doctor.py again — its `data` block has
   `chunks_processed`, `rules`, `dpo_pairs`.
```

### Mid-run: switching CC Switch profile

If the user switches CC Switch profiles while training is running, the running backend will
NOT pick it up — credentials are read once at startup. Tell them, then on confirmation:

```
stop_services.py --backend
start_services.py --backend
```

Existing in-memory state (rules, in-progress chunks) is lost; `data/dpo.jsonl` is preserved.

## Estimating cost before running

Quick math the agent can do up front:

- chunks ≈ `len(novel_in_chars) / chunk_size`
- LLM calls ≈ `chunks × (n_candidates + 1 hard_negative + 1 rule_extraction)` = `chunks × 6`
  (defaults: n_candidates=4)

Show this estimate to the user before invoking `train.py`.

## After training: where the artifacts live

- `core/data/dpo.jsonl` — every DPO pair, JSONL, ready for downstream use
- The in-memory `AlchemistState` (rules, dpo_pairs, logs) — visible in the dashboard;
  fetchable as a snapshot via `GET /state`
- Service logs at `core/data/logs/{backend,frontend}.log`

`data/dpo.jsonl` is the durable artifact. Restarting the backend wipes the in-memory state
but keeps the file.

## Stopping mid-run

If the user wants to stop training partway, run `stop_services.py --backend`. The next time
they want to resume, you'll need to start again with `--start <char_offset>` so chunks
already processed aren't re-fed (the system itself doesn't dedupe — it would happily
re-train on the same chunks).
