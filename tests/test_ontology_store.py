"""Ontology store adapter: shipped modules, per-DB binding, append-only ledger."""

from pathlib import Path

import pytest

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
