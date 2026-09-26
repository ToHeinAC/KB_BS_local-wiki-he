"""Evolving an ontology (plan Phase 7): editor tables, cue tester, re-classify, suggestions.

Pure. Every change still goes through the one write path (`ontology_store.prepare_*` →
`apply`, validated and logged):
- the GUI editor turns the state into two tables (local classes, source facts) and the
  edited tables back into a state (`editor_tables` / `state_from_tables`);
- `cue_matches` shows which documents a regex would match, before it is saved;
- re-classify re-derives the *derived* layer: rule facts follow the current cues, user
  decisions are never touched (report §5.6), withdrawn rule facts are retracted;
- a model may *suggest* a new class for an unclassified document; code checks it (new id,
  existing broader class, one-line definition, a cue that compiles and matches the
  document) and it stays a proposal until a maintainer accepts it (report §7.2).
See docs/ontology.md §Evolution.
"""

from __future__ import annotations

import copy
import json
import re
from typing import Any, cast

import ontology
import ontology_detect

CUE_SEP = " || "  # cues in one table cell
_FACT_KEYS = ("class", "work", "version_date")
_ID_RE = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
_JSON_RE = re.compile(r"\{.*?\}", re.DOTALL)


def _map(value: object) -> dict[str, Any]:
    return cast("dict[str, Any]", value) if isinstance(value, dict) else {}


# --- editor tables -------------------------------------------------------------------


def _class_row(cid: str, spec: dict[str, Any]) -> dict[str, Any]:
    labels = _map(spec.get("labels"))
    return {
        "id": cid,
        "broader": spec.get("broader") or "",
        "label_de": labels.get("de", ""),
        "label_en": labels.get("en", ""),
        "definition": spec.get("definition") or "",
        "cues": CUE_SEP.join(str(c) for c in cast("list[Any]", spec.get("cues") or [])),
        "deprecated": bool(spec.get("deprecated")),
        "replaced_by": spec.get("replaced_by") or "",
    }


