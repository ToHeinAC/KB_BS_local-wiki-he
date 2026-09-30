"""Maintenance page of the Broadsheet frontend (docs/ui.md): the upkeep of one database.

Sections work on one classification level at a time (a level picker appears when more than one
is reachable): the search index, deleting and moving sources, link health, lint, page
language, the ontology workbench and the activity log. Destructive actions are for
maintainers and re-checked in the handler, not just hidden. Admin lives on its own page.
"""

from dataclasses import dataclass, field
from typing import Any

from nicegui import ui

import classification
import db_context
import dedup
import gui_session
import lex_index
import wiki_engine

SECTIONS = (
    "Search index",
    "Delete source",
    "Link graph health",
    "Lint",
    "Page language",
    "Ontology",
    "Activity log",
)


def megabytes(size: int) -> str:
    return f"{size / 1_048_576:.1f}"


def normalize_rows(report: dict[str, Any]) -> list[dict[str, Any]]:
    """The Page language scan as table rows."""
    return [
        {
            "Page": page,
            "Stamp language": info.get("lang", ""),
            "Foreign lines": info.get("foreign_lines", 0),
            "Fix references": "yes" if info.get("references") else "",
        }
        for page, info in report.items()
    ]


def needs_translation(report: dict[str, Any]) -> int:
    return sum(1 for info in report.values() if info.get("foreign_lines"))


@dataclass
class Maint:
    """One browser's Maintenance state; dropped with the session's content."""

    section: str = SECTIONS[0]
    level: str | None = None
    report: dict[str, Any] | None = None
    flash: str = ""
    extra: list[str] = field(default_factory=lambda: [])


def maint_state(session: gui_session.Session) -> Maint:
    state = session.state.get("maint")
    if not isinstance(state, Maint):
        state = session.state["maint"] = Maint()
    return state


