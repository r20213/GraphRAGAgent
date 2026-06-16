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

READ_ONLY = os.getenv("NEO4J_READ_ONLY", "true").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}
QUERY_TIMEOUT = float(os.getenv("NEO4J_QUERY_TIMEOUT", "15"))
MAX_RESULT_RECORDS = int(os.getenv("MAX_RESULT_RECORDS", "100"))
SCHEMA_SAMPLE_LIMIT = int(os.getenv("SCHEMA_SAMPLE_LIMIT", "1000"))
MAX_POOL_SIZE = int(os.getenv("NEO4J_MAX_POOL_SIZE", "50"))
CONNECTION_TIMEOUT = float(os.getenv("NEO4J_CONNECTION_TIMEOUT", "30"))

SCHEMA_DOC_PATH = _REPO_ROOT / "utils" / "neo4j_schema.md"

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
        logger.info("Initialising Neo4j driver pool -> %s", NEO4J_URI)
        _driver = GraphDatabase.driver(
            NEO4J_URI,
            auth=(NEO4J_USERNAME, NEO4J_PASSWORD),
            max_connection_pool_size=MAX_POOL_SIZE,
            connection_timeout=CONNECTION_TIMEOUT,
        )
        # Fail fast on a broken endpoint / bad credentials.
        _driver.verify_connectivity()
        logger.info("Neo4j driver pool ready (read_only=%s).", READ_ONLY)
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
# Security: write-clause detection for the ad-hoc Cypher fallback
# --------------------------------------------------------------------------- #
_WRITE_CLAUSE = re.compile(
    r"\b(CREATE|MERGE|DELETE|DETACH\s+DELETE|SET|REMOVE|DROP|FOREACH|"
    r"LOAD\s+CSV|CALL\s+\{[^}]*\b(CREATE|MERGE|DELETE|SET)\b|"
    r"apoc\.(create|merge|refactor)|CREATE\s+(INDEX|CONSTRAINT)|"
    r"CALL\s+db\.create)\b",
    re.IGNORECASE,
)


def _is_write_query(cypher: str) -> bool:
    """Heuristically detect whether a Cypher statement mutates the graph."""
    # Strip string literals so keywords inside data values do not trigger.
    stripped = re.sub(r"'[^']*'|\"[^\"]*\"", "", cypher)
    return bool(_WRITE_CLAUSE.search(stripped))


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
# MCP server + declarative pre-validated query catalogue
# --------------------------------------------------------------------------- #
mcp = FastMCP(
    "neo4j-companies",
    instructions=(
        "Read-only MCP server for the Neo4j `companies` graph. Prefer the "
        "declarative tools (get_industries, get_companies_in_industry, "
        "get_articles_with_sentiment, get_people_in_organizations, "
        "find_investor_by_name, find_investor_by_id). Use get_neo4j_schema + "
        "run_cypher_query only for ad-hoc graph traversals not covered by a "
        "declarative tool. All inputs are passed as native Cypher parameters."
    ),
)

