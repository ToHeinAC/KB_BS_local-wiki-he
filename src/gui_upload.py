"""Upload panel of the Broadsheet frontend, the right column of 2BrAIn (mockup `05-upload.html`).

Three steps, never automatic: files are prepared (duplicates skipped, PDF/DOCX/images
converted, dates and ontology classes detected); the user reviews one table (date, class,
work, classification level per file); then the batch is ingested oldest-first, one
classification level at a time, each into its own shard. A disabled button says why it is
disabled. Contradictions the ingest reports feed a Resolve panel.
"""

from collections.abc import Callable, Generator
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from nicegui import events, ui

import classification
import dedup
import gui_session
import md_convert
import metadata_extract
import ollama_client
import ontology_ui
import ui_logic

ACCEPT = ".md,.pdf,.docx,.png,.jpg,.jpeg,.tiff,.tif,.bmp"
_OLLAMA_DOWN = "Ollama is not reachable. Start it to convert non-Markdown files."
_TICK_SECONDS = 0.2
_DATE_FORMAT = "Use YYYY-MM-DD, e.g. 2024-01-15."


@dataclass
class Prepared:
    """The outcome of preparing a batch."""

    files: list[dict[str, Any]] = field(default_factory=lambda: [])
    skipped: list[str] = field(default_factory=lambda: [])
    warnings: list[str] = field(default_factory=lambda: [])
    error: str = ""
    info: str = ""
    classes: list[str] | None = None  # class options; None: this database has no ontology
    rows: dict[str, dict[str, str]] = field(default_factory=lambda: {})


class Progress:
    """A readout the worker thread writes and a UI timer reads (plain attributes, no widgets)."""

    def __init__(self, total: int = 0) -> None:
        self.total, self.done, self.text, self._frac = total, 0, "", 0.0

    @property
    def fraction(self) -> float:
        return self.done / self.total if self.total else self._frac

    def set(self, frac: float, text: str) -> None:
        self._frac, self.text = frac, text

    def tick(self) -> None:
        self.done += 1

    @contextmanager
    def status(self, label: str) -> Generator[None]:
        self.text = label
        yield


# --- preparing ----------


def _prepare_one(
    name: str, data: bytes, index: int, count: int, on_progress: Callable[[float, str], None]
) -> dict[str, Any] | str:
    """A prepared file, or the warning explaining why it was skipped."""
    convertible = md_convert.is_convertible(name)
    if convertible:
        try:
            text = md_convert.convert_to_markdown(
                data, name, ui_logic.convert_progress(on_progress, name, index, count)
            )
        except (RuntimeError, ValueError) as e:
            return f"Skipped {name}: conversion failed: {e}"
        save_name, content = Path(name).stem + ".md", text.encode()
    else:
        on_progress((index + 1) / count, f"{name}: reading…")
        text, save_name, content = data.decode(errors="replace"), name, None
    return {
        "save_name": save_name,
        "raw": data,
        "text": text,
        "content_bytes": content,
        "convertible": convertible,
        "detected_date": metadata_extract.extract_effective_date(text) or "",
    }


def _ontology_columns(prep: Prepared) -> None:
    """Prefill class, work and the other versions of that work, when the DB has an ontology."""
    schema = ontology_ui.upload_schema()
    if schema is None:
        return
    prep.classes = ["", *sorted(cid for cid, c in schema.classes.items() if not c.deprecated)]
    for f in prep.files:
        f["ontology"] = ontology_ui.detected(f["text"], f["detected_date"], schema)
    base = [{"File": f["save_name"], "effective as of": f["detected_date"]} for f in prep.files]
    for row in ontology_ui.review_rows(base, prep.files):
        prep.rows[row["File"]].update(
            {"class": row["Class"], "work": row["Work"], "others": row["Other versions"]}
        )


def prepare_batch(
    raws: dict[str, bytes], active_db: str, on_progress: Callable[[float, str], None]
) -> Prepared:
    """Check, convert and analyse an uploaded batch (blocking: run in a worker)."""
    prep = Prepared()
    prep.skipped = [n for n, b in raws.items() if ui_logic.visible_duplicate(b, active_db)]
    todo = [n for n in raws if n not in prep.skipped]
    if not todo:
        prep.info = "Nothing new to ingest."
        return prep
    if any(md_convert.is_convertible(n) for n in todo) and not ollama_client.is_available():
        prep.error = _OLLAMA_DOWN
        return prep
    on_progress(0.0, "Preparing files…")
    for i, name in enumerate(todo):
        item = _prepare_one(name, raws[name], i, len(todo), on_progress)
        if isinstance(item, str):
            prep.warnings.append(item)
        else:
            prep.files.append(item)
    prep.rows = {
        f["save_name"]: {"date": f["detected_date"], "class": "", "work": "", "others": ""}
        for f in prep.files
    }
    if prep.files:
        _ontology_columns(prep)
    return prep


