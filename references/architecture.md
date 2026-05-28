# Architecture — Echo-Quill Alchemist

How the system actually works, written for the agent that operates it. Read this when the
user asks "how does this work" or when you need to reason about a non-obvious behavior.

## One-line summary

A novel is sliced into `(context, truth)` windows; for each window the LLM generates several
candidate continuations plus one deliberately disfigured "hard negative"; a dual-tower judge
(MiniLM cosine + ROUGE-L F1) ranks them; the winner pairs with the loser to form a DPO
training pair. A live React dashboard watches the whole thing over WebSocket.

## Layout

```
repo_root/
  SKILL.md                  ← skill router (the natural-language surface)
  scripts/                  ← skill scripts that the agent invokes
  references/               ← these docs, loaded on demand
  core/                     ← the actual system
    backend/
      models.py             ← Pydantic black-boxes
      engine.py             ← DualTowerJudge + LLMClient + Alchemist
      server.py             ← FastAPI + WebSocket
      persistence/          ← crash-safe state IO (paths, atomic_io, snapshot)
    frontend/               ← Vite/React/Zustand dashboard
    scripts/feeder.py       ← internal feeder (called by scripts/train.py)
    data/
      dpo.jsonl             ← every DPO pair appended here
      snapshots/state.json  ← rules + chunks_processed; rewritten each chunk
      progress/<sha>.json   ← per-novel feed cursor (PR-2)
      seen/<sha>.txt        ← per-novel chunk_id idempotency log (PR-2)
      logs/                 ← service stdout/stderr
  .env                      ← LLM keys (loaded by core/backend/server.py at startup)
  .echo-quill.state.json    ← runtime PIDs (managed by start_services / stop_services)
```

## Two design invariants (do not violate)

1. **No subjective LLM scoring.** Quality is a composite of MiniLM cosine + ROUGE-L F1
   (defaults α=0.6, β=0.4). The LLM only generates and extracts structured rules. If you
   ever feel tempted to add an "LLM rates this 0–10" path, stop — that's exactly the failure
   mode this system was built to avoid.
2. **Every chunk emits at least one DPO pair.** This is enforced by always generating one
   hard-negative continuation alongside the Best-of-N pool. `best_normal vs hard_negative` is
   the floor. `best vs worst_normal` is added on top whenever the spread ≥ θ (default 0.05).

## Per-chunk pipeline (what happens for each `/trigger_training`)

```
phase=generation
  ├ best_of_N normal candidates (LLM, parallel)
  └ 1 hard-negative candidate    (LLM, parallel)

phase=judging
  for each candidate:
    semantic = MiniLM cosine(candidate, truth)
    rouge    = ROUGE-L F1(candidate, truth)
    composite = α·semantic + β·rouge
  sort by composite descending

phase=dpo
  emit DPOPair(best, hard_negative)                       ← always
  if best.composite − worst.composite ≥ θ:
    emit DPOPair(best, worst_normal)                      ← when meaningful
  append every pair to data/dpo.jsonl

phase=rules
  for each existing rule r:
    if MiniLM_cosine(r.description, truth) ≥ 0.32: r.hit_count += 1; r.lifespan = min(r.initial, r.lifespan+1)
    else: r.lifespan -= 1
  cull rules with lifespan ≤ 0
  ask LLM to extract ≤5 new rules from truth; merge unique into rules

phase=idle
  broadcast chunk_done; ready for next /trigger_training
```

## State (Pydantic black-boxes)

- `StyleRule(id, description, lifespan=15, initial_lifespan=15, hit_count=0, born_at, last_hit_at)`
- `Candidate(text, semantic_score, rouge_score, composite_score, is_hard_negative)`
- `DPOPair(prompt, chosen, rejected, chosen_score, rejected_score, margin, reason, created_at)`
- `AlchemistState(rules, arena_candidates, arena_hard_negative, dpo_pairs, logs, current_phase, chunks_processed, …)`

The lifespan/hit_count counters are not optional — they exist to prevent unbounded memory
growth and to surface stale rules in the dashboard heatmap.

## Wire formats

WebSocket frames (`backend/models.py::WSMessage`):

