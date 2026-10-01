"""Upload page of the Broadsheet frontend (src/gui_upload.py)."""

import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from nicegui import ui
from nicegui.testing import User

import auth
import classification
import db_context
import dedup
import gui_app
import gui_session
import gui_upload
import md_convert
import ollama_client
import ontology_ui
import ui_logic
import wiki_engine

DB = db_context.DEFAULT_DB
DOC_A = b"# Alpha\n\nEffective as of 2024-01-15.\n\nAlpha text."
DOC_B = b"# Beta\n\nEffective as of 2023-05-01.\n\nBeta text."


def _progress() -> tuple[list[tuple[float, str]], Any]:
    seen: list[tuple[float, str]] = []
    return seen, lambda frac, text: seen.append((frac, text))


# --- preparing a batch ------------------------------------------------------------------------


def test_markdown_files_are_read_as_they_are_with_their_detected_date(gui_env: Path) -> None:
    seen, on_progress = _progress()
    with db_context.clearance({DB: 0}):
        prep = gui_upload.prepare_batch({"a.md": DOC_A}, DB, on_progress)
    (f,) = prep.files
    assert (f["save_name"], f["convertible"], f["content_bytes"]) == ("a.md", False, None)
    assert f["text"].startswith("# Alpha")
    assert f["detected_date"] == "2024-01-15"
    assert prep.rows["a.md"] == {"date": "2024-01-15", "class": "", "work": "", "others": ""}
    assert prep.classes is None
    assert seen[-1][0] == 1.0


def test_already_ingested_files_are_skipped_and_named(gui_env: Path) -> None:
    with db_context.clearance({DB: 0}):
        dedup.register_file(DOC_A, "a.md")
        prep = gui_upload.prepare_batch({"a.md": DOC_A, "b.md": DOC_B}, DB, _progress()[1])
    assert prep.skipped == ["a.md"]
    assert [f["save_name"] for f in prep.files] == ["b.md"]


def test_a_batch_of_only_duplicates_says_there_is_nothing_new(gui_env: Path) -> None:
    with db_context.clearance({DB: 0}):
        dedup.register_file(DOC_A, "a.md")
        prep = gui_upload.prepare_batch({"a.md": DOC_A}, DB, _progress()[1])
    assert prep.files == []
    assert prep.info == "Nothing new to ingest."


def test_a_duplicate_at_a_level_the_user_cannot_see_is_not_reported(gui_env: Path) -> None:
    with db_context.clearance({DB: 1}):
        db_context.ensure_shard(f"{DB}@confidential")
        with db_context.using_db(f"{DB}@confidential"):
            dedup.register_file(DOC_A, "a.md")
    with db_context.clearance({DB: 0}):
        prep = gui_upload.prepare_batch({"a.md": DOC_A}, DB, _progress()[1])
    assert prep.skipped == []
    assert [f["save_name"] for f in prep.files] == ["a.md"]


