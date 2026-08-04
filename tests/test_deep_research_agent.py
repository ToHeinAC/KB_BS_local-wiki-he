"""Tests for deep_research_agent.py — the vendored open_deep_research adapter.

The vendored graph is never actually run here: `_astream_sync` is the seam, and
it is replaced with scripted `(node, state_delta)` events. What is under test is
our adapter — event → step-dict mapping, citation extraction, report
persistence, and the fall-back-to-Quick contract.
"""

import pytest
from langchain_core.messages import AIMessage, ToolMessage

import deep_research_agent as dra


TAVILY_RESULT = """Search results: \n
--- SOURCE 1: Reactor Safety Update ---
URL: https://example.org/a

SUMMARY:
first summary


--- SOURCE 2: Second Page ---
URL: https://example.org/b

SUMMARY:
second summary
"""


@pytest.fixture(autouse=True)
def _tavily_key(monkeypatch):
    monkeypatch.setenv("TAVILY_API_KEY", "tvly-test")


def _script(monkeypatch, events):
    """Replace the async bridge with a scripted (node, delta) sequence."""
    monkeypatch.setattr(dra, "_astream_sync", lambda q, d: iter(events))


def _report_event(text="## Findings\n\nBody [1](https://example.org/a)"):
    return ("final_report_generation", {"final_report": text})


# --- citation extraction ---------------------------------------------------

def test_extract_sources_parses_url_and_title():
    got = dra._extract_sources(TAVILY_RESULT)
    assert got == [
        {"title": "Reactor Safety Update", "url": "https://example.org/a"},
        {"title": "Second Page", "url": "https://example.org/b"},
    ]


def test_extract_sources_empty_on_unrelated_text():
    assert dra._extract_sources("no sources here") == []
    assert dra._extract_sources("") == []


# --- event → step-dict mapping --------------------------------------------

def test_research_brief_becomes_a_thought(monkeypatch, wiki_dir):
    _script(monkeypatch, [
        ("write_research_brief", {"research_brief": "Investigate X thoroughly"}),
        _report_event(),
    ])
    steps = list(dra.run_deep_research("what about X?"))
    assert any(s["type"] == "thought" and "Investigate X thoroughly" in s["content"]
               for s in steps)


def test_tool_call_and_tool_result_are_emitted(monkeypatch, wiki_dir):
    ai = AIMessage(content="", tool_calls=[
        {"name": "ConductResearch", "args": {"research_topic": "X"}, "id": "1",
         "type": "tool_call"}])
    tm = ToolMessage(content=TAVILY_RESULT, name="web_search", tool_call_id="1")
    _script(monkeypatch, [
        ("supervisor", {"supervisor_messages": [ai]}),
        ("researcher_tools", {"researcher_messages": [tm]}),
        _report_event(),
    ])
    steps = list(dra.run_deep_research("q?"))
    calls = [s for s in steps if s["type"] == "tool_call"]
    results = [s for s in steps if s["type"] == "tool_result"]
    assert calls[0]["name"] == "ConductResearch"
    assert calls[0]["args"] == {"research_topic": "X"}
    assert results[0]["name"] == "web_search"
    assert [s["url"] for s in results[0]["sources"]] == [
        "https://example.org/a", "https://example.org/b"]


def test_sources_come_from_raw_notes(monkeypatch, wiki_dir):
    """The researcher subgraphs run via `ainvoke` and never stream their own
    web_search messages — `raw_notes` is the only path the URLs arrive on."""
    _script(monkeypatch, [
        ("research_supervisor", {"raw_notes": [TAVILY_RESULT]}),
        _report_event(),
    ])
    steps = list(dra.run_deep_research("q?"))
    results = [s for s in steps if s["type"] == "tool_result"]
    assert results and results[0]["name"] == "web_search"
    assert [s["url"] for s in results[0]["sources"]] == [
        "https://example.org/a", "https://example.org/b"]
    assert [s["url"] for s in steps[-1]["sources"]] == [
        "https://example.org/a", "https://example.org/b"]


