"""Unit tests for unified FTS index initialization logic."""

from __future__ import annotations


def _result(rows):
    class _Result:
        def __init__(self, values):
            self._values = values

        def __iter__(self):
            return iter(self._values)

        def single(self):
            return self._values[0] if self._values else None

        def consume(self):
            return None

    return _Result(rows)


def test_should_include_fts_property_exact_targets_only(idx):
    assert idx._should_include_fts_property("Article", "title") is True
    assert idx._should_include_fts_property("Article", "author") is True
    assert idx._should_include_fts_property("Organization", "name") is True

    assert idx._should_include_fts_property("Article", "siteName") is False
    assert idx._should_include_fts_property("Organization", "motto") is False
    assert idx._should_include_fts_property("City", "id") is False
    assert idx._should_include_fts_property("Fewshot", "Question") is False


def test_initialize_global_fts_index_recreates_index_with_exact_targets(
    idx,
    monkeypatch,
    fake_driver_factory,
):
    executed = []

    schema = {
        "Article": {
            "title": "A headline",
            "author": "J. Doe",
            "siteName": "Should not be indexed",
            "id": "ART-1",
        },
        "Person": {"name": "Jane", "summary": "Should not be indexed"},
        "Organization": {"name": "Acme", "motto": "Do not include"},
        "City": {"name": "Seattle"},
        "Country": {"name": "United States"},
        "IndustryCategory": {"name": "Enterprise Software"},
        "Fewshot": {"Question": "Ignore this label"},
    }

    def run_handler(query, params):
        del params
        executed.append(query)

        if "CALL db.labels()" in query:
            labels = sorted(schema)
            return _result([{"label": label} for label in labels])

        if "UNWIND keys(n) AS property_key" in query:
            marker = "MATCH (n:`"
            start = query.index(marker) + len(marker)
            end = query.index("`)", start)
            label = query[start:end]
            props = schema[label]
            return _result(
                [
                    {"property_key": key, "sample": sample}
                    for key, sample in props.items()
                ]
            )

        if "DROP INDEX global_entity_search IF EXISTS" in query:
            return _result([])

        if "CREATE FULLTEXT INDEX global_entity_search" in query:
            return _result([])

        raise AssertionError(f"Unexpected query: {query}")

    driver = fake_driver_factory(run_handler)
    monkeypatch.setattr(idx, "get_driver", lambda: driver)

    summary = idx.initialize_global_fts_index()

    assert summary["created"] is True
    assert set(summary["labels"]) == {
        "Article",
        "City",
        "Country",
        "IndustryCategory",
        "Organization",
        "Person",
    }
    assert set(summary["properties"]) == {"author", "name", "title"}

    drop_calls = [q for q in executed if "DROP INDEX global_entity_search" in q]
    create_calls = [
        q for q in executed if "CREATE FULLTEXT INDEX global_entity_search" in q
    ]

    assert len(drop_calls) == 1
    assert len(create_calls) == 1

    create_query = create_calls[0]
    for label in {
        "Article",
        "City",
        "Country",
        "IndustryCategory",
        "Organization",
        "Person",
    }:
        assert f"`{label}`" in create_query
    assert "n.`author`" in create_query
    assert "n.`name`" in create_query
    assert "n.`title`" in create_query
    assert "n.`siteName`" not in create_query
    assert "n.`motto`" not in create_query


def test_initialize_global_fts_index_reports_missing_required_targets(
    idx,
    monkeypatch,
    fake_driver_factory,
):
    logs = []

    schema = {
        "Article": {"author": "Only author is present"},
        "Person": {"name": "Jane"},
        "Organization": {"name": "Acme"},
        "City": {"name": "Seattle"},
        "Country": {"name": "United States"},
        "IndustryCategory": {"name": "Enterprise Software"},
    }

    def run_handler(query, params):
        del params
        if "CALL db.labels()" in query:
            return _result([{"label": label} for label in sorted(schema)])

        if "UNWIND keys(n) AS property_key" in query:
            marker = "MATCH (n:`"
            start = query.index(marker) + len(marker)
            end = query.index("`)", start)
            label = query[start:end]
            props = schema[label]
            return _result(
                [
                    {"property_key": key, "sample": sample}
                    for key, sample in props.items()
                ]
            )

        if "DROP INDEX global_entity_search IF EXISTS" in query:
            return _result([])

        if "CREATE FULLTEXT INDEX global_entity_search" in query:
            return _result([])

        raise AssertionError(f"Unexpected query: {query}")

    driver = fake_driver_factory(run_handler)
    monkeypatch.setattr(idx, "get_driver", lambda: driver)
    monkeypatch.setattr(idx, "_stderr", lambda message: logs.append(message))

    summary = idx.initialize_global_fts_index()

    assert summary["created"] is True
    assert any("required FTS targets" in line for line in logs)
    assert any("Article" in line and "title" in line for line in logs)


def test_initialize_global_fts_index_returns_not_created_when_no_targets(
    idx,
    monkeypatch,
    fake_driver_factory,
):
    logs = []

    def run_handler(query, params):
        del params
        if "CALL db.labels()" in query:
            return _result([{"label": "Fewshot"}])

        if "UNWIND keys(n) AS property_key" in query:
            return _result([
                {"property_key": "Question", "sample": "ignored"},
            ])

        raise AssertionError(f"Unexpected query: {query}")

    driver = fake_driver_factory(run_handler)
    monkeypatch.setattr(idx, "get_driver", lambda: driver)
    monkeypatch.setattr(idx, "_stderr", lambda message: logs.append(message))

    summary = idx.initialize_global_fts_index()

    assert summary == {
        "index_name": "global_entity_search",
        "labels": [],
        "properties": [],
        "created": False,
    }
    assert any("no eligible labels/properties" in line for line in logs)
