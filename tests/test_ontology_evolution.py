"""Evolving an ontology (plan Phase 7): editor tables, cue tester, re-classify, schema proposals."""

from pathlib import Path
from typing import Any

import pytest

import ontology
import ontology_bundle as ob
import ontology_evolution as ev
import ontology_store

HEADS = Path(__file__).resolve().parents[1] / "bench" / "ontology_detect"


@pytest.fixture(scope="module")
def shared() -> dict[str, Any]:
    return ontology_store.shared_modules()


@pytest.fixture(scope="module")
def schema(shared: dict[str, Any]) -> ontology.Schema:
    built, errors = ontology.build_schema([shared["core"], shared["legal-de"]])
    assert built is not None, errors
    return built


def _memo() -> dict[str, Any]:
    return {
        "broader": "report",
        "labels": {"en": "Memo", "de": "Notiz"},
        "definition": "Internal memo",
        "cues": [r"\bNotiz\b", r"\bMemo\b"],
        "rank": 9,
    }


STATE: dict[str, Any] = {
    "schema": {
        "modules": ["core", "legal-de"],
        "local": {"version": "0.1.0", "classes": {"memo": _memo()}},
    },
    "facts": {
        "sources": {
            "a.md": {"class": "memo", "work": "w-a", "cites": ["w-b"]},
            "b.md": {"class": "report"},
        }
    },
}


# --- editor tables --------------------------------------------------------------------


def test_tables_round_trip_to_the_same_ontology() -> None:
    classes, facts = ev.editor_tables(STATE, ["a.md", "b.md", "c.md"])
    assert classes == [
        {
            "id": "memo",
            "broader": "report",
            "label_de": "Notiz",
            "label_en": "Memo",
            "definition": "Internal memo",
            "cues": r"\bNotiz\b || \bMemo\b",
            "deprecated": False,
            "replaced_by": "",
        }
    ]
    assert [f["source"] for f in facts] == ["a.md", "b.md", "c.md"]  # untyped sources too
    state, errors = ev.state_from_tables(STATE, classes, facts)
    assert errors == []
    assert ob.revision_hash(state) == ob.revision_hash(STATE)
    assert state["schema"]["local"]["classes"]["memo"]["rank"] == 9  # not in the table, kept
    assert state["facts"]["sources"]["a.md"]["cites"] == ["w-b"]  # relations kept


def test_table_edits_become_state_changes() -> None:
    classes, facts = ev.editor_tables(STATE, ["a.md", "b.md", "c.md"])
    classes.append(
        {
            "id": "note",
            "broader": "report",
            "label_de": "Vermerk",
            "label_en": "Note",
            "definition": "A short note",
            "cues": "",
            "deprecated": False,
            "replaced_by": "",
        }
    )
    facts[2]["class"] = "note"
    facts[0]["work"] = ""
    state, errors = ev.state_from_tables(STATE, classes, facts)
    assert errors == []
    assert state["schema"]["local"]["classes"]["note"]["labels"] == {"de": "Vermerk", "en": "Note"}
    assert state["facts"]["sources"]["c.md"] == {"class": "note"}
    assert "work" not in state["facts"]["sources"]["a.md"]


def test_rows_without_an_id_are_errors_blank_rows_are_ignored() -> None:
    classes, facts = ev.editor_tables(STATE, ["a.md"])
    classes += [{"id": "", "definition": "x"}, {"id": ""}]
    _, errors = ev.state_from_tables(STATE, classes, facts)
    assert errors == ["class row 2: `id` is required"]


def test_deprecating_a_class_migrates_its_facts(shared: dict[str, Any]) -> None:
    classes, facts = ev.editor_tables(STATE, ["a.md", "b.md"])
    classes[0].update(deprecated=True, replaced_by="report")
    state, _ = ev.state_from_tables(STATE, classes, facts)
    plan = ob.plan_import(
        state,
        base=STATE,
        current=STATE,
        shared=shared,
        known_sources={"a.md", "b.md"},
        referenced={"memo"},
    )
    assert plan.status == "ready", plan.errors
    assert plan.state["facts"]["sources"]["a.md"]["class"] == "report"


# --- cue tester -------------------------------------------------------------------------


