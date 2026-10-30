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
            AIMessage(content="", tool_calls=[]),  # stalls: nudged once to go on
            AIMessage(content="", tool_calls=[]),  # stalls again: graph ends, no answer
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
    assert final[-1]["closing"] == "notes-fallback"
    assert "foo.md" in final[-1]["sources"]


def test_an_empty_turn_before_the_run_is_covered_is_sent_back_once(monkeypatch):
    # E4B sometimes ends with an empty turn after the pre-flight; falling through to the
    # ungated notes fallback let an unread § into the answer (q3).
    monkeypatch.setattr(chat_agent, "_preflight", lambda q: [])
    fake = _patch_llm(monkeypatch, [AIMessage(content=""), AIMessage(content="")])
    monkeypatch.setattr(chat_agent.ollama_client, "generate", lambda system, prompt, **kw: "x")
    steps = list(chat_agent.run_chat_agent("q?"))
    assert len(fake.calls) == 2
    nudge = fake.calls[1][-1]
    assert isinstance(nudge, HumanMessage)
    assert "submit_chat_answer" in nudge.content
    gates = [s["content"] for s in steps if s["type"] == "gate"]
    assert gates == ["empty turn: sent back to search and read"]


def test_a_covered_runs_empty_turn_still_ends_the_run(monkeypatch):
    monkeypatch.setattr(chat_agent, "_preflight", lambda q: [])
    monkeypatch.setattr(chat_agent, "_covered", lambda mem: True)
    monkeypatch.setattr(chat_agent, "STALL_TURNS", 99)
    fake = _patch_llm(monkeypatch, [AIMessage(content="")])
    monkeypatch.setattr(chat_agent.ollama_client, "generate", lambda system, prompt, **kw: "x")
    list(chat_agent.run_chat_agent("q?"))
    assert len(fake.calls) == 1


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
    # Empty completions, no tool calls -> no notes -> no synthesis, plain error (the first
    # empty turn is sent back once).
    monkeypatch.setattr(chat_agent, "_preflight", lambda q: [])  # pre-flight hits are notes
    _patch_llm(monkeypatch, [AIMessage(content="", tool_calls=[]), AIMessage(content="")])
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


def test_build_llm_samples_as_recommended_for_gemma_and_does_not_think(monkeypatch):
    # Google, Ollama and Unsloth give 1.0 / 0.95 / 64 for every use. Thinking stays off even
    # for a model that can: on the KI bench it cited 5 unread sections on q1 and ran q2 past
    # 4.8x the baseline (bench/results/deep_chat_2026-10-22.md).
    monkeypatch.setattr(chat_agent.ollama_client, "host", lambda: "http://127.0.0.1:11434")
    monkeypatch.setattr(chat_agent.ollama_client, "thinks", lambda model: True, raising=False)
    llm: Any = chat_agent._build_llm()
    assert (llm.bound.temperature, llm.bound.top_p, llm.bound.top_k) == (1.0, 0.95, 64)
    assert llm.bound.reasoning is None


def test_a_deep_chat_run_has_room_to_research_before_the_submit_nudge():
    assert chat_agent.MAX_ITER >= 40
    assert chat_agent.NUDGE_AT >= 18  # agent turns; each turn is two graph steps


def test_the_deep_chat_prompt_asks_for_a_structured_answer_not_a_concise_one():
    import prompts

    assert "concise" not in prompts.CHAT_AGENT_SYSTEM
    assert "## " in prompts.CHAT_AGENT_SYSTEM
    assert "2-4 sentences" in prompts.CHAT_BUDGET_NUDGE  # detailed, without a word floor
    assert "level by level" in prompts.CHAT_LEVEL_HEADERS[1]
    # the levels guide comes with the level reads, not in every run's system prompt
    assert "level 1" not in prompts.CHAT_AGENT_SYSTEM + prompts.RESEARCHER_INSTRUCTIONS


