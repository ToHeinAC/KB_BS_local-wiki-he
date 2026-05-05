"""Tests for tools.py — deep researcher tools."""

from unittest.mock import MagicMock, patch

import pytest

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
    monkeypatch.setattr(tools, "WIKI_DIR", tmp_path)
    monkeypatch.setattr(tools, "MIN_WORDS", 100)
    monkeypatch.setattr(tools, "MIN_URLS", 2)
    out = tools._submit_final_impl("T", "too short http://a.com")
    assert out.startswith("REJECTED") and "words" in out


def test_submit_rejects_few_urls(tmp_path, monkeypatch):
    monkeypatch.setattr(tools, "WIKI_DIR", tmp_path)
    monkeypatch.setattr(tools, "MIN_WORDS", 3)
    monkeypatch.setattr(tools, "MIN_URLS", 3)
    out = tools._submit_final_impl("T", "one two three http://a.com")
    assert out.startswith("REJECTED") and "URL" in out


def test_submit_accepts_and_writes_file(tmp_path, monkeypatch):
    monkeypatch.setattr(tools, "WIKI_DIR", tmp_path)
    monkeypatch.setattr(tools, "MIN_WORDS", 3)
    monkeypatch.setattr(tools, "MIN_URLS", 2)
    out = tools._submit_final_impl(
        "My Report", "alpha beta gamma http://a.com http://b.com"
    )
    assert out.startswith("ACCEPTED")
    written = (tmp_path / "comparisons" / "report-my-report.md").read_text()
    assert "My Report" in written and "http://a.com" in written


# --- think_tool -----------------------------------------------------------

def test_think_tool_passthrough():
    assert tools.TOOL_FUNCTIONS["think_tool"]("just thinking") == "just thinking"
