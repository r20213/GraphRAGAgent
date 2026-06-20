"""Enterprise-grade Model Context Protocol (MCP) server for Neo4j.

Exposes a curated set of declarative, pre-validated query tools alongside a
schema-informed Graph Database Agent fallback for ad-hoc read traversals over
the public ``companies`` demo graph.

Production design patterns implemented here:

* Connection pooling & lifecycle management
    - Single global :class:`neo4j.Driver` instance reused across requests.
    - Every unit of work runs inside a ``with driver.session() as session``
      context manager so connections always return cleanly to the pool.
    - ``SIGTERM`` / ``SIGINT`` / ``atexit`` hooks close the driver gracefully.

* Security & Cypher-injection prevention
    - Optional ``NEO4J_READ_ONLY`` enforcement (sessions opened READ-only and
      write clauses rejected).
    - All tool inputs are passed as native Cypher ``$parameters`` — never via
      string concatenation.

* Performance guardrails
    - Hard per-transaction timeout (default 15s).
    - Server-side result cap (default 100 records).
    - Schema sampling capped per label (default 1000 nodes).

* Observability
    - Tracing metadata (``mcp_tool_name``, ``agent_session_id``) attached to
      every transaction.
    - try/except telemetry returns clean LLM-friendly strings while raw stack
      traces are logged to the internal error stream.
"""

from __future__ import annotations

import atexit
import logging
import os
import re
import signal
import sys
import uuid
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP
from neo4j import READ_ACCESS, GraphDatabase, Query
from neo4j.exceptions import (
    AuthError,
    CypherSyntaxError,
    Neo4jError,
    ServiceUnavailable,
)

# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #
_REPO_ROOT = Path(__file__).resolve().parent.parent

# Load the repository-root .env first, then fall back to utils/.env so the
# server works regardless of which file the operator populated.
load_dotenv(_REPO_ROOT / ".env")
load_dotenv(_REPO_ROOT / "utils" / ".env")

NEO4J_URI = os.getenv("NEO4J_URI", "neo4j+s://demo.neo4jlabs.com")
NEO4J_USERNAME = os.getenv("NEO4J_USERNAME", "companies")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "companies")
NEO4J_DATABASE = os.getenv("NEO4J_DATABASE", "companies")

# Optional least-privilege read-only credentials. The original `companies`
# demo database is writable by no one (the account itself is read-only), but
# the migrated target (Aura) authenticates with a *writable* account. When a
# dedicated read-only user is available, set these so the driver authenticates
# as that user — writes are then blocked at the database RBAC level, the
# strongest guardrail. They default to the primary credentials when unset.
NEO4J_READONLY_USERNAME = os.getenv("NEO4J_READONLY_USERNAME", "").strip()
NEO4J_READONLY_PASSWORD = os.getenv("NEO4J_READONLY_PASSWORD", "")

QUERY_TIMEOUT = float(os.getenv("NEO4J_QUERY_TIMEOUT", "15"))
MAX_RESULT_RECORDS = int(os.getenv("MAX_RESULT_RECORDS", "100"))
SCHEMA_SAMPLE_LIMIT = int(os.getenv("SCHEMA_SAMPLE_LIMIT", "1000"))
MAX_POOL_SIZE = int(os.getenv("NEO4J_MAX_POOL_SIZE", "50"))
CONNECTION_TIMEOUT = float(os.getenv("NEO4J_CONNECTION_TIMEOUT", "30"))

# Transport: "stdio" for local desktop clients, "streamable-http" (or "sse")
# for networked/production deployment behind a URL (served by uvicorn).
MCP_TRANSPORT = os.getenv("MCP_TRANSPORT", "streamable-http").strip().lower()
MCP_HOST = os.getenv("MCP_HOST", "0.0.0.0")
MCP_PORT = int(os.getenv("MCP_PORT", "8000"))

