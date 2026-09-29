"""Writes of derived content: high-water mark, provenance, no web with classified scope."""

import frontmatter
import pytest

import agent
import db_context
import deep_research_agent
import tools
import wiki_engine

DB = "KI"


@pytest.fixture
def levels(tmp_path, monkeypatch):
    monkeypatch.setattr(db_context, "DATA_ROOT", tmp_path)
    db_context.set_active_db(DB)
    with db_context.clearance({DB: 2}):
        for shard in (DB, f"{DB}@strict"):
            db_context.ensure_shard(shard)
            with db_context.using_db(shard):
                wiki_engine.init_wiki()
    yield tmp_path
    db_context.set_search_scope([])


def _scope(level: int, shards: list[str]):
    ctx = db_context.clearance({DB: level})
    ctx.__enter__()
    db_context.set_search_scope(shards)
    return ctx


def _reports(root, shard_dir: str) -> list[str]:
    return sorted(p.name for p in (root / shard_dir / "wiki" / "comparisons").glob("*.md"))


def test_a_report_drawing_on_strict_is_saved_at_strict(levels, monkeypatch):
    monkeypatch.setattr(tools, "MIN_WORDS", 1)
    monkeypatch.setattr(tools, "MIN_URLS", 0)
    ctx = _scope(2, [DB, f"{DB}@strict"])
    try:
        assert tools._submit_final_impl("Bunker", "Plan [Source: x.md]").startswith("ACCEPTED")
    finally:
        ctx.__exit__(None, None, None)
    assert _reports(levels, "KI/_levels/strict") == ["report-bunker.md"]
    assert _reports(levels, "KI") == []


def test_a_normal_only_report_stays_normal(levels, monkeypatch):
    monkeypatch.setattr(tools, "MIN_WORDS", 1)
    monkeypatch.setattr(tools, "MIN_URLS", 0)
    tools._submit_final_impl("Bunker", "Plan")
    assert _reports(levels, "KI") == ["report-bunker.md"]


def test_deep_research_reports_follow_the_high_water_mark(levels):
    ctx = _scope(2, [DB, f"{DB}@strict"])
    try:
        assert deep_research_agent._save_report("Bunker?", "Text", []) is not None
    finally:
        ctx.__exit__(None, None, None)
    assert _reports(levels, "KI/_levels/strict") == ["report-bunker.md"]


def test_filed_answers_record_what_they_were_derived_from(levels):
    rel = wiki_engine.file_answer("Why?", "Because.", [], derived_from=["a.md", "KI::p.md"])
    meta = frontmatter.load(str(levels / "KI" / "wiki" / rel)).metadata
    assert meta["derived_from"] == ["a.md", "KI::p.md"]


def _tool_names() -> set[str]:
    return {t.name for t in agent._bound_tools()}


def test_web_tools_are_unbound_while_a_classified_level_is_in_scope(levels):
    assert {"tavily_search", "fetch_webpage_content"} <= _tool_names()
    ctx = _scope(2, [DB, f"{DB}@strict"])
    try:
        assert not {"tavily_search", "fetch_webpage_content"} & _tool_names()
        assert "Web search is off" in agent._system_prompt("")
    finally:
        ctx.__exit__(None, None, None)


def test_web_tools_refuse_even_when_called_directly_with_a_classified_scope(levels, monkeypatch):
    monkeypatch.setattr(tools, "_tavily_one", lambda *_a, **_k: "WEB CALLED")
    monkeypatch.setattr(tools, "_fetch_one", lambda *_a, **_k: "WEB CALLED")
    ctx = _scope(2, [DB, f"{DB}@strict"])
    try:
        assert "WEB CALLED" not in tools._tavily_search_impl(query="bunker plan")
        assert "WEB CALLED" not in tools._fetch_webpage_impl(["https://example.org"])
    finally:
        ctx.__exit__(None, None, None)


def test_deep_research_refuses_a_classified_scope(levels, monkeypatch):
    monkeypatch.setenv("TAVILY_API_KEY", "test")
    monkeypatch.setattr(deep_research_agent, "_run_graph", lambda *_a: iter([{"type": "x"}]))
    ctx = _scope(2, [DB, f"{DB}@strict"])
    try:
        steps = list(deep_research_agent.run_deep_research("q"))
    finally:
        ctx.__exit__(None, None, None)
    assert [s["type"] for s in steps] == ["error"]
