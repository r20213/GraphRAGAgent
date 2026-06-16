"""Investment Research Agent — core definition (Google ADK).

Wires a Gemini-powered :class:`google.adk.Agent` to the local FastMCP Neo4j
server (``mcp_server/server.py``) through an ADK :class:`MCPToolset`. The
toolset is attached *dynamically* at runtime: ADK launches the MCP server as a
stdio subprocess, performs tool discovery, and exposes only the authorized
subset of tools to the model.

Design notes
------------
* **Dynamic discovery, static authorization.** The server advertises more tools
  than this agent may touch. ``tool_filter`` enforces the authorization matrix.
* **Generalized reasoning.** The system instruction encodes a scalable
  ReAct / chain-of-thought policy rather than hardcoded query routines.
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
APP_NAME = os.environ.get("ADK_APP_NAME", "investment_research_app")
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
# ever sees it.
AUTHORIZED_TOOLS = [
    "get_industries",
    "get_companies_in_industry",
    "get_articles_with_sentiment",
    "get_people_in_organizations",
]


# --------------------------------------------------------------------------- #
# System instruction: generalized reason-before-action policy
# --------------------------------------------------------------------------- #
SYSTEM_INSTRUCTION = """\
You are the **Investment Research Agent**, an autonomous financial-intelligence
analyst operating over a corporate knowledge graph. You answer questions about
industries, companies, market sentiment, and corporate leadership by reasoning
step by step and calling graph tools — never by guessing.

## Reasoning framework (ReAct / Chain-of-Thought)
For every request, run an explicit iterative loop and do NOT hardcode routines:
1. **Analyze context** — restate the user goal and identify the entities,
   constraints, and the final shape of the answer.
2. **Decompose** — if the goal is multi-domain, nested, or broad, break it into
   ordered sub-tasks. Solve one sub-task at a time.
3. **Select the single best tool** for the current sub-task. Call exactly one
   tool, then stop and read its output before deciding anything else.
4. **Process output** — extract the entities/values you need for the next step.
5. **Decide** — determine whether more data is required. If yes, loop back to
   step 3 with the newly acquired constraints; if no, synthesize the answer.

## Logical data intersections (piping)
Treat tool outputs as inputs to later tools. Typical chains:
- Resolve an industry name with `get_industries`, then feed the chosen name to
  `get_companies_in_industry`.
- Collect the array of company names returned above and pass that *list*
  directly into `get_people_in_organizations(company_names=[...], role=...)`
  to batch-fetch leadership.
- Cross-reference companies against `get_articles_with_sentiment` to attach a
  market-sentiment signal to each entity.
Never re-ask the user for a value you can derive from a previous tool result.

## Graceful argument extraction
Translate natural-language qualifiers into the exact structured parameters each
tool schema expects:
- Sentiment qualifiers → `min_sentiment` floats: "positive"/"favorable" ⇒ 0.5,
  "highly positive"/"strongly positive" ⇒ 0.7, "overwhelmingly positive" ⇒ 0.9.
- Temporal qualifiers → `year` / `month` integers: "in 2023" ⇒ year=2023,
  "recent"/"latest" ⇒ the most recent plausible year, a named month ⇒ its
  number. Omit `year`/`month` when the user gives no time constraint.
- Leadership qualifiers → `role` strings: "CEO", "founder", "board member",
  "investor", etc. Use "any" when the user does not specify a role.

## Defensive guardrails & fallbacks
A tool call must never end the conversation in failure:
- **Empty result** — try an alternative path (e.g. re-list industries to fix a
  near-miss name, relax a sentiment threshold, or widen a date window), then
  clearly state the constraint if data genuinely does not exist.
- **Schema/validation error** — re-read the tool signature, correct the
  argument types (especially list vs. string and float vs. int), and retry once.
- **Timeout / database error** — narrow the query scope or fall back to a
  broader read, and explain the limitation to the user instead of erroring out.
Only call tools from your authorized set. If a request needs a capability you do
not have, say so plainly.

## Executive summary & formatting
Synthesize — never dump raw JSON. Present findings as an executive readout:
- Use **Markdown tables** for comparative arrays (companies, articles, metrics).
- Use **bulleted matrices** for relational data (e.g. company → executives).
- Lead with a one- or two-sentence headline insight, then the supporting detail.
- Note any data gaps or assumptions (e.g. thresholds you chose) at the end.
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
    """Construct the Investment Research Agent with its authorized toolset."""
    return Agent(
        name="investment_research_agent",
        model=AGENT_MODEL,
        description=(
            "Autonomous analyst that researches industries, companies, market "
            "sentiment, and corporate leadership over a Neo4j knowledge graph."
        ),
        instruction=SYSTEM_INSTRUCTION,
        tools=[build_mcp_toolset()],
    )


# ADK CLI / web / A2A tooling looks for a module-level ``root_agent``.
root_agent = build_agent()
