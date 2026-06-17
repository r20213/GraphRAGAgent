"""Routing heuristics and Markdown rendering for the Root Agent."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

STATIC_MCP_TOOL_KEYWORDS = {
    "get_industries",
    "get_companies_in_industry",
    "get_articles_with_sentiment",
    "get_people_in_organizations",
    "find_investor_by_name",
    "find_investor_by_id",
    "find_investors_for_companies",
}

FLUFF_PATTERNS = {
    "hi",
    "hello",
    "hey",
    "thanks",
    "thank you",
    "good morning",
    "good afternoon",
}

SUMMARY_PATTERNS = {"summary", "summarize", "recap", "conversation history"}

INVESTOR_PATTERNS = {
    "investor",
    "portfolio",
    "backer",
    "funded by",
    "co-invest",
    "overlap",
}

INVESTMENT_PATTERNS = {
    "industry",
    "companies in",
    "sentiment",
    "leadership",
    "executive",
    "market",
    "articles",
}

GRAPH_PATTERNS = {
    "path",
    "traversal",
    "relationship",
    "multi-hop",
    "neighbors",
    "schema",
    "graph",
    "fallback",
    "cypher",
}


@dataclass(slots=True)
class RoutePlan:
    route: str
    confidence: float
    is_fluff: bool = False
    is_summary: bool = False
    reasons: tuple[str, ...] = ()


def _normalise(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def classify_query(text: str) -> RoutePlan:
    lowered = _normalise(text)
    if not lowered:
        return RoutePlan("graph_database_agent", 0.0, reasons=("empty",))

    if lowered in FLUFF_PATTERNS or len(lowered.split()) <= 2 and lowered in {
        "hi",
        "hello",
        "thanks",
        "thank you",
    }:
        return RoutePlan("conversation", 1.0, is_fluff=True, reasons=("fluff",))

    if any(pattern in lowered for pattern in SUMMARY_PATTERNS):
        return RoutePlan("conversation", 0.9, is_summary=True, reasons=("summary",))

    reasons: list[str] = []
    scores = {
        "investment_research_agent": 0.0,
        "investor_research_agent": 0.0,
        "graph_database_agent": 0.0,
    }

    for pattern in INVESTMENT_PATTERNS:
        if pattern in lowered:
            scores["investment_research_agent"] += 1.0
            reasons.append(f"investment:{pattern}")

    for pattern in INVESTOR_PATTERNS:
        if pattern in lowered:
            scores["investor_research_agent"] += 1.2
            reasons.append(f"investor:{pattern}")

    for pattern in GRAPH_PATTERNS:
        if pattern in lowered:
            scores["graph_database_agent"] += 1.1
            reasons.append(f"graph:{pattern}")

    if any(pattern in lowered for pattern in STATIC_MCP_TOOL_KEYWORDS):
        scores["investment_research_agent"] += 1.5
        scores["investor_research_agent"] += 1.5

    if scores["investor_research_agent"] > scores["investment_research_agent"]:
        route = "investor_research_agent"
    elif scores["investment_research_agent"] > 0:
        route = "investment_research_agent"
    elif scores["graph_database_agent"] > 0:
        route = "graph_database_agent"
    else:
        route = "graph_database_agent"

    confidence = max(scores.values())
    return RoutePlan(route, confidence, reasons=tuple(dict.fromkeys(reasons)))


def should_save_memory(
    route: str,
    payload: dict[str, Any],
    query_text: str,
) -> tuple[bool, str]:
    lowered = _normalise(query_text)
    if not lowered or lowered in FLUFF_PATTERNS:
        return False, "fluff"
    if any(pattern in lowered for pattern in SUMMARY_PATTERNS):
        return False, "summary-request"
    if any(keyword in lowered for keyword in STATIC_MCP_TOOL_KEYWORDS):
        return False, "static-mcp-tool"

    notes = _normalise(str(payload.get("notes", "")))
    intent = _normalise(str(payload.get("intent", "")))

    if route == "graph_database_agent" and intent in {
        "query",
        "aggregation",
        "traversal",
    }:
        return True, "graph-query-success"
    if "schema mismatch" in notes or "syntax" in notes or "corrected" in notes:
        return True, "self-correction"
    if "alias" in notes or "mapped" in notes:
        return True, "alias-mapping"
    if "a2a" in notes or "orchestration" in notes:
        return True, "multi-agent-track"
    if route in {"investment_research_agent", "investor_research_agent"}:
        return True, "specialist-research"
    return False, "noisy"


def extract_json_block(text: str) -> dict[str, Any] | None:
    matches = re.findall(
        r"```json\s*(.*?)\s*```", text, flags=re.DOTALL | re.IGNORECASE
    )
    if not matches:
        return None
    block = matches[-1].strip()
    try:
        return json.loads(block)
    except json.JSONDecodeError:
        return None


def render_markdown(payload: dict[str, Any], raw_text: str = "") -> str:
    rows = payload.get("rows")
    if isinstance(rows, list) and rows:
        return _render_rows(rows)

    for key in ("investors", "companies", "articles", "results"):
        value = payload.get(key)
        if isinstance(value, list) and value:
            return _render_rows(value)

    summary = payload.get("summary") or payload.get("notes") or raw_text
    if isinstance(summary, str) and summary.strip():
        return summary.strip()

    return raw_text.strip()


def _render_rows(rows: list[dict[str, Any]]) -> str:
    keys = list(rows[0].keys())
    lines = ["| " + " | ".join(keys) + " |"]
    lines.append("| " + " | ".join("---" for _ in keys) + " |")
    for row in rows:
        cells = [_stringify(row.get(key, "")) for key in keys]
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def _stringify(value: Any) -> str:
    if isinstance(value, list):
        return ", ".join(_stringify(item) for item in value)
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False)
    if value is None:
        return ""
    return str(value)
