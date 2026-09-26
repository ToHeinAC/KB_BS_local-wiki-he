"""Evolving an ontology end to end (plan Phase 7): re-classify, editor, class suggestions."""

import json
from pathlib import Path
from typing import Any

import pytest

import auth
import dedup
import ollama_client
import ontology
import ontology_evolution as ev
import ontology_store
import wiki_engine

HEADS = Path(__file__).resolve().parents[1] / "bench" / "ontology_detect"
REPORT = "Prüfbericht KTA-Wiederholungsprüfung\n\nDieser Prüfbericht dokumentiert die Prüfung."


@pytest.fixture
def db(wiki_dir: Path) -> Path:
    ontology_store.binding_path().write_text("modules: [core, legal-de]\n")
    auth.add_user("maint", "pw", ["test"], maintains=["test"])
    auth.add_user("reader", "pw", ["test"])
    dedup.register_file((HEADS / "strlschv_2018.md").read_bytes(), "v.md")
    dedup.register_file((HEADS / "gg.md").read_bytes(), "g.md")
    dedup.register_file(REPORT.encode(), "r.md")
    ontology_store.append_rows(
        [
            ontology.assertion("src:v.md", "class", "federal-act", by="rule"),
            ontology.assertion("src:g.md", "class", "report", by="user", user="maint"),
        ]
    )
    return wiki_dir


def _facts() -> dict[str, Any]:
    return ontology_store.current_state()["facts"].get("sources", {})


# --- re-classify ---------------------------------------------------------------------


def test_reclassify_dry_run_writes_nothing(db: Path) -> None:
    before = ontology_store.read_rows()
    changes, row = wiki_engine.reclassify("maint", apply=False)
    assert row is None
    assert ontology_store.read_rows() == before
    assert {(c["source"], c["action"]) for c in changes} >= {
        ("v.md", "update"),
        ("g.md", "kept-user"),
    }


def test_reclassify_apply_follows_the_cues_and_keeps_user_decisions(db: Path) -> None:
    _, row = wiki_engine.reclassify("maint", apply=True)
    assert row is not None
    assert row["via"] == "reclassify"
    facts = _facts()
    assert facts["v.md"]["class"] == "ordinance"
    assert facts["v.md"]["work"] == "de-strlschv-2018"
    assert facts["g.md"]["class"] == "report"  # the user decision survived
    assert "via reclassify" in (db / "log.md").read_text()


def test_only_maintainers_reclassify(db: Path) -> None:
    with pytest.raises(PermissionError):
        wiki_engine.reclassify("reader", apply=True)


# --- the GUI editor feeds the normal apply path ---------------------------------------


def test_editor_changes_are_a_human_revision(db: Path) -> None:
    state = ontology_store.current_state()
    classes, facts = ev.editor_tables(state, dedup.list_sources())
    classes.append(
        {
            "id": "memo",
            "broader": "report",
            "label_de": "Notiz",
            "label_en": "Memo",
            "definition": "Internal memo",
            "cues": r"\bNotiz\b",
            "deprecated": False,
            "replaced_by": "",
        }
    )
    next(f for f in facts if f["source"] == "r.md")["class"] = "memo"
    new, errors = ev.state_from_tables(state, classes, facts)
    assert errors == []
    row = wiki_engine.apply_ontology(ontology_store.prepare_state(new), user="maint", via="editor")
    assert row is not None
    assert ontology_store.last_change(human=True) == row
    assert _facts()["r.md"]["class"] == "memo"


def test_deprecating_a_used_class_in_the_editor_migrates_its_facts(db: Path) -> None:
    test_editor_changes_are_a_human_revision(db)
    state = ontology_store.current_state()
    classes, facts = ev.editor_tables(state, dedup.list_sources())
    classes[0].update(deprecated=True, replaced_by="report")
    new, _ = ev.state_from_tables(state, classes, facts)
    plan = ontology_store.prepare_state(new)
    assert plan.status == "ready", plan.errors
    wiki_engine.apply_ontology(plan, user="maint", via="editor")
    assert _facts()["r.md"]["class"] == "report"


# --- class suggestions ------------------------------------------------------------------


def _suggest(monkeypatch: pytest.MonkeyPatch, **kw: str) -> dict[str, Any] | str:
    answer = {
        "id": "test-report",
        "broader": "report",
        "label_de": "Prüfbericht",
        "label_en": "Test report",
        "definition": "Report of a recurring test",
        "cue": r"\bPrüfbericht\b",
        **kw,
    }
    monkeypatch.setattr(ollama_client, "generate", lambda *a, **k: json.dumps(answer))
    return wiki_engine.suggest_class("r.md", user="maint")


def test_an_accepted_suggestion_adds_the_class_and_types_the_document(
    db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    proposal = _suggest(monkeypatch)
    assert isinstance(proposal, dict)
    assert ontology_store.schema_proposals() == [proposal]
    row = wiki_engine.decide_schema_proposal(proposal["id"], accept=True, user="maint")
    assert row is not None
    assert row["via"] == "review"
    schema, _ = ontology_store.load()
    assert schema is not None
    assert schema.classes["test-report"].cues == (r"\bPrüfbericht\b",)
    assert _facts()["r.md"]["class"] == "test-report"
    assert ontology_store.schema_proposals() == []


def test_a_rejected_or_invalid_suggestion_changes_nothing(
    db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert _suggest(monkeypatch, cue=r"\bGutachten\b") == "the cue does not match the document"
    proposal = _suggest(monkeypatch)
    assert isinstance(proposal, dict)
    assert wiki_engine.decide_schema_proposal(proposal["id"], accept=False, user="maint") is None
    assert ontology_store.schema_proposals() == []
    schema, _ = ontology_store.load()
    assert schema is not None
    assert "test-report" not in schema.classes
