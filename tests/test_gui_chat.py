"""Chat page of the Broadsheet frontend (src/gui_chat.py)."""

import asyncio
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from nicegui import ui
from nicegui.testing import User

import auth
import chat_agent
import db_context
import gui_app
import gui_chat
import gui_session
import lex_index
import tools
import wiki_engine

DB = db_context.DEFAULT_DB
ANSWER = "Fewer than claimed [Source: ai.md §6.1] and cooling [Wiki: p.md]."
FAST = {"answer": ANSWER, "sources": ["p.md"], "raw_sources": ["ai.md"], "audit": None}


@pytest.fixture(autouse=True)
def _pages(user: User, gui_env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    gui_session._SESSIONS.clear()
    monkeypatch.setattr(lex_index, "index_health", lambda: {"raw": 3, "wiki": 2})
    monkeypatch.setattr(wiki_engine, "query_with_sources", lambda q: FAST)
    gui_app.register()


async def _open(user: User, name: str = auth.DEFAULT_USER, pw: str = auth.DEFAULT_PASSWORD) -> None:
    await user.open("/login")
    user.find("Username").type(name)
    user.find("Password").type(pw)
    user.find("sign-in").click()
    await user.should_see("2BrAIn")
    await user.open("/chat")


async def _ask(user: User, question: str) -> None:
    user.find("chat-input").type(question)
    user.find("ask").click()


def _session() -> gui_session.Session:
    (session,) = gui_session._SESSIONS.values()
    return session


# --- pure helpers ------------------------------------------------------------------------------


def test_deep_steps_collect_the_final_answer_and_its_sources() -> None:
    acc = gui_chat.new_deep()
    gui_chat.apply_deep_step(acc, {"type": "thought", "content": "hm"})
    gui_chat.apply_deep_step(
        acc,
        {"type": "final_answer", "content": "A", "sources": ["r.md"], "wiki_sources": ["p.md"]},
    )
    assert acc == {"answer": "A", "raw_sources": ["r.md"], "wiki_pages": ["p.md"]}


def test_an_error_step_is_the_answer_only_when_there_is_none_yet() -> None:
    acc = gui_chat.new_deep()
    gui_chat.apply_deep_step(acc, {"type": "error", "content": "boom"})
    assert acc["answer"] == "Error: boom"
    gui_chat.apply_deep_step(acc, {"type": "final_answer", "content": "A"})
    gui_chat.apply_deep_step(acc, {"type": "error", "content": "later"})
    assert acc["answer"] == "A"


# --- page --------------------------------------------------------------------------------------


async def test_the_chat_page_offers_modes_scope_and_an_input(user: User) -> None:
    await _open(user)
    for text in ("How to answer", "Fast", "Deep", "Search in", "New conversation"):
        await user.should_see(text)


async def test_a_missing_search_index_is_reported_not_silently_empty(
    user: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(lex_index, "index_health", lambda: {"raw": 0, "wiki": 0})
    await _open(user)
    await user.should_see("No search index")


async def test_a_fast_answer_shows_numbered_citations_and_margin_notes(user: User) -> None:
    await _open(user)
    await _ask(user, "What is cooling?")
    await user.should_see("What is cooling?")
    await user.should_see('<sup class="cite" data-n="1">1</sup>')
    await user.should_see("ai.md §6.1")
    await user.should_see("p.md")
    await user.should_see("Fast answer")


async def test_a_deep_answer_streams_its_trace_and_shows_the_audit(
    user: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    def agent(q: str) -> Iterator[dict[str, Any]]:
        yield {"type": "tool_call", "name": "raw_search", "args": {"q": q}}
        yield {"type": "final_answer", "content": ANSWER, "sources": ["ai.md"], "wiki_sources": []}

    audit = {"kept": [("ai.md", 0.9)], "below_tau": [], "over_cap": [], "ontology": [], "tau": 0.5}
    monkeypatch.setattr(chat_agent, "run_chat_agent", agent)
    monkeypatch.setattr(tools, "current_run_audit", lambda db=None: audit)
    await _open(user)
    (toggle,) = user.find("mode").elements
    assert isinstance(toggle, ui.toggle)
    toggle.set_value("Deep")
    await _ask(user, "Deep question")
    await user.should_see("Deep answer")
    await user.should_see("How the answer ran")
    await user.should_not_see("How this answer was made")
    (rail,) = user.find("chat-run").elements
    texts = [str(getattr(e, "text", "") or e.props.get("label", "")) for e in rail.descendants()]
    assert {"How the answer ran", "raw_search"} <= set(texts)
    await user.should_see("Why these sources")


async def test_a_backend_error_becomes_the_answer_without_actions(
    user: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    err = {"answer": "Error: model gone", "sources": [], "raw_sources": [], "audit": None}
    monkeypatch.setattr(wiki_engine, "query_with_sources", lambda q: err)
    await _open(user)
    await _ask(user, "Q")
    await user.should_see("Error: model gone")
    await user.should_not_see("Save to wiki")
    await user.should_not_see("Follow up")


async def test_a_follow_up_is_condensed_against_the_previous_turn(
    user: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    asked: list[str] = []
    monkeypatch.setattr(wiki_engine, "query_with_sources", lambda q: asked.append(q) or FAST)
    monkeypatch.setattr(wiki_engine, "condense_followup", lambda q, a, f: f"{q} / {f}")
    await _open(user)
    await _ask(user, "First?")
    await user.should_see("Follow up")
    user.find("follow-up").click()
    await user.should_see("Follow-up to")
    await _ask(user, "and more")
    await user.should_see("Interpreted as")
    assert asked == ["First?", "First? / and more"]


async def test_maintainers_can_save_the_answer_at_the_searched_level(
    user: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    filed: dict[str, Any] = {}

    def file_answer(q: str, a: str, related: list[str], derived_from: list[str]) -> str:
        filed.update(db=db_context.get_active_db(), q=q, derived=derived_from)
        return "insights/x.md"

    monkeypatch.setattr(wiki_engine, "file_answer", file_answer)
    await _open(user)
    await _ask(user, "Save me")
    await user.should_see("Save to wiki")
    user.find("save-answer").click()
    await user.should_see("Filed as insights/x.md")
    assert filed == {"db": DB, "q": "Save me", "derived": ["p.md", "ai.md"]}


async def test_readers_cannot_save(user: User) -> None:
    await _open(user, "reader", "pw")
    await _ask(user, "Q")
    await user.should_see("Fast answer")
    await user.should_not_see("Save to wiki")


async def test_new_conversation_clears_the_history(user: User) -> None:
    await _open(user)
    await _ask(user, "Remember me")
    await user.should_see("Fast answer")
    user.find("new-chat").click()
    await user.should_not_see("Fast answer")


async def test_scope_lists_every_reachable_level_and_names_a_wide_scope(user: User) -> None:
    auth.set_clearance("reader", DB, "confidential", by="t")
    with db_context.clearance({DB: 1}):
        db_context.ensure_shard(f"{DB}@confidential")
    await _open(user, "reader", "pw")
    await user.should_see(f"{DB} · Confidential")
    await user.should_see("Searching in 2 places")
    assert _session().scope == [DB, f"{DB}@confidential"]


async def test_narrowing_the_scope_rebinds_the_session(user: User) -> None:
    auth.set_clearance("reader", DB, "confidential", by="t")
    with db_context.clearance({DB: 1}):
        db_context.ensure_shard(f"{DB}@confidential")
    await _open(user, "reader", "pw")
    user.find(f"scope-{DB}@confidential").click()
    for _ in range(40):
        if _session().scope == [DB]:
            break
        await asyncio.sleep(0.05)
    assert _session().scope == [DB]


async def test_a_margin_note_opens_the_cited_original(
    user: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(wiki_engine, "read_raw_source", lambda name: f"Text of {name}".encode())
    await _open(user)
    await _ask(user, "Q")
    await user.should_see("ai.md §6.1")
    user.find("note-1").click()
    await user.should_see("Text of ai.md")
    await user.should_see("Download")


async def test_an_answer_offers_a_markdown_export(user: User) -> None:
    await _open(user)
    await _ask(user, "Q")
    await user.should_see("ai.md §6.1")
    await user.should_see("export-md")


def test_the_hover_script_pairs_numerals_with_notes() -> None:
    assert "sup.cite" in gui_app.CITE_JS
    assert ".note[data-n" in gui_app.CITE_JS


CANARY = "CANARY-7f3a-strict-only"


def _plant_strict_canary() -> None:
    strict = f"{DB}@strict"
    with db_context.clearance({DB: 2}):
        db_context.ensure_shard(strict)
        with db_context.using_db(strict):
            (db_context.raw_dir() / "secret.md").write_text(CANARY)
            (db_context.wiki_dir() / "secret-page.md").write_text(f"# S\n\n{CANARY}\n")


@pytest.mark.parametrize(
    ("citation", "shown"),
    [
        (f"[Source: {DB}@strict::secret.md]", "This document cannot be previewed."),
        (f"[Wiki: {DB}@strict::secret-page.md]", "Page not found"),
    ],
)
async def test_a_reader_cannot_open_a_higher_level_document_through_a_citation(
    user: User, monkeypatch: pytest.MonkeyPatch, citation: str, shown: str
) -> None:
    _plant_strict_canary()
    answer = {"answer": f"Claim {citation}.", "sources": [], "raw_sources": [], "audit": None}
    monkeypatch.setattr(wiki_engine, "query_with_sources", lambda q: answer)
    await _open(user, "reader", "pw")
    await _ask(user, "Q")
    await user.should_see("Claim")
    user.find("note-1").click()
    await user.should_see(shown)
    await user.should_not_see(CANARY)


async def test_a_cleared_user_can_open_the_same_document(
    user: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    _plant_strict_canary()
    auth.set_clearance("reader", DB, "strict", by="t")
    cite = f"[Source: {DB}@strict::secret.md]"
    answer = {"answer": f"Claim {cite}.", "sources": [], "raw_sources": [], "audit": None}
    monkeypatch.setattr(wiki_engine, "query_with_sources", lambda q: answer)
    await _open(user, "reader", "pw")
    await _ask(user, "Q")
    await user.should_see("Claim")
    user.find("note-1").click()
    await user.should_see(CANARY)
