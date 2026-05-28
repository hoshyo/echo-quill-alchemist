---
name: echo-quill-alchemist
description: Train a model to imitate a novel's voice and use that voice on demand. Load this skill whenever the user asks to train/fine-tune/learn the style of a novel or .txt file, mentions Echo-Quill / Alchemist / 炼金 / 双塔, asks to open the training dashboard, asks how the system works, asks to stop or restart the training services, or asks to write/continue text in a previously-trained style. The skill manages a local FastAPI backend + Vite/React dashboard, dependency installation, .env scaffolding, training, and post-training inference — the user supplies a novel path or a passage, the skill handles everything underneath.
---

# Echo-Quill Alchemist — skill router

You are the natural-language entry point to the Echo-Quill Alchemist, a local system that
turns novels into DPO training pairs and a dashboard, then serves style-conditioned generation
post-training. The user does not understand the internals (dual-tower judge, ROUGE-L, DPO
pairs, WebSocket) — they say "train on this novel" or "write something in last week's style".
You translate that into the right scripts.

**The user's mental model is:** drop in a novel → see a dashboard → later, ask for writing in
that style. Don't lecture them with internals unless they ask.

---

## The single rule that comes before everything else

**Always run `python scripts/doctor.py` first** for any echo-quill request. Its JSON output
is the ground truth for every dispatch decision below. Don't guess. Don't trust state from
earlier turns. Re-run the doctor.

---

## Intent → action map

| User says (paraphrased)                                                  | What you do                                                           |
|--------------------------------------------------------------------------|-----------------------------------------------------------------------|
| "train on `<novel.txt>`" / "用这本书炼金" / "feed `<path>` to echo-quill" | doctor → resolve missing deps/env (ASK before installing) → start_services → open_dashboard → train.py --path `<...>` |
| "show me the dashboard" / "open the observatory"                         | doctor → start_services (if down) → open_dashboard                    |
| "how's training going?" / "status?"                                      | doctor + summarize backend `healthz` (chunks, rules, dpo_pairs)      |
| "stop / shut it down / clean up"                                         | stop_services                                                         |
| "write in the trained style" / "continue this in [novel]'s voice"        | doctor → start_services (if down) → infer.py --context "..."         |
| "explain how this works"                                                 | read references/architecture.md and summarize for the user            |
| "something broke / errors"                                                | doctor → read core/data/logs/{backend,frontend}.log → references/troubleshooting.md |

---

## Rules of engagement

- **ASK before heavy installs.** `pip install sentence-transformers` pulls torch + MiniLM (~2 GB
  on first run). `npm install` in `core/frontend/` takes ~30 s. Use AskUserQuestion. Never
  silently start either when `doctor.py` reports them missing.
- **ASK before spending API tokens.** A real training run burns ~5 LLM calls per chunk
  (Best-of-N=4 + 1 hard-negative + 1 rule extraction = ~6). On a novel of 100 chunks that's
  600+ calls. Confirm provider, model, and chunk count with the user before invoking
  `train.py`.
- **ASK before writing the .env.** Never paste an API key into the terminal log without
  confirming the user knows you're writing it to `.env` on disk. Prefer asking the user to
  fill `.env` themselves; only use `ensure_env.py --provider X --key Y` if they explicitly
  hand you the key in chat.
- **The backend reads `.env` only at startup.** If you (or the user) modify `.env`, you must
  `stop_services.py --backend` then `start_services.py --backend` for the change to take
  effect. Tell the user when you do this and why.
- **Background services persist between turns.** `.echo-quill.state.json` at repo root holds
  PIDs. Always check `doctor.py` before spawning anything — never start a second backend.
- **Translate technical errors.** When a script returns a stack trace or a non-zero exit,
  render the user-facing reason: "API key invalid", "novel file not found", "port 8000 already
  in use", "backend log shows MiniLM download timed out". Don't dump tracebacks unless the
  user asks for "the full error".
- **Keep the user in the loop while training.** After `train.py` starts, the dashboard streams
  progress visually — direct the user there. Don't tail logs and recite chunks.
- **One job at a time.** Don't kick off `train.py` while another novel is being trained
  (check backend `healthz.queued`). Ask the user whether to wait or cancel first.

---

## Available scripts (call them; don't reimplement)

All scripts live at `scripts/` and are invoked with `python scripts/<name>.py`. Most accept
`--help`. They output JSON (or plain text for `infer.py`) for easy consumption.

| Script              | Purpose                                                            |
|---------------------|--------------------------------------------------------------------|
| `doctor.py`         | JSON status — deps, env, services, data. Always run first.         |
| `install_deps.py`   | `[--backend|--frontend]` — idempotent dep install. Heavy on first run. |
| `ensure_env.py`     | Validate `.env`, or write one with `--provider X --key Y`.         |
| `start_services.py` | `[--backend|--frontend|--no-wait]` — spawn detached, write state.  |
| `stop_services.py`  | `[--backend|--frontend]` — kill via state PIDs, fallback to ports. |
| `open_dashboard.py` | Open browser to `http://localhost:5173`.                           |
| `train.py`          | `--path X.txt [--chunk_size N --ctx N --limit N]` — feed novel.    |
| `infer.py`          | `--context "..." [--top_rules N --few_shot N]` — generate style.   |

Internal script (do NOT call from skill — `train.py` wraps it): `core/scripts/feeder.py`.

---

## When to load reference docs

Only pull these into context when the user's request actually needs them.

- `references/architecture.md` — when the user asks how the system works (dual-tower, DPO,
  rule lifecycle), or when you yourself need to reason about a non-obvious behavior.
- `references/workflow-train.md` — before starting a real training run, especially the first
  one for a given user/novel.
- `references/workflow-infer.md` — before calling `infer.py`, or when explaining how the
  "use the trained style" flow works.
- `references/troubleshooting.md` — when `doctor.py` shows a problem or a script returned
  non-zero.
