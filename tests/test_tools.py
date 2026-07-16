"""Tests for tools.py — deep researcher tools."""

from unittest.mock import MagicMock, patch

import pytest

import chunker
import run_memory
import tools


# --- tavily_search --------------------------------------------------------

def _fake_tavily_response(q):
    return {
        "answer": f"answer for {q}",
        "results": [
            {"title": f"T-{q}", "url": f"http://e.com/{q}", "content": "x" * 50}
        ],
    }


def test_tavily_search_single_query(monkeypatch):
    fake_client = MagicMock()
    fake_client.search.side_effect = lambda q, **kw: _fake_tavily_response(q)
    monkeypatch.setenv("TAVILY_API_KEY", "test")
    with patch("tavily.TavilyClient", return_value=fake_client):
        out = tools._tavily_search_impl(query="rust")
    assert "rust" in out and "http://e.com/rust" in out


def test_tavily_search_parallel_batch(monkeypatch):
    calls = []
    fake_client = MagicMock()

    def fake_search(q, **kw):
        calls.append(q)
        return _fake_tavily_response(q)

    fake_client.search.side_effect = fake_search
    monkeypatch.setenv("TAVILY_API_KEY", "test")
    with patch("tavily.TavilyClient", return_value=fake_client):
        out = tools._tavily_search_impl(queries=["a", "b", "c"])
    assert set(calls) == {"a", "b", "c"}
    assert "## Query: a" in out and "## Query: b" in out and "## Query: c" in out


def test_tavily_search_empty_input_returns_error():
    out = tools._tavily_search_impl()
    assert "Error" in out


# --- fetch_webpage_content ------------------------------------------------

def test_fetch_webpage_returns_markdown(monkeypatch):
    fake_resp = MagicMock(text="<h1>Hi</h1><p>body</p>")
    fake_resp.raise_for_status = lambda: None
    with patch("httpx.get", return_value=fake_resp):
        out = tools._fetch_webpage_impl(["http://x.com"])
    assert "Hi" in out and "http://x.com" in out


def test_fetch_webpage_handles_failure(monkeypatch):
    with patch("httpx.get", side_effect=RuntimeError("boom")):
        out = tools._fetch_webpage_impl("http://x.com")
    assert "fetch failed" in out


# --- submit_final_answer --------------------------------------------------

def test_submit_rejects_short_answer(tmp_path, monkeypatch):
    monkeypatch.setattr(tools.db_context, "wiki_dir", lambda: tmp_path)
    monkeypatch.setattr(tools, "MIN_WORDS", 100)
    monkeypatch.setattr(tools, "MIN_URLS", 2)
    out = tools._submit_final_impl("T", "too short http://a.com")
    assert out.startswith("REJECTED") and "words" in out


def test_submit_rejects_few_sources(tmp_path, monkeypatch):
    monkeypatch.setattr(tools.db_context, "wiki_dir", lambda: tmp_path)
    monkeypatch.setattr(tools, "MIN_WORDS", 3)
    monkeypatch.setattr(tools, "MIN_URLS", 3)
    out = tools._submit_final_impl("T", "one two three http://a.com")
    assert out.startswith("REJECTED") and "sources" in out


def test_submit_accepts_and_writes_file(tmp_path, monkeypatch):
    monkeypatch.setattr(tools.db_context, "wiki_dir", lambda: tmp_path)
    monkeypatch.setattr(tools, "MIN_WORDS", 3)
    monkeypatch.setattr(tools, "MIN_URLS", 2)
    out = tools._submit_final_impl(
        "My Report", "alpha beta gamma http://a.com http://b.com"
    )
    assert out.startswith("ACCEPTED")
    written = (tmp_path / "comparisons" / "report-my-report.md").read_text()
    assert "My Report" in written and "http://a.com" in written


def test_submit_accepts_wiki_citations_as_sources(tmp_path, monkeypatch):
    monkeypatch.setattr(tools.db_context, "wiki_dir", lambda: tmp_path)
    monkeypatch.setattr(tools, "MIN_WORDS", 3)
    monkeypatch.setattr(tools, "MIN_URLS", 2)
    out = tools._submit_final_impl(
        "Wiki Only", "alpha beta gamma [Wiki: siemens-ag.md] [Wiki: sap-se.md]"
    )
    assert out.startswith("ACCEPTED")
    written = (tmp_path / "comparisons" / "report-wiki-only.md").read_text()
    assert "wiki:siemens-ag.md" in written