| `type`        | `payload` shape                                                    |
|---------------|--------------------------------------------------------------------|
| `snapshot`    | full `AlchemistState` (sent on each WS connect)                    |
| `log`         | `{"line": str}`                                                    |
| `phase`       | `{"phase": "generation"\|"judging"\|"dpo"\|"rules"\|"idle"}`       |
| `rules`       | `[StyleRule, …]` (full list)                                       |
| `arena`       | `{"candidates": [Candidate, …], "hard_negative": Candidate?}`     |
| `dpo`         | one `DPOPair`                                                      |
| `chunk_start` | `{"chunk_index": int, "context_preview": str}`                    |
| `chunk_done`  | `{"chunk_index": int, "dpo_emitted": int}`                        |

When you change this list, update `frontend/src/store.ts` in the same commit.

## Persistence

Two independent disk artifacts, each with a different durability model:

- `data/dpo.jsonl` — **append-only training log**. Authoritative for DPO pairs;
  one line per `DPOPair`. The in-memory `state.dpo_pairs` is just a live cache
  for `/infer`'s few-shot selector and is rebuilt from this file on each boot.
- `data/snapshots/state.json` — **atomic full-rewrite** each chunk, holding
  `rules` + `chunks_processed`. A `state.json.bak` is kept as a one-generation
  safety net.

The snapshot is written **after** `dpo.jsonl` is appended and **before**
`chunk_done` is broadcast on the WebSocket — so the dashboard's reported
progress is always ≤ what's been persisted.

On startup, `server.py::lifespan` does two recoveries in order:
1. `persistence.snapshot.load()` → restores rules + chunk counter
2. `persistence.dpo_log.load_pairs()` → replays `dpo.jsonl` into `state.dpo_pairs`

Transient fields (arena candidates, logs, current phase, previews) are
deliberately not persisted.

All persistence IO lives under `core/backend/persistence/` and is the only
module that knows file paths or atomicity details — `engine.py` and
`server.py` just call into it. Engine still owns the *append* to `dpo.jsonl`
via its own constant for now; future PRs may consolidate.

## Resumable training (PR-2)

Two persistence files plus a deterministic chunk_id give the feeder /
backend pair crash-safe, idempotent training.

- **`data/progress/<sha>.json`** — per-novel cursor with the slicing params
  (`chunk_size`, `ctx`, `overlap`) and the `next_char_offset` to resume from.
  Atomically rewritten by the engine after each chunk completes.
- **`data/seen/<sha>.txt`** — append-only log of every committed `chunk_id`,
  loaded into an in-memory set on first access for O(1) lookup.

Each chunk carries:

```
chunk_id = "<sha[:12]>:cs<chunk_size>:ctx<ctx>:ov<overlap>:off<char_offset>"
```

Embedding the slicing params in the id means changing any of them yields a
fresh id-space — old progress doesn't accidentally apply to a newly re-sliced
run.

**Flow on `python scripts/train.py --path X.txt`:**

1. Feeder hashes `X.txt` → `sha256`.
2. Feeder GETs `/progress?novel_sha256=<sha>` and, if params match, jumps
   `--start` forward to `next_char_offset`. Pass `--no-resume` to skip this.
3. Feeder slides the window, tags each chunk with `chunk_id` + slicing
   metadata, POSTs to `/trigger_training`.
4. Engine's worker checks `seen_chunks.contains(...)` BEFORE incrementing
   counters or spending tokens — duplicates are a silent no-op.
5. After successful processing, the engine appends `chunk_id` to the seen
   log and atomically advances the per-novel cursor.

Order at chunk completion (matters for crash semantics):
`dpo.jsonl append → state.json snapshot → seen log append → progress.json rewrite`.
A crash anywhere leaves the cursor either correct or behind — never ahead.

## Inference (`/infer`)

There is no fine-tuned model in this system. `data/dpo.jsonl` is the artifact you'd feed to
a downstream DPO trainer. Until that's wired up, `/infer` does the next-best thing: it
prompts the base LLM with the top-K rules (sorted by hit_count) plus the top-N highest-scored
DPO `chosen` examples as few-shot, then asks for a continuation. This is a prompt-time RAG
over the learned style, not a model with weights changed.

## API key resolution

`core/backend/server.py` calls `load_dotenv(REPO_ROOT/".env")` once at startup. The
`LLMClient` reads:

- `LLM_PROVIDER` (forces choice; otherwise auto-detects from which key is set)
- `ANTHROPIC_API_KEY` + `ANTHROPIC_MODEL` (default `claude-sonnet-4-6`)
- `OPENAI_API_KEY` + `OPENAI_MODEL` (default `gpt-4o-mini`)

Changing `.env` requires restarting the backend.
