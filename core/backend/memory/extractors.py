"""LLM-based structured extraction for Canon (entities) and Plot (events).

The LLM here is a *structured-data extractor*, not a judge. It answers
"what entities/events does this passage mention?" with strict JSON. This
respects invariant 1: no subjective scoring path is introduced.

Both extractors return at most 5 items per call to bound cost — a single
chunk rarely yields more salient items, and over-extraction creates noisy
canon that hurts retrieval downstream.

Output parsing is forgiving: code fences, leading "json", and trailing
commentary are stripped before json.loads. Malformed responses produce an
empty list rather than raising — the engine continues, the chunk just
contributes nothing to canon/plot for that round.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List


CANON_EXTRACTION_SYSTEM = (
    "你是小说世界观提取器。从给定文本中提取出现的【人物 / 地点 / 物件 / 术语】。\n"
    "输出 JSON 数组，每条形如：\n"
    "{\"type\":\"character\",\"canonical_name\":\"林黛玉\","
    "\"aliases\":[\"黛玉\",\"林姑娘\",\"颦儿\"],"
    "\"attributes\":{\"role\":\"贾府表小姐\",\"traits\":\"敏感多愁\",\"habitat\":\"潇湘馆\"}}\n"
    "约束：\n"
    "- type 必须是 character / place / item / term 之一\n"
    "- canonical_name 取文中最常出现或最规范的写法\n"
    "- aliases 列出该实体在本段中出现的所有其它称呼（不重复 canonical_name）\n"
    "- attributes 是 string→string 的关键事实，不超过 5 条；只写文中明确提到的，不要推测\n"
    "- 整个数组不超过 5 条；只包括本段实际登场或明确指代的实体\n"
    "- 严禁臆造、严禁泛化（如 \"主角\" \"某地\"）\n"
    "只输出 JSON 数组，无解释、无 Markdown。"
)

PLOT_EXTRACTION_SYSTEM = (
    "你是小说事件提取器。从给定文本中提取关键叙事事件。\n"
    "输出 JSON 数组，每条形如：\n"
    "{\"summary\":\"林黛玉初进荣国府\","
    "\"primary_actors\":[\"林黛玉\",\"贾母\"],"
    "\"location\":\"荣国府\","
    "\"chapter_marker\":\"第三回\"}\n"
    "约束：\n"
    "- summary 一句话，≤30 字，必须是动作/事件而非状态描述\n"
    "- primary_actors 是参与该事件的核心人物名列表\n"
    "- location 不确定可空字符串\n"
    "- chapter_marker 是文中显式提到的章节/时间/季节标记，没有就空字符串\n"
    "- 整个数组不超过 5 条；只挑【确实推动情节】的事件\n"
    "- 严禁臆造未发生事件、严禁记录纯心理描写\n"
    "只输出 JSON 数组，无解释、无 Markdown。"
)


def _strip_fences(s: str) -> str:
    s = (s or "").strip()
    if s.startswith("```"):
        s = s.strip("`").strip()
        if s.lower().startswith("json"):
            s = s[4:].strip()
    return s


def _slice_array(s: str) -> str:
    l = s.find("[")
    r = s.rfind("]")
    return s[l : r + 1] if (l >= 0 and r > l) else ""


def parse_json_array(raw: str) -> List[Dict[str, Any]]:
    """Best-effort extraction of a JSON array from LLM text. Empty list on failure."""
    body = _slice_array(_strip_fences(raw))
    if not body:
        return []
    try:
        arr = json.loads(body)
    except Exception:
        return []
    if not isinstance(arr, list):
        return []
    return [x for x in arr if isinstance(x, dict)]


# ---------------------------------------------------------------------------
# Validators — clamp shape so downstream code can trust the records
# ---------------------------------------------------------------------------

_VALID_CANON_TYPES = {"character", "place", "item", "term"}


def normalize_canon_records(raw: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for r in raw:
        t = str(r.get("type", "")).strip().lower()
        if t not in _VALID_CANON_TYPES:
            continue
        name = str(r.get("canonical_name", "")).strip()
        if not name:
            continue
        aliases_raw = r.get("aliases") or []
        aliases = [str(a).strip() for a in aliases_raw if isinstance(a, (str, int, float))]
        aliases = [a for a in aliases if a and a != name][:8]
        attrs_raw = r.get("attributes") or {}
        attributes: Dict[str, str] = {}
        if isinstance(attrs_raw, dict):
            for k, v in list(attrs_raw.items())[:5]:
                if isinstance(k, str) and isinstance(v, (str, int, float)):
                    attributes[k.strip()] = str(v).strip()
        out.append({
            "type": t,
            "canonical_name": name,
            "aliases": aliases,
            "attributes": attributes,
        })
    return out[:5]


def normalize_plot_records(raw: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for r in raw:
        summary = str(r.get("summary", "")).strip()
        if not summary:
            continue
        actors_raw = r.get("primary_actors") or []
        actors = [str(a).strip() for a in actors_raw if isinstance(a, (str, int, float))]
        actors = [a for a in actors if a][:6]
        location = str(r.get("location", "")).strip() or None
        chapter = str(r.get("chapter_marker", "")).strip() or None
        out.append({
            "summary": summary[:60],  # hard cap; the prompt asks for ≤30 but trust nothing
            "primary_actors": actors,
            "location": location,
            "chapter_marker": chapter,
        })
    return out[:5]
