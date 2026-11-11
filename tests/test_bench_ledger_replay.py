"""The pure ledger transforms the answer-replay bench compares."""

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "bench_ledger_replay.py"


def _bench() -> ModuleType:
    spec = importlib.util.spec_from_file_location("bench_ledger_replay", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["bench_ledger_replay"] = module
    spec.loader.exec_module(module)
    return module


CORE = ("A.md § 1", "Wer misst, richtet sich nach den Arbeitsfeldern nach Anlage 8.")
TERM = ("A.md § 5 Abs. 2", "Arbeitsplatz ist jeder Ort, an dem eine Person tätig ist.")
CORE_2 = ("A.md § 1", "Die Messung erfolgt innerhalb von 18 Monaten.")
ANNEX = ("A.md Anlage 8", "1. Untertägige Bergwerke, 2. Radonheilbäder")


def test_a_section_s_quotes_stay_together_and_a_referenced_one_follows_its_referrer():
    ledger, levels = _bench().grouped([CORE, TERM, CORE_2, ANNEX], [1, 2, 1, 0])
    assert ledger == [CORE, CORE_2, ANNEX, TERM]
    assert levels == [1, 1, 1, 2]


def test_only_a_section_of_the_same_file_and_number_is_pulled_after_its_referrer():
    other = ("B.md Anlage 8", "Liste B")
    near = ("A.md § 12", "Zwölf.")
    core = ("A.md § 1", "Nach § 127 und § 12a sowie Anlage 8 gilt.")
    ledger, levels = _bench().grouped([core, other, near], [1, 0, 0])
    assert ledger == [core, other, near]
    assert levels == [1, 0, 0]


def test_pruning_keeps_the_core_and_required_terms_and_drops_the_quotes_off_the_question():
    off = ("A.md § 9", "Die Behörde führt ein Register über alle Vorgänge.")
    on = ("A.md § 9", "Die Messung von Radon am Arbeitsplatz ist zu dokumentieren.")
    question = "Wann muss am Arbeitsplatz Radon gemessen werden?"
    ledger, levels = _bench().pruned([CORE, TERM, off, on], [1, 2, 2, 3], question, {TERM[0]})
    assert ledger == [CORE, TERM, on]
    assert levels == [1, 2, 3]


def test_the_omitted_quotes_are_figures_and_referenced_sections_the_answer_never_cites():
    deadline = ("A.md § 9", "Die Frist beträgt sechs Monate.")
    general = ("A.md § 7", "Das Gesetz dient dem Schutz.")
    answer = "Es ist zu messen [Source: A.md § 1]."
    assert _bench().omitted(answer, [CORE, deadline, general, ANNEX]) == [deadline, ANNEX]


def test_a_section_cited_only_as_an_open_point_counts_as_omitted():
    answer = "Messen [Source: A.md § 1].\n\n## Offene Punkte\n- Unklar [Source: A.md Anlage 8]."
    assert _bench().omitted(answer, [CORE, ANNEX]) == [ANNEX]


def test_a_cited_section_is_not_omitted():
    answer = "Bergwerke [Source: A.md Anlage 8] und Frist [Source: A.md § 1]."
    assert _bench().omitted(answer, [CORE, CORE_2, ANNEX]) == []


def test_the_omitted_quotes_go_before_the_open_points_in_the_question_s_language():
    answer = "Antwort [Source: A.md § 1].\n\n## Offene Punkte\n- Nichts."
    out = _bench().with_omitted(answer, [ANNEX], "de")
    assert out == (
        "Antwort [Source: A.md § 1].\n\n## Weitere Belege aus den Quellen\n"
        '- "1. Untertägige Bergwerke, 2. Radonheilbäder" [Source: A.md Anlage 8]\n\n'
        "## Offene Punkte\n- Nichts."
    )
    assert _bench().with_omitted("Answer.", [], "en") == "Answer."
    assert (
        _bench()
        .with_omitted("Answer.", [ANNEX], "en")
        .endswith(
            '## Further evidence from the sources\n- "1. Untertägige Bergwerke, 2. Radonheilbäder"'
            " [Source: A.md Anlage 8]"
        )
    )


def test_the_gold_ledger_keeps_only_the_gold_sections():
    gold = [{"file": "A.md", "section": "§ 1"}, {"file": "A.md", "section": "Anlage 8"}]
    assert _bench().gold_only([CORE, TERM, ANNEX], gold) == [CORE, ANNEX]
