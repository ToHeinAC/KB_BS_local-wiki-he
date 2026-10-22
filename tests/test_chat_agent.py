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
    monkeypatch.setattr(chat_agent, "_preflight", lambda q: [])  # pre-flight hits are notes
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


def test_build_llm_samples_as_recommended_for_gemma_and_thinks_when_the_model_can(monkeypatch):
    # Google, Ollama and Unsloth give 1.0 / 0.95 / 64 for every use; small models call tools
    # more reliably with thinking on. ChatOllama sends the thinking back with the history,
    # so the prompt stays append-only for Ollama's cache.
    monkeypatch.setattr(chat_agent.ollama_client, "host", lambda: "http://127.0.0.1:11434")
    monkeypatch.setattr(chat_agent.ollama_client, "thinks", lambda model: True)
    llm: Any = chat_agent._build_llm()
    assert (llm.bound.temperature, llm.bound.top_p, llm.bound.top_k) == (1.0, 0.95, 64)
    assert llm.bound.reasoning is True
    monkeypatch.setattr(chat_agent.ollama_client, "thinks", lambda model: False)
    assert chat_agent._build_llm().bound.reasoning is None  # type: ignore[attr-defined]


def test_thinking_counts_toward_the_context_budget():
    thought = AIMessage(content="", additional_kwargs={"reasoning_content": "t" * 5000})
    assert chat_agent._size(thought) >= 5000


def test_a_trim_also_drops_the_thinking_of_old_turns():
    def turn(i: int) -> AIMessage:
        return AIMessage(
            content="",
            additional_kwargs={"reasoning_content": "t" * 20_000},
            tool_calls=[{"name": "think_tool", "args": {}, "id": f"c{i}", "type": "tool_call"}],
        )

    msgs: list[Any] = [HumanMessage(content="q")]
    for i in range(5):
        msgs += [turn(i), _tool("think_tool", "note", f"c{i}")]
    fitted, _ = chat_agent._fit_window(msgs, budget_chars=60_000)
    assert sum(map(chat_agent._size, fitted)) <= 60_000
    assert fitted[-2].additional_kwargs["reasoning_content"]  # the latest turn keeps it


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


# --- pre-flight search (report tweak 2) ---


def test_code_runs_the_first_raw_and_wiki_search_before_the_model_acts(monkeypatch):
    # A small model's weakest step is starting retrieval at all; the question itself is
    # the first query, so code runs it and the model starts from the hits.
    tm = chat_agent.tool_module
    monkeypatch.setattr(chat_agent, "_hyde_search", lambda q: [])  # tested on its own
    monkeypatch.setattr(tm, "_raw_search_impl", lambda queries, **kw: "RAW HITS for " + queries[0])
    monkeypatch.setattr(tm, "_wiki_search_impl", lambda queries, **kw: "WIKI HITS")
    fake = _patch_llm(monkeypatch, [])
    monkeypatch.setattr(chat_agent.ollama_client, "generate", lambda system, prompt, **kw: "x")
    list(chat_agent.run_chat_agent("Wer genehmigt NORM-Rückstände?"))
    first = fake.calls[0]
    results = {m.name: m.content for m in first if isinstance(m, ToolMessage)}
    assert results == {
        "raw_search": "RAW HITS for Wer genehmigt NORM-Rückstände?",
        "wiki_search": "WIKI HITS",
    }
    calls = next(m for m in first if isinstance(m, AIMessage)).tool_calls
    assert [c["name"] for c in calls] == ["raw_search", "wiki_search"]
    mem = chat_agent.run_memory.current()
    assert mem is not None
    assert len(mem.searches) == 2  # they count toward the gate


def test_a_failing_pre_flight_search_leaves_the_run_to_the_model(monkeypatch):
    def boom(*_a, **_k):
        raise RuntimeError("no index")

    monkeypatch.setattr(chat_agent.tool_module, "_raw_search_impl", boom)
    fake = _patch_llm(monkeypatch, [])
    monkeypatch.setattr(chat_agent.ollama_client, "generate", lambda system, prompt, **kw: "x")
    list(chat_agent.run_chat_agent("q?"))
    assert not any(isinstance(m, ToolMessage) for m in fake.calls[0])


# --- auto-read of the top original (report tweak 7) ---

