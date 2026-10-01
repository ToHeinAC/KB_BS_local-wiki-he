"""Explorer page of the Broadsheet frontend (mockup `02-explorer.html`, docs/ui.md).

A bar (level, Map/Index, layout, find, size, overlays), the map with a standings table or the
index or search hits on the left, and the reader on the right. Everything reads one
classification level at a time: pages of different levels are never mixed on screen.
"""

import re
from dataclasses import dataclass, field
from typing import Any

from nicegui import ui

import db_context
import graph_widget
import gui_chat
import gui_graph
import gui_session
import lex_index
import retrieval
import ui_logic
import wiki_engine

VIEWS = ("Map", "Index")
SIZES = {"pagerank": "PageRank", "degree": "Connections"}
_LIST_CAP = 25


@dataclass
class Explorer:
    """One browser's Explorer state; dropped with the session's content."""

    view: str = "Map"
    layout: str = "Galaxy"
    size_by: str = "pagerank"
    overlays: list[str] = field(default_factory=lambda: ["Hubs"])
    selected: str | None = None
    query: str = ""
    level: str | None = None


def explorer_state(session: gui_session.Session) -> Explorer:
    state = session.state.get("explorer")
    if not isinstance(state, Explorer):
        state = session.state["explorer"] = Explorer()
    return state


def plain_excerpt(text: str) -> str:
    """A search excerpt as one line of plain text (a preview starting `## …` must not shout)."""
    plain = re.sub(r"[#*_`>]+", "", text)
    return re.sub(r"\s+", " ", plain).strip().lstrip("-* ")


def _search(query: str) -> tuple[list[dict[str, Any]], dict[str, Any] | None, bool]:
    """Hits, the ontology stage's frame and whether the index has any pages (blocking)."""
    results = wiki_engine.search_wiki(query)
    return results, retrieval.last_frame(), bool(lex_index.index_health()["wiki"])


def _overview() -> str:
    wiki_engine.ensure_description()
    return wiki_engine.read_description() or ""


