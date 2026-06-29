"""Tests for chat_agent.py — fallback synthesis when the agent stalls."""

from langchain_core.messages import AIMessage

import chat_agent


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
    monkeypatch.setattr(chat_agent, "_build_llm", lambda: fake)
    return fake


def _ai_with_tool(name, args, call_id="c1"):
    return AIMessage(
        content="",
        tool_calls=[{"name": name, "args": args, "id": call_id, "type": "tool_call"}],
    )


def test_stalled_agent_synthesizes_from_notes(monkeypatch):
    # Agent calls a tool, then emits an empty completion (no prose, no submit).
    _patch_llm(
        monkeypatch,
        [
            _ai_with_tool("think_tool", {"reflection": "found X about Y"}),
            AIMessage(content="", tool_calls=[]),  # stalls: graph ends, no answer
        ],
    )
    monkeypatch.setattr(
        chat_agent.ollama_client, "generate",
        lambda system, prompt, **kw: "SYNTHESIZED [Source: foo.md]",
    )
    steps = list(chat_agent.run_chat_agent("q?"))
    final = [s for s in steps if s["type"] == "final_answer"]
    assert final and "SYNTHESIZED" in final[-1]["content"]
    assert final[-1].get("note", "").startswith("Fallback synthesis")
    assert "foo.md" in final[-1]["sources"]


def test_iteration_limit_appends_end_hint(monkeypatch):
    # LLM never stops calling tools -> the graph hits the recursion limit.
    class LoopingLLM:
        def invoke(self, messages):
            return _ai_with_tool("think_tool", {"reflection": "still working"})

    monkeypatch.setattr(chat_agent, "_build_llm", lambda: LoopingLLM())
    monkeypatch.setattr(chat_agent, "MAX_ITER", 4)
    monkeypatch.setattr(
        chat_agent.ollama_client, "generate",
        lambda system, prompt, **kw: "PARTIAL [Source: foo.md]",
    )
    steps = list(chat_agent.run_chat_agent("q?"))
    final = [s for s in steps if s["type"] == "final_answer"]
    assert final and "iteration limit (4)" in final[-1]["content"]
    assert final[-1]["content"].rstrip().endswith("may be partial.*")


def test_no_notes_no_prose_yields_error_without_synth_call(monkeypatch):
    # Empty first completion, no tool calls -> no notes -> no synthesis, plain error.
    _patch_llm(monkeypatch, [AIMessage(content="", tool_calls=[])])
    called = {"n": 0}

    def _spy(system, prompt, **kw):
        called["n"] += 1
        return "X"

    monkeypatch.setattr(chat_agent.ollama_client, "generate", _spy)
    steps = list(chat_agent.run_chat_agent("q?"))
    assert called["n"] == 0
    assert steps and steps[-1]["type"] == "error"
