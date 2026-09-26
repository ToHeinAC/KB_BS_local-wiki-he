"""Ontology store adapter: shipped modules, per-DB binding, append-only ledger."""

from pathlib import Path

import pytest
import yaml

import ontology
import ontology_store

_CORE = """\
id: core
version: 1.0.0
classes:
  document: {labels: {en: Document, de: Dokument}, definition: Any source}
  report: {broader: document, labels: {en: Report, de: Bericht}, definition: A report}
"""


@pytest.fixture
def modules(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    mdir = tmp_path / "modules"
    mdir.mkdir()
    (mdir / "core.yaml").write_text(_CORE)
    monkeypatch.setattr(ontology_store, "MODULE_DIR", mdir)
    return mdir


def _files(root: Path) -> set[Path]:
    return {p for p in root.rglob("*")}


def test_shipped_modules_validate_clean() -> None:
    texts = {m: p.read_text() for m, p in ontology_store.available_modules().items()}
    assert {"core", "legal-de"} <= set(texts)
    parsed = [ontology.parse_yaml(t) for t in texts.values()]
    assert [e for _, e in parsed] == [[] for _ in parsed]
    _, errors = ontology.build_schema([d for d, _ in parsed])
    assert errors == []


def test_no_ontology_loads_as_none_and_creates_nothing(raw_dir: Path, modules: Path) -> None:
    root = raw_dir.parent
    before = _files(root)
    assert not ontology_store.exists()
    assert ontology_store.load() == (None, [])
    assert ontology_store.read_rows() == []
    assert ontology_store.retract_subject("src:x.md", by="system", reason="gone") == 0
    assert _files(root) == before


def test_load_binds_modules_and_local_extension(raw_dir: Path, modules: Path) -> None:
    ontology_store.binding_path().write_text(
        "modules: [core]\nlocal:\n  classes:\n    memo: {broader: report, "
        "labels: {en: Memo, de: Notiz}, definition: Internal memo}\n"
    )
    schema, errors = ontology_store.load()
    assert errors == []
    assert schema is not None
    assert set(schema.classes) == {"document", "report", "memo"}


@pytest.mark.parametrize(
    ("binding", "needle"),
    [("modules: [core\n", "ontology.yaml"), ("modules: [ghost]\n", "ghost")],
)
def test_broken_binding_fails_open_with_errors(
    raw_dir: Path, modules: Path, binding: str, needle: str
) -> None:
    ontology_store.binding_path().write_text(binding)
    schema, errors = ontology_store.load()
    assert schema is None
    assert any(needle in e for e in errors)


def test_broken_module_file_is_reported(raw_dir: Path, modules: Path) -> None:
    (modules / "core.yaml").write_text("id: core\nversion: 1.0.0\nclasses: {x: 1}\n")
    ontology_store.binding_path().write_text("modules: [core]\n")
    schema, errors = ontology_store.load()
    assert schema is None
    assert any("core" in e for e in errors)


def test_append_assigns_ids_and_skips_corrupt_lines(raw_dir: Path) -> None:
    rows = [ontology.assertion("src:a.md", "class", "report", by="rule") for _ in range(2)]
    assert ontology_store.append_rows(rows) == ["a-000001", "a-000002"]
    with ontology_store.ledger_path().open("a") as fh:
        fh.write("\n{not json")  # a blank line and a torn, unparseable last line
    assert ontology_store.append_rows(rows[:1]) == ["a-000003"]
    stored = ontology_store.read_rows()
    assert [r["id"] for r in stored] == ["a-000001", "a-000002", "a-000003"]
    assert all(r["recorded_at"].endswith("Z") for r in stored)


def test_retract_subject_touches_only_that_subject(raw_dir: Path) -> None:
    ontology_store.append_rows(
        [
            ontology.assertion("src:a.md", "class", "report", by="rule"),
            ontology.assertion("src:a.md", "work", "w-a", by="user"),
            ontology.assertion("src:b.md", "class", "report", by="rule"),
        ]
    )
    assert ontology_store.retract_subject("src:a.md", by="system", reason="deleted") == 2
    assert ontology_store.retract_subject("src:a.md", by="system", reason="deleted") == 0
    facts = ontology.project(ontology_store.read_rows(), multi=set())
    assert facts == {"src:b.md": {"class": "report"}}


# --- Phase 2: revisions, import/apply, history ---------------------------------------


@pytest.fixture
def onto(wiki_dir: Path, modules: Path) -> Path:
    """Test DB with two sources, a maintainer and a reader; no ontology yet."""
    import auth
    import dedup

    dedup.register_file(b"alpha", "a.md")
    dedup.register_file(b"beta", "b.md")
    auth.add_user("maint", "pw", ["test"], maintains=["test"])
    auth.add_user("reader", "pw", ["test"])
    return wiki_dir


def _create() -> dict:
    plan = ontology_store.prepare_state({"schema": {"modules": ["core"]}})
    row = ontology_store.apply(plan, user="maint", via="create")
    assert row is not None
    return row


def _edited(text: str, **sources: str) -> str:
    doc = yaml.safe_load(text)
    doc["facts"] = {"sources": {name: {"class": cls} for name, cls in sources.items()}}
    return yaml.safe_dump(doc, sort_keys=False, allow_unicode=True)


def test_create_writes_binding_revision_one_and_snapshot(onto: Path) -> None:
    row = _create()
    assert ontology_store.exists()
    assert (row["seq"], row["via"], row["user"]) == (1, "create", "maint")
    assert ontology_store.history() == [row]
    assert ontology_store.snapshot_text(1) is not None
    assert ontology_store.current_revision() == (1, row["hash"])
    assert ontology_store.last_change(human=True) == row
    assert ontology_store.last_change(human=False) is None


def test_reexporting_and_importing_the_same_file_is_a_no_op(onto: Path) -> None:
    _create()
    text = ontology_store.export_text("maint")
    plan = ontology_store.prepare_import(text)
    assert plan.status == "unchanged"
    assert len(ontology_store.history()) == 1


def test_import_applies_edits_as_user_facts_and_a_new_revision(onto: Path) -> None:
    _create()
    plan = ontology_store.prepare_import(
        _edited(ontology_store.export_text("maint"), **{"a.md": "report"})
    )
    assert plan.status == "ready", plan.errors
    row = ontology_store.apply(plan, user="maint", via="import", file_name="e.yaml")
    assert row is not None
    assert (row["seq"], row["file"]) == (2, "e.yaml")
    assert row["summary"]["facts"]["added"] == 1
    assert ontology_store.current_state()["facts"] == {"sources": {"a.md": {"class": "report"}}}
    [fact] = ontology.live_rows(ontology_store.read_rows())
    assert (fact["by"], fact["user"]) == ("user", "maint")


def test_import_of_an_older_export_keeps_newer_automatic_changes(onto: Path) -> None:
    _create()
    old_export = ontology_store.export_text("maint")
    ontology_store.append_rows([ontology.assertion("src:b.md", "class", "document", by="rule")])
    auto = ontology_store.record_change("ingest")
    assert auto is not None
    assert ontology_store.last_change(human=False) == auto
    plan = ontology_store.prepare_import(_edited(old_export, **{"a.md": "report"}))
    assert plan.status == "ready", plan.errors
    ontology_store.apply(plan, user="maint", via="import")
    facts = ontology_store.current_state()["facts"]["sources"]
    assert facts == {"a.md": {"class": "report"}, "b.md": {"class": "document"}}


def test_apply_refuses_a_plan_computed_on_an_older_revision(onto: Path) -> None:
    _create()
    plan = ontology_store.prepare_import(
        _edited(ontology_store.export_text("maint"), **{"a.md": "report"})
    )
    ontology_store.append_rows([ontology.assertion("src:b.md", "class", "report", by="rule")])
    with pytest.raises(ontology_store.StaleRevisionError):
        ontology_store.apply(plan, user="maint", via="import")


def test_only_maintainers_may_apply(onto: Path) -> None:
    plan = ontology_store.prepare_state({"schema": {"modules": ["core"]}})
    with pytest.raises(PermissionError):
        ontology_store.apply(plan, user="reader", via="create")
    assert not ontology_store.exists()


def test_restore_makes_a_new_revision_equal_to_the_old_one(onto: Path) -> None:
    first = _create()
    plan = ontology_store.prepare_import(
        _edited(ontology_store.export_text("maint"), **{"a.md": "report"})
    )
    ontology_store.apply(plan, user="maint", via="import")
    restore = ontology_store.prepare_restore(1)
    assert restore.status == "ready"
    row = ontology_store.apply(restore, user="maint", via="restore", file_name="rev 1")
    assert row is not None
    assert (row["seq"], row["hash"]) == (3, first["hash"])
    assert [r["seq"] for r in ontology_store.history()] == [1, 2, 3]


def test_record_change_is_silent_without_ontology_or_change(onto: Path) -> None:
    assert ontology_store.record_change("ingest") is None
    _create()
    assert ontology_store.record_change("ingest") is None
    assert ontology_store.prepare_restore(99).status == "error"


def test_apply_ontology_writes_the_activity_log(onto: Path) -> None:
    import wiki_engine

    plan = ontology_store.prepare_state({"schema": {"modules": ["core"]}})
    wiki_engine.apply_ontology(plan, user="maint", via="create")
    assert "rev 1 by maint via create" in (onto / "log.md").read_text()
