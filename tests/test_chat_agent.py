"""Tests for chat_agent.py — fallback synthesis when the agent stalls."""

from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

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
        chat_agent.ollama_client,
        "generate",
        lambda system, prompt, **kw: "SYNTHESIZED [Source: foo.md]",
    )
    steps = list(chat_agent.run_chat_agent("q?"))
    final = [s for s in steps if s["type"] == "final_answer"]
    assert final
    assert "SYNTHESIZED" in final[-1]["content"]
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
        chat_agent.ollama_client,
        "generate",
        lambda system, prompt, **kw: "PARTIAL [Source: foo.md]",
    )
    steps = list(chat_agent.run_chat_agent("q?"))
    final = [s for s in steps if s["type"] == "final_answer"]
    assert final
    assert "iteration limit (4)" in final[-1]["content"]
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
    assert steps
    assert steps[-1]["type"] == "error"


def test_build_llm_applies_the_per_call_timeout(monkeypatch):
    # ChatOllama ignores unknown kwargs, so the timeout must reach the HTTP client.
    monkeypatch.setattr(chat_agent.ollama_client, "host", lambda: "http://127.0.0.1:11434")
    llm: Any = chat_agent._build_llm()
    assert llm.bound._client._client.timeout.read == chat_agent.LLM_TIMEOUT


def test_build_llm_uses_the_app_wide_context_window(monkeypatch):
    # Without num_ctx Ollama's default window cuts long runs, and a window that differs
    # from the other calls' reloads the model on every switch between Fast and Deep.
    monkeypatch.setattr(chat_agent.ollama_client, "host", lambda: "http://127.0.0.1:11434")
    llm: Any = chat_agent._build_llm()
    assert llm.bound.num_ctx == chat_agent.ollama_client.NUM_CTX


def test_a_deep_chat_run_has_room_to_research_before_the_submit_nudge():
    assert chat_agent.MAX_ITER >= 40
    assert chat_agent.NUDGE_AT >= 18  # agent turns; each turn is two graph steps


def test_the_deep_chat_prompt_asks_for_a_structured_answer_not_a_concise_one():
    import prompts

    assert "concise" not in prompts.CHAT_AGENT_SYSTEM
    assert "## " in prompts.CHAT_AGENT_SYSTEM
    nudge = prompts.CHAT_BUDGET_NUDGE.format(min_words=500)
    assert "500+ words" in nudge


def _tool(name: str, content: str, call_id: str) -> ToolMessage:
    return ToolMessage(content=content, name=name, tool_call_id=call_id)


def test_old_tool_results_are_trimmed_so_the_answer_fits_the_window():
    # A full window cuts the answer mid-sentence (Ollama stops at num_ctx), so bulky old
    # results shrink to their head; notes, the question and the latest result stay whole.
    msgs = [
        SystemMessage(content="system"),
        HumanMessage(content="question"),
        _tool("raw_read", "## Raw file: a.md\n" + "a" * 50_000, "1"),
        _tool("think_tool", "Have: fact [Source: a.md]", "2"),
        _tool("raw_read", "## Raw file: b.md\n" + "b" * 50_000, "3"),
        _tool("raw_read", "## Raw file: c.md\n" + "c" * 30_000, "4"),
    ]
    fitted, _ = chat_agent._fit_window(msgs, budget_chars=60_000)
    assert sum(len(str(m.content)) for m in fitted) <= 60_000
    head = str(fitted[2].content)
    assert head.startswith("## Raw file: a.md")
    assert "trimmed" in head
    assert fitted[3].content == "Have: fact [Source: a.md]"
    assert fitted[5].content == msgs[5].content  # the latest result stays whole
    assert [m.content for m in fitted[:2]] == ["system", "question"]
    assert msgs[2].content.endswith("a" * 100)  # the run's history itself is untouched


def test_a_short_history_is_sent_unchanged():
    msgs = [HumanMessage(content="q"), _tool("raw_read", "short", "1")]
    assert chat_agent._fit_window(msgs, budget_chars=60_000) == (msgs, frozenset())


