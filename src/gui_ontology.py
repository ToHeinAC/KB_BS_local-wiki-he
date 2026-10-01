"""Ontology workbench of the Broadsheet frontend: Maintenance → Ontology (docs/ontology.md).

A port of `ontology_ui.render` view by view, reusing its pure helpers. Every write goes
through the same plans (`ontology_store.prepare_*` → `wiki_engine.apply_ontology`), which
validate, check maintainer rights and record a revision; model calls run in a worker.
"""

import hashlib
import json
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from nicegui import events, ui

import db_context
import dedup
import gui_session
import ontology
import ontology_bundle as bundle
import ontology_detect
import ontology_evolution
import ontology_export
import ontology_store
import ontology_ui
import wiki_engine

VIEWS = ("Overview", "Classes", "Facts", "Edit", "Proposals", "Cues", "Lint", "History", "Import")
_CLASS_FIELDS = ("id", "broader", "label_de", "label_en", "definition", "cues", "replaced_by")
_FACT_FIELDS = ("class", "work", "version_date")
_WRITE_ERRORS = (ontology_store.StaleRevisionError, PermissionError, KeyError, ValueError)


def class_tree(
    classes: dict[str, ontology.ClassDef], usage: dict[str, int]
) -> list[tuple[int, str]]:
    """(depth, line) for every class, children under their parent, siblings sorted."""
    children: dict[str | None, list[str]] = {}
    for c in classes.values():
        children.setdefault(c.broader, []).append(c.id)
    lines: list[tuple[int, str]] = []

    def walk(parent: str | None, depth: int) -> None:
        for cid in sorted(children.get(parent, [])):
            lines.append((depth, ontology_ui.class_line(classes[cid], usage.get(cid, 0))))
            walk(cid, depth + 1)

    walk(None, 0)
    return lines


def fact_rows(facts: dict[str, Any]) -> list[dict[str, str]]:
    fmt = ontology_ui.fmt
    return [
        {
            "Kind": section,
            "Subject": key,
            "Class": fmt(values.get("class")),
            "Work": fmt(values.get("work")),
            "Other": "; ".join(
                f"{p} = {fmt(v)}" for p, v in values.items() if p not in ("class", "work")
            ),
        }
        for section, entries in facts.items()
        for key, values in entries.items()
    ]


def _grid(rows: list[dict[str, Any]], columns: list[str]) -> None:
    """A read-only table as a CSS grid of labels (hairlines come from the stylesheet)."""
    with (
        ui.element("div")
        .classes("agate-grid")
        .style(f"display: grid; grid-template-columns: repeat({len(columns)}, auto); gap: 4px 18px")
    ):
        for column in columns:
            ui.label(column).classes("label")
        for row in rows:
            for column in columns:
                ui.label(str(row.get(column, ""))).classes("cell")


