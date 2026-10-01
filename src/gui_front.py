"""2BrAIn, the front page of the Broadsheet frontend (mockup `01-front-page.html`, docs/ui.md).

The start of the user flow: a dateline with the tagline, then three columns: recent
activity from the wiki's `log.md` with the archive's figures, the galaxy map of the wiki (a
double-click opens the page in the Explorer), and the upload for maintainers. Everything is read
for the session's database at its normal level.
"""

import re
from datetime import date
from typing import Any

from nicegui import ui

import graph_widget
import gui_explorer
import gui_graph
import gui_session
import gui_upload
import ui_logic
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
    if not wiki_engine.list_pages():
        return {"empty": True}
    return {
        "empty": False,
        "log": log_entries(wiki_engine.read_log(), _LOG_LIMIT),
        "map": gui_graph.map_data(
            overlays=["Hubs"],
            size_by="pagerank",
            layout=ui_logic.GRAPH_LAYOUTS["Galaxy"],
            selected=None,
        ),
        "health": graph_widget.graph_health(),
    }


class FrontView:
    def __init__(self, session: gui_session.Session) -> None:
        self.session = session
        self._guard = gui_session.guarded(session)

    def build(self) -> None:
        with ui.column().classes("front w-full"):
            with ui.row().classes("dateline w-full items-baseline justify-between no-wrap"):
                ui.label(date.today().strftime("%A, %d %B %Y")).classes("muted text-caption")
                ui.label(
                    "Your documents, compiled into a linked archive on your infrastructure"
                ).classes("tagline")
            self.grid = ui.element("div").classes("front-grid").mark("front-grid")
            with self.grid:
                self.side = ui.column().classes("log gap-0")
                self.galaxy = ui.column().classes("galaxy gap-1")
                with ui.column().classes("intake gap-1"):
                    self._render_intake()
        ui.on("graph_open", self._guard(self._on_graph))
        ui.timer(0.05, self._guard(self.load), once=True)

    def _render_intake(self) -> None:
        ui.label("Add documents").classes("section-label")
        if self.session.can_maintain:
            gui_upload.UploadView(self.session, on_review=self._review).build()
        else:
            ui.label("A maintainer of this database can add documents.").classes("muted")

    def _review(self, reviewing: bool) -> None:
        """While a batch is prepared or reviewed the upload takes the galaxy's place; when it
        ends, the columns reload so new pages show up."""
        if reviewing:
            self.grid.classes(add="reviewing")
            return
        self.grid.classes(remove="reviewing")
        with self.grid:
            ui.timer(0.05, self._guard(self.load), once=True)

    async def load(self) -> None:
        data = await gui_session.in_worker(front_data)
        self.side.clear()
        self.galaxy.clear()
        if data["empty"]:
            with self.galaxy:
                ui.label(
                    "No wiki pages yet. Upload a document to get started."
                    if self.session.can_maintain
                    else "No wiki pages yet."
                ).classes("muted")
            return
        with self.side:
            self._render_log(data["log"])
            self._render_figures(data["health"])
        self._render_galaxy(data["map"])

    def _render_log(self, entries: list[tuple[str, str, str, str]]) -> None:
        ui.label("Recent activity").classes("section-label")
        if not entries:
            ui.label("Nothing has happened yet.").classes("muted")
        for day, time, action, detail in entries:
            with ui.column().classes("entry gap-0"):
                ui.label(f"{day}, {time}").classes("when")
                ui.label(f"{action.capitalize()}: {detail}" if detail else action.capitalize())
        ui.link("Full activity log", "/maintenance").classes("btn text small q-mt-sm")

    def _render_galaxy(self, data: dict[str, Any]) -> None:
        with self.galaxy:
            with ui.row().classes("w-full items-baseline no-wrap"):
                ui.label("The archive as a galaxy").classes("kicker")
                ui.space()
                ui.label(data["caption"]).classes("hint")
            ui.element("iframe").props(
                f"id=wiki-graph src={gui_graph.ASSET_URL}/index.html"
            ).classes("graph-frame").mark("front-map")
            ui.label("Double-click a page to read it in the Explorer.").classes("hint")
        gui_graph.push_args(data["args"])

    def _on_graph(self, event: Any) -> None:
        action = gui_graph.graph_click(event.args)
        if action is None:
            return
        if action[0] == "notice":
            ui.notify(action[1])
            return
        explorer = gui_explorer.explorer_state(self.session)
        explorer.selected, explorer.view, explorer.query = action[1], "Map", ""
        ui.navigate.to("/explorer")

    def _render_figures(self, health: dict[str, Any]) -> None:
        ui.label("The archive in figures").classes("section-label q-mt-lg")
        for label, value, warn in figures(health):
            with ui.row().classes("figure w-full justify-between no-wrap"):
                ui.label(label)
                ui.label(str(value)).classes("num warn" if warn else "num")
        rising = growing(health)
        if rising:
            ui.label(f"Growing in the last {health['window_days']} days").classes(
                "section-label q-mt-md"
            )
            for label, count in rising:
                with ui.row().classes("figure w-full justify-between no-wrap"):
                    ui.label(f"Around {label}")
                    ui.label(f"+{count}").classes("num")


def build(session: gui_session.Session) -> None:
    """Page body of `/`."""
    FrontView(session).build()
