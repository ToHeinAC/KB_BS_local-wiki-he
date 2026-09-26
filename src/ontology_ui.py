"""Maintenance → Ontology: view, export, import and history of the active DB's ontology.

Streamlit only; every decision and write goes through `ontology_store` (plans) and
`wiki_engine.apply_ontology` (apply + Activity log). Sub-views use a segmented control,
not `st.tabs`, for the reason in docs/ui.md. See docs/ontology.md §Workbench.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable
from datetime import UTC, date, datetime
from typing import Any

import streamlit as st

import db_context
import dedup
import ontology
import ontology_bundle as bundle
import ontology_detect
import ontology_evolution
import ontology_export
import ontology_query
import ontology_store
import wiki_engine

VIEWS = ["Overview", "Classes", "Facts", "Edit", "Proposals", "Cues", "Lint", "History", "Import"]


def render(user: str, can_maintain: bool) -> None:
    """The whole Ontology section for the active DB."""
    notice = st.session_state.pop("onto_notice", None)
    if notice:
        st.success(notice)
    if not ontology_store.exists():
        _render_missing(user, can_maintain)
        return
    schema, errors = ontology_store.load()
    _render_header(user)
    if errors:
        st.error(
            "**This ontology is invalid.** Nothing uses it until it is fixed "
            "(import a corrected file or restore a revision):\n\n" + _bullets(errors)
        )
    if st.session_state.get("onto_view") not in VIEWS:
        st.session_state["onto_view"] = VIEWS[0]
    view = st.segmented_control(
        "Ontology view", VIEWS, key="onto_view", required=True, label_visibility="collapsed"
    )
    renderers: dict[str, Callable[[], None]] = {
        "Overview": lambda: _render_overview(schema),
        "Classes": lambda: _render_classes(schema),
        "Facts": _render_facts,
        "Edit": lambda: _render_edit(schema, user, can_maintain),
        "Proposals": lambda: _render_proposals(user, can_maintain),
        "Cues": lambda: _render_cues(user, can_maintain),
        "Lint": _render_lint,
        "History": lambda: _render_history(user, can_maintain),
    }
    renderers.get(str(view), lambda: _render_import(user, can_maintain))()


# --- helpers -------------------------------------------------------------------------


def _bullets(items: list[str]) -> str:
    return "\n".join(f"- {i}" for i in items)


def _when(iso: str) -> str:
    return iso[:16].replace("T", " ") + " UTC"


def _fmt(value: object) -> str:
    if value is None:
        return ""
    items = bundle.as_list(value)  # before narrowing: a narrowed list is list[Unknown]
    return ", ".join(str(v) for v in items) if isinstance(value, list) else str(value)


def _change_line(title: str, row: dict[str, Any] | None) -> str:
    if row is None:
        return f"**{title}:** none yet"
    source = f" of `{row['file']}`" if row.get("file") else ""
    who = row.get("user") or "system"
    summary = bundle.summary_text(row["summary"])
    return f"**{title}:** {_when(row['at'])} · {who} · {row['via']}{source} — {summary}"


def _apply(
    plan: bundle.ImportPlan,
    user: str,
    via: str,
    file_name: str | None = None,
    file_sha: str | None = None,
) -> None:
    if plan.status == "unchanged":
        st.info("Identical to the current revision — nothing changed.")
        return
    if plan.status != "ready":
        st.error("**Cannot apply:**\n\n" + _bullets(plan.errors))
        return
    try:
        row = wiki_engine.apply_ontology(
            plan, user=user, via=via, file_name=file_name, file_sha=file_sha
        )
    except (ontology_store.StaleRevisionError, PermissionError) as exc:
        st.error(str(exc))
        return
    st.session_state["onto_notice"] = (
        f"Applied revision {row['seq']}." if row else "Nothing changed."
    )
    st.session_state["onto_upload_n"] = st.session_state.get("onto_upload_n", 0) + 1
    st.rerun()


# --- states and views ------------------------------------------------------------------


def _render_missing(user: str, can_maintain: bool) -> None:
    st.info("No ontology for this database.")
    st.caption(
        "An ontology types this database's documents (classes such as *report* or "
        "*ordinance*) and records facts about them. Start from shared modules, or import "
        "an exported file."
    )
    if not can_maintain:
        st.caption("Only maintainers of this database can create one.")
        return
    options = sorted(ontology_store.available_modules())
    modules = st.multiselect(
        "Modules", options, default=[m for m in ("core",) if m in options], key="onto_modules"
    )
    if st.button("Create ontology", key="onto_create", type="primary", disabled=not modules):
        _apply(ontology_store.prepare_state({"schema": {"modules": modules}}), user, "create")
    st.markdown("**Or import a file**")
    _render_import(user, can_maintain)


def _render_header(user: str) -> None:
    seq, rev = ontology_store.current_revision()
    rows = ontology_store.history()
    unrecorded = bool(rows) and rows[-1]["hash"] != rev
    note = " · *changed since the last recorded revision*" if unrecorded else ""
    open_proposals = len(ontology_store.proposals())
    if open_proposals:
        note += f" · **{open_proposals} open proposal(s)**"
    st.markdown(f"**Revision {seq}** · `{rev}`{note}")
    st.markdown(_change_line("Last change", ontology_store.last_change(human=True)))
    st.markdown(_change_line("Last automatic change", ontology_store.last_change(human=False)))
    db = db_context.get_active_db()
    day = datetime.now(UTC).strftime("%Y%m%d")
    st.download_button(
        "Export current (YAML)",
        data=ontology_store.export_text(user),
        file_name=f"ontology-{db}-rev{seq}-{day}.yaml",
        mime="application/x-yaml",
        key="onto_export",
    )


def _render_overview(schema: ontology.Schema | None) -> None:
    if schema is None:
        return
    facts = ontology_store.current_state()["facts"]
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Classes", len(schema.classes))
    c2.metric("Relations", len(schema.relations))
    c3.metric("Sources with facts", len(facts.get("sources", {})))
    c4.metric("Works", len(facts.get("works", {})))
    st.markdown("**Modules:** " + " · ".join(f"`{m}` {v}" for m, v in schema.modules.items()))
    db = db_context.get_active_db()
    skos, jsonld = st.columns(2)
    skos.download_button(
        "Schema as SKOS (Turtle)",
        ontology_export.skos_turtle(schema),
        file_name=f"ontology-{db}.ttl",
        mime="text/turtle",
        key="onto_skos",
    )
    view = ontology_store.view()
    if view is not None:
        doc = ontology_export.facts_jsonld(view, db=db)
        jsonld.download_button(
            "Facts as JSON-LD",
            json.dumps(doc, indent=2, ensure_ascii=False),
            file_name=f"ontology-{db}.jsonld",
            mime="application/ld+json",
            key="onto_jsonld",
        )


def _class_usage() -> dict[str, int]:
    usage: dict[str, int] = {}
    for section in ontology_store.current_state()["facts"].values():
        for facts in section.values():
            cls = facts.get("class")
            if isinstance(cls, str):
                usage[cls] = usage.get(cls, 0) + 1
    return usage


def _class_line(c: ontology.ClassDef, used: int) -> str:
    parts = [f"**{c.labels.get('de', c.id)}** / {c.labels.get('en', c.id)} `{c.id}`"]
    if c.rank is not None:
        parts.append(f"rank {c.rank}")
    if c.module == ontology.LOCAL_ID:
        parts.append("*local*")
    if c.deprecated:
        parts.append(f"deprecated → `{c.replaced_by}`")
    if used:
        parts.append(f"{used} fact(s)")
    return " · ".join(parts)


def _render_classes(schema: ontology.Schema | None) -> None:
    if schema is None:
        st.info("Fix the errors above to see the classes.")
        return
    children: dict[str | None, list[str]] = {}
    for c in schema.classes.values():
        children.setdefault(c.broader, []).append(c.id)
    usage, lines = _class_usage(), list[str]()

    def walk(parent: str | None, depth: int) -> None:
        for cid in sorted(children.get(parent, [])):
            lines.append("  " * depth + "- " + _class_line(schema.classes[cid], usage.get(cid, 0)))
            walk(cid, depth + 1)

    walk(None, 0)
    st.markdown("\n".join(lines))
    st.dataframe(
        [
            {
                "Relation": r.id,
                "Domain": ", ".join(r.domain),
                "Range": ", ".join(r.range),
                "Inverse": r.inverse or "",
                "Target": r.target,
                "Module": r.module,
            }
            for r in schema.relations.values()
        ],
        hide_index=True,
        width="stretch",
    )


def _render_facts() -> None:
    facts = ontology_store.current_state()["facts"]
    rows = [
        {
            "Kind": section,
            "Subject": key,
            "Class": _fmt(values.get("class")),
            "Work": _fmt(values.get("work")),
            "Other": "; ".join(
                f"{p} = {_fmt(v)}" for p, v in values.items() if p not in ("class", "work")
            ),
        }
        for section, entries in facts.items()
        for key, values in entries.items()
    ]
    if not rows:
        st.info("No facts yet. Add them by exporting, editing `facts:` and importing the file.")
        return
    st.dataframe(rows, hide_index=True, width="stretch")


def _diff_table(changes: list[dict[str, Any]]) -> None:
    st.dataframe(
        [
            {
                "Item": bundle.label(c["path"]),
                "Change": c["op"],
                "Before": _fmt(c.get("from")),
                "After": _fmt(c.get("to")),
            }
            for c in changes
        ],
        hide_index=True,
        width="stretch",
    )


def _render_history(user: str, can_maintain: bool) -> None:
    rows = list(reversed(ontology_store.history()))
    if not rows:
        st.info("No revisions recorded yet.")
        return
    st.dataframe(
        [
            {
                "Rev": r["seq"],
                "When": _when(r["at"]),
                "Who": r.get("user") or "system",
                "Via": r["via"],
                "File": r.get("file") or "",
                "Changes": bundle.summary_text(r["summary"]),
            }
            for r in rows
        ],
        hide_index=True,
        width="stretch",
    )
    picked = st.selectbox("Revision", [r["seq"] for r in rows], key="onto_hist_rev")
    row = next((r for r in rows if r["seq"] == picked), rows[0])
    seq: int = row["seq"]
    _diff_table(row.get("diff") or [])
    text = ontology_store.snapshot_text(seq)
    if text:
        db = db_context.get_active_db()
        name = f"ontology-{db}-rev{seq}.yaml"
        st.download_button(f"Download revision {seq}", text, file_name=name, key="onto_hist_dl")
    if can_maintain and seq != rows[0]["seq"]:
        ok = st.checkbox(f"Restore revision {seq} as a new revision", key="onto_restore_ok")
        if st.button("Restore", key="onto_restore", disabled=not ok):
            _apply(ontology_store.prepare_restore(seq), user, "restore", f"revision {seq}")


def _conflict_choices(conflicts: list[dict[str, Any]]) -> dict[str, str]:
    if not conflicts:
        return {}
    st.warning(
        f"**{len(conflicts)} conflict(s):** these items changed both in your file and in "
        "the database since your export. The default keeps the current value."
    )
    choices: dict[str, str] = {}
    for i, c in enumerate(conflicts):
        pick = st.radio(
            f"{c['path']} — current: `{_fmt(c['current'])}`, yours: `{_fmt(c['mine'])}`",
            ["Keep current", "Use mine"],
            key=f"onto_conflict_{i}",
            horizontal=True,
        )
        if pick == "Use mine":
            choices[c["path"]] = "mine"
    return choices


def _render_plan(plan: bundle.ImportPlan) -> None:
    for warning in plan.warnings:
        st.warning(warning)
    if plan.status == "error":
        st.error("**The file cannot be imported:**\n\n" + _bullets(plan.errors))
    elif plan.status == "unchanged":
        seq, _ = ontology_store.current_revision()
        st.info(f"Identical to revision {seq} — nothing changed.")
    else:
        summary = bundle.summary_text(plan.summary)
        st.markdown(f"**Preview:** {summary} · local schema version {plan.local_version}")
        _diff_table(plan.changes)


def _render_import(user: str, can_maintain: bool) -> None:
    n = st.session_state.get("onto_upload_n", 0)
    upload = st.file_uploader(
        "Edited ontology file (YAML)", type=["yaml", "yml"], key=f"onto_upload_{n}"
    )
    if upload is None:
        st.caption("Export, edit, upload. Nothing is written before you confirm the preview.")
        return
    data = upload.getvalue()
    text = data.decode("utf-8", errors="replace")
    other = st.checkbox("This file comes from another database", key="onto_other_db")
    plan = ontology_store.prepare_import(text, allow_other_db=other)
    choices = _conflict_choices(plan.conflicts)
    if choices:
        plan = ontology_store.prepare_import(text, resolutions=choices, allow_other_db=other)
    _render_plan(plan)
    if plan.status != "ready":
        return
    if not can_maintain:
        st.info("Only maintainers of this database can apply an import.")
    elif st.button("Apply import", key="onto_apply", type="primary"):
        sha = hashlib.sha256(data).hexdigest()
        _apply(plan, user, "import", upload.name, sha)


# --- proposals (plan Phase 3) ----------------------------------------------------------


def _decide(row_id: str, accept: bool, user: str) -> None:
    try:
        row = wiki_engine.decide_proposal(row_id, accept=accept, user=user)
    except (KeyError, PermissionError, ontology_store.StaleRevisionError) as exc:
        st.error(str(exc))
        return
    st.session_state["onto_notice"] = (
        f"Confirmed — revision {row['seq']}." if row else "Proposal rejected."
    )
    st.rerun()


def _render_proposals(user: str, can_maintain: bool) -> None:
    rows = ontology_store.proposals()
    if not rows:
        st.info("No open fact proposals.")
    else:
        _render_fact_proposals(rows, user, can_maintain)
    _render_suggestions(user, can_maintain)


def _render_fact_proposals(rows: list[dict[str, Any]], user: str, can_maintain: bool) -> None:
    st.caption(
        "Suggested by the model when no cue matched. Each quote was checked to occur "
        "verbatim in the document. Confirm to make it a fact, or reject it."
    )
    for r in rows:
        subject = str(r["subject"]).split(":", 1)[1]
        with st.container(border=True):
            attrs = ", ".join(f"{k}={v}" for k, v in bundle.as_map(r.get("attributes")).items())
            suffix = f" ({attrs})" if attrs else ""
            st.markdown(f"**{subject}** · `{r['predicate']}` = `{r['object']}`{suffix}")
            st.caption(f"“{r.get('evidence') or ''}”")
            if can_maintain:
                ok, no = st.columns(2)
                if ok.button("Confirm", key=f"onto_ok_{r['id']}"):
                    _decide(r["id"], True, user)
                if no.button("Reject", key=f"onto_no_{r['id']}"):
                    _decide(r["id"], False, user)


# --- upload review table (plan Phase 3) --------------------------------------------------


def upload_schema() -> ontology.Schema | None:
    """The active DB's schema when it has a valid ontology, else None (no extra columns)."""
    if not ontology_store.exists():
        return None
    schema, _ = ontology_store.load()
    return schema