class OntologyView:
    """The workbench inside a container of the Maintenance page."""

    def __init__(self, session: gui_session.Session, box: ui.column) -> None:
        self.session = session
        self.box = box
        self._guard = gui_session.guarded(session)
        state = session.state.setdefault("ontology", {})
        self.state: dict[str, Any] = state

    # --- frame --------------------

    def render(self) -> None:
        self.box.clear()
        with self.box:
            notice = self.state.pop("notice", "")
            if notice:
                ui.label(notice).classes("text-positive")
            if not ontology_store.exists():
                self._render_missing()
                return
            schema, errors = ontology_store.load()
            self._render_header()
            if errors:
                ui.label("This ontology is invalid. Nothing uses it until it is fixed:").classes(
                    "text-negative"
                )
                ui.markdown(ontology_ui.bullets(errors))
            view = self.state.get("view", VIEWS[0])
            ui.toggle(list(VIEWS), value=view, on_change=self._guard(self._set_view)).classes(
                "toggle"
            ).mark("onto-view")
            self.body = ui.column().classes("w-full gap-2")
        self._render_view(schema)

    def _set_view(self, event: Any) -> None:
        self.state["view"] = event.value
        self.render()

    def _render_view(self, schema: ontology.Schema | None) -> None:
        renderers: dict[str, Callable[[], None]] = {
            "Overview": lambda: self._overview(schema),
            "Classes": lambda: self._classes(schema),
            "Facts": self._facts,
            "Edit": lambda: self._edit(schema),
            "Proposals": self._proposals,
            "Cues": self._cues,
            "Lint": self._lint,
            "History": self._history,
            "Import": self._import,
        }
        with self.body:
            renderers[self.state.get("view", VIEWS[0])]()

    def _done(self, notice: str) -> None:
        self.state["notice"] = notice
        self.render()

    def _apply(self, plan: bundle.ImportPlan, via: str, name: str | None = None,
               sha: str | None = None) -> None:  # fmt: skip
        if plan.status == "unchanged":
            self._done("Identical to the current revision, nothing changed.")
            return
        if plan.status != "ready":
            ui.notify("Cannot apply: " + "; ".join(plan.errors), type="negative")
            return
        try:
            row = wiki_engine.apply_ontology(
                plan, user=self.session.user, via=via, file_name=name, file_sha=sha
            )
        except _WRITE_ERRORS as exc:
            ui.notify(str(exc), type="negative")
            return
        self.state.pop("upload", None)
        self._done(f"Applied revision {row['seq']}." if row else "Nothing changed.")

    def _button(
        self, label: str, marker: str, action: Callable[[], Any], primary: bool = False
    ) -> ui.button:
        button = ui.button(label, on_click=self._guard(action)).props("flat")
        return button.classes("btn primary" if primary else "btn small").mark(marker)

    # --- states --------------------

    def _render_missing(self) -> None:
        ui.label("No ontology for this database.").classes("headline s")
        ui.label(
            "An ontology types this database's documents (classes such as report or ordinance) "
            "and records facts about them. Start from shared modules, or import an exported file."
        ).classes("hint")
        if not self.session.can_maintain:
            ui.label("Only maintainers of this database can create one.").classes("muted")
            return
        options = sorted(ontology_store.available_modules())
        picked = [m for m in ("core",) if m in options]
        modules = ui.select(options, value=picked, multiple=True, label="Modules")
        modules.props("use-chips outlined dense").classes("w-96").mark("onto-modules")
        warning = ui.label("").classes("text-warning")
        with_cues = ontology_evolution.modules_with_cues(ontology_store.shared_modules())

        def check(_e: Any = None) -> None:
            chosen = set(modules.value or [])
            none = bool(chosen) and not chosen & set(with_cues)
            warning.set_text(
                "The selected modules have no detection cues: documents will not be classified "
                f"automatically. Modules with cues: {', '.join(with_cues) or 'none'}."
                if none
                else ""
            )

        modules.on_value_change(check)
        check()

        def create() -> None:
            chosen = list(modules.value or [])
            if chosen:
                self._apply(ontology_store.prepare_state({"schema": {"modules": chosen}}), "create")

        self._button("Create ontology", "onto-create", create, primary=True)
        ui.label("Or import a file").classes("label q-mt-md")
        self.body = ui.column().classes("w-full")
        with self.body:
            self._import()

    def _render_header(self) -> None:
        seq, rev = ontology_store.current_revision()
        rows = ontology_store.history()
        note = (
            " · changed since the last recorded revision"
            if rows and rows[-1]["hash"] != rev
            else ""
        )
        open_proposals = len(ontology_store.proposals())
        if open_proposals:
            note += f" · {open_proposals} open proposal(s)"
        ui.label(f"Revision {seq} · {rev}{note}").classes("section-label")
        ui.markdown(ontology_ui.change_line("Last change", ontology_store.last_change(human=True)))
        ui.markdown(
            ontology_ui.change_line(
                "Last automatic change", ontology_store.last_change(human=False)
            )
        )
        db, day = db_context.get_active_db(), datetime.now(UTC).strftime("%Y%m%d")
        text, name = (
            ontology_store.export_text(self.session.user),
            f"ontology-{db}-rev{seq}-{day}.yaml",
        )
        ui.button("Export current (YAML)", on_click=lambda: ui.download.content(text, name)).props(
            "flat"
        ).classes("btn text small")

    # --- read views --------------------

    def _overview(self, schema: ontology.Schema | None) -> None:
        if schema is None:
            return
        facts = ontology_store.current_state()["facts"]
        with ui.row().classes("meta"):
            ui.label(f"Classes {len(schema.classes)}")
            ui.label(f"Relations {len(schema.relations)}")
            ui.label(f"Sources with facts {len(facts.get('sources', {}))}")
            ui.label(f"Works {len(facts.get('works', {}))}")
        ui.label("Modules: " + " · ".join(f"{m} {v}" for m, v in schema.modules.items()))
        db = db_context.get_active_db()
        turtle = ontology_export.skos_turtle(schema)
        with ui.row():
            ui.button(
                "Schema as SKOS (Turtle)",
                on_click=lambda: ui.download.content(turtle, f"ontology-{db}.ttl"),
            ).props("flat").classes("btn text small")
            view = ontology_store.view()
            if view is not None:
                doc = json.dumps(
                    ontology_export.facts_jsonld(view, db=db), indent=2, ensure_ascii=False
                )
                ui.button(
                    "Facts as JSON-LD",
                    on_click=lambda: ui.download.content(doc, f"ontology-{db}.jsonld"),
                ).props("flat").classes("btn text small")

    def _classes(self, schema: ontology.Schema | None) -> None:
        if schema is None:
            ui.label("Fix the errors above to see the classes.").classes("muted")
            return
        for depth, line in class_tree(schema.classes, ontology_ui.class_usage()):
            ui.markdown(line).style(f"margin-left: {depth * 1.5}rem")
        rows = [
            {"Relation": r.id, "Domain": ", ".join(r.domain), "Range": ", ".join(r.range),
             "Inverse": r.inverse or "", "Target": r.target, "Module": r.module}
            for r in schema.relations.values()
        ]  # fmt: skip
        if rows:
            _grid(rows, list(rows[0]))

    def _facts(self) -> None:
        rows = fact_rows(ontology_store.current_state()["facts"])
        if not rows:
            ui.label("No facts yet. Add them in Edit, or by export, edit and import.").classes(
                "muted"
            )
            return
        _grid(rows, list(rows[0]))

    def _lint(self) -> None:
        findings = wiki_engine.ontology_lint()
        if not findings:
            ui.label("No findings: no cycles, rank or date problems, nothing missing.").classes(
                "text-positive"
            )
            return
        ui.label("Ranks only order and warn; they never decide a legal conflict.").classes("hint")
        for f in findings:
            ui.label(f["message"]).classes("text-warning" if f["level"] == "warning" else "")

    # --- plans: preview, history, import --------------------

    def _render_plan(self, plan: bundle.ImportPlan) -> None:
        for warning in plan.warnings:
            ui.label(warning).classes("text-warning")
        if plan.status == "error":
            ui.label("This cannot be applied:").classes("text-negative")
            ui.markdown(ontology_ui.bullets(plan.errors))
        elif plan.status == "unchanged":
            seq, _ = ontology_store.current_revision()
            ui.label(f"Identical to revision {seq}, nothing changed.").classes("muted")
        else:
            summary = bundle.summary_text(plan.summary)
            ui.label(f"Preview: {summary} · local schema version {plan.local_version}")
            self._diff(plan.changes)

    def _diff(self, changes: list[dict[str, Any]]) -> None:
        fmt = ontology_ui.fmt
        rows = [
            {"Item": bundle.label(c["path"]), "Change": c["op"],
             "Before": fmt(c.get("from")), "After": fmt(c.get("to"))}
            for c in changes
        ]  # fmt: skip
        if rows:
            _grid(rows, ["Item", "Change", "Before", "After"])

    def _history(self) -> None:
        rows = list(reversed(ontology_store.history()))
        if not rows:
            ui.label("No revisions recorded yet.").classes("muted")
            return
        _grid(
            [
                {
                    "Rev": r["seq"],
                    "When": ontology_ui.when(r["at"]),
                    "Who": r.get("user") or "system",
                    "Via": r["via"],
                    "File": r.get("file") or "",
                    "Changes": bundle.summary_text(r["summary"]),
                }
                for r in rows
            ],
            ["Rev", "When", "Who", "Via", "File", "Changes"],
        )
        seq = int(self.state.get("revision", rows[0]["seq"]))
        pick = ui.select([r["seq"] for r in rows], value=seq, label="Revision")
        pick.props("dense outlined").classes("w-48").mark("onto-revision")
        pick.on_value_change(self._guard(self._pick_revision))
        row = next((r for r in rows if r["seq"] == seq), rows[0])
        self._diff(row.get("diff") or [])
        text = ontology_store.snapshot_text(seq)
        if text:
            name = f"ontology-{db_context.get_active_db()}-rev{seq}.yaml"
            ui.button(
                f"Download revision {seq}", on_click=lambda: ui.download.content(text, name)
            ).props("flat").classes("btn text small")
        if self.session.can_maintain and seq != rows[0]["seq"]:
            self._restore_controls(seq)

    def _pick_revision(self, event: Any) -> None:
        self.state["revision"] = event.value
        self.render()

    def _restore_controls(self, seq: int) -> None:
        button = self._button(
            "Restore",
            "onto-restore",
            lambda: self._apply(ontology_store.prepare_restore(seq), "restore", f"revision {seq}"),
        )
        button.set_enabled(False)
        ui.checkbox(
            f"Restore revision {seq} as a new revision",
            on_change=lambda e: button.set_enabled(bool(e.value)),
        ).mark("onto-restore-ok")

    def _import(self) -> None:
        up = ui.upload(auto_upload=True, on_upload=self._guard(self._received))
        up.props('accept=".yaml,.yml" flat bordered label="Edited ontology file (YAML)"')
        up.classes("w-full").mark("onto-upload")
        upload = self.state.get("upload")
        if upload is None:
            ui.label(
                "Export, edit, upload. Nothing is written before you confirm the preview."
            ).classes("hint")
            return
        ui.checkbox(
            "This file comes from another database",
            value=bool(self.state.get("other_db")),
            on_change=self._guard(self._set_other_db),
        )
        self._import_preview(upload)

    async def _received(self, event: events.UploadEventArguments) -> None:
        data = await event.file.read()
        self.state["upload"] = {"name": event.file.name, "data": data}
        self.state["choices"] = {}
        self.render()

    def _set_other_db(self, event: Any) -> None:
        self.state["other_db"] = bool(event.value)
        self.render()

    def _import_preview(self, upload: dict[str, Any]) -> None:
        text = upload["data"].decode("utf-8", errors="replace")
        other, choices = bool(self.state.get("other_db")), self.state.setdefault("choices", {})
        plan = ontology_store.prepare_import(text, allow_other_db=other)
        self._conflicts(plan.conflicts, choices)
        if choices:
            plan = ontology_store.prepare_import(text, resolutions=choices, allow_other_db=other)
        self._render_plan(plan)
        if plan.status != "ready":
            return
        if not self.session.can_maintain:
            ui.label("Only maintainers of this database can apply an import.").classes("muted")
            return
        sha = hashlib.sha256(upload["data"]).hexdigest()
        self._button(
            "Apply import", "onto-apply",
            lambda: self._apply(plan, "import", upload["name"], sha), primary=True,
        )  # fmt: skip

    def _conflicts(self, conflicts: list[dict[str, Any]], choices: dict[str, str]) -> None:
        if not conflicts:
            return
        ui.label(
            f"{len(conflicts)} conflict(s): these items changed both in your file and in the "
            "database since your export. The default keeps the current value."
        ).classes("text-warning")
        fmt = ontology_ui.fmt
        for c in conflicts:
            path = c["path"]
            ui.label(f"{path}: current {fmt(c['current'])}, yours {fmt(c['mine'])}").classes("file")
            ui.radio(
                {"current": "Keep current", "mine": "Use mine"},
                value=choices.get(path, "current"),
                on_change=self._guard(self._choice(path)),
            ).props("inline")

    def _choice(self, path: str) -> Callable[[Any], None]:
        def choose(event: Any) -> None:
            choices: dict[str, str] = self.state.setdefault("choices", {})
            if event.value == "mine":
                choices[path] = "mine"
            else:
                choices.pop(path, None)
            self.render()

        return choose

    # --- edit --------------------

    def _edit(self, schema: ontology.Schema | None) -> None:
        if schema is None or not self.session.can_maintain:
            ui.label(
                "Editing needs a valid ontology and maintainer rights for this database."
            ).classes("muted")
            return
        tables = self.state.get("edit")
        if tables is None:
            classes, facts = ontology_evolution.editor_tables(
                ontology_store.current_state(), dedup.list_sources()
            )
            tables = self.state["edit"] = {"classes": classes, "facts": facts}
        ui.label("Local classes. Shared modules change via git.").classes("section-label")
        ui.label(
            f"Several cues in one cell: separate them with `{ontology_evolution.CUE_SEP}`."
        ).classes("hint")
        for i, row in enumerate(tables["classes"]):
            self._class_row(i, row)
        self._button("Add class", "onto-add-class", self._add_class)
        ids = sorted({*schema.classes, *(str(r.get("id") or "") for r in tables["classes"])} - {""})
        ui.label("Facts per document. Relations and aliases: use export and import.").classes(
            "section-label q-mt-md"
        )
        for row in tables["facts"]:
            self._fact_row(row, ["", *ids])
        self._button("Preview changes", "onto-edit-preview", self._preview_edit)
        preview = self.state.get("edit_preview")
        if preview is not None:
            self._edit_preview(preview)

    def _class_row(self, i: int, row: dict[str, Any]) -> None:
        with ui.row().classes("items-center no-wrap w-full"):
            for name in _CLASS_FIELDS:
                field = ui.input(name, value=str(row.get(name) or ""), on_change=_setter(row, name))
                field.props("dense outlined").classes("grow").mark(f"onto-class-{i}-{name}")
            ui.checkbox(
                "deprecated",
                value=bool(row.get("deprecated")),
                on_change=_setter(row, "deprecated"),
            )

    def _fact_row(self, row: dict[str, Any], classes: list[str]) -> None:
        with ui.row().classes("items-center no-wrap w-full"):
            ui.label(row["source"]).classes("file").style("min-width: 14rem")
            ui.select(classes, value=row.get("class") or "", on_change=_setter(row, "class")).props(
                "dense outlined"
            ).classes("w-48")
            for name in _FACT_FIELDS[1:]:
                ui.input(name, value=row.get(name) or "", on_change=_setter(row, name)).props(
                    "dense outlined"
                )

    def _add_class(self) -> None:
        self.state["edit"]["classes"].append(
            {**dict.fromkeys(_CLASS_FIELDS, ""), "deprecated": False}
        )
        self.state.pop("edit_preview", None)
        self.render()

    def _preview_edit(self) -> None:
        tables = self.state["edit"]
        state = ontology_store.current_state()
        new, errors = ontology_evolution.state_from_tables(
            state, tables["classes"], tables["facts"]
        )
        self.state["edit_preview"] = {"errors": errors, "state": new}
        self.render()

    def _edit_preview(self, preview: dict[str, Any]) -> None:
        if preview["errors"]:
            ui.label("Fix the tables first:").classes("text-negative")
            ui.markdown(ontology_ui.bullets(preview["errors"]))
            return
        plan = ontology_store.prepare_state(preview["state"])
        self._render_plan(plan)
        if plan.status == "ready":
            self._button(
                "Apply changes", "onto-edit-apply", lambda: self._apply_edit(plan), primary=True
            )

    def _apply_edit(self, plan: bundle.ImportPlan) -> None:
        self.state.pop("edit", None)
        self.state.pop("edit_preview", None)
        self._apply(plan, "editor")

    # --- proposals and suggestions --------------------

    def _proposals(self) -> None:
        rows = ontology_store.proposals()
        if not rows:
            ui.label("No open fact proposals.").classes("muted")
        else:
            ui.label(
                "Suggested by the model when no cue matched. Each quote was checked to occur "
                "verbatim in the document. Confirm to make it a fact, or reject it."
            ).classes("hint")
            for r in rows:
                self._fact_proposal(r)
        self._page_classes()
        self._suggestions()

    def _fact_proposal(self, r: dict[str, Any]) -> None:
        subject = str(r["subject"]).split(":", 1)[1]
        attrs = ", ".join(f"{k}={v}" for k, v in bundle.as_map(r.get("attributes")).items())
        suffix = f" ({attrs})" if attrs else ""
        with ui.column().classes("fold w-full gap-1"):
            ui.label(f"{subject} · {r['predicate']} = {r['object']}{suffix}").classes("t")
            ui.label(f"“{r.get('evidence') or ''}”").classes("muted")
            if self.session.can_maintain:
                with ui.row():
                    self._button(
                        "Confirm", f"onto-ok-{r['id']}", lambda: self._decide(r["id"], True)
                    )
                    self._button(
                        "Reject", f"onto-no-{r['id']}", lambda: self._decide(r["id"], False)
                    )

    def _decide(self, row_id: str, accept: bool) -> None:
        try:
            row = wiki_engine.decide_proposal(row_id, accept=accept, user=self.session.user)
        except _WRITE_ERRORS as exc:
            ui.notify(str(exc), type="negative")
            return
        self._done(f"Confirmed, revision {row['seq']}." if row else "Proposal rejected.")

    def _page_classes(self) -> None:
        schema, _ = ontology_store.load()
        if not self.session.can_maintain or schema is None:
            return
        if not ontology_detect.page_class_options(schema):
            return
        ui.label("Concept pages").classes("section-label q-mt-md")
        ui.label(
            "Asks the model for a class for up to 10 unclassified concept/entity pages."
        ).classes("hint")
        self._button("Classify concept pages", "onto-classify-pages", self._classify_pages)

    async def _classify_pages(self) -> None:
        made = await gui_session.in_worker(
            wiki_engine.propose_page_classes, self.session.user, limit=10
        )
        self._done(f"{made} page class proposal(s) added for review.")

    def _suggestions(self) -> None:
        ui.label("New class suggestions").classes("section-label q-mt-md")
        for p in ontology_store.schema_proposals():
            self._suggestion(p)
        facts = ontology_store.current_state()["facts"].get("sources", {})
        unclassified = [s for s in dedup.list_sources() if not facts.get(s, {}).get("class")]
        if not unclassified:
            ui.label("Every document has a class.").classes("muted")
            return
        if not self.session.can_maintain:
            return
        pick = ui.select(unclassified, value=unclassified[0], label="Unclassified document")
        pick.props("dense outlined").classes("w-96").mark("onto-unclassified")
        self._button(
            "Ask the model for a new class", "onto-suggest", lambda: self._suggest(pick.value)
        )

    def _suggestion(self, p: dict[str, Any]) -> None:
        spec = p["spec"]
        with ui.column().classes("fold w-full gap-1"):
            ui.label(
                f"{p['class_id']} under {spec['broader']} for {p['source']}: "
                f"{spec['labels']['de']} / {spec['labels']['en']}: {spec['definition']}"
            ).classes("t")
            ui.label(f"cue {spec['cues'][0]} matches: “{p.get('evidence', '')}”").classes("muted")
            if self.session.can_maintain:
                with ui.row():
                    self._button(
                        "Accept", f"onto-sok-{p['id']}", lambda: self._decide_schema(p["id"], True)
                    )
                    self._button(
                        "Reject", f"onto-sno-{p['id']}", lambda: self._decide_schema(p["id"], False)
                    )

    def _decide_schema(self, pid: str, accept: bool) -> None:
        try:
            row = wiki_engine.decide_schema_proposal(pid, accept=accept, user=self.session.user)
        except _WRITE_ERRORS as exc:
            ui.notify(str(exc), type="negative")
            return
        self._done(f"Class added, revision {row['seq']}." if row else "Suggestion rejected.")

    async def _suggest(self, source: str) -> None:
        result = await gui_session.in_worker(
            wiki_engine.suggest_class, source, user=self.session.user
        )
        if isinstance(result, str):
            ui.notify(f"No suggestion: {result}", type="warning")
            return
        self._done(f"Suggestion {result['class_id']} added for review.")

    # --- cues --------------------

    def _cues(self) -> None:
        heads = ontology_store.source_heads()
        field = ui.input("Test a cue (regular expression)").classes("w-96").mark("onto-cue")
        result = ui.column().classes("w-full gap-1")

        def test(_e: Any = None) -> None:
            result.clear()
            with result:
                _cue_result(field.value or "", heads)

        field.on_value_change(test)
        test()
        ui.label("Re-classify").classes("section-label q-mt-md")
        ui.label(
            "Re-runs detection with the current cues. Facts made by code follow the cues; your "
            "own decisions are never changed (they are listed as kept)."
        ).classes("hint")
        changes, _ = wiki_engine.reclassify(self.session.user, apply=False)
        if not changes:
            self._nothing_to_reclassify()
            return
        _grid(_reclassify_rows(changes), ["Document", "Fact", "Now", "Would be", "Action"])
        applicable = any(c["action"] in ("update", "withdraw") for c in changes)
        if self.session.can_maintain and applicable:
            self._button("Apply re-classify", "onto-reclassify", self._reclassify)

    def _nothing_to_reclassify(self) -> None:
        schema, _ = ontology_store.load()
        if schema is None:
            return
        note = ontology_evolution.reclassify_note(
            ontology_store.source_heads(), schema, ontology_store.read_rows()
        )
        ui.label(note).classes("text-positive" if note.startswith("Every") else "text-warning")

    def _reclassify(self) -> None:
        try:
            _, row = wiki_engine.reclassify(self.session.user, apply=True)
        except _WRITE_ERRORS as exc:
            ui.notify(str(exc), type="negative")
            return
        self._done(f"Re-classified, revision {row['seq']}." if row else "Nothing changed.")


def _setter(row: dict[str, Any], key: str) -> Callable[[Any], None]:
    def set_value(event: Any) -> None:
        row[key] = event.value

    return set_value


def _cue_result(pattern: str, heads: dict[str, str]) -> None:
    if not pattern:
        ui.label("Shows which documents a cue would match, before you save it.").classes("hint")
        return
    matches, error = ontology_evolution.cue_matches(pattern, heads)
    if error:
        ui.label(error).classes("text-negative")
        return
    ui.label(f"Matches {len(matches)} of {len(heads)} documents")
    if matches:
        _grid([{"Document": n, "Line": line} for n, line in matches], ["Document", "Line"])


def _reclassify_rows(changes: list[dict[str, Any]]) -> list[dict[str, str]]:
    fmt = ontology_ui.fmt
    return [
        {"Document": c["source"], "Fact": c["predicate"], "Now": fmt(c["old"]),
         "Would be": fmt(c["new"]), "Action": c["action"]}
        for c in changes
    ]  # fmt: skip


def render(session: gui_session.Session, box: ui.column) -> None:
    """Draw the workbench for the session's bound level into `box`."""
    OntologyView(session, box).render()
