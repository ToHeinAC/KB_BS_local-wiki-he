"""Research page of the Broadsheet frontend (src/gui_research.py)."""

import asyncio
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from nicegui import ui
from nicegui.testing import User

import agent
import auth
import db_context
import deep_research_agent
import gui_app
import gui_research
import gui_session
import tools
import wiki_engine

DB = db_context.DEFAULT_DB
ANSWER = "Defence pays [Source: https://eo.example/a] and launch [Source: https://l.example/b]."
REPORT = "/data/x/comparisons/report.md"


def quick_run(q: str, ctx: str) -> Iterator[dict[str, Any]]:
    yield {"type": "thought", "content": "plan the search"}
    yield {"type": "tool_call", "name": "wiki_search", "args": {"query": q}}
    yield {"type": "tool_result", "name": "wiki_search", "result": "3 hits", "sources": []}
    yield {"type": "final_answer", "content": ANSWER, "report_path": REPORT}


def deep_run(q: str, ctx: str) -> Iterator[dict[str, Any]]:
    yield {"type": "notice", "content": "Deep mode fell back to Quick."}
    yield {"type": "tool_call", "name": "web_search", "args": {"q": q}}
    yield {
        "type": "tool_result",
        "name": "web_search",
        "result": "r",
        "sources": [
            {"url": "https://eo.example/a", "title": "EO budgets"},
            {"url": "https://x.example/c", "title": "Extra reading"},
        ],
    }
    yield {"type": "tool_call", "name": "ResearchComplete", "args": {}, "terminal": True}
    yield {
        "type": "final_answer",
        "content": ANSWER,
        "metrics": {"tasks": 2, "searches": 5, "sources_checked": 9, "sources_cited": 2},
    }


