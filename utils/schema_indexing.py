"""Schema indexing utilities for the Neo4j GraphRAG pipeline.

This module provides:
1) Unified global full-text index initialisation.
2) Relationship-structure semantic vector indexing.

Design goals:
- Global driver singleton with least-privilege credential preference.
- Session choke points via `with driver.session(database=...) as session:`.
- Clean stderr telemetry with no stack-trace leakage.
"""

from __future__ import annotations

import argparse
import atexit
import json
import os
import re
import sys
from datetime import date, datetime, time
from pathlib import Path
from typing import Any, Iterable, cast

from dotenv import load_dotenv

try:
    from neo4j import GraphDatabase  # type: ignore[reportMissingImports]
    from neo4j.exceptions import Neo4jError  # type: ignore[reportMissingImports]
except ImportError as exc:  # pragma: no cover
    raise ImportError(
        "The 'neo4j' package is required. Install it with: pip install neo4j"
    ) from exc

# Load root .env first, then utils/.env as fallback.
_REPO_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_REPO_ROOT / ".env")
load_dotenv(Path(__file__).resolve().parent / ".env")

NEO4J_URI = os.getenv("NEO4J_URI", "neo4j://localhost:7687")
NEO4J_DATABASE = os.getenv("NEO4J_DATABASE", "companies")

# Prefer dedicated least-privilege indexer credentials when provided.
NEO4J_INDEXER_USERNAME = os.getenv(
    "NEO4J_INDEXER_USERNAME", os.getenv("NEO4J_USERNAME", "neo4j")
)
NEO4J_INDEXER_PASSWORD = os.getenv(
    "NEO4J_INDEXER_PASSWORD", os.getenv("NEO4J_PASSWORD", "neo4j")
)

EMBED_MODEL_NAME = "jinaai/jina-embeddings-v5-text-nano"
EMBED_DIM = 512
CATEGORICAL_VALUE_LIMIT = int(os.getenv("SCHEMA_VALUE_PROFILE_LIMIT", "500"))

# Required by user spec: exclude this label from both indexes.
EXCLUDED_LABELS = {"Fewshot"}

# FTS filtering: never include identifiers and verbose free-text fields.
EXCLUDED_FTS_PROPERTIES = {
    "summary",
    "text",
    "cypher",
    "question",
    "embedding",
    "embed_model_name",
    "motto",
}

# Explicit FTS targets requested for the unified index.
REQUIRED_FTS_TARGETS: dict[str, set[str]] = {
    "Article": {"title", "author", "siteName"},
    "Person": {"name"},
    "Organization": {"name"},
    "City": {"name"},
    "Country": {"name"},
    "IndustryCategory": {"name"},
}

_IDENTIFIER_KEYS = {
    "id",
    "_src_id",
    "src_id",
    "_src_rid",
    "src_rid",
    "diffbotid",
    "elementid",
}
_IDENTIFIER_PATTERN = re.compile(r"(^id$|(^|_)id$|(^|_)rid$)", re.IGNORECASE)

_driver = None


def _stderr(message: str) -> None:
    print(message, file=sys.stderr)


def _quote_ident(identifier: str) -> str:
    return "`" + identifier.replace("`", "``") + "`"


def _is_identifier_property(prop: str) -> bool:
    lowered = prop.lower()
    return lowered in _IDENTIFIER_KEYS or bool(_IDENTIFIER_PATTERN.search(lowered))


def _is_temporal_value(value: Any) -> bool:
    return isinstance(value, (date, datetime, time)) or hasattr(value, "isoformat")


def _to_iso(value: Any) -> str | None:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _safe_json(data: Any) -> str:
    return json.dumps(data, ensure_ascii=True, sort_keys=True)


def get_driver():
    """Return a lazily-initialized global Neo4j driver singleton."""
    global _driver
    if _driver is None:
        _driver = GraphDatabase.driver(
            NEO4J_URI,
            auth=(NEO4J_INDEXER_USERNAME, NEO4J_INDEXER_PASSWORD),
        )
        _driver.verify_connectivity()
        _stderr(
            "[schema-indexing] Neo4j driver ready "
            f"(uri={NEO4J_URI}, db={NEO4J_DATABASE}, user={NEO4J_INDEXER_USERNAME})."
        )
    return _driver


