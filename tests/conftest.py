"""Shared fixtures for schema indexing tests."""

from __future__ import annotations

import pytest

from utils import schema_indexing as _schema_indexing


@pytest.fixture()
def idx(monkeypatch):
    """Return the schema_indexing module with clean singleton state."""
    monkeypatch.setattr(_schema_indexing, "_driver", None)
    return _schema_indexing


class FakeRecord:
    """Dictionary-like record supporting [] access."""

    def __init__(self, data: dict):
        self._data = data

    def data(self):
        return self._data


class FakeSession:
    """Context-manager session with configurable run handler."""

    def __init__(self, run_handler):
        self._run_handler = run_handler
        self.run_calls = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def run(self, query, params=None):
        self.run_calls.append((query, params))
        return self._run_handler(query, params or {})


class FakeDriver:
    """Driver stub returning a session with a custom run handler."""

    def __init__(self, run_handler):
        self._run_handler = run_handler
        self.session_kwargs = None
        self.closed = False

    def session(self, **kwargs):
        self.session_kwargs = kwargs
        return FakeSession(self._run_handler)

    def close(self):
        self.closed = True

    def verify_connectivity(self):
        return True


@pytest.fixture()
def fake_driver_factory():
    """Factory that builds a FakeDriver from a run-handler callback."""

    def _make(run_handler):
        return FakeDriver(run_handler)

    return _make
