"""Standalone LEGO-GraphRAG pipeline service.

Execution pathway:
1. Receive natural language query + target entity.
2. Extract schema-agnostic, degree-pruned graph triples from Neo4j.
3. Gather unique anchor ids and fetch semantic chunks from Milvus.
4. Build a unified grounded context prompt.
5. Ask gpt-4o (temperature=0) for a deterministic answer.
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass

from google import genai
from google.genai import types
from neo4j import GraphDatabase
from pymilvus import MilvusClient
from pymilvus.exceptions import MilvusException

LOGGER = logging.getLogger("isolated-lego-graphrag")

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
class ServiceConfig:
    """Runtime configuration for the standalone service."""

    neo4j_uri: str
    neo4j_username: str
    neo4j_password: str
    neo4j_database: str
    milvus_uri: str
    milvus_token: str
    milvus_collection: str
    milvus_id_field: str
    milvus_text_field: str
    hub_degree_limit: int
    llm_model: str

    @classmethod
    def from_env(cls) -> ServiceConfig:
        """Load settings from environment variables only."""
        neo4j_uri = os.environ.get("NEO4J_URI", "")
        neo4j_username = os.environ.get("NEO4J_USERNAME", "")
        neo4j_password = os.environ.get("NEO4J_PASSWORD", "")
        neo4j_database = os.environ.get("NEO4J_DATABASE", "neo4j")

        milvus_uri = os.environ.get("MILVUS_URI", "")
        milvus_token = os.environ.get("MILVUS_TOKEN", "")

        missing = []
        if not neo4j_uri:
            missing.append("NEO4J_URI")
        if not neo4j_username:
            missing.append("NEO4J_USERNAME")
        if not neo4j_password:
            missing.append("NEO4J_PASSWORD")
        if not milvus_uri:
            missing.append("MILVUS_URI")
        if not milvus_token:
            missing.append("MILVUS_TOKEN")

        if missing:
            raise ValueError("Missing required environment variables: " + ", ".join(missing))

        return cls(
            neo4j_uri=neo4j_uri,
            neo4j_username=neo4j_username,
            neo4j_password=neo4j_password,
            neo4j_database=neo4j_database,
            milvus_uri=milvus_uri,
            milvus_token=milvus_token,
            milvus_collection=os.environ.get("MILVUS_COLLECTION", "semantic_chunks"),
            milvus_id_field=os.environ.get("MILVUS_ID_FIELD", "id"),
            milvus_text_field=os.environ.get("MILVUS_TEXT_FIELD", "text"),
            hub_degree_limit=int(os.environ.get("GRAPH_HUB_DEGREE_LIMIT", "300")),
            llm_model=os.environ.get("LLM_MODEL", "gemini-2.0-flash"),
        )


class LegoGraphRAGService:
    """Pure Python agent service for dual-retrieval graph + vector grounding."""

    def __init__(self, config: ServiceConfig) -> None:
        self.config = config
        self._neo4j_driver = GraphDatabase.driver(
            config.neo4j_uri,
            auth=(config.neo4j_username, config.neo4j_password),
        )
        self._milvus = self._init_milvus_client()
        self._gemini = genai.Client()

    def close(self) -> None:
        """Close underlying client resources."""
        self._neo4j_driver.close()

    def run(self, query: str, target_entity: str) -> str:
        """Execute the single pathway end-to-end and return a localized answer."""
        triples = self._fetch_pruned_subgraph_triples(target_entity)
        anchor_ids = self._collect_anchor_ids(triples)
        chunks = self._fetch_semantic_chunks(anchor_ids)
        grounded_prompt = self._build_grounded_prompt(query, target_entity, triples, chunks)
        return self._synthesize_answer(query, grounded_prompt)

    def _init_milvus_client(self) -> MilvusClient:
        """Initialize MilvusClient with hardened error handling."""
        try:
            return MilvusClient(uri=self.config.milvus_uri, token=self.config.milvus_token)
        except MilvusException as exc:
            LOGGER.exception("Milvus client initialization failed: %s", exc)
            raise RuntimeError(
                "Failed to initialize Milvus client. Check MILVUS_URI and MILVUS_TOKEN."
            ) from exc
        except Exception as exc:  # noqa: BLE001
            LOGGER.exception("Unexpected Milvus initialization failure: %s", exc)
            raise RuntimeError("Unexpected Milvus connectivity/credential issue.") from exc

    def _fetch_pruned_subgraph_triples(self, target_entity: str) -> list[dict[str, str]]:
        """Fetch schema-agnostic neighborhood triples with in-query hub pruning."""
        pattern = self._entity_pattern(target_entity)
        records: list[dict[str, str]] = []

        with self._neo4j_driver.session(database=self.config.neo4j_database) as session:
            result = session.run(
                SCHEMA_AGNOSTIC_QUERY,
                pattern=pattern,
                degree_limit=self.config.hub_degree_limit,
            )
            for row in result:
                records.append(
                    {
                        "source_label": str(row["source_label"]),
                        "source_name": str(row["source_name"]),
                        "relationship_type": str(row["relationship_type"]),
                        "target_label": str(row["target_label"]),
                        "target_name": str(row["target_name"]),
                        "anchor_id": str(row["anchor_id"]),
                    }
                )

        return records

    def _fetch_semantic_chunks(self, anchor_ids: list[str]) -> list[str]:
        """Fetch descriptive text chunks from Milvus using scalar expression filter."""
        if not anchor_ids:
            return []

        expr = self._build_id_filter_expression(anchor_ids)
        try:
            rows = self._milvus.query(
                collection_name=self.config.milvus_collection,
                filter=expr,
                output_fields=[self.config.milvus_id_field, self.config.milvus_text_field],
                limit=max(len(anchor_ids), 1),
            )
        except MilvusException as exc:
            LOGGER.warning("Milvus query transient failure: %s", exc)
            return []
        except Exception as exc:  # noqa: BLE001
            LOGGER.warning("Milvus query unexpected failure: %s", exc)
            return []

        chunks: list[str] = []
        for row in rows:
            text_value = row.get(self.config.milvus_text_field)
            if text_value is not None:
                chunks.append(str(text_value))
        return chunks

    def _synthesize_answer(self, query: str, grounded_prompt: str) -> str:
        """Call Gemini at temperature 0 for deterministic synthesis."""
        response = self._gemini.models.generate_content(
            model=self.config.llm_model,
            contents=f"Question: {query}\n\n{grounded_prompt}",
            config=types.GenerateContentConfig(
                temperature=0,
                system_instruction=(
                    "You are a precise backend graph analyst. Use ONLY the provided "
                    "SUBGRAPH MAP and SEMANTIC CONTEXT. If evidence is missing, "
                    "state that explicitly. Do not hallucinate unbacked claims."
                ),
            ),
        )
        return (response.text or "").strip()

    def _build_grounded_prompt(
        self,
        query: str,
        target_entity: str,
        triples: list[dict[str, str]],
        chunks: list[str],
    ) -> str:
        """Create the strict dual-context payload with dedicated Markdown blocks."""
        triple_lines = self._format_triple_lines(triples)
        chunk_lines = chunks if chunks else ["No semantic chunks matched Milvus anchor ids."]

        return (
            f"Target Entity: {target_entity}\n"
            f"Query: {query}\n\n"
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
    def _collect_anchor_ids(triples: list[dict[str, str]]) -> list[str]:
        seen: set[str] = set()
        ordered_ids: list[str] = []
        for triple in triples:
            anchor = triple["anchor_id"]
            if anchor and anchor not in seen:
                seen.add(anchor)
                ordered_ids.append(anchor)
        return ordered_ids

    @staticmethod
    def _format_triple_lines(triples: list[dict[str, str]]) -> list[str]:
        if not triples:
            return ["No qualifying paths found after degree pruning."]

        lines: list[str] = []
        for triple in triples:
            lines.append(
                f"({triple['source_name']}:{triple['source_label']}) "
                f"-[:{triple['relationship_type']}]-> "
                f"({triple['target_name']}:{triple['target_label']})"
            )
        return lines

    def _build_id_filter_expression(self, anchor_ids: list[str]) -> str:
        escaped_ids = [self._quote_id(item) for item in anchor_ids]
        return f"{self.config.milvus_id_field} in [{', '.join(escaped_ids)}]"

    @staticmethod
    def _quote_id(value: str) -> str:
        return "'" + value.replace("\\", "\\\\").replace("'", "\\'") + "'"

    @staticmethod
    def _entity_pattern(target_entity: str) -> str:
        escaped = re.escape(target_entity.strip())
        return rf"(?i).*{escaped}.*"
