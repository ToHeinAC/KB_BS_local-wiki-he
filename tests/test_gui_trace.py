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
        ("call", "web_search"),
        ("result", "Result: web_search — 1 source(s)"),
        ("thought", "Plan"),
        ("notice", "Notice"),
        ("error", "Error"),
    ]
    assert items[1].detail == "{'q': 'x'}\nn"
    assert "A (https://a)" in items[2].detail


def test_steps_are_stamped_with_the_time_they_arrived() -> None:
    step = gui_trace.stamp({"type": "thought", "content": "t"})
    assert step["type"] == "thought"
    assert len(step["at"]) == 8
    assert step["at"][2] == ":"
