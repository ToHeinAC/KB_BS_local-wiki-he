"""Ontology exchange file: canonical form, diff, 3-way merge, validation, import plans (pure)."""

import copy
from typing import Any

import pytest
import yaml

import ontology_bundle as ob

DB = "KI"


def _labels(en: str, de: str) -> dict[str, str]:
    return {"en": en, "de": de}


SHARED: dict[str, Any] = {
    "core": {
        "id": "core",
        "version": "1.0.0",
        "classes": {
            "document": {"labels": _labels("Document", "Dokument"), "definition": "Any source"},
            "report": {
                "broader": "document",
                "labels": _labels("Report", "Bericht"),
                "definition": "A report",
            },
            "guidance": {
                "broader": "document",
                "labels": _labels("Guidance", "Leitfaden"),
                "definition": "A guideline",
            },
        },
        "relations": {"cites": {"domain": "document", "range": "document", "inverse": "cited_by"}},
    }
}
SOURCES = {"a.md", "b.md"}


def _memo(definition: str = "Internal memo") -> dict[str, Any]:
    return {"broader": "report", "labels": _labels("Memo", "Notiz"), "definition": definition}


def _state() -> dict[str, Any]:
    return {
        "schema": {
            "modules": ["core"],
            "local": {"version": "0.1.0", "classes": {"memo": _memo()}},
        },
        "facts": {
            "sources": {"a.md": {"class": "report", "work": "w-a", "version_date": "2020-01-31"}},
            "works": {"w-a": {"class": "report", "aliases": ["A", "Alpha"], "cites": ["w-a"]}},
        },
    }


def _render(state: dict[str, Any], revision: str = "1-abc") -> str:
    return ob.render(
        state, db=DB, revision=revision, user="tobias", exported_at="2026-09-26T10:00:00Z"
    )


def _plan(imported: dict[str, Any], current: dict[str, Any], **kw: Any) -> ob.ImportPlan:
    kw.setdefault("base", current)
    kw.setdefault("referenced", set())
    return ob.plan_import(imported, current=current, shared=SHARED, known_sources=SOURCES, **kw)


# --- canonical form and revision hash (D8) ------------------------------------------


def test_render_parse_round_trip_keeps_the_revision() -> None:
    state, base, errors = ob.parse(_render(_state()), db=DB)
    assert (base, errors) == ("1-abc", [])
    assert state is not None
    assert ob.revision_hash(state) == ob.revision_hash(_state())


def test_formatting_comments_order_and_metadata_are_not_changes() -> None:
    text = """\
# my notes
exported_by: someone else
exported_at: 2030-01-01T00:00:00Z
base_revision: 9-zzz
db: KI
format: localwiki-ontology/1
facts:
  works:
    w-a: {aliases: [Alpha, A, A], cites: [w-a], class: "report"}   # reordered, duplicated
  sources:
    a.md:
      version_date: 2020-01-31      # unquoted: YAML reads a date
      work: '  w-a '
      class: report
schema:
  local:
    version: 7.7.7                  # code-owned, ignored
    classes:
      memo: {definition: Internal memo, labels: {de: Notiz, en: Memo}, broader: report,
             deprecated: false}
  modules: [core, core]
"""
    state, _, errors = ob.parse(text, db=DB)
    assert errors == []
    assert state is not None
    assert ob.revision_hash(state) == ob.revision_hash(_state())


def test_a_changed_definition_is_a_change_with_exactly_that_path() -> None:
    edited = _state()
    edited["schema"]["local"]["classes"]["memo"]["definition"] = "Internal note"
    assert ob.revision_hash(edited) != ob.revision_hash(_state())
    changes = ob.diff(_state(), edited)
    assert [(c["path"], c["op"]) for c in changes] == [
        (["schema", "local", "classes", "memo", "definition"], "change")
    ]


@pytest.mark.parametrize(
    ("text", "needle"),
    [
        ("format: other/1\ndb: KI\nschema: {modules: [core]}\n", "format"),
        ("format: localwiki-ontology/1\ndb: Other\nschema: {modules: [core]}\n", "Other"),
        ("format: localwiki-ontology/1\ndb: KI\nschema: {}\nextra: 1\n", "extra"),
        ("- a list\n", "mapping"),
        ("format: localwiki-ontology/1\ndb: KI\nschema: &s {modules: [core]}\nx: *s\n", "alias"),
        ("format: localwiki-ontology/1\ndb: KI\nfacts: []\nschema: {}\n", "facts"),
        ("key: [unclosed\n", "line"),
    ],
)
def test_parse_rejects_bad_files(text: str, needle: str) -> None:
    state, _, errors = ob.parse(text, db=DB)
    assert state is None
    assert any(needle in e for e in errors), errors


