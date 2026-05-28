"""Hybrid retrieval — alias substring + dense bge-m3 cosine, plus actor-match plot ranking.

Used by `/write` to assemble the 5-block system prompt for memory-mode
continuation. Reads union across all corpora on disk (original + user layers
co-exist transparently; rollback works by removing whole bundles).

Design notes
------------
- Alias substring match is the high-precision signal. We boost it heavily
  because exact name hits are gold for canon recall.
- Dense embedding is the high-recall signal — catches synonym / paraphrase
  references the alias path misses.
- Confidence (`training` > `approved` > `inferred`) weighs every score, so
  approved-layer entries lose to original-layer entries on ties.
- Plot ranking is intentionally simpler — actor / location string match only.
  Embedding ranking for events adds complexity (event summaries are short and
  context-bound) without clear ROI in v1.
"""
from __future__ import annotations

from typing import List, Optional, Tuple

import numpy as np

from backend.models import CanonEntity, DPOPair, PlotEvent, StyleRule
from backend.memory import canon as _canon
from backend.memory import plot as _plot
from backend.persistence import dpo_log as _dpo
from backend.persistence import paths as _paths
from backend.persistence import snapshot as _snap


def _all_corpora(scope: Optional[List[str]]) -> List[str]:
    return scope if scope is not None else _paths.list_corpora()


# ---------------------------------------------------------------------------
# Canon
# ---------------------------------------------------------------------------

def retrieve_canon(
    context: str,
    *,
    top_k: int = 5,
    scope: Optional[List[str]] = None,
) -> List[CanonEntity]:
    """Hybrid: alias substring (precision) + bge-m3 cosine (recall). Top-K
    after fusing both signals, weighted by per-entity confidence."""
    corpora = _all_corpora(scope)
    if not corpora:
        return []

    # 1. Collect all entities + embeddings
    all_entities: List[CanonEntity] = []
    all_embs: List[Optional[np.ndarray]] = []
    for cid in corpora:
        store = _canon.get(cid)
        for e in store.entities:
            all_entities.append(e)
            all_embs.append(store.embeddings.get(e.id))
    if not all_entities:
        return []

    # 2. Alias substring hits — score by alias length² × confidence
    alias_scores: dict[str, float] = {}
    for e in all_entities:
        for name in {e.canonical_name, *e.aliases}:
            if name and name in context:
                bonus = (len(name) ** 2) * e.confidence
                if e.id not in alias_scores or alias_scores[e.id] < bonus:
                    alias_scores[e.id] = bonus

    # 3. Dense embedding hits — cosine top-3K, score = cosine × confidence
    dense_scores: dict[str, float] = {}
    valid_pairs = [(i, emb) for i, emb in enumerate(all_embs) if emb is not None]
    if valid_pairs:
        try:
            from backend.embedding.canon_embedder import CanonEmbedder, cosine_top_k
            q = CanonEmbedder.encode_one(context[-400:] or context)
            matrix = np.stack([emb for _, emb in valid_pairs])
            idx_map = [i for i, _ in valid_pairs]
            for rel_idx, score in cosine_top_k(q, matrix, top_k * 3):
                ent = all_entities[idx_map[rel_idx]]
                weighted = score * ent.confidence
                if ent.id not in dense_scores or dense_scores[ent.id] < weighted:
                    dense_scores[ent.id] = weighted
        except Exception as e:
            print(f"[retrieval] dense canon lookup failed: {e!r}")

    # 4. Fuse: normalize each layer independently, sum, then top-K
    fused: dict[str, float] = {}
    if alias_scores:
        max_alias = max(alias_scores.values()) or 1.0
        for k, v in alias_scores.items():
            fused[k] = fused.get(k, 0.0) + (v / max_alias) * 1.5  # alias = high-precision boost
    if dense_scores:
        max_dense = max(dense_scores.values()) or 1.0
        for k, v in dense_scores.items():
            fused[k] = fused.get(k, 0.0) + (v / max_dense)

    by_id = {e.id: e for e in all_entities}
    ranked = sorted(fused.items(), key=lambda x: x[1], reverse=True)
    return [by_id[k] for k, _ in ranked[:top_k]]


# ---------------------------------------------------------------------------
# Plot
# ---------------------------------------------------------------------------

