"""Neo4j schema extraction utilities.

Connects to a Neo4j database, introspects its schema (node labels,
relationship types, properties with data types and example values, and the
exact source/target labels each relationship connects) and renders it as
clean Markdown suitable for injecting into an LLM prompt.
"""

from __future__ import annotations

import os
from collections import defaultdict
from pathlib import Path
from typing import Any

try:
    from neo4j import GraphDatabase
    from neo4j.exceptions import Neo4jError, ServiceUnavailable, AuthError
except ImportError as exc:  # pragma: no cover
    raise ImportError(
        "The 'neo4j' package is required. Install it with: pip install neo4j"
    ) from exc

try:
    from dotenv import load_dotenv
except ImportError as exc:  # pragma: no cover
    raise ImportError(
        "The 'python-dotenv' package is required. "
        "Install it with: pip install python-dotenv"
    ) from exc


# Load environment variables from the .env file next to this module.
load_dotenv(Path(__file__).resolve().parent / ".env")

# --- Default connection details (loaded from utils/.env) -------------------
DEFAULT_URI = os.getenv("NEO4J_URI", "neo4j+s://demo.neo4jlabs.com")
DEFAULT_USER = os.getenv("NEO4J_USERNAME", "companies")
DEFAULT_PASSWORD = os.getenv("NEO4J_PASSWORD", "companies")
DEFAULT_DATABASE = os.getenv("NEO4J_DATABASE", "companies")

# How many example values to collect per property.
DEFAULT_EXAMPLE_COUNT = 3


def _format_value(value: Any) -> str:
    """Return a compact, single-line string representation of a value."""
    if value is None:
        return "null"
    if isinstance(value, str):
        text = value.replace("\n", " ").strip()
        if len(text) > 60:
            text = text[:57] + "..."
        return f'"{text}"'
    if isinstance(value, (list, tuple)):
        preview = ", ".join(_format_value(v) for v in list(value)[:3])
        return f"[{preview}]"
    return str(value)


def _python_type_name(value: Any) -> str:
    """Map a Python/Neo4j value to a readable type name."""
    if value is None:
        return "null"
    type_map = {
        bool: "Boolean",
        int: "Integer",
        float: "Float",
        str: "String",
        list: "List",
        dict: "Map",
    }
    for py_type, name in type_map.items():
        if isinstance(value, py_type):
            return name
    # Temporal / spatial types expose their class name directly.
    return type(value).__name__


def _fetch_node_schema(
    session, example_count: int
) -> dict[str, dict[str, dict[str, Any]]]:
    """Collect properties, types and example values for every node label.

    Returns a mapping:
        { label: { property: {"types": set[str], "examples": list[Any]} } }
    """
    # Discover all labels present in the database.
    labels = [
        record["label"]
        for record in session.run("CALL db.labels() YIELD label RETURN label")
    ]

    node_schema: dict[str, dict[str, dict[str, Any]]] = {}

    for label in sorted(labels):
        properties: dict[str, dict[str, Any]] = defaultdict(
            lambda: {"types": set(), "examples": []}
        )

        # Sample a bounded number of nodes per label to infer property shape.
        query = (
            f"MATCH (n:`{label}`) "
            "WITH n LIMIT 500 "
            "RETURN properties(n) AS props"
        )
        for record in session.run(query):
            props = record["props"] or {}
            for key, value in props.items():
                entry = properties[key]
                entry["types"].add(_python_type_name(value))
                if value is not None and len(entry["examples"]) < example_count:
                    if value not in entry["examples"]:
                        entry["examples"].append(value)

        node_schema[label] = dict(properties)

    return node_schema


def _fetch_relationship_schema(
    session, example_count: int
) -> dict[str, dict[str, Any]]:
    """Collect properties, types, example values and connectivity per rel type.

    Returns a mapping:
        { rel_type: {
            "properties": { prop: {"types": set, "examples": list} },
            "connections": set[(source_label, target_label)],
        } }
    """
    rel_types = [
        record["relationshipType"]
        for record in session.run(
            "CALL db.relationshipTypes() YIELD relationshipType "
            "RETURN relationshipType"
        )
    ]

    rel_schema: dict[str, dict[str, Any]] = {}

    for rel_type in sorted(rel_types):
        properties: dict[str, dict[str, Any]] = defaultdict(
            lambda: {"types": set(), "examples": []}
        )
        connections: set[tuple[str, str]] = set()

        query = (
            f"MATCH (a)-[r:`{rel_type}`]->(b) "
            "WITH a, r, b LIMIT 500 "
            "RETURN labels(a) AS src, properties(r) AS props, labels(b) AS dst"
        )
        for record in session.run(query):
            src_labels = record["src"] or ["_"]
            dst_labels = record["dst"] or ["_"]
            for src in src_labels:
                for dst in dst_labels:
                    connections.add((src, dst))

            props = record["props"] or {}
            for key, value in props.items():
                entry = properties[key]
                entry["types"].add(_python_type_name(value))
                if value is not None and len(entry["examples"]) < example_count:
                    if value not in entry["examples"]:
                        entry["examples"].append(value)

        rel_schema[rel_type] = {
            "properties": dict(properties),
            "connections": connections,
        }

    return rel_schema


