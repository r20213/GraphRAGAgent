"""Autonomous Knowledge Agent with dual-retrieval GraphRAG execution."""

from __future__ import annotations

import json
import logging
import os
import re
import time
from dataclasses import dataclass, field
from typing import Any

from google import genai
from google.genai import types
from neo4j import GraphDatabase

LOGGER = logging.getLogger("knowledge-agent")

SCHEMA_AGNOSTIC_QUERY = """
MATCH (src)
WHERE src.name =~ $pattern
MATCH path = (src)-[*1..2]-(tgt)
WITH path, tgt, count{(tgt)--()} AS tgt_degree
WHERE tgt_degree <= $degree_limit
UNWIND relationships(path) AS rel
WITH startNode(rel) AS source_node,
     endNode(rel) AS target_node,
     type(rel) AS relationship_type,
     tgt
RETURN DISTINCT
  coalesce(head(labels(source_node)), 'Unknown') AS source_label,
  coalesce(source_node.name, '<unnamed>') AS source_name,
  relationship_type,
  coalesce(head(labels(target_node)), 'Unknown') AS target_label,
  coalesce(target_node.name, '<unnamed>') AS target_name,
  coalesce(toString(tgt.anchor_id), toString(tgt.id), toString(elementId(tgt))) AS anchor_id
ORDER BY relationship_type, source_name, target_name
LIMIT $candidate_limit
"""

CHUNK_RETRIEVAL_QUERY = """
MATCH (anchor)
WHERE anchor.id IN $anchor_ids OR elementId(anchor) IN $anchor_ids
CALL {
  WITH anchor
  MATCH (anchor)<-[:MENTIONS]-(:Article)-[:HAS_CHUNK]->(c:Chunk)
  RETURN c
  UNION
  WITH anchor
  MATCH (anchor)-[:HAS_CHUNK]->(c:Chunk)
  RETURN c
}
WITH DISTINCT c
WHERE c.text IS NOT NULL
RETURN c.text AS text
LIMIT $chunk_limit
"""


@dataclass(slots=True)
class ExecutionState:
    """Mutable state matrix maintained across one agent run."""

    run_id: str
    started_at: float
    steps_taken: list[str] = field(default_factory=list)
    tool_status: dict[str, str] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    triples_count: int = 0
    anchor_count: int = 0
    semantic_chunk_count: int = 0
    completed_at: float | None = None

    @property
    def duration_ms(self) -> int:
        end = self.completed_at if self.completed_at is not None else time.time()
        return int((end - self.started_at) * 1000)


@dataclass(slots=True)
class AgentResponse:
    """Final packaged response containing execution metadata and answer."""

    answer: str
    metrics: dict[str, Any]


@dataclass(slots=True)
class AgentConfig:
    """Environment-backed configuration for the autonomous agent."""

    neo4j_uri: str
    neo4j_username: str
    neo4j_password: str
    neo4j_database: str
    degree_limit: int
    result_limit: int
    candidate_limit: int
    per_rel_limit: int
    chunk_limit: int
    require_semantic_context: bool
    llm_model: str

    @classmethod
    def from_env(cls) -> AgentConfig:
        required = {
            "NEO4J_URI": os.environ.get("NEO4J_URI", ""),
            "NEO4J_USERNAME": os.environ.get("NEO4J_USERNAME", ""),
            "NEO4J_PASSWORD": os.environ.get("NEO4J_PASSWORD", ""),
            "GOOGLE_API_KEY": os.environ.get("GOOGLE_API_KEY", ""),
        }
        missing = [name for name, value in required.items() if not value]
        if missing:
            raise ValueError("Missing required environment variables: " + ", ".join(missing))

        return cls(
            neo4j_uri=required["NEO4J_URI"],
            neo4j_username=required["NEO4J_USERNAME"],
            neo4j_password=required["NEO4J_PASSWORD"],
            neo4j_database=os.environ.get("NEO4J_DATABASE", "neo4j"),
            degree_limit=int(os.environ.get("GRAPH_HUB_DEGREE_LIMIT", "300")),
            result_limit=int(os.environ.get("GRAPH_RESULT_LIMIT", "200")),
            candidate_limit=int(
                os.environ.get("GRAPH_CANDIDATE_LIMIT", "2000")
            ),
            per_rel_limit=int(os.environ.get("GRAPH_PER_REL_LIMIT", "25")),
            chunk_limit=int(os.environ.get("CHUNK_RETRIEVAL_LIMIT", "50")),
            require_semantic_context=(
                os.environ.get("REQUIRE_SEMANTIC_CONTEXT", "true").strip().lower()
                in {"1", "true", "yes", "on"}
            ),
            llm_model=os.environ.get("LLM_MODEL", "gemini-2.0-flash"),
        )


