"""Graph Database Agent package.

Exposes the module-level ``root_agent`` that the ADK runtime (CLI, web UI, and
A2A server) discovers automatically. This agent is the ecosystem's dynamic
fallback: a natural-language interface that grounds Cypher generation on the
live Neo4j schema and executes read-only traversals via the shared MCP server.
"""

from .agent import root_agent

__all__ = ["root_agent"]
