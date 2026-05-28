"""Echo-Quill Alchemist core engine.

Two design invariants:

  1. Subjective scoring is forbidden. Composite score = alpha * MiniLM_cosine + beta * ROUGE-L.
     The LLM is *only* a generator (and a structured rule extractor); it never judges quality.

  2. Every chunk yields at least one DPO pair. We enforce this by always generating one
     deliberately disfigured "hard negative" continuation alongside the Best-of-N pool.
     best_normal vs hard_negative is the floor; if the spread between best_normal and
     worst_normal exceeds `dpo_margin_threshold`, we emit a second pair on top.
"""
from __future__ import annotations

import asyncio
import json
import os
import random
from datetime import datetime, timezone
from typing import Awaitable, Callable, List, Optional

import httpx
import numpy as np
from rouge_score import rouge_scorer
from sentence_transformers import SentenceTransformer

from backend.models import (
    AlchemistState,
    Candidate,
    DPOPair,
    StyleRule,
    TrainingRequest,
    WSMessage,
)


# ---------------------------------------------------------------------------
# Dual Tower Judge
# ---------------------------------------------------------------------------

class DualTowerJudge:
    """Two independent towers strip the LLM of subjective scoring authority.

    Tower A — semantic: sentence-transformers MiniLM cosine similarity.
    Tower B — lexical/structural: ROUGE-L F1 (the style fingerprint).

    Composite = alpha * semantic + beta * rouge. Defaults 0.6 / 0.4 favor meaning over
    surface overlap, so paraphrase-correct continuations aren't punished, but a continuation
    that drifts off-topic can't compensate by parroting truth tokens.
    """

    def __init__(
        self,
        model_name: str = "sentence-transformers/all-MiniLM-L6-v2",
        alpha: float = 0.6,
        beta: float = 0.4,
        device: Optional[str] = None,
    ):
        self.model_name = model_name
        self.alpha = alpha
        self.beta = beta
        print(f"[judge] loading {model_name} (first run downloads ~90MB) ...")
        self.embedder = SentenceTransformer(model_name, device=device)
        self.rouge = rouge_scorer.RougeScorer(["rougeL"], use_stemmer=False)
        print("[judge] ready.")

    def _embed(self, texts: List[str]) -> np.ndarray:
        return self.embedder.encode(texts, convert_to_numpy=True, normalize_embeddings=True)

    def semantic(self, a: str, b: str) -> float:
        if not a.strip() or not b.strip():
            return 0.0
        va, vb = self._embed([a, b])
        return float(np.dot(va, vb))

    def rouge_l(self, a: str, b: str) -> float:
        if not a.strip() or not b.strip():
            return 0.0
        return float(self.rouge.score(b, a)["rougeL"].fmeasure)

    def score_one(self, candidate: str, truth: str) -> Candidate:
        s = self.semantic(candidate, truth)
        r = self.rouge_l(candidate, truth)
        return Candidate(
            text=candidate,
            semantic_score=s,
            rouge_score=r,
            composite_score=self.alpha * s + self.beta * r,
        )

    def rule_match(self, rule_desc: str, passage: str, threshold: float) -> bool:
        """Decide whether `passage` exhibits `rule_desc` by encoder proximity."""
        return self.semantic(rule_desc, passage) >= threshold


# ---------------------------------------------------------------------------
# LLM client (HTTP, env-keyed)
# ---------------------------------------------------------------------------