class MaintView:
    """The level picker, the statistics, the section toggle and the section body."""

    def __init__(self, session: gui_session.Session) -> None:
        self.session = session
        self.state = maint_state(session)
        self._guard = gui_session.guarded(session)

    def build(self) -> None:
        shards = db_context.reachable_shards(self.session.active_db)
        if self.state.level in shards:
            self.session.bind_shard(self.state.level or "")
        else:
            self.state.level = None
        with ui.column().classes("maint-col"):
            if len(shards) > 1:
                ui.toggle(
                    {
                        s: classification.level_label(classification.parse_shard(s)[1])
                        for s in shards
                    },
                    value=self.session.shard,
                    on_change=self._guard(self._set_level),
                ).classes("toggle").mark("maint-level")
            self.stats = ui.row().classes("meta")
            ui.toggle(
                list(SECTIONS), value=self.state.section, on_change=self._guard(self._set_section)
            ).classes("toggle").mark("maint-section")
            self.body = ui.column().classes("w-full gap-2")
        ui.timer(0.05, self._guard(self.load), once=True)

    async def load(self) -> None:
        stats = await gui_session.in_worker(wiki_engine.stats)
        self.stats.clear()
        with self.stats:
            ui.label(f"Wiki pages {stats['pages']}")
            ui.label(f"Raw sources {stats['raw_files']}")
            ui.label(f"Data size (MB) {megabytes(stats['data_bytes'])}")
        await self.render()

    async def _set_level(self, event: Any) -> None:
        if event.value not in db_context.reachable_shards(self.session.active_db):
            return
        self.session.bind_shard(event.value)
        self.state.level, self.state.report, self.state.flash = event.value, None, ""
        await self.load()

    async def _set_section(self, event: Any) -> None:
        self.state.section, self.state.flash = event.value, ""
        await self.render()

    async def render(self) -> None:
        self.body.clear()
        renderers = {
            "Search index": self._search_index,
            "Delete source": self._delete_source,
            "Link graph health": self._links,
            "Lint": self._lint,
            "Page language": self._language,
            "Ontology": self._ontology,
            "Activity log": self._log,
        }
        with self.body:
            if self.state.flash:
                ui.label(self.state.flash).classes("text-positive")
        await renderers[self.state.section]()

    def _maintainer_only(self) -> None:
        if not self.session.can_maintain:
            raise PermissionError("Maintainers only.")

    # --- search index ---------------------------------------------------------------------

    async def _search_index(self) -> None:
        health = await gui_session.in_worker(lex_index.index_health)
        with self.body:
            ui.label(
                "Lexical BM25 index (index/chunks.sqlite): the grounding source for search, both "
                "chat modes and the research agent. It is a derived cache; rebuilding reads "
                "chunks/ and wiki/ only, never the LLM."
            ).classes("hint")
            with ui.row().classes("meta"):
                ui.label("Source chunks indexed")
                ui.label(str(health["raw"]))
                ui.label("Wiki page chunks indexed")
                ui.label(str(health["wiki"]))
            if not health["wiki"]:
                ui.label(
                    "No index for this database. Every search and chat answer comes back empty "
                    "until it is rebuilt."
                ).classes("text-negative")
            if not self.session.can_maintain:
                ui.label("Only maintainers of this database can rebuild the index.").classes(
                    "muted"
                )
                return
            ui.button("Rebuild search index", on_click=self._guard(self._rebuild)).props(
                "flat"
            ).classes("btn").mark("rebuild-index")

    async def _rebuild(self) -> None:
        self._maintainer_only()
        result = await gui_session.in_worker(wiki_engine.rebuild_lex_index)
        self.state.flash = f"Indexed {result['chunks']} chunks."
        await self.render()

    # --- delete and move --------------------------------------------------------------------

    async def _delete_source(self) -> None:
        with self.body:
            if not self.session.can_maintain:
                ui.label("Delete actions require maintainer rights for this database.").classes(
                    "muted"
                )
                return
        sources = await gui_session.in_worker(dedup.list_sources)
        with self.body:
            if not sources:
                ui.label("No sources ingested yet.").classes("muted")
                return
            self._render_delete(sources)
            self._render_move(sources)

    def _render_delete(self, sources: list[str]) -> None:
        pick = ui.select(sources, value=sources[0], label="Source to delete").classes("w-96")
        ui.label(
            "Deletes the raw file, all chunks, QA pairs and all wiki pages that reference this "
            "source. This cannot be undone."
        ).classes("text-warning")
        button = ui.button("Delete source", on_click=self._guard(lambda: self._delete(pick.value)))
        button.props("flat").classes("btn primary").mark("delete-source")
        button.set_enabled(False)
        ui.checkbox(
            "I understand this is irreversible",
            on_change=lambda e: button.set_enabled(bool(e.value)),
        ).mark("delete-confirm")

    async def _delete(self, name: str) -> None:
        self._maintainer_only()
        result = await gui_session.in_worker(wiki_engine.delete_source, name)
        self.state.flash = (
            f"Deleted {name}. Wiki pages removed: {len(result['wiki_pages'])}. "
            f"QA rows removed: {result['qa_rows']}. Index rebuilt."
        )
        await self.render()

    def _render_move(self, sources: list[str]) -> None:
        here = db_context.get_active_db()
        targets = [s for s in db_context.reachable_shards(db_context.base_db()) if s != here]
        if not targets:
            return
        ui.label("Move to another classification level").classes("section-label q-mt-md")
        pick = ui.select(sources, value=sources[0], label="Source to move").classes("w-96")
        options = {t: classification.label(t) for t in targets}
        target = ui.select(options, value=targets[0], label="Target level").classes("w-96")
        target.mark("move-target")
        warning = ui.label("").classes("hint")

        def explain() -> None:
            up = classification.parse_shard(target.value)[1] > db_context.level()
            warning.set_text(
                "Moving up removes every trace from this level: pages it shares with other "
                "sources are rebuilt from them, answers and reports drawn from it are deleted, "
                "and its ontology facts and log lines are erased."
                if up
                else ""
            )

        target.on_value_change(lambda _e: explain())
        explain()
        ui.button(
            "Move source", on_click=self._guard(lambda: self._move(pick.value, target.value))
        ).props("flat").classes("btn").mark("move-source")

    async def _move(self, name: str, target: str) -> None:
        self._maintainer_only()
        report = await gui_session.in_worker(
            wiki_engine.move_source, name, target, self.session.user
        )
        self.state.flash = f"Moved {name} to {classification.label(target)}."
        self.state.extra = report.get("review") or []
        await self.render()
        if self.state.extra:
            with self.body:
                ui.label(
                    "Filed answers without provenance, created after this source: review them."
                ).classes("text-warning")
                for line in self.state.extra:
                    ui.label(line).classes("file")

    # --- link health, lint, language, ontology, log -------------------------------------------

    async def _links(self) -> None:
        orphans = await gui_session.in_worker(wiki_engine.find_orphans)
        with self.body:
            if not orphans:
                ui.label("No orphans: every page is linked from at least one other page.").classes(
                    "text-positive"
                )
                return
            ui.label(f"{len(orphans)} orphan(s): pages with no related in-links.").classes(
                "text-warning"
            )
            for page in orphans:
                ui.label(page).classes("file")

    async def _lint(self) -> None:
        with self.body:
            ui.label("Ask the LLM to review wiki quality: contradictions, orphans, gaps.").classes(
                "hint"
            )
            out = ui.column().classes("w-full")
            ui.button("Run lint", on_click=self._guard(lambda: self._run_lint(out))).props(
                "flat"
            ).classes("btn").mark("run-lint")

    async def _run_lint(self, out: ui.column) -> None:
        out.clear()
        with out:
            ui.label("Running lint (may take a minute)…").classes("muted")
        try:
            report = await gui_session.in_worker(wiki_engine.lint)
        except RuntimeError as e:
            out.clear()
            with out:
                ui.label(str(e)).classes("text-negative")
            return
        out.clear()
        with out:
            ui.markdown(report).classes("prose compact")

    async def _language(self) -> None:
        with self.body:
            ui.label(
                "Each page keeps the language it was created in. This pass stamps that language, "
                "translates lines written in the other language (a translation that fails its "
                "number/citation check is kept as a labelled Original quote), and removes "
                "[Teil n/m] and .md.md from source references."
            ).classes("hint")
            self.language = ui.column().classes("w-full")
            ui.button("Scan pages", on_click=self._guard(self._scan)).props("flat").classes(
                "btn"
            ).mark("scan-pages")
        self._render_language()

    async def _scan(self) -> None:
        self.state.report = await gui_session.in_worker(wiki_engine.normalize_pages, dry_run=True)
        self._render_language()

    def _render_language(self) -> None:
        report = self.state.report
        self.language.clear()
        if report is None:
            return
        with self.language:
            if not report:
                ui.label(
                    "Every page is pinned to one language and its references are clean."
                ).classes("text-positive")
                return
            ui.label(
                f"{len(report)} pages to update · {needs_translation(report)} need translation "
                "(one LLM call per block of foreign lines)."
            )
            for row in normalize_rows(report):
                ui.label("  ·  ".join(f"{k}: {v}" for k, v in row.items() if v != "")).classes(
                    "file"
                )
            if not self.session.can_maintain:
                ui.label("Only maintainers of this database can normalize pages.").classes("muted")
                return
            ui.button(
                f"Normalize {len(report)} pages", on_click=self._guard(self._normalize)
            ).props("flat").classes("btn primary").mark("normalize-pages")

    async def _normalize(self) -> None:
        self._maintainer_only()
        done = await gui_session.in_worker(wiki_engine.normalize_pages, dry_run=False)
        self.state.report, self.state.flash = None, f"Updated {len(done)} pages."
        await self.render()

    async def _ontology(self) -> None:
        with self.body:
            ui.label("The ontology workbench is not built yet in the Broadsheet frontend.").classes(
                "muted"
            )

    async def _log(self) -> None:
        text = await gui_session.in_worker(wiki_engine.read_log)
        with self.body:
            ui.label(text).classes("file").style("white-space: pre-wrap")


def build(session: gui_session.Session) -> None:
    """Page body of `/maintenance`."""
    MaintView(session).build()