# Words of one corpus that once served as prompt examples: a small model reads an example
# as a hint what to read, so the agents' prompts use neutral placeholders instead.
_CORPUS_WORDS = ("StrlSch", "Rückst", "Kernbrenn", "Pu-239", "AtG", "mSv", "Strahlen")


def _corpus_examples(text: str) -> list[str]:
    return [w for w in _CORPUS_WORDS if w in text]


def test_the_agent_prompts_carry_no_example_from_one_corpus():
    import prompts

    assert _corpus_examples("read `StrlSchG.md § 62`") == ["StrlSch"]  # the check bites
    texts = (
        prompts.CHAT_AGENT_SYSTEM,
        prompts.RESEARCHER_INSTRUCTIONS,
        prompts.RAW_SEARCH_DESCRIPTION,
        prompts.RAW_READ_DESCRIPTION,
        prompts.EVALUATE_CONDITION_DESCRIPTION,
        prompts.CONDENSE_PROMPT,
        prompts.ONTOLOGY_LOOKUP_DESCRIPTION,
    )
    assert [w for t in texts for w in _corpus_examples(t)] == []


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
        [
            i
            for i, m in enumerate(call)
            if isinstance(m, HumanMessage) and "STEP BUDGET" in m.content
        ]
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
    reads = [(m.name, m.content) for m in first if isinstance(m, ToolMessage)]
    assert reads == [
        ("raw_search", "RAW HITS for Wer genehmigt NORM-Rückstände?"),
        ("wiki_search", "WIKI HITS"),
        ("raw_search", "RAW HITS for genehmigt NORM-Rückstände"),
    ]
    calls = next(m for m in first if isinstance(m, AIMessage)).tool_calls
    assert [c["name"] for c in calls] == ["raw_search", "wiki_search", "raw_search"]
    mem = chat_agent.run_memory.current()
    assert mem is not None
    # The question in two scopes is one search, its key terms a second: the model still
    # makes the third itself.
    assert mem.search_count() == 2


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
    monkeypatch.setattr(chat_agent, "level_messages", lambda q, searched: [])  # tested on its own
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
    assert final["closing"] == "ledger"
    assert final["content"] == "FROM QUOTES [Source: f0.md § 0]"
    assert '[1] [Source: f0.md § 0] "Satz 0' in prompts_seen[0]
    assert final["sources"] == ["f0.md § 0"]


def test_the_ledger_prompt_names_the_sources_the_gate_requires(monkeypatch):
    # E4B left the definition of the term the question names out of the ledger answer
    mem = _ledger_run()
    mem.core_refs = ["f0.md § 0", "f1.md § 1"]
    mem.term_refs = ["f2.md § 2"]
    prompts_seen: list = []
    monkeypatch.setattr(
        chat_agent.ollama_client,
        "generate",
        lambda system, prompt, **kw: prompts_seen.append(prompt) or "x",
    )
    monkeypatch.setattr(chat_agent.tool_module, "chat_verdict", lambda a: "REJECTED")
    chat_agent._write_ledger_answer(mem, "q?", "")
    assert "at least one of [Source: f0.md § 0], [Source: f1.md § 1]" in prompts_seen[0]
    assert "each of [Source: f2.md § 2]" in prompts_seen[0]
    mem.core_refs, mem.term_refs = [], []  # no levels read: nothing extra is asked
    chat_agent._write_ledger_answer(mem, "q?", "")
    assert "at least one of" not in prompts_seen[1]


def test_a_ledger_answer_the_gate_rejects_leaves_the_agents_answer(monkeypatch):
    _ledger_run()
    monkeypatch.setattr(chat_agent.ollama_client, "generate", lambda system, prompt, **kw: "bad")
    monkeypatch.setattr(chat_agent.tool_module, "_submit_chat_impl", lambda a, s=None: "REJECTED")
    monkeypatch.setattr(chat_agent, "_extract_submitted_answer", lambda m: ("AGENT ANSWER", []))
    final = chat_agent._final_step("q?", "", chat_agent._Run())
    assert final["content"] == "AGENT ANSWER"
    assert final["closing"] == "submitted"


