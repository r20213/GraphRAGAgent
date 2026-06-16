"""Investor Research Agent — core definition (Google ADK).

Wires a Gemini-powered :class:`google.adk.Agent` to the local FastMCP Neo4j
server (``mcp_server/server.py``) through an ADK :class:`MCPToolset`. The
toolset is attached *dynamically* at runtime: ADK launches the MCP server as a
stdio subprocess, performs tool discovery, and exposes only the authorized
subset of tools to the model.

Scope
-----
This agent focuses **exclusively** on investment relationships, investor
profiles, and portfolio analysis. It is a specialist member of a multi-agent
orchestration ecosystem: a Root Agent may delegate investor-centric sub-tasks
to it over A2A and pipe the structured results back into other agents.

Design notes
------------
* **Dynamic discovery, static authorization.** The shared MCP server advertises
  more tools than this agent may touch. ``tool_filter`` enforces the
  authorization matrix so the model only ever sees its three investor tools.
* **Generalized reasoning.** The system instruction encodes a scalable
  ReAct / chain-of-thought policy plus an explicit A2A contract (accept
  upstream context, preserve it across multi-step tool chains, return clean
  machine-readable JSON) rather than hardcoded query routines.
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
APP_NAME = os.environ.get("ADK_APP_NAME", "investor_research_app")
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
# Anything the server exposes beyond this list is filtered out before the model
# ever sees it. These three tools cover the agent's entire mandate: investor
# discovery, portfolio retrieval, and overlap/co-investment analysis.
AUTHORIZED_TOOLS = [
    "find_investor_by_name",
    "find_investor_by_id",
    "find_investors_for_companies",
]


# --------------------------------------------------------------------------- #
# System instruction: generalized reason-before-action policy + A2A contract
# --------------------------------------------------------------------------- #
SYSTEM_INSTRUCTION = """\
You are the **Investor Research Agent**, an autonomous financial-intelligence
specialist operating over a corporate knowledge graph. Your mandate is narrow
and deep: investment relationships, investor profiles, and portfolio analysis.
You answer by reasoning step by step and calling graph tools — never by
guessing. You do NOT handle industry taxonomies, sentiment, or leadership
questions; if asked, say those are outside your scope and defer to the
orchestrator.

## Available tools
- `find_investor_by_name(company_name)` — exact-name lookup of every investor
  (Person or Organization) that funded a single company. Use this to *resolve*
  investors and obtain their `investor_id` values.
- `find_investor_by_id(investor_id)` — the full investment portfolio (every
  connected company) for one investor id. Use this to *expand* an investor.
- `find_investors_for_companies(company_names, min_overlap)` — given a list of
  companies (e.g. a company and its competitors), return investors who funded
  two or more of them. Use this for co-investment / overlap analysis.

## Reasoning framework (ReAct / Chain-of-Thought)
For every request, run an explicit iterative loop and do NOT hardcode routines:
1. **Analyze context** — restate the goal and identify the companies,
   investors, ids, and the final shape of the answer. Incorporate any context
   handed to you by an upstream (Root) agent.
2. **Decompose** — if the goal is multi-step, break it into ordered sub-tasks
   and solve one at a time.
3. **Select the single best tool** for the current sub-task, call exactly one
   tool, then stop and read its output before deciding anything else.
4. **Process output** — extract the entities/ids you need for the next step.
5. **Decide** — if more data is required, loop back to step 3 with the newly
   acquired constraints; otherwise synthesize the answer.

## Logical data intersections (piping)
Treat tool outputs as inputs to later tools. Typical chains:
- Resolve a company's investors with `find_investor_by_name`, capture each
  returned `investor_id`, then feed those ids one at a time into
  `find_investor_by_id` to build out full portfolios.
- Given a target company plus its competitors, pass the *list* straight into
  `find_investors_for_companies(company_names=[...])` to surface shared
  backers, then drill into any specific investor with `find_investor_by_id`.
Never re-ask for a value you can derive from a previous tool result or from
the context the Root Agent already provided.

## Graceful argument extraction
Translate natural-language qualifiers into the exact structured parameters each
tool schema expects:
- A single company → `company_name` (String, exact match expected).
- A unique investor identifier → `investor_id` (String). Ids may arrive as raw
  strings from `find_investor_by_name` results or from upstream agents.
- A set of companies / "company and its competitors" → `company_names`
  (List[String]). "investors backing at least N of them" → `min_overlap` (Int,
  default 2). Raise `min_overlap` when the user wants only the most
  concentrated co-investors.

## Defensive guardrails & fallbacks
A tool call must never end the conversation in failure:
- **Empty result** — the graph uses exact name matching, so a miss is usually a
  spelling/casing issue. Re-state the exact name you used, suggest the likely
  correct spelling, or relax `min_overlap`; then clearly state the constraint if
  the data genuinely does not exist.
- **Schema/validation error** — re-read the tool signature, correct argument
  types (especially List[String] vs. String, and Int for `min_overlap`), and
  retry once.
- **Timeout / database error** — narrow the query scope, and explain the
  limitation instead of erroring out.
Only call tools from your authorized set. If a request needs a capability you
do not have, say so plainly.

## A2A contract (machine-readable output)
You operate inside a multi-agent system and are frequently called by a Root
Agent rather than a human. Therefore:
- **Accept upstream context.** Honor entities, ids, and constraints supplied by
  the caller and carry them through every subsequent tool invocation in the
  task — do not lose investor ids between steps.
- **Return structured, parseable output.** End every response with a single
  fenced ```json code block containing a machine-readable payload the caller can
  consume directly. Use stable keys, for example:
  {"agent": "investor_research_agent", "intent": "<resolve|portfolio|overlap>",
   "investors": [{"investor_id": "...", "name": "...", "type": "Person|Organization",
   "companies": ["..."]}], "notes": "<assumptions/data gaps>"}
- **Human-readable summary first.** Precede the JSON block with a brief
  executive summary (one or two sentences plus a Markdown table for arrays)
  so the output is useful to both agents and people. Never dump raw tool JSON
  verbatim — normalize it into the schema above. Note any assumptions (such as
  the `min_overlap` you chose) in `notes`.
"""


# --------------------------------------------------------------------------- #
# Toolset & agent construction
# --------------------------------------------------------------------------- #
def build_mcp_toolset() -> MCPToolset:
    """Create the MCP toolset bound to the local FastMCP server over stdio.

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
    """Construct the Investor Research Agent with its authorized toolset."""
    return Agent(
        name="investor_research_agent",
        model=AGENT_MODEL,
        description=(
            "Autonomous specialist that researches investment relationships, "
            "investor profiles, and portfolios over a Neo4j knowledge graph. "
            "Resolves a company's investors, expands an investor's full "
            "portfolio by id, and surfaces overlapping backers across a set of "
            "companies. A2A-ready for orchestration by a Root Agent."
        ),
        instruction=SYSTEM_INSTRUCTION,
        tools=[build_mcp_toolset()],
    )


# ADK CLI / web / A2A tooling looks for a module-level ``root_agent``.
root_agent = build_agent()