# Declarative, expert-authored query templates. The graph uses `Organization`
# (companies), `IndustryCategory` (industries) and `HAS_INVESTOR` / `HAS_CEO`
# / `HAS_BOARD_MEMBER` relationships per utils/neo4j_schema.md.
QUERY_TEMPLATES: dict[str, dict[str, str]] = {
    "get_industries": {
        "description": "Fetch all industries (IndustryCategory) from database.",
        "query": """
            MATCH (i:IndustryCategory)
            RETURN i.name AS name, i.id AS id
            ORDER BY name
        """,
    },
    "get_companies_in_industry": {
        "description": "List companies (Organizations) within an industry.",
        "query": """
            MATCH (o:Organization)-[:HAS_CATEGORY]->(i:IndustryCategory)
            WHERE toLower(i.name) = toLower($industry_name)
            RETURN o.id AS id,
                   o.name AS name,
                   o.summary AS summary,
                   o.nbrEmployees AS employees,
                   o.revenue AS revenue,
                   o.isPublic AS is_public
            ORDER BY name
        """,
    },
    "get_articles_with_sentiment": {
        "description": "Articles filtered by minimum sentiment and optional date.",
        "query": """
            MATCH (a:Article)
            WHERE a.sentiment >= $min_sentiment
              AND ($year IS NULL OR a.date.year = $year)
              AND ($month IS NULL OR a.date.month = $month)
            RETURN a.title AS title,
                   a.sentiment AS sentiment,
                   a.date AS date,
                   a.siteName AS site
            ORDER BY a.sentiment DESC
        """,
    },
    "get_people_in_organizations": {
        "description": "Personnel matching a role within selected companies.",
        "query": """
            MATCH (o:Organization)-[rel]->(p:Person)
            WHERE o.name IN $company_names
              AND type(rel) IN $rel_types
            RETURN o.name AS company,
                   p.name AS person,
                   p.summary AS details,
                   type(rel) AS relationship
            ORDER BY company, person
        """,
    },
    "find_investor_by_name": {
        "description": "Entities that invested in the target company.",
        "query": """
            MATCH (o:Organization)-[:HAS_INVESTOR]->(inv)
            WHERE toLower(o.name) = toLower($company_name)
            RETURN inv.name AS investor,
                   inv.id AS investor_id,
                   labels(inv) AS node_types
            ORDER BY investor
        """,
    },
    "find_investor_by_id": {
        "description": "Full investment portfolio for a unique investor id.",
        "query": """
            MATCH (o:Organization)-[:HAS_INVESTOR]->(inv)
            WHERE inv.id = $investor_id
            RETURN inv.name AS investor,
                   labels(inv) AS investor_type,
                   collect({company: o.name, company_id: o.id})[..100] AS portfolio
        """,
    },
}

# Map human role names to the graph's relationship types.
_ROLE_TO_RELS: dict[str, list[str]] = {
    "ceo": ["HAS_CEO"],
    "board member": ["HAS_BOARD_MEMBER"],
    "board": ["HAS_BOARD_MEMBER"],
    "director": ["HAS_BOARD_MEMBER"],
    "any": ["HAS_CEO", "HAS_BOARD_MEMBER"],
}


# --------------------------------------------------------------------------- #
# Investment Research Agent tools
# --------------------------------------------------------------------------- #
@mcp.tool()
def get_industries(agent_session_id: str | None = None) -> str:
    """List every available industry name and id.

    Routing: Investment Research Agent. Input: none.
    """
    tmpl = QUERY_TEMPLATES["get_industries"]

    def _run() -> str:
        records = execute_read("get_industries", tmpl["query"], {}, agent_session_id)
        return _format_records(records, "No industries found in the database.")

    return _safe("get_industries", _run)


@mcp.tool()
def get_companies_in_industry(
    industry_name: str, agent_session_id: str | None = None
) -> str:
    """List companies belonging to ``industry_name`` (case-insensitive).

    Routing: Investment Research Agent. Input: industry_name (String).
    """
    tmpl = QUERY_TEMPLATES["get_companies_in_industry"]

    def _run() -> str:
        records = execute_read(
            "get_companies_in_industry",
            tmpl["query"],
            {"industry_name": industry_name},
            agent_session_id,
        )
        return _format_records(
            records,
            f"No companies found for industry '{industry_name}'. "
            "Check the spelling or call get_industries() for valid names.",
        )

    return _safe("get_companies_in_industry", _run)


@mcp.tool()
def get_articles_with_sentiment(
    min_sentiment: float,
    year: int | None = None,
    month: int | None = None,
    agent_session_id: str | None = None,
) -> str:
    """Articles with sentiment >= ``min_sentiment``, optionally by year/month.

    Routing: Investment Research Agent.
    Input: min_sentiment (Float), year (Int, opt), month (Int, opt).
    """
    tmpl = QUERY_TEMPLATES["get_articles_with_sentiment"]

    def _run() -> str:
        records = execute_read(
            "get_articles_with_sentiment",
            tmpl["query"],
            {"min_sentiment": min_sentiment, "year": year, "month": month},
            agent_session_id,
        )
        return _format_records(
            records,
            "No articles matched the given sentiment/date filters.",
        )

    return _safe("get_articles_with_sentiment", _run)


