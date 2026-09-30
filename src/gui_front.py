"""Front page of the Broadsheet frontend (mockup `01-front-page.html`, docs/ui.md).

The one place with the full nameplate. Three columns: recent activity from the wiki's
`log.md`, the most connected page as the lead with the recently updated pages below it, and
"Ask the archive" with the archive's figures. Everything is read for the session's
database at its normal level; the numbers come from the same graph payload the Explorer draws.
"""

import re
from datetime import date
from typing import Any

from nicegui import ui

import graph_widget
import gui_chat
import gui_explorer
import gui_session
import wiki_engine

_ENTRY_RE = re.compile(r"^- (\d{2}:\d{2}) — ([^:]+?)(?::\s*(.*))?$")
_DAY_RE = re.compile(r"^## (\d{4}-\d{2}-\d{2})\s*$")
_LOG_LIMIT = 6
_RECENT_LIMIT = 3


def log_entries(text: str, limit: int) -> list[tuple[str, str, str, str]]:
    """(day, time, action, detail) of the newest `limit` entries in an OKF `log.md`."""
    entries: list[tuple[str, str, str, str]] = []
    day = ""
    for line in text.splitlines():
        if found := _DAY_RE.match(line):
            day = found.group(1)
        elif (found := _ENTRY_RE.match(line.strip())) and day:
            time, action, detail = found.groups()
            entries.append((day, time, action.strip(), " ".join((detail or "").split())))
            if len(entries) >= limit:
                break
    return entries


def _pages(payload: dict[str, Any]) -> list[dict[str, Any]]:
    return [n for n in payload["nodes"] if n.get("kind") == "page"]


def lead_page(payload: dict[str, Any]) -> dict[str, Any] | None:
    """The most connected page: the highest PageRank, ties broken by label."""
    pages = _pages(payload)
    return min(pages, key=lambda n: (-n["pr"], n["label"])) if pages else None


def recent_pages(payload: dict[str, Any], skip: str | None, limit: int) -> list[dict[str, Any]]:
    """The most recently updated pages other than the lead."""
    dated = [n for n in _pages(payload) if n.get("updated") and n["id"] != skip]
    dated.sort(key=lambda n: (n["updated"], n["label"]), reverse=True)
    return [
        {"id": n["id"], "label": n["label"], "kind": str(n["cat"]).replace("-", " ").capitalize()}
        for n in dated[:limit]
    ]


def figures(health: dict[str, Any]) -> list[tuple[str, int, bool]]:
    """(label, value, needs attention) for the figures box."""
    counts = [
        ("Pages", health["pages"], False),
        ("Source documents", health["sources"], False),
        ("Pages with no links", len(health["orphans"]), True),
        ("Stale pages", len(health["stale"]), True),
        ("Built on outdated versions", len(health.get("outdated", [])), True),
        ("Low confidence", len(health["low_confidence"]), True),
    ]
    return [(label, value, flag and value > 0) for label, value, flag in counts]


def growing(health: dict[str, Any]) -> list[tuple[str, int]]:
    """Clusters that gained pages within the health window, fastest first."""
    return [(c["label"], c["recent"]) for c in health["clusters"] if c["recent"]][:_RECENT_LIMIT]


def front_data() -> dict[str, Any]:
    """Everything the page shows, read at once (blocking: run in a worker)."""
    pages = wiki_engine.list_pages()
    if not pages:
        return {"empty": True}
    payload = graph_widget.graph_stats()
    lead = lead_page(payload)
    meta = {p["filename"]: p for p in pages}
    return {
        "empty": False,
        "log": log_entries(wiki_engine.read_log(), _LOG_LIMIT),
        "lead": lead,
        "lead_meta": meta.get(lead["id"], {}) if lead else {},
        "recent": recent_pages(payload, lead["id"] if lead else None, _RECENT_LIMIT),
        "health": graph_widget.graph_health(),
    }