def test_every_written_ledger_answer_is_kept_for_the_trace(monkeypatch):
    # A rejected ledger answer is not shown, so its text is kept to see why it failed.
    mem = _ledger_run()
    monkeypatch.setattr(chat_agent.ollama_client, "generate", lambda system, prompt, **kw: "bad")
    monkeypatch.setattr(chat_agent.tool_module, "_submit_chat_impl", lambda a, s=None: "REJECTED")
    monkeypatch.setattr(chat_agent, "_clean_ledger_answer", lambda a, mem: a.upper())
    assert chat_agent._ledger_answer("q?", "") is None
    assert mem.ledger_drafts == ["BAD"]
    assert mem.ledger_raw == ["bad"]  # the model's text, to trace a rule that cost words


def test_no_ledger_answer_before_the_run_has_its_searches(monkeypatch):
    # The gate rejects an answer of a run with too few searches, so writing one is waste.
    mem = _ledger_run()
    mem.searches = {"raw_search:a": 1}
    calls: list = []
    monkeypatch.setattr(chat_agent.ollama_client, "generate", lambda *a, **k: calls.append(1))
    assert chat_agent._ledger_answer("q?", "") is None
    assert calls == []


def test_the_ledger_answers_tags_are_mapped_to_the_quoted_sections(monkeypatch):
    # E4B writes "§ 31 (2)" into a tag, or a § the quote never carried: code maps each tag
    # to the quote's own tag and drops a claim no quote backs, or one naming an unread §.
    mem = _ledger_run()
    mem.ledger = [("V.md § 31", "a"), ("V.md", "b")]
    keys = {"V.md § 31 (2)": "31", "V.md § 31": "31", "V.md": "V", "V.md § 4": "4"}
    monkeypatch.setattr(chat_agent.tool_module, "ref_key", lambda r: keys[r])
    monkeypatch.setattr(
        chat_agent.tool_module,
        "_prose_unread",
        lambda mem, text, cited: [("V.md", "§ 42")] if "§ 42" in text else [],
    )
    answer = (
        "## Kriterium\n"
        "Es gilt 10 µSv [Source: V.md § 31 (2)]. Falsch [Source: V.md § 4].\n"
        "Nach § 42 gilt X [Source: V.md]. Allgemein gilt Y [Source: V.md].\n"
        "Nur falsch [Source: V.md § 4]."
    )
    assert chat_agent._clean_ledger_answer(answer, mem) == (
        "## Kriterium\nEs gilt 10 µSv [Source: V.md § 31].\nAllgemein gilt Y [Source: V.md]."
    )


def _clean_setup(monkeypatch, unnamed: list[str]) -> Any:
    mem = _ledger_run()
    mem.question = "Welches Dosiskriterium gilt?"
    mem.ledger = [("V.md § 31", "a")]
    monkeypatch.setattr(chat_agent.tool_module, "ref_key", lambda r: r.replace(" (2)", ""))
    monkeypatch.setattr(chat_agent.tool_module, "_prose_unread", lambda mem, text, cited: [])
    monkeypatch.setattr(chat_agent.tool_module, "open_refs_unnamed", lambda a, c: unnamed)
    return mem


def test_code_names_the_out_of_scope_works_under_open_points(monkeypatch):
    # The gate requires a law the cited sections rely on but the DB lacks under Open points;
    # code knows those laws, so it writes the entry instead of an LLM round.
    mem = _clean_setup(monkeypatch, ["Atomgesetzes", "TrinkwV"])
    out = chat_agent._clean_ledger_answer("Es gilt X [Source: V.md § 31].", mem)
    head, open_points = out.split("\n\n## Open points\n")
    assert head == "Es gilt X [Source: V.md § 31]."
    assert open_points.splitlines() == [
        chat_agent.CHAT_OPEN_REF_LINE["de"].format(work=w) for w in ("Atomgesetzes", "TrinkwV")
    ]
    existing = "Es gilt X [Source: V.md § 31].\n\n## Offene Punkte\n- Y bleibt offen."
    out = chat_agent._clean_ledger_answer(existing, mem)
    assert out.endswith(
        "- Y bleibt offen.\n"
        + chat_agent.CHAT_OPEN_REF_LINE["de"].format(work="Atomgesetzes")
        + "\n"
        + chat_agent.CHAT_OPEN_REF_LINE["de"].format(work="TrinkwV")
    )
    assert out.count("Offene Punkte") == 1


