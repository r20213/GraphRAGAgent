"""GraphRAGAgent — Neo4j MCP server package.

Exposes the production MCP server and its core helpers so they can be imported
straight from the package (e.g. ``from mcp_server import mcp, main``).

Public symbols are resolved lazily via :pep:`562` ``__getattr__`` so that
importing the ``mcp_server`` package does not eagerly pull in the heavy
third-party ``mcp`` / ``neo4j`` / ``python-dotenv`` dependencies (or run the
server module's import-time side effects) until a symbol is actually accessed.
"""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING, Any

# Every public symbol lives in mcp_server.server.
_LAZY_EXPORTS = (
    "mcp",
    "main",
    "get_driver",
    "close_driver",
    "execute_read",
    "get_industries",
    "get_companies_in_industry",
    "get_articles_with_sentiment",
    "get_people_in_organizations",
    "find_investor_by_name",
    "find_investor_by_id",
    "get_neo4j_schema",
    "run_cypher_query",
)

__all__ = [
    "mcp",
    "main",
    "get_driver",
    "close_driver",
    "execute_read",
    "get_industries",
    "get_companies_in_industry",
    "get_articles_with_sentiment",
    "get_people_in_organizations",
    "find_investor_by_name",
    "find_investor_by_id",
    "get_neo4j_schema",
    "run_cypher_query",
]


def __getattr__(name: str) -> Any:
    """Lazily import a public symbol from ``mcp_server.server`` (PEP 562)."""
    if name not in _LAZY_EXPORTS:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module = importlib.import_module("mcp_server.server")
    attr = getattr(module, name)
    # Cache on the package so later accesses skip __getattr__ entirely.
    globals()[name] = attr
    return attr


def __dir__() -> list[str]:
    """Include lazily-exported names in ``dir(mcp_server)``."""
    return sorted(list(globals()) + __all__)


if TYPE_CHECKING:  # Static type-checkers / IDEs resolve the real symbols.
    from mcp_server.server import (
        close_driver as close_driver,
        execute_read as execute_read,
        find_investor_by_id as find_investor_by_id,
        find_investor_by_name as find_investor_by_name,
        get_articles_with_sentiment as get_articles_with_sentiment,
        get_companies_in_industry as get_companies_in_industry,
        get_driver as get_driver,
        get_industries as get_industries,
        get_neo4j_schema as get_neo4j_schema,
        get_people_in_organizations as get_people_in_organizations,
        main as main,
        mcp as mcp,
        run_cypher_query as run_cypher_query,
    )

