"""Front page of the Broadsheet frontend (src/gui_front.py)."""

from pathlib import Path

import frontmatter
import pytest
from nicegui import ui
from nicegui.testing import User, UserInteraction

import auth
import db_context
import gui_app
import gui_explorer
import gui_front
import gui_session
import okf
import wiki_engine

LOG = okf.add_log_entry(
    okf.add_log_entry("", "ingest", "old.pdf", day="2026-09-24", time="09:15"),
    "ingest",
    "orbit.pdf  created 2",
    day="2026-09-29",
    time="18:40",
)

# --- pure helpers ------------------------------------------------------------------------------


def test_log_entries_are_newest_first_with_their_day() -> None:
    assert gui_front.log_entries(LOG, limit=5) == [
        ("2026-09-29", "18:40", "ingest", "orbit.pdf created 2"),
        ("2026-09-24", "09:15", "ingest", "old.pdf"),
    ]
    assert gui_front.log_entries(LOG, limit=1) == [
        ("2026-09-29", "18:40", "ingest", "orbit.pdf created 2")
    ]


def test_log_lines_in_other_formats_are_ignored() -> None:
    assert gui_front.log_entries("(no log yet)", limit=5) == []
    assert gui_front.log_entries("## 2026-01-01\n- stray text\n- 10:00 — lint", limit=5) == [
        ("2026-01-01", "10:00", "lint", "")
    ]


def test_figures_and_growing_clusters() -> None:
    health = {
        "pages": 3, "sources": 1, "orphans": ["c.md"], "stale": [], "outdated": ["a.md"],
        "low_confidence": [], "window_days": 30,
        "clusters": [
            {"label": "Beta", "size": 2, "recent": 2},
            {"label": "Gamma", "size": 1, "recent": 0},
        ],
    }  # fmt: skip
    assert gui_front.figures(health) == [
        ("Pages", 3, False),
        ("Source documents", 1, False),
        ("Pages with no links", 1, True),
        ("Stale pages", 0, False),
        ("Built on outdated versions", 1, True),
        ("Low confidence", 0, False),
    ]
    assert gui_front.growing(health) == [("Beta", 2)]


# --- page ----------------------------------------------------------------------------------------


def _page(name: str, title: str, related: tuple[str, ...] = ()) -> None:
    post = frontmatter.Post(f"# {title}\n\n{title} explains orbits.", title=title, type="concept")
    post.metadata["related"] = list(related)
    post.metadata["description"] = f"All about {title}."
    post.metadata["updated"] = "2026-09-20"
    (db_context.wiki_dir() / name).write_text(frontmatter.dumps(post))


@pytest.fixture
def wiki(gui_env: Path) -> Path:
    _page("hub.md", "Hub", related=("a.md", "b.md"))
    _page("a.md", "Leaf A", related=("hub.md",))
    _page("b.md", "Leaf B", related=("hub.md",))
    (db_context.wiki_dir() / "log.md").write_text(LOG)
    wiki_engine.rebuild_lex_index()
    return gui_env


@pytest.fixture(autouse=True)
def _pages(user: User, gui_env: Path) -> None:
    gui_session._SESSIONS.clear()
    gui_app.register()


async def _see(user: User, text: str) -> None:
    await user.should_see(text, retries=100)


async def _sign_in(user: User) -> None:
    await user.open("/login")
    user.find("Username").type(auth.DEFAULT_USER)
    user.find("Password").type(auth.DEFAULT_PASSWORD)
    user.find("sign-in").click()
    await user.should_see("2BrAIn")


def _session() -> gui_session.Session:
    (session,) = gui_session._SESSIONS.values()
    return session


async def test_an_empty_wiki_shows_onboarding(user: User) -> None:
    await _sign_in(user)
    await _see(user, "No wiki pages yet")


async def test_2brain_shows_activity_the_galaxy_upload_and_figures(wiki: Path, user: User) -> None:
    await _sign_in(user)
    await _see(user, "Your documents, compiled into a linked archive on your infrastructure")
    await _see(user, "orbit.pdf created 2")
    await _see(user, "3 pages, ")  # the galaxy's caption
    await _see(user, "front-map")
    await _see(user, "upload-files")
    await _see(user, "The archive in figures")
    await _see(user, "Pages with no links")
    await user.should_not_see("Ask the archive")


async def test_the_tagline_shares_the_date_line_and_there_is_no_nameplate(
    wiki: Path, user: User
) -> None:
    await _sign_in(user)
    await _see(user, "on your infrastructure")
    (tagline,) = user.find("on your infrastructure").elements
    assert tagline.parent_slot is not None
    line = tagline.parent_slot.parent
    assert "dateline" in line.classes
    assert not [e for e in user.find(ui.label).elements if e.text == "2BrAIn"]


async def test_an_empty_wiki_still_offers_the_upload(user: User) -> None:
    await _sign_in(user)
    await _see(user, "No wiki pages yet")
    await _see(user, "upload-files")


async def test_double_clicking_a_galaxy_node_opens_it_in_the_explorer(
    wiki: Path, user: User
) -> None:
    await _sign_in(user)
    await _see(user, "front-map")
    assert user.client is not None
    layout = UserInteraction(user, {user.client.layout}, None)
    layout.trigger("graph_open", {"node": "hub.md", "kind": "page"})
    await _see(user, "Hub explains orbits.")
    assert gui_explorer.explorer_state(_session()).selected == "hub.md"


async def test_a_reader_is_not_told_to_upload(user: User) -> None:
    await user.open("/login")
    user.find("Username").type("reader")
    user.find("Password").type("pw")
    user.find("sign-in").click()
    await _see(user, "A maintainer of this database can add documents.")
    await user.should_not_see("upload-files")