def test_a_list_item_emptied_by_the_clean_up_is_dropped(monkeypatch):
    mem = _clean_setup(monkeypatch, [])
    answer = "Es umfasst:\n1. Stoffe [Source: V.md § 4].\n2. Gegenstände [Source: V.md § 31]."
    assert chat_agent._clean_ledger_answer(answer, mem) == (
        "Es umfasst:\n2. Gegenstände [Source: V.md § 31]."
    )


def test_untagged_body_sentences_and_the_gaps_they_leave_are_dropped(monkeypatch):
    # E4B pads a section with a filler sentence no quote backs ("Ein wichtiger Punkt ist
    # …"); the lead, a list's intro line and the open points may go without a tag.
    mem = _clean_setup(monkeypatch, [])
    answer = (
        "Kurz: es gilt X.\n\n"
        "## Verfahren\n"
        "Ein besonderes Verfahren gibt es. Es gilt Y [Source: V.md § 31].\n\n\n\n"
        "Es umfasst:\n1. Stoffe [Source: V.md § 31].\n\n"
        "## Leer\n"
        "Ein wichtiger Punkt ist die Abgrenzung.\n\n"
        "## Open points\n"
        "Unklar bleibt Z."
    )
    assert chat_agent._clean_ledger_answer(answer, mem) == (
        "Kurz: es gilt X.\n\n"
        "## Verfahren\n"
        "Es gilt Y [Source: V.md § 31].\n\n"
        "Es umfasst:\n1. Stoffe [Source: V.md § 31].\n\n"
        "## Open points\n"
        "Unklar bleibt Z."
    )


def test_code_written_open_points_follow_prose_after_a_blank_line(monkeypatch):
    mem = _clean_setup(monkeypatch, ["Atomgesetz"])
    out = chat_agent._clean_ledger_answer(
        "Es gilt X [Source: V.md § 31].\n\n## Open points\nUnklar bleibt Z.", mem
    )
    assert out.endswith(
        "Unklar bleibt Z.\n\n" + chat_agent.CHAT_OPEN_REF_LINE["de"].format(work="Atomgesetz")
    )


def test_no_ledger_answer_without_enough_quoted_sources(monkeypatch):
    _ledger_run(n_refs=1)  # the gate needs 2 sources; a call that cannot pass is skipped
    calls: list = []
    monkeypatch.setattr(chat_agent.ollama_client, "generate", lambda *a, **k: calls.append(1))
    assert chat_agent._ledger_answer("q?", "") is None
    assert calls == []


def _stalling_run(monkeypatch, verdict: str, covered: bool = True) -> tuple[FakeLLM, list]:
    # A covered run whose model keeps thinking without new quotes, and a ledger answer the
    # gate judges with `verdict`.
    monkeypatch.setattr(chat_agent, "_preflight", lambda q: [])
    monkeypatch.setattr(chat_agent, "_covered", lambda mem: covered)
    monkeypatch.setattr(chat_agent.evidence, "render", lambda ledger, *a: "QUOTES")
    fake = _patch_llm(
        monkeypatch,
        [_ai_with_tool("think_tool", {"reflection": f"n{i}"}, f"t{i}") for i in range(6)],
    )
    monkeypatch.setattr(chat_agent.ollama_client, "generate", lambda system, prompt, **kw: "LEDGER")
    monkeypatch.setattr(chat_agent.tool_module, "_submit_chat_impl", lambda a, s=None: verdict)
    real_begin = chat_agent.run_memory.begin_run

    def begin(question: str = ""):
        mem = real_begin(question)
        mem.ledger = [(f"f{i}.md § {i}", f"Satz {i}.") for i in range(3)]
        return mem

    monkeypatch.setattr(chat_agent.run_memory, "begin_run", begin)
    return fake, list(chat_agent.run_chat_agent("q?"))


