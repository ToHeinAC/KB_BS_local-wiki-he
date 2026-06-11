"""Tests for schema_loader.py — full vs. query system-prompt variants."""

import schema_loader


def test_full_mode_is_default():
    assert schema_loader.get_system_prompt() == schema_loader.get_system_prompt("full")


def test_query_mode_is_shorter_than_full():
    full = schema_loader.get_system_prompt("full")
    query = schema_loader.get_system_prompt("query")
    assert len(query) < len(full)


def test_query_mode_drops_page_templates():
    query = schema_loader.get_system_prompt("query")
    # The trimmed variant must omit the ingest-only template sections.
    assert "Page Types" not in query
    assert "Required Frontmatter" not in query


def test_query_mode_keeps_confidence_rules():
    query = schema_loader.get_system_prompt("query")
    assert "Confidence" in query


def test_query_mode_falls_back_to_full_when_file_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(schema_loader, "_SCHEMA_QUERY_PATH", tmp_path / "missing.md")
    assert schema_loader.get_system_prompt("query") == schema_loader.get_system_prompt("full")