def retrieve_plot(
    context: str,
    *,
    top_k: int = 3,
    scope: Optional[List[str]] = None,
) -> List[PlotEvent]:
    """Rank events by actor / location string overlap with `context`."""
    corpora = _all_corpora(scope)
    if not corpora:
        return []

    all_events: List[PlotEvent] = []
    for cid in corpora:
        all_events.extend(_plot.get(cid).events)
    if not all_events:
        return []

    scored: List[Tuple[float, int, PlotEvent]] = []
    for i, ev in enumerate(all_events):
        score = 0.0
        for actor in ev.primary_actors:
            if actor and actor in context:
                score += 2.0 * ev.confidence
        if ev.location and ev.location in context:
            score += 1.0 * ev.confidence
        if score > 0:
            scored.append((score, i, ev))

    scored.sort(key=lambda x: (x[0], x[1]), reverse=True)
    return [ev for _, _, ev in scored[:top_k]]


# ---------------------------------------------------------------------------
# Rules (style)
# ---------------------------------------------------------------------------

def aggregate_rules(
    *,
    top_k: int = 5,
    scope: Optional[List[str]] = None,
) -> List[StyleRule]:
    """Top-K style rules across all corpora, ranked by (hit_count, lifespan)."""
    corpora = _all_corpora(scope)
    pool: List[StyleRule] = []
    for cid in corpora:
        snap = _snap.load(cid)
        if snap is not None:
            pool.extend(snap.rules)
    pool.sort(key=lambda r: (r.hit_count, r.lifespan), reverse=True)
    return pool[:top_k]


# ---------------------------------------------------------------------------
# DPO few-shot
# ---------------------------------------------------------------------------

def fewshot_pairs(
    *,
    top_n: int = 2,
    scope: Optional[List[str]] = None,
) -> List[DPOPair]:
    """Top-N DPO chosen examples across all corpora, ranked by chosen_score."""
    corpora = _all_corpora(scope)
    pool: List[DPOPair] = []
    for cid in corpora:
        pool.extend(_dpo.load_pairs(cid))
    pool.sort(key=lambda p: p.chosen_score, reverse=True)
    return pool[:top_n]


# ---------------------------------------------------------------------------
# Prompt assembly
# ---------------------------------------------------------------------------

def format_entity(e: CanonEntity) -> str:
    """Compact single-line representation for system-prompt injection."""
    parts = [f"【{e.type}】{e.canonical_name}"]
    if e.aliases:
        parts.append("/" + "/".join(e.aliases[:5]))
    if e.attributes:
        kv = "，".join(f"{k}={v}" for k, v in list(e.attributes.items())[:4])
        parts.append(f"({kv})")
    return "".join(parts)


def format_event(ev: PlotEvent) -> str:
    actors = "/".join(ev.primary_actors[:4]) if ev.primary_actors else "—"
    loc = ev.location or "—"
    marker = f"[{ev.chapter_marker}] " if ev.chapter_marker else ""
    return f"{marker}{ev.summary}（人物：{actors}；地：{loc}）"


def assemble_system_prompt(
    *,
    context: str,
    top_rules: int = 5,
    top_canon: int = 5,
    top_plot: int = 3,
    few_shot: int = 2,
    scope: Optional[List[str]] = None,
) -> dict:
    """Build the 5-block memory-mode system prompt and return both the assembled
    string and counts for the response payload."""
    rules = aggregate_rules(top_k=top_rules, scope=scope)
    entities = retrieve_canon(context, top_k=top_canon, scope=scope)
    events = retrieve_plot(context, top_k=top_plot, scope=scope)
    shots = fewshot_pairs(top_n=few_shot, scope=scope)

    rule_block = "\n".join(f"- {r.description}" for r in rules) or "（无）"
    canon_block = "\n".join(f"- {format_entity(e)}" for e in entities) or "（无相关角色/地点/物件）"
    plot_block = "\n".join(f"- {format_event(e)}" for e in events) or "（无相关事件）"
    if shots:
        fewshot_block = "\n\n".join(
            f"【示例上文】\n{p.prompt[-300:]}\n【示例续写】\n{p.chosen}" for p in shots
        )
    else:
        fewshot_block = "（暂无示例）"

    system = (
        "你是续写引擎。你拥有【从训练语料习得的世界观与文风记忆】。请：\n"
        "1) 严格保持下列【风格规则】的写作习惯\n"
        "2) 涉及到下列【角色/地点/物件】时遵循其设定，不要凭空改写\n"
        "3) 接续【最近事件】所建立的剧情线索，新写内容必须自洽\n"
        "4) 模仿【风格示例】的语感与笔调\n"
        "只输出续写文本，不要前言、不要解释、不要标题、不要 Markdown。长度 300~800 字。\n\n"
        f"【风格规则】\n{rule_block}\n\n"
        f"【角色/地点/物件】\n{canon_block}\n\n"
        f"【最近事件】\n{plot_block}\n\n"
        f"【风格示例】\n{fewshot_block}"
    )
    return {
        "system": system,
        "rules_used": len(rules),
        "canon_used": len(entities),
        "plot_used": len(events),
        "fewshot_used": len(shots),
    }