def test_parse_rejects_oversized_files_and_allows_other_db_on_request() -> None:
    _, _, errors = ob.parse("x" * (ob.MAX_BYTES + 1), db=DB)
    assert any("MB" in e for e in errors)
    text = _render(_state()).replace("db: KI", "db: Other")
    state, _, errors = ob.parse(text, db=DB, allow_other_db=True)
    assert state is not None
    assert errors == []


# --- 3-way merge (R9) ------------------------------------------------------------------


def test_merge_keeps_newer_current_changes_and_applies_mine() -> None:
    base = _state()
    current = copy.deepcopy(base)  # e.g. an ingest added a fact after the export
    current["facts"]["sources"]["b.md"] = {"class": "guidance"}
    mine = copy.deepcopy(base)
    mine["facts"]["sources"]["a.md"]["class"] = "guidance"
    merged, conflicts = ob.merge3(base, mine, current)
    assert conflicts == []
    assert merged["facts"]["sources"]["a.md"]["class"] == "guidance"
    assert merged["facts"]["sources"]["b.md"] == {"class": "guidance"}


def test_merge_reports_conflicts_and_keeps_current_unless_told_otherwise() -> None:
    base = _state()
    current, mine = copy.deepcopy(base), copy.deepcopy(base)
    current["facts"]["sources"]["a.md"]["class"] = "guidance"
    mine["facts"]["sources"]["a.md"]["class"] = "memo"
    merged, conflicts = ob.merge3(base, mine, current)
    label = "facts > sources > a.md > class"
    assert [c["path"] for c in conflicts] == [label]
    assert conflicts[0]["current"] == "guidance"
    assert conflicts[0]["mine"] == "memo"
    assert merged["facts"]["sources"]["a.md"]["class"] == "guidance"
    merged, _ = ob.merge3(base, mine, current, {label: "mine"})
    assert merged["facts"]["sources"]["a.md"]["class"] == "memo"


# --- import plans --------------------------------------------------------------------


def test_identical_import_is_unchanged() -> None:
    plan = _plan(_state(), _state())
    assert plan.status == "unchanged"
    assert plan.changes == []


def test_ready_plan_lists_changes_summary_and_version_bump() -> None:
    edited = _state()
    edited["schema"]["local"]["classes"]["note"] = _memo("Short note")
    edited["facts"]["sources"]["b.md"] = {"class": "memo"}
    plan = _plan(edited, _state())
    assert plan.status == "ready", plan.errors
    assert plan.summary == {
        "schema": {"added": 1, "changed": 0, "removed": 0},
        "facts": {"added": 1, "changed": 0, "removed": 0},
    }
    assert plan.local_version == "0.2.0"
    assert plan.state["schema"]["local"]["version"] == "0.2.0"
    assert plan.new_hash == ob.revision_hash(edited)


def test_missing_base_warns_that_the_merge_is_two_way() -> None:
    edited = _state()
    edited["facts"]["sources"]["b.md"] = {"class": "report"}
    plan = _plan(edited, _state(), base=None)
    assert plan.status == "ready"
    assert any("base revision" in w for w in plan.warnings)


@pytest.mark.parametrize(
    ("fact", "needle"),
    [
        ({"class": "nope"}, "nope"),
        ({"version_date": "31.01.2020"}, "YYYY-MM-DD"),
        ({"in_force": "maybe"}, "in_force"),
        ({"colour": "red"}, "colour"),
        ({"work": "Not An Id"}, "work"),
        ({"aliases": "A"}, "aliases"),
    ],
)
def test_invalid_facts_are_errors(fact: dict[str, Any], needle: str) -> None:
    edited = _state()
    edited["facts"]["sources"]["a.md"] = fact
    plan = _plan(edited, _state())
    assert plan.status == "error"
    assert any(needle in e for e in plan.errors), plan.errors


