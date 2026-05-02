"""Tests for agent.py — ReAct research agent."""

from unittest.mock import MagicMock, patch

import pytest

import agent
import ollama_client


def _msg(content="", tool_calls=None):
    return {"message": {"content": content, "tool_calls": tool_calls or []}}


def _make_client(monkeypatch):
    mock = MagicMock()
    monkeypatch.setattr(ollama_client, "_client", lambda: mock)
    return mock


# --- basic step types ---

def test_yields_thought_on_text_response(monkeypatch):
    mock = _make_client(monkeypatch)
    mock.chat.return_value = _msg(content="thinking about it")
    steps = list(agent.run_research_agent("question?"))
    thoughts = [s for s in steps if s["type"] == "thought"]
    assert any("thinking" in t["content"] for t in thoughts)


def test_yields_final_answer_when_no_tool_calls(monkeypatch):
    mock = _make_client(monkeypatch)
    mock.chat.return_value = _msg(content="my final answer")
    steps = list(agent.run_research_agent("q?"))
    assert any(s["type"] == "final_answer" for s in steps)


def test_yields_tool_call_dict(monkeypatch):
    mock = _make_client(monkeypatch)
    tool_call = {"function": {"name": "tavily_search", "arguments": {"query": "test"}}}
    mock.chat.side_effect = [
        _msg(content="", tool_calls=[tool_call]),
        _msg(content="done"),
    ]
    steps = list(agent.run_research_agent("q?"))
    tc_steps = [s for s in steps if s["type"] == "tool_call"]
    assert len(tc_steps) >= 1
    assert tc_steps[0]["name"] == "tavily_search"


def test_yields_tool_result_after_execution(monkeypatch):
    mock = _make_client(monkeypatch)
    tool_call = {"function": {"name": "tavily_search", "arguments": {"query": "x"}}}
    mock.chat.side_effect = [
        _msg(content="", tool_calls=[tool_call]),
        _msg(content="done"),
    ]
    with patch("tools.TOOL_FUNCTIONS", {"tavily_search": lambda **_: "search result"}):
        steps = list(agent.run_research_agent("q?"))
    tr_steps = [s for s in steps if s["type"] == "tool_result"]
    assert any("search result" in s["result"] for s in tr_steps)


def test_yields_final_answer_after_report_writer(monkeypatch):
    mock = _make_client(monkeypatch)
    tool_call = {"function": {"name": "report_writer", "arguments": {"report": "md", "filename": "r.md"}}}
    mock.chat.return_value = _msg(content="", tool_calls=[tool_call])
    with patch("tools.TOOL_FUNCTIONS", {"report_writer": lambda **_: "data/wiki/comparisons/r.md"}):
        steps = list(agent.run_research_agent("q?"))
    fa_steps = [s for s in steps if s["type"] == "final_answer"]
    assert len(fa_steps) >= 1
    assert fa_steps[0].get("report_path") is not None


# --- error cases ---

def test_yields_error_when_ollama_raises(monkeypatch):
    mock = _make_client(monkeypatch)
    mock.chat.side_effect = ConnectionError("down")
    steps = list(agent.run_research_agent("q?"))
    assert any(s["type"] == "error" for s in steps)


def test_yields_error_after_max_iter(monkeypatch):
    mock = _make_client(monkeypatch)
    tool_call = {"function": {"name": "tavily_search", "arguments": {"query": "loop"}}}
    mock.chat.return_value = _msg(content="", tool_calls=[tool_call])
    with patch("tools.TOOL_FUNCTIONS", {"tavily_search": lambda **_: "result"}):
        steps = list(agent.run_research_agent("q?"))
    assert any(s["type"] == "error" and "max" in s["content"].lower() for s in steps)


# --- context and edge cases ---

def test_wiki_context_in_system_when_provided(monkeypatch):
    captured = {}
    mock = _make_client(monkeypatch)

    def fake_chat(model, messages, tools, options):
        captured["system"] = messages[0]["content"]
        return _msg(content="done")

    mock.chat.side_effect = fake_chat
    list(agent.run_research_agent("q?", wiki_context="WIKI CONTEXT HERE"))
    assert "WIKI CONTEXT HERE" in captured["system"]


def test_unknown_tool_produces_error_result(monkeypatch):
    mock = _make_client(monkeypatch)
    tool_call = {"function": {"name": "nonexistent_tool", "arguments": {}}}
    mock.chat.side_effect = [
        _msg(content="", tool_calls=[tool_call]),
        _msg(content="done"),
    ]
    steps = list(agent.run_research_agent("q?"))
    tr_steps = [s for s in steps if s["type"] == "tool_result"]
    assert any("Unknown tool" in s["result"] for s in tr_steps)


def test_malformed_json_args_handled_gracefully(monkeypatch):
    mock = _make_client(monkeypatch)
    tool_call = {"function": {"name": "tavily_search", "arguments": "not-json-{"}}
    mock.chat.side_effect = [
        _msg(content="", tool_calls=[tool_call]),
        _msg(content="done"),
    ]
    with patch("tools.TOOL_FUNCTIONS", {"tavily_search": lambda **_: "ok"}):
        steps = list(agent.run_research_agent("q?"))
    # Should not raise; agent handles gracefully
    assert any(s["type"] in ("tool_result", "final_answer", "error") for s in steps)
