"""Front page of the Broadsheet frontend (src/gui_front.py)."""

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
import gui_chat
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

PAYLOAD = {
    "nodes": [
        {"id": "a.md", "label": "Alpha", "kind": "page", "cat": "concept", "pr": 0.1, "deg": 2,
         "updated": "2026-09-01"},
        {"id": "b.md", "label": "Beta", "kind": "page", "cat": "entity", "pr": 0.5, "deg": 7,
         "updated": "2026-09-20"},
        {"id": "c.md", "label": "Gamma", "kind": "page", "cat": "source-summary", "pr": 0.2,
         "deg": 1, "updated": None},
        {"id": "source::x.pdf", "label": "x.pdf", "kind": "source", "cat": "source", "pr": 0.9,
         "deg": 3, "updated": None},
    ],
    "edges": [],
    "communities": 1,
}  # fmt: skip


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


def test_the_lead_is_the_page_with_the_highest_pagerank() -> None:
    lead = gui_front.lead_page(PAYLOAD)
    assert lead is not None
    assert (lead["id"], lead["deg"]) == ("b.md", 7)
    assert gui_front.lead_page({"nodes": []}) is None


def test_recent_pages_are_pages_by_update_date_skipping_undated_and_the_lead() -> None:
    rows = gui_front.recent_pages(PAYLOAD, skip="b.md", limit=3)
    assert [(r["id"], r["kind"]) for r in rows] == [("a.md", "Concept")]


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


async def _until(check: Any, tries: int = 100) -> None:
    for _ in range(tries):
        if check():
            return
        await asyncio.sleep(0.05)


async def _sign_in(user: User) -> None:
    await user.open("/login")
    user.find("Username").type(auth.DEFAULT_USER)
    user.find("Password").type(auth.DEFAULT_PASSWORD)
    user.find("sign-in").click()
    await user.should_see("Front page")


def _session() -> gui_session.Session:
    (session,) = gui_session._SESSIONS.values()
    return session


async def test_an_empty_wiki_shows_onboarding(user: User) -> None:
    await _sign_in(user)
    await _see(user, "No wiki pages yet")


async def test_the_front_page_shows_activity_the_lead_page_and_figures(
    wiki: Path, user: User
) -> None:
    await _sign_in(user)
    await _see(user, "Your documents, compiled into a linked archive on this machine")
    await _see(user, "orbit.pdf created 2")
    await _see(user, "The most connected page in this edition")
    await _see(user, "Hub")
    await _see(user, "All about Hub.")
    await _see(user, "Linked to 2 pages")
    await _see(user, "The archive in figures")
    await _see(user, "Pages with no links")


async def test_opening_the_lead_page_lands_in_the_explorer_reader(wiki: Path, user: User) -> None:
    await _sign_in(user)
    await _see(user, "Open the page")
    user.find("open-lead").click()
    await _see(user, "Hub explains orbits.")
    assert gui_explorer.explorer_state(_session()).selected == "hub.md"


async def test_asking_the_archive_runs_the_question_in_chat(
    wiki: Path, user: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    asked: list[str] = []
    answer = {"answer": "Orbits are paths.", "sources": [], "raw_sources": [], "audit": None}
    monkeypatch.setattr(wiki_engine, "query_with_sources", lambda q: asked.append(q) or answer)
    await _sign_in(user)
    await _see(user, "Ask the archive")
    user.find("front-question").type("What is an orbit?")
    user.find("front-ask").click()
    await _see(user, "Orbits are paths.")
    assert asked == ["What is an orbit?"]
    assert gui_chat.chat_state(_session()).pending is None


async def test_asking_in_deep_mode_sets_the_chat_mode(
    wiki: Path, user: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    started: list[str] = []

    def deep(q: str) -> Any:
        started.append(q)
        yield {
            "type": "final_answer",
            "content": "Deep says so.",
            "sources": [],
            "wiki_sources": [],
        }

    monkeypatch.setattr(gui_chat.chat_agent, "run_chat_agent", deep)
    await _sign_in(user)
    await _see(user, "Ask the archive")
    (mode,) = user.find("front-mode").elements
    assert isinstance(mode, ui.toggle)
    mode.set_value("Deep")
    user.find("front-question").type("Deep?")
    user.find("front-ask").click()
    await _see(user, "Deep says so.")
    assert started == ["Deep?"]
    assert gui_chat.chat_state(_session()).mode == "Deep"


async def test_an_empty_question_stays_on_the_front_page(wiki: Path, user: User) -> None:
    await _sign_in(user)
    await _see(user, "Ask the archive")
    user.find("front-ask").click()
    await _see(user, "The archive in figures")
    assert gui_chat.chat_state(_session()).pending is None


async def test_a_reader_is_not_told_to_upload(user: User) -> None:
    await user.open("/login")
    user.find("Username").type("reader")
    user.find("Password").type("pw")
    user.find("sign-in").click()
    await _see(user, "A maintainer of this database can add documents.")