def test_unknown_source_and_section_are_errors() -> None:
    edited = _state()
    edited["facts"]["sources"]["ghost.md"] = {"class": "report"}
    edited["facts"]["things"] = {"x": {"class": "report"}}
    plan = _plan(edited, _state())
    assert any("ghost.md" in e for e in plan.errors)
    assert any("things" in e for e in plan.errors)


def test_schema_errors_block_the_import() -> None:
    edited = _state()
    edited["schema"]["local"]["classes"]["memo"]["broader"] = "nowhere"
    plan = _plan(edited, _state())
    assert plan.status == "error"
    assert any("nowhere" in e for e in plan.errors)


def test_dangling_relation_target_is_only_a_warning() -> None:
    edited = _state()
    edited["facts"]["works"]["w-a"]["cites"] = ["w-a", "w-missing"]
    plan = _plan(edited, _state())
    assert plan.status == "ready"
    assert any("w-missing" in w for w in plan.warnings)


def test_removing_a_referenced_class_is_refused_but_an_unused_one_is_allowed() -> None:
    edited = _state()
    del edited["schema"]["local"]["classes"]["memo"]
    plan = _plan(edited, _state(), referenced={"memo"})
    assert plan.status == "error"
    assert any("deprecated" in e for e in plan.errors)
    assert _plan(edited, _state()).status == "ready"


def test_deprecated_class_with_replacement_migrates_facts() -> None:
    edited = _state()
    edited["schema"]["local"]["classes"]["memo"].update(deprecated=True, replaced_by="report")
    edited["facts"]["sources"]["a.md"]["class"] = "memo"
    plan = _plan(edited, _state())
    assert plan.status == "ready", plan.errors
    assert plan.state["facts"]["sources"]["a.md"]["class"] == "report"
    assert any("memo" in w and "report" in w for w in plan.warnings)


# --- versions, ledger rows, log line -------------------------------------------------


def test_bump_follows_semver_rules() -> None:
    old = _state()["schema"]["local"]
    patch = copy.deepcopy(old)
    patch["classes"]["memo"]["definition"] = "Changed"
    minor = copy.deepcopy(old)
    minor["classes"]["note"] = _memo()
    major = copy.deepcopy(old)
    major["classes"]["memo"]["broader"] = "guidance"
    assert ob.bump("0.1.0", old, old) == "0.1.0"
    assert ob.bump("0.1.0", old, patch) == "0.1.1"
    assert ob.bump("0.1.0", old, minor) == "0.2.0"
    assert ob.bump("0.1.3", old, major) == "1.0.0"
    assert ob.bump("junk", old, minor) == "0.2.0"


def test_fact_rows_turn_edits_into_user_assertions() -> None:
    old = _state()["facts"]
    new = copy.deepcopy(old)
    new["sources"]["a.md"]["class"] = "guidance"
    del new["sources"]["a.md"]["version_date"]
    new["works"]["w-a"]["aliases"] = ["A", "Alfa"]
    rows = ob.fact_rows(old, new, user="tobias", evidence="import rev 2")
    got = {(r["subject"], r["predicate"], r["object"], r["negated"]) for r in rows}
    assert got == {
        ("src:a.md", "class", "guidance", False),
        ("src:a.md", "version_date", None, False),
        ("work:w-a", "aliases", "Alfa", False),
        ("work:w-a", "aliases", "Alpha", True),
    }
    assert {(r["by"], r["user"], r["evidence"]) for r in rows} == {
        ("user", "tobias", "import rev 2")
    }


def test_log_line_names_revision_user_via_file_and_counts() -> None:
    row = {
        "seq": 8,
        "user": "tobias",
        "via": "import",
        "file": "edited.yaml",
        "summary": {
            "schema": {"added": 1, "changed": 1, "removed": 0},
            "facts": {"added": 3, "changed": 2, "removed": 1},
        },
    }
    assert ob.log_line(row) == (
        "rev 8 by tobias via import (edited.yaml): schema +1 ~1 −0, facts +3 ~2 −1"
    )


def test_rendered_file_is_plain_yaml_with_reference_section() -> None:
    text = ob.render(
        _state(), db=DB, revision="1-abc", user=None, exported_at="x", reference=SHARED
    )
    assert text.startswith("#")
    doc = yaml.safe_load(text)
    assert doc["format"] == ob.FORMAT
    assert doc["reference"]["core"]["id"] == "core"
    assert "&" not in text.split("reference:")[0]