@pytest.fixture(autouse=True)
def _pages(user: User, gui_env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    gui_session._SESSIONS.clear()
    monkeypatch.setenv("TAVILY_API_KEY", "key")
    monkeypatch.setattr(agent, "run_research_agent", quick_run)
    monkeypatch.setattr(deep_research_agent, "run_deep_research", deep_run)
    monkeypatch.setattr(tools, "current_run_audit", lambda db=None: None)
    monkeypatch.setattr(
        wiki_engine, "read_page_parsed", lambda ref: {"content": f"# Report\n\n{ANSWER}"}
    )
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
    await user.open("/research")


async def _start(user: User, question: str = "Who pays?") -> None:
    user.find("research-question").type(question)
    user.find("start-research").click()


def _session() -> gui_session.Session:
    (session,) = gui_session._SESSIONS.values()
    return session


# --- pure helpers ---------------------------------------------------------------------------


def test_urls_are_recorded_once_and_keep_their_order() -> None:
    panel: list[dict[str, str]] = [{"url": "https://a", "title": "A"}]
    step = {"sources": [{"url": "https://a", "title": "A"}, {"url": "https://b", "title": "B"}]}
    gui_research.record_urls(panel, step)
    gui_research.record_urls(panel, {})
    assert [s["url"] for s in panel] == ["https://a", "https://b"]


def test_steps_feed_the_sources_panel_and_the_error_line() -> None:
    run = gui_research.Research()
    gui_research.apply_step(run, {"type": "tool_call", "name": "web_search", "args": {"q": "x"}})
    gui_research.apply_step(run, {"type": "tool_result", "name": "n", "result": "", "sources": [
        {"url": "https://a", "title": "A"}]})  # fmt: skip
    gui_research.apply_step(run, {"type": "error", "content": "boom"})
    assert run.sources == [
        {"tool": "web_search", "query": "{'q': 'x'}"},
        {"url": "https://a", "title": "A"},
    ]
    assert run.error == "boom"
    assert [s["type"] for s in run.steps] == ["tool_call", "tool_result", "error"]
    assert all(s["at"] for s in run.steps)


def test_metric_tiles_drop_sources_checked_when_it_repeats_the_searches() -> None:
    full = {"tasks": 2, "searches": 5, "sources_checked": 9, "sources_cited": 2}
    assert gui_research.metric_tiles(full) == [
        ("Sub-tasks", 2),
        ("Web searches", 5),
        ("Pages read", 9),
        ("Sources cited", 2),
    ]
    same = {"tasks": 1, "searches": 4, "sources_checked": 4, "sources_cited": 3}
    assert [label for label, _ in gui_research.metric_tiles(same)] == [
        "Sub-tasks",
        "Web searches",
        "Sources cited",
    ]
    assert gui_research.metric_tiles(None) == []


def test_a_run_resets_the_previous_results_and_notes_a_rephrased_question() -> None:
    run = gui_research.Research(answer="old", error="e", steps=[{"type": "x"}], saved="s")
    interpreted = gui_research.new_run(run, "standalone question", "asked")
    assert interpreted == "standalone question"
    assert (run.answer, run.error, run.steps, run.saved, run.question) == ("", "", [], "", "asked")
    assert gui_research.new_run(run, "same", "same") is None


def test_finishing_a_run_records_history_and_flags_an_empty_answer() -> None:
    run = gui_research.Research()
    step = {"type": "final_answer", "content": "", "report_path": REPORT}
    gui_research.finish(run, step, "q", None, reread=None)
    assert run.error.startswith("The agent finished but produced no answer text")
    assert run.history == [
        {"q": "q", "a": "", "interpreted": None, "report": "comparisons/report.md"}
    ]
    ok = gui_research.Research()
    gui_research.finish(ok, {"type": "final_answer", "content": "A"}, "q", "i", reread="Re-read")
    assert (ok.answer, ok.error, ok.report) == ("Re-read", "", "")


# --- page -----------------------------------------------------------------------------------


async def test_without_a_tavily_key_research_is_disabled_and_says_why(
    user: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("TAVILY_API_KEY")
    await _open(user)
    await _see(user, "TAVILY_API_KEY not set")
    (start,) = user.find("start-research").elements
    assert isinstance(start, ui.button)
    assert not start.enabled


async def test_a_quick_run_shows_the_report_with_numbered_web_citations(user: User) -> None:
    await _open(user)
    await _start(user)
    await _see(user, "Research report")
    await _see(user, '<sup class="cite" data-n="1">1</sup>')
    await _see(user, "eo.example")
    await _see(user, "How the research ran")
    await _see(user, "wiki_search")


async def test_a_deep_run_shows_metrics_the_terminal_step_and_the_fallback_notice(
    user: User,
) -> None:
    await _open(user)
    (toggle,) = user.find("research-method").elements
    assert isinstance(toggle, ui.toggle)
    toggle.set_value("Deep")
    await _start(user)
    await _see(user, "Deep research report")
    await _see(user, "Sub-tasks")
    await _see(user, "Pages read")
    await _see(user, "ResearchComplete — research phase finished")
    await _see(user, "Deep mode fell back to Quick.")


def _texts(user: User, marker: str) -> list[str]:
    (column,) = user.find(marker).elements
    return [
        str(getattr(e, "text", "") or e.props.get("label", ""))
        for e in [column, *column.descendants()]
    ]


async def test_run_report_and_sources_sit_in_three_columns_like_chat(user: User) -> None:
    await _open(user)
    (toggle,) = user.find("research-method").elements
    assert isinstance(toggle, ui.toggle)
    toggle.set_value("Deep")
    await _start(user)
    await _see(user, "Deep research report")
    run = _texts(user, "research-run")
    assert {"Sub-tasks", "How the research ran"} <= set(run)
    assert "Deep research report" in _texts(user, "research-report")
    sources = _texts(user, "research-sources")
    assert {"Sources", "EO budgets", "eo.example", "Also read (1)"} <= set(sources)
    assert "Extra reading" in sources
    assert "How the research ran" not in sources


async def test_a_run_without_a_result_says_so_instead_of_a_blank_page(
    user: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(agent, "run_research_agent", lambda q, c: iter([]))
    await _open(user)
    await _start(user)
    await _see(user, "The run ended without producing a result")


async def test_an_agent_error_is_shown_with_its_trace(
    user: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    def failing(q: str, ctx: str) -> Iterator[dict[str, Any]]:
        yield {"type": "error", "content": "Tavily refused"}

    monkeypatch.setattr(agent, "run_research_agent", failing)
    await _open(user)
    await _start(user)
    await _see(user, "Tavily refused")


async def test_an_empty_question_is_refused_without_running(user: User) -> None:
    await _open(user)
    user.find("start-research").click()
    await _see(user, "Enter a research question first.")


async def test_maintainers_save_the_report_and_may_register_it_as_a_source(
    user: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[tuple[str, str, str]] = []
    monkeypatch.setattr(
        wiki_engine,
        "ingest",
        lambda text, title: calls.append(("ingest", db_context.get_active_db(), title)),
    )
    monkeypatch.setattr(
        wiki_engine,
        "ingest_as_source",
        lambda text, title: (
            calls.append(("source", db_context.get_active_db(), title))
            or {"duplicate": False, "source_name": "s.md"}
        ),
    )
    await _open(user)
    await _start(user, "Who pays for orbit?")
    await _see(user, "Save to wiki")
    user.find("save-research").click()
    await _see(user, "Saved to wiki.")
    assert calls == [("ingest", DB, "Research: Who pays for orbit?")]


async def test_registering_as_a_source_saves_through_the_manifest(
    user: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        wiki_engine,
        "ingest_as_source",
        lambda text, title: {"duplicate": False, "source_name": "s.md"},
    )
    await _open(user)
    await _start(user)
    await _see(user, "Save to wiki")
    (box,) = user.find("as-source").elements
    assert isinstance(box, ui.checkbox)
    box.set_value(True)
    user.find("save-research").click()
    await _see(user, "Saved as source `s.md`.")


async def test_readers_cannot_save_a_report(user: User) -> None:
    await _open(user, "reader", "pw")
    await _start(user)
    await _see(user, "Research report")
    await user.should_not_see("Save to wiki")


async def test_a_follow_up_is_condensed_and_run_again(
    user: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    asked: list[str] = []

    def run(q: str, ctx: str) -> Iterator[dict[str, Any]]:
        asked.append(q)
        yield {"type": "final_answer", "content": ANSWER}

    monkeypatch.setattr(agent, "run_research_agent", run)
    monkeypatch.setattr(wiki_engine, "condense_followup", lambda q, a, f: f"{q} / {f}")
    await _open(user)
    await _start(user, "First?")
    await _see(user, "Research report")
    user.find("followup").type("and then?")
    user.find("followup-go").click()
    for _ in range(100):
        if len(asked) == 2:
            break
        await asyncio.sleep(0.05)
    assert asked == ["First?", "First? / and then?"]


async def test_new_research_clears_the_report(user: User) -> None:
    await _open(user)
    await _start(user)
    await _see(user, "Research report")
    user.find("new-research").click()
    await user.should_not_see("Research report")


def _strict_shard() -> None:
    with db_context.clearance({DB: 2}):
        db_context.ensure_shard(f"{DB}@strict")


async def test_no_classified_option_without_a_higher_level_and_scope_stays_on_the_active_db(
    user: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    _strict_shard()
    seen: list[tuple[str, ...]] = []

    def run(q: str, ctx: str) -> Iterator[dict[str, Any]]:
        seen.append(db_context.search_scope())
        yield {"type": "final_answer", "content": ANSWER}

    monkeypatch.setattr(agent, "run_research_agent", run)
    await _open(user, "reader", "pw")
    await user.should_not_see("Include classified levels")
    await _start(user)
    await _see(user, "Research report")
    assert seen == [(DB,)]


async def test_classified_research_searches_every_level_with_the_web_off_and_locks(
    user: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    _strict_shard()
    auth.set_clearance("reader", DB, "strict", by="t")
    seen: list[tuple[str, ...]] = []

    def run(q: str, ctx: str) -> Iterator[dict[str, Any]]:
        seen.append(db_context.search_scope())
        yield {"type": "final_answer", "content": ANSWER}

    monkeypatch.setattr(agent, "run_research_agent", run)
    monkeypatch.setattr(deep_research_agent, "run_deep_research", lambda q, c: pytest.fail("web"))
    await _open(user, "reader", "pw")
    (box,) = user.find("classified-levels").elements
    assert isinstance(box, ui.checkbox)
    box.set_value(True)
    (toggle,) = user.find("research-method").elements
    assert isinstance(toggle, ui.toggle)
    await _until(lambda: not toggle.enabled)
    assert not toggle.enabled
    assert toggle.value == "Quick"
    await _start(user)
    await _see(user, "Research report")
    assert seen == [(DB, f"{DB}@strict")]
    assert not box.enabled  # locked until New research
    user.find("new-research").click()
    await _until(lambda: box.enabled)
    assert box.enabled