def close_driver() -> None:
    """Close the global Neo4j driver if it has been initialised."""
    global _driver
    if _driver is not None:
        try:
            _driver.close()
        finally:
            _driver = None


atexit.register(close_driver)


def _discover_string_properties(session, label: str) -> list[str]:
    query = (
        f"MATCH (n:{_quote_ident(label)}) "
        "UNWIND keys(n) AS property_key "
        "WITH property_key, n[property_key] AS property_value "
        "WHERE property_value IS NOT NULL "
        "WITH property_key, collect(property_value)[0] AS sample "
        "RETURN property_key, sample"
    )
    string_keys: list[str] = []
    for record in session.run(query):
        key = record["property_key"]
        sample = record["sample"]
        if isinstance(sample, str):
            string_keys.append(key)
    return sorted(set(string_keys))


def _should_include_fts_property(label: str, prop: str) -> bool:
    if label in EXCLUDED_LABELS:
        return False
    allowed_props = REQUIRED_FTS_TARGETS.get(label, set())
    if prop not in allowed_props:
        return False
    if _is_identifier_property(prop):
        return False
    # Explicitly allowed targets win over broad exclusions, e.g. Article.title.
    if prop.lower() in EXCLUDED_FTS_PROPERTIES and prop not in allowed_props:
        return False
    return True


def initialize_global_fts_index() -> dict[str, Any]:
    """Create one unified full-text index for discoverable entity text fields.

    Returns:
        Summary metadata describing included labels/properties and status.
    """
    summary: dict[str, Any] = {
        "index_name": "global_entity_search",
        "labels": [],
        "properties": [],
        "created": False,
    }

    try:
        driver = get_driver()
        with driver.session(database=NEO4J_DATABASE) as session:
            labels = [
                r["label"]
                for r in session.run(
                    "CALL db.labels() YIELD label RETURN label ORDER BY label"
                )
            ]

            selected_labels: list[str] = []
            selected_properties: set[str] = set()
            included_targets: set[tuple[str, str]] = set()

            for label in labels:
                if label in EXCLUDED_LABELS:
                    continue
                string_props = _discover_string_properties(session, label)
                includable = [
                    prop
                    for prop in string_props
                    if _should_include_fts_property(label, prop)
                ]
                if includable:
                    selected_labels.append(label)
                    selected_properties.update(includable)
                    included_targets.update((label, prop) for prop in includable)

            expected_targets = {
                (label, prop)
                for label, props in REQUIRED_FTS_TARGETS.items()
                for prop in props
            }
            missing_targets = sorted(expected_targets - included_targets)
            if missing_targets:
                _stderr(
                    "[schema-indexing] Warning: some required FTS targets "
                    "were not discovered in live schema: "
                    f"{_safe_json(missing_targets)}"
                )

            if not selected_labels or not selected_properties:
                _stderr(
                    "[schema-indexing] global_entity_search skipped: "
                    "no eligible labels/properties discovered."
                )
                return summary

            labels_union = "|".join(_quote_ident(l) for l in sorted(selected_labels))
            prop_list = ", ".join(
                f"n.{p}" for p in sorted(selected_properties)
            )

            # Always drop-and-recreate so exclusion rule changes take effect.
            try:
                session.run(
                    "DROP INDEX global_entity_search IF EXISTS"
                ).consume()
                _stderr(
                    "[schema-indexing] Dropped existing global_entity_search "
                    "index (will recreate with current property set)."
                )
            except Neo4jError as drop_exc:
                _stderr(
                    "[schema-indexing] Warning: could not drop existing index: "
                    f"{drop_exc.message if hasattr(drop_exc, 'message') else str(drop_exc)}"
                )

            create_query = (
                "CREATE FULLTEXT INDEX global_entity_search "
                f"FOR (n:{labels_union}) "
                f"ON EACH [{prop_list}]"
            )

            session.run(create_query).consume()

            summary["labels"] = sorted(selected_labels)
            summary["properties"] = sorted(selected_properties)
            summary["created"] = True

            _stderr(
                "[schema-indexing] Initialized global_entity_search "
                f"(labels={len(selected_labels)}, properties={len(selected_properties)})."
            )
            return summary

    except Neo4jError as exc:
        _stderr(
            "[schema-indexing] Failed to initialize global_entity_search: "
            f"{exc.message if hasattr(exc, 'message') else str(exc)}"
        )
        return summary
    except Exception as exc:  # noqa: BLE001
        _stderr(
            "[schema-indexing] Failed to initialize global_entity_search: "
            f"{str(exc)}"
        )
        return summary