def _render_markdown(
    node_schema: dict[str, dict[str, dict[str, Any]]],
    rel_schema: dict[str, dict[str, Any]],
    database: str,
) -> str:
    """Render the collected schema into clean Markdown for an LLM context."""
    lines: list[str] = []
    lines.append(f"# Neo4j Graph Schema — `{database}`")
    lines.append("")
    lines.append(
        f"This schema describes **{len(node_schema)} node label(s)** and "
        f"**{len(rel_schema)} relationship type(s)**."
    )
    lines.append("")

    # --- Node labels -------------------------------------------------------
    lines.append("## Node Labels")
    lines.append("")
    if not node_schema:
        lines.append("_No node labels found._")
        lines.append("")
    for label, properties in node_schema.items():
        lines.append(f"### (:{label})")
        lines.append("")
        if not properties:
            lines.append("_No properties._")
            lines.append("")
            continue
        lines.append("| Property | Type | Example Values |")
        lines.append("| --- | --- | --- |")
        for prop, meta in sorted(properties.items()):
            types = " \\| ".join(sorted(meta["types"])) or "unknown"
            examples = ", ".join(_format_value(v) for v in meta["examples"])
            examples = examples or "—"
            lines.append(f"| `{prop}` | {types} | {examples} |")
        lines.append("")

    # --- Relationship types ------------------------------------------------
    lines.append("## Relationship Types")
    lines.append("")
    if not rel_schema:
        lines.append("_No relationship types found._")
        lines.append("")
    for rel_type, meta in rel_schema.items():
        lines.append(f"### [:{rel_type}]")
        lines.append("")

        connections = sorted(meta["connections"])
        if connections:
            lines.append("**Connections:**")
            lines.append("")
            for src, dst in connections:
                lines.append(f"- `(:{src})-[:{rel_type}]->(:{dst})`")
            lines.append("")

        properties = meta["properties"]
        if properties:
            lines.append("**Properties:**")
            lines.append("")
            lines.append("| Property | Type | Example Values |")
            lines.append("| --- | --- | --- |")
            for prop, prop_meta in sorted(properties.items()):
                types = " \\| ".join(sorted(prop_meta["types"])) or "unknown"
                examples = ", ".join(
                    _format_value(v) for v in prop_meta["examples"]
                )
                examples = examples or "—"
                lines.append(f"| `{prop}` | {types} | {examples} |")
            lines.append("")
        else:
            lines.append("_No properties._")
            lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def get_neo4j_schema_markdown(
    uri: str = DEFAULT_URI,
    username: str = DEFAULT_USER,
    password: str = DEFAULT_PASSWORD,
    database: str = DEFAULT_DATABASE,
    example_count: int = DEFAULT_EXAMPLE_COUNT,
    output_path: str | None = None,
) -> str:
    """Connect to Neo4j, extract the schema and return it as Markdown.

    Args:
        uri: Neo4j connection URI (e.g. ``neo4j+s://host``).
        username: Database username.
        password: Database password.
        database: Target database name.
        example_count: Number of example values to collect per property.
        output_path: Optional file path. If provided, the Markdown is also
            written to this file.

    Returns:
        The schema rendered as a Markdown string.

    Raises:
        RuntimeError: If the connection or schema extraction fails.
    """
    driver = None
    try:
        driver = GraphDatabase.driver(uri, auth=(username, password))
        # Fail fast if the server is unreachable or credentials are wrong.
        driver.verify_connectivity()

        with driver.session(database=database) as session:
            node_schema = _fetch_node_schema(session, example_count)
            rel_schema = _fetch_relationship_schema(session, example_count)

    except AuthError as exc:
        raise RuntimeError(
            f"Authentication failed for user '{username}': {exc}"
        ) from exc
    except ServiceUnavailable as exc:
        raise RuntimeError(
            f"Could not reach Neo4j at '{uri}': {exc}"
        ) from exc
    except Neo4jError as exc:
        raise RuntimeError(f"Neo4j query error: {exc}") from exc
    except Exception as exc:  # noqa: BLE001 - surface any unexpected failure
        raise RuntimeError(f"Unexpected error extracting schema: {exc}") from exc
    finally:
        if driver is not None:
            driver.close()

    markdown = _render_markdown(node_schema, rel_schema, database)

    if output_path:
        try:
            with open(output_path, "w", encoding="utf-8") as handle:
                handle.write(markdown)
        except OSError as exc:
            raise RuntimeError(
                f"Failed to write schema to '{output_path}': {exc}"
            ) from exc

    return markdown


if __name__ == "__main__":
    schema_md = get_neo4j_schema_markdown(output_path="neo4j_schema.md")
    print(schema_md)
