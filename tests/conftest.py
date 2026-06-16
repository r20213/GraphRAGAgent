"""Shared pytest fixtures for the GraphRAGAgent test suite.

The server is imported as a normal package (``from mcp_server import server``)
thanks to the package ``__init__.py`` files and the ``pythonpath = .`` setting
in ``pytest.ini`` — no ``sys.path`` / ``sys.modules`` manipulation required.

Tests stay isolated from any live database by monkeypatching
``server.get_driver`` with the :class:`FakeDriver` provided here.
"""

from __future__ import annotations

import pytest

from mcp_server import server as _server


@pytest.fixture()
def srv():
    """Return the imported MCP server module under test."""
    return _server


class FakeRecord:
    """Mimics a neo4j Record: ``.data()`` returns a plain dict."""

    def __init__(self, data: dict):
        self._data = data

    def data(self):
        return self._data


class FakeSession:
    """Context-manager session whose ``run`` yields the configured records."""

    def __init__(self, records):
        self._records = records
        self.run_calls = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def run(self, query, params=None):
        self.run_calls.append((query, params))
        return iter(self._records)


class FakeDriver:
    """Driver stub returning a pre-seeded :class:`FakeSession`."""

    def __init__(self, records):
        self._records = records
        self.session_kwargs = None

    def session(self, **kwargs):
        self.session_kwargs = kwargs
        return FakeSession(self._records)

    def close(self):
        pass

    def verify_connectivity(self):
        return True


@pytest.fixture()
def fake_driver_factory():
    """Factory that builds a FakeDriver from a list of record dicts."""

    def _make(record_dicts):
        return FakeDriver([FakeRecord(d) for d in record_dicts])

    return _make