def _infer_property_sample_type(session, label: str, prop: str) -> Any:
    query = (
        f"MATCH (n:{_quote_ident(label)}) "
        "WHERE n[$prop] IS NOT NULL "
        "RETURN n[$prop] AS value LIMIT 1"
    )
    record = session.run(query, prop=prop).single()
    return None if record is None else record["value"]


def _profile_temporal(session, label: str, prop: str) -> dict[str, Any]:
    query = (
        f"MATCH (n:{_quote_ident(label)}) "
        "WHERE n[$prop] IS NOT NULL "
        "RETURN min(n[$prop]) AS earliest, max(n[$prop]) AS latest"
    )
    row = session.run(query, prop=prop).single()
    earliest = None if row is None else row["earliest"]
    latest = None if row is None else row["latest"]
    return {
        "earliest": _to_iso(earliest),
        "latest": _to_iso(latest),
    }


def _profile_float(session, label: str, prop: str) -> dict[str, Any]:
    query = (
        f"MATCH (n:{_quote_ident(label)}) "
        "WHERE n[$prop] IS NOT NULL "
        "WITH toFloat(n[$prop]) AS v "
        "RETURN min(v) AS min, max(v) AS max, avg(v) AS mean, "
        "percentileCont(v, 0.5) AS median"
    )
    row = session.run(query, prop=prop).single() or {}
    return {
        "min": row.get("min"),
        "max": row.get("max"),
        "mean": row.get("mean"),
        "median": row.get("median"),
    }


def _embed_texts(
    embedding_model_client: Any, texts: list[str], normalize: bool = True
) -> list[list[float]]:
    """Embed text using a flexible client surface (SentenceTransformer or API)."""
    if not texts:
        return []

    if hasattr(embedding_model_client, "encode"):
        try:
            vectors = embedding_model_client.encode(
                texts,
                batch_size=min(32, max(1, len(texts))),
                task="retrieval",
                prompt_name="document",
                truncate_dim=EMBED_DIM,
                convert_to_numpy=True,
                normalize_embeddings=normalize,
                show_progress_bar=False,
            )
        except TypeError:
            vectors = embedding_model_client.encode(texts)

        out: list[list[float]] = []
        for row in vectors:
            as_list = row.tolist() if hasattr(row, "tolist") else list(row)
            if len(as_list) > EMBED_DIM:
                as_list = as_list[:EMBED_DIM]
            if len(as_list) < EMBED_DIM:
                as_list = as_list + [0.0] * (EMBED_DIM - len(as_list))
            out.append([float(v) for v in as_list])
        return out

    if hasattr(embedding_model_client, "embed"):
        vectors = embedding_model_client.embed(texts)
        out: list[list[float]] = []
        for row in vectors:
            if hasattr(row, "tolist"):
                raw = row.tolist()
            else:
                raw = list(row)
            raw = raw[:EMBED_DIM]
            if len(raw) < EMBED_DIM:
                raw = raw + [0.0] * (EMBED_DIM - len(raw))
            out.append([float(v) for v in raw])
        return out

    if callable(embedding_model_client):
        vectors = cast(Iterable[Any], embedding_model_client(texts))
        out: list[list[float]] = []
        for row in vectors:
            if hasattr(row, "tolist"):
                raw = row.tolist()
            else:
                raw = list(row)
            raw = raw[:EMBED_DIM]
            if len(raw) < EMBED_DIM:
                raw = raw + [0.0] * (EMBED_DIM - len(raw))
            out.append([float(v) for v in raw])
        return out

    raise TypeError(
        "Unsupported embedding_model_client interface. "
        "Expected .encode(), .embed(), or callable."
    )


def _ensure_property_value_vector_index(session, label: str, prop: str) -> None:
    raw = f"schema_property_value_{label}_{prop}_vector".lower()
    safe = re.sub(r"[^a-z0-9_]", "_", raw)
    index_name = safe[:60]

    query = (
        f"CREATE VECTOR INDEX {_quote_ident(index_name)} IF NOT EXISTS "
        "FOR (n:SchemaPropertyValue) ON (n.embedding) "
        "OPTIONS {indexConfig: {"
        "`vector.dimensions`: 512, "
        "`vector.similarity_function`: 'cosine'"
        "}}"
    )
    session.run(query).consume()


