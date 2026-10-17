"""The timeline of an agent run, shared by Chat and Research (src/gui_trace.py)."""

import gui_trace


def test_trace_items_name_the_terminal_call_and_summarise_results() -> None:
    items = gui_trace.trace_items(
        [
            {"type": "tool_call", "name": "ResearchComplete", "args": {}, "terminal": True},
            {"type": "tool_call", "name": "web_search", "args": {"q": "x"}, "note": "n"},
            {
                "type": "tool_result",
                "name": "web_search",
                "result": "text",
                "sources": [{"url": "https://a", "title": "A"}],
            },
            {"type": "thought", "content": "t", "label": "Plan"},
            {"type": "notice", "content": "fell back"},
            {"type": "error", "content": "bad"},
            {"type": "final_answer", "content": "A"},
        ]
    )
    assert [(i.kind, i.title) for i in items] == [
        ("done", "ResearchComplete — research phase finished"),
        ("call", "web_search — q: x"),
        ("result", "Result: web_search — 1 source(s)"),
        ("thought", "Plan"),
        ("notice", "Notice"),
        ("error", "Error"),
    ]
    assert items[1].detail == "q: x\nn"
    assert "A (https://a)" in items[2].detail


def test_steps_are_stamped_with_the_time_they_arrived() -> None:
    step = gui_trace.stamp({"type": "thought", "content": "t"})
    assert step["type"] == "thought"
    assert len(step["at"]) == 8
    assert step["at"][2] == ":"


RAW = (
    "## Raw query: Grenzwert\n"
    "[Raw hit 1]\nfile: KI/law.md §3\nchunk_id: 7\nscore: 1.2  matched: grenzwert\n"
    "excerpt: " + "x" * 3000 + "\n---\n"
    "[Raw hit 2]\nfile: KI/permit.md\nchunk_id: 9\nscore: 0.8  matched: grenzwert\n"
    "excerpt: y\n---"
)


def test_a_search_result_is_summarised_and_kept_in_full() -> None:
    (item,) = gui_trace.trace_items([{"type": "tool_result", "name": "raw_search", "result": RAW}])
    assert item.title == "Result: raw_search — 2 hit(s)"
    assert item.detail == "KI/law.md §3\nKI/permit.md"
    assert item.full == RAW  # nothing cut: the whole output can be looked up


def test_reads_misses_and_other_results_get_a_one_line_summary() -> None:
    def title(result: str) -> str:
        step = {"type": "tool_result", "name": "t", "result": result}
        return gui_trace.trace_items([step])[0].title

    assert title("## Raw file: KI/law.md (offset 0/900)\ntext") == (
        "Result: t — read KI/law.md (offset 0/900)"
    )
    assert title("## Wiki query: q\n(no results)") == "Result: t — no results"
    assert title("\nACCEPTED: 120 words, 2 sources cited.") == (
        "Result: t — ACCEPTED: 120 words, 2 sources cited."
    )
    assert title("Result 1: Title A\nCite as: [Source: https://a]\n---") == ("Result: t — 1 hit(s)")


def test_memory_hits_section_maps_and_the_gate_are_labelled() -> None:
    def title(result: str) -> str:
        return gui_trace.summarize(result)

    advanced = (
        "## Raw file: StrlSchG.md § 62 [memory: repeat of step 3 → serving the next unread "
        "best match]\nEntlassung …"
    )
    assert title(advanced) == "repeat of step 3 → served StrlSchG.md § 62"
    mapped = (
        "## Raw file: StrlSchG.md — section map (218 sections; best matches read in full)\n\n"
        "## Raw file: StrlSchG.md § 62\nText\n\n## Raw file: StrlSchG.md § 61\nText"
    )
    assert title(mapped) == "section map of StrlSchG.md → read § 62, § 61"
    explored = "## Raw file: a.md\n[memory] a.md fully explored for this question — submit"
    assert title(explored) == "a.md fully explored"
    (gate,) = gui_trace.trace_items([{"type": "gate", "content": "rejected (retry 1/2): R"}])
    assert (gate.kind, gate.title) == ("notice", "Quality gate — rejected (retry 1/2): R")
