"""Autonomous Knowledge Agent with dual-retrieval GraphRAG execution."""

from __future__ import annotations

import logging
import os
import re
import time
from dataclasses import dataclass, field
from typing import Any

from google import genai
from google.genai import types
from neo4j import GraphDatabase
from pymilvus import MilvusClient
from pymilvus.exceptions import MilvusException

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
ORDER BY source_name, relationship_type, target_name
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
    milvus_uri: str
    milvus_token: str
    milvus_collection: str
    milvus_id_field: str
    milvus_text_field: str
    degree_limit: int
    llm_model: str

    @classmethod
    def from_env(cls) -> AgentConfig:
        required = {
            "NEO4J_URI": os.environ.get("NEO4J_URI", ""),
            "NEO4J_USERNAME": os.environ.get("NEO4J_USERNAME", ""),
            "NEO4J_PASSWORD": os.environ.get("NEO4J_PASSWORD", ""),
            "MILVUS_URI": os.environ.get("MILVUS_URI", ""),
            "MILVUS_TOKEN": os.environ.get("MILVUS_TOKEN", ""),
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
            milvus_uri=required["MILVUS_URI"],
            milvus_token=required["MILVUS_TOKEN"],
            milvus_collection=os.environ.get("MILVUS_COLLECTION", "semantic_chunks"),
            milvus_id_field=os.environ.get("MILVUS_ID_FIELD", "id"),
            milvus_text_field=os.environ.get("MILVUS_TEXT_FIELD", "text"),
            degree_limit=int(os.environ.get("GRAPH_HUB_DEGREE_LIMIT", "300")),
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
        self._milvus = self._init_milvus_client()
        self._llm = genai.Client()

    def close(self) -> None:
        """Release driver resources."""
        self._neo4j_driver.close()

    def run(self, user_query: str, target_entity: str) -> AgentResponse:
        """Execute the autonomous multi-step tool loop and return final payload."""
        state = ExecutionState(
            run_id=str(int(time.time() * 1000)),
            started_at=time.time(),
        )

        triples: list[dict[str, str]] = []
        chunks: list[str] = []

        for phase in (
            "graph_slice",
            "anchor_collect",
            "semantic_retrieve",
            "context_synthesis",
            "reasoning",
        ):
            state.steps_taken.append(phase)
            try:
                if phase == "graph_slice":
                    triples = self._graph_slice(target_entity)
                    state.triples_count = len(triples)
                    state.tool_status[phase] = "ok"

                elif phase == "anchor_collect":
                    anchor_ids = self._collect_anchor_ids(triples)
                    state.anchor_count = len(anchor_ids)
                    state.tool_status[phase] = "ok"

                elif phase == "semantic_retrieve":
                    chunks = self._semantic_retrieve(anchor_ids)
                    state.semantic_chunk_count = len(chunks)
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
        }
        return AgentResponse(answer=answer, metrics=metrics)

    def _init_milvus_client(self) -> MilvusClient:
        """Initialize Milvus tool with autonomous fail-safe handling."""
        try:
            return MilvusClient(
                uri=self.config.milvus_uri,
                token=self.config.milvus_token,
            )
        except MilvusException as exc:
            LOGGER.exception("Milvus auth/network initialization failed: %s", exc)
            raise RuntimeError(
                "Milvus initialization failed. Verify MILVUS_URI and MILVUS_TOKEN."
            ) from exc
        except Exception as exc:  # noqa: BLE001
            LOGGER.exception("Unexpected Milvus initialization error: %s", exc)
            raise RuntimeError("Unexpected Milvus initialization failure.") from exc

    def _graph_slice(self, target_entity: str) -> list[dict[str, str]]:
        """Run schema-agnostic query with degree-based path pruning."""
        pattern = self._build_entity_pattern(target_entity)
        rows: list[dict[str, str]] = []

        with self._neo4j_driver.session(database=self.config.neo4j_database) as session:
            result = session.run(
                SCHEMA_AGNOSTIC_QUERY,
                pattern=pattern,
                degree_limit=self.config.degree_limit,
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
        return rows

    def _semantic_retrieve(self, anchor_ids: list[str]) -> list[str]:
        """Retrieve semantic chunks using scalar expression id containment."""
        if not anchor_ids:
            return []

        expr = self._build_id_expression(anchor_ids)
        try:
            result = self._milvus.query(
                collection_name=self.config.milvus_collection,
                filter=expr,
                output_fields=[
                    self.config.milvus_id_field,
                    self.config.milvus_text_field,
                ],
                limit=max(len(anchor_ids), 1),
            )
        except MilvusException as exc:
            LOGGER.warning("Milvus query network/cluster issue: %s", exc)
            return []
        except Exception as exc:  # noqa: BLE001
            LOGGER.warning("Milvus query unexpected issue: %s", exc)
            return []

        chunks: list[str] = []
        for row in result:
            if self.config.milvus_text_field in row and row[self.config.milvus_text_field]:
                chunks.append(str(row[self.config.milvus_text_field]))
        return chunks

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
            "No Milvus semantic chunks matched the anchor_id set."
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

    def _build_id_expression(self, anchor_ids: list[str]) -> str:
        quoted = [self._quote_literal(anchor_id) for anchor_id in anchor_ids]
        return f"{self.config.milvus_id_field} in [{', '.join(quoted)}]"

    @staticmethod
    def _quote_literal(value: str) -> str:
        return "'" + value.replace("\\", "\\\\").replace("'", "\\'") + "'"

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
