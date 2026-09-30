"""Research page of the Broadsheet frontend (mockup `04-research.html`, docs/ui.md).

A question bar, the report laid out as a feature article with numbered web citations, and a
side column with the figures box and a timeline of how the run went. Quick starts at the
local wiki; Deep is web-only. Including classified levels switches the web off (G4), which
also rules Deep out, and locks that choice until the next New research.
"""

import os
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

from nicegui import ui

import agent as research_agent
import classification
import db_context
import deep_research_agent
import gui_chat
import gui_cite
import gui_session
import tools
import ui_logic
import wiki_engine

METHODS = {"Quick": "Quick, wiki first", "Deep": "Deep, web only"}
_NO_RESULT = (
    "The run ended without producing a result. The timeline shows how far it got: "
    "try rephrasing, or start a New research."
)
_NO_ANSWER = (
    "The agent finished but produced no answer text. Try rephrasing the question, "
    "or start a New research."
)


@dataclass
class Research:
    """One browser's research session; dropped with the session's content."""

    mode: str = "Quick"
    classified: bool = False
    as_source: bool = False
    level: int = 0
    history: list[dict[str, Any]] = field(default_factory=lambda: [])
    question: str = ""
    answer: str = ""
    interpreted: str | None = None
    report: str = ""
    sources: list[dict[str, str]] = field(default_factory=lambda: [])
    steps: list[dict[str, Any]] = field(default_factory=lambda: [])
    metrics: dict[str, Any] | None = None
    audit: dict[str, Any] | None = None
    error: str = ""
    notice: str = ""
    saved: str = ""
    running: bool = False
    seconds: int = 0


@dataclass(frozen=True)
class TraceItem:
    kind: str  # call, result, thought, notice, error, done
    title: str
    detail: str
    at: str


def research_state(session: gui_session.Session) -> Research:
    state = session.state.get("research")
    if not isinstance(state, Research):
        state = session.state["research"] = Research()
    return state


# --- pure logic ---------------------------------------------------------------------------


def record_urls(panel: list[dict[str, str]], step: dict[str, Any]) -> None:
    """Append web citations from a step, de-duplicated by URL."""
    known = {s["url"] for s in panel if s.get("url")}
    new: list[dict[str, str]] = step.get("sources") or []
    for src in new:
        if src["url"] not in known:
            known.add(src["url"])
            panel.append(src)


def apply_step(run: Research, step: dict[str, Any]) -> None:
    """Record one intermediate step: the trace, the sources panel and the error line."""
    run.steps.append({**step, "at": time.strftime("%H:%M:%S")})
    kind = step["type"]
    if kind == "tool_call":
        run.sources.append({"tool": step["name"], "query": str(step["args"])[:80]})
    elif kind == "tool_result":
        record_urls(run.sources, step)
    elif kind == "error":
        run.error = step["content"]


def metric_tiles(metrics: dict[str, Any] | None) -> list[tuple[str, int]]:
    """Figures for a finished Deep run; pages read is dropped when it repeats the searches."""
    if not metrics:
        return []
    tiles = [("Sub-tasks", metrics.get("tasks", 0)), ("Web searches", metrics.get("searches", 0))]
    checked = metrics.get("sources_checked", 0)
    if checked != metrics.get("searches", 0):
        tiles.append(("Pages read", checked))
    return [*tiles, ("Sources cited", metrics.get("sources_cited", 0))]


def _item(step: dict[str, Any]) -> TraceItem | None:
    kind, at = step["type"], step.get("at", "")
    if kind == "thought":
        return TraceItem("thought", step.get("label") or "Thought", step["content"], at)
    if kind == "notice":
        return TraceItem("notice", "Notice", step["content"], at)
    if kind == "ontology":
        return TraceItem("thought", "Ontology frame", step["content"], at)
    if kind == "error":
        return TraceItem("error", "Error", step["content"], at)
    if kind == "tool_call":
        args: dict[str, Any] = step.get("args") or {}
        if step.get("terminal"):
            return TraceItem("done", f"{step['name']} — research phase finished", "", at)
        detail = "\n".join(p for p in (str(args)[:300] if args else "", step.get("note", "")) if p)
        return TraceItem("call", step["name"], detail, at)
    if kind == "tool_result":
        srcs: list[dict[str, str]] = step.get("sources") or []
        title = f"Result: {step['name']}" + (f" — {len(srcs)} source(s)" if srcs else "")
        lines = [step.get("note", ""), *(f"{s['title'] or s['url']} ({s['url']})" for s in srcs)]
        return TraceItem(
            "result", title, "\n".join([*filter(None, lines), step["result"][:2000]]), at
        )
    return None


