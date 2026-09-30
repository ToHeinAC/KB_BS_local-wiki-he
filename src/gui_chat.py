"""Chat page of the Broadsheet frontend (mockup `03-chat.html`, docs/ui.md).

Three columns: a rail (mode, search scope, conversation), the reading column (question as a
headline, the answer with numbered citations, actions) and a margin column with the sources.
Fast answers come from the wiki, Deep answers from an agent that reads the originals; both
produce the same message dicts, so the view does not care which one ran.
"""

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from nicegui import ui

import auth
import chat_agent
import classification
import db_context
import gui_cite
import gui_session
import lex_index
import ontology_ui
import tools
import ui_logic
import wiki_engine

MODES = ("Fast", "Deep")


@dataclass
class Chat:
    """One browser's conversation. Lives in `Session.state`, so it is dropped with the
    session's content when a grant shrinks or the database changes."""

    messages: list[dict[str, Any]] = field(default_factory=lambda: [])
    mode: str = "Fast"
    scope: list[str] = field(default_factory=lambda: [])
    followup: dict[str, str] | None = None
    live: dict[str, Any] | None = None


def chat_state(session: gui_session.Session) -> Chat:
    chat = session.state.get("chat")
    if not isinstance(chat, Chat):
        chat = session.state["chat"] = Chat()
    return chat


def reachable(session: gui_session.Session) -> list[str]:
    """Every classification level of every database the user may search."""
    return [s for db in auth.user_dbs(session.user) for s in db_context.reachable_shards(db)]


def effective_scope(session: gui_session.Session, chat: Chat) -> list[str]:
    """The chosen scope narrowed to what is still reachable; the active DB's levels if empty."""
    allowed = reachable(session)
    default = list(db_context.reachable_shards(session.active_db))
    return [s for s in chat.scope if s in allowed] or default


def _bind_scope(session: gui_session.Session, chat: Chat) -> None:
    chat.scope = effective_scope(session, chat)
    session.scope = list(chat.scope)
    db_context.set_search_scope(session.scope)


def save_target(session: gui_session.Session) -> str | None:
    """Where a saved answer goes: the highest level searched. None above the clearance."""
    try:
        return db_context.write_target(session.active_db, db_context.search_scope())
    except db_context.AccessDenied:
        return None


# --- turns -------------------------------------------------------------------------------


def new_deep() -> dict[str, Any]:
    return {"answer": "", "raw_sources": [], "wiki_pages": []}


def apply_deep_step(acc: dict[str, Any], step: dict[str, Any]) -> None:
    """Fold one agent step into the answer being assembled."""
    kind = step["type"]
    if kind == "final_answer":
        acc["answer"] = step["content"]
        acc["raw_sources"] = step.get("sources", []) or []
        acc["wiki_pages"] = step.get("wiki_sources", []) or []
    elif kind == "error" and not acc["answer"]:
        acc["answer"] = f"Error: {step['content']}"


def step_line(step: dict[str, Any]) -> str | None:
    """One line of the trace for an agent step; None for steps that are not shown."""
    kind = step["type"]
    if kind in ("thought", "ontology"):
        return str(step["content"])
    if kind == "tool_call":
        return f"{step['name']} — {step['args']}"
    if kind == "tool_result":
        return str(step["result"])[:600]
    if kind == "error":
        return f"Error: {step['content']}"
    return None


async def _deep_message(chat: Chat, question: str, on_update: Callable[[], None]) -> dict[str, Any]:
    acc = new_deep()
    steps: list[dict[str, Any]] = []
    stream = gui_session.stream_steps(
        chat_agent.run_chat_agent, question, after=tools.current_run_audit
    )
    try:
        async for step in stream:
            steps.append(step)
            if chat.live is not None:
                chat.live["steps"] = list(steps)
            apply_deep_step(acc, step)
            on_update()
    except Exception as e:
        acc["answer"] = acc["answer"] or f"Error: {e}"
    return {
        "content": acc["answer"] or "(no answer)",
        "sources": acc["wiki_pages"],
        "raw_sources": acc["raw_sources"],
        "steps": steps,
        "audit": stream.after_result,
    }