def test_raw_notes_without_urls_emit_no_step(monkeypatch, wiki_dir):
    _script(monkeypatch, [
        ("research_supervisor", {"raw_notes": ["just prose, no sources"]}),
        _report_event(),
    ])
    steps = list(dra.run_deep_research("q?"))
    assert not [s for s in steps if s["type"] == "tool_result"]


def test_replayed_parent_updates_are_not_emitted_twice(monkeypatch, wiki_dir):
    """`research_supervisor` re-emits the supervisor messages its subgraph
    already streamed; each step must still reach the UI exactly once."""
    ai = AIMessage(content="", tool_calls=[
        {"name": "ConductResearch", "args": {"research_topic": "X"}, "id": "1",
         "type": "tool_call"}])
    _script(monkeypatch, [
        ("write_research_brief", {"research_brief": "brief text"}),
        ("supervisor", {"supervisor_messages": [ai]}),
        # the parent node echoing the whole accumulated sub-state
        ("research_supervisor", {"research_brief": "brief text",
                                 "supervisor_messages": [ai]}),
        _report_event(),
    ])
    steps = list(dra.run_deep_research("q?"))
    assert len([s for s in steps if s["type"] == "tool_call"]) == 1
    assert len([s for s in steps if s["type"] == "thought"
                and "brief text" in s["content"]]) == 1


def test_compressed_findings_are_not_shown_twice(monkeypatch, wiki_dir):
    """`supervisor_tools` re-wraps each researcher's `compressed_research` in a
    ConductResearch ToolMessage, so the same text arrives as both a thought and
    a tool result. The trace must show it once."""
    findings = "Sub-topic findings text that is identical in both places."
    tm = ToolMessage(content=findings, name="ConductResearch", tool_call_id="1")
    _script(monkeypatch, [
        ("compress_research", {"compressed_research": findings}),
        ("supervisor", {"supervisor_messages": [tm]}),
        _report_event(),
    ])
    steps = list(dra.run_deep_research("q?"))
    bodies = [s for s in steps if findings in (s.get("content") or s.get("result") or "")]
    assert len(bodies) == 1
    assert bodies[0]["type"] == "thought"


def test_final_report_node_messages_are_not_echoed_as_a_thought(monkeypatch, wiki_dir):
    report = "## The whole report body"
    _script(monkeypatch, [
        ("final_report_generation",
         {"final_report": report, "messages": [AIMessage(content=report)]}),
    ])
    steps = list(dra.run_deep_research("q?"))
    assert [s["type"] for s in steps] == ["final_answer"]
    assert steps[0]["content"] == report


def test_compressed_research_becomes_a_thought(monkeypatch, wiki_dir):
    _script(monkeypatch, [
        ("compress_research", {"compressed_research": "sub-topic notes"}),
        _report_event(),
    ])
    steps = list(dra.run_deep_research("q?"))
    assert any(s["type"] == "thought" and "sub-topic notes" in s["content"] for s in steps)


# --- final answer + persistence -------------------------------------------

def test_final_answer_carries_report_and_saved_path(monkeypatch, wiki_dir):
    tm = ToolMessage(content=TAVILY_RESULT, name="web_search", tool_call_id="1")
    _script(monkeypatch, [
        ("researcher_tools", {"researcher_messages": [tm]}),
        _report_event("## Findings\n\nBody text."),
    ])
    steps = list(dra.run_deep_research("Reactor safety in 2026"))
    final = steps[-1]
    assert final["type"] == "final_answer"
    assert final["content"] == "## Findings\n\nBody text."
    assert final["report_path"].startswith("comparisons/report-")
    saved = wiki_dir / final["report_path"].split("comparisons/")[-1]
    assert (wiki_dir / "comparisons" / saved.name).exists()
    body = (wiki_dir / "comparisons" / saved.name).read_text()
    assert "Body text." in body
    assert "https://example.org/a" in body