RAW_HITS = (
    "## Raw query: q\n[Raw hit 1]\nfile: strl.md §5\nchunk_id: c1\n---\n[Raw hit 2]\nfile: b.md\n"
)


def _stub_search(monkeypatch, reads):
    tm = chat_agent.tool_module
    monkeypatch.setattr(tm, "_raw_search_impl", lambda queries, **kw: RAW_HITS)
    monkeypatch.setattr(tm, "_wiki_search_impl", lambda queries, **kw: "WIKI HITS")
    monkeypatch.setattr(
        tm, "_memory_read", lambda mem, f, offset: (reads.append([f]) or "READ TEXT", f)
    )
    monkeypatch.setattr(tm, "_pagination_nudge", lambda mem, qbases: None)
    monkeypatch.setattr(chat_agent.ollama_client, "generate", lambda system, prompt, **kw: "x")


def test_code_opens_the_top_hit_when_the_model_has_read_no_original(monkeypatch):
    # Small models answer from search excerpts; the gate wants a read original, so by the
    # third turn code opens the best hit's section for the model.
    reads: list = []
    _stub_search(monkeypatch, reads)
    fake = _patch_llm(
        monkeypatch,
        [_ai_with_tool("think_tool", {"reflection": f"n{i}"}, f"t{i}") for i in range(2)],
    )
    list(chat_agent.run_chat_agent("q?"))
    assert reads == [["strl.md §5"]]
    third = fake.calls[2]
    assert any(isinstance(m, ToolMessage) and m.content == "READ TEXT" for m in third)


def test_no_auto_read_once_the_model_opened_an_original_itself(monkeypatch):
    reads: list = []
    _stub_search(monkeypatch, reads)
    _patch_llm(
        monkeypatch,
        [
            _ai_with_tool("raw_read", {"filenames": ["b.md"]}, "r1"),
            _ai_with_tool("think_tool", {"reflection": "n"}, "t1"),
            _ai_with_tool("think_tool", {"reflection": "m"}, "t2"),
        ],
    )
    list(chat_agent.run_chat_agent("q?"))
    assert reads == [["b.md"]]


# --- tool errors (report tweak 9) ---


def test_a_failing_tool_reports_an_error_line_instead_of_ending_the_run(monkeypatch):
    # LangGraph's ToolNode re-raises tool exceptions by default, which ended the whole run
    # at one bad read. The model gets a plain ERROR line and carries on; the exception text
    # stays out of it, so a denied name reads exactly like a missing one.
    monkeypatch.setattr(chat_agent, "_preflight", lambda q: [])

    def boom(*_a, **_k):
        raise KeyError("Strahlenschutz@strict")

    monkeypatch.setattr(chat_agent.tool_module, "_raw_search_impl", boom)
    fake = _patch_llm(monkeypatch, [_ai_with_tool("raw_search", {"query": "x"})])
    monkeypatch.setattr(chat_agent.ollama_client, "generate", lambda system, prompt, **kw: "x")
    steps = list(chat_agent.run_chat_agent("q?"))
    assert all(s["type"] != "error" for s in steps)
    result = next(m for m in fake.calls[1] if isinstance(m, ToolMessage))
    assert str(result.content).startswith("ERROR:")
    assert "strict" not in str(result.content)


# --- answer from the evidence ledger (answer tweaks 1 and 3) ---


def _ledger_run(n_refs: int = 3) -> Any:
    mem = chat_agent.run_memory.begin_run("q?")
    for q in ("a", "b", "c"):
        mem.mark_search(f"raw_search:{q}")
    mem.ledger = [(f"f{i}.md § {i}", f"Satz {i} mit Inhalt und Zahl {i}.") for i in range(n_refs)]
    return mem


def test_the_final_answer_is_written_from_the_ledger_when_it_passes_the_gate(monkeypatch):
    # A small model writes better from a short list of quotes than from a 30K history.
    _ledger_run()
    prompts_seen: list = []
    monkeypatch.setattr(
        chat_agent.ollama_client,
        "generate",
        lambda system, prompt, **kw: (
            prompts_seen.append(prompt) or "FROM QUOTES [Source: f0.md § 0]"
        ),
    )
    monkeypatch.setattr(chat_agent.tool_module, "_submit_chat_impl", lambda a, s=None: "ACCEPTED")
    run = chat_agent._Run()
    run.messages = [_ai_with_tool("submit_chat_answer", {"answer": "AGENT ANSWER"})]
    final = chat_agent._final_step("q?", "", run)
    assert final["content"] == "FROM QUOTES [Source: f0.md § 0]"
    assert '[1] [Source: f0.md § 0] "Satz 0' in prompts_seen[0]
    assert final["sources"] == ["f0.md § 0"]