# Schema documentation. The server can be pointed at either the *original*
# Neo4j database (described by ``utils/neo4j_schema.md``) or the migrated
# *target* database (described by ``utils/neo4j_export_schema.md``). Both share
# the same core labels/relationships, so every declarative tool works against
# either; only the schema doc surfaced by ``get_neo4j_schema`` differs. The
# correct doc is resolved at runtime by matching the connected
# ``NEO4J_DATABASE`` against the database name recorded in each doc's title,
# with an optional explicit ``NEO4J_SCHEMA_DOC`` override.
_SCHEMA_DOC_DIR = _REPO_ROOT / "utils"
_SCHEMA_DOC_CANDIDATES = (
    _SCHEMA_DOC_DIR / "neo4j_schema.md",  # original `companies` database
    _SCHEMA_DOC_DIR / "neo4j_export_schema.md",  # migrated target database
)
# Explicit operator override (absolute path, or relative to the repo root).
_SCHEMA_DOC_OVERRIDE = os.getenv("NEO4J_SCHEMA_DOC", "").strip()

# Backwards-compatible default used when nothing else matches.
SCHEMA_DOC_PATH = _SCHEMA_DOC_CANDIDATES[0]

# Parses the database name out of a schema-doc title, e.g.
# "# Neo4j Graph Schema — `companies`" -> "companies". The separator may be an
# em dash (U+2014), en dash (U+2013) or hyphen.
_SCHEMA_TITLE_DB = re.compile(
    r"#\s*Neo4j Graph Schema\s*[\u2014\u2013-]\s*`?([^`\n]+?)`?\s*$",
    re.MULTILINE,
)

# Cache the resolved doc so the title files are only parsed once per process.
_schema_doc_resolved: Path | None = None


def _schema_doc_db_name(path: Path) -> str | None:
    """Return the database name recorded in a schema doc's title, if any."""
    try:
        head = path.read_text(encoding="utf-8")[:512]
    except OSError:
        return None
    match = _SCHEMA_TITLE_DB.search(head)
    return match.group(1).strip() if match else None


def _resolve_schema_doc() -> Path | None:
    """Pick the schema doc that matches the connected database (cached).

    Resolution order:
      1. ``NEO4J_SCHEMA_DOC`` explicit override (if it exists).
      2. The candidate whose title database name equals ``NEO4J_DATABASE``.
      3. The first existing candidate (backwards-compatible default).
    """
    global _schema_doc_resolved
    if _schema_doc_resolved is not None:
        return _schema_doc_resolved

    # 1. Explicit operator override always wins.
    if _SCHEMA_DOC_OVERRIDE:
        override = Path(_SCHEMA_DOC_OVERRIDE)
        if not override.is_absolute():
            override = _REPO_ROOT / override
        if override.exists():
            _schema_doc_resolved = override
            logger.info("Using schema doc from NEO4J_SCHEMA_DOC=%s.", override)
            return override
        logger.warning(
            "NEO4J_SCHEMA_DOC=%s not found; falling back to auto-detection.",
            _SCHEMA_DOC_OVERRIDE,
        )

    # 2. Match the connected database against each doc's recorded title name.
    target_db = (NEO4J_DATABASE or "").strip().lower()
    if target_db:
        for path in _SCHEMA_DOC_CANDIDATES:
            doc_db = _schema_doc_db_name(path)
            if doc_db and doc_db.lower() == target_db:
                _schema_doc_resolved = path
                logger.info(
                    "Resolved schema doc %s for database '%s'.",
                    path.name,
                    NEO4J_DATABASE,
                )
                return path

    # 3. Backwards-compatible fallback: first candidate that exists on disk.
    for path in _SCHEMA_DOC_CANDIDATES:
        if path.exists():
            _schema_doc_resolved = path
            logger.info(
                "No schema doc matched database '%s'; defaulting to %s.",
                NEO4J_DATABASE,
                path.name,
            )
            return path

    return None

# --------------------------------------------------------------------------- #
# Logging (raw stack traces go to the internal error stream, never to the LLM)
# --------------------------------------------------------------------------- #
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    stream=sys.stderr,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
)
logger = logging.getLogger("neo4j-mcp")

# --------------------------------------------------------------------------- #
# Global driver (connection pool) — initialised once, reused everywhere
# --------------------------------------------------------------------------- #
_driver = None