def test_a_trim_cuts_deep_so_the_next_turns_send_the_same_prefix():
    # Ollama reuses its prompt cache only up to the first changed token. Trimming just
    # enough each turn would cut one more early result per turn and re-prefill everything
    # after it; one deep cut, then reused verbatim, keeps the prefix stable.
    msgs: list[Any] = [HumanMessage(content="q")] + [
        _tool("raw_read", f"## Raw file: {i}.md\n" + "x" * 20_000, str(i)) for i in range(5)
    ]
    first, trimmed = chat_agent._fit_window(msgs, budget_chars=90_000)
    assert sum(len(str(m.content)) for m in first) <= 90_000 * chat_agent._TRIM_TO
    grown = [*msgs, _tool("raw_read", "## Raw file: 9.md\n" + "y" * 20_000, "9")]
    second, again = chat_agent._fit_window(grown, trimmed, budget_chars=90_000)
    assert again == trimmed
    assert second[: len(first)] == first


def test_the_wrap_up_nudge_is_stored_once_in_the_history(monkeypatch):
    # A nudge re-added at the tail of every turn's prompt changes the prompt behind the
    # last answer, so each turn re-prefills; stored once, it is just more history.
    monkeypatch.setattr(chat_agent, "NUDGE_AT", 1)
    fake = _patch_llm(
        monkeypatch,
        [_ai_with_tool("think_tool", {"reflection": f"note {i}"}, f"c{i}") for i in range(3)],
    )
    monkeypatch.setattr(chat_agent.ollama_client, "generate", lambda system, prompt, **kw: "x")
    list(chat_agent.run_chat_agent("q?"))
    nudges = [
        [i for i, m in enumerate(call) if isinstance(m, HumanMessage) and "500+ words" in m.content]
        for call in fake.calls
    ]
    assert nudges[1]
    assert all(n == nudges[1] for n in nudges[2:])


# --- prose exit gate (ideas/deep-chat-read-memory-and-section-grounding.md Fix A) ---


def _gate(monkeypatch) -> None:
    """The submit gate accepts exactly the answers that contain GOOD."""
    monkeypatch.setattr(
        chat_agent.tool_module,
        "_submit_chat_impl",
        lambda answer, sources=None: (
            "ACCEPTED: ok" if "GOOD" in answer else "REJECTED: you cite § 62 but never read it."
        ),
    )


def test_a_prose_exit_that_fails_the_gate_is_sent_back_with_the_reason(monkeypatch):
    _gate(monkeypatch)
    fake = _patch_llm(monkeypatch, [AIMessage(content="weak prose"), AIMessage(content="GOOD")])
    steps = list(chat_agent.run_chat_agent("q?"))
    assert "REJECTED: you cite § 62" in str(fake.calls[1][-1].content)
    final = steps[-1]
    assert final["type"] == "final_answer"
    assert final["content"] == "GOOD"
    gates = [s["content"] for s in steps if s["type"] == "gate"]
    assert gates[0].startswith("rejected (retry 1/")
    assert gates[-1] == "accepted"


def test_a_prose_exit_after_the_retries_is_labelled_best_effort_with_the_reason(monkeypatch):
    _gate(monkeypatch)
    monkeypatch.setattr(chat_agent, "PROSE_RETRIES", 2)
    fake = _patch_llm(monkeypatch, [])  # always answers "done" in prose
    steps = list(chat_agent.run_chat_agent("q?"))
    assert len(fake.calls) == 3  # the first prose plus two retries, then the run ends
    final = steps[-1]
    assert final["content"].startswith(
        "(best-effort — quality gate not met: REJECTED: you cite § 62 but never read it.)"
    )
    assert final["content"].endswith("done")


def test_section_citations_are_counted_like_the_gate_counts_them():
    out = chat_agent._cites("a [Source: StrlSchG.md §62] b [Source: StrlSchG.md §61]")
    assert out["sources"] == ["StrlSchG.md §61", "StrlSchG.md §62"]


def _looping(bonus: int):
    class LoopingLLM:
        calls = 0

        def invoke(self, messages):
            LoopingLLM.calls += 1
            mem = chat_agent.run_memory.current()
            assert mem is not None
            mem.bonus = bonus  # as if references were followed
            return _ai_with_tool("think_tool", {"reflection": "still working"})

    return LoopingLLM


def test_followed_references_extend_the_step_limit(monkeypatch):
    monkeypatch.setattr(chat_agent, "MAX_ITER", 4)
    monkeypatch.setattr(chat_agent.ollama_client, "generate", lambda *a, **k: "")
    for bonus, calls in ((0, 2), (2, 4)):
        llm = _looping(bonus)
        monkeypatch.setattr(chat_agent, "_build_llm", llm)
        steps = list(chat_agent.run_chat_agent("q?"))
        assert llm.calls == calls
        assert any("Recursion limit" in s.get("content", "") for s in steps)
