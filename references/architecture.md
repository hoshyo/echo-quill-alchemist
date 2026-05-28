# Architecture — Echo-Quill Alchemist

How the system actually works, written for the agent that operates it. Read this when the
user asks "how does this work" or when you need to reason about a non-obvious behavior.

## One-line summary

A novel is sliced into `(context, truth)` windows; for each window the LLM generates several
candidate continuations plus one deliberately disfigured "hard negative"; a dual-tower judge
(MiniLM cosine + ROUGE-L F1) ranks them; a DPO pair is emitted. Concurrently the LLM extracts
structured **canon** (entities) and **plot** (events) into per-corpus stores, and bge-m3
embeddings let later "memory-mode" continuations retrieve the right characters, places, and
recent events. A live React dashboard watches the whole thing over WebSocket.

## Layout (PR-3)

```
repo_root/
  SKILL.md                  ← skill router (natural-language surface)
  scripts/                  ← skill scripts the agent invokes
    write.py                  memory-mode continuation
    infer.py                  pure-style no-memory continuation (legacy, kept)
    train.py                  training (orchestrator over core/scripts/feeder.py)
    rollback.py               bundle-level archive / restore
    doctor.py                 JSON status (always run first)
    {start,stop}_services.py  backend / frontend lifecycle
  references/               ← these docs, loaded on demand
  core/                     ← the actual system
    backend/
      models.py             ← Pydantic black-boxes (StyleRule, CanonEntity, PlotEvent…)
      engine.py             ← DualTowerJudge + LLMClient + Alchemist (per-corpus state)
      server.py             ← FastAPI + WebSocket
      persistence/          ← corpus-scoped IO (paths, atomic_io, snapshot, dpo_log,
                              progress, seen_chunks)
      embedding/            ← canon_embedder.py: lazy bge-m3 wrapper (1024-d, normalized)
      memory/               ← canon.py (CanonStore), plot.py (PlotStore),
                              extractors.py (LLM JSON), retrieval.py (hybrid)
    frontend/               ← Vite/React/Zustand dashboard
    scripts/feeder.py       ← internal feeder (called by scripts/train.py)
    data/
      corpora/<layer>/<bundle>/   ← self-contained training bundle
        meta.json                   {corpus_id, layer, source_path, sha, created_at}
        novel.txt | text.txt        snapshot of source (for rollback / re-train)
        snapshot.json               rules + chunks_processed (atomic, .bak rotated)
        dpo.jsonl                   append-only DPO pairs
        progress.json               feeder cursor (next_char_offset)
        seen.txt                    chunk_id idempotency log
        canon.jsonl                 entities (atomic rewrite on each ingest)
        plot.jsonl                  events (append-only)
      embeddings/<safe_id>.canon.npz  parallel ids[] + 1024-d vecs[] for canon
      archive/<layer>/<bundle>_<ts>/  rollback target (one-way bin, --restore reverses)
      drafts/<ts>.txt             every write.py output (for "train this one" later)
      logs/                       service stdout/stderr
  .env                      ← LLM keys (optional with CC Switch)
  .echo-quill.state.json    ← runtime PIDs (managed by start/stop_services)
```

## Three design invariants (do not violate)

1. **No subjective LLM scoring.** Quality is `α·MiniLM_cosine + β·ROUGE-L F1` (defaults
   α=0.6, β=0.4). The LLM only generates and does structured JSON extraction (canon / plot /
   rules). Never "rate this 0–10".
2. **Every chunk emits at least one DPO pair.** Hard-negative continuation is generated
   alongside the Best-of-N pool; `best_normal vs hard_negative` is the floor.
3. **Every persisted record belongs to one corpus bundle.** No global state at the data root.
   Rollback is `mv corpora/<id>/ archive/<id>_<ts>/`. Reads at retrieve time union all bundles.

## Per-chunk pipeline (`/trigger_training`)

```
[idempotency gate]  seen_chunks.contains(corpus_id, chunk_id) → short-circuit

phase=generation
  ├ best_of_N normal candidates (LLM, parallel)
  └ 1 hard-negative candidate    (LLM, parallel)

phase=judging
  for each candidate:
    semantic = MiniLM cosine(candidate, truth)
    rouge    = ROUGE-L F1(candidate, truth)
    composite = α·semantic + β·rouge
  sort by composite desc

phase=dpo
  emit DPOPair(best, hard_negative)                       ← always
  if best.composite − worst.composite ≥ θ (0.05):
    emit DPOPair(best, worst_normal)                      ← when meaningful
  → corpora/<id>/dpo.jsonl   (append)

phase=rules
  - existing rules: MiniLM_cosine(rule, truth) ≥ 0.32 → hit++ , lifespan = min(initial, +1)
                                                     else → lifespan -= 1
  - LLM extract ≤5 new rule descriptions from truth; merge unique into pool

phase=canon
  - LLM extract ≤5 entity records {type, canonical_name, aliases, attributes}
  - alias-overlap dedup against existing entities; merge attrs into matches
  - new entities: bge-m3 encode → embeddings cache
  - persist (atomic full-rewrite + npz)

phase=plot
  - LLM extract ≤5 event records {summary, actors, location, marker}
  - dedup on summary equality; append to corpora/<id>/plot.jsonl

[durability barrier]
  - snapshot save (atomic, .bak rotated)
  - seen_chunks add(corpus_id, chunk_id)
  - progress update(corpus_id, next_char_offset, …)

phase=idle  → broadcast chunk_done
```