# --- planning and ingesting ----------


def date_problem(value: str) -> str | None:
    """Why an entered effective date cannot be used; None when it is empty or valid."""
    text = value.strip()
    if not text:
        return None
    try:
        datetime.strptime(text, "%Y-%m-%d")
    except ValueError:
        return _DATE_FORMAT
    return None


def undated(names: list[str], dates: dict[str, str]) -> list[str]:
    """Files without a usable effective date (empty or malformed), in table order."""
    return [n for n in names if not dates.get(n, "").strip() or date_problem(dates[n])]


def make_plan(levels: dict[str, str | None], max_level: int) -> classification.UploadPlan:
    return classification.plan_upload(levels, max_level)


def block_reason(plan: classification.UploadPlan) -> str:
    """Why the ingest button is disabled; empty when it is not."""
    if plan.missing:
        return "Choose a classification for: " + ", ".join(plan.missing)
    if plan.denied:
        return "Above your clearance: " + ", ".join(plan.denied)
    return ""


def build_pending(
    files: list[dict[str, Any]],
    plan: classification.UploadPlan,
    dates: dict[str, str],
    ontology: dict[str, dict[str, str]] | None,
    shared: dict[str, str],
) -> dict[str, Any]:
    """The batch as `ui_logic.ingest_level` expects it."""
    return {
        "files": files,
        "dates": {n: str(v or "").strip() for n, v in dates.items()},
        "shared": {k: v.strip() for k, v in shared.items()},
        "levels": {n: lvl for lvl, names in plan.by_level.items() for n in names},
        "ontology": ontology,
    }


def run_ingest(
    pending: dict[str, Any],
    active_db: str,
    user: str,
    on_file: Callable[[str], AbstractContextManager[Any]],
    tick: Callable[[], None],
) -> dict[str, list[str]]:
    """Ingest the batch oldest-first (a newer version supersedes), one level at a time, each
    level into its own shard so pages of different levels are never merged."""
    dates: dict[str, str] = pending["dates"]
    files = sorted(pending["files"], key=lambda f: dates.get(f["save_name"]) or "")
    agg: dict[str, list[str]] = {
        "created": [],
        "updated": [],
        "contradictions": [],
        "failed": [],
        "ontology": [],
    }
    for level in sorted(set(pending["levels"].values())):
        group = [f for f in files if pending["levels"][f["save_name"]] == level]
        shard = classification.shard_id(active_db, level)
        ui_logic.ingest_level(shard, group, pending, agg, user, on_file, tick)
    return agg


# --- state ----------


@dataclass
class Upload:
    """One browser's upload session; dropped with the session's content."""

    key: str = ""
    prepared: Prepared | None = None
    dates: dict[str, str] = field(default_factory=lambda: {})
    classes: dict[str, str] = field(default_factory=lambda: {})
    works: dict[str, str] = field(default_factory=lambda: {})
    levels: dict[str, str | None] = field(default_factory=lambda: {})
    part_of: str = ""
    description: str = ""
    convert_text: str | None = None
    result: dict[str, list[str]] | None = None
    contradictions: list[str] = field(default_factory=lambda: [])
    pages: list[str] = field(default_factory=lambda: [])
    busy: bool = False
    message: str = ""


def upload_state(session: gui_session.Session) -> Upload:
    state = session.state.get("upload")
    if not isinstance(state, Upload):
        state = session.state["upload"] = Upload()
    return state


