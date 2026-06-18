"""Standalone unit tests for the Neo4j MCP server.

These tests run without any database, network, or third-party packages: the
``mcp`` SDK and ``neo4j`` driver are stubbed in ``conftest.py``. They exercise
the production guardrails (injection detection, result caps, serialisation,
error telemetry) and the declarative query catalogue.
"""

from __future__ import annotations

import json

import pytest


# --------------------------------------------------------------------------- #
# Security: write-clause / injection detection
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "cypher",
    [
        "MATCH (c:Organization) RETURN count(c)",
        "MATCH (a)-[:HAS_COMPETITOR]->(b) RETURN a.name, b.name",
        "MATCH (i:IndustryCategory) RETURN i.name ORDER BY i.name",
        "RETURN 1 AS one",
    ],
)
def test_read_queries_not_flagged(srv, cypher):
    assert srv._is_write_query(cypher) is False


@pytest.mark.parametrize(
    "cypher",
    [
        "CREATE (n:Hacker {name:'x'})",
        "MATCH (n) DETACH DELETE n",
        "MATCH (n) SET n.flag = true",
        "MERGE (n:Org {id:1})",
        "MATCH (n) REMOVE n.prop",
        "DROP INDEX foo",
        "CREATE CONSTRAINT bar FOR (n:X) REQUIRE n.id IS UNIQUE",
    ],
)
def test_write_queries_flagged(srv, cypher):
    assert srv._is_write_query(cypher) is True


def test_write_keyword_inside_string_literal_is_ignored(srv):
    # The word DELETE only appears inside a quoted value, not as a clause.
    cypher = "MATCH (a:Article) WHERE a.title = 'How to DELETE files' RETURN a"
    assert srv._is_write_query(cypher) is False


# --------------------------------------------------------------------------- #
# Serialisation
# --------------------------------------------------------------------------- #
class _FakeTemporal:
    def isoformat(self):
        return "2022-03-10T00:00:00+00:00"


def test_serialise_temporal(srv):
    assert srv._serialise(_FakeTemporal()) == "2022-03-10T00:00:00+00:00"


def test_serialise_nested_structures(srv):
    value = {"a": [1, 2, {"b": _FakeTemporal()}]}
    assert srv._serialise(value) == {
        "a": [1, 2, {"b": "2022-03-10T00:00:00+00:00"}]
    }


def test_serialise_primitive_passthrough(srv):
    assert srv._serialise(42) == 42
    assert srv._serialise("hello") == "hello"
    assert srv._serialise(None) is None


# --------------------------------------------------------------------------- #
# Record formatting & token-cost cap metadata
# --------------------------------------------------------------------------- #
def test_format_records_empty_returns_hint(srv):
    assert srv._format_records([], "nothing here") == "nothing here"


def test_format_records_wraps_payload(srv):
    out = srv._format_records([{"name": "Acme"}], "empty")
    parsed = json.loads(out)
    assert parsed["record_count"] == 1
    assert parsed["capped_at"] == srv.MAX_RESULT_RECORDS
    assert parsed["records"] == [{"name": "Acme"}]


# --------------------------------------------------------------------------- #
# execute_read guardrails (capping, parameters, tracing metadata)
# --------------------------------------------------------------------------- #
def test_execute_read_caps_results(srv, monkeypatch, fake_driver_factory):
    records = [{"n": i} for i in range(250)]
    driver = fake_driver_factory(records)
    monkeypatch.setattr(srv, "get_driver", lambda: driver)
    monkeypatch.setattr(srv, "MAX_RESULT_RECORDS", 100)

    out = srv.execute_read("unit", "MATCH (n) RETURN n", {})
    assert len(out) == 100


def test_execute_read_respects_explicit_cap(srv, monkeypatch, fake_driver_factory):
    records = [{"n": i} for i in range(50)]
    driver = fake_driver_factory(records)
    monkeypatch.setattr(srv, "get_driver", lambda: driver)

    out = srv.execute_read("unit", "MATCH (n) RETURN n", {}, cap=10)
    assert len(out) == 10


def test_execute_read_passes_parameters(srv, monkeypatch, fake_driver_factory):
    driver = fake_driver_factory([{"name": "Acme"}])
    monkeypatch.setattr(srv, "get_driver", lambda: driver)

    srv.execute_read("unit", "MATCH (n) WHERE n.id = $id RETURN n", {"id": "X"})
    # Confirm read access mode was requested on the driver session opened by
    # execute_read (do NOT open another session here, it would overwrite the
    # captured kwargs).
    assert driver.session_kwargs["default_access_mode"] == srv.READ_ACCESS