def editor_tables(
    state: dict[str, Any], sources: list[str]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """(local class rows, one fact row per known source) for `st.data_editor`."""
    local = _map(_map(state.get("schema")).get("local"))
    classes = [_class_row(cid, _map(s)) for cid, s in sorted(_map(local.get("classes")).items())]
    facts = _map(_map(state.get("facts")).get("sources"))
    names = sorted(set(sources) | set(facts))
    rows = [
        {"source": n, **{k: str(_map(facts.get(n)).get(k) or "") for k in _FACT_KEYS}}
        for n in names
    ]
    return classes, rows


def _class_spec(row: dict[str, Any], old: dict[str, Any]) -> dict[str, Any]:
    spec = dict(old)  # keeps fields the table does not show (rank, norm, note, …)
    spec.update(
        broader=str(row.get("broader") or "").strip() or None,
        labels={"de": str(row.get("label_de") or ""), "en": str(row.get("label_en") or "")},
        definition=str(row.get("definition") or ""),
        cues=[c.strip() for c in str(row.get("cues") or "").split(CUE_SEP.strip()) if c.strip()],
        deprecated=bool(row.get("deprecated")),
        replaced_by=str(row.get("replaced_by") or "").strip() or None,
    )
    return spec


def _classes_from_rows(
    rows: list[dict[str, Any]], old: dict[str, Any]
) -> tuple[dict[str, Any], list[str]]:
    classes: dict[str, Any] = {}
    errors: list[str] = []
    for i, row in enumerate(rows, 1):
        cid = str(row.get("id") or "").strip()
        if not cid:
            if any(str(v).strip() for k, v in row.items() if k != "deprecated" and v):
                errors.append(f"class row {i}: `id` is required")
            continue
        classes[cid] = _class_spec(row, _map(old.get(cid)))
    return classes, errors


def state_from_tables(
    state: dict[str, Any], class_rows: list[dict[str, Any]], fact_rows: list[dict[str, Any]]
) -> tuple[dict[str, Any], list[str]]:
    """The state the edited tables describe (other facts and relations are kept)."""
    new = copy.deepcopy(state)
    schema = new.setdefault("schema", {})
    local = schema.setdefault("local", {})
    local["classes"], errors = _classes_from_rows(class_rows, _map(local.get("classes")))
    sources = new.setdefault("facts", {}).setdefault("sources", {})
    for row in fact_rows:
        name = str(row.get("source") or "")
        facts = dict(_map(sources.get(name)))
        for key in _FACT_KEYS:
            value = str(row.get(key) or "").strip()
            if value:
                facts[key] = value
            else:
                facts.pop(key, None)
        sources[name] = facts
    return new, errors


# --- cue tester ------------------------------------------------------------------------


def cue_matches(pattern: str, heads: dict[str, str]) -> tuple[list[tuple[str, str]], str | None]:
    """(source, matched line) for every document whose head ``pattern`` matches."""
    try:
        rx = re.compile(pattern)
    except re.error as exc:
        return [], f"not a valid regex: {exc}"
    if rx.search(""):
        return [], "the pattern matches the empty string (it would match every document)"
    out: list[tuple[str, str]] = []
    for name, text in sorted(heads.items()):
        head = text[: ontology_detect.HEAD_CHARS]
        m = rx.search(head)
        if m:
            start = head.rfind("\n", 0, m.start()) + 1
            end = head.find("\n", m.end())
            out.append((name, head[start : end if end >= 0 else len(head)].strip()))
    return out, None


# --- re-classify -----------------------------------------------------------------------


def _change(
    current: dict[str, Any] | None, new: str | None, evidence: str
) -> dict[str, Any] | None:
    old = current.get("object") if current else None
    if current is not None and current.get("by") == "user":
        return None if old == new else {"action": "kept-user"}
    if old == new:
        return None
    return {"action": "update" if new else "withdraw", "evidence": evidence}


def reclassify_changes(
    heads: dict[str, str], schema: ontology.Schema, rows: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """What re-running detection would change: rule facts that differ from the current
    cues ("update" / "withdraw"), and user decisions it would *not* change ("kept-user")."""
    won = ontology.winners(rows, set())
    changes: list[dict[str, Any]] = []
    for source, text in sorted(heads.items()):
        found = ontology_detect.detect(text, schema)
        for pred, new in (("class", found.class_id), ("work", found.work)):
            current = won.get((f"src:{source}", pred))
            change = _change(current, new, found.evidence)
            if change:
                old = current.get("object") if current else None
                changes.append(
                    {"source": source, "predicate": pred, "old": old, "new": new, **change}
                )
    return changes


def reclassify_rows(
    changes: list[dict[str, Any]], rows: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Ledger rows applying ``changes``: retract the live rule rows, assert the new value.
    User rows are never retracted (their facts win the projection anyway)."""
    live = ontology.live_rows(rows)
    out: list[dict[str, Any]] = []
    for c in changes:
        if c["action"] not in ("update", "withdraw"):
            continue
        subject = f"src:{c['source']}"
        out += [
            ontology.retraction(r, by="rule", reason="re-classify")
            for r in live
            if r.get("subject") == subject
            and r.get("predicate") == c["predicate"]
            and r.get("by") == "rule"
            and r.get("status") == "confirmed"
        ]
        if c["new"]:
            out.append(
                ontology.assertion(
                    subject, c["predicate"], c["new"], by="rule", evidence=c.get("evidence", "")
                )
            )
    return out


# --- class suggestions from the model --------------------------------------------------


def _suggestion_error(item: dict[str, Any], head: str, schema: ontology.Schema) -> str:
    cid, cue = str(item.get("id") or ""), str(item.get("cue") or "")
    definition = str(item.get("definition") or "").strip()
    if not _ID_RE.match(cid):
        return f"invalid id {cid!r}"
    if cid in schema.classes:
        return f"class {cid!r} exists already"
    if item.get("broader") not in schema.classes:
        return f"broader class {item.get('broader')!r} is unknown"
    if not definition or "\n" in definition or len(definition) > ontology.MAX_DEFINITION:
        return "definition must be one line"
    if not (item.get("label_de") and item.get("label_en")):
        return "labels in de and en are required"
    matches, error = cue_matches(cue, {"doc": head})
    if error:
        return f"cue: {error}"
    return "" if matches else "the cue does not match the document"


def parse_class_suggestion(
    answer: str, head: str, schema: ontology.Schema
) -> tuple[dict[str, Any] | None, str]:
    """(proposal, "") for a valid suggested class, else (None, reason)."""
    blob = _JSON_RE.search(answer)
    try:
        item = _map(json.loads(blob[0])) if blob else {}
    except json.JSONDecodeError:
        item = {}
    if not item:
        return None, "the model answered no JSON"
    reason = _suggestion_error(item, head, schema)
    if reason:
        return None, reason
    matched, _ = cue_matches(str(item["cue"]), {"doc": head})
    spec = {
        "broader": item["broader"],
        "labels": {"de": str(item["label_de"]), "en": str(item["label_en"])},
        "definition": str(item["definition"]).strip(),
        "cues": [str(item["cue"])],
    }
    return {"id": item["id"], "spec": spec, "evidence": matched[0][1]}, ""