def _index_categorical_string_values(
    session,
    embedding_model_client: Any,
    label: str,
    prop: str,
) -> dict[str, Any]:
    """Create per-property value vectors for categorical string fields."""
    values_query = (
        f"MATCH (n:{_quote_ident(label)}) "
        "WHERE n[$prop] IS NOT NULL "
        "WITH DISTINCT toString(n[$prop]) AS value "
        "RETURN value ORDER BY value LIMIT $limit"
    )
    values = [
        r["value"]
        for r in session.run(values_query, prop=prop, limit=CATEGORICAL_VALUE_LIMIT)
    ]

    if not values:
        return {"vector_index_created": False, "embedded_values": 0}

    vectors = _embed_texts(embedding_model_client, values)
    rows = [
        {"value": values[i], "embedding": vectors[i]}
        for i in range(min(len(values), len(vectors)))
    ]

    write_query = (
        "UNWIND $rows AS row "
        "MERGE (v:SchemaPropertyValue {"
        "label_name: $label_name, property_key: $property_key, value: row.value"
        "}) "
        "SET v.embedding = row.embedding, "
        "    v.embed_model_name = $model_name, "
        "    v.embed_dim = $embed_dim, "
        "    v.element_type = 'PROPERTY_VALUE'"
    )

    session.run(
        write_query,
        rows=rows,
        label_name=label,
        property_key=prop,
        model_name=EMBED_MODEL_NAME,
        embed_dim=EMBED_DIM,
    ).consume()

    _ensure_property_value_vector_index(session, label, prop)

    return {
        "vector_index_created": True,
        "embedded_values": len(rows),
        "index_limit": CATEGORICAL_VALUE_LIMIT,
    }


def _profile_property(
    session,
    embedding_model_client: Any,
    label: str,
    prop: str,
) -> dict[str, Any]:
    if _is_identifier_property(prop):
        return {
            "role": "Identifier",
            "exact_match_only": True,
        }

    sample = _infer_property_sample_type(session, label, prop)

    if sample is None:
        return {"role": "Unknown"}

    if _is_temporal_value(sample):
        payload = _profile_temporal(session, label, prop)
        payload["role"] = "Temporal"
        return payload

    if isinstance(sample, float):
        payload = _profile_float(session, label, prop)
        payload["role"] = "Float"
        return payload

    if isinstance(sample, str):
        query = (
            f"MATCH (n:{_quote_ident(label)}) "
            "WHERE n[$prop] IS NOT NULL "
            "RETURN count(n[$prop]) AS total_count, "
            "count(DISTINCT n[$prop]) AS unique_values_count"
        )
        row = session.run(query, prop=prop).single() or {}
        total_count = int(row.get("total_count") or 0)
        unique_count = int(row.get("unique_values_count") or 0)

        payload: dict[str, Any] = {
            "role": "String",
            "total_values_count": total_count,
            "unique_values_count": unique_count,
        }

        if unique_count < total_count:
            payload.update(
                {
                    "role": "Categorical",
                    "requires_value_resolution": True,
                }
            )
            try:
                payload["categorical_vector_index"] = (
                    _index_categorical_string_values(
                        session,
                        embedding_model_client,
                        label,
                        prop,
                    )
                )
            except Exception as exc:  # noqa: BLE001
                _stderr(
                    "[schema-indexing] Categorical value index failed "
                    f"for {label}.{prop}: {str(exc)}"
                )
                payload["categorical_vector_index"] = {
                    "vector_index_created": False,
                    "error": str(exc),
                }

        return payload

    return {"role": type(sample).__name__}


def _collect_label_property_metadata(
    session,
    embedding_model_client: Any,
    label: str,
) -> dict[str, Any]:
    key_query = (
        f"MATCH (n:{_quote_ident(label)}) "
        "UNWIND keys(n) AS property_key "
        "RETURN DISTINCT property_key ORDER BY property_key"
    )
    keys = [r["property_key"] for r in session.run(key_query)]

    out: dict[str, Any] = {}
    for key in keys:
        out[key] = _profile_property(session, embedding_model_client, label, key)
    return out