def test_a_pdf_is_converted_to_markdown_and_stored_as_dot_md(
    gui_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(ollama_client, "is_available", lambda: True)
    seen, on_progress = _progress()

    def convert(data: bytes, name: str, progress: Any) -> str:
        progress(1, 2, "page 1")
        return "# Converted\n\nEffective as of 2020-02-02."

    monkeypatch.setattr(md_convert, "convert_to_markdown", convert)
    with db_context.clearance({DB: 0}):
        prep = gui_upload.prepare_batch({"scan.pdf": b"%PDF"}, DB, on_progress)
    (f,) = prep.files
    assert (f["save_name"], f["convertible"]) == ("scan.md", True)
    assert f["content_bytes"] == f["text"].encode()
    assert ("scan.pdf: page 1" in text for _, text in seen)
    assert any(text == "scan.pdf: page 1" for _, text in seen)


def test_a_failed_conversion_skips_the_file_with_a_warning(
    gui_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(ollama_client, "is_available", lambda: True)

    def broken(*_a: Any) -> str:
        raise RuntimeError("no OCR")

    monkeypatch.setattr(md_convert, "convert_to_markdown", broken)
    with db_context.clearance({DB: 0}):
        prep = gui_upload.prepare_batch({"scan.pdf": b"x", "a.md": DOC_A}, DB, _progress()[1])
    assert prep.warnings == ["Skipped scan.pdf: conversion failed: no OCR"]
    assert [f["save_name"] for f in prep.files] == ["a.md"]


def test_conversion_needs_a_reachable_ollama(
    gui_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(ollama_client, "is_available", lambda: False)
    with db_context.clearance({DB: 0}):
        prep = gui_upload.prepare_batch({"scan.pdf": b"x"}, DB, _progress()[1])
    assert prep.files == []
    assert prep.error == "Ollama is not reachable. Start it to convert non-Markdown files."


def test_a_database_with_an_ontology_gets_class_and_work_columns(
    gui_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    schema = SimpleNamespace(
        classes={"law": SimpleNamespace(deprecated=False), "old": SimpleNamespace(deprecated=True)}
    )
    monkeypatch.setattr(ontology_ui, "upload_schema", lambda: schema)
    monkeypatch.setattr(ontology_ui, "detected", lambda text, date, s: {"class": "law"})
    monkeypatch.setattr(
        ontology_ui,
        "review_rows",
        lambda rows, prepared: [
            {**r, "Class": "law", "Work": "w1", "Other versions": "v1.md"} for r in rows
        ],
    )
    with db_context.clearance({DB: 0}):
        prep = gui_upload.prepare_batch({"a.md": DOC_A}, DB, _progress()[1])
    assert prep.classes == ["", "law"]
    assert prep.rows["a.md"] == {
        "date": "2024-01-15",
        "class": "law",
        "work": "w1",
        "others": "v1.md",
    }


# --- planning and ingesting ---------------------------------------------------------------------


def _files() -> list[dict[str, Any]]:
    return [{"save_name": "a.md"}, {"save_name": "b.md"}, {"save_name": "c.md"}]


def test_the_plan_blocks_unclassified_and_over_clearance_files() -> None:
    plan = gui_upload.make_plan({"a.md": None, "b.md": "confidential", "c.md": "normal"}, 0)
    assert (plan.missing, plan.denied, plan.ok) == (["a.md"], ["b.md"], False)
    assert gui_upload.block_reason(plan) == "Choose a classification for: a.md"
    only_denied = gui_upload.make_plan({"b.md": "strict"}, 1)
    assert gui_upload.block_reason(only_denied) == "Above your clearance: b.md"
    assert gui_upload.block_reason(gui_upload.make_plan({"c.md": "normal"}, 0)) == ""


def test_pending_carries_dates_levels_shared_metadata_and_ontology_values() -> None:
    plan = gui_upload.make_plan({"a.md": "normal", "b.md": "confidential"}, 1)
    pending = gui_upload.build_pending(
        _files()[:2],
        plan,
        dates={"a.md": " 2024-01-01 ", "b.md": ""},
        ontology={"a.md": {"class": "law", "work": "w"}},
        shared={"part of": " X ", "description": ""},
    )
    assert pending["dates"] == {"a.md": "2024-01-01", "b.md": ""}
    assert pending["levels"] == {"a.md": 0, "b.md": 1}
    assert pending["shared"] == {"part of": "X", "description": ""}
    assert pending["ontology"] == {"a.md": {"class": "law", "work": "w"}}
    assert (
        gui_upload.build_pending(_files()[:1], plan, {}, None, {"part of": "", "description": ""})[
            "ontology"
        ]
        is None
    )


def test_ingest_runs_oldest_first_one_level_at_a_time(
    gui_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[tuple[str, list[str]]] = []

    def fake_level(shard: str, group: list[dict[str, Any]], *_a: Any) -> None:
        calls.append((shard, [f["save_name"] for f in group]))

    monkeypatch.setattr(ui_logic, "ingest_level", fake_level)
    pending = {
        "files": [{"save_name": n} for n in ("late.md", "early.md", "conf.md")],
        "dates": {"late.md": "2024-01-01", "early.md": "2020-01-01", "conf.md": "2022-01-01"},
        "levels": {"late.md": 0, "early.md": 0, "conf.md": 1},
        "shared": {},
        "ontology": None,
    }
    with db_context.clearance({DB: 1}):
        agg = gui_upload.run_ingest(pending, DB, "u", ui_logic.no_status, lambda: None)
    assert calls == [(DB, ["early.md", "late.md"]), (f"{DB}@confidential", ["conf.md"])]
    assert agg == {"created": [], "updated": [], "contradictions": [], "failed": [], "ontology": []}


# --- page ----------------------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _pages(user: User, gui_env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    gui_session._SESSIONS.clear()
    gui_app.register()


async def _see(user: User, text: str) -> None:
    await user.should_see(text, retries=100)


async def _until(check: Any, tries: int = 100) -> None:
    for _ in range(tries):
        if check():
            return
        await asyncio.sleep(0.05)


async def _open(user: User, name: str = auth.DEFAULT_USER, pw: str = auth.DEFAULT_PASSWORD) -> None:
    await user.open("/login")
    user.find("Username").type(name)
    user.find("Password").type(pw)
    user.find("sign-in").click()
    await user.should_see("2BrAIn")
    await user.open("/")


async def _drop(user: User, files: dict[str, bytes]) -> None:
    (up,) = user.find("upload-files").elements
    assert isinstance(up, ui.upload)
    uploads = [
        ui.upload.SmallFileUpload(name=n, content_type="text/markdown", _data=b)  # type: ignore[call-arg]
        for n, b in files.items()
    ]
    await up.handle_uploads(cast(list[ui.upload.FileUpload], uploads))


def _classify(user: User, name: str, level: str) -> None:
    (toggle,) = user.find(f"level-{name}").elements
    assert isinstance(toggle, ui.toggle)
    toggle.set_value(level)


def _reviewing(user: User) -> bool:
    """2BrAIn hides the galaxy and widens the upload while a batch is prepared or reviewed."""
    (grid,) = user.find("front-grid").elements
    return "reviewing" in grid.classes


def _stub_ingest(monkeypatch: pytest.MonkeyPatch, seen: list[tuple[str, str]]) -> None:
    def begin(text: str, name: str, meta: Any) -> dict[str, Any]:
        seen.append((db_context.get_active_db(), name))
        return {"name": name, "text": text}

    monkeypatch.setattr(wiki_engine, "ingest_begin", begin)
    monkeypatch.setattr(wiki_engine, "ingest_piece", lambda *a: None)
    monkeypatch.setattr(
        wiki_engine,
        "ingest_end",
        lambda ctx, finalize=False: {
            "created": [f"{ctx['name']}-page.md"],
            "updated": [],
            "contradictions": [],
        },
    )


async def test_the_review_table_lists_files_with_dates_and_blocks_until_classified(
    user: User,
) -> None:
    await _open(user)
    await _drop(user, {"a.md": DOC_A, "b.md": DOC_B})
    await _see(user, "2 file(s) ready to ingest.")
    await _see(user, "a.md")
    await _see(user, "2024-01-15")
    await _see(user, "Choose a classification for: a.md, b.md")
    (button,) = user.find("ingest-batch").elements
    assert isinstance(button, ui.button)
    assert not button.enabled


async def test_a_classified_batch_is_ingested_into_the_chosen_level_only(
    user: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    auth.add_user("lead", "pw", [DB], maintains=[DB], clearance={DB: "confidential"})
    with db_context.clearance({DB: 1}):
        db_context.ensure_shard(f"{DB}@confidential")
    seen: list[tuple[str, str]] = []
    _stub_ingest(monkeypatch, seen)
    await _open(user, "lead", "pw")
    assert not _reviewing(user)
    await _drop(user, {"a.md": DOC_A})
    await _see(user, "1 file(s) ready to ingest.")
    assert _reviewing(user)
    _classify(user, "a.md", "confidential")
    await _until(lambda: user.find("ingest-batch").elements.copy().pop().enabled)  # type: ignore[union-attr]
    user.find("ingest-batch").click()
    await _see(user, "Ingest complete.")
    await _see(user, "a.md-page.md")
    assert not _reviewing(user)
    assert seen == [(f"{DB}@confidential", "a.md")]
    with db_context.clearance({DB: 1}):
        with db_context.using_db(f"{DB}@confidential"):
            assert (db_context.raw_dir() / "a.md").exists()
        assert not (db_context.raw_dir() / "a.md").exists()  # never filed at the normal level


async def test_a_prepared_batch_can_be_discarded_and_the_galaxy_returns(user: User) -> None:
    await _open(user)
    await _drop(user, {"a.md": DOC_A})
    await _see(user, "1 file(s) ready to ingest.")
    assert _reviewing(user)
    user.find("discard-batch").click()
    await _until(lambda: not _reviewing(user))
    assert not _reviewing(user)
    await user.should_not_see("1 file(s) ready to ingest.")
    await _drop(user, {"a.md": DOC_A})  # the same file can be dropped again
    await _see(user, "1 file(s) ready to ingest.")


async def test_levels_above_the_uploaders_clearance_are_not_offered(user: User) -> None:
    await _open(user)
    await _drop(user, {"a.md": DOC_A})
    await _see(user, "1 file(s) ready to ingest.")
    (toggle,) = user.find("level-a.md").elements
    assert isinstance(toggle, ui.toggle)
    assert list(toggle.options) == [classification.LEVELS[0]]


async def test_a_single_converted_file_can_be_edited_before_ingest(
    user: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(ollama_client, "is_available", lambda: True)
    monkeypatch.setattr(md_convert, "convert_to_markdown", lambda b, n, cb: "# Scan\n\nOCR text")
    texts: list[str] = []

    def begin(text: str, name: str, meta: Any) -> dict[str, Any]:
        texts.append(text)
        return {"name": name}

    monkeypatch.setattr(wiki_engine, "ingest_begin", begin)
    monkeypatch.setattr(wiki_engine, "ingest_piece", lambda *a: None)
    monkeypatch.setattr(
        wiki_engine,
        "ingest_end",
        lambda ctx, finalize=False: {"created": [], "updated": [], "contradictions": []},
    )
    await _open(user)
    await _drop(user, {"scan.pdf": b"%PDF"})
    await _see(user, "Converted Markdown")
    (editor,) = user.find("convert-editor").elements
    assert isinstance(editor, ui.textarea)
    assert str(editor.props.get("rows")) == "3"  # scrolls, so the ingest button stays in view
    assert "autogrow" not in editor.props
    editor.set_value("# Scan\n\nCorrected text")
    _classify(user, "scan.md", "normal")
    await _until(lambda: user.find("ingest-batch").elements.copy().pop().enabled)  # type: ignore[union-attr]
    user.find("ingest-batch").click()
    await _see(user, "Ingest complete.")
    assert texts == ["# Scan\n\nCorrected text"]


async def test_conversion_without_ollama_is_reported(
    user: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(ollama_client, "is_available", lambda: False)
    await _open(user)
    await _drop(user, {"scan.pdf": b"%PDF"})
    await _see(user, "Ollama is not reachable")


async def test_duplicates_are_named_and_nothing_new_is_said(user: User) -> None:
    with db_context.clearance({DB: 0}):
        dedup.register_file(DOC_A, "a.md")
    await _open(user)
    await _drop(user, {"a.md": DOC_A})
    await _see(user, "Skipped (already ingested): a.md")
    await _see(user, "Nothing new to ingest.")


async def test_contradictions_feed_a_resolve_panel_that_reconciles_or_dismisses(
    user: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    def begin(text: str, name: str, meta: Any) -> dict[str, Any]:
        return {"name": name}

    monkeypatch.setattr(wiki_engine, "ingest_begin", begin)
    monkeypatch.setattr(wiki_engine, "ingest_piece", lambda *a: None)
    monkeypatch.setattr(
        wiki_engine,
        "ingest_end",
        lambda ctx, finalize=False: {
            "created": ["p.md"],
            "updated": [],
            "contradictions": ["Alpha says 5, Beta says 6"],
        },
    )
    resolved: list[tuple[str, list[str], str]] = []

    def resolve(desc: str, refs: list[str], guidance: str, active_db: str) -> dict[str, list[str]]:
        resolved.append((desc, refs, guidance))
        return {"updated": refs, "skipped": []}

    monkeypatch.setattr(ui_logic, "resolve_by_shard", resolve)
    await _open(user)
    await _drop(user, {"a.md": DOC_A})
    await _see(user, "1 file(s) ready to ingest.")
    _classify(user, "a.md", "normal")
    await _until(lambda: user.find("ingest-batch").elements.copy().pop().enabled)  # type: ignore[union-attr]
    user.find("ingest-batch").click()
    await _see(user, "Resolve contradictions")
    await _see(user, "Alpha says 5, Beta says 6")
    user.find("reconcile-0").click()
    await _see(user, "Updated: p.md")
    assert resolved == [("Alpha says 5, Beta says 6", ["p.md"], "")]
    user.find("dismiss-contradictions").click()
    await user.should_not_see("Resolve contradictions")


def test_status_text_reaches_the_progress_readout() -> None:
    progress = gui_upload.Progress(total=2)
    with progress.status("Ingesting a.md (Normal)…"):
        assert progress.text == "Ingesting a.md (Normal)…"
    progress.tick()
    assert progress.fraction == 0.5