def test_the_cue_tester_counts_and_shows_matching_lines() -> None:
    heads = {"a.md": "Titel\nInterne Notiz zur Wartung", "b.md": "Bericht", "c.md": "Notizbuch"}
    matches, error = ev.cue_matches(r"\bNotiz\b", heads)
    assert error is None
    assert matches == [("a.md", "Interne Notiz zur Wartung")]


@pytest.mark.parametrize(("cue", "needle"), [("(", "regex"), ("x*", "empty"), ("", "empty")])
def test_the_cue_tester_rejects_bad_patterns(cue: str, needle: str) -> None:
    matches, error = ev.cue_matches(cue, {"a.md": "x"})
    assert matches == []
    assert error is not None
    assert needle in error


# --- re-classify (derived layer) ---------------------------------------------------------


def _rows(*rows: dict[str, Any]) -> list[dict[str, Any]]:
    for i, row in enumerate(rows, 1):
        row["id"] = f"a-{i:06d}"
    return list(rows)


def test_reclassify_updates_rule_facts_and_keeps_user_decisions(schema: ontology.Schema) -> None:
    heads = {
        "v.md": (HEADS / "strlschv_2018.md").read_text(encoding="utf-8"),
        "g.md": (HEADS / "gg.md").read_text(encoding="utf-8"),
        "n.md": "Notizen ohne Klasse",
    }
    rows = _rows(
        ontology.assertion("src:v.md", "class", "federal-act", by="rule"),  # outdated cue result
        ontology.assertion("src:g.md", "class", "report", by="user"),  # a user decision
        ontology.assertion("src:n.md", "class", "permit", by="rule"),  # cue no longer matches
    )
    changes = ev.reclassify_changes(heads, schema, rows)
    got = {(c["source"], c["predicate"], c["action"], c["new"]) for c in changes}
    assert ("v.md", "class", "update", "ordinance") in got
    assert ("v.md", "work", "update", "de-strlschv-2018") in got
    assert ("g.md", "class", "kept-user", "constitution") in got
    assert ("n.md", "class", "withdraw", None) in got
    new_rows = ev.reclassify_rows(changes, rows)
    facts = ontology.project(rows + new_rows, set())
    assert facts["src:v.md"]["class"] == "ordinance"
    assert facts["src:g.md"]["class"] == "report"  # the user decision survives
    assert "class" not in facts.get("src:n.md", {})


# --- schema proposals from the model ------------------------------------------------------

HEAD = "Prüfbericht KTA-Wiederholungsprüfung\n\nDieser Prüfbericht dokumentiert die Prüfung."


def _answer(**kw: str) -> str:
    base = {
        "id": "test-report",
        "broader": "report",
        "label_de": "Prüfbericht",
        "label_en": "Test report",
        "definition": "Report of a recurring test",
        "cue": r"\bPrüfbericht\b",
    }
    base.update(kw)
    import json

    return "```json\n" + json.dumps(base, ensure_ascii=False) + "\n```"


def test_a_valid_class_suggestion_becomes_a_schema_proposal(schema: ontology.Schema) -> None:
    proposal, reason = ev.parse_class_suggestion(_answer(), HEAD, schema)
    assert reason == ""
    assert proposal is not None
    assert proposal["id"] == "test-report"
    assert proposal["spec"]["cues"] == [r"\bPrüfbericht\b"]
    assert proposal["evidence"] == "Prüfbericht KTA-Wiederholungsprüfung"


@pytest.mark.parametrize(
    ("change", "needle"),
    [
        ({"id": "report"}, "exists"),
        ({"id": "Bad Id"}, "id"),
        ({"broader": "nowhere"}, "broader"),
        ({"cue": r"\bGutachten\b"}, "does not match"),
        ({"cue": "("}, "regex"),
        ({"definition": "two\nlines"}, "definition"),
    ],
)
def test_invalid_suggestions_are_rejected_with_a_reason(
    schema: ontology.Schema, change: dict[str, str], needle: str
) -> None:
    proposal, reason = ev.parse_class_suggestion(_answer(**change), HEAD, schema)
    assert proposal is None
    assert needle in reason


def test_unparseable_answers_are_rejected(schema: ontology.Schema) -> None:
    assert ev.parse_class_suggestion("no json", HEAD, schema)[0] is None