async def run_turn(chat: Chat, prompt: str, on_update: Callable[[], None]) -> None:
    """Answer `prompt` in the current mode and append the exchange to the conversation."""
    started = time.monotonic()
    followup, chat.followup = chat.followup, None
    question = prompt
    if followup:
        question = await gui_session.in_worker(
            wiki_engine.condense_followup, followup["q"], followup["a"], prompt
        )
    interpreted = question if (followup and question.strip() != prompt.strip()) else None
    chat.messages.append({"role": "user", "content": prompt})
    chat.live = {"question": prompt, "interpreted": interpreted, "steps": []}
    on_update()
    try:
        if chat.mode == "Deep":
            message = await _deep_message(chat, question, on_update)
        else:
            message = await gui_session.in_worker(ui_logic.answer_fast, question)
    finally:
        chat.live = None
    message.update(
        role="assistant",
        question=prompt,
        interpreted=interpreted,
        mode=chat.mode,
        seconds=int(time.monotonic() - started),
    )
    chat.messages.append(message)
    on_update()


# --- rendering ---------------------------------------------------------------------------


def _read_source(ref: str, kind: str) -> str | None:
    """Text of a cited original or wiki page (blocking: run in a worker).

    None when there is nothing to show. A denied name looks exactly like a missing one.
    """
    try:
        if kind == "wiki":
            db, name = db_context.split_ref(ref)
            with db_context.using_db(db):
                return wiki_engine.read_page_parsed(name)["content"] or None
        previewable, data = ui_logic.resolve_raw_source(ref)
    except (db_context.AccessDenied, OSError):
        return None
    return data.decode("utf-8", errors="replace") if previewable and data is not None else None


async def _open_source(session: gui_session.Session, note: gui_cite.Note) -> None:
    session.seal()
    text = await gui_session.in_worker(_read_source, note.ref, note.kind)
    with ui.dialog() as dialog, ui.card().classes("w-full").style("max-width: 760px"):
        ui.label(note.label).classes("file")
        if text is None:
            ui.label("This document cannot be previewed.").classes("muted")
        else:
            ui.markdown(text).classes("prose compact")
            ui.button("Download", on_click=lambda: ui.download.content(text, note.file)).props(
                "flat"
            ).classes("btn sm")
        ui.button("Close", on_click=dialog.close).props("flat").classes("btn text sm")
    dialog.open()


def render_why(audit: dict[str, Any] | None) -> None:
    """Search-ladder audit: which sources were kept and which dropped (silent without one)."""
    if not audit:
        return
    kept: list[tuple[str, float | None]] = audit.get("kept") or []
    below: list[tuple[str, float | None]] = audit.get("below_tau") or []
    over: list[tuple[str, float | None]] = audit.get("over_cap") or []
    frames: list[dict[str, Any]] = audit.get("ontology") or []
    if not (kept or below or over or frames):
        return

    def score(s: float | None) -> str:
        return "n/a" if s is None else f"{s:.2f}"

    with ui.expansion(f"Why these sources ({len(kept)} kept)").classes("fold w-full"):
        for name, s in kept:
            ui.label(f"✓ {name} — {score(s)}").classes("file")
        for name, s in below:
            ui.label(f"✗ {name} — {score(s)} (below τ)").classes("file muted")
        for name, s in over:
            ui.label(f"✗ {name} — {score(s)} (over cap)").classes("file muted")
        for frame in frames:
            ui.label(ui_logic.ontology_line(frame)).classes("muted")


def _render_trace(steps: list[dict[str, Any]]) -> None:
    lines = [line for line in map(step_line, steps) if line]
    with (
        ui.expansion("How this answer was made")
        .classes("fold w-full")
        .props(f'caption="{len(lines)} steps"')
    ):
        for line in lines:
            ui.label(line).classes("muted text-caption")


def _opener(session: gui_session.Session, note: gui_cite.Note) -> Callable[[], Any]:
    async def open_it() -> None:
        await _open_source(session, note)

    return open_it


def _render_note(session: gui_session.Session, note: gui_cite.Note) -> None:
    with ui.element("div").classes("note").props(f"data-n={note.n}"):
        ui.label(str(note.n)).classes("n")
        with ui.column().classes("gap-0"):
            if note.kind == "web":
                ui.link(note.label, note.file, new_tab=True).classes("t")
            else:
                title = ui.label(note.label).classes("t file cursor-pointer").mark(f"note-{note.n}")
                title.on("click", gui_session.guarded(session)(_opener(session, note)))
            hint = "Wiki page" if note.kind == "wiki" else ontology_ui.source_badge(note.ref)
            if hint:
                ui.label(hint).classes("w")