def _build_relationship_prompt(
    source_label: str,
    relationship_type: str,
    target_label: str,
    source_properties: dict[str, Any],
    target_properties: dict[str, Any],
) -> str:
    """Prompt template mandated by the user request (kept verbatim)."""
    return (
        "You are an expert graph data architect. Analyze the graph relationship structure:\n"
        f"Source Label: (:{source_label}) with properties "
        f"{_safe_json(source_properties)}\n"
        f"Connected via relationship: [:{relationship_type}]\n"
        f"To Target Label: (:{target_label}) with properties "
        f"{_safe_json(target_properties)}\n\n"
        "TASK: Generate a purely semantic, natural language description "
        "detailing what this corporate/media/investment relationship "
        "represents to a human researcher.\n\n"
        "CRITICAL RULE: Do not include or bleed any of the raw technical "
        "property strings, property data types (like Float, String), or "
        "programmatic keys in your final description sentence. Focus "
        "exclusively on human concepts (e.g., map 'Article MENTIONS "
        "Organization' to concepts like news updates, coverage, scandals, "
        "bad press, or press releases talking about a company)."
    )


def _generate_description(generator_llm_client: Any, prompt: str) -> str:
    """Generate text from a flexible LLM client interface."""
    if hasattr(generator_llm_client, "generate_content"):
        response = generator_llm_client.generate_content(prompt)
        text = getattr(response, "text", None)
        if text:
            return str(text).strip()

    if hasattr(generator_llm_client, "invoke"):
        response = generator_llm_client.invoke(prompt)
        if isinstance(response, str):
            return response.strip()
        if hasattr(response, "content"):
            return str(response.content).strip()

    if callable(generator_llm_client):
        response = generator_llm_client(prompt)
        if isinstance(response, str):
            return response.strip()
        return str(response).strip()

    raise TypeError(
        "Unsupported generator_llm_client interface. "
        "Expected .generate_content(), .invoke(), or callable."
    )


def _create_schema_relationship_vector_index(session) -> None:
    query = (
        "CREATE VECTOR INDEX schema_relationship_vector IF NOT EXISTS "
        "FOR (n:SchemaRelationship) ON (n.embedding) "
        "OPTIONS {indexConfig: {"
        "`vector.dimensions`: 512, "
        "`vector.similarity_function`: 'cosine'"
        "}}"
    )
    session.run(query).consume()