class LLMClient:
    """Async LLM client supporting Anthropic and OpenAI via env vars.

    Env:
      LLM_PROVIDER       "anthropic" | "openai"  (auto-detected if unset)
      ANTHROPIC_API_KEY  required when provider=anthropic
      ANTHROPIC_MODEL    default: claude-sonnet-4-6
      OPENAI_API_KEY     required when provider=openai
      OPENAI_MODEL       default: gpt-4o-mini
    """

    def __init__(self):
        forced = os.getenv("LLM_PROVIDER")
        if forced:
            self.provider = forced
        elif os.getenv("ANTHROPIC_API_KEY"):
            self.provider = "anthropic"
        else:
            self.provider = "openai"
        self.client = httpx.AsyncClient(timeout=120.0)

    async def aclose(self) -> None:
        await self.client.aclose()

    async def complete(
        self,
        system: str,
        user: str,
        temperature: float = 0.8,
        max_tokens: int = 800,
    ) -> str:
        if self.provider == "anthropic":
            return await self._anthropic(system, user, temperature, max_tokens)
        return await self._openai(system, user, temperature, max_tokens)

    async def _anthropic(self, system, user, temperature, max_tokens) -> str:
        key = os.getenv("ANTHROPIC_API_KEY")
        if not key:
            raise RuntimeError("ANTHROPIC_API_KEY not set")
        model = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-6")
        r = await self.client.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": model,
                "max_tokens": max_tokens,
                "temperature": temperature,
                "system": system,
                "messages": [{"role": "user", "content": user}],
            },
        )
        r.raise_for_status()
        data = r.json()
        return "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")

    async def _openai(self, system, user, temperature, max_tokens) -> str:
        key = os.getenv("OPENAI_API_KEY")
        if not key:
            raise RuntimeError("OPENAI_API_KEY not set")
        model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
        r = await self.client.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json={
                "model": model,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            },
        )
        r.raise_for_status()
        data = r.json()
        return data["choices"][0]["message"]["content"]


# ---------------------------------------------------------------------------
# The Alchemist
# ---------------------------------------------------------------------------

Broadcaster = Callable[[WSMessage], Awaitable[None]]


GENERATION_SYSTEM = (
    "你是一个小说续写引擎。给定上文，输出与上文风格一致、文笔自然的下文。\n"
    "只输出续写文本，不要前言、不要解释、不要标题、不要 Markdown。\n"
    "长度控制在 200~500 字。"
)

HARD_NEGATIVE_SYSTEM = (
    "你是一个反面教材生成器，专门写出风格毁容的续写以供对比训练。\n"
    "给定上文，故意生成低劣、突兀、流水账、AI 腔的续写：\n"
    "- 大量陈词滥调（'心中一动'、'不禁'、'暗道'、'果然不出所料'、'缓缓道'）\n"
    "- 强行总结而非展现，乱贴情感标签\n"
    "- 节奏破坏，叙事突兀转折，描写冗长无效\n"
    "- 但要看起来像真的在续写：保持人称、主要人物、基本场景\n"
    "只输出毁容版续写文本，不要任何解释、不要 Markdown。长度 200~500 字。"
)

RULE_EXTRACTION_SYSTEM = (
    "你是文体分析器。从给定文本中提炼最多 5 条「最具识别度」的风格规则。\n"
    "每条规则用一行简短中文短语描述（10~25 字），聚焦于：句式偏好、修辞习惯、节奏、意象、词汇癖好等。\n"
    "严禁内容性总结。严禁泛泛而谈（如'细腻'、'生动'）。\n"
    "只输出 JSON 数组，例如：[\"短句堆叠制造紧张感\",\"以味觉切入场景\",\"对话不带提示语\"]"
)


