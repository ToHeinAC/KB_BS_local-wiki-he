"""Query vocabulary: the acronym guard, the user's own gloss and ontology terms.

A capitalised acronym ("NORM") must not match the ordinary word ("Norm" = standard), a
gloss the user writes in brackets is searched with the acronym, and an ontology term
bridges the user's word to the sources' word ("NORM" -> "Rückstände").
"""

from pathlib import Path
from typing import Any

import pytest

import chunker
import gloss
import lex_index
import ontology_query
import ontology_store
import retrieval
import run_memory
import tools

DIN = """\
## 1 Anwendungsbereich
Diese Norm gilt für Laboratorien. Die Norm legt bauliche Anforderungen fest.
Die Entsorgung ist nicht Gegenstand dieser Norm.
"""
LAW = """\
## § 61 Anfall von Rückständen
Bei NORM ist die Entsorgung anzuzeigen. Rückstände sind zu überwachen.
"""
RESIDUE = """\
## § 62 Entlassung von Rückständen aus der Überwachung
Rückstände werden entlassen, wenn die Überwachungsgrenzen eingehalten sind.
"""
NATURAL = """\
## § 5 Begriffe
Natürliche Radioaktivität stammt aus Radionukliden natürlichen Ursprungs.
"""
QUESTION = "Wie kann NORM (natürliche Radioaktivität) sicher entsorgt werden?"
TERMS = """\
modules: [core]
local:
  terms:
    rueckstaende:
      pref: Rückstände
      alt: [NORM, natürlich vorkommende radioaktive Stoffe]
      expand: [Rückstand, Überwachungsgrenze, Entlassung]
"""


@pytest.fixture
def corpus(wiki_dir: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("RERANK_ENABLED", "0")
    for name, text in (
        ("DIN.md", DIN),
        ("Law.md", LAW),
        ("Residue.md", RESIDUE),
        ("Natural.md", NATURAL),
    ):
        chunker.write_chunks(name, chunker.split(text))
    lex_index.build()
    return wiki_dir


def _sources(hits: list[dict[str, Any]]) -> list[str]:
    return [h["source"] for h in hits]


# --- pure detection -----------------------------------------------------------------


def test_acronyms_are_capitalised_words_in_a_mixed_case_query() -> None:
    assert gloss.acronyms("Wie wird NORM in DE entsorgt") == ["NORM", "DE"]
    assert gloss.acronyms("Norm StrlSchG") == []
    assert gloss.acronyms("NORM ENTSORGUNG") == []  # an all-caps query has no acronyms


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (QUESTION, [("NORM", "natürliche Radioaktivität")]),
        (
            "Entsorgung natürlicher Radioaktivität (NORM) in DE",
            [("NORM", "natürlicher Radioaktivität")],
        ),
        ("Was regelt § 62 (Entlassung)?", []),
        ("StrlSchG (2017) und StrlSchV", []),
        ("Norm (Standard)", []),
    ],
)
def test_gloss_pairs_an_acronym_with_the_users_explanation(
    text: str, expected: list[tuple[str, str]]
) -> None:
    assert gloss.find(text) == expected


# --- S2b: acronym guard in the lexical arm --------------------------------------------


def test_capitalised_acronym_does_not_match_the_ordinary_word(corpus: Path) -> None:
    hits = lex_index.query("NORM Entsorgung", top_k=10, scope="raw")
    assert _sources(hits)[0] == "Law.md"
    din = [h for h in hits if h["source"] == "DIN.md"]
    assert all("norm" not in h["matched_terms"] for h in din)


def test_a_lowercase_word_still_matches_every_spelling(corpus: Path) -> None:
    assert _sources(lex_index.query("Norm Laboratorien", top_k=10, scope="raw"))[0] == "DIN.md"


# --- S2c: the user's gloss -------------------------------------------------------------


def test_gloss_from_the_run_question_is_searched_with_the_acronym(corpus: Path) -> None:
    assert "Natural.md" not in _sources(retrieval.search("NORM", top_k=10, scope="raw"))
    run_memory.begin_run(QUESTION)
    assert "Natural.md" in _sources(retrieval.search("NORM", top_k=10, scope="raw"))


def test_briefing_states_the_gloss_without_an_ontology(corpus: Path) -> None:
    brief, _ = retrieval.ontology_briefing(QUESTION)
    assert '"NORM"' in brief
    assert "natürliche Radioaktivität" in brief
    assert retrieval.ontology_briefing("Wie wird Norm entsorgt?")[0] == ""


# --- S1: ontology terms ----------------------------------------------------------------


def test_term_bridges_the_users_word_to_the_sources_word(corpus: Path) -> None:
    q = "NORM Entsorgung"
    assert "Residue.md" not in _sources(retrieval.search(q, top_k=10, scope="raw"))
    ontology_store.binding_path().write_text(TERMS)
    on = retrieval.search(q, top_k=10, scope="raw")
    assert "Residue.md" in _sources(on)
    assert _sources(on)[0] in {"Law.md", "Residue.md"}


def test_acronym_label_matches_only_in_capitals(corpus: Path) -> None:
    ontology_store.binding_path().write_text(TERMS)
    view = ontology_store.view()
    assert view is not None
    assert [t for _, t in ontology_query.match_terms("NORM entsorgen", view)] == ["rueckstaende"]
    assert ontology_query.match_terms("Norm entsorgen", view) == []
    assert ontology_query.match_terms("natürlich vorkommende radioaktive Stoffe", view)


def test_question_without_a_term_is_unchanged(corpus: Path) -> None:
    q = "Laboratorien Anforderungen"
    before = retrieval.search(q, top_k=10, scope="raw")
    ontology_store.binding_path().write_text(TERMS)
    assert retrieval.search(q, top_k=10, scope="raw") == before


def test_briefing_names_the_sources_word(corpus: Path) -> None:
    ontology_store.binding_path().write_text(TERMS)
    brief, _ = retrieval.ontology_briefing("Wie wird NORM entsorgt?")
    assert "Rückstände" in brief
    assert "Überwachungsgrenze" in brief


STATUTE = """\
## § 1 Begriffsbestimmungen
Entsorgt im Sinne dieses Gesetzes ist, was entsorgt wird.

## § 61 Anfall von Rückständen
Rückstände sind zu überwachen, solange die Überwachungsgrenze überschritten ist.
"""


def test_term_ranks_a_statutes_sections_on_a_bare_read(corpus: Path) -> None:
    chunker.write_chunks("Statute.md", chunker.split(STATUTE))
    lex_index.build()
    mem = run_memory.begin_run("Wie wird NORM entsorgt?")
    assert tools._ranked_unread(mem, tools._target("Statute.md"))[0]["anchor"].startswith("§ 1 ")
    ontology_store.binding_path().write_text(TERMS)
    assert tools._ranked_unread(mem, tools._target("Statute.md"))[0]["anchor"].startswith("§ 61")