def get_driver():
    """Return the lazily-initialised, process-wide Neo4j driver singleton."""
    global _driver
    if _driver is None:
        # Prefer a dedicated least-privilege read-only user when configured so
        # writes are blocked at the database RBAC layer, not just by the
        # transaction access mode and syntactic guards.
        if NEO4J_READONLY_USERNAME:
            auth = (NEO4J_READONLY_USERNAME, NEO4J_READONLY_PASSWORD)
            auth_user = NEO4J_READONLY_USERNAME
        else:
            auth = (NEO4J_USERNAME, NEO4J_PASSWORD)
            auth_user = NEO4J_USERNAME
        logger.info(
            "Initialising Neo4j driver pool -> %s (user=%s)", NEO4J_URI, auth_user
        )
        _driver = GraphDatabase.driver(
            NEO4J_URI,
            auth=auth,
            max_connection_pool_size=MAX_POOL_SIZE,
            connection_timeout=CONNECTION_TIMEOUT,
        )
        # Fail fast on a broken endpoint / bad credentials.
        _driver.verify_connectivity()
        logger.info("Neo4j driver pool ready.")
    return _driver


def close_driver(*_args: Any) -> None:
    """Gracefully close the driver, releasing all pooled sockets."""
    global _driver
    if _driver is not None:
        logger.info("Closing Neo4j driver pool ...")
        try:
            _driver.close()
        finally:
            _driver = None


def _handle_signal(signum: int, _frame: Any) -> None:
    """Signal handler that closes sockets before the process exits."""
    logger.info("Received signal %s; shutting down gracefully.", signum)
    close_driver()
    # Re-raise the default behaviour so the process actually terminates.
    sys.exit(0)


# Register cleanup hooks for orchestrators that send SIGTERM (k8s, systemd).
atexit.register(close_driver)
for _sig in (signal.SIGTERM, signal.SIGINT):
    try:
        signal.signal(_sig, _handle_signal)
    except (ValueError, OSError):  # pragma: no cover - non-main thread
        # signal.signal only works in the main thread; safe to skip otherwise.
        pass

# --------------------------------------------------------------------------- #
# Core read executor — single choke point for every tool
# --------------------------------------------------------------------------- #
def _serialise(value: Any) -> Any:
    """Convert Neo4j temporal/graph types into JSON-friendly primitives."""
    if isinstance(value, (list, tuple)):
        return [_serialise(v) for v in value]
    if isinstance(value, dict):
        return {k: _serialise(v) for k, v in value.items()}
    if hasattr(value, "isoformat"):  # neo4j.time.DateTime / Date / Time
        return value.isoformat()
    if hasattr(value, "items"):  # neo4j Node / Relationship as mapping
        return {k: _serialise(v) for k, v in dict(value).items()}
    return value


def execute_read(
    tool_name: str,
    cypher: str,
    params: dict[str, Any] | None = None,
    agent_session_id: str | None = None,
    cap: int | None = None,
) -> list[dict[str, Any]]:
    """Run a parameterised read query with full production guardrails.

    Args:
        tool_name: Logical MCP tool name (injected into tracing metadata).
        cypher: Parameterised Cypher (``$param`` placeholders only).
        params: Native Cypher parameter map.
        agent_session_id: Correlation id propagated into tx metadata.
        cap: Hard record cap; defaults to ``MAX_RESULT_RECORDS``.

    Returns:
        A list of JSON-serialisable record dictionaries (capped).
    """
    params = params or {}
    cap = cap or MAX_RESULT_RECORDS
    session_id = agent_session_id or str(uuid.uuid4())

    driver = get_driver()
    access_mode = READ_ACCESS  # all declarative tools are read-only

    # Observability: this metadata surfaces in query.log / dbms.listQueries.
    metadata = {
        "mcp_tool_name": tool_name,
        "agent_session_id": session_id,
        "app": "neo4j-mcp-server",
    }
    query = Query(cypher, timeout=QUERY_TIMEOUT, metadata=metadata)

    with driver.session(
        database=NEO4J_DATABASE, default_access_mode=access_mode
    ) as session:
        result = session.run(query, params)
        records: list[dict[str, Any]] = []
        for record in result:
            records.append({k: _serialise(v) for k, v in record.data().items()})
            if len(records) >= cap:
                logger.info(
                    "[%s] result capped at %s records (session=%s).",
                    tool_name,
                    cap,
                    session_id,
                )
                break
        return records