class EchoQuillAlchemist:
    def __init__(
        self,
        judge: DualTowerJudge,
        llm: LLMClient,
        broadcaster: Broadcaster,
        n_candidates: int = 4,
        dpo_margin_threshold: float = 0.05,
        rule_match_threshold: float = 0.32,
    ):
        self.judge = judge
        self.llm = llm
        self.broadcast = broadcaster
        self.n = n_candidates
        self.dpo_margin_threshold = dpo_margin_threshold
        self.rule_match_threshold = rule_match_threshold
        self.state = AlchemistState()

    # ---------- broadcasting helpers ----------
    async def _emit(self, type_: str, payload) -> None:
        await self.broadcast(WSMessage(type=type_, payload=payload))

    async def _log(self, line: str) -> None:
        self.state.logs.append(line)
        # cap to keep snapshot small
        if len(self.state.logs) > 500:
            del self.state.logs[: len(self.state.logs) - 500]
        await self._emit("log", {"line": line})

    async def _phase(self, name: str) -> None:
        self.state.current_phase = name
        await self._emit("phase", {"phase": name})

    # ---------- main entry point ----------
    async def process_chunk(self, req: TrainingRequest) -> dict:
        self.state.chunks_processed += 1
        idx = self.state.chunks_processed
        self.state.last_context_preview = req.context[-200:]
        self.state.last_truth_preview = req.truth[:200]

        await self._log(f"=== chunk #{idx} 入炉 (truth {len(req.truth)}字 / ctx {len(req.context)}字) ===")
        await self._emit("chunk_start", {
            "chunk_index": idx,
            "context_preview": self.state.last_context_preview,
        })

        # 1) Best-of-N + Hard Negative — fully parallel
        await self._phase("generation")
        await self._log(f"生成 {self.n} 个常规候选 + 1 个困难负样本…")
        normal_task = asyncio.gather(*(self._gen_normal(req.context) for _ in range(self.n)))
        hardneg_task = asyncio.create_task(self._gen_hard_negative(req.context))
        normal_texts, hard_neg_text = await asyncio.gather(normal_task, hardneg_task)

        # filter empty
        normal_texts = [t for t in normal_texts if t.strip()]
        if not normal_texts:
            await self._log("× 全部常规候选生成失败，跳过本 chunk。")
            await self._phase("idle")
            return {"chunk_index": idx, "dpo_emitted": 0, "skipped": True}

        # 2) Dual-tower judging
        await self._phase("judging")
        await self._log("双塔裁判打分（语义 + ROUGE）…")
        candidates = [self.judge.score_one(t, req.truth) for t in normal_texts]
        candidates.sort(key=lambda c: c.composite_score, reverse=True)

        hard_neg = self.judge.score_one(hard_neg_text, req.truth) if hard_neg_text.strip() else None
        if hard_neg is not None:
            hard_neg.is_hard_negative = True

        self.state.arena_candidates = candidates
        self.state.arena_hard_negative = hard_neg
        await self._emit("arena", {
            "candidates": [c.model_dump(mode="json") for c in candidates],
            "hard_negative": hard_neg.model_dump(mode="json") if hard_neg else None,
        })
        for i, c in enumerate(candidates):
            await self._log(
                f"  候选#{i+1}  sem={c.semantic_score:.3f}  rouge={c.rouge_score:.3f}  ∑={c.composite_score:.3f}"
            )
        if hard_neg is not None:
            await self._log(
                f"  困难负   sem={hard_neg.semantic_score:.3f}  rouge={hard_neg.rouge_score:.3f}  ∑={hard_neg.composite_score:.3f}"
            )

        # 3) DPO 相变 — guaranteed best_vs_hard_neg + optional best_vs_worst_normal
        await self._phase("dpo")
        best = candidates[0]
        worst = candidates[-1]
        new_pairs: List[DPOPair] = []

        if hard_neg is not None:
            new_pairs.append(DPOPair(
                prompt=req.context,
                chosen=best.text,
                rejected=hard_neg.text,
                chosen_score=best.composite_score,
                rejected_score=hard_neg.composite_score,
                margin=best.composite_score - hard_neg.composite_score,
                reason="best_vs_hard_negative",
            ))

        bw_margin = best.composite_score - worst.composite_score
        if len(candidates) >= 2 and bw_margin >= self.dpo_margin_threshold:
            new_pairs.append(DPOPair(
                prompt=req.context,
                chosen=best.text,
                rejected=worst.text,
                chosen_score=best.composite_score,
                rejected_score=worst.composite_score,
                margin=bw_margin,
                reason="best_vs_worst_normal",
            ))

        for p in new_pairs:
            self.state.dpo_pairs.append(p)
            await self._emit("dpo", p.model_dump(mode="json"))
            await self._log(f"  DPO[{p.reason}] margin={p.margin:.3f}")

        # 4) Style rule lifecycle update
        await self._phase("rules")
        await self._update_rules(req.truth)

        # 5) Persist DPO pairs to disk
        self._persist_dpo(new_pairs)

        await self._phase("idle")
        await self._emit("chunk_done", {"chunk_index": idx, "dpo_emitted": len(new_pairs)})
        await self._log(f"=== chunk #{idx} 出炉 — 新增 DPO 对 {len(new_pairs)} 条 ===")
        return {"chunk_index": idx, "dpo_emitted": len(new_pairs)}

    # ---------- generation ----------
    async def _gen_normal(self, context: str) -> str:
        try:
            txt = await self.llm.complete(
                system=GENERATION_SYSTEM,
                user=f"上文：\n{context}\n\n请续写：",
                temperature=0.85 + random.uniform(-0.1, 0.1),
            )
            return (txt or "").strip()
        except Exception as e:
            await self._log(f"  ! 候选生成失败: {e!r}")
            return ""

    async def _gen_hard_negative(self, context: str) -> str:
        try:
            txt = await self.llm.complete(
                system=HARD_NEGATIVE_SYSTEM,
                user=f"上文：\n{context}\n\n请输出毁容版续写：",
                temperature=1.0,
            )
            return (txt or "").strip()
        except Exception as e:
            await self._log(f"  ! 困难负样本生成失败: {e!r}")
            return ""

    # ---------- rules ----------
    async def _update_rules(self, truth: str) -> None:
        for r in self.state.rules:
            if self.judge.rule_match(r.description, truth, self.rule_match_threshold):
                r.hit_count += 1
                r.last_hit_at = datetime.now(timezone.utc)
                # successful hit grants a small lifespan refresh, capped at initial
                r.lifespan = min(r.initial_lifespan, r.lifespan + 1)
            else:
                r.lifespan -= 1

        before = len(self.state.rules)
        self.state.rules = [r for r in self.state.rules if r.lifespan > 0]
        culled = before - len(self.state.rules)
        if culled:
            await self._log(f"  规则裁汰 {culled} 条")

        # extract fresh rules from the current truth
        try:
            raw = await self.llm.complete(
                system=RULE_EXTRACTION_SYSTEM,
                user=truth,
                temperature=0.3,
                max_tokens=400,
            )
            new_descs = self._parse_rule_json(raw)
        except Exception as e:
            await self._log(f"  ! 规则提取失败: {e!r}")
            new_descs = []

        existing = {r.description for r in self.state.rules}
        added = 0
        for d in new_descs:
            if d in existing:
                continue
            self.state.rules.append(StyleRule(description=d))
            existing.add(d)
            added += 1
        if added:
            await self._log(f"  新增风格规则 {added} 条")
        await self._emit("rules", [r.model_dump(mode="json") for r in self.state.rules])

    @staticmethod
    def _parse_rule_json(raw: str) -> List[str]:
        s = (raw or "").strip()
        # strip code fences
        if s.startswith("```"):
            s = s.strip("`")
            if s.lower().startswith("json"):
                s = s[4:]
            s = s.strip()
        l = s.find("[")
        r = s.rfind("]")
        if l < 0 or r < 0:
            return []
        try:
            arr = json.loads(s[l : r + 1])
            return [str(x).strip() for x in arr if isinstance(x, (str, int, float))][:5]
        except Exception:
            return []

    # ---------- persistence ----------
    @staticmethod
    def _persist_dpo(pairs: List[DPOPair]) -> None:
        if not pairs:
            return
        os.makedirs("data", exist_ok=True)
        path = os.path.join("data", "dpo.jsonl")
        with open(path, "a", encoding="utf-8") as f:
            for p in pairs:
                f.write(json.dumps(p.model_dump(mode="json"), ensure_ascii=False) + "\n")
