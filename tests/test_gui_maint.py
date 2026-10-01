"""Maintenance page of the Broadsheet frontend (src/gui_maint.py)."""

import asyncio
from pathlib import Path
from typing import Any

import frontmatter
import pytest
from nicegui import ui
from nicegui.testing import User

import auth
import db_context
import dedup
import gui_app
import gui_maint
import gui_session
import wiki_engine

DB = db_context.DEFAULT_DB


def _page(name: str, title: str, related: tuple[str, ...] = ()) -> None:
    post = frontmatter.Post(f"# {title}\n\nBody.", title=title, type="concept")
    post.metadata["sources"] = ["doc.md"]
    post.metadata["related"] = list(related)
    (db_context.wiki_dir() / name).write_text(frontmatter.dumps(post))


@pytest.fixture
def wiki(gui_env: Path) -> Path:
    dedup.register_file(b"# Doc\n\nOriginal.", "doc.md")
    _page("alpha.md", "Alpha", related=("beta.md",))
    _page("beta.md", "Beta")
    _page("lonely.md", "Lonely")
    wiki_engine.rebuild_lex_index()
    return gui_env


@pytest.fixture(autouse=True)
def _pages(user: User, gui_env: Path) -> None:
    gui_session._SESSIONS.clear()
    gui_app.register()


async def _see(user: User, text: str) -> None:
    await user.should_see(text, retries=100)


async def _until(check: Any, tries: int = 100) -> None:
    for _ in range(tries):
        if check():
            return
        await asyncio.sleep(0.05)


async def _find(user: User, marker: str) -> Any:
    """`user.find` that waits for the section to render."""
    for _ in range(100):
        try:
            return user.find(marker)
        except AssertionError:
            await asyncio.sleep(0.05)
    return user.find(marker)


async def _open(user: User, name: str = auth.DEFAULT_USER, pw: str = auth.DEFAULT_PASSWORD) -> None:
    await user.open("/login")
    user.find("Username").type(name)
    user.find("Password").type(pw)
    user.find("sign-in").click()
    await user.should_see("2BrAIn")
    await user.open("/maintenance")
    await user.should_see("Wiki pages", retries=100)  # the initial load has finished


async def _section(user: User, name: str) -> None:
    (toggle,) = user.find("maint-section").elements
    assert isinstance(toggle, ui.toggle)
    toggle.set_value(name)


def test_sections_are_the_streamlit_ones_without_admin() -> None:
    assert gui_maint.SECTIONS == (
        "Search index",
        "Delete source",
        "Link graph health",
        "Lint",
        "Page language",
        "Ontology",
        "Activity log",
    )


def test_data_size_is_shown_in_megabytes() -> None:
    assert gui_maint.megabytes(1_048_576) == "1.0"
    assert gui_maint.megabytes(0) == "0.0"
    assert gui_maint.megabytes(1_572_864) == "1.5"


def test_normalize_rows_summarise_each_page() -> None:
    report = {"a.md": {"lang": "de", "foreign_lines": 3, "references": True}, "b.md": {}}
    assert gui_maint.normalize_rows(report) == [
        {"Page": "a.md", "Stamp language": "de", "Foreign lines": 3, "Fix references": "yes"},
        {"Page": "b.md", "Stamp language": "", "Foreign lines": 0, "Fix references": ""},
    ]
    assert gui_maint.needs_translation(report) == 1


async def test_the_page_shows_wiki_statistics(wiki: Path, user: User) -> None:
    await _open(user)
    await _see(user, "Wiki pages 3")
    await _see(user, "Raw sources 1")


