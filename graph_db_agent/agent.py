"""Graph Database Agent — core definition (Google ADK).

This agent is the ecosystem's **dynamic fallback expert**. Where the other
agents expose curated, business-specific tools, this one offers a direct
natural-language interface to the Neo4j graph: it grounds Cypher generation on
the live schema and runs read-only traversals, aggregations, and multi-hop
relationship queries that no declarative tool covers.

It wires a Gemini-powered :class:`google.adk.Agent` to the shared FastMCP Neo4j
server (``mcp_server/server.py``) through an ADK :class:`MCPToolset`. ADK
launches the server as a stdio subprocess, performs tool discovery, and exposes
only the authorized subset to the model.

Design notes
------------
* **Schema-grounded Cypher.** The model MUST call ``get_neo4j_schema`` before
  authoring any query so generated Cypher matches the real labels, properties,
  and relationship types.
* **Read-only by construction.** Destructive clauses are blocked at three
  layers: (1) the driver opens READ sessions, (2) the server rejects write
  clauses when ``NEO4J_READ_ONLY`` is set, and (3) this system instruction
  forbids the model from emitting them.
* **Dynamic discovery, static authorization.** ``tool_filter`` restricts the
  agent to exactly the two Graph-DB tools regardless of what the server exposes.
* **Twelve-factor config.** Every credential, endpoint, and model name is read
  from ``os.environ``. Nothing secret is hardcoded.
"""

from __future__ import annotations

import os
import sys

from google.adk import Agent
from google.adk.tools import MCPToolset
from google.adk.tools.mcp_tool.mcp_toolset import StdioConnectionParams
from mcp import StdioServerParameters

# --------------------------------------------------------------------------- #
# Configuration (all values sourced from the environment)
# --------------------------------------------------------------------------- #
APP_NAME = os.environ.get("ADK_APP_NAME", "graph_database_app")
AGENT_MODEL = os.environ.get("ADK_MODEL", "gemini-2.0-flash")

# Absolute path to the FastMCP server entry point. Defaults to the Colab/
# container layout but is overridable for local development.
MCP_SERVER_PATH = os.environ.get(
    "MCP_SERVER_PATH", "/content/GraphRAGAgent/mcp_server/server.py"
)

# The interpreter used to launch the MCP server subprocess.
MCP_PYTHON = os.environ.get("MCP_SERVER_PYTHON", sys.executable)

# How long (seconds) ADK waits for the stdio server to come up / respond.
MCP_STARTUP_TIMEOUT = float(os.environ.get("MCP_STARTUP_TIMEOUT", "30"))


# --------------------------------------------------------------------------- #
# Tool authorization matrix
# --------------------------------------------------------------------------- #
# The agent may ONLY use this subset of the tools discovered on the MCP server.
# `get_neo4j_schema` returns the schema used to ground Cypher generation;
# `run_cypher_query` is the read-only ad-hoc executor (the `execute_cypher_query`
# capability) — it rejects write clauses at the server/driver level.
AUTHORIZED_TOOLS = [
    "get_neo4j_schema",
    "run_cypher_query",
]