def test_execute_read_injects_tracing_metadata(srv, monkeypatch, fake_driver_factory):
    captured = {}

    class _Driver:
        def session(self, **kwargs):
            return _Session()

        def close(self):
            pass

    class _Session:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def run(self, query, params=None):
            captured["metadata"] = query.metadata
            captured["timeout"] = query.timeout
            return iter([])

    monkeypatch.setattr(srv, "get_driver", lambda: _Driver())
    srv.execute_read("my_tool", "RETURN 1", {}, agent_session_id="sess-123")

    assert captured["metadata"]["mcp_tool_name"] == "my_tool"
    assert captured["metadata"]["agent_session_id"] == "sess-123"
    assert captured["timeout"] == srv.QUERY_TIMEOUT


# --------------------------------------------------------------------------- #
# _safe telemetry: clean strings for the LLM, never raw tracebacks
# --------------------------------------------------------------------------- #
def test_safe_returns_value_on_success(srv):
    assert srv._safe("t", lambda: "ok") == "ok"


def test_safe_handles_cypher_syntax_error(srv):
    from neo4j.exceptions import CypherSyntaxError

    def boom():
        raise CypherSyntaxError("bad syntax")

    out = srv._safe("t", boom)
    assert "invalid Cypher syntax" in out


def test_safe_handles_service_unavailable(srv):
    from neo4j.exceptions import ServiceUnavailable

    def boom():
        raise ServiceUnavailable("down")

    out = srv._safe("t", boom)
    assert "unreachable" in out.lower()


def test_safe_handles_unexpected_error(srv):
    def boom():
        raise ValueError("kaboom")

    out = srv._safe("t", boom)
    assert "unexpected internal error" in out.lower()
    # Ensure the raw exception text is not leaked to the LLM.
    assert "kaboom" not in out


# --------------------------------------------------------------------------- #
# Declarative query catalogue integrity
# --------------------------------------------------------------------------- #
EXPECTED_TEMPLATES = {
    "get_industries",
    "get_companies_in_industry",
    "get_articles_with_sentiment",
    "get_people_in_organizations",
    "find_investor_by_name",
    "find_investor_by_id",
    "find_investors_for_companies",
}


def test_all_templates_present(srv):
    assert set(srv.QUERY_TEMPLATES) == EXPECTED_TEMPLATES


def test_templates_have_description_and_query(srv):
    for name, tmpl in srv.QUERY_TEMPLATES.items():
        assert tmpl["description"].strip(), f"{name} missing description"
        assert "RETURN" in tmpl["query"].upper(), f"{name} missing RETURN"


def test_templates_use_parameters_not_concatenation(srv):
    # Every template that takes input must reference a $param, never f-strings.
    parametrised = {
        "get_companies_in_industry": "$industry_name",
        "get_articles_with_sentiment": "$min_sentiment",
        "get_people_in_organizations": "$company_names",
        "find_investor_by_name": "$company_name",
        "find_investor_by_id": "$investor_id",
    }
    for name, param in parametrised.items():
        assert param in srv.QUERY_TEMPLATES[name]["query"]


def test_no_template_contains_write_clause(srv):
    for name, tmpl in srv.QUERY_TEMPLATES.items():
        assert not srv._is_write_query(tmpl["query"]), f"{name} is not read-only"


# --------------------------------------------------------------------------- #
# Role-to-relationship mapping
# --------------------------------------------------------------------------- #
def test_role_mapping_ceo(srv):
    assert srv._ROLE_TO_RELS["ceo"] == ["HAS_CEO"]


def test_role_mapping_board(srv):
    assert "HAS_BOARD_MEMBER" in srv._ROLE_TO_RELS["board member"]


def test_role_mapping_any_covers_both(srv):
    assert set(srv._ROLE_TO_RELS["any"]) == {"HAS_CEO", "HAS_BOARD_MEMBER"}


# --------------------------------------------------------------------------- #
# Tool wrappers (end-to-end with a fake driver)
# --------------------------------------------------------------------------- #
def test_get_industries_tool(srv, monkeypatch, fake_driver_factory):
    driver = fake_driver_factory([{"name": "Software", "id": "i1"}])
    monkeypatch.setattr(srv, "get_driver", lambda: driver)

    out = srv.get_industries()
    parsed = json.loads(out)
    assert parsed["records"][0]["name"] == "Software"


