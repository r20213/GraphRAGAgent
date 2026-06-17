"""A2A surface for the Root Agent orchestrator."""

from __future__ import annotations

import os

from google.adk.a2a.utils.agent_to_a2a import to_a2a

from .agent import root_agent
from .config import ROOT_AGENT_HOST, ROOT_AGENT_PORT

A2A_HOST = os.environ.get("A2A_HOST", ROOT_AGENT_HOST)
A2A_PORT = int(
    os.environ.get("PORT", os.environ.get("A2A_PORT", str(ROOT_AGENT_PORT)))
)

a2a_app = to_a2a(root_agent, host=A2A_HOST, port=A2A_PORT)