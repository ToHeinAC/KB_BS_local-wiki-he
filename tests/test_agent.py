"""Tests for agent.py — LangGraph deep researcher."""

from unittest.mock import MagicMock

import pytest
from langchain_core.messages import AIMessage

import agent


class FakeLLM:
    """Drop-in for ChatOllama.bind_tools(...) — returns scripted AIMessages."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    def invoke(self, messages):
        self.calls.append(messages)
        if not self._responses:
            return AIMessage(content="done")
        return self._responses.pop(0)


def _patch_llm(monkeypatch, responses):
    fake = FakeLLM(responses)
    monkeypatch.setattr(agent, "_build_llm", lambda: fake)
    return fake


def _ai_with_tool(name, args, call_id="c1"):
    return AIMessage(
        content="",
        tool_calls=[{"name": name, "args": args, "id": call_id, "type": "tool_call"}],
    )


# --- basic step types ------------------------------------------------------

def test_plain_text_response_yields_final_answer(monkeypatch):
    _patch_llm(monkeypatch, [AIMessage(content="just an answer")])
    steps = list(agent.run_research_agent("q?"))
    assert any(s["type"] == "final_answer" and "just an answer" in s["content"] for s in steps)


def test_tool_call_emits_tool_call_and_tool_result(monkeypatch):
    _patch_llm(
        monkeypatch,
        [_ai_with_tool("think_tool", {"reflection": "planning"}), AIMessage(content="done")],
    )
    steps = list(agent.run_research_agent("q?"))
    assert any(s["type"] == "tool_call" and s["name"] == "think_tool" for s in steps)
    assert any(s["type"] == "tool_result" and s["name"] == "think_tool" for s in steps)


def test_submit_final_answer_accepted_yields_report_path(monkeypatch, tmp_path):
    import tools
    monkeypatch.setattr(tools, "WIKI_DIR", tmp_path)
    monkeypatch.setattr(tools, "MIN_WORDS", 3)
    monkeypatch.setattr(tools, "MIN_URLS", 1)
    body = "alpha beta gamma delta http://example.com/x"
    _patch_llm(
        monkeypatch,
        [_ai_with_tool("submit_final_answer", {"title": "T", "answer": body})],
    )
    steps = list(agent.run_research_agent("q?"))
    final = [s for s in steps if s["type"] == "final_answer"]
    assert final and final[-1]["report_path"] and "report-t.md" in final[-1]["report_path"]


def test_submit_rejected_keeps_agent_running(monkeypatch):
    # Default thresholds reject the trivial answer; the agent then plain-texts -> final_answer.
    _patch_llm(
        monkeypatch,
        [
            _ai_with_tool("submit_final_answer", {"title": "T", "answer": "too short"}),
            AIMessage(content="ok I will research more"),
        ],
    )
    steps = list(agent.run_research_agent("q?"))
    tr = [s for s in steps if s["type"] == "tool_result" and s["name"] == "submit_final_answer"]
    assert tr and tr[0]["result"].startswith("REJECTED")
    assert any(s["type"] == "final_answer" for s in steps)


# --- system prompt & wiki context -----------------------------------------

def test_wiki_context_appears_in_system_message(monkeypatch):
    fake = _patch_llm(monkeypatch, [AIMessage(content="ok")])
    list(agent.run_research_agent("q?", wiki_context="WIKI-CTX-MARKER"))
    assert "WIKI-CTX-MARKER" in fake.calls[0][0].content


def test_thresholds_appear_in_system_prompt(monkeypatch):
    fake = _patch_llm(monkeypatch, [AIMessage(content="ok")])
    list(agent.run_research_agent("q?"))
    sys_text = fake.calls[0][0].content
    assert str(agent.MIN_SEARCHES) in sys_text and str(agent.MIN_WORDS) in sys_text


# --- error handling --------------------------------------------------------

def test_llm_init_failure_yields_error(monkeypatch):
    def boom():
        raise RuntimeError("ollama down")
    monkeypatch.setattr(agent, "_build_llm", boom)
    steps = list(agent.run_research_agent("q?"))
    assert steps and steps[-1]["type"] == "error"


def test_invoke_failure_yields_error(monkeypatch):
    fake = MagicMock()
    fake.invoke.side_effect = ConnectionError("nope")
    monkeypatch.setattr(agent, "_build_llm", lambda: fake)
    steps = list(agent.run_research_agent("q?"))
    assert any(s["type"] == "error" for s in steps)