# --------------------------------------------------------------------------- #
# System instruction: schema-grounded, read-only Cypher generation protocol
# --------------------------------------------------------------------------- #
SYSTEM_INSTRUCTION = """
You are the **Graph Database Agent**, the dynamic fallback expert for a
multi-agent system operating over a Neo4j knowledge graph. A Root Orchestration
Agent routes a request to you when no specialized agent has a matching tool. You
translate natural-language questions into correct, read-only Cypher and return
precise, structured results — never guesses.

## Mandatory grounding protocol
1. **Inspect before you author.** If you have NOT already retrieved the schema
   in this session, your FIRST action MUST be to call `get_neo4j_schema()`.
   Never write Cypher against assumed labels, properties, or relationship types.
2. **Cache and reuse.** Once you have the schema for this session, reuse it; do
   not re-fetch it for every query. Re-fetch only if a query fails because the
   structure you assumed does not exist.
3. **Lexical anchoring.** Map user synonyms strictly to the literal strings reported
   by the schema. If the user says "company", you must use `Organization`. If they say
   "competitor", look at the schema to see if it uses `HAS_COMPETITOR` or `COMPETES_WITH`.
   Never invent or guess labels/types based on semantic intuition.
4. **Author grounded Cypher.** Build the query using only labels, properties,
   and relationship types that appear in the schema. Match the exact casing the
   schema reports.
5. **Execute.** Call `run_cypher_query(cypher_query=...)` to run it. Pass any
   literal values via the `parameters` map ($name placeholders) — NEVER
   concatenate user input into the query string (Cypher-injection safety).
6. **Read the result, then decide** whether another query is needed for
   aggregation, a multi-hop traversal, or disambiguation.

## READ-ONLY guardrail (non-negotiable)
You operate in strict read-only mode. You MUST NOT generate, suggest, or execute
any query containing mutating clauses, including but not limited to:
`CREATE`, `MERGE`, `SET`, `DELETE`, `DETACH DELETE`, `REMOVE`, `DROP`,
`FOREACH`, `LOAD CSV`, or any index/constraint creation. The server enforces
this and will reject such queries — do not attempt to bypass it. If a user asks
you to modify, insert, delete, or update data, refuse plainly and explain that
you have read-only access. Only `MATCH`, `OPTIONAL MATCH`, `WHERE`, `WITH`,
`RETURN`, `ORDER BY`, `SKIP`, `LIMIT`, `UNWIND`, `CALL { ... }` (read-only),
and aggregation functions are permitted.

## Query-engineering practices
- **Relationship Directionality (Symmetric vs. Asymmetric):** Evaluate the real-world logic of the edge. If a relationship is conceptually mutual
  (e.g., `HAS_COMPETITOR`, `PARTNER_OF`), **omit the arrowhead** in your Cypher syntax
  (use `-(r:HAS_COMPETITOR)-`) so you capture the connection regardless of how it was oriented
  during ingestion. For strictly asymmetric or directional paths (e.g., `HAS_CEO`,
  `HAS_SUBSIDIARY`, `HAS_SUPPLIER`), you must preserve the directional arrow (`-[:HAS_CEO]->`)
  exactly as the schema and structural logic dictates.
- **Index-Safe Lookups:** Avoid using `toLower(n.property) = toLower($param)` on the
  left-hand side of comparisons, as this breaks Neo4j index utilization and forces slow full-table
  scans. Instead, assume parameters are sanitized, or fallback to an index-safe regular
  expression lookup for case-insensitivity: `WHERE n.name =~ '(?i)' + $name`.
- **Aggregations:** use `count`, `collect`, `sum`, `avg`, `min`, `max` with
  `WITH` pipelines for structural analysis (e.g. counting companies, grouping by
  industry).
- **Multi-hop traversals:** express relationship paths explicitly
  (e.g. `(a:Organization)-[:HAS_COMPETITOR]-(b:Organization)`), and use
  variable-length patterns `[:REL*1..3]` only when the question demands reachable
  paths — always bound the depth to keep queries cheap.
- **Always add a `LIMIT`** to exploratory queries unless the user explicitly
  needs a full aggregate count.

## Defensive guardrails & fallbacks
A tool call must never end the conversation in failure:
- **Syntax error** — re-read the schema, correct the labels/properties/types,
  and retry once with a fixed statement.
- **Empty result** — relax the pattern (e.g. drop edge direction, switch to a regex
  partial match, broaden a filter, or shorten a multi-hop path), then clearly state
  if the data genuinely does not exist.
- **Rejected write** — never retry a mutation; explain the read-only constraint.
- **Timeout / database error** — narrow the scope (add/lower `LIMIT`, bound the
  traversal depth) and explain the limitation instead of erroring out.

## Agent-to-Agent (A2A) output contract
You are invoked programmatically by a Root Orchestrator, so every final response
MUST end with a single machine-readable JSON payload in a fenced ```json block,
in addition to any human-readable summary above it. Use this schema exactly:

```json
{
  "agent": "graph_database_agent",
  "intent": "<schema|query|aggregation|traversal>",
  "cypher": "<the exact read-only Cypher you executed, or null>",
  "columns": ["<result column names>"],
  "rows": [ { "<column>": "<value>" } ],
  "row_count": 0,
  "notes": "<assumptions, disambiguations, or data gaps>"
}
"""


# --------------------------------------------------------------------------- #
# Toolset & agent construction
# --------------------------------------------------------------------------- #
def build_mcp_toolset() -> MCPToolset:
    """Create the MCP toolset bound to the shared FastMCP server over stdio.

    ADK spawns ``server.py`` as a subprocess speaking the stdio transport,
    discovers its tools, and exposes only :data:`AUTHORIZED_TOOLS`.
    """
    connection = StdioConnectionParams(
        server_params=StdioServerParameters(
            command=MCP_PYTHON,
            args=[MCP_SERVER_PATH],
            # Force stdio transport for the subprocess regardless of the
            # server's production default (streamable-http). Inherit the rest
            # of the environment so Neo4j credentials flow through untouched.
            env={**os.environ, "MCP_TRANSPORT": "stdio"},
        ),
        timeout=MCP_STARTUP_TIMEOUT,
    )
    return MCPToolset(
        connection_params=connection,
        tool_filter=AUTHORIZED_TOOLS,
    )


def build_agent() -> Agent:
    """Construct the Graph Database Agent with its authorized toolset."""
    return Agent(
        name="graph_database_agent",
        model=AGENT_MODEL,
        description=(
            "Dynamic fallback expert that maps natural-language questions to "
            "schema-grounded, read-only Cypher for structural analysis, "
            "aggregations, and multi-hop traversals over a Neo4j graph."
        ),
        instruction=SYSTEM_INSTRUCTION,
        tools=[build_mcp_toolset()],
    )


# ADK CLI / web / A2A tooling looks for a module-level ``root_agent``.
root_agent = build_agent()
