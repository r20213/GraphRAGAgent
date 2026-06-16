"""A2A (Agent-to-Agent) protocol surface for the Graph Database Agent.

Wraps :data:`graph_db_agent.agent.root_agent` in an A2A-compliant ASGI
application using ADK's :func:`to_a2a` helper. Serving this module with an ASGI
server (uvicorn) exposes:

* ``/.well-known/agent-card.json`` — the public Agent Card describing the
  agent's identity, skills, and JSON-RPC endpoint, used by A2A clients (the Root
  Orchestrator) for capability discovery.
* the A2A JSON-RPC endpoint that other agents call to create and stream tasks.

Run locally::

    uvicorn graph_db_agent.a2a:a2a_app --host 0.0.0.0 --port 8080

Everything is configured from the environment so the same module runs unchanged
on Cloud Run (which injects ``$PORT``).
"""

from __future__ import annotations

import os

from google.adk.a2a.utils.agent_to_a2a import to_a2a

from .agent import root_agent

# Host/port advertised in the generated Agent Card. On Cloud Run, $PORT is the
# container's listen port; the public HTTPS URL is set via PUBLIC_URL so the
# card points clients at the externally reachable endpoint.
A2A_HOST = os.environ.get("A2A_HOST", "0.0.0.0")
A2A_PORT = int(os.environ.get("PORT", os.environ.get("A2A_PORT", "8080")))

# Build the A2A ASGI application exposing the agent over the protocol.
a2a_app = to_a2a(root_agent, host=A2A_HOST, port=A2A_PORT)