**Order matters at the durability barrier.** dpo.jsonl is appended first (line-atomic),
then snapshot.json is rewritten, then chunk_id is committed to seen.txt, then progress.json
advances. A crash anywhere leaves the cursor either correct or *behind* — never ahead. This
keeps PR-2's resume semantics intact under the new layout.

## Memory mode continuation (`/write`)

```
context  →  retrieval (corpora-union)
              ├─ Style rules: top-K by (hit_count, lifespan)
              ├─ Canon: hybrid hits
              │     • alias substring match  (len² × confidence)
              │     • bge-m3 cosine top-3K   (cosine × confidence)
              │     normalize each layer, sum, top-K
              ├─ Plot: actor / location string overlap in context, ≥1 → score by confidence
              └─ Few-shot: top-N DPO chosen by chosen_score
                 ↓
       5-block system prompt
       【风格规则】 【角色/地点/物件】 【最近事件】 【风格示例】
                 ↓
       LLM.complete()
                 ↓
       draft_path  =  core/data/drafts/<ts>.txt   (auto-archive)
       response    →  client
```

**No state mutation on /write.** The drafts file is a log artifact; canon/plot/rules don't
change from a generation. Memory grows *only* when the user explicitly trains (a draft or
any other .txt) via `train.py --layer user`.

## Pure-style mode (`/infer`)

Uses only the currently-loaded corpus's rules + DPO few-shot (no canon, no plot). Kept as
a fast fallback when the user explicitly wants "style only, ignore what was learned about
the world". Same prompt template as the original system, untouched.

## Corpus identity

`corpus_id` is the relative path under `corpora/`, encoding both layer and bundle:

| Layer    | Allocation rule                                  | Example                       |
|----------|--------------------------------------------------|-------------------------------|
| original | `original/<sha256[:12]>`                         | `original/b10aaeaf693b`       |
| user     | `user/<YYYYMMDD_HHMMSS>_<rand4>`                 | `user/20260528_091223_x7k2`   |

`scripts/train.py` allocates the id, creates the bundle dir with `meta.json` + a snapshot
of the source text, then delegates per-chunk feeding to `core/scripts/feeder.py`. The
feeder embeds `corpus_id` in every `/trigger_training` payload; the engine uses it for
state switching, idempotency keying, and all persistence calls.

## Rollback

```
scripts/rollback.py --to original
  → for each corpora/user/<b>:
        mv corpora/user/<b>  archive/user/<b>_<ts>

scripts/rollback.py --remove user/20260528_x7k2
  → mv corpora/user/20260528_x7k2  archive/user/20260528_x7k2_<ts>

scripts/rollback.py --restore user/20260528_x7k2_<ts>
  → mv archive/user/20260528_x7k2_<ts>  corpora/user/20260528_x7k2

scripts/rollback.py --wipe-all --yes
  → rm -rf core/data/   (last resort; everything goes including archive/)
```

Archive is a one-way trash bin: nothing is unrecoverable except via `--wipe-all`. After
any structural change the backend should be restarted so its in-memory caches
(`canon._stores`, `plot._stores`, alchemist.current_corpus_id) refresh.

## State (Pydantic black-boxes)

- `StyleRule(id, description, lifespan=15, initial_lifespan=15, hit_count=0, born_at, last_hit_at)`
- `CanonEntity(id, type, canonical_name, aliases, attributes, source, corpus_id, confidence, hit_count, born_at, last_seen_at, last_seen_chunk)`
- `PlotEvent(id, summary, primary_actors, location, chapter_marker, source, corpus_id, confidence, born_at, chunk_index)`
- `Candidate(text, semantic_score, rouge_score, composite_score, is_hard_negative)`
- `DPOPair(prompt, chosen, rejected, chosen_score, rejected_score, margin, reason, created_at)`
- `AlchemistState(corpus_id, rules, …, dpo_pairs, canon_count, plot_count, current_phase, chunks_processed, last_*_preview)`

`AlchemistState.corpus_id` reflects which corpus the engine is currently "tuned to" — set
by `EchoQuillAlchemist.switch_corpus()`. Each `/trigger_training` payload's `corpus_id`
drives the switch.