class ChatView:
    """The three columns and the handlers that change them."""

    def __init__(self, session: gui_session.Session) -> None:
        self.session = session
        self.chat = chat_state(session)
        self._guard = gui_session.guarded(session)

    def build(self) -> None:
        _bind_scope(self.session, self.chat)
        if not lex_index.index_health()["wiki"]:
            ui.label(
                "No search index for this database. Answers will come back empty until it is "
                "rebuilt: Maintenance → Search index → Rebuild."
            ).classes("text-negative q-pa-md")
        with ui.element("div").classes("chat-grid"):
            self.rail = ui.column().classes("rail")
            with ui.column().classes("chat-col"):
                self.convo = ui.column().classes("w-full gap-2")
                self._ask_row()
            self.notes = ui.column().classes("notes-col")
        self.refresh()

    def refresh(self) -> None:
        for box, render in (
            (self.rail, self._render_rail),
            (self.convo, self._render_convo),
            (self.notes, self._render_notes),
        ):
            box.clear()
            with box:
                render()

    # --- rail ---------------------------------------------------------------------------

    def _render_rail(self) -> None:
        ui.label("How to answer").classes("label")
        toggle = ui.toggle(list(MODES), value=self.chat.mode, on_change=self._guard(self._set_mode))
        toggle.classes("toggle").mark("mode")
        ui.label(
            "Deep reads the original documents and cites them by section. It takes about a minute."
        ).classes("hint")
        ui.label("Search in").classes("label q-mt-md")
        for shard in reachable(self.session):
            box = ui.checkbox(
                classification.label(shard),
                value=shard in self.chat.scope,
                on_change=self._scope_handler(shard),
            )
            box.mark(f"scope-{shard}")
        target = save_target(self.session)
        if target:
            ui.label(
                f"Answers you save go to {classification.label(target)}, the top level searched."
            ).classes("hint")
        ui.label("This conversation").classes("label q-mt-md")
        for m in (m for m in self.chat.messages if m["role"] == "user"):
            ui.label(m["content"]).classes("hist")
        ui.button("New conversation", on_click=self._guard(self._new)).props("flat").classes(
            "btn sm q-mt-md"
        ).mark("new-chat")

    def _scope_handler(self, shard: str) -> Callable[[Any], Any]:
        def on_change(event: Any) -> None:
            self._toggle_scope(event, shard)

        return self._guard(on_change)

    def _set_mode(self, event: Any) -> None:
        self.chat.mode = event.value

    def _toggle_scope(self, event: Any, shard: str) -> None:
        picked = [s for s in self.chat.scope if s != shard] + ([shard] if event.value else [])
        if not picked:  # a chat must search somewhere
            event.sender.set_value(True)
            return
        self.chat.scope = picked
        _bind_scope(self.session, self.chat)
        self._refresh_convo()

    def _new(self) -> None:
        self.chat.messages, self.chat.followup = [], None
        self.refresh()

    # --- reading column -------------------------------------------------------------------

    def _refresh_convo(self) -> None:
        self.convo.clear()
        with self.convo:
            self._render_convo()

    def _render_convo(self) -> None:
        if len(self.chat.scope) > 1:
            labels = ", ".join(map(classification.label, self.chat.scope))
            ui.label(f"Searching in {len(self.chat.scope)} places: {labels}").classes("hint")
        pairs = self.chat.messages
        earlier = pairs[:-2] if not self.chat.live else pairs[:-1]
        for m in (m for m in earlier if m["role"] == "user"):
            ui.label(f"Earlier: {m['content']}").classes("earlier")
        if self.chat.live is not None:
            self._render_live(self.chat.live)
        elif pairs and pairs[-1]["role"] == "assistant":
            self._render_answer(pairs[-1])

    def _render_live(self, live: dict[str, Any]) -> None:
        ui.label(live["question"]).classes("headline m")
        if live["interpreted"]:
            ui.label(f"Interpreted as: {live['interpreted']}").classes("muted")
        ui.label("Working…").classes("muted")
        lines = [line for line in map(step_line, live["steps"]) if line]
        for line in lines[-6:]:
            ui.label(line).classes("muted text-caption")

    def _render_answer(self, msg: dict[str, Any]) -> None:
        text, notes = gui_cite.number_citations(msg["content"])
        ui.label(msg["question"]).classes("headline m")
        if msg.get("interpreted"):
            ui.label(f"Interpreted as: {msg['interpreted']}").classes("muted")
        with ui.row().classes("meta"):
            ui.label(f"{msg['mode']} answer")
            ui.label(f"{len(notes)} cited")
            ui.label(f"{msg['seconds']} seconds")
        ui.markdown(text).classes("prose")
        if not msg["content"].startswith("Error:"):
            self._render_actions(msg)
        if msg.get("steps"):
            _render_trace(msg["steps"])

    def _render_actions(self, msg: dict[str, Any]) -> None:
        with ui.row().classes("actions items-center"):
            target = save_target(self.session)
            if self.session.can_maintain and target and not msg.get("saved"):
                ui.button("Save to wiki", on_click=self._guard(lambda: self._save(msg))).props(
                    "flat"
                ).classes("btn sm").mark("save-answer")
            ui.button(
                "Download", on_click=lambda: ui.download.content(msg["content"], "answer.md")
            ).props("flat").classes("btn text sm")
            ui.button(
                "Copy with citations", on_click=lambda: ui.clipboard.write(msg["content"])
            ).props("flat").classes("btn text sm")
            ui.button("Follow up", on_click=self._guard(lambda: self._follow(msg))).props(
                "flat"
            ).classes("btn text sm").mark("follow-up")
        if msg.get("saved"):
            ui.label(msg["saved"]).classes("muted")
        elif self.session.can_maintain and save_target(self.session) is None:
            ui.label(
                "This answer searched a level above your clearance; narrow 'Search in' to save it."
            ).classes("hint")

    async def _save(self, msg: dict[str, Any]) -> None:
        target = save_target(self.session)
        if target is None:
            return
        try:
            rel = await gui_session.in_worker(
                ui_logic.save_answer,
                msg["question"],
                msg["content"],
                msg.get("sources", []),
                msg.get("raw_sources", []),
                target,
            )
            msg["saved"] = f"Filed as {rel} in {classification.label(target)}"
        except RuntimeError as e:
            msg["saved"] = str(e)
        self.refresh()

    def _follow(self, msg: dict[str, Any]) -> None:
        self.chat.followup = {"q": msg["question"], "a": msg["content"]}
        self._render_followup()

    # --- ask row ----------------------------------------------------------------------------

    def _ask_row(self) -> None:
        self.follow_box = ui.row().classes("items-center w-full")
        with ui.row().classes("ask items-end no-wrap w-full"):
            self.field = ui.input(placeholder="Ask something…").props("borderless").classes("field")
            self.field.mark("chat-input")
            self.field.on("keydown.enter", self._guard(self._ask))
            ui.button("Ask", on_click=self._guard(self._ask)).props("flat").classes(
                "btn primary"
            ).mark("ask")
        self._render_followup()

    def _render_followup(self) -> None:
        self.follow_box.clear()
        if not self.chat.followup:
            return
        with self.follow_box:
            ui.label(f"Follow-up to: {self.chat.followup['q']}").classes("muted")
            ui.button("Cancel", on_click=self._guard(self._cancel_followup)).props("flat").classes(
                "btn text sm"
            ).mark("cancel-follow-up")

    def _cancel_followup(self) -> None:
        self.chat.followup = None
        self._render_followup()

    async def _ask(self) -> None:
        prompt = (self.field.value or "").strip()
        if not prompt or self.chat.live is not None:
            return
        self.field.set_value("")
        self.follow_box.clear()
        await run_turn(self.chat, prompt, self.refresh)

    # --- margin ------------------------------------------------------------------------------

    def _render_notes(self) -> None:
        last = next((m for m in reversed(self.chat.messages) if m["role"] == "assistant"), None)
        ui.label("Sources").classes("section-label")
        if last is None:
            ui.label("Sources appear here after each answer.").classes("muted")
            return
        _, notes = gui_cite.number_citations(last["content"])
        for note in notes:
            _render_note(self.session, note)
        used = [*last.get("sources", []), *last.get("raw_sources", [])]
        rest = gui_cite.uncited(notes, used)
        if rest:
            with ui.expansion(f"Also read ({len(rest)})").classes("fold w-full"):
                for ref in rest:
                    ui.label(ref).classes("file")
        render_why(last.get("audit"))


def build(session: gui_session.Session) -> None:
    """Page body of `/chat`."""
    ChatView(session).build()
