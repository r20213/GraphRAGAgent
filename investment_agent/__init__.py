"""Investment Research Agent package.

Exposes the module-level ``root_agent`` that the ADK runtime (CLI, web UI, and
A2A server) discovers automatically.
"""

from .agent import root_agent

__all__ = ["root_agent"]
