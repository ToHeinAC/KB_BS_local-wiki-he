"""Ontology at upload/ingest: review rows, LLM proposals, page stamping, proposal review."""

from pathlib import Path
from typing import Any

import frontmatter
import pytest

import auth
import dedup
import ollama_client
import ontology
import ontology_detect
import ontology_store
import wiki_engine

STRLSCHV = (
    Path(__file__).resolve().parents[1] / "bench" / "ontology_detect" / "strlschv_2018.md"
).read_text()
NOTE = "Interne Notiz zur Kalibrierung\n\nDiese Notiz beschreibt die monatliche Kalibrierung.\n"
SUMMARY = "summary-strlschv.md"


@pytest.fixture
def legal(wiki_dir: Path) -> Path:
    ontology_store.binding_path().write_text("modules: [core, legal-de]\n")
    auth.add_user("maint", "pw", ["test"], maintains=["test"])
    auth.add_user("reader", "pw", ["test"])
    dedup.register_file(STRLSCHV.encode(), "strlschv.md")
    dedup.register_file(NOTE.encode(), "note.md")
    return wiki_dir


def _detected(text: str = STRLSCHV, date: str = "2024-10-23") -> dict[str, Any]:
    schema, _ = ontology_store.load()
    assert schema is not None
    return ontology_detect.detected_dict(ontology_detect.detect(text, schema), date)


def _record(review: dict[str, str], text: str = STRLSCHV, source: str = "strlschv.md") -> list[str]:
    detected = _detected(text) if text == STRLSCHV else _detected(text, "")
    return wiki_engine.record_source_ontology(text, source, review, detected, user="maint")


def _facts() -> dict[str, Any]:
    return ontology_store.current_state()["facts"]


def _summary(wiki: Path, **meta: Any) -> Path:
    post = frontmatter.Post("# StrlSchV\n\nDie Verordnung regelt den Strahlenschutz im Detail.")
    post.metadata.update({"title": "StrlSchV", "type": "source-summary", "lang": "de"})
    post.metadata.update({"sources": ["strlschv.md"], **meta})
    path = wiki / SUMMARY
    path.write_text(frontmatter.dumps(post) + "\n")
    return path


# --- upload review rows ------------------------------------------------------------


def test_accepted_detection_is_stored_as_rule_facts(legal: Path) -> None:
    review = {"class": "ordinance", "work": "de-strlschv-2018", "version_date": "2024-10-23"}
    assert _record(review) == []
    rows = ontology.live_rows(ontology_store.read_rows())
    assert {r["by"] for r in rows} == {"rule"}
    assert _facts()["sources"]["strlschv.md"] == {
        "class": "ordinance",
        "work": "de-strlschv-2018",
        "version_date": "2024-10-23",
    }
    work = _facts()["works"]["de-strlschv-2018"]
    assert work == {
        "class": "ordinance",
        "aliases": ["Strahlenschutzverordnung", "StrlSchV"],
        "transposes": ["eu-dir-2013-59-euratom"],  # the head's transposition clause (Phase 6)
    }


def test_corrections_in_the_review_table_are_user_facts(legal: Path) -> None:
    _record({"class": "federal-act", "work": "de-strlschv-2018", "version_date": "2024-11-01"})
    by = {(r["predicate"], r["by"]) for r in ontology.live_rows(ontology_store.read_rows())}
    assert {("class", "user"), ("version_date", "user"), ("work", "rule")} <= by


def test_invalid_review_values_are_skipped_with_a_warning(legal: Path) -> None:
    warnings = _record({"class": "nope", "work": "Not An Id", "version_date": "01.02.2024"})
    assert len(warnings) == 3
    assert "src:strlschv.md" not in ontology.project(ontology_store.read_rows(), set())