def trace_items(steps: list[dict[str, Any]]) -> list[TraceItem]:
    return [item for item in map(_item, steps) if item is not None]


def new_run(run: Research, question_to_run: str, display_q: str) -> str | None:
    """Clear the previous run's results; return the rephrased question, if it differs."""
    run.question, run.answer, run.error, run.notice, run.saved = display_q, "", "", "", ""
    run.sources, run.steps, run.metrics, run.audit, run.report = [], [], None, None, ""
    run.interpreted = question_to_run if question_to_run.strip() != display_q.strip() else None
    return run.interpreted


def finish(
    run: Research, step: dict[str, Any], display_q: str, interpreted: str | None, reread: str | None
) -> None:
    """Store the final answer. `reread` is the filed report read back (preferred); the agent's
    own text is the fallback, so a read-back problem never loses the answer."""
    record_urls(run.sources, step)
    run.metrics = step.get("metrics")
    run.answer = reread or step.get("content", "")
    path = step.get("report_path")
    run.report = path or ""
    if not run.answer.strip():
        run.error = _NO_ANSWER
    run.history.append(
        {
            "q": display_q,
            "a": run.answer,
            "interpreted": interpreted,
            "report": ui_logic.report_ref(path) if path else None,
        }
    )


def api_key() -> str:
    return os.getenv("TAVILY_API_KEY", "")


# --- running ------------------------------------------------------------------------------


async def _reread(session: gui_session.Session, run: Research, step: dict[str, Any]) -> str | None:
    if not step.get("report_path"):
        return None
    try:
        return await gui_session.in_worker(
            ui_logic.read_report, step["report_path"], session.active_db
        )
    except Exception as exc:
        run.notice = (
            f"Saved report could not be re-read ({type(exc).__name__}); "
            "showing the result as produced."
        )
        return None


async def run_research(
    session: gui_session.Session,
    run: Research,
    question_to_run: str,
    display_q: str,
    context: str,
    deep: bool,
    on_update: Callable[[], None],
) -> None:
    """Stream one research run into `run`, updating the view after every step."""
    started = time.monotonic()
    interpreted = new_run(run, question_to_run, display_q)
    run.level = max(run.level, classification.high_water(db_context.search_scope()))
    run.running = True
    on_update()
    runner = deep_research_agent.run_deep_research if deep else research_agent.run_research_agent
    stream = gui_session.stream_steps(
        runner, question_to_run, context, after=tools.current_run_audit
    )
    try:
        async for step in stream:
            if step["type"] == "final_answer":
                reread = await _reread(session, run, step)
                finish(run, step, display_q, interpreted, reread)
            else:
                apply_step(run, step)
            on_update()
    except Exception as exc:
        run.error = run.error or f"Research failed: {exc}"
    finally:
        run.running = False
    if not (run.answer.strip() or run.error.strip()):
        run.error = _NO_RESULT
    run.audit, run.seconds = stream.after_result, int(time.monotonic() - started)
    on_update()


# --- rendering ------------------------------------------------------------------------------


def _render_item(item: TraceItem) -> None:
    with ui.element("div").classes(f"row {'done' if item.kind == 'done' else ''}".strip()):
        ui.label(item.at).classes("time")
        ui.element("span").classes("pin")
        with ui.column().classes("what gap-0"):
            if item.detail and item.kind in ("result", "call", "thought"):
                with ui.expansion(item.title).classes("fold w-full"):
                    ui.label(item.detail).classes("muted text-caption").style(
                        "white-space: pre-wrap"
                    )
            else:
                ui.label(item.title).classes("text-negative" if item.kind == "error" else "")
                if item.detail:
                    ui.label(item.detail).classes("muted text-caption")


def _render_figures(metrics: dict[str, Any] | None) -> None:
    tiles = metric_tiles(metrics)
    if not tiles:
        return
    with ui.column().classes("figs w-full gap-0"):
        for label, value in tiles:
            with ui.row().classes("w-full justify-between"):
                ui.label(label)
                ui.label(str(value)).classes("num")