class UploadView:
    """The drop zone, the review table, the result and the Resolve panel."""

    def __init__(
        self, session: gui_session.Session, on_review: Callable[[bool], None] | None = None
    ) -> None:
        self.session = session
        self.state = upload_state(session)
        self._guard = gui_session.guarded(session)
        self.progress = Progress()
        self.on_review = on_review  # told when a batch starts or stops being prepared/reviewed
        self._reviewing = False

    def build(self) -> None:
        ui.label(
            "Markdown, PDF, DOCX and images. Non-Markdown files are converted to Markdown before "
            "ingest. Nothing is ingested until you confirm."
        ).classes("hint q-px-xl q-pt-md")
        with ui.column().classes("upload-col"):
            self.uploader = ui.upload(
                multiple=True, auto_upload=True, on_multi_upload=self._guard(self._received)
            )
            self.uploader.props(f'accept="{ACCEPT}" flat bordered').classes("w-full").mark(
                "upload-files"
            )
            self.bar = ui.linear_progress(value=0, show_value=False).props("size=4px")
            with ui.row().classes("items-center no-wrap gap-2"):
                self.spinner = ui.spinner(size="1.4em").mark("ingest-spinner")
                self.readout = ui.label("").classes("muted text-caption")
            self.stage = ui.column().classes("w-full gap-3")
        ui.timer(_TICK_SECONDS, self._tick)
        self._render()

    def _tick(self) -> None:
        for part in (self.bar, self.spinner, self.readout):
            part.set_visibility(self.state.busy)
        if self.state.busy:
            self.bar.set_value(self.progress.fraction)
            self.readout.set_text(self.progress.text)

    # --- receiving and preparing ----------

    async def _received(self, event: events.MultiUploadEventArguments) -> None:
        raws = {f.name: await f.read() for f in event.files}
        key = "|".join(sorted(dedup.sha256(b) for b in raws.values()))
        if key == self.state.key or self.state.busy:
            return
        keep = (self.state.contradictions, self.state.pages)
        self.state = self.session.state["upload"] = Upload(key=key)
        self.state.contradictions, self.state.pages = keep
        self.state.busy, self.progress = True, Progress()
        self._render()
        try:
            prep = await gui_session.in_worker(
                prepare_batch, raws, self.session.active_db, self.progress.set
            )
        except Exception as exc:
            prep = Prepared(error=f"Preparing the files failed: {exc}")
        self._adopt(prep)

    def _adopt(self, prep: Prepared) -> None:
        state = self.state
        state.prepared, state.busy = prep, False
        for name, row in prep.rows.items():
            state.dates[name], state.classes[name] = row["date"], row["class"]
            state.works[name], state.levels[name] = row["work"], None
        if len(prep.files) == 1 and prep.files[0]["convertible"]:
            state.convert_text = prep.files[0]["text"]
        self._render()

    # --- rendering ----------

    def _render(self) -> None:
        prep = self.state.prepared
        reviewing = self.state.busy or (prep is not None and bool(prep.files))
        if self.on_review is not None and reviewing != self._reviewing:
            self._reviewing = reviewing
            self.on_review(reviewing)
        self.stage.clear()
        with self.stage:
            prep = self.state.prepared
            if prep is not None:
                self._render_notices(prep)
                if prep.files:
                    self._render_review(prep)
            if self.state.result is not None:
                self._render_result(self.state.result)
            if self.state.message:
                ui.label(self.state.message).classes("text-negative")
            if self.state.contradictions:
                self._render_resolve()

    def _render_notices(self, prep: Prepared) -> None:
        if prep.skipped:
            ui.label("Skipped (already ingested): " + ", ".join(prep.skipped)).classes("muted")
        for warning in prep.warnings:
            ui.label(warning).classes("text-warning")
        for text, css in ((prep.error, "text-negative"), (prep.info, "muted")):
            if text:
                ui.label(text).classes(css)

    def _render_review(self, prep: Prepared) -> None:
        ui.label(f"{len(prep.files)} file(s) ready to ingest.").classes("section-label")
        if self.state.convert_text is not None:
            ui.label("Converted Markdown: review and edit before ingest.").classes("label")
            editor = ui.textarea(value=self.state.convert_text).classes("w-full")
            editor.props("outlined rows=3").mark("convert-editor")
            editor.on_value_change(lambda e: setattr(self.state, "convert_text", e.value))
        self.date_fields: dict[str, ui.input] = {}
        self._render_table(prep)
        self.date_hint = ui.label("").classes("date-hint")
        self._sync_date_hint()
        with ui.expansion("Optional shared metadata (applied to all files)").classes("fold w-full"):
            ui.input("part of", on_change=lambda e: setattr(self.state, "part_of", e.value or ""))
            ui.input(
                "description", on_change=lambda e: setattr(self.state, "description", e.value or "")
            )
        ui.label(
            f"Will be written to database {self.session.active_db}, each file at its chosen level."
        ).classes("hint")
        self.reason = ui.label("").classes("muted")
        with ui.row().classes("items-center gap-4"):
            self.ingest = ui.button(
                f"Ingest {len(prep.files)} file(s) into “{self.session.active_db}”",
                on_click=self._guard(self._ingest),
            )
            self.ingest.props("flat").classes("btn primary").mark("ingest-batch")
            ui.button("Discard", on_click=self._guard(self._discard)).props("flat").classes(
                "btn text small"
            ).mark("discard-batch")
        self._sync_ingest()

    def _discard(self) -> None:
        """Drop the prepared batch without ingesting it (nothing has been written yet)."""
        if self.state.busy:
            return
        self.state.prepared, self.state.key, self.state.convert_text = None, "", None
        self.uploader.reset()
        self._render()

    def _render_table(self, prep: Prepared) -> None:
        cols = "minmax(0,2fr) 11rem" + (" 9rem 10rem minmax(0,1.5fr)" if prep.classes else "")
        with (
            ui.element("div")
            .classes("review")
            .style(
                f"display: grid; grid-template-columns: {cols} auto; "
                "gap: 8px 16px; align-items: center"
            )
        ):
            heads = ["File", "Effective as of"] + (
                ["Class", "Work", "Other versions"] if prep.classes else []
            )
            for head in [*heads, "Classification"]:
                ui.label(head).classes("label")
            for f in prep.files:
                self._render_row(f["save_name"], prep)

    def _render_row(self, name: str, prep: Prepared) -> None:
        state = self.state
        ui.label(name).classes("file")
        self._render_date(name)
        if prep.classes:
            ui.select(
                prep.classes,
                value=state.classes.get(name, ""),
                on_change=self._setter(state.classes, name),
            ).props("dense borderless").mark(f"class-{name}")
            ui.input(
                value=state.works.get(name, ""), on_change=self._setter(state.works, name)
            ).props("dense borderless")
            ui.label(prep.rows[name]["others"]).classes("muted text-caption")
        max_level = self.session.grants.get(self.session.active_db, 0)
        options = {k: ui_logic.level_key_label(k) for k in classification.LEVELS[: max_level + 1]}
        ui.toggle(options, value=None, on_change=self._guard(self._set_level(name))).classes(
            "toggle"
        ).mark(f"level-{name}")

    def _render_date(self, name: str) -> None:
        """The effective date: typed as YYYY-MM-DD or picked, highlighted while it is missing."""
        box = ui.input(
            value=self.state.dates.get(name, ""),
            placeholder="YYYY-MM-DD",
            validation=lambda v: date_problem(str(v or "")),
        )
        box.props("dense outlined").classes("date-field").mark(f"date-{name}")
        with box, ui.menu().props("no-parent-event") as menu:
            ui.date(mask="YYYY-MM-DD").bind_value(box)
        with box.add_slot("append"):
            ui.icon("edit_calendar").classes("cursor-pointer").on("click", menu.open)

        def changed(event: Any) -> None:
            self.state.dates[name] = str(event.value or "")
            menu.close()
            self._sync_date_hint()

        box.on_value_change(changed)
        self.date_fields[name] = box

    def _sync_date_hint(self) -> None:
        prep = self.state.prepared
        names = [f["save_name"] for f in prep.files] if prep else []
        missing = undated(names, self.state.dates)
        self.date_hint.set_text(
            f"No effective date for: {', '.join(missing)}. Add the date the document took effect "
            "(look for “Stand”, “Fassung vom”, “gültig ab”): it decides which source is newer "
            "when pages merge. Without one, the file counts as undated."
            if missing
            else ""
        )
        self.date_hint.set_visibility(bool(missing))
        for name, box in self.date_fields.items():
            box.classes(add="missing") if name in missing else box.classes(remove="missing")

    @staticmethod
    def _setter(target: dict[str, str], name: str) -> Callable[[Any], None]:
        def set_value(event: Any) -> None:
            target[name] = event.value or ""

        return set_value

    def _set_level(self, name: str) -> Callable[[Any], None]:
        def set_level(event: Any) -> None:
            self.state.levels[name] = event.value
            self._sync_ingest()

        return set_level

    def _plan(self) -> classification.UploadPlan:
        return make_plan(self.state.levels, self.session.grants.get(self.session.active_db, 0))

    def _sync_ingest(self) -> None:
        plan = self._plan()
        self.reason.set_text(block_reason(plan))
        self.ingest.set_enabled(plan.ok and not self.state.busy)

    # --- ingesting ----------

    async def _ingest(self) -> None:
        state, prep = self.state, self.state.prepared
        plan = self._plan()
        if prep is None or not plan.ok or state.busy:
            return
        files = prep.files
        if state.convert_text is not None:
            files[0]["text"] = state.convert_text
            files[0]["content_bytes"] = state.convert_text.encode()
        ontology = (
            {
                n: {"class": state.classes.get(n, ""), "work": state.works.get(n, "")}
                for n in state.dates
            }
            if prep.classes is not None
            else None
        )
        pending = build_pending(
            files,
            plan,
            state.dates,
            ontology,
            {"part of": state.part_of, "description": state.description},
        )
        state.contradictions, state.pages, state.result, state.message = [], [], None, ""
        state.busy, self.progress = True, Progress(total=len(files))
        self._sync_ingest()
        try:
            agg = await gui_session.in_worker(
                run_ingest,
                pending,
                self.session.active_db,
                self.session.user,
                self.progress.status,
                self.progress.tick,
            )
        except Exception as exc:
            state.busy, state.message = False, f"Ingest failed: {exc}"
            self._render()
            return
        self._finish(agg)

    def _finish(self, agg: dict[str, list[str]]) -> None:
        state = self.state
        state.busy, state.prepared, state.key, state.result = False, None, "", agg
        state.contradictions = agg["contradictions"]
        state.pages = list({*agg["created"], *agg["updated"]})
        self.uploader.reset()
        self._render()

    def _render_result(self, agg: dict[str, list[str]]) -> None:
        ui.label("Ingest complete.").classes("section-label")
        with ui.row().classes("meta"):
            ui.label(f"Created {len(dict.fromkeys(agg['created']))}")
            ui.label(f"Updated {len(dict.fromkeys(agg['updated']))}")
            ui.label(f"Contradictions {len(agg['contradictions'])}")
        if agg["created"]:
            ui.label("New pages: " + ", ".join(dict.fromkeys(agg["created"]))).classes("file")
        for title, items, css in (
            ("Failed", agg["failed"], "text-negative"),
            ("Ontology values ignored", agg["ontology"], "text-warning"),
            ("Contradictions found", agg["contradictions"], "text-warning"),
        ):
            if items:
                ui.label(f"{title}:").classes(f"label {css}")
                for item in items:
                    ui.label(item).classes(css)

    # --- resolving contradictions ----------

    def _render_resolve(self) -> None:
        with ui.row().classes("items-center w-full"):
            ui.label("Resolve contradictions").classes("section-label").tooltip(
                ui_logic.RESOLVE_HELP
            )
            ui.space()
            ui.button("Dismiss", on_click=self._guard(self._dismiss)).props("flat").classes(
                "btn text small"
            ).mark("dismiss-contradictions")
        for i, desc in enumerate(self.state.contradictions):
            self._render_contradiction(i, desc)

    def _render_contradiction(self, i: int, desc: str) -> None:
        with ui.expansion(desc).classes("fold w-full"):
            pages = ui.select(self.state.pages, value=list(self.state.pages), multiple=True)
            pages.props("dense outlined use-chips").classes("w-full")
            guidance = ui.textarea("Guidance (optional): which claim is authoritative?").classes(
                "w-full"
            )
            out = ui.column().classes("gap-1")
            ui.button(
                "Reconcile",
                on_click=self._guard(lambda: self._reconcile(desc, pages, guidance, out)),
            ).props("flat").classes("btn primary").mark(f"reconcile-{i}")

    async def _reconcile(
        self, desc: str, pages: ui.select, guidance: ui.textarea, out: ui.column
    ) -> None:
        out.clear()
        try:
            res = await gui_session.in_worker(
                ui_logic.resolve_by_shard,
                desc,
                list(pages.value),
                guidance.value or "",
                self.session.active_db,
            )
        except RuntimeError as e:
            with out:
                ui.label(str(e)).classes("text-negative")
            return
        with out:
            if res["updated"]:
                ui.label("Updated: " + ", ".join(res["updated"])).classes("text-positive")
            elif not res["skipped"]:
                ui.label("No pages were rewritten.").classes("muted")
            if res["skipped"]:
                ui.label(
                    "Not rewritten, the reply switched the page's language: "
                    + ", ".join(res["skipped"])
                ).classes("text-warning")

    def _dismiss(self) -> None:
        self.state.contradictions, self.state.pages = [], []
        self._render()