def test_a_ledger_answer_the_gate_rejects_leaves_the_agents_answer(monkeypatch):
    _ledger_run()
    monkeypatch.setattr(chat_agent.ollama_client, "generate", lambda system, prompt, **kw: "bad")
    monkeypatch.setattr(chat_agent.tool_module, "_submit_chat_impl", lambda a, s=None: "REJECTED")
    monkeypatch.setattr(chat_agent, "_extract_submitted_answer", lambda m: ("AGENT ANSWER", []))
    final = chat_agent._final_step("q?", "", chat_agent._Run())
    assert final["content"] == "AGENT ANSWER"


def test_no_ledger_answer_without_enough_quoted_sources(monkeypatch):
    _ledger_run(n_refs=2)  # the gate needs 3 sources; a call that cannot pass is skipped
    calls: list = []
    monkeypatch.setattr(chat_agent.ollama_client, "generate", lambda *a, **k: calls.append(1))
    assert chat_agent._ledger_answer("q?", "") is None
    assert calls == []


def test_the_run_stops_once_covered_and_no_new_evidence_arrives(monkeypatch):
    # Retrieval thrash: a covered run that keeps searching without new quotes ends after
    # STALL_TURNS turns, and the answer is written from the ledger.
    monkeypatch.setattr(chat_agent, "_preflight", lambda q: [])
    monkeypatch.setattr(chat_agent, "_covered", lambda mem: True)
    fake = _patch_llm(
        monkeypatch,
        [_ai_with_tool("think_tool", {"reflection": f"n{i}"}, f"t{i}") for i in range(20)],
    )
    monkeypatch.setattr(chat_agent.ollama_client, "generate", lambda system, prompt, **kw: "x")
    steps = list(chat_agent.run_chat_agent("q?"))
    assert len(fake.calls) == chat_agent.STALL_TURNS
    assert any(s["type"] == "gate" and "no new evidence" in s["content"] for s in steps)


# --- HyDE in the pre-flight (answer tweak 5) ---


def test_the_pre_flight_also_searches_with_a_hypothetical_answer_passage(monkeypatch):
    # HyDE: a passage shaped like the answer matches the originals better than a question
    # (the one query-side transform that helped in Wang et al. 2024). It does not count
    # toward the gate's searches, so the agent still has to search itself.
    seen: list = []
    tm = chat_agent.tool_module
    monkeypatch.setattr(tm, "_raw_search_impl", lambda queries, **kw: seen.append(queries) or "RAW")
    monkeypatch.setattr(tm, "_wiki_search_impl", lambda queries, **kw: "WIKI")
    monkeypatch.setattr(
        chat_agent.ollama_client, "generate", lambda system, prompt, **kw: "Rückstände dürfen nur"
    )
    chat_agent.run_memory.begin_run("q?")
    msgs = chat_agent._preflight("Wann dürfen Rückstände verwertet werden?")
    assert seen == [["Wann dürfen Rückstände verwertet werden?"], ["Rückstände dürfen nur"]]
    assert [m.name for m in msgs if isinstance(m, ToolMessage)] == [
        "raw_search",
        "wiki_search",
        "raw_search",
    ]
    mem = chat_agent.run_memory.current()
    assert mem is not None
    assert len(mem.searches) == 2


def test_a_failed_hypothetical_passage_leaves_the_plain_pre_flight(monkeypatch):
    tm = chat_agent.tool_module
    monkeypatch.setattr(tm, "_raw_search_impl", lambda queries, **kw: "RAW")
    monkeypatch.setattr(tm, "_wiki_search_impl", lambda queries, **kw: "WIKI")

    def down(*_a, **_k):
        raise ConnectionError("down")

    monkeypatch.setattr(chat_agent.ollama_client, "generate", down)
    chat_agent.run_memory.begin_run("q?")
    msgs = chat_agent._preflight("q?")
    assert len([m for m in msgs if isinstance(m, ToolMessage)]) == 2