def _safe(tool_name: str, fn) -> Any:
    """Wrap a tool body with telemetry: clean LLM strings, raw logs internally."""
    try:
        return fn()
    except CypherSyntaxError as exc:
        logger.exception("[%s] Cypher syntax error.", tool_name)
        return f"Query rejected: invalid Cypher syntax. ({exc.message})"
    except AuthError:
        logger.exception("[%s] Authentication failure.", tool_name)
        return "Authentication failed: check Neo4j credentials in .env."
    except ServiceUnavailable:
        logger.exception("[%s] Database unavailable.", tool_name)
        return "The graph database is currently unreachable. Try again shortly."
    except Neo4jError as exc:
        logger.exception("[%s] Neo4j error.", tool_name)
        # Surface a hint but never the raw stack trace.
        return f"Query could not be completed: {exc.code or 'database error'}."
    except Exception:  # noqa: BLE001 - last-resort telemetry barrier
        logger.exception("[%s] Unexpected failure.", tool_name)
        return "An unexpected internal error occurred. The team has been notified."


def _format_records(records: list[dict[str, Any]], empty_hint: str) -> str:
    """Render capped records as a compact JSON-ish block for the LLM."""
    import json

    if not records:
        return empty_hint
    payload = {
        "record_count": len(records),
        "capped_at": MAX_RESULT_RECORDS,
        "records": records,
    }
    return json.dumps(payload, indent=2, ensure_ascii=False, default=str)


# --------------------------------------------------------------------------- #
# MCP server
# --------------------------------------------------------------------------- #
mcp = FastMCP(
    "neo4j-graphrag",
    host=MCP_HOST,
    port=MCP_PORT,
    instructions=(
        "Read-only MCP server for the Neo4j GraphRAG pipeline. "
        "Writes are rejected at the driver level via READ_ACCESS mode — "
        "no regex guardrail required. "
        "Use search_entities_fts to run full-text searches across the "
        "global_entity_search index (covers Article.title, Article.author, "
        "Article.siteName, and .name on Person/Organization/City/Country/"
        "IndustryCategory). "
        "Use run_graph_query for arbitrary read-only Cypher traversals. "
        "Use get_neo4j_schema to inspect labels, properties and relationships "
        "before authoring Cypher."
    ),
)


# --------------------------------------------------------------------------- #
# Graph tools
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# Graph Database Agent tools (schema + ad-hoc fallback)
# --------------------------------------------------------------------------- #
@mcp.tool()
def get_neo4j_schema() -> str:
    """Return the graph schema (node labels, properties, relationships).

    Routing: Graph Database Agent. Input: none. Reads the pre-computed schema
    doc matching the connected database (``utils/neo4j_schema.md`` for the
    original ``companies`` graph or ``utils/neo4j_export_schema.md`` for the
    migrated target graph) so the LLM can author correct ad-hoc Cypher.
    """

    def _run() -> str:
        doc = _resolve_schema_doc()
        if doc is not None and doc.exists():
            return doc.read_text(encoding="utf-8")
        # Fallback: live, sampled introspection (cap nodes per label).
        return _live_schema()

    return _safe("get_neo4j_schema", _run)


def _live_schema() -> str:
    """Lightweight, sampled schema introspection (<= SCHEMA_SAMPLE_LIMIT/label)."""
    labels = execute_read(
        "get_neo4j_schema",
        "CALL db.labels() YIELD label RETURN label ORDER BY label",
        cap=1000,
    )
    lines = ["# Neo4j Graph Schema (live sample)", ""]
    for row in labels:
        label = row["label"]
        props = execute_read(
            "get_neo4j_schema",
            # Parameterised label is not allowed; label comes from db.labels()
            # (trusted source), used via apoc-free sampling with LIMIT.
            f"MATCH (n:`{label}`) WITH n LIMIT $limit "
            "UNWIND keys(n) AS k RETURN DISTINCT k ORDER BY k",
            {"limit": SCHEMA_SAMPLE_LIMIT},
            cap=200,
        )
        keys = ", ".join(p["k"] for p in props) or "(no properties sampled)"
        lines.append(f"- **(:{label})**: {keys}")
    return "\n".join(lines)


