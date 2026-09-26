"""Time in search, tools and answers (plan Phase 5: validity order, run point in time, S4)."""

from pathlib import Path
from typing import Any

import pytest

import chunker
import lex_index
import ontology
import ontology_store
import retrieval
import run_memory
import tools

OLD = "## § 55 Grenzwert\nDer Grenzwert beträgt 20 Millisievert. Der Grenzwert gilt jährlich.\n"
NEW = (
    "## § 55 Grenzwert\nDer Grenzwert beträgt 6 Millisievert. "
    + "Die Behörde kann Ausnahmen zulassen, wenn der Betreiber dies begründet. " * 6
    + "\n"
)
Q = "Grenzwert Millisievert"


@pytest.fixture
def versions(wiki_dir: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Two versions of one ordinance; lexical search prefers the old one."""
    monkeypatch.setenv("RERANK_ENABLED", "0")
    chunker.write_chunks("StrlSchV_A.md", chunker.split(OLD))
    chunker.write_chunks("StrlSchV_B.md", chunker.split(NEW))
    lex_index.build()
    ontology_store.binding_path().write_text("modules: [core, legal-de]\n")

    def rule(subject: str, pred: str, obj: str) -> dict[str, Any]:
        return ontology.assertion(subject, pred, obj, by="rule")

    ontology_store.append_rows(
        [
            rule("src:StrlSchV_A.md", "work", "de-strlschv-2018"),
            rule("src:StrlSchV_A.md", "version_date", "2020-01-01"),
            rule("src:StrlSchV_B.md", "work", "de-strlschv-2018"),
            rule("src:StrlSchV_B.md", "version_date", "2024-10-23"),
            rule("work:de-strlschv-2018", "aliases", "StrlSchV"),
        ]
    )
    return wiki_dir


def _order(q: str, **kw: Any) -> list[str]:
    return [h["source"] for h in retrieval.search(q, top_k=5, scope="raw", **kw)]


# --- validity order in retrieval ------------------------------------------------------


def test_superseded_versions_are_demoted_not_removed(versions: Path) -> None:
    assert _order(Q, use_ontology=False) == ["StrlSchV_A.md", "StrlSchV_B.md"]
    assert _order(Q) == ["StrlSchV_B.md", "StrlSchV_A.md"]


def test_a_named_date_selects_the_version_in_force_then(versions: Path) -> None:
    assert _order(f"Was galt im Jahr 2021: {Q}")[0] == "StrlSchV_A.md"


def test_a_past_without_date_does_not_reorder(versions: Path) -> None:
    assert _order(f"Wie war damals der {Q}") == _order(
        f"Wie war damals der {Q}", use_ontology=False
    )


def test_agent_sub_queries_inherit_the_questions_point_in_time(versions: Path) -> None:
    run_memory.begin_run()
    retrieval.ontology_briefing("Was galt im Jahr 2021 nach StrlSchV zum Grenzwert?")
    assert _order(Q)[0] == "StrlSchV_A.md"  # the sub-query names no date itself
    run_memory.begin_run()
    assert _order(Q)[0] == "StrlSchV_B.md"


def test_raw_hits_say_which_version_is_in_force(versions: Path) -> None:
    out = tools.TOOL_FUNCTIONS["raw_search"](query=Q, max_results=3)
    assert "de-strlschv-2018 · 2024-10-23 · in force" in out
    assert "de-strlschv-2018 · 2020-01-01 · superseded" in out


def test_lookup_takes_a_point_in_time(versions: Path) -> None:
    now = tools.TOOL_FUNCTIONS["ontology_lookup"](term="StrlSchV")
    assert "StrlSchV_A.md (2020-01-01, superseded)" in now
    then = tools.TOOL_FUNCTIONS["ontology_lookup"](term="StrlSchV", as_of="2021-06-01")
    assert "StrlSchV_A.md (2020-01-01, in force)" in then
    assert "StrlSchV_B.md (2024-10-23, not yet in force)" in then


# --- S4: the answer check -------------------------------------------------------------


@pytest.fixture
def gate(versions: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tools, "CHAT_MIN_WORDS", 1)
    monkeypatch.setattr(tools, "CHAT_MIN_SOURCES", 1)
    run_memory.begin_run()


OLD_ANSWER = "Der Grenzwert beträgt 20 Millisievert [Source: StrlSchV_A.md §55]."


def test_an_answer_citing_only_a_superseded_version_is_rejected_once(gate: None) -> None:
    first = tools.TOOL_FUNCTIONS["submit_chat_answer"](answer=OLD_ANSWER)
    assert first.startswith("REJECTED")
    assert "StrlSchV_B.md" in first
    second = tools.TOOL_FUNCTIONS["submit_chat_answer"](answer=OLD_ANSWER)
    assert second.startswith("ACCEPTED")


def test_citing_the_current_version_passes(gate: None) -> None:
    answer = "Der Grenzwert beträgt 6 Millisievert [Source: StrlSchV_B.md]."
    assert tools.TOOL_FUNCTIONS["submit_chat_answer"](answer=answer).startswith("ACCEPTED")


def test_a_question_about_the_past_may_cite_old_versions(gate: None) -> None:
    retrieval.ontology_briefing("Was galt damals nach der alten Fassung?")
    assert tools.TOOL_FUNCTIONS["submit_chat_answer"](answer=OLD_ANSWER).startswith("ACCEPTED")


def test_the_check_is_silent_without_ontology(gate: None) -> None:
    ontology_store.binding_path().unlink()
    assert tools.TOOL_FUNCTIONS["submit_chat_answer"](answer=OLD_ANSWER).startswith("ACCEPTED")