## Wire formats

WebSocket frames (`backend/models.py::WSMessage`):

| `type`          | `payload` shape                                                |
|-----------------|----------------------------------------------------------------|
| `snapshot`      | full `AlchemistState` (sent on each WS connect)                |
| `log`           | `{"line": str}`                                                |
| `phase`         | `{"phase": "generation" \| "judging" \| "dpo" \| "rules" \| "canon" \| "plot" \| "idle"}` |
| `rules`         | `[StyleRule, …]`                                               |
| `arena`         | `{"candidates": [Candidate, …], "hard_negative": Candidate?}`  |
| `dpo`           | one `DPOPair`                                                  |
| `canon`         | `{"deltas": [CanonEntity, …], "total": int}`                   |
| `plot`          | `{"deltas": [PlotEvent, …], "total": int}`                     |
| `chunk_start`   | `{"chunk_index": int, "context_preview": str, "corpus_id": str}` |
| `chunk_done`    | `{"chunk_index": int, "dpo_emitted": int}`                     |
| `corpus_switch` | `{"corpus_id": str}` — sent when active corpus changes         |

When this list changes, update `frontend/src/store.ts` in the same commit.

## HTTP endpoints

| Method | Path                 | Body / params                              | Purpose                                          |
|--------|----------------------|--------------------------------------------|--------------------------------------------------|
| POST   | `/trigger_training`  | `TrainingRequest` (incl. `corpus_id`)      | enqueue chunk for the alchemist worker          |
| POST   | `/write`             | `WriteRequest`                             | memory-mode continuation (5-block prompt)        |
| POST   | `/infer`             | `InferRequest`                             | pure-style continuation (rules + few-shot only)  |
| GET    | `/state`             |                                            | current `AlchemistState`                         |
| GET    | `/healthz`           |                                            | live counters incl. `corpus_id`                  |
| GET    | `/corpora`           |                                            | list all corpora on disk + active                |
| GET    | `/progress`          | `?corpus_id=...`                           | feeder cursor for that corpus                    |
| WS     | `/ws/alchemist`      |                                            | push-only event stream                           |

## API key resolution

`core/backend/server.py` calls `load_dotenv(REPO_ROOT/".env")` once at startup. The
`LLMClient` reads:

- `LLM_PROVIDER` (forces choice; otherwise auto-detects from which key is set)
- `ANTHROPIC_AUTH_TOKEN` → `Authorization: Bearer …` (Claude Code / relay style)
- `ANTHROPIC_API_KEY` → `x-api-key: …` (official sk-ant-… key)
- `ANTHROPIC_BASE_URL` (default `https://api.anthropic.com`)
- `ANTHROPIC_MODEL` (default `claude-sonnet-4-6`)
- `OPENAI_API_KEY` + `OPENAI_BASE_URL` + `OPENAI_MODEL` (default `gpt-4o-mini`)

Changing `.env` or switching CC Switch profile requires restarting the backend.

## Two embedders, deliberately not unified

- **MiniLM (`all-MiniLM-L6-v2`, 384-d, ~90 MB)** — `DualTowerJudge`. Symmetric short-text
  similarity for candidate ranking and rule-match detection. Eagerly loaded at server
  startup.
- **bge-m3 (`BAAI/bge-m3`, 1024-d, ~2.3 GB)** — `CanonEmbedder` (lazy singleton). Used
  for canon entity embedding at ingest time and dense canon retrieval at write time.
  The default install flow runs `scripts/prefetch_models.py` after `install_deps.py`,
  so by the time the server starts both model snapshots are already in the local HF
  cache. The lazy-load path inside `CanonEmbedder.model()` is therefore the *resilience*
  path — it covers (a) someone who skipped the prefetch gate, and (b) a corrupted
  cache that gets cleared between sessions — not the primary download trigger.

The judge's α/β/threshold constants were tuned against MiniLM's distribution — do NOT swap
its model without re-tuning. bge-m3 stays scoped to memory retrieval to keep the dual-tower
invariant stable.

## What's NOT here

- No fine-tuning. `dpo.jsonl` files are the artifact you'd hand to TRL / LLaMA-Factory.
- No per-approve interactive session. Generation is stateless: read-only on canon/plot.
- No edit/regenerate ceremony. If the user dislikes a draft, they tell the model in
  natural language ("把李四改成女性") and pass it as `extra_instruction` to `/write`.
- No reranker. Hybrid (alias + dense) is enough at corpus sizes <~10k entities. A
  cross-encoder reranker is a future drop-in for `memory/retrieval.py::retrieve_canon`.
- No vector database. Numpy brute-force cosine over <~10k vectors is sub-10ms; switch
  to FAISS only if a corpus grows past that.