class FrontView:
    def __init__(self, session: gui_session.Session) -> None:
        self.session = session
        self._guard = gui_session.guarded(session)

    def build(self) -> None:
        with ui.column().classes("front w-full"):
            ui.label(date.today().strftime("%A, %d %B %Y")).classes("muted text-caption")
            with ui.column().classes("plate-wrap w-full items-center"):
                ui.label("LocalWiki").classes("nameplate")
                ui.label("Your documents, compiled into a linked archive on this machine").classes(
                    "tagline"
                )
            self.body = ui.element("div").classes("front-grid")
        ui.timer(0.05, self._guard(self.load), once=True)

    async def load(self) -> None:
        data = await gui_session.in_worker(front_data)
        self.body.clear()
        with self.body:
            if data["empty"]:
                ui.label(
                    "No wiki pages yet. Upload a document to get started."
                    if self.session.can_maintain
                    else "No wiki pages yet. A maintainer of this database can add documents."
                ).classes("muted")
                self._render_ask()
                return
            self._render_log(data["log"])
            self._render_lead(data)
            with ui.column().classes("ask gap-1"):
                self._render_ask()
                self._render_figures(data["health"])

    def _render_log(self, entries: list[tuple[str, str, str, str]]) -> None:
        with ui.column().classes("log gap-0"):
            ui.label("Recent activity").classes("section-label")
            if not entries:
                ui.label("Nothing has happened yet.").classes("muted")
            for day, time, action, detail in entries:
                with ui.column().classes("entry gap-0"):
                    ui.label(f"{day}, {time}").classes("when")
                    ui.label(f"{action.capitalize()}: {detail}" if detail else action.capitalize())
            ui.link("Full activity log", "/maintenance").classes("btn text sm q-mt-sm")

    def _render_lead(self, data: dict[str, Any]) -> None:
        lead, meta = data["lead"], data["lead_meta"]
        with ui.column().classes("lead gap-2"):
            if lead is not None:
                ui.label("The most connected page in this edition").classes("kicker")
                ui.label(lead["label"]).classes("headline xl")
                if meta.get("description"):
                    ui.label(meta["description"]).classes("standfirst")
                with ui.row().classes("meta"):
                    ui.label(f"Linked to {lead['deg']} pages")
                    if lead.get("updated"):
                        ui.label(f"Updated {lead['updated']}")
                ui.button("Open the page", on_click=self._guard(self._opener(lead["id"]))).props(
                    "flat"
                ).classes("btn").mark("open-lead")
            if data["recent"]:
                ui.label("Recently updated").classes("section-label q-mt-md")
                with ui.element("div").classes("more"):
                    for page in data["recent"]:
                        self._render_recent(page)

    def _render_recent(self, page: dict[str, Any]) -> None:
        with ui.column().classes("gap-0 cursor-pointer") as card:
            ui.label(page["kind"]).classes("k")
            ui.label(page["label"]).classes("headline s")
        card.on("click", self._guard(self._opener(page["id"])))
        card.mark(f"recent-{page['id']}")

    def _opener(self, page: str) -> Any:
        def open_it() -> None:
            explorer = gui_explorer.explorer_state(self.session)
            explorer.selected, explorer.view, explorer.query = page, "Map", ""
            ui.navigate.to("/explorer")

        return open_it

    def _render_ask(self) -> None:
        ui.label("Ask the archive").classes("section-label")
        self.question = ui.input(placeholder="What would you like to know?").props("borderless")
        self.question.classes("field w-full").mark("front-question")
        self.question.on("keydown.enter", self._guard(self._ask))
        with ui.row().classes("items-center justify-between w-full"):
            self.mode = ui.toggle(list(gui_chat.MODES), value="Fast").classes("toggle")
            self.mode.mark("front-mode")
            ui.button("Ask", on_click=self._guard(self._ask)).props("flat").classes(
                "btn primary"
            ).mark("front-ask")

    def _ask(self) -> None:
        question = (self.question.value or "").strip()
        if not question:
            return
        chat = gui_chat.chat_state(self.session)
        chat.mode, chat.pending = str(self.mode.value), question
        ui.navigate.to("/chat")

    def _render_figures(self, health: dict[str, Any]) -> None:
        ui.label("The archive in figures").classes("section-label q-mt-md")
        for label, value, warn in figures(health):
            with ui.row().classes("figure w-full justify-between"):
                ui.label(label)
                ui.label(str(value)).classes("num warn" if warn else "num")
        rising = growing(health)
        if rising:
            ui.label(f"Growing in the last {health['window_days']} days").classes(
                "section-label q-mt-md"
            )
            for label, count in rising:
                with ui.row().classes("figure w-full justify-between"):
                    ui.label(f"Around {label}")
                    ui.label(f"+{count}").classes("num")


def build(session: gui_session.Session) -> None:
    """Page body of `/`."""
    FrontView(session).build()