def test_a_stalled_run_stops_when_its_ledger_answer_passes_the_gate(monkeypatch):
    # Retrieval thrash: a covered run that goes STALL_TURNS turns without a new quote ends,
    # and the user gets the ledger answer that passed (written once, not again at the end).
    fake, steps = _stalling_run(monkeypatch, "ACCEPTED")
    assert len(fake.calls) == chat_agent.STALL_TURNS
    gates = [s["content"] for s in steps if s["type"] == "gate"]
    assert gates == ["ledger answer accepted", "stopped: no new evidence in 3 turns"]
    final = steps[-1]
    assert final["content"] == "LEDGER"
    assert final["note"] == chat_agent.LEDGER_NOTE


def test_a_stalled_run_whose_ledger_answer_fails_goes_on_with_the_verdict(monkeypatch):
    # Stopping on a ledger answer the gate rejects would ship a best-effort draft: the run
    # goes on instead, with the verdict as feedback, and is judged again STALL_TURNS later.
    fake, steps = _stalling_run(monkeypatch, "REJECTED: too short\nmore")
    assert len(fake.calls) > chat_agent.STALL_TURNS
    feedback = fake.calls[chat_agent.STALL_TURNS][-1]
    assert isinstance(feedback, HumanMessage)
    assert "REJECTED: too short" in feedback.content
    gates = [s["content"] for s in steps if s["type"] == "gate"]
    assert gates[0] == "ledger answer rejected: REJECTED: too short"
    assert not any(g.startswith("stopped") for g in gates)


def test_the_final_ledger_answer_reports_its_verdict_as_a_gate_step(monkeypatch):
    # Why a ledger answer did not ship must show in the trace and the bench rows.
    monkeypatch.setattr(chat_agent, "STALL_TURNS", 99)  # only the final step writes one
    _, steps = _stalling_run(monkeypatch, "REJECTED: unread § 6")
    gates = [s["content"] for s in steps if s["type"] == "gate"]
    assert gates[-1] == "ledger answer rejected: REJECTED: unread § 6"
    assert steps[-1]["type"] == "final_answer"


# --- follow-up: re-read the previous run's ledger sections ---


def test_the_final_answer_names_its_ledger_sections_most_quoted_first(monkeypatch):
    # What a follow-up carries over: section names only, never the quoted text.
    _, steps = _stalling_run(monkeypatch, "REJECTED: x", covered=False)
    final = steps[-1]
    assert final["type"] == "final_answer"
    assert final["evidence_refs"] == ["f0.md § 0", "f1.md § 1", "f2.md § 2"]


def test_most_quoted_sections_lead_and_are_capped():
    mem = chat_agent.run_memory.RunMemory(
        ledger=[("a § 1", "x"), ("b § 2", "y"), ("b § 2", "z"), *((f"c{i}", "w") for i in range(9))]
    )
    refs = chat_agent._carry_refs(mem)
    assert refs[:2] == ["b § 2", "a § 1"]
    assert len(refs) == chat_agent.CARRY_MAX