def test_final_answer_sources_are_deduped_by_url(monkeypatch, wiki_dir):
    tm = ToolMessage(content=TAVILY_RESULT, name="web_search", tool_call_id="1")
    _script(monkeypatch, [
        ("researcher_tools", {"researcher_messages": [tm]}),
        ("researcher_tools", {"researcher_messages": [tm]}),  # same hits again
        _report_event(),
    ])
    final = list(dra.run_deep_research("q?"))[-1]
    assert [s["url"] for s in final["sources"]] == [
        "https://example.org/a", "https://example.org/b"]


# --- ResearchComplete: zero-field sentinel, no result ----------------------

def test_research_complete_is_marked_terminal_and_explained(monkeypatch, wiki_dir):
    """It is a pydantic model with no fields, so `args` is legitimately `{}` and
    `supervisor_tools` returns no ToolMessage for it. The UI needs to know that
    so it doesn't render a bare `— {}` as if the call had failed."""
    ai = AIMessage(content="", tool_calls=[
        {"name": "ResearchComplete", "args": {}, "id": "1", "type": "tool_call"}])
    _script(monkeypatch, [("supervisor", {"supervisor_messages": [ai]}), _report_event()])
    call = [s for s in dra.run_deep_research("q?") if s["type"] == "tool_call"][0]
    assert call["args"] == {}
    assert call["terminal"] is True
    assert "no arguments and no result" in call["note"]


def test_non_terminal_tool_calls_carry_a_note_but_are_not_terminal(monkeypatch, wiki_dir):
    ai = AIMessage(content="", tool_calls=[
        {"name": "ConductResearch", "args": {"research_topic": "X"}, "id": "1",
         "type": "tool_call"}])
    _script(monkeypatch, [("supervisor", {"supervisor_messages": [ai]}), _report_event()])
    call = [s for s in dra.run_deep_research("q?") if s["type"] == "tool_call"][0]
    assert call["terminal"] is False
    assert "sub-topic" in call["note"]


# --- trace labels + metrics ------------------------------------------------

def test_thoughts_carry_labels_for_the_trace_expanders(monkeypatch, wiki_dir):
    _script(monkeypatch, [
        ("write_research_brief", {"research_brief": "b"}),
        ("compress_research", {"compressed_research": "c"}),
        ("supervisor", {"supervisor_messages": [AIMessage(content="reasoning")]}),
        _report_event(),
    ])
    labels = [s.get("label") for s in dra.run_deep_research("q?") if s["type"] == "thought"]
    assert labels == ["Research brief", "Sub-topic findings", "Supervisor reasoning"]


def test_metrics_counted_across_the_run(monkeypatch, wiki_dir):
    ai = AIMessage(content="", tool_calls=[
        {"name": "ConductResearch", "args": {"research_topic": "X"}, "id": "1",
         "type": "tool_call"},
        {"name": "ConductResearch", "args": {"research_topic": "Y"}, "id": "2",
         "type": "tool_call"}])
    # two tavily_search calls' worth of output, three unique URLs between them
    notes = TAVILY_RESULT + "\nSearch results: \n\n--- SOURCE 1: Third ---\nURL: https://example.org/c\n\nSUMMARY:\nx\n"
    report = ("Body citing https://example.org/a and https://example.org/b.\n\n"
              "### Sources\n[1] A: https://example.org/a\n[2] B: https://example.org/b\n")
    _script(monkeypatch, [
        ("supervisor", {"supervisor_messages": [ai]}),
        ("research_supervisor", {"raw_notes": [notes]}),
        _report_event(report),
    ])
    m = list(dra.run_deep_research("q?"))[-1]["metrics"]
    assert m == {"tasks": 2, "searches": 2, "sources_checked": 3, "sources_cited": 2}


def test_report_urls_dedupe_and_strip_trailing_punctuation():
    assert dra._report_urls("see https://a.org/x. and https://a.org/x again") == {"https://a.org/x"}
    assert dra._report_urls("") == set()