def test_submit_accepts_file_source_citations(tmp_path, monkeypatch):
    monkeypatch.setattr(tools.db_context, "wiki_dir", lambda: tmp_path)
    monkeypatch.setattr(tools, "MIN_WORDS", 3)
    monkeypatch.setattr(tools, "MIN_URLS", 2)
    out = tools._submit_final_impl(
        "Legal", "alpha beta gamma [Source: StrlSchG.md § 78] [Source: StrlSchV.md § 33]"
    )
    assert out.startswith("ACCEPTED") and "2 source cites" in out
    written = (tmp_path / "comparisons" / "report-legal.md").read_text()
    assert "src:StrlSchG.md § 78" in written


def test_submit_does_not_double_count_url_source_citations(tmp_path, monkeypatch):
    monkeypatch.setattr(tools.db_context, "wiki_dir", lambda: tmp_path)
    monkeypatch.setattr(tools, "MIN_WORDS", 3)
    monkeypatch.setattr(tools, "MIN_URLS", 2)
    # A single [Source: <URL>.html] must count once (as a URL), not twice.
    out = tools._submit_final_impl("Once", "alpha beta gamma [Source: https://x.com/a.html]")
    assert out.startswith("REJECTED") and "1 unique source" in out


# --- wiki_search / wiki_read ---------------------------------------------


def test_wiki_search_returns_hits(monkeypatch):
    fake_hits = [
        {"filename": "siemens-ag.md", "title": "Siemens AG", "excerpt": "industrial..."},
        {"filename": "sap-se.md", "title": "SAP SE", "excerpt": "ERP..."},
    ]
    monkeypatch.setattr(tools.wiki_engine, "search_wiki", lambda q: fake_hits)
    out = tools._wiki_search_impl(query="german industrial")
    assert "siemens-ag.md" in out and "Siemens AG" in out and "industrial..." in out


def test_wiki_search_no_results(monkeypatch):
    monkeypatch.setattr(tools.wiki_engine, "search_wiki", lambda q: [])
    out = tools._wiki_search_impl(query="unknown")
    assert "(no results)" in out


def test_wiki_search_parallel_batch(monkeypatch):
    seen = []

    def fake(q):
        seen.append(q)
        return [{"filename": f"{q}.md", "title": q, "excerpt": ""}]

    monkeypatch.setattr(tools.wiki_engine, "search_wiki", fake)
    out = tools._wiki_search_impl(queries=["a", "b", "c"])
    assert set(seen) == {"a", "b", "c"}
    assert "a.md" in out and "b.md" in out and "c.md" in out


def test_wiki_search_appends_linked_pages(monkeypatch):
    monkeypatch.setattr(tools, "WIKI_LINK_EXPANSION", True)
    monkeypatch.setattr(
        tools.wiki_engine, "search_wiki",
        lambda q: [{"filename": "a.md", "title": "A", "excerpt": "hit"}],
    )
    captured = {}

    def fake_linked(seeds, limit):
        captured["seeds"] = seeds
        return [{"filename": "b.md", "title": "B", "excerpt": "nbr", "via": "a.md"}]

    monkeypatch.setattr(tools.wiki_engine, "linked_pages", fake_linked)
    out = tools._wiki_search_impl(query="x")
    assert captured["seeds"] == ["a.md"]
    assert "Wiki linked 1" in out and "b.md" in out and "related via a.md" in out


def test_wiki_search_link_expansion_skips_already_shown(monkeypatch):
    monkeypatch.setattr(tools, "WIKI_LINK_EXPANSION", True)
    monkeypatch.setattr(
        tools.wiki_engine, "search_wiki",
        lambda q: [{"filename": "a.md", "title": "A", "excerpt": "hit"}],
    )
    # linked_pages returns a page already present as a direct hit -> filtered out
    monkeypatch.setattr(
        tools.wiki_engine, "linked_pages",
        lambda seeds, limit: [{"filename": "a.md", "title": "A", "excerpt": "", "via": "a.md"}],
    )
    out = tools._wiki_search_impl(query="x")
    assert "Wiki linked" not in out


