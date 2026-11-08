"""The pure metrics and the gold file of the retrieval and Deep chat study."""

import importlib.util
import json
import re
import sys
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "bench_study.py"
GOLD = ROOT / "bench" / "fixture_study_StrlSch_DE.json"


def _bench() -> ModuleType:
    spec = importlib.util.spec_from_file_location("bench_study", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["bench_study"] = module
    spec.loader.exec_module(module)
    return module


def _hit(source: str, anchor: str) -> dict[str, str]:
    return {"source": source, "anchor": anchor}


def test_a_long_sections_parts_count_as_one_rank():
    bench = _bench()
    hits = [_hit("a.md", "§ 1 (Teil 1)"), _hit("a.md", "§ 1 (Teil 2)"), _hit("a.md", "§ 2")]
    assert bench.rank_of({"file": "a.md", "section": "§ 2"}, hits) == 2
    assert bench.rank_of({"file": "a.md", "section": "§ 1"}, hits) == 1


def test_the_same_section_of_another_file_is_no_hit():
    bench = _bench()
    assert bench.rank_of({"file": "a.md", "section": "§ 1"}, [_hit("b.md", "§ 1")]) is None


def test_a_gold_part_counts_only_that_part_of_a_long_annex():
    bench = _bench()
    gold = {"file": "a.md", "section": "Anlage 4", "part": "Anlage 4 (Teil 6)"}
    assert bench.rank_of(gold, [_hit("a.md", "Anlage 4 (Teil 12)")]) is None
    hits = [
        _hit("a.md", "§ 1"),
        _hit("a.md", "Anlage 4 (Teil 12)"),
        _hit("a.md", "Anlage 4 (Teil 6)"),
    ]
    assert bench.rank_of(gold, hits) == 2


def test_section_ten_is_not_section_one():
    bench = _bench()
    assert bench.rank_of({"file": "a.md", "section": "§ 1"}, [_hit("a.md", "§ 10")]) is None


def test_a_rerank_arm_without_scores_failed_open_and_is_no_result():
    bench = _bench()
    assert bench.rerank_ran([{"top_score": -1.2}, {"top_score": 3.4}])
    assert not bench.rerank_ran([{"top_score": -1.2}, {"top_score": None}])


def test_recall_counts_gold_sections_up_to_the_cutoff():
    bench = _bench()
    assert bench.recall_at([1, 5, 11, None], 10) == 2
    assert bench.recall_at([1, 5, 11, None], 5) == 2
    assert bench.recall_at([], 10) == 0


def test_mrr_takes_the_best_gold_rank_of_a_question():
    bench = _bench()
    assert bench.mrr([4, 2, None]) == 0.5
    assert bench.mrr([None]) == 0.0


def test_ndcg_is_one_when_all_gold_leads_and_lower_when_it_trails():
    bench = _bench()
    assert bench.ndcg_at([1, 2], 10) == 1.0
    assert 0 < bench.ndcg_at([3, 4], 10) < 1
    assert bench.ndcg_at([None, 11], 10) == 0.0


def test_a_fact_is_found_across_a_line_break_and_in_any_case():
    bench = _bench()
    answer = "Der Referenzwert beträgt 300\nBecquerel je Kubikmeter."
    assert bench.fact_hits(answer, [r"300 (Becquerel|Bq)", r"30 Monate"]) == [True, False]
    assert bench.fact_hits("UNVERZÜGLICH handeln", ["unverzüglich"]) == [True]


def test_the_gold_file_is_complete_and_names_the_chosen_questions():
    gold = json.loads(GOLD.read_text(encoding="utf-8"))
    questions = gold["questions"]
    assert gold["db"] == "StrlSch_DE"
    assert [q["id"] for q in questions] == [f"F{n:02d}" for n in range(1, 11)]
    assert [q["id"] for q in questions if q["deep"]] == ["F02", "F03", "F05", "F06", "F10"]
    assert sum(len(q["gold"]) for q in questions) == 26
    for q in questions:
        assert all(re.compile(f) for f in q["facts"])
        assert q["facts"] or q["id"] == "F04"
