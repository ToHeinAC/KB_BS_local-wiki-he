"""Time in the ontology (plan Phase 5): time intent, validity, versions (pure)."""

from datetime import date
from typing import Any

import pytest

import ontology
import ontology_query as oq
import ontology_store
import ontology_time as ot

TODAY = date(2026, 9, 26)


@pytest.fixture(scope="module")
def view() -> oq.View:
    shared = ontology_store.shared_modules()
    schema, errors = ontology.build_schema([shared["core"], shared["legal-de"]])
    assert schema is not None, errors
    facts: dict[str, Any] = {
        "sources": {
            "StrlSchV_2001.md": {"work": "de-strlschv-2001", "version_date": "2012-02-24"},
            "StrlSchV_A.md": {"work": "de-strlschv-2018", "version_date": "2020-01-01"},
            "StrlSchV_B.md": {"work": "de-strlschv-2018", "version_date": "2024-10-23"},
            "notes.md": {"class": "report"},
            "undated.md": {"work": "de-atg-1959"},
        },
        "works": {
            "de-strlschv-2001": {"aliases": ["StrlSchV"], "in_force_until": "2018-12-30"},
            "de-strlschv-2018": {"aliases": ["StrlSchV"], "in_force_from": "2018-12-31"},
        },
    }
    return oq.build_view(
        schema, facts, {"dosis.md": ["StrlSchV_A.md"], "neu.md": ["StrlSchV_B.md"]}
    )


# --- time intent ---------------------------------------------------------------------


@pytest.mark.parametrize(
    ("question", "as_of", "past"),
    [
        ("Was galt am 01.06.2017 nach StrlSchV?", date(2017, 6, 1), True),
        ("Was galt am 1. Juni 2017?", date(2017, 6, 1), True),
        ("Rechtslage as of 2017-06-01", date(2017, 6, 1), True),
        ("Was galt im Jahr 2017 für die Freigabe?", date(2017, 12, 31), True),
        ("Stand 2019: Grenzwerte", date(2019, 12, 31), True),
        ("Was regelte die alte Fassung dazu?", TODAY, True),
        ("Wie war das damals geregelt?", TODAY, True),
        ("Was verlangt die Richtlinie 2013/59/Euratom?", TODAY, False),
        ("Grenzwerte nach StrlSchV", TODAY, False),
        ("Was gilt ab 2030?", date(2030, 12, 31), False),
    ],
)
def test_time_intent_is_detected_in_code(question: str, as_of: date, past: bool) -> None:
    intent = ot.time_intent(question, TODAY)
    assert (intent.as_of, intent.past) == (as_of, past)
    assert intent.explicit == (as_of != TODAY)


# --- validity ------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("source", "as_of", "expected"),
    [
        ("StrlSchV_B.md", TODAY, "valid"),
        ("StrlSchV_A.md", TODAY, "superseded"),
        ("StrlSchV_A.md", date(2022, 1, 1), "valid"),
        ("StrlSchV_B.md", date(2022, 1, 1), "not-yet"),
        ("StrlSchV_2001.md", date(2017, 6, 1), "valid"),
        ("StrlSchV_2001.md", TODAY, "superseded"),  # the work ended 2018-12-30
        ("StrlSchV_A.md", date(2017, 6, 1), "not-yet"),
        ("notes.md", TODAY, "unknown"),
        ("undated.md", TODAY, "unknown"),
        ("missing.md", TODAY, "unknown"),
    ],
)
def test_validity_of_a_version(view: oq.View, source: str, as_of: date, expected: str) -> None:
    assert ot.validity(view, source, as_of) == expected


def test_current_expression_follows_the_date(view: oq.View) -> None:
    assert ot.current_expression(view, "de-strlschv-2018", TODAY) == "StrlSchV_B.md"
    assert ot.current_expression(view, "de-strlschv-2018", date(2022, 1, 1)) == "StrlSchV_A.md"
    assert ot.current_expression(view, "de-strlschv-2018", date(2017, 1, 1)) is None


def test_an_ambiguous_alias_resolves_to_the_work_in_force(view: oq.View) -> None:
    frame = oq.resolve("Was galt am 01.06.2017 nach StrlSchV?", view, today=TODAY)
    assert frame is not None
    assert frame.works == ("de-strlschv-2001",)
    assert frame.as_of == "2017-06-01"
    frame = oq.resolve("Grenzwerte nach StrlSchV", view, today=TODAY)
    assert frame is not None
    assert frame.works == ("de-strlschv-2018",)
    assert frame.as_of == TODAY.isoformat()


def test_outdated_pages_rest_only_on_superseded_versions(view: oq.View) -> None:
    assert ot.outdated_pages(view, TODAY) == ["dosis.md"]
    assert ot.outdated_pages(view, date(2022, 1, 1)) == []


# --- ordering and labels -------------------------------------------------------------


def test_superseded_hits_are_demoted_not_removed(view: oq.View) -> None:
    hits = [{"source": s} for s in ("StrlSchV_A.md", "notes.md", "StrlSchV_B.md")]
    ordered = ot.validity_order(hits, view, TODAY)
    assert [h["source"] for h in ordered] == ["notes.md", "StrlSchV_B.md", "StrlSchV_A.md"]
    assert ot.validity_order(hits, view, date(2022, 1, 1))[0]["source"] == "StrlSchV_A.md"


def test_badges_and_briefing_carry_validity(view: oq.View) -> None:
    assert oq.badge(view, "StrlSchV_A.md", TODAY).endswith("superseded")
    assert oq.badge(view, "StrlSchV_B.md", TODAY).endswith("in force")
    frame = oq.resolve("Grenzwerte nach StrlSchV", view, today=TODAY)
    text = oq.briefing(frame, view)
    assert "StrlSchV_B.md (2024-10-23, in force)" in text
    assert "StrlSchV_A.md (2020-01-01, superseded)" in text
    assert f"Point in time: {TODAY.isoformat()} (today)" in text
    past = oq.briefing(
        oq.resolve("Was galt 2021 laut Stand 2021 nach StrlSchV?", view, today=TODAY), view
    )
    assert "Point in time: 2021-12-31 (from the question)" in past