def test_without_a_class_the_llm_may_propose_one_with_a_verbatim_quote(
    legal: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    answer = (
        '{"class": "operational-rule", '
        '"quote": "Diese Notiz beschreibt die monatliche Kalibrierung."}'
    )
    monkeypatch.setattr(ollama_client, "generate", lambda *a, **k: answer)
    _record({}, text=NOTE, source="note.md")
    [row] = ontology_store.proposals()
    assert (row["subject"], row["object"], row["by"]) == ("src:note.md", "operational-rule", "llm")
    assert "src:note.md" not in _facts().get("sources", {})  # proposals are not facts


@pytest.mark.parametrize(
    "answer", ['{"class": "procedure", "quote": "Dieses Gesetz tritt in Kraft."}', RuntimeError]
)
def test_fabricated_or_failed_llm_answers_propose_nothing(
    legal: Path, monkeypatch: pytest.MonkeyPatch, answer: object
) -> None:
    def fake(*_a: object, **_k: object) -> str:
        if answer is RuntimeError:
            raise RuntimeError("ollama down")
        return str(answer)

    monkeypatch.setattr(ollama_client, "generate", fake)
    _record({}, text=NOTE, source="note.md")
    assert ontology_store.proposals() == []


def test_a_db_without_ontology_gets_no_rows_no_files_no_llm_call(
    wiki_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(ollama_client, "generate", lambda *a, **k: pytest.fail("LLM called"))
    assert wiki_engine.record_source_ontology(NOTE, "note.md", {}, {}, user="maint") == []
    wiki_engine.finish_ontology_batch("maint")
    assert not ontology_store.store_dir().exists()


# --- stamping (report §4.4, F7) ------------------------------------------------------


def test_summary_pages_are_stamped_from_facts_and_unstamped_on_removal(legal: Path) -> None:
    page = _summary(legal)
    _record({"class": "ordinance", "work": "de-strlschv-2018", "version_date": "2024-10-23"})
    wiki_engine.finish_ontology_batch("maint")
    meta = frontmatter.load(str(page)).metadata
    assert (meta["class"], meta["work"], meta["version_date"]) == (
        "ordinance",
        "de-strlschv-2018",
        "2024-10-23",
    )
    ontology_store.append_rows(
        [ontology.assertion("src:strlschv.md", "class", None, by="user", user="maint")]
    )
    wiki_engine.restamp_summaries()
    assert "class" not in frontmatter.load(str(page)).metadata


def test_an_llm_rewrite_cannot_drop_the_stamped_keys(
    legal: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _record({"class": "ordinance", "work": "de-strlschv-2018", "version_date": "2024-10-23"})
    page = _summary(legal, **{"class": "ordinance"})
    rewrite = (
        f"=== {SUMMARY} ===\n---\ntitle: StrlSchV\ntype: source-summary\nsources: [strlschv.md]\n"
        "---\n# StrlSchV\n\nDie Verordnung regelt den Strahlenschutz, jetzt ohne Widerspruch.\n"
        "=== END ===\n"
    )
    monkeypatch.setattr(ollama_client, "generate", lambda *a, **k: rewrite)
    result = wiki_engine.resolve_contradiction("Dosis", [SUMMARY])
    assert result["updated"] == [SUMMARY]
    meta = frontmatter.load(str(page)).metadata
    assert (meta["class"], meta["work"]) == ("ordinance", "de-strlschv-2018")


def test_without_ontology_pages_are_left_byte_identical(wiki_dir: Path) -> None:
    page = _summary(wiki_dir, **{"class": "hand-written"})
    before = page.read_bytes()
    wiki_engine.restamp_summaries()
    assert page.read_bytes() == before


# --- batch end and proposal review -----------------------------------------------------


def test_an_ingest_batch_is_one_automatic_revision(legal: Path) -> None:
    _record({"class": "ordinance", "work": "de-strlschv-2018", "version_date": "2024-10-23"})
    _record({"class": "report"}, text=NOTE, source="note.md")
    wiki_engine.finish_ontology_batch("maint")
    [row] = ontology_store.history()
    assert (row["via"], row["user"]) == ("ingest", "maint")
    assert ontology_store.last_change(human=False) == row
    assert "via ingest" in (legal / "log.md").read_text()


def _propose(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    answer = (
        '{"class": "operational-rule", '
        '"quote": "Diese Notiz beschreibt die monatliche Kalibrierung."}'
    )
    monkeypatch.setattr(ollama_client, "generate", lambda *a, **k: answer)
    _record({}, text=NOTE, source="note.md")
    [row] = ontology_store.proposals()
    return row


def test_confirming_a_proposal_makes_it_a_user_fact(
    legal: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    row = _propose(monkeypatch)
    change = wiki_engine.decide_proposal(row["id"], accept=True, user="maint")
    assert change is not None
    assert change["via"] == "review"
    assert _facts()["sources"]["note.md"] == {"class": "operational-rule"}
    assert ontology_store.proposals() == []
    assert ontology_store.last_change(human=True) == change


def test_rejecting_a_proposal_only_withdraws_it(
    legal: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    row = _propose(monkeypatch)
    assert wiki_engine.decide_proposal(row["id"], accept=False, user="maint") is None
    assert ontology_store.proposals() == []
    assert "note.md" not in _facts().get("sources", {})


def test_only_maintainers_decide_proposals(legal: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    row = _propose(monkeypatch)
    with pytest.raises(PermissionError):
        wiki_engine.decide_proposal(row["id"], accept=True, user="reader")
    with pytest.raises(KeyError):
        wiki_engine.decide_proposal("a-999999", accept=True, user="maint")
