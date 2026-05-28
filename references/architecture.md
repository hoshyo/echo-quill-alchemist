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
    frontend/               ← Vite/React/Zustand dashboard
    scripts/feeder.py       ← internal feeder (called by scripts/train.py)
    data/
      dpo.jsonl             ← every DPO pair appended here
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
