"""The pure metrics of the live Deep chat bench (scripts/bench_deep_chat.py)."""

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "bench_deep_chat.py"


def _bench() -> ModuleType:
    spec = importlib.util.spec_from_file_location("bench_deep_chat", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["bench_deep_chat"] = module
    spec.loader.exec_module(module)
    return module


def test_the_exit_path_names_how_the_answer_got_out():
    bench = _bench()
    submit = {"type": "tool_result", "name": "submit_chat_answer", "result": "ACCEPTED: 9"}
    assert bench.exit_path([submit]) == "submit-accepted"
    assert bench.exit_path([{"type": "gate", "content": "accepted"}]) == "prose-gated-accepted"
    assert bench.exit_path([{"type": "gate", "content": "rejected, retries used up"}]) == (
        "best-effort"
    )


def test_memory_counts_tell_auto_advances_from_empty_stubs():
    bench = _bench()
    steps = [
        {"type": "tool_result", "name": "raw_read", "result": "## Raw file: a.md § 2 [memory: x"},
        {
            "type": "tool_result",
            "name": "raw_read",
            "result": "[memory] a.md fully explored for this question — submit",
        },
        {"type": "tool_call", "name": "raw_read", "args": {}},
    ]
    assert bench.memory_counts(steps) == {"tool_calls": 1, "advances": 1, "empty_stubs": 1}


def test_quote_overlap_is_the_share_of_citing_sentences_that_quote_the_section():
    bench = _bench()
    text = "Rueckstaende werden auf Antrag aus der Ueberwachung entlassen wenn die Dosis klein ist."
    answer = (
        "Sie werden auf Antrag aus der Ueberwachung entlassen [Source: StrlSchG.md §62]. "
        "Nach § 62 gilt zudem etwas ganz anderes ohne jedes Zitat. "
        "Dieser Satz nennt die Vorschrift nicht."
    )
    assert bench.quote_overlap(answer, "§ 62", text) == 0.5
    assert bench.quote_overlap("Nichts dazu.", "§ 62", text) is None
