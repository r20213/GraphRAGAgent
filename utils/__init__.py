"""Utility helpers for the GraphRAGAgent project.

Provides Neo4j schema extraction (see :mod:`utils.eda`).

Public functions are exposed lazily via :pep:`562` ``__getattr__`` so that
``from utils import get_neo4j_schema_markdown`` works without importing the
heavy ``neo4j`` / ``python-dotenv`` dependencies until the symbol is actually
accessed.
"""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING, Any

# Map of public attribute name -> defining submodule.
_LAZY_EXPORTS = {
    "get_neo4j_schema_markdown": "utils.eda",
}

__all__ = ["get_neo4j_schema_markdown"]


def __getattr__(name: str) -> Any:
    """Lazily import and return a public symbol on first access (PEP 562)."""
    module_path = _LAZY_EXPORTS.get(name)
    if module_path is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module = importlib.import_module(module_path)
    attr = getattr(module, name)
    # Cache on the package so subsequent accesses skip __getattr__ entirely.
    globals()[name] = attr
    return attr


def __dir__() -> list[str]:
    """Include lazily-exported names in ``dir(utils)`` for discoverability."""
    return sorted(list(globals()) + __all__)


if TYPE_CHECKING:  # Static type-checkers / IDEs see the real symbol.
    from utils.eda import get_neo4j_schema_markdown as get_neo4j_schema_markdown