def _render_endnote(
    session: gui_session.Session, note: gui_cite.Note, sources: list[dict[str, str]]
) -> None:
    title = next((s.get("title") for s in sources if s.get("url") == note.file), "") or note.label
    with ui.element("div").classes("note").props(f"data-n={note.n}"):
        ui.label(str(note.n)).classes("n")
        with ui.column().classes("gap-0"):
            if note.kind == "web":
                ui.link(title, note.file, new_tab=True).classes("t")
                ui.label(urlparse(note.file).netloc).classes("muted text-caption")
            else:
                label = ui.label(note.label).classes("t file cursor-pointer")
                label.on("click", gui_session.guarded(session)(gui_chat.opener(session, note)))


class ResearchView:
    """The question bar, the report column, the side column and their handlers."""

    def __init__(self, session: gui_session.Session) -> None:
        self.session = session
        self.run = research_state(session)
        self._guard = gui_session.guarded(session)
        self.shards = db_context.reachable_shards(session.active_db)

    def build(self) -> None:
        self._bind()
        ui.label(
            "Quick starts at the local wiki, then searches the web to fill the gaps. Deep is "
            "web-only: it splits the question into sub-topics, researches each one and writes "
            "a report cited to web URLs. It is slower and ignores the wiki."
        ).classes("hint q-px-xl q-pt-md")
        if not api_key():
            ui.label(
                "TAVILY_API_KEY not set. Add it to your .env file to enable web research."
            ).classes("text-negative q-px-xl")
        with ui.row().classes("qbar items-end w-full no-wrap"):
            self._render_bar()
        with ui.element("div").classes("research-grid"):
            self.report = ui.column().classes("report")
            self.side = ui.column().classes("side")
        self._sync_controls()
        self.refresh()

    def _bind(self) -> None:
        scope = list(self.shards) if self.run.classified else [self.session.active_db]
        self.session.scope = scope
        db_context.set_search_scope(scope)

    def _locked(self) -> bool:
        return bool(self.run.level and self.run.history)

    def _sync_controls(self) -> None:
        self.method.set_enabled(not self.run.classified)
        self.start.set_enabled(bool(api_key()))
        if self.classified_box is not None:
            self.classified_box.set_enabled(not self._locked())

    # --- bar --------------------------------------------------------------------------------

    def _render_bar(self) -> None:
        with ui.column().classes("grow gap-0"):
            ui.label("Question").classes("label")
            self.question = ui.input(placeholder="e.g. What are the latest advances in RAG?")
            self.question.props("borderless").classes("field").mark("research-question")
            self.question.on("keydown.enter", self._guard(self._start))
        with ui.column().classes("gap-0"):
            ui.label("Method").classes("label")
            self.method = ui.toggle(
                METHODS, value=self.run.mode, on_change=self._guard(self._set_mode)
            ).classes("toggle")
            self.method.mark("research-method")
        self.classified_box = None
        if len(self.shards) > 1:
            self.classified_box = ui.checkbox(
                "Include classified levels (web search off)",
                value=self.run.classified,
                on_change=self._guard(self._set_classified),
            ).mark("classified-levels")
        self.start = ui.button("Start research", on_click=self._guard(self._start))
        self.start.props("flat").classes("btn primary").mark("start-research")
        ui.button("New research", on_click=self._guard(self._new)).props("flat").classes(
            "btn"
        ).mark("new-research")

    def _set_mode(self, event: Any) -> None:
        self.run.mode = event.value

    def _set_classified(self, event: Any) -> None:
        self.run.classified = bool(event.value)
        if self.run.classified:  # nothing leaves this machine while classified levels are in scope
            self.run.mode = "Quick"
            self.method.set_value("Quick")
        self._bind()
        self._sync_controls()
        self.refresh()

    def _new(self) -> None:
        keep = Research(
            mode=self.run.mode, classified=self.run.classified, as_source=self.run.as_source
        )
        self.session.state["research"] = self.run = keep
        self._sync_controls()
        self.refresh()

    # --- running ----------------------------------------------------------------------------

    def _deep(self) -> bool:
        return self.run.mode == "Deep" and not self.run.classified

    async def _start(self) -> None:
        question = (self.question.value or "").strip()
        if self.run.running:
            return
        if not question:
            self.run.error = "Enter a research question first."
            self.refresh()
            return
        self.question.set_value("")
        await run_research(
            self.session, self.run, question, question, "", self._deep(), self.refresh
        )
        self._sync_controls()

    async def _follow_up(self, field_: ui.input) -> None:
        text = (field_.value or "").strip()
        if not text or self.run.running:
            return
        standalone = await gui_session.in_worker(
            wiki_engine.condense_followup, self.run.question, self.run.answer, text
        )
        await run_research(self.session, self.run, standalone, text, "", self._deep(), self.refresh)
        self._sync_controls()

    async def _save(self) -> None:
        try:
            target = db_context.write_target(self.session.active_db, db_context.search_scope())
            self.run.saved = await gui_session.in_worker(
                ui_logic.save_research,
                self.run.answer,
                self.run.question[:60],
                self.run.as_source,
                target,
            )
        except db_context.AccessDenied:
            self.run.saved = "This research searched a level above your clearance."
        except Exception as exc:
            self.run.saved = f"Save to wiki failed: {exc}"
        self.refresh()

    # --- columns -----------------------------------------------------------------------------

    def refresh(self) -> None:
        for box, render in ((self.report, self._render_report), (self.side, self._render_side)):
            box.clear()
            with box:
                render()

    def _render_report(self) -> None:
        run = self.run
        if run.running:
            ui.label(run.question).classes("headline m")
            ui.label("Researching…").classes("muted")
        elif run.answer.strip():
            self._render_answer()
        elif run.error:
            ui.label(run.error).classes("text-negative")
        else:
            ui.label("Ask a question above to start.").classes("muted")
        self._render_history()

    def _render_answer(self) -> None:
        run = self.run
        text, notes = gui_cite.number_citations(run.answer)
        ui.label("Deep research report" if run.mode == "Deep" else "Research report").classes(
            "kicker"
        )
        ui.label(run.question).classes("headline")
        if run.interpreted:
            ui.label(f"Interpreted as: {run.interpreted}").classes("muted")
        with ui.row().classes("meta"):
            ui.label(f"{len(notes)} sources cited")
            ui.label(f"Finished in {run.seconds} s")
            ui.label(run.saved or "Not yet saved")
        if run.notice:
            ui.label(run.notice).classes("text-warning")
        ui.markdown(text).classes("prose")
        with ui.element("div").classes("endnotes"):
            for note in notes:
                _render_endnote(self.session, note, run.sources)
        gui_chat.render_why(run.audit)
        self._render_actions()

    def _render_actions(self) -> None:
        run = self.run
        with ui.row().classes("actions items-center w-full"):
            can_save = self.session.can_maintain and not run.saved
            if can_save:
                ui.button("Save to wiki", on_click=self._guard(self._save)).props("flat").classes(
                    "btn primary"
                ).mark("save-research")
                box = ui.checkbox("Also register as a source document", value=run.as_source).mark(
                    "as-source"
                )
                box.on_value_change(lambda e: setattr(run, "as_source", bool(e.value)))
            name = run.report.rsplit("/", 1)[-1] if run.report else "research-answer.md"
            ui.button(
                "Download report", on_click=lambda: ui.download.content(run.answer, name)
            ).props("flat").classes("btn text sm")

    def _render_history(self) -> None:
        earlier = self.run.history[:-1] if self.run.answer.strip() else self.run.history
        if not earlier:
            return
        with ui.expansion(f"Earlier research ({len(earlier)})").classes("fold w-full"):
            for h in earlier:
                ui.label(h["q"]).classes("t")
                ui.markdown(h["a"]).classes("prose compact")

    def _render_side(self) -> None:
        _render_figures(self.run.metrics)
        items = trace_items(self.run.steps)
        if items:
            ui.label("How the research ran").classes("section-label")
            with ui.column().classes("wire w-full gap-0"):
                for item in items:
                    _render_item(item)
        urls = [s for s in self.run.sources if s.get("url")]
        if urls:
            with ui.expansion(f"Pages consulted ({len(urls)})").classes("fold w-full"):
                for src in urls:
                    ui.link(src.get("title") or src["url"], src["url"], new_tab=True)
        if self.run.question and not self.run.running:
            self._render_follow_up()

    def _render_follow_up(self) -> None:
        with ui.expansion("Ask a follow-up").classes("fold w-full"):
            field_ = ui.input(placeholder="A follow-up about this research").classes("w-full")
            field_.mark("followup")
            ui.button("Ask follow-up", on_click=self._guard(lambda: self._follow_up(field_))).props(
                "flat"
            ).classes("btn sm").mark("followup-go")


def build(session: gui_session.Session) -> None:
    """Page body of `/research`."""
    ResearchView(session).build()