def test_a_follow_up_re_reads_the_previous_runs_sections_before_the_model_acts(monkeypatch):
    # The follow-up runs on a new question, so code re-reads the sections the last answer
    # rested on: the quotes are taken again against the new question, and the gate sees
    # them read in this run.
    monkeypatch.setattr(chat_agent, "_preflight", lambda q: [])
    monkeypatch.setattr(
        chat_agent.tool_module, "_memory_read", lambda mem, f, offset: (f"TEXT {f}", f)
    )
    fake = _patch_llm(monkeypatch, [])
    monkeypatch.setattr(chat_agent.ollama_client, "generate", lambda system, prompt, **kw: "x")
    list(chat_agent.run_chat_agent("und bei 2 mSv?", ["StrlSchG.md § 61"]))
    first = fake.calls[0]
    calls = next(m for m in first if isinstance(m, AIMessage)).tool_calls
    assert calls[0]["name"] == "raw_read"
    assert calls[0]["args"] == {"filenames": ["StrlSchG.md § 61"]}
    reads = [m.content for m in first if isinstance(m, ToolMessage)]
    assert reads == ["TEXT StrlSchG.md § 61"]


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
    assert seen == [
        ["Wann dürfen Rückstände verwertet werden?"],
        ["Rückstände verwertet"],
        ["Rückstände dürfen nur"],
    ]
    assert [m.name for m in msgs if isinstance(m, ToolMessage)] == [
        "raw_search",
        "wiki_search",
        "raw_search",
        "raw_search",
    ]
    mem = chat_agent.run_memory.current()
    assert mem is not None
    assert mem.search_count() == 2  # HyDE does not count


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


# --- unread sections a rejection names are read by code (ideas/deep-chat-levels.md) ---


def test_code_reads_the_sections_a_rejection_names_as_unread(monkeypatch):
    # E4B resubmitted one answer six times against "you cite § 100 … but never read it"
    # (~70 s) before reading it; code makes that read itself right after the rejection.
    reads: list = []
    _stub_search(monkeypatch, reads)

    verdicts = iter(["REJECTED: you cite § 100 of StrlSchV.md but never read it."])

    def gate(answer, sources=None):
        verdict = next(verdicts, "ACCEPTED: ok")
        mem = chat_agent.run_memory.current()
        if mem is not None and verdict.startswith("REJECTED"):
            mem.unread_due = ["StrlSchV.md § 100"]
        return verdict

    monkeypatch.setattr(chat_agent.tool_module, "_submit_chat_impl", gate)
    fake = _patch_llm(
        monkeypatch,
        [
            _ai_with_tool("raw_read", {"filenames": ["b.md"]}, "r1"),
            _ai_with_tool("submit_chat_answer", {"answer": "A [Source: StrlSchV.md § 100]"}, "s1"),
        ],
    )
    list(chat_agent.run_chat_agent("q?"))
    assert reads == [["b.md"], ["StrlSchV.md § 100"]]
    after = fake.calls[2]
    assert isinstance(after[-1], ToolMessage)
    assert after[-1].content == "READ TEXT"
    mem = chat_agent.run_memory.current()
    assert mem is not None
    assert mem.unread_due == []


def test_the_levels_code_reads_reach_the_model_as_raw_read_turns(monkeypatch):
    tm = chat_agent.tool_module
    monkeypatch.setattr(chat_agent, "_hyde_search", lambda q: [])
    monkeypatch.setattr(tm, "_raw_search_impl", lambda queries, **kw: "RAW HITS")
    monkeypatch.setattr(tm, "_wiki_search_impl", lambda queries, **kw: "WIKI HITS")
    seen: list = []

    def levels(question, searched):
        seen.append(searched)
        return [(["a.md § 1"], "[level 1] CORE"), (["a.md § 5 Abs. 2"], "[level 2] TERM")]

    monkeypatch.setattr(tm, "level_reads", levels)
    fake = _patch_llm(monkeypatch, [])
    monkeypatch.setattr(chat_agent.ollama_client, "generate", lambda system, prompt, **kw: "x")
    list(chat_agent.run_chat_agent("Wie werden Rückstände entlassen?"))
    assert seen == [["RAW HITS", "RAW HITS"]]  # the raw searches, not the wiki one
    first = fake.calls[0]
    reads = [
        (m.tool_call_id, m.content)
        for m in first
        if isinstance(m, ToolMessage) and m.name == "raw_read"
    ]
    assert reads == [("level-1", "[level 1] CORE"), ("level-2", "[level 2] TERM")]
