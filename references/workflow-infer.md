# Workflow — Using the trained style

Load this when the user wants to write or continue a passage in a previously trained voice.

## What "trained style" actually is

There is **no fine-tuned model**. After training, the system holds two artifacts:

1. **Style rules** in memory (live, decay over time) — short Chinese phrases like
   "短句堆叠制造紧张感" extracted from the truth chunks.
2. **DPO pairs** in `core/data/dpo.jsonl` — pairs of `(chosen, rejected)` continuations.

`/infer` prompts the base LLM with the top-K rules + top-N highest-scoring DPO `chosen`
examples as few-shot, and asks for a continuation. This is prompt-time RAG over the learned
style, not a model with new weights.

If the user expects "the model has been fine-tuned", correct that gently and explain the
distinction. The DPO file is the artifact they'd hand to a downstream DPO trainer (TRL,
LLaMA-Factory, etc.) — that's a separate pipeline this skill does not run.

## Preconditions

- Backend up (`doctor.py`'s `services.backend.up == true`)
- Some training has happened (`data.dpo_pairs_on_disk > 0` and/or `data.rules > 0`).
  If both are zero, tell the user there's no learned style yet and offer to run training
  first.

If the backend was just restarted, `rules` will be 0 (in-memory state is lost). The DPO file
on disk is still the durable artifact. `/infer` only uses *in-memory* rules + DPO pairs, so
inference quality drops after a restart until new chunks come in. Tell the user this if
they ask why the result feels generic.

## The call

```
python scripts/infer.py --context "<the user's upstream passage>" \
                        [--top_rules 5] [--few_shot 2] \
                        [--max_tokens 600] [--temperature 0.85]
```

Or, if they hand you a long context, write it to a file and pass `--context-file`.

The script prints the continuation to stdout. With `--json` it emits the full response
(`continuation`, `rules_used`, `fewshot_used`).

## Tuning advice

- More `--top_rules` = more constraint, more style fidelity, sometimes mechanical output.
- More `--few_shot` = stronger imitation, but eats context and biases toward those examples'
  topics — keep it small (2–3) unless the user asks otherwise.
- Lower `--temperature` (≈0.5) for high fidelity; higher (≈1.0) for creativity. Default 0.85
  is the trained-style sweet spot.

If the user is unhappy with the output, the right next moves (in order):
1. Run training on more of the novel (more chunks → better rules + more DPO examples).
2. Increase `--few_shot` to 4–6.
3. Lower temperature to 0.6.
4. Look at the rules in the dashboard; if they're shallow ("生动", "细腻"), the rule
   extraction prompt may be drifting — file that as a system tweak, not a prompt tweak.