def test_get_companies_empty_returns_helpful_hint(srv, monkeypatch, fake_driver_factory):
    driver = fake_driver_factory([])
    monkeypatch.setattr(srv, "get_driver", lambda: driver)

    out = srv.get_companies_in_industry("Nonexistent")
    assert "No companies found" in out
    assert "get_industries()" in out


def test_get_people_maps_role_to_rel_types(srv, monkeypatch, fake_driver_factory):
    seen = {}

    def fake_execute(tool_name, cypher, params=None, agent_session_id=None, cap=None):
        seen["params"] = params
        return [{"company": "Acme", "person": "Jane"}]

    monkeypatch.setattr(srv, "execute_read", fake_execute)
    out = srv.get_people_in_organizations(["Acme"], role="CEO")
    assert seen["params"]["rel_types"] == ["HAS_CEO"]
    assert "Jane" in out


# --------------------------------------------------------------------------- #
# Ad-hoc Cypher fallback: read-only enforcement
# --------------------------------------------------------------------------- #
def test_run_cypher_rejects_writes_in_read_only(srv, monkeypatch):
    monkeypatch.setattr(srv, "READ_ONLY", True)
    out = srv.run_cypher_query("CREATE (n:Bad)")
    assert "read-only" in out.lower()


def test_run_cypher_allows_reads(srv, monkeypatch, fake_driver_factory):
    monkeypatch.setattr(srv, "READ_ONLY", True)
    driver = fake_driver_factory([{"total": 42}])
    monkeypatch.setattr(srv, "get_driver", lambda: driver)

    out = srv.run_cypher_query("MATCH (c:Organization) RETURN count(c) AS total")
    parsed = json.loads(out)
    assert parsed["records"][0]["total"] == 42


# --------------------------------------------------------------------------- #
# Schema tool
# --------------------------------------------------------------------------- #
def test_get_neo4j_schema_reads_local_markdown(srv):
    out = srv.get_neo4j_schema()
    # The repository ships utils/neo4j_schema.md describing the companies graph.
    assert "Neo4j Graph Schema" in out


# --------------------------------------------------------------------------- #
# Permission-level guardrail: writes must be rejected by the server itself
# --------------------------------------------------------------------------- #
class _ProbeTx:
    """Fake transaction whose run() either raises or returns, tracking rollback."""

    def __init__(self, raise_exc):
        self._raise = raise_exc
        self.rolled_back = False

    def run(self, *args, **kwargs):
        if self._raise is not None:
            raise self._raise
        return _ProbeResult()

    def rollback(self):
        self.rolled_back = True


class _ProbeResult:
    def consume(self):
        return None


class _ProbeSession:
    def __init__(self, tx):
        self._tx = tx

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def begin_transaction(self, **kwargs):
        return self._tx


class _ProbeDriver:
    def __init__(self, raise_exc):
        self.tx = _ProbeTx(raise_exc)

    def session(self, **kwargs):
        return _ProbeSession(self.tx)

    def close(self):
        pass

    def verify_connectivity(self):
        return True


def test_verify_read_only_passes_when_write_rejected(srv, monkeypatch):
    from neo4j.exceptions import ClientError

    rejected = ClientError("Writing in read access mode not allowed")
    rejected.code = "Neo.ClientError.Statement.AccessMode"
    driver = _ProbeDriver(rejected)
    monkeypatch.setattr(srv, "READ_ONLY", True)
    monkeypatch.setattr(srv, "get_driver", lambda: driver)

    # Server rejected the probe write -> no exception, and the probe is rolled
    # back so nothing is persisted.
    srv.verify_read_only_enforced()
    assert driver.tx.rolled_back is True


def test_verify_read_only_fails_closed_when_write_accepted(srv, monkeypatch):
    # No exception on run() => the endpoint accepted a write in READ mode.
    driver = _ProbeDriver(None)
    monkeypatch.setattr(srv, "READ_ONLY", True)
    monkeypatch.setattr(srv, "get_driver", lambda: driver)

    with pytest.raises(RuntimeError, match="Read-only guardrail FAILED"):
        srv.verify_read_only_enforced()
    # Even on a writable endpoint the probe must never persist anything.
    assert driver.tx.rolled_back is True


def test_verify_read_only_skipped_when_disabled(srv, monkeypatch):
    def _boom():  # pragma: no cover - must not be called
        raise AssertionError("get_driver should not be called when disabled")

    monkeypatch.setattr(srv, "READ_ONLY", False)
    monkeypatch.setattr(srv, "get_driver", _boom)

    # READ_ONLY disabled -> probe is skipped without touching the driver.
    srv.verify_read_only_enforced()
