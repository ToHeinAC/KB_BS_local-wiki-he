"""Explorer page of the Broadsheet frontend (src/gui_explorer.py)."""

import asyncio
from pathlib import Path
from typing import Any

import frontmatter
import pytest
from nicegui import ui
from nicegui.testing import User

import auth
import db_context
import gui_app
import gui_explorer
import gui_session
import ollama_client
import wiki_engine

DB = db_context.DEFAULT_DB


def _page(
    name: str,
    title: str,
    ptype: str = "concept",
    related: tuple[str, ...] = (),
    sources: tuple[str, ...] = ("doc.md",),
    body: str = "Body text.",
) -> None:
    post = frontmatter.Post(f"# {title}\n\n{body}", title=title, type=ptype)
    post.metadata["sources"] = list(sources)
    post.metadata["related"] = list(related)
    (db_context.wiki_dir() / name).write_text(frontmatter.dumps(post))


@pytest.fixture
def wiki(gui_env: Path) -> Path:
    (db_context.raw_dir() / "doc.md").write_text("# Doc\n\nOriginal text of doc.")
    _page("alpha.md", "Alpha", related=("beta.md",), body="Alpha discusses orbital cooling.")
    _page("beta.md", "Beta", ptype="entity")
    wiki_engine.rebuild_lex_index()
    return gui_env


@pytest.fixture(autouse=True)
def _pages(user: User, gui_env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    gui_session._SESSIONS.clear()
    monkeypatch.setattr(ollama_client, "generate", lambda *a, **k: "")
    gui_app.register()


async def _open(user: User, name: str = auth.DEFAULT_USER, pw: str = auth.DEFAULT_PASSWORD) -> None:
    await user.open("/login")
    user.find("Username").type(name)
    user.find("Password").type(pw)
    user.find("sign-in").click()
    await _see(user, "2BrAIn")
    await user.open("/explorer")


def _session() -> gui_session.Session:
    (session,) = gui_session._SESSIONS.values()
    return session


async def _see(user: User, text: str) -> None:
    """`should_see` with a patient wait: the map loads in a worker, and coverage slows it down."""
    await user.should_see(text, retries=100)


async def _until(check: Any, tries: int = 60) -> None:
    for _ in range(tries):
        if check():
            return
        await asyncio.sleep(0.05)


async def test_an_empty_wiki_shows_onboarding_not_an_empty_map(gui_env: Path, user: User) -> None:
    await _open(user)
    await _see(user, "No wiki pages yet")


async def test_the_map_view_lists_the_standings_and_counts(wiki: Path, user: User) -> None:
    await _open(user)
    await _see(user, "Alpha")
    await _see(user, "Beta")
    await _see(user, "2 pages")


async def test_choosing_a_page_opens_it_in_the_reader_with_sources_and_links(
    wiki: Path, user: User
) -> None:
    await _open(user)
    await _see(user, "Alpha")
    user.find("row-alpha.md").click()
    await _see(user, "Alpha discusses orbital cooling.")
    await _see(user, "doc.md")  # original document, from the page's sources
    await _see(user, "Download")
    user.find("chip-beta.md").click()
    await _until(lambda: gui_explorer.explorer_state(_session()).selected == "beta.md")
    assert gui_explorer.explorer_state(_session()).selected == "beta.md"


async def test_closing_the_reader_returns_to_the_bundle_health(wiki: Path, user: User) -> None:
    await _open(user)
    await _see(user, "Bundle health")
    user.find("row-alpha.md").click()
    await _see(user, "Alpha discusses orbital cooling.")
    user.find("close-reader").click()
    await _see(user, "Bundle health")


async def test_a_source_in_the_reader_opens_the_original(wiki: Path, user: User) -> None:
    await _open(user)
    await _see(user, "Alpha")
    user.find("row-alpha.md").click()
    await _see(user, "doc.md")
    user.find("source-doc.md").click()
    await _see(user, "Original text of doc.")


async def test_the_index_view_groups_pages_by_type(wiki: Path, user: User) -> None:
    await _open(user)
    (view,) = user.find("view").elements
    assert isinstance(view, ui.toggle)
    view.set_value("Index")
    await _see(user, "Concepts (1)")
    await _see(user, "Entities (1)")
    user.find("nav-beta.md").click()
    await _see(user, "Beta")
    await _until(lambda: gui_explorer.explorer_state(_session()).selected == "beta.md")


async def test_find_lists_hits_with_an_excerpt(wiki: Path, user: User) -> None:
    await _open(user)
    user.find("find").type("orbital")
    await _see(user, "1 result")
    await _see(user, "Alpha discusses orbital cooling.")


async def test_find_without_an_index_says_so_instead_of_no_results(wiki: Path, user: User) -> None:
    (db_context.wiki_dir().parent / "index" / "chunks.sqlite").unlink()
    await _open(user)
    user.find("find").type("orbital")
    await _see(user, "No search index")


async def test_a_reader_never_sees_a_higher_level_page(wiki: Path, user: User) -> None:
    strict = f"{DB}@strict"
    with db_context.clearance({DB: 2}):
        db_context.ensure_shard(strict)
        with db_context.using_db(strict):
            wiki_engine.init_wiki()
            _page("secret.md", "Canary Secret", body="CANARY-strict-only")
            wiki_engine.rebuild_lex_index()
    await _open(user, "reader", "pw")
    await _see(user, "Alpha")
    await user.should_not_see("Canary Secret")
    await user.should_not_see("Level")  # no level picker without a higher level to reach


async def test_a_cleared_user_switches_level_and_sees_only_that_levels_pages(
    wiki: Path, user: User
) -> None:
    strict = f"{DB}@strict"
    auth.set_clearance("reader", DB, "strict", by="t")
    with db_context.clearance({DB: 2}):
        db_context.ensure_shard(strict)
        with db_context.using_db(strict):
            wiki_engine.init_wiki()
            _page("secret.md", "Canary Secret", body="CANARY-strict-only")
            wiki_engine.rebuild_lex_index()
    await _open(user, "reader", "pw")
    await _see(user, "Alpha")
    await user.should_not_see("Canary Secret")
    (level,) = user.find("level").elements
    assert isinstance(level, ui.toggle)
    level.set_value(strict)
    await _see(user, "Canary Secret")
    await user.should_not_see("Alpha")
    assert (_session().shard, _session().scope) == (strict, [strict])


def test_search_hits_are_reduced_to_plain_excerpts() -> None:
    assert gui_explorer.plain_excerpt("## Heading\n**bold** and `code`\n\n- item") == (
        "Heading bold and code - item"
    )
    assert gui_explorer.plain_excerpt("") == ""