def test_wiki_search_link_expansion_disabled(monkeypatch):
    monkeypatch.setattr(tools, "WIKI_LINK_EXPANSION", False)
    monkeypatch.setattr(
        tools.wiki_engine, "search_wiki",
        lambda q: [{"filename": "a.md", "title": "A", "excerpt": "hit"}],
    )
    monkeypatch.setattr(
        tools.wiki_engine, "linked_pages",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("should not be called")),
    )
    out = tools._wiki_search_impl(query="x")
    assert "Wiki linked" not in out


def test_wiki_read_returns_body(monkeypatch):
    monkeypatch.setattr(tools.wiki_engine, "read_page", lambda f: f"BODY OF {f}")
    out = tools._wiki_read_impl(["siemens-ag.md"])
    assert "siemens-ag.md" in out and "BODY OF siemens-ag.md" in out


def test_wiki_read_empty_input():
    assert "Error" in tools._wiki_read_impl([])


def test_research_tools_include_raw_search_and_read():
    names = {getattr(t, "name", None) for t in tools.TOOLS}
    assert {"wiki_search", "raw_search", "raw_read"} <= names  # research can drill into raw docs


# --- raw_read section resolution ------------------------------------------


def _ingest_source(name: str, text: str):
    """Write a raw source + its chunks so section-aware raw_read can resolve."""
    (tools.db_context.raw_dir() / name).write_text(text, encoding="utf-8")
    chunker.write_chunks(name, chunker.split(text))


_LEGAL_DOC = (
    "# StrlSchG\n\n"
    "## § 61 Anfall und Lagerung\n"
    + "Regelungen zum Anfall ueberwachungsbeduerftiger Rueckstaende. " * 5 + "\n\n"
    "## § 62 Entlassung aus der Ueberwachung\n"
    + "Entlassung von Rueckstaenden aus der Ueberwachung erfolgt auf Antrag. " * 5 + "\n\n"
    "## § 63 Verbleibende Rueckstaende\n"
    + "In der Ueberwachung verbleibende Rueckstaende unterliegen Auflagen. " * 5 + "\n"
)

_MD_DOC = (
    "# Guide\n\n"
    "## Overview\n"
    + "This guide gives a broad overview of the monitoring process and scope. " * 4 + "\n\n"
    "## Release Procedure\n"
    + "The release procedure describes how items leave monitoring on request. " * 4 + "\n\n"
    "## Limits\n"
    + "Limits define the numeric thresholds applied during the assessment phase. " * 4 + "\n"
)


def test_raw_read_resolves_legal_section(wiki_dir):
    _ingest_source("StrlSchG.md", _LEGAL_DOC)
    out62 = tools._raw_read_one("StrlSchG.md § 62")
    out63 = tools._raw_read_one("StrlSchG.md § 63")
    assert "§ 62" in out62 and "Entlassung" in out62
    assert "§ 63" in out63 and "verbleibende" in out63
    assert out62 != out63  # distinct sections, not the same offset-0 window


def test_raw_read_resolves_markdown_heading(wiki_dir):
    _ingest_source("guide.md", _MD_DOC)
    out = tools._raw_read_one("guide.md ## Release Procedure")
    assert "Release Procedure" in out and "release procedure" in out
    assert "Overview" not in out.split("\n", 1)[1]  # not the wrong section body


def test_raw_read_section_memory_keys_distinct(wiki_dir):
    _ingest_source("StrlSchG.md", _LEGAL_DOC)
    run_memory.begin_run()
    a = tools.raw_read.invoke({"filenames": ["StrlSchG.md § 61"]})
    b = tools.raw_read.invoke({"filenames": ["StrlSchG.md § 62"]})
    assert "[memory] Already read" not in a
    assert "[memory] Already read" not in b  # different section is a fresh read
    again = tools.raw_read.invoke({"filenames": ["StrlSchG.md § 61"]})
    assert "[memory] Already read this section" in again
    # menu lists only sections not yet read this run (§61, §62 already read)
    assert "§ 63" in again and "§ 62" not in again