class ExplorerView:
    """The bar, the two columns and the handlers that change them."""

    def __init__(self, session: gui_session.Session) -> None:
        self.session = session
        self.ex = explorer_state(session)
        self._guard = gui_session.guarded(session)
        self.map_args: dict[str, Any] | None = None
        self.rows: dict[str, ui.element] = {}
        self.left: ui.column | None = None
        self.right: ui.column | None = None

    def build(self) -> None:
        shards = db_context.reachable_shards(self.session.active_db)
        if self.ex.level in shards:
            self.session.shard, self.session.scope = self.ex.level, [self.ex.level]
            ui_logic.bind_level(self.ex.level)
        else:
            self.ex.level = None
        self.bar = ui.row().classes("bar items-center w-full no-wrap")
        with self.bar:
            self._render_bar(shards)
        self.body = ui.element("div").classes("explorer-grid")
        ui.on("graph_open", self._guard(self._on_graph))
        ui.timer(0.05, self._guard(self.load), once=True)

    # --- bar --------------------------------------------------------------------------------

    def _render_bar(self, shards: tuple[str, ...]) -> None:
        if len(shards) > 1:
            ui.toggle(
                {s: ui_logic.level_name(s) for s in shards},
                value=self.session.shard,
                on_change=self._guard(self._set_level),
            ).classes("toggle").mark("level")
        ui.toggle(list(VIEWS), value=self.ex.view, on_change=self._guard(self._set_view)).classes(
            "toggle"
        ).mark("view")
        self.layout_toggle = ui.toggle(
            list(ui_logic.GRAPH_LAYOUTS),
            value=self.ex.layout,
            on_change=self._guard(self._set_layout),
        ).classes("toggle")
        self.layout_toggle.set_visibility(self.ex.view == "Map")
        find = ui.input(placeholder="Find a page", value=self.ex.query).props(
            "borderless debounce=300"
        )
        find.classes("find").mark("find")
        find.on_value_change(self._guard(self._set_query))
        ui.space()
        ui.label("Size by").classes("muted text-caption")
        ui.select(SIZES, value=self.ex.size_by, on_change=self._guard(self._set_size)).props(
            "dense borderless options-dense"
        ).mark("size-by")
        for label in ui_logic.OVERLAY_LABELS:
            ui.checkbox(
                label, value=label in self.ex.overlays, on_change=self._guard(self._set_overlays)
            ).mark(f"overlay-{label}")

    async def _set_level(self, event: Any) -> None:
        if event.value not in db_context.reachable_shards(self.session.active_db):
            return
        self.session.bind_shard(event.value)
        self.ex.level, self.ex.selected, self.ex.query = event.value, None, ""
        await self.load()

    async def _set_view(self, event: Any) -> None:
        self.ex.view = event.value
        if event.value == "Index":
            self.ex.selected = None  # the index always lands on the database overview
        self.layout_toggle.set_visibility(event.value == "Map")
        await self.load()

    async def _set_layout(self, event: Any) -> None:
        self.ex.layout = event.value
        await self.refresh_left()

    async def _set_size(self, event: Any) -> None:
        self.ex.size_by = event.value
        await self.refresh_left()

    async def _set_overlays(self, event: Any) -> None:
        label = event.sender.text
        picked = [o for o in self.ex.overlays if o != label] + ([label] if event.value else [])
        self.ex.overlays = [o for o in ui_logic.OVERLAY_LABELS if o in picked]
        await self.refresh_left()

    async def _set_query(self, event: Any) -> None:
        self.ex.query = (event.value or "").strip()
        await self.refresh_left()

    # --- columns ------------------------------------------------------------------------------

    async def load(self) -> None:
        self.body.clear()
        self.left = self.right = None
        pages = await gui_session.in_worker(wiki_engine.list_pages)
        with self.body:
            if not pages:
                ui.label("No wiki pages yet. Upload a document to get started.").classes(
                    "q-pa-xl muted"
                )
                return
            self.left = ui.column().classes("left")
            self.right = ui.column().classes("reader")
        await self.refresh_left()
        await self.refresh_right()

    async def refresh_left(self) -> None:
        if self.left is None:
            return
        self.left.clear()
        self.rows = {}
        with self.left:
            if self.ex.query or self.ex.view == "Map":
                box = ui.column().classes("w-full")
            else:
                box = ui.column().classes("w-full")
        if self.ex.query:
            await self._render_search(box)
        elif self.ex.view == "Map":
            await self._render_map(box)
        else:
            await self._render_index(box)

    @property
    def _reader(self) -> ui.column:
        assert self.right is not None
        return self.right

    async def refresh_right(self) -> None:
        if self.right is None:
            return
        self.right.clear()
        if self.ex.selected:
            await self._render_reader()
        elif self.ex.view == "Map":
            await self._render_health()
        else:
            await self._render_overview()

    async def select(self, page: str) -> None:
        self.ex.selected = page
        for pid, row in self.rows.items():
            row.classes(add="sel") if pid == page else row.classes(remove="sel")
        if self.map_args is not None and self.ex.view == "Map" and not self.ex.query:
            self.map_args["selected"] = page
            gui_graph.push_args(self.map_args)
        await self.refresh_right()

    async def _on_graph(self, event: Any) -> None:
        action = gui_graph.graph_click(event.args)
        if action is None:
            return
        if action[0] == "open":
            await self.select(action[1])
        else:
            ui.notify(action[1])

    # --- left: map, index, search ---------------------------------------------------------------

    async def _render_map(self, box: ui.column) -> None:
        with box:
            cap = ui.label("").classes("hint")
            ui.element("iframe").props(
                f"id=wiki-graph src={gui_graph.ASSET_URL}/index.html"
            ).classes("graph-frame")
            table = ui.element("div").classes("standings")
        try:
            data = await gui_session.in_worker(
                gui_graph.map_data,
                overlays=self.ex.overlays,
                size_by=self.ex.size_by,
                layout=ui_logic.GRAPH_LAYOUTS[self.ex.layout],
                selected=self.ex.selected,
            )
        except Exception as exc:
            cap.set_text(f"Graph render failed: {exc}")
            return
        self.map_args = data["args"]
        cap.set_text(data["caption"])
        with table:
            for row in data["standings"]:
                self._render_standing(row)
        gui_graph.push_args(data["args"])

    def _render_standing(self, row: dict[str, Any]) -> None:
        async def open_it() -> None:
            await self.select(row["id"])

        line = ui.row().classes("standing items-center no-wrap")
        line.classes(add="sel") if row["id"] == self.ex.selected else None
        self.rows[row["id"]] = line
        with line:
            ui.label(str(row["rank"])).classes("rk")
            ui.label(row["label"]).classes("pg")
            ui.label(row["type"]).classes("ty muted")
            ui.element("span").classes("bar-pr").style(f"width: {int(80 * row['width'])}px")
            ui.label(row["value"]).classes("muted")
        line.on("click", self._guard(open_it))
        line.mark(f"row-{row['id']}")

    async def _render_index(self, box: ui.column) -> None:
        tree = await gui_session.in_worker(wiki_engine.get_wiki_tree)
        with box:
            for group, label in ui_logic.NAV_GROUPS.items():
                pages = tree.get(group)
                if not pages:
                    continue
                with ui.expansion(f"{label} ({len(pages)})", value=group == "concept").classes(
                    "fold w-full"
                ):
                    for page in pages:
                        self._render_nav_row(page)

    def _render_nav_row(self, page: dict[str, Any]) -> None:
        async def open_it() -> None:
            await self.select(page["filename"])

        title = ("⚠ " if page.get("stale") else "") + page.get("title", page["filename"])
        row = ui.label(title).classes("nav-row cursor-pointer")
        self.rows[page["filename"]] = row
        row.on("click", self._guard(open_it))
        row.mark(f"nav-{page['filename']}")

    async def _render_search(self, box: ui.column) -> None:
        results, frame, has_index = await gui_session.in_worker(_search, self.ex.query)
        with box:
            if not results and not has_index:
                ui.label(
                    "No search index for this database. Search comes back empty until it is "
                    "rebuilt: Maintenance → Search index → Rebuild."
                ).classes("text-negative")
                return
            ui.label(f"{len(results)} result(s)").classes("hint")
            if frame:
                ui.label(ui_logic.ontology_line(frame)).classes("hint")
            top = max((r.get("score", 0.0) for r in results), default=0.0)
            for hit in results:
                self._render_hit(hit, top)

    def _render_hit(self, hit: dict[str, Any], top: float) -> None:
        async def open_it() -> None:
            await self.select(hit["filename"])

        with ui.column().classes("hit w-full gap-1"):
            title = ui.label(hit["title"]).classes("headline s cursor-pointer")
            title.on("click", self._guard(open_it))
            title.mark(f"hit-{hit['filename']}")
            if top > 0:
                ui.linear_progress(
                    value=min(hit.get("score", 0.0) / top, 1.0), show_value=False
                ).props("size=4px color=grey-8")
            excerpt = plain_excerpt(hit.get("excerpt") or "")
            if excerpt:
                ui.label(excerpt).classes("prose compact")
            terms: list[str] = hit.get("matched_terms") or []
            if terms:
                ui.label("matched: " + " ".join(terms)).classes("muted text-caption")

    # --- right: reader, health, overview ---------------------------------------------------------

    async def _render_reader(self) -> None:
        page = self.ex.selected or ""
        try:
            parsed = await gui_session.in_worker(wiki_engine.read_page_parsed, page)
        except Exception as exc:
            with self._reader:
                ui.label(f"Could not load page: {exc}").classes("text-negative")
            return
        with self._reader:
            with ui.row().classes("top items-baseline w-full"):
                ui.label(page).classes("file")
                ui.space()
                ui.button("Close", on_click=self._guard(self._close)).props("flat").classes(
                    "btn text small"
                ).mark("close-reader")
            ui.markdown(parsed["content"]).classes("prose compact")
            ui.button(
                "Download Markdown", on_click=lambda: ui.download.content(parsed["content"], page)
            ).props("flat").classes("btn text small")
            self._render_sources(parsed["sources"])
            self._render_related(parsed["related"])

    async def _close(self) -> None:
        self.ex.selected = None
        if self.map_args is not None and self.ex.view == "Map" and not self.ex.query:
            self.map_args["selected"] = None
            gui_graph.push_args(self.map_args)
        for row in self.rows.values():
            row.classes(remove="sel")
        await self.refresh_right()

    def _render_sources(self, sources: list[str]) -> None:
        if not sources:
            return
        ui.label("Sources").classes("section-label")
        for ref in sources:
            title = ui.label(ref).classes("file cursor-pointer")
            title.on("click", self._guard(self._source_opener(ref)))
            title.mark(f"source-{ref}")

    def _source_opener(self, ref: str) -> Any:
        async def open_it() -> None:
            await gui_chat.open_source(self.session, ref, "source", ref)

        return open_it

    def _render_related(self, related: list[str]) -> None:
        if not related:
            return
        ui.label("Linked pages").classes("section-label")
        with ui.row().classes("linked"):
            for name in related:
                chip = ui.button(name, on_click=self._guard(self._page_opener(name)))
                chip.props("flat dense no-caps").classes("chip").mark(f"chip-{name}")

    def _page_opener(self, name: str) -> Any:
        async def open_it() -> None:
            await self.select(name)

        return open_it

    async def _render_health(self) -> None:
        health = await gui_session.in_worker(graph_widget.graph_health)
        with self._reader:
            ui.label("Bundle health").classes("section-label")
            ui.label("Double-click a node to read it here.").classes("hint")
            with ui.row().classes("meta"):
                for label, value in (
                    ("Pages", health["pages"]),
                    ("Orphans", len(health["orphans"])),
                    ("Stale", len(health["stale"])),
                ):
                    ui.label(f"{label} {value}")
            ui.label(f"Clusters, updated in the last {health['window_days']} days").classes(
                "label q-mt-md"
            )
            for cluster in health["clusters"][:6]:
                growth = f" · +{cluster['recent']}" if cluster["recent"] else ""
                ui.label(f"{cluster['label']} — {cluster['size']} pages{growth}")
            for label, ids in (
                ("Orphaned", health["orphans"]),
                ("Stale", health["stale"]),
                ("Outdated", health.get("outdated", [])),
                ("Low confidence", health["low_confidence"]),
            ):
                self._render_page_list(label, ids)

    def _render_page_list(self, label: str, ids: list[str]) -> None:
        if not ids:
            return
        with ui.expansion(f"{label} ({len(ids)})").classes("fold w-full"):
            for page in ids[:_LIST_CAP]:
                row = ui.label(page).classes("file cursor-pointer")
                row.on("click", self._guard(self._page_opener(page)))
            if len(ids) > _LIST_CAP:
                ui.label(f"…and {len(ids) - _LIST_CAP} more.").classes("muted")

    async def _render_overview(self) -> None:
        text = await gui_session.in_worker(_overview)
        with self._reader:
            if text:
                ui.markdown(text).classes("prose compact")
            else:
                ui.label("Select a page from the index.").classes("muted")


def build(session: gui_session.Session) -> None:
    """Page body of `/explorer`."""
    ExplorerView(session).build()