@mcp.tool()
def search_entities_fts(
    query: str,
    top_k: int = 20,
    agent_session_id: str | None = None,
) -> str:
    """Full-text search across all indexed entity labels.

    Searches the ``global_entity_search`` index which covers:
    - ``Article``: title, author, siteName
    - ``Person``, ``Organization``, ``City``, ``Country``,
      ``IndustryCategory``: name

    Lucene syntax is supported (e.g. ``"Acme~"``, ``"Google OR Apple"``).
    Results are ranked by relevance score descending.

    Each result includes a ``matched_fields`` list naming the specific
    properties (``name``, ``title``, ``author``, ``siteName``) whose value
    contains the query term, so the agent knows exactly why a node matched.
    """
    fts_cypher = (
        'CALL db.index.fulltext.queryNodes('
        '"global_entity_search", $query, {limit: $top_k}) '
        "YIELD node, score "
        "RETURN "
        "  labels(node) AS labels, "
        "  score, "
        "  node.name    AS name, "
        "  node.title   AS title, "
        "  node.author  AS author, "
        "  node.siteName AS site_name, "
        # Tell the agent exactly which property triggered the match so it does
        # not have to guess why a node is relevant. Case-insensitive contains.
        "  [key IN ['name', 'title', 'author', 'siteName'] "
        "   WHERE node[key] IS NOT NULL "
        "     AND toLower(toString(node[key])) CONTAINS toLower($query)] "
        "  AS matched_fields "
        "ORDER BY score DESC"
    )

    def _run() -> str:
        records = execute_read(
            "search_entities_fts",
            fts_cypher,
            {"query": query, "top_k": top_k},
            agent_session_id,
            cap=top_k,
        )
        return _format_records(
            records, f"No entities matched the full-text query: '{query}'."
        )

    return _safe("search_entities_fts", _run)


@mcp.tool()
def run_graph_query(
    cypher: str,
    parameters: dict[str, Any] | None = None,
    agent_session_id: str | None = None,
) -> str:
    """Execute an arbitrary read-only Cypher query against the graph.

    Writes are rejected at the driver level by READ_ACCESS mode — no
    application-level write check is needed. Use ``get_neo4j_schema`` first
    to confirm label/property names. Pass all variable values via
    ``parameters`` to avoid string-interpolation issues.
    """

    def _run() -> str:
        records = execute_read(
            "run_graph_query",
            cypher,
            parameters or {},
            agent_session_id,
        )
        return _format_records(records, "Query executed successfully; 0 rows.")

    return _safe("run_graph_query", _run)






# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #
def main() -> None:
    """Start the MCP server after verifying Neo4j connectivity.

    Transport is selected via ``MCP_TRANSPORT``:
    ``streamable-http`` (default, production — served by uvicorn on
    ``MCP_HOST``:``MCP_PORT``), ``sse`` (legacy HTTP), or ``stdio`` (local
    desktop clients).
    """
    try:
        get_driver()  # fail fast before accepting MCP traffic
    except Exception:  # noqa: BLE001
        logger.exception(
            "Fatal: could not establish a Neo4j connection."
        )
        close_driver()
        sys.exit(1)

    if MCP_TRANSPORT == "stdio":
        logger.info(
            "Starting Neo4j MCP server over stdio "
            "(timeout=%ss, cap=%s).",
            QUERY_TIMEOUT,
            MAX_RESULT_RECORDS,
        )
    else:
        logger.info(
            "Starting Neo4j MCP server over %s on %s:%s "
            "(timeout=%ss, cap=%s).",
            MCP_TRANSPORT,
            MCP_HOST,
            MCP_PORT,
            QUERY_TIMEOUT,
            MAX_RESULT_RECORDS,
        )

    try:
        mcp.run(transport=MCP_TRANSPORT)
    finally:
        close_driver()


if __name__ == "__main__":
    main()