def test_raw_read_duplicate_offset_names_next_unread_window(wiki_dir):
    cap = tools.RAW_READ_CAP
    (tools.db_context.raw_dir() / "big.md").write_text("x" * (cap * 3), encoding="utf-8")
    run_memory.begin_run()
    first = tools.raw_read.invoke({"filenames": ["big.md"], "offset": 0})
    assert "[memory] Already read" not in first
    dup = tools.raw_read.invoke({"filenames": ["big.md"], "offset": 0})
    assert "[memory] Already read" in dup
    assert f"offset={cap}" in dup  # concrete next window, not generic advice


def test_raw_read_duplicate_offset_after_full_read_has_no_offset_hint(wiki_dir):
    cap = tools.RAW_READ_CAP
    (tools.db_context.raw_dir() / "small.md").write_text("y" * (cap // 2), encoding="utf-8")
    run_memory.begin_run()
    tools.raw_read.invoke({"filenames": ["small.md"], "offset": 0})  # whole file in one window
    dup = tools.raw_read.invoke({"filenames": ["small.md"], "offset": 0})
    assert "[memory] Already read" in dup
    assert "Whole file already read" in dup and "offset=" not in dup


def test_raw_read_nudges_submit_after_paginating(wiki_dir):
    cap = tools.RAW_READ_CAP
    (tools.db_context.raw_dir() / "big.md").write_text("z" * (cap * 4), encoding="utf-8")
    run_memory.begin_run()
    first = tools.raw_read.invoke({"filenames": ["big.md"], "offset": 0})
    assert "Stop paginating" not in first  # one window read, no nudge yet
    second = tools.raw_read.invoke({"filenames": ["big.md"], "offset": cap})
    assert "Stop paginating" in second  # RAW_READ_NUDGE_AFTER=2 windows reached
    assert "submit_chat_answer" in second


# --- think_tool -----------------------------------------------------------

def test_think_tool_passthrough():
    assert tools.TOOL_FUNCTIONS["think_tool"]("just thinking") == "just thinking"


# --- Deep chat: wiki access ------------------------------------------------

def test_chat_tools_expose_wiki_search_and_read():
    """Deep chat can navigate the wiki (and thus follow `related:` links)."""
    names = {t.name for t in tools.CHAT_TOOLS}
    assert {"wiki_search", "wiki_read"} <= names
    assert {"raw_search", "raw_read"} <= names  # still raw-grounded


def test_submit_chat_counts_wiki_citations(monkeypatch):
    monkeypatch.setattr(tools, "CHAT_MIN_WORDS", 5)
    monkeypatch.setattr(tools, "CHAT_MIN_SOURCES", 2)
    answer = "one two three four five [Source: raw.md] and [Wiki: page.md]"
    assert tools._submit_chat_impl(answer).startswith("ACCEPTED")


def test_submit_chat_wiki_cite_alone_does_not_meet_source_gate(monkeypatch):
    """Wiki pages orient the agent; grounding still needs a second source."""
    monkeypatch.setattr(tools, "CHAT_MIN_WORDS", 5)
    monkeypatch.setattr(tools, "CHAT_MIN_SOURCES", 2)
    answer = "one two three four five [Wiki: page.md]"
    assert tools._submit_chat_impl(answer).startswith("REJECTED")


def test_wiki_search_labels_shared_source_neighbours(monkeypatch):
    monkeypatch.setattr(tools, "WIKI_LINK_EXPANSION", True)
    monkeypatch.setattr(
        tools.wiki_engine, "search_wiki",
        lambda q: [{"filename": "a.md", "title": "A", "excerpt": "hit"}],
    )
    monkeypatch.setattr(
        tools.wiki_engine, "linked_pages",
        lambda seeds, limit: [{"filename": "b.md", "title": "B", "excerpt": "nbr",
                               "via": "a.md", "kind": "shared-source"}],
    )
    out = tools._wiki_search_impl(query="x")
    assert "shares a source with a.md" in out