class KnowledgeAgent:
    """Active autonomous agent that coordinates graph and vector tools."""

    def __init__(self, config: AgentConfig | None = None) -> None:
        self.config = config or AgentConfig.from_env()
        self._neo4j_driver = GraphDatabase.driver(
            self.config.neo4j_uri,
            auth=(self.config.neo4j_username, self.config.neo4j_password),
        )
        self._llm = genai.Client()

    def close(self) -> None:
        """Release driver resources."""
        self._neo4j_driver.close()

    def run(self, user_query: str) -> AgentResponse:
        """Execute the autonomous multi-step tool loop and return final payload."""
        state = ExecutionState(
            run_id=str(int(time.time() * 1000)),
            started_at=time.time(),
        )

        triples: list[dict[str, str]] = []
        chunks: list[str] = []
        anchor_ids: list[str] = []
        entities: list[str] = []
        target_entity = ""
        answer = "No results found."

        for phase in (
            "entity_extract",
            "graph_slice",
            "anchor_collect",
            "semantic_retrieve",
            "context_synthesis",
            "reasoning",
        ):
            state.steps_taken.append(phase)
            try:
                if phase == "entity_extract":
                    entities = self._extract_entities(user_query)
                    if not entities:
                        state.tool_status[phase] = "no-entity"
                        state.completed_at = time.time()
                        metrics = {
                            "run_id": state.run_id,
                            "steps_taken": state.steps_taken,
                            "tool_status": state.tool_status,
                            "errors": state.errors,
                            "triples_count": state.triples_count,
                            "anchor_count": state.anchor_count,
                            "semantic_chunk_count": state.semantic_chunk_count,
                            "duration_ms": state.duration_ms,
                            "extracted_entities": entities,
                            "selected_entity": None,
                        }
                        return AgentResponse(answer="No results found.", metrics=metrics)
                    target_entity = entities[0]
                    state.tool_status[phase] = "ok"

                elif phase == "graph_slice":
                    triples = self._graph_slice(target_entity)
                    state.triples_count = len(triples)
                    state.tool_status[phase] = "ok"

                elif phase == "anchor_collect":
                    anchor_ids = self._collect_anchor_ids(triples)
                    state.anchor_count = len(anchor_ids)
                    state.tool_status[phase] = "ok"

                elif phase == "semantic_retrieve":
                    chunks, semantic_error = self._semantic_retrieve(anchor_ids)
                    state.semantic_chunk_count = len(chunks)
                    if semantic_error:
                        state.tool_status[phase] = semantic_error
                        state.errors.append(f"{phase}: {semantic_error}")
                        if self.config.require_semantic_context:
                            state.completed_at = time.time()
                            metrics = {
                                "run_id": state.run_id,
                                "steps_taken": state.steps_taken,
                                "tool_status": state.tool_status,
                                "errors": state.errors,
                                "triples_count": state.triples_count,
                                "anchor_count": state.anchor_count,
                                "semantic_chunk_count": state.semantic_chunk_count,
                                "duration_ms": state.duration_ms,
                                "extracted_entities": entities,
                                "selected_entity": target_entity or None,
                            }
                            return AgentResponse(
                                answer="No results found.",
                                metrics=metrics,
                            )
                    else:
                        state.tool_status[phase] = "ok"

                elif phase == "context_synthesis":
                    grounded_context = self._build_grounded_context(
                        user_query=user_query,
                        target_entity=target_entity,
                        triples=triples,
                        chunks=chunks,
                    )
                    state.tool_status[phase] = "ok"

                elif phase == "reasoning":
                    answer = self._reason(user_query, grounded_context)
                    state.tool_status[phase] = "ok"

            except Exception as exc:  # noqa: BLE001
                state.tool_status[phase] = "error"
                state.errors.append(f"{phase}: {exc}")
                LOGGER.exception("Agent phase failed (%s): %s", phase, exc)

                if phase == "reasoning":
                    answer = self._fallback_answer(triples, chunks)
                else:
                    continue

        state.completed_at = time.time()
        metrics = {
            "run_id": state.run_id,
            "steps_taken": state.steps_taken,
            "tool_status": state.tool_status,
            "errors": state.errors,
            "triples_count": state.triples_count,
            "anchor_count": state.anchor_count,
            "semantic_chunk_count": state.semantic_chunk_count,
            "duration_ms": state.duration_ms,
            "extracted_entities": entities,
            "selected_entity": target_entity or None,
        }
        return AgentResponse(answer=answer, metrics=metrics)

    def _graph_slice(self, target_entity: str) -> list[dict[str, str]]:
        """Run schema-agnostic query with degree-based path pruning."""
        pattern = self._build_entity_pattern(target_entity)
        rows: list[dict[str, str]] = []

        with self._neo4j_driver.session(database=self.config.neo4j_database) as session:
            result = session.run(
                SCHEMA_AGNOSTIC_QUERY,
                pattern=pattern,
                degree_limit=self.config.degree_limit,
                candidate_limit=self.config.candidate_limit,
            )
            for record in result:
                row = {
                    "source_label": str(record["source_label"]),
                    "source_name": str(record["source_name"]),
                    "relationship_type": str(record["relationship_type"]),
                    "target_label": str(record["target_label"]),
                    "target_name": str(record["target_name"]),
                    "anchor_id": str(record["anchor_id"]),
                }
                row["triple"] = self._format_triple(row)
                rows.append(row)
        return self._diversify_triples(rows)

    def _diversify_triples(
        self, rows: list[dict[str, str]]
    ) -> list[dict[str, str]]:
        """Select a breadth-first slice covering many relationship types.

        Groups candidate triples by relationship type and fills the final
        budget by cycling across groups (round-robin), capping how many
        triples any single relationship type may contribute. This favors
        coverage of distinct relationships over alphabetical truncation.
        """
        if len(rows) <= self.config.result_limit:
            return rows

        buckets: dict[str, list[dict[str, str]]] = {}
        order: list[str] = []
        for row in rows:
            rel = row["relationship_type"]
            if rel not in buckets:
                buckets[rel] = []
                order.append(rel)
            buckets[rel].append(row)

        selected: list[dict[str, str]] = []
        cursors = {rel: 0 for rel in order}
        per_rel_limit = max(1, self.config.per_rel_limit)
        while len(selected) < self.config.result_limit:
            progressed = False
            for rel in order:
                cursor = cursors[rel]
                if cursor >= len(buckets[rel]) or cursor >= per_rel_limit:
                    continue
                selected.append(buckets[rel][cursor])
                cursors[rel] = cursor + 1
                progressed = True
                if len(selected) >= self.config.result_limit:
                    break
            if not progressed:
                break
        return selected

    def _semantic_retrieve(self, anchor_ids: list[str]) -> tuple[list[str], str | None]:
        """Retrieve semantic chunks directly from Neo4j via the graph.

        Chunks are stored in Neo4j as `(:Chunk)` nodes connected through
        `(:Article)-[:MENTIONS]->(anchor)` and `(:Article)-[:HAS_CHUNK]->(:Chunk)`
        (and any direct `(anchor)-[:HAS_CHUNK]->(:Chunk)`). This replaces the
        former external vector store: anchors discovered during graph slicing
        are used to gather their grounded chunk text.
        """
        if not anchor_ids:
            return [], None

        try:
            with self._neo4j_driver.session(
                database=self.config.neo4j_database
            ) as session:
                result = session.run(
                    CHUNK_RETRIEVAL_QUERY,
                    anchor_ids=anchor_ids,
                    chunk_limit=self.config.chunk_limit,
                )
                chunks = [
                    str(record["text"])
                    for record in result
                    if record["text"]
                ]
        except Exception as exc:  # noqa: BLE001
            LOGGER.warning("Neo4j chunk retrieval failed: %s", exc)
            return [], "chunk-retrieval-failed"

        return chunks, None

    def _reason(self, user_query: str, grounded_context: str) -> str:
        """Use Gemini as deterministic final reasoning engine."""
        response = self._llm.models.generate_content(
            model=self.config.llm_model,
            contents=f"Question: {user_query}\n\n{grounded_context}",
            config=types.GenerateContentConfig(
                temperature=0,
                system_instruction=(
                    "You are an autonomous Knowledge Agent. "
                    "Use only the provided SUBGRAPH MAP and SEMANTIC CONTEXT. "
                    "Trace paths explicitly and do not hallucinate unsupported claims."
                ),
            ),
        )
        return (response.text or "").strip()

    def _build_grounded_context(
        self,
        user_query: str,
        target_entity: str,
        triples: list[dict[str, str]],
        chunks: list[str],
    ) -> str:
        """Merge deterministic graph map and semantic context into Markdown blocks."""
        triple_lines = [row["triple"] for row in triples] or [
            "No qualifying paths remained after degree pruning."
        ]
        chunk_lines = chunks or [
            "No graph-linked chunks matched the anchor set."
        ]

        return (
            f"Target Entity: {target_entity}\n"
            f"User Query: {user_query}\n\n"
            "## SUBGRAPH MAP\n"
            "```text\n"
            + "\n".join(triple_lines)
            + "\n```\n\n"
            "## SEMANTIC CONTEXT\n"
            "```text\n"
            + "\n\n".join(chunk_lines)
            + "\n```"
        )

    @staticmethod
    def _collect_anchor_ids(rows: list[dict[str, str]]) -> list[str]:
        seen: set[str] = set()
        anchor_ids: list[str] = []
        for row in rows:
            anchor_id = row.get("anchor_id", "")
            if anchor_id and anchor_id not in seen:
                seen.add(anchor_id)
                anchor_ids.append(anchor_id)
        return anchor_ids

    @staticmethod
    def _build_entity_pattern(target_entity: str) -> str:
        escaped = re.escape(target_entity.strip())
        return rf"(?i).*{escaped}.*"

    def _extract_entities(self, user_query: str) -> list[str]:
        """Extract named entities from the query (LLM first, regex fallback)."""
        entities = self._extract_entities_llm(user_query)
        if entities:
            return entities
        return self._extract_entities_regex(user_query)

    def _extract_entities_llm(self, user_query: str) -> list[str]:
        """Use Gemini to pull concrete named entities from the query."""
        try:
            response = self._llm.models.generate_content(
                model=self.config.llm_model,
                contents=(
                    "Extract the concrete named entities (companies, people, "
                    "products, organizations, places) from the question below. "
                    "Return ONLY a JSON array of strings, most important first. "
                    "Ignore generic words like 'competitors', 'main', 'who'. "
                    "If there are none, return [].\n\n"
                    f"Question: {user_query}"
                ),
                config=types.GenerateContentConfig(
                    temperature=0,
                    response_mime_type="application/json",
                ),
            )
        except Exception as exc:  # noqa: BLE001
            LOGGER.warning("LLM entity extraction failed: %s", exc)
            return []

        raw = (response.text or "").strip()
        if not raw:
            return []
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            LOGGER.warning("LLM entity extraction returned non-JSON: %s", raw)
            return []

        entities: list[str] = []
        seen: set[str] = set()
        for item in parsed if isinstance(parsed, list) else []:
            token = str(item).strip()
            if not token:
                continue
            key = token.casefold()
            if key in seen:
                continue
            seen.add(key)
            entities.append(token)
        return entities

    @staticmethod
    def _extract_entities_regex(user_query: str) -> list[str]:
        candidates: list[str] = []

        # Highest-confidence path: quoted entities.
        candidates.extend(re.findall(r"['\"]([^'\"]{2,80})['\"]", user_query))

        # Capture entities after intent prepositions (e.g., "competitors of YouTube").
        candidates.extend(
            re.findall(
                r"\b(?:of|for|about|regarding|on|at|in)\s+"
                r"([A-Za-z][\w&.-]*(?:\s+[A-Za-z0-9][\w&.-]*){0,4})",
                user_query,
            )
        )

        # General title-case and acronym entities.
        candidates.extend(
            re.findall(
                r"\b([A-Z][\w&.-]*(?:\s+[A-Z0-9][\w&.-]*){0,4}|[A-Z]{2,})\b",
                user_query,
            )
        )

        stopwords = {
            "who",
            "what",
            "when",
            "where",
            "why",
            "how",
            "which",
            "whose",
            "main",
            "top",
            "give",
            "show",
            "list",
            "find",
            "tell",
            "competitor",
            "competitors",
        }

        entities: list[str] = []
        seen: set[str] = set()
        for item in candidates:
            token = item.strip(" ?!.,;:\"'()[]{}")
            if not token:
                continue
            if token.casefold() in stopwords:
                continue
            key = token.casefold()
            if key in seen:
                continue
            seen.add(key)
            entities.append(token)
        return entities

    @staticmethod
    def _format_triple(row: dict[str, str]) -> str:
        return (
            f"({row['source_name']}:{row['source_label']}) "
            f"-[:{row['relationship_type']}]-> "
            f"({row['target_name']}:{row['target_label']})"
        )

    @staticmethod
    def _fallback_answer(triples: list[dict[str, str]], chunks: list[str]) -> str:
        if triples:
            top = "\n".join(row["triple"] for row in triples[:5])
            return (
                "Reasoning model call failed. Returning grounded partial graph evidence:\n"
                + top
            )
        if chunks:
            return (
                "Reasoning model call failed. Returning semantic context excerpts:\n"
                + "\n\n".join(chunks[:3])
            )
        return "No grounded evidence could be retrieved for this query."