def test_metrics_zero_when_the_graph_did_no_research(monkeypatch, wiki_dir):
    """The observed small-model failure mode: a report written straight from
    model knowledge. The run still succeeds, so the metrics are the only tell."""
    _script(monkeypatch, [_report_event("A report with no sources at all.")])
    m = list(dra.run_deep_research("q?"))[-1]["metrics"]
    assert m == {"tasks": 0, "searches": 0, "sources_checked": 0, "sources_cited": 0}


# --- fall back to Quick ----------------------------------------------------

def _capture_quick(monkeypatch):
    seen = {}

    def fake_quick(question, wiki_context=""):
        seen["args"] = (question, wiki_context)
        yield {"type": "final_answer", "content": "quick answer", "report_path": None}

    monkeypatch.setattr(dra.quick_agent, "run_research_agent", fake_quick)
    return seen


def test_graph_exception_falls_back_to_quick(monkeypatch, wiki_dir):
    seen = _capture_quick(monkeypatch)

    def boom(q, d):
        raise ValueError("structured output failed")
        yield  # pragma: no cover — makes this a generator

    monkeypatch.setattr(dra, "_astream_sync", boom)
    steps = list(dra.run_deep_research("q?", "ctx"))
    assert [s["type"] for s in steps] == ["notice", "final_answer"]
    assert "structured output failed" in steps[0]["content"]
    assert steps[-1]["content"] == "quick answer"
    assert seen["args"] == ("q?", "ctx")


def test_report_error_string_falls_back_to_quick(monkeypatch, wiki_dir):
    _capture_quick(monkeypatch)
    _script(monkeypatch, [_report_event("Error generating final report: boom")])
    steps = list(dra.run_deep_research("q?"))
    assert steps[0]["type"] == "notice" and "boom" in steps[0]["content"]
    assert steps[-1]["content"] == "quick answer"


def test_empty_report_falls_back_to_quick(monkeypatch, wiki_dir):
    _capture_quick(monkeypatch)
    _script(monkeypatch, [_report_event("   ")])
    steps = list(dra.run_deep_research("q?"))
    assert steps[0]["type"] == "notice"
    assert steps[-1]["content"] == "quick answer"


def test_missing_tavily_key_errors_without_running_the_graph(monkeypatch):
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    monkeypatch.setattr(dra, "_astream_sync",
                        lambda q, d: pytest.fail("graph must not run"))
    steps = list(dra.run_deep_research("q?"))
    assert steps == [{"type": "error",
                      "content": "TAVILY_API_KEY not set — Deep Research is web-only."}]


# --- configuration ---------------------------------------------------------

def test_all_model_roles_point_at_local_ollama():
    cfg = dra._configurable()
    roles = ["research_model", "final_report_model", "compression_model",
             "summarization_model"]
    assert all(cfg[r] == f"ollama:{dra.MODEL}" for r in roles)
    assert cfg["search_api"] == "tavily"
    assert cfg["allow_clarification"] is False


def test_ollama_host_is_wired_before_the_graph_runs(monkeypatch, wiki_dir):
    monkeypatch.setenv("OLLAMA_HOST", "http://wrong:1")
    monkeypatch.setattr(dra.ollama_client, "_HOST", "http://gpu-box:11434")
    _script(monkeypatch, [_report_event()])
    list(dra.run_deep_research("q?"))
    import os
    assert os.environ["OLLAMA_HOST"] == "http://gpu-box:11434"


# --- the real async bridge -------------------------------------------------

def test_astream_sync_closes_its_event_loop(monkeypatch):
    """The bridge owns its loop: it must not leak one into the calling thread."""
    import asyncio

    class FakeGraph:
        def astream(self, **kwargs):
            async def gen():
                yield ((), {"write_research_brief": {"research_brief": "b"}})
            return gen()

    monkeypatch.setattr(dra, "deep_researcher", FakeGraph())
    events = list(dra._astream_sync("q?", ""))
    assert events == [("write_research_brief", {"research_brief": "b"})]
    with pytest.raises(RuntimeError):
        asyncio.get_event_loop_policy().get_event_loop()