async def test_the_search_index_section_shows_counts_and_rebuilds(
    wiki: Path, user: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(wiki_engine, "rebuild_lex_index", lambda: {"chunks": 7})
    await _open(user)
    await _see(user, "Wiki page chunks indexed")
    (await _find(user, "rebuild-index")).click()
    await _see(user, "Indexed 7 chunks.")


async def test_a_missing_index_is_flagged(wiki: Path, user: User) -> None:
    (db_context.wiki_dir().parent / "index" / "chunks.sqlite").unlink()
    await _open(user)
    await _see(user, "No index for this database")


async def test_readers_cannot_rebuild_delete_or_normalize(wiki: Path, user: User) -> None:
    await _open(user, "reader", "pw")
    await _see(user, "Only maintainers of this database can rebuild the index.")
    await user.should_not_see("Rebuild search index")
    await _section(user, "Delete source")
    await _see(user, "Delete actions require maintainer rights for this database.")


async def test_deleting_a_source_needs_the_confirmation(
    wiki: Path, user: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    deleted: list[str] = []

    def delete(name: str) -> dict[str, Any]:
        deleted.append(name)
        return {"wiki_pages": ["a.md", "b.md"], "qa_rows": 4}

    monkeypatch.setattr(wiki_engine, "delete_source", delete)
    await _open(user)
    await _section(user, "Delete source")
    await _see(user, "This cannot be undone.")
    (button,) = (await _find(user, "delete-source")).elements
    assert isinstance(button, ui.button)
    assert not button.enabled
    (box,) = (await _find(user, "delete-confirm")).elements
    assert isinstance(box, ui.checkbox)
    box.set_value(True)
    await _until(lambda: button.enabled)
    (await _find(user, "delete-source")).click()
    await _see(user, "Wiki pages removed: 2. QA rows removed: 4. Index rebuilt.")
    assert deleted == ["doc.md"]


async def test_no_sources_says_so(gui_env: Path, user: User) -> None:
    await _open(user)
    await _section(user, "Delete source")
    await _see(user, "No sources ingested yet.")


async def test_moving_a_source_up_warns_and_moves(
    wiki: Path, user: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    auth.add_user("lead", "pw", [DB], maintains=[DB], clearance={DB: "confidential"})
    with db_context.clearance({DB: 1}):
        db_context.ensure_shard(f"{DB}@confidential")
    moved: list[tuple[str, str, str]] = []

    def move(name: str, target: str, user_: str) -> dict[str, Any]:
        moved.append((name, target, user_))
        return {"review": ["insights/old.md"]}

    monkeypatch.setattr(wiki_engine, "move_source", move)
    await _open(user, "lead", "pw")
    await _section(user, "Delete source")
    await _see(user, "Move to another classification level")
    await _see(user, "Moving up removes every trace from this level")
    (await _find(user, "move-source")).click()
    await _see(user, "Moved doc.md to")
    await _see(user, "insights/old.md")
    assert moved == [("doc.md", f"{DB}@confidential", "lead")]


async def test_no_move_offer_without_another_reachable_level(wiki: Path, user: User) -> None:
    await _open(user)
    await _section(user, "Delete source")
    await _see(user, "This cannot be undone.")
    await user.should_not_see("Move to another classification level")


async def test_orphans_are_listed(wiki: Path, user: User) -> None:
    await _open(user)
    await _section(user, "Link graph health")
    await _see(user, "lonely.md")


async def test_lint_shows_the_report_or_the_error(
    wiki: Path, user: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(wiki_engine, "lint", lambda: "## Findings\n\nAll good.")
    await _open(user)
    await _section(user, "Lint")
    (await _find(user, "run-lint")).click()
    await _see(user, "All good.")

    def broken() -> str:
        raise RuntimeError("model gone")

    monkeypatch.setattr(wiki_engine, "lint", broken)
    (await _find(user, "run-lint")).click()
    await _see(user, "model gone")


async def test_page_language_scans_then_normalizes(
    wiki: Path, user: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    report = {"a.md": {"lang": "de", "foreign_lines": 2, "references": False}}
    calls: list[bool] = []

    def normalize(dry_run: bool = True) -> dict[str, Any]:
        calls.append(dry_run)
        return report

    monkeypatch.setattr(wiki_engine, "normalize_pages", normalize)
    await _open(user)
    await _section(user, "Page language")
    (await _find(user, "scan-pages")).click()
    await _see(user, "1 pages to update")
    await _see(user, "a.md")
    (await _find(user, "normalize-pages")).click()
    await _see(user, "Updated 1 pages.")
    assert calls == [True, False]


async def test_a_clean_scan_says_so(
    wiki: Path, user: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(wiki_engine, "normalize_pages", lambda dry_run=True: {})
    await _open(user)
    await _section(user, "Page language")
    (await _find(user, "scan-pages")).click()
    await _see(user, "Every page is pinned to one language")


async def test_the_activity_log_is_shown(wiki: Path, user: User) -> None:
    (db_context.wiki_dir() / "log.md").write_text("## [2026-09-30] ingest | doc.md\n")
    await _open(user)
    await _section(user, "Activity log")
    await _see(user, "ingest | doc.md")
    await _see(user, "Times in this log are UTC.")


async def test_the_ontology_section_shows_the_workbench(wiki: Path, user: User) -> None:
    await _open(user)
    await _section(user, "Ontology")
    await _see(user, "No ontology for this database.")


def _strict_log() -> None:
    strict = f"{DB}@strict"
    with db_context.clearance({DB: 2}):
        db_context.ensure_shard(strict)
        with db_context.using_db(strict):
            wiki_engine.init_wiki()
            (db_context.wiki_dir() / "log.md").write_text("CANARY-strict-log\n")


async def test_a_reader_never_sees_a_higher_levels_log_or_a_level_picker(
    wiki: Path, user: User
) -> None:
    _strict_log()
    await _open(user, "reader", "pw")
    await _section(user, "Activity log")
    await _see(user, "Wiki pages 3")
    await user.should_not_see("CANARY-strict-log")
    await user.should_not_see("maint-level")


async def test_a_cleared_user_switches_level_and_the_sections_follow(
    wiki: Path, user: User
) -> None:
    _strict_log()
    auth.set_clearance("reader", DB, "strict", by="t")
    await _open(user, "reader", "pw")
    await _section(user, "Activity log")
    await user.should_not_see("CANARY-strict-log")
    (level,) = user.find("maint-level").elements
    assert isinstance(level, ui.toggle)
    level.set_value(f"{DB}@strict")
    await _see(user, "CANARY-strict-log")
    await _see(user, "Wiki pages 0")
