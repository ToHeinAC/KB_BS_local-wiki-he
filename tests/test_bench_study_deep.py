"""The pure telemetry and the arm switches of the Deep chat runs of the study."""

import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "bench_study_deep.py"


def _bench() -> ModuleType:
    spec = importlib.util.spec_from_file_location("bench_study_deep", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["bench_study_deep"] = module
    spec.loader.exec_module(module)
    return module


def _call(
    prompt: int, prefill_s: float = 1.0, answer: int = 100, reason: str = "stop"
) -> dict[str, Any]:
    return {
        "prompt_tokens": prompt,
        "prefill_s": prefill_s,
        "answer_tokens": answer,
        "answer_s": 2.0,
        "done_reason": reason,
    }


def test_the_fill_level_compares_each_prompt_with_the_window():
    bench = _bench()
    row = bench.telemetry([_call(8000), _call(16000), _call(24000)], 32000)
    assert row["llm_calls"] == 3
    assert row["fill_max"] == 0.75
    assert row["fill_mean"] == 0.5
    assert row["answer_tokens"] == 300


def test_a_cached_prompt_is_told_by_its_prefill_time_not_its_token_count():
    bench = _bench()
    cold, warm = _call(3000, prefill_s=10.0), _call(3000, prefill_s=0.04)
    row = bench.telemetry([cold, warm], 32000)
    assert row["cached_calls"] == 1
    assert row["prefill_s"] == 10.0


def test_a_prompt_at_the_window_and_a_cut_answer_are_flagged():
    bench = _bench()
    row = bench.telemetry([_call(31990), _call(100, reason="length")], 32000)
    assert row["at_window"] == 1
    assert row["cut_answers"] == 1


def test_no_call_gives_a_zero_row():
    bench = _bench()
    assert bench.telemetry([], 32000)["fill_max"] == 0


def test_the_first_usable_answer_is_the_first_acceptance():
    bench = _bench()
    steps = [
        (1.0, {"type": "tool_result", "name": "raw_search", "result": "x"}),
        (2.0, {"type": "tool_result", "name": "submit_chat_answer", "result": "REJECTED: y"}),
        (3.0, {"type": "tool_result", "name": "submit_chat_answer", "result": "ACCEPTED: z"}),
        (4.0, {"type": "final_answer", "content": "z"}),
    ]
    assert bench.first_usable_s(steps) == 3.0
    assert bench.first_usable_s(steps[:2] + steps[3:]) == 4.0
    assert bench.first_usable_s(steps[:2]) is None


def test_an_arm_switch_applies_inside_the_block_and_is_undone_after_it():
    bench = _bench()
    before = bench.tools.TERMS_MAX
    with bench.arm_switches("D2"):
        assert bench.tools.TERMS_MAX == 0
        assert bench.tools.CITING_MAX == 0
    assert before == bench.tools.TERMS_MAX


def test_the_reference_switch_silences_the_footer():
    bench = _bench()
    with bench.arm_switches("D1"):
        assert bench.tools._ref_footer(None, None, None, "siehe § 12") == ""


def test_every_arm_of_the_framework_is_known():
    bench = _bench()
    assert set(bench.ARMS) == {"E0", "E1", "E2", "E3", "E4", "D1", "D2", "D3", "D4", "O"}


def test_the_token_budget_follows_the_measured_ratio():
    bench = _bench()
    assert bench.token_budget(32768, chars=40000, tokens=10000) == (32768 - 8192) * 4
    assert bench.token_budget(32768, chars=6000, tokens=5000) == int((32768 - 8192) * 1.2)
    # Before the first call there is no measurement: the code's conservative estimate holds.
    assert bench.token_budget(32768, chars=0, tokens=0) == (32768 - 8192) * 3


def test_a_ratio_without_a_measured_history_falls_back_to_the_codes_estimate():
    bench = _bench()
    # a first fit has no history yet but follows a short generate call (query expansion)
    assert bench.token_budget(32768, chars=0, tokens=226) == (32768 - 8192) * 3


class _Resp:
    def __init__(self, prompt: int) -> None:
        self.prompt_eval_count, self.prompt_eval_duration = prompt, 10**9
        self.eval_count, self.eval_duration, self.done_reason = 10, 10**9, "stop"


def test_the_budget_pairs_each_history_with_the_chat_call_that_sent_it():
    from langchain_core.messages import HumanMessage

    bench = _bench()
    rec = bench._Recorder()
    rec.token_budget = True
    budgets: list[int] = []

    def fit(msgs: Any, trimmed: Any, budget: int) -> Any:
        budgets.append(budget)
        return msgs, trimmed

    rec._fit = fit
    window = bench.ollama_client.NUM_CTX - bench.RESERVE
    history = [HumanMessage("x" * 40000)]
    rec.note(_Resp(226))  # a generate call before the first fit
    rec.fit(history)
    rec.note(_Resp(10000), chat=True)  # the agent's call that sent this history
    rec.note(_Resp(3229))  # another generate call in between
    rec.fit(history)
    assert budgets == [window * 3, window * 4]


def _tagged_here(bench: ModuleType) -> str:
    return bench.caller(sys._getframe(), Path(__file__).parent)


def test_a_call_is_tagged_with_the_first_function_under_the_root():
    bench = _bench()
    assert bench.caller(sys._getframe(), Path(__file__).parent).endswith(
        "test_a_call_is_tagged_with_the_first_function_under_the_root"
    )
    assert _tagged_here(bench).endswith("._tagged_here")
    assert bench.caller(sys._getframe(), Path("/nonexistent")) == "?"


def test_generated_tokens_are_summed_per_caller():
    bench = _bench()
    calls = [
        {**_call(100, answer=500), "caller": "chat_agent.agent"},
        {**_call(100, answer=300), "caller": "chat_agent._write_ledger_answer"},
        {**_call(100, answer=200), "caller": "chat_agent.agent"},
    ]
    row = bench.telemetry(calls, 32000)
    assert row["tokens_by_caller"] == {
        "chat_agent.agent": 700,
        "chat_agent._write_ledger_answer": 300,
    }


def test_intermediate_text_is_counted_by_kind():
    bench = _bench()
    steps = [
        {"type": "thought", "content": "abcd"},
        {"type": "tool_call", "name": "think_tool", "args": {"reflection": "x" * 10}},
        {"type": "tool_call", "name": "submit_chat_answer", "args": {"answer": "y" * 7}},
        {"type": "tool_call", "name": "raw_search", "args": {"query": "z" * 50}},
        {"type": "tool_result", "name": "think_tool", "result": "r" * 99},
    ]
    assert bench.text_by_kind(steps) == {"thought_chars": 4, "think_chars": 10, "submit_chars": 7}


def test_each_fact_is_located_in_the_reads_and_the_ledger():
    bench = _bench()
    reads = ["Der Grenzwert beträgt 20 Millisievert.", "Im Einzelfall 50 mSv."]
    ledger = [("StrlSchG.md § 78", "Der Grenzwert beträgt 20 Millisievert.")]
    row = bench.fact_trace([r"\b20 (Millisievert|mSv)", r"\b50 (Millisievert|mSv)"], reads, ledger)
    assert row == {"facts_in_reads": [True, True], "facts_in_ledger": [True, False]}


def _chunks(file: str) -> list[dict[str, Any]]:
    assert file == "G.md"
    return [
        {"anchor": "§ 1", "text": "Erster Satz gilt. Zweiter Satz nennt 5 mSv."},
        {"anchor": "§ 2", "text": "Anderer Paragraf."},
        {"anchor": "Anlage 4 (Teil 13)", "text": "Tabelle:\n1. Cs-137 1 E+4\n2. Co-60 1 E+5"},
        {"anchor": "Anlage 4 (Teil 14)", "text": "Nächster Teil."},
    ]


def test_the_oracle_ledger_holds_every_sentence_of_the_gold_sections_only():
    bench = _bench()
    gold = [
        {"file": "G.md", "section": "§ 1", "heading": "x"},
        {"file": "G.md", "section": "Anlage 4", "part": "Anlage 4 (Teil 13)", "heading": "y"},
    ]
    ledger = bench.oracle_ledger(gold, _chunks)
    refs = {ref for ref, _ in ledger}
    text = " ".join(s for _, s in ledger)
    assert refs == {"G.md § 1", "G.md Anlage 4"}
    for kept in ("Erster Satz gilt.", "Zweiter Satz nennt 5 mSv.", "Cs-137 1 E+4", "Co-60 1 E+5"):
        assert kept in text
    for other in ("Anderer", "Nächster"):
        assert other not in text


def test_an_oracle_run_answers_from_the_gold_ledger_and_traces_its_facts(monkeypatch: Any):
    bench = _bench()
    seen: list[list[tuple[str, str]]] = []

    def write(mem: Any, question: str, directive: str) -> str:
        seen.append(list(mem.ledger))
        return "Es gelten 5 mSv."

    monkeypatch.setattr(bench.chunker, "load_chunks", _chunks)
    monkeypatch.setattr(bench.chat_agent, "_write_ledger_answer", write)
    item = {
        "id": "X",
        "question": "Welcher Wert gilt?",
        "gold": [{"file": "G.md", "section": "§ 1", "heading": "x"}],
        "facts": [r"\b5 mSv", r"\b7 mSv"],
    }
    row = bench.run_once(item, "O", 0, bench._Recorder())
    assert seen
    assert {ref for ref, _ in seen[0]} == {"G.md § 1"}
    assert row["closing"] == "oracle"
    assert row["facts"] == [True, False]
    assert row["facts_in_ledger"] == [True, False]
    assert row["ledger"] == [list(q) for q in seen[0]]