def index_relationship_schema_vectors(
    embedding_model_client: Any,
    generator_llm_client: Any,
) -> dict[str, Any]:
    """Index semantic descriptions for unique relationship schema triples.

    The function discovers unique (source_label)-[relationship]->(target_label)
    triples, profiles source/target property distributions, generates semantic
    relationship descriptions via an LLM, embeds those descriptions with Jina,
    and writes schema tracking nodes to Neo4j.
    """
    summary: dict[str, Any] = {
        "triples_discovered": 0,
        "triples_indexed": 0,
        "vector_index_created": False,
        "errors": [],
    }

    try:
        driver = get_driver()
        with driver.session(database=NEO4J_DATABASE) as session:
            triple_query = (
                "MATCH (s)-[r]->(t) "
                "UNWIND labels(s) AS source_label "
                "UNWIND labels(t) AS target_label "
                "WITH source_label, type(r) AS relationship_type, target_label, "
                "count(*) AS rel_count "
                "WHERE NOT source_label IN $excluded_labels "
                "  AND NOT target_label IN $excluded_labels "
                "RETURN source_label, relationship_type, target_label, rel_count "
                "ORDER BY rel_count DESC"
            )
            triples = list(
                session.run(triple_query, excluded_labels=list(EXCLUDED_LABELS))
            )
            summary["triples_discovered"] = len(triples)

            write_query = (
                "MERGE (n:SchemaRelationship {"
                "relationship_type: $relationship_type, "
                "source_label: $source_label, "
                "target_label: $target_label"
                "}) "
                "ON CREATE SET n.created_at = datetime() "
                "SET n.element_type = 'RELATIONSHIP', "
                "    n.text_description = $text_description, "
                "    n.embedding = $embedding, "
                "    n.embed_model_name = $model_name, "
                "    n.embed_dim = $embed_dim, "
                "    n.metadata_json = $metadata_json, "
                "    n.updated_at = datetime()"
            )

            for triple in triples:
                source_label = triple["source_label"]
                relationship_type = triple["relationship_type"]
                target_label = triple["target_label"]
                rel_count = int(triple["rel_count"] or 0)

                try:
                    source_profile = _collect_label_property_metadata(
                        session,
                        embedding_model_client,
                        source_label,
                    )
                    target_profile = _collect_label_property_metadata(
                        session,
                        embedding_model_client,
                        target_label,
                    )

                    prompt = _build_relationship_prompt(
                        source_label=source_label,
                        relationship_type=relationship_type,
                        target_label=target_label,
                        source_properties=source_profile,
                        target_properties=target_profile,
                    )
                    text_description = _generate_description(
                        generator_llm_client,
                        prompt,
                    )

                    vector = _embed_texts(
                        embedding_model_client,
                        [text_description],
                    )[0]

                    metadata_payload = {
                        "element_type": "RELATIONSHIP",
                        "relationship_type": relationship_type,
                        "source_label": source_label,
                        "target_label": target_label,
                        "relationship_count": rel_count,
                        "source_properties_profile": source_profile,
                        "target_properties_profile": target_profile,
                    }

                    session.run(
                        write_query,
                        relationship_type=relationship_type,
                        source_label=source_label,
                        target_label=target_label,
                        text_description=text_description,
                        embedding=vector,
                        model_name=EMBED_MODEL_NAME,
                        embed_dim=EMBED_DIM,
                        metadata_json=_safe_json(metadata_payload),
                    ).consume()
                    summary["triples_indexed"] += 1

                except Exception as triple_exc:  # noqa: BLE001
                    message = (
                        f"{source_label}-[:{relationship_type}]->{target_label}: "
                        f"{str(triple_exc)}"
                    )
                    summary["errors"].append(message)
                    _stderr(
                        "[schema-indexing] Triple indexing failed: "
                        f"{message}"
                    )

            try:
                _create_schema_relationship_vector_index(session)
                summary["vector_index_created"] = True
            except Exception as index_exc:  # noqa: BLE001
                err = f"schema_relationship_vector: {str(index_exc)}"
                summary["errors"].append(err)
                _stderr(
                    "[schema-indexing] Failed creating schema_relationship_vector: "
                    f"{str(index_exc)}"
                )

            _stderr(
                "[schema-indexing] Relationship schema vector indexing completed "
                f"(indexed={summary['triples_indexed']}/"
                f"{summary['triples_discovered']})."
            )
            return summary

    except Neo4jError as exc:
        message = exc.message if hasattr(exc, "message") else str(exc)
        summary["errors"].append(message)
        _stderr(
            "[schema-indexing] Relationship schema vector indexing failed: "
            f"{message}"
        )
        return summary
    except Exception as exc:  # noqa: BLE001
        summary["errors"].append(str(exc))
        _stderr(
            "[schema-indexing] Relationship schema vector indexing failed: "
            f"{str(exc)}"
        )
        return summary


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Initialize Neo4j schema indexes for GraphRAG: "
            "global fulltext and relationship schema vector indexes."
        )
    )
    parser.add_argument(
        "--mode",
        choices=["all", "fts", "relationship"],
        default="all",
        help="Select which indexing flow to run (default: all).",
    )
    parser.add_argument(
        "--skip-vector",
        action="store_true",
        help=(
            "Run relationship schema profiling/description generation only and "
            "skip embedding/index write. Requires code-level clients otherwise."
        ),
    )
    return parser


def _main() -> int:
    args = _build_arg_parser().parse_args()
    exit_code = 0

    if args.mode in {"all", "fts"}:
        _stderr("[schema-indexing] Running unified global fulltext index init...")
        fts_summary = initialize_global_fts_index()
        _stderr(
            "[schema-indexing] FTS summary: "
            f"{_safe_json(fts_summary)}"
        )
        if not fts_summary.get("created"):
            exit_code = 1

    if args.mode in {"all", "relationship"}:
        if args.skip_vector:
            _stderr(
                "[schema-indexing] --skip-vector was provided, but "
                "relationship indexing requires embedding_model_client and "
                "generator_llm_client instances. "
                "Use this module programmatically for relationship mode."
            )
            exit_code = 2
        else:
            _stderr(
                "[schema-indexing] Relationship mode needs runtime clients "
                "(embedding_model_client and generator_llm_client). "
                "Run programmatically, for example:\n"
                "from utils.schema_indexing import index_relationship_schema_vectors\n"
                "index_relationship_schema_vectors(embedding_client, llm_client)"
            )
            exit_code = 2

    close_driver()
    return exit_code


if __name__ == "__main__":
    raise SystemExit(_main())