@mcp.tool()
def get_people_in_organizations(
    company_names: list[str],
    role: str = "any",
    agent_session_id: str | None = None,
) -> str:
    """Personnel matching ``role`` (e.g. "CEO") in the given companies.

    Routing: Investment Research Agent.
    Input: company_names (List[String]), role (String).
    """
    tmpl = QUERY_TEMPLATES["get_people_in_organizations"]
    rel_types = _ROLE_TO_RELS.get(role.strip().lower(), _ROLE_TO_RELS["any"])

    def _run() -> str:
        records = execute_read(
            "get_people_in_organizations",
            tmpl["query"],
            {"company_names": company_names, "rel_types": rel_types},
            agent_session_id,
        )
        return _format_records(
            records,
            f"No '{role}' personnel found for the supplied companies.",
        )

    return _safe("get_people_in_organizations", _run)


# --------------------------------------------------------------------------- #
# Investor Research Agent tools
# --------------------------------------------------------------------------- #
@mcp.tool()
def find_investor_by_name(
    company_name: str, agent_session_id: str | None = None
) -> str:
    """Find entities (Person/Organization) that invested in ``company_name``.

    Routing: Investor Research Agent. Input: company_name (String).
    """
    tmpl = QUERY_TEMPLATES["find_investor_by_name"]

    def _run() -> str:
        records = execute_read(
            "find_investor_by_name",
            tmpl["query"],
            {"company_name": company_name},
            agent_session_id,
        )
        return _format_records(
            records,
            f"No investors found for company '{company_name}'. "
            "Verify the company name spelling.",
        )

    return _safe("find_investor_by_name", _run)


@mcp.tool()
def find_investor_by_id(
    investor_id: str, agent_session_id: str | None = None
) -> str:
    """Return the full investment portfolio for a unique ``investor_id``.

    Routing: Investor Research Agent. Input: investor_id (String/Int).
    """
    tmpl = QUERY_TEMPLATES["find_investor_by_id"]

    def _run() -> str:
        records = execute_read(
            "find_investor_by_id",
            tmpl["query"],
            {"investor_id": str(investor_id)},
            agent_session_id,
        )
        return _format_records(
            records,
            f"No investor found with id '{investor_id}'.",
        )

    return _safe("find_investor_by_id", _run)


# --------------------------------------------------------------------------- #
# Graph Database Agent tools (schema + ad-hoc fallback)
# --------------------------------------------------------------------------- #
@mcp.tool()
def get_neo4j_schema() -> str:
    """Return the graph schema (node labels, properties, relationships).

    Routing: Graph Database Agent. Input: none. Reads the pre-computed
    ``utils/neo4j_schema.md`` so the LLM can author correct ad-hoc Cypher.
    """

    def _run() -> str:
        if SCHEMA_DOC_PATH.exists():
            return SCHEMA_DOC_PATH.read_text(encoding="utf-8")
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
def run_cypher_query(
    cypher_query: str,
    parameters: dict[str, Any] | None = None,
    agent_session_id: str | None = None,
) -> str:
    """Execute an ad-hoc, read-only Cypher query for GraphRAG traversals.

    Routing: Graph Database Agent. Use ``get_neo4j_schema()`` first to author
    a correct statement. Pass any literals via ``parameters`` ($name syntax) —
    never concatenate values into the query string.

    Examples: ``MATCH (c:Organization) RETURN count(c) AS total`` or
    ``MATCH (a:Organization)-[:HAS_COMPETITOR]->(b) RETURN a.name, b.name``.
    """

    def _run() -> str:
        if READ_ONLY and _is_write_query(cypher_query):
            logger.warning("Rejected write query in read-only mode.")
            return (
                "Rejected: this server is read-only. Write clauses (CREATE, "
                "MERGE, DELETE, SET, REMOVE, DROP, ...) are not permitted."
            )
        records = execute_read(
            "run_cypher_query",
            cypher_query,
            parameters or {},
            agent_session_id,
        )
        return _format_records(records, "Query executed successfully; 0 rows.")

    return _safe("run_cypher_query", _run)


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #
def main() -> None:
    """Start the MCP server over stdio after verifying connectivity."""
    try:
        get_driver()  # fail fast before accepting MCP traffic
    except Exception:  # noqa: BLE001
        logger.exception("Fatal: could not establish Neo4j connectivity.")
        close_driver()
        sys.exit(1)

    logger.info(
        "Starting Neo4j MCP server (read_only=%s, timeout=%ss, cap=%s).",
        READ_ONLY,
        QUERY_TIMEOUT,
        MAX_RESULT_RECORDS,
    )
    try:
        mcp.run()
    finally:
        close_driver()


if __name__ == "__main__":
    main()