def detected(text: str, version_date: str, schema: ontology.Schema) -> dict[str, Any]:
    return ontology_detect.detected_dict(ontology_detect.detect(text, schema), version_date)


def review_rows(rows: list[dict[str, Any]], prepared: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The date rows plus prefilled Class / Work and the sources already filed under
    that work (read-only)."""
    by_work: dict[str, list[str]] = {}
    for source, facts in ontology_store.current_state()["facts"].get("sources", {}).items():
        if facts.get("work"):
            by_work.setdefault(str(facts["work"]), []).append(source)
    out: list[dict[str, Any]] = []
    for row, f in zip(rows, prepared, strict=True):
        det = bundle.as_map(f.get("ontology"))
        others = ", ".join(sorted(by_work.get(det.get("work", ""), [])))
        out.append(
            {
                **row,
                "Class": det.get("class", ""),
                "Work": det.get("work", ""),
                "Other versions": others,
            }
        )
    return out


def review_column_config(schema: ontology.Schema) -> dict[str, Any]:
    options = ["", *sorted(cid for cid, c in schema.classes.items() if not c.deprecated)]
    return {
        "Class": st.column_config.SelectboxColumn("Class", options=options),
        "Work": st.column_config.TextColumn("Work id"),
        "Other versions": st.column_config.TextColumn("Other versions in this DB"),
    }


def source_badge(ref: str) -> str:
    """Version/validity line for a cited document (e.g. under chat answers); "" without
    an ontology or facts. Judged at today, as the answer is read now."""
    db, name = db_context.split_ref(ref)
    name = re.sub(r"\s*[§#].*$", "", name)  # "doc.md §1" cites a section of doc.md
    with db_context.using_db(db):
        view = ontology_store.view()
    return ontology_query.badge(view, name, date.today()) if view is not None else ""


def _render_lint() -> None:
    """Deterministic consistency findings (docs/ontology.md §Relations)."""
    findings = wiki_engine.ontology_lint()
    if not findings:
        st.success("No findings: no cycles, rank or date problems, nothing missing.")
        return
    st.caption("Ranks only order and warn; they never decide a legal conflict.")
    for f in findings:
        (st.warning if f["level"] == "warning" else st.info)(f["message"])


# --- evolution (plan Phase 7) -----------------------------------------------------------

_CLASS_BLANK = {
    "id": "",
    "broader": "",
    "label_de": "",
    "label_en": "",
    "definition": "",
    "cues": "",
    "deprecated": False,
    "replaced_by": "",
}


def _edited_tables(
    schema: ontology.Schema, state: dict[str, Any]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    classes, facts = ontology_evolution.editor_tables(state, dedup.list_sources())
    st.markdown("**Local classes** — shared modules change via git.")
    st.caption(f"Several cues in one cell: separate them with `{ontology_evolution.CUE_SEP}`.")
    edited_classes: list[dict[str, Any]] = st.data_editor(
        classes or [dict(_CLASS_BLANK)],
        key="onto_edit_classes",
        num_rows="dynamic",
        hide_index=True,
        width="stretch",
        column_config={"deprecated": st.column_config.CheckboxColumn("deprecated")},
    )
    ids = sorted({*schema.classes, *(str(r.get("id") or "") for r in edited_classes)} - {""})
    st.markdown("**Facts per document** — relations and aliases: use export / import.")
    edited_facts: list[dict[str, Any]] = st.data_editor(
        facts,
        key="onto_edit_facts",
        hide_index=True,
        width="stretch",
        disabled=["source"],
        column_config={"class": st.column_config.SelectboxColumn("class", options=["", *ids])},
    )
    return list(edited_classes), list(edited_facts)


def _render_edit(schema: ontology.Schema | None, user: str, can_maintain: bool) -> None:
    """Edit local classes and document facts in tables; same validation and log as import."""
    if schema is None or not can_maintain:
        st.info("Editing needs a valid ontology and maintainer rights for this database.")
        return
    state = ontology_store.current_state()
    classes, facts = _edited_tables(schema, state)
    new, errors = ontology_evolution.state_from_tables(state, classes, facts)
    if errors:
        st.error("**Fix the tables first:**\n\n" + _bullets(errors))
        return
    plan = ontology_store.prepare_state(new)
    _render_plan(plan)
    if plan.status == "ready" and st.button("Apply changes", key="onto_edit_apply", type="primary"):
        _apply(plan, user, "editor")


def _render_cue_tester(heads: dict[str, str]) -> None:
    pattern = st.text_input("Test a cue (regular expression)", key="onto_cue")
    if not pattern:
        st.caption("Shows which documents a cue would match, before you save it.")
        return
    matches, error = ontology_evolution.cue_matches(pattern, heads)
    if error:
        st.error(error)
        return
    st.markdown(f"**Matches {len(matches)} of {len(heads)} documents**")
    if matches:
        rows = [{"Document": name, "Line": line} for name, line in matches]
        st.dataframe(rows, hide_index=True, width="stretch")


def _render_cues(user: str, can_maintain: bool) -> None:
    _render_cue_tester(ontology_store.source_heads())
    st.markdown("**Re-classify**")
    st.caption(
        "Re-runs detection with the current cues. Facts made by code follow the cues; "
        "your own decisions are never changed (they are listed as kept)."
    )
    changes, _ = wiki_engine.reclassify(user, apply=False)
    if not changes:
        st.success("Every document already matches the current cues.")
        return
    st.dataframe(
        [
            {
                "Document": c["source"],
                "Fact": c["predicate"],
                "Now": _fmt(c["old"]),
                "Would be": _fmt(c["new"]),
                "Action": c["action"],
            }
            for c in changes
        ],
        hide_index=True,
        width="stretch",
    )
    applicable = any(c["action"] in ("update", "withdraw") for c in changes)
    if can_maintain and applicable and st.button("Apply re-classify", key="onto_reclassify"):
        _, row = wiki_engine.reclassify(user, apply=True)
        st.session_state["onto_notice"] = (
            f"Re-classified — revision {row['seq']}." if row else "Nothing changed."
        )
        st.rerun()


def _decide_schema(pid: str, accept: bool, user: str) -> None:
    try:
        row = wiki_engine.decide_schema_proposal(pid, accept=accept, user=user)
    except (KeyError, PermissionError, ValueError, ontology_store.StaleRevisionError) as exc:
        st.error(str(exc))
        return
    st.session_state["onto_notice"] = (
        f"Class added — revision {row['seq']}." if row else "Suggestion rejected."
    )
    st.rerun()


def _render_suggestion(p: dict[str, Any], user: str, can_maintain: bool) -> None:
    spec = p["spec"]
    with st.container(border=True):
        st.markdown(
            f"**{p['class_id']}** under `{spec['broader']}` for `{p['source']}` — "
            f"{spec['labels']['de']} / {spec['labels']['en']}: {spec['definition']}"
        )
        st.caption(f"cue `{spec['cues'][0]}` matches: “{p.get('evidence', '')}”")
        if can_maintain:
            ok, no = st.columns(2)
            if ok.button("Accept", key=f"onto_sok_{p['id']}"):
                _decide_schema(p["id"], True, user)
            if no.button("Reject", key=f"onto_sno_{p['id']}"):
                _decide_schema(p["id"], False, user)


def _render_suggestions(user: str, can_maintain: bool) -> None:
    st.markdown("**New class suggestions**")
    for p in ontology_store.schema_proposals():
        _render_suggestion(p, user, can_maintain)
    facts = ontology_store.current_state()["facts"].get("sources", {})
    unclassified = [s for s in dedup.list_sources() if not facts.get(s, {}).get("class")]
    if not unclassified or not can_maintain:
        st.caption("Every document has a class." if not unclassified else "")
        return
    source = st.selectbox("Unclassified document", unclassified, key="onto_unclassified")
    if st.button("Ask the model for a new class", key="onto_suggest"):
        result = wiki_engine.suggest_class(str(source), user=user)
        if isinstance(result, str):
            st.warning(f"No suggestion: {result}")
            return
        st.session_state["onto_notice"] = f"Suggestion {result['class_id']} added for review."
        st.rerun()
