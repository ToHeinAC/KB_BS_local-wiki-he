"""Ontology exchange file: render, parse, canonical form, diff, 3-way merge, import plans.

Pure (no I/O). A DB's editable ontology *state* is
``{"schema": <binding: modules + local extension>, "facts": {"sources"|"works"|"pages":
{key: {predicate: value}}}}``. Two states are the same ontology exactly when their
canonical forms hash the same: comments, key order, formatting, quoting, duplicates in
set-like lists, export metadata and the code-owned `local.version` are not changes.
`plan_import` turns an edited file into a validated, previewable plan; the store applies
it. See docs/ontology.md §Workbench.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, cast

import yaml

import ontology

FORMAT = "localwiki-ontology/1"
MAX_BYTES = 2_000_000
SECTIONS = {"sources": "src:", "works": "work:", "pages": "page:"}
DATES = {"version_date", "in_force_from", "applicable_from", "in_force_until"}
TEXTS = {"label", "note"}
IN_FORCE = ("in-force", "not-in-force", "partially-in-force")
DEFAULT_LOCAL_VERSION = "0.1.0"
SEP = " > "

_TOP_KEYS = {
    "format",
    "db",
    "revision",
    "base_revision",
    "exported_at",
    "exported_by",
    "schema",
    "facts",
    "reference",
}
_STRUCTURAL = {"broader", "domain", "range", "inverse", "target", "transitive", "deprecated"}
_WORK_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_MISSING = object()
_HEADER = """\
# LocalWiki ontology export.
# Edit `schema` (bound modules, `local` classes/relations) and `facts`, then import the file
# in Maintenance -> Ontology. `reference` shows the shared modules and is ignored on import
# (they change via git). Comments are not kept; use a `note:` field instead.
# `local.version` is set by code. Keep `base_revision`: it lets the import merge your edits
# with changes made since this export.
"""


@dataclass
class ImportPlan:
    status: str  # "error" | "unchanged" | "ready"
    errors: list[str] = field(default_factory=lambda: [])
    warnings: list[str] = field(default_factory=lambda: [])
    conflicts: list[dict[str, Any]] = field(default_factory=lambda: [])
    changes: list[dict[str, Any]] = field(default_factory=lambda: [])
    summary: dict[str, dict[str, int]] = field(default_factory=lambda: {})
    state: dict[str, Any] = field(default_factory=lambda: {})
    current_hash: str = ""
    new_hash: str = ""
    local_version: str = DEFAULT_LOCAL_VERSION


def as_map(value: object) -> dict[str, Any]:
    """``value`` if it is a mapping, else {} (for untrusted, hand-edited YAML)."""
    return cast("dict[str, Any]", value) if isinstance(value, dict) else {}


def as_list(value: object) -> list[Any]:
    """``value`` if it is a list, else []."""
    return cast("list[Any]", value) if isinstance(value, list) else []


def label(path: list[str] | tuple[str, ...]) -> str:
    return SEP.join(path)


# --- canonical form ----------------------------------------------------------------


def _empty(value: object) -> bool:
    return value is None or value is False or value in ("", [], {})


def _canon_list(items: list[Any]) -> list[Any]:
    values = [v for v in (_canon(i) for i in items) if not _empty(v)]
    if any(isinstance(v, dict | list) for v in values):
        return values
    unique = {json.dumps(v, sort_keys=True): v for v in values}
    return [unique[k] for k in sorted(unique)]


def _canon(value: object) -> Any:
    if isinstance(value, dict):
        items = {str(k): _canon(v) for k, v in cast("dict[Any, Any]", value).items()}
        return {k: items[k] for k in sorted(items) if not _empty(items[k])}
    if isinstance(value, list):
        return _canon_list(cast("list[Any]", value))
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return value


def canonical(state: object) -> dict[str, Any]:
    """The semantic content of a state: schema binding (minus `local.version`) + facts."""
    s = as_map(state)
    schema = as_map(s.get("schema"))
    local = {k: v for k, v in as_map(schema.get("local")).items() if k != "version"}
    core = {"schema": {"modules": schema.get("modules"), "local": local}, "facts": s.get("facts")}
    return cast("dict[str, Any]", _canon(core))


def revision_hash(state: object) -> str:
    blob = json.dumps(canonical(state), sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:12]


def local_version(state: object) -> str:
    version = as_map(as_map(as_map(state).get("schema")).get("local")).get("version")
    return version if isinstance(version, str) else DEFAULT_LOCAL_VERSION


def facts_state(projection: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Ledger projection ``{"src:a.md": {...}}`` → state facts ``{"sources": {"a.md": ...}}``."""
    out: dict[str, dict[str, Any]] = {}
    for subject, facts in projection.items():
        for section, prefix in SECTIONS.items():
            if subject.startswith(prefix):
                out.setdefault(section, {})[subject[len(prefix) :]] = facts
    return out


# --- render / parse ----------------------------------------------------------------


class _NoAliasDumper(yaml.SafeDumper):
    def ignore_aliases(self, data: Any) -> bool:
        return True


def render(
    state: object,
    *,
    db: str,
    revision: str,
    user: str | None,
    exported_at: str,
    reference: dict[str, Any] | None = None,
) -> str:
    """The exchange file for ``state`` (plain YAML, no anchors)."""
    c = canonical(state)
    schema = as_map(c.get("schema"))
    local = {"version": local_version(state), **as_map(schema.get("local"))}
    doc: dict[str, Any] = {
        "format": FORMAT,
        "db": db,
        "base_revision": revision,
        "exported_at": exported_at,
        "exported_by": user,
        "schema": {"modules": schema.get("modules", []), "local": local},
        "facts": c.get("facts", {}),
        "reference": reference or {},
    }
    return _HEADER + dump_yaml(doc)


def dump_yaml(data: object) -> str:
    """Plain block YAML in the given key order, without anchors/aliases."""
    return yaml.dump(data, Dumper=_NoAliasDumper, sort_keys=False, allow_unicode=True, width=100)


def _alias_errors(text: str) -> list[str]:
    try:
        events: list[object] = list(yaml.parse(text, Loader=yaml.SafeLoader))  # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType]
    except yaml.YAMLError:
        return []  # parse_yaml reports the syntax error with its position
    if any(isinstance(e, yaml.AliasEvent) for e in events):
        return ["YAML anchors/aliases (& and *) are not supported in ontology files"]
    return []


def _header_errors(doc: dict[str, Any], db: str, allow_other_db: bool) -> list[str]:
    errors = [f"unknown top-level key {k!r}" for k in doc if k not in _TOP_KEYS]
    if doc.get("format") != FORMAT:
        errors.append(f"`format` must be {FORMAT!r} (is this an ontology export?)")
    if doc.get("db") != db and not allow_other_db:
        errors.append(f"the file is for database {doc.get('db')!r}, not {db!r}")
    for key in ("schema", "facts"):
        if not isinstance(doc.get(key, {}), dict):
            errors.append(f"`{key}` must be a mapping")
    return errors


def parse(
    text: str, *, db: str, allow_other_db: bool = False
) -> tuple[dict[str, Any] | None, str | None, list[str]]:
    """(state, base_revision, errors) of an exchange file; state is None on any error."""
    if len(text.encode("utf-8")) > MAX_BYTES:
        return None, None, [f"file is larger than {MAX_BYTES // 1_000_000} MB"]
    errors = _alias_errors(text)
    data, parse_errors = ontology.parse_yaml(text)
    errors += parse_errors
    if errors:
        return None, None, errors
    if not isinstance(data, dict):
        return None, None, ["the file must be a YAML mapping (an ontology export)"]
    doc = cast("dict[str, Any]", data)
    errors = _header_errors(doc, db, allow_other_db)
    if errors:
        return None, None, errors
    base = doc.get("base_revision")
    state: dict[str, Any] = {"schema": as_map(doc.get("schema")), "facts": as_map(doc.get("facts"))}
    return state, base if isinstance(base, str) else None, []


# --- flatten / diff / merge --------------------------------------------------------


def flatten(value: object, prefix: tuple[str, ...] = ()) -> dict[tuple[str, ...], Any]:
    """Leaf paths of a nested mapping; lists are leaves (they are canonical sets)."""
    if not isinstance(value, dict) or not value:
        return {prefix: value} if prefix else {}
    out: dict[tuple[str, ...], Any] = {}
    for k, v in cast("dict[str, Any]", value).items():
        out.update(flatten(v, (*prefix, k)))
    return out


def unflatten(flat: dict[tuple[str, ...], Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for path, value in sorted(flat.items()):
        node = out
        for key in path[:-1]:
            child = node.get(key)
            if not isinstance(child, dict):
                child = node[key] = {}
            node = cast("dict[str, Any]", child)
        node[path[-1]] = value
    return out


def diff(old: object, new: object) -> list[dict[str, Any]]:
    """Leaf-level changes between two states, in path order."""
    a, b = flatten(canonical(old)), flatten(canonical(new))
    changes: list[dict[str, Any]] = []
    for path in sorted(a.keys() | b.keys()):
        if path not in b:
            changes.append({"path": list(path), "op": "remove", "from": a[path]})
        elif path not in a:
            changes.append({"path": list(path), "op": "add", "to": b[path]})
        elif a[path] != b[path]:
            changes.append({"path": list(path), "op": "change", "from": a[path], "to": b[path]})
    return changes


def _entity(path: tuple[str, ...]) -> tuple[str, tuple[str, ...]]:
    """(area, entity) a leaf belongs to: a module list, a local class/relation, a fact subject."""
    if path[0] == "schema":
        return "schema", path[:4] if path[1:2] == ("local",) else path[:2]
    return "facts", path[:3]


def summarize(old: object, new: object) -> dict[str, dict[str, int]]:
    """Entity-level counts: {"schema"|"facts": {"added", "changed", "removed"}}."""
    a, b = flatten(canonical(old)), flatten(canonical(new))
    before = {_entity(p) for p in a}
    after = {_entity(p) for p in b}
    touched = {_entity(p) for p in a.keys() | b.keys() if a.get(p, _MISSING) != b.get(p, _MISSING)}
    out = {area: {"added": 0, "changed": 0, "removed": 0} for area in ("schema", "facts")}
    for area, entity in touched:
        key = (area, entity)
        op = "added" if key not in before else "removed" if key not in after else "changed"
        out[area][op] += 1
    return out


def _show(value: object) -> Any:
    return "(absent)" if value is _MISSING else value


def merge3(
    base: object, mine: object, current: object, resolutions: dict[str, str] | None = None
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Apply mine's edits (relative to base) onto current. A leaf both sides changed
    differently is a conflict: current wins unless ``resolutions[label] == "mine"``."""
    fb, fm, ft = (flatten(canonical(s)) for s in (base, mine, current))
    merged = dict(ft)
    conflicts: list[dict[str, Any]] = []
    for path in sorted(fb.keys() | fm.keys()):
        b, m, t = fb.get(path, _MISSING), fm.get(path, _MISSING), ft.get(path, _MISSING)
        if b == m:
            continue
        if t not in (b, m):
            name = label(path)
            conflicts.append(
                {"path": name, "base": _show(b), "mine": _show(m), "current": _show(t)}
            )
            if (resolutions or {}).get(name) != "mine":
                continue
        if m is _MISSING:
            merged.pop(path, None)
        else:
            merged[path] = m
    return unflatten(merged), conflicts


# --- versions ----------------------------------------------------------------------


def _ids(local: dict[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
    return {
        (kind, item_id): as_map(spec)
        for kind in ("classes", "relations")
        for item_id, spec in as_map(local.get(kind)).items()
    }


def bump(version: str, old_local: object, new_local: object) -> str:
    """SemVer bump of the local extension: patch = text/cues, minor = new ids,
    major = removed ids or structural changes (re-parenting, domain/range, …)."""
    m = re.match(r"^(\d+)\.(\d+)\.(\d+)$", version)
    major, minor, patch = (int(m[1]), int(m[2]), int(m[3])) if m else (0, 1, 0)
    old, new = _ids(as_map(_canon(old_local))), _ids(as_map(_canon(new_local)))
    if old == new:
        return version
    common = old.keys() & new.keys()
    structural = any(old[i].get(k) != new[i].get(k) for i in common for k in _STRUCTURAL)
    if old.keys() - new.keys() or structural:
        return f"{major + 1}.0.0"
    if new.keys() - old.keys():
        return f"{major}.{minor + 1}.0"
    return f"{major}.{minor}.{patch + 1}"


# --- validation ----------------------------------------------------------------------


def schema_for(state: object, shared: dict[str, Any]) -> tuple[ontology.Schema | None, list[str]]:
    """Build the schema a state binds: its shared modules + its local extension."""
    ids, local, errors = ontology.read_binding(as_map(state).get("schema"), set(shared))
    if errors:
        return None, errors
    return ontology.build_schema([shared[i] for i in ids] + ([local] if local else []))


def _is_date(value: object) -> bool:
    if not (isinstance(value, str) and _DATE_RE.match(value)):
        return False
    try:
        date.fromisoformat(value)
    except ValueError:
        return False
    return True


def _value_error(pred: str, value: object, schema: ontology.Schema) -> str | None:
    """Why ``value`` is not allowed for a single-valued predicate, or None."""
    if pred == "class":
        return None if value in schema.classes else f"unknown class {value!r}"
    if pred == "work":
        ok = isinstance(value, str) and _WORK_ID_RE.match(value)
        return None if ok else f"`work` must be a lowercase work id, got {value!r}"
    if pred in DATES:
        return None if _is_date(value) else f"`{pred}` must be a date YYYY-MM-DD, got {value!r}"
    if pred == "in_force":
        return None if value in IN_FORCE else f"`in_force` must be one of {IN_FORCE}"
    if pred in TEXTS:
        return None if isinstance(value, str) else f"`{pred}` must be text"
    return f"unknown predicate {pred!r}"


def _list_error(pred: str, value: object, schema: ontology.Schema) -> str | None:
    if pred not in schema.multi_valued():
        return None
    items = cast("list[Any]", value) if isinstance(value, list) else None
    if items is None or not all(isinstance(v, str) for v in items):
        return f"`{pred}` must be a list of ids"
    return None


def _subject_issues(
    where: str, facts: dict[str, Any], schema: ontology.Schema, works: set[str]
) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    for pred, value in facts.items():
        if pred in schema.multi_valued():
            err = _list_error(pred, value, schema)
            if err is None and pred in schema.relations:
                missing = [w for w in cast("list[str]", value) if w not in works]
                warnings += [f"{where}: `{pred}` target {w!r} is not a known work" for w in missing]
        else:
            err = _value_error(pred, value, schema)
        if err:
            errors.append(f"{where}: {err}")
    return errors, warnings


def validate_facts(
    facts: object, schema: ontology.Schema, known_sources: set[str]
) -> tuple[list[str], list[str]]:
    """(errors, warnings) for state facts; a dangling relation target is only a warning."""
    sections = as_map(facts)
    works = set(as_map(sections.get("works")))
    errors = [f"facts: unknown section {s!r}" for s in sections if s not in SECTIONS]
    warnings: list[str] = []
    for section in SECTIONS:
        for key, subject_facts in as_map(sections.get(section)).items():
            where = f"facts > {section} > {key}"
            if section == "sources" and key not in known_sources:
                errors.append(f"{where}: unknown source (not in this database)")
            elif section == "works" and not _WORK_ID_RE.match(key):
                errors.append(f"{where}: invalid work id")
            errs, warns = _subject_issues(where, as_map(subject_facts), schema, works)
            errors += errs
            warnings += warns
    return errors, warnings


def migrate_deprecated(
    state: dict[str, Any], schema: ontology.Schema
) -> tuple[dict[str, Any], list[str]]:
    """Point `class` facts at `replaced_by` when their class is deprecated."""
    out = copy.deepcopy(state)
    warnings: list[str] = []
    for section in SECTIONS:
        for key, facts in as_map(as_map(out.get("facts")).get(section)).items():
            cls = schema.classes.get(str(as_map(facts).get("class")))
            if cls is not None and cls.deprecated and cls.replaced_by:
                facts["class"] = cls.replaced_by
                warnings.append(
                    f"facts > {section} > {key}: class {cls.id!r} is deprecated, "
                    f"migrated to {cls.replaced_by!r}"
                )
    return out, warnings


def _removed_errors(current: object, merged: object, referenced: set[str]) -> list[str]:
    def local_ids(state: object) -> set[tuple[str, str]]:
        return set(_ids(as_map(as_map(as_map(state).get("schema")).get("local"))))

    return [
        f"{kind[:-2] if kind == 'classes' else 'relation'} {item_id!r} is used by ledger facts; "
        "mark it `deprecated: true` with `replaced_by` instead of removing it"
        for kind, item_id in sorted(local_ids(current) - local_ids(merged))
        if item_id in referenced
    ]


# --- import plan ---------------------------------------------------------------------


def _validate(
    merged: dict[str, Any], current: object, shared: dict[str, Any], known: set[str],
    referenced: set[str],
) -> tuple[dict[str, Any], list[str], list[str]]:  # fmt: skip
    schema, errors = schema_for(merged, shared)
    if schema is None:
        return merged, errors, []
    merged, warnings = migrate_deprecated(merged, schema)
    fact_errors, fact_warnings = validate_facts(merged.get("facts"), schema, known)
    errors = fact_errors + _removed_errors(current, merged, referenced)
    return merged, errors, warnings + fact_warnings


def plan_import(
    imported: object,
    *,
    base: object | None,
    current: object,
    shared: dict[str, Any],
    known_sources: set[str],
    referenced: set[str],
    resolutions: dict[str, str] | None = None,
) -> ImportPlan:
    """Merge ``imported`` onto ``current`` (3-way against ``base``; 2-way when None),
    validate the result and describe it. Writes nothing."""
    warnings: list[str] = []
    if base is None:
        warnings.append(
            "No matching base revision: the file is compared with the current revision "
            "only, so edits made since your export may be undone."
        )
        base = current
    merged, conflicts = merge3(base, imported, current, resolutions)
    plan = ImportPlan("unchanged", current_hash=revision_hash(current), conflicts=conflicts)
    merged, errors, more_warnings = _validate(merged, current, shared, known_sources, referenced)
    plan.warnings = warnings + more_warnings
    plan.new_hash = revision_hash(merged)
    if plan.new_hash == plan.current_hash:
        return plan
    old_local = as_map(as_map(current).get("schema")).get("local")
    plan.local_version = bump(local_version(current), old_local, merged["schema"].get("local"))
    if as_map(merged["schema"].get("local")):
        merged["schema"]["local"]["version"] = plan.local_version
    plan.state, plan.errors = merged, errors
    plan.changes, plan.summary = diff(current, merged), summarize(current, merged)
    plan.status = "error" if errors else "ready"
    return plan


# --- ledger rows and log line ------------------------------------------------------


def fact_rows(old: object, new: object, *, user: str, evidence: str) -> list[dict[str, Any]]:
    """User ledger rows that turn facts ``old`` into ``new`` (list values per member)."""
    rows: list[dict[str, Any]] = []
    a, b = as_map(old), as_map(new)
    for section, prefix in SECTIONS.items():
        sa, sb = as_map(a.get(section)), as_map(b.get(section))
        for key in sorted(sa.keys() | sb.keys()):
            fa, fb = as_map(sa.get(key)), as_map(sb.get(key))
            for pred in sorted(fa.keys() | fb.keys()):
                rows += _pred_rows(prefix + key, pred, fa.get(pred), fb.get(pred), user, evidence)
    return rows


def _pred_rows(
    subject: str, pred: str, old: object, new: object, user: str, evidence: str
) -> list[dict[str, Any]]:
    def row(obj: object, negated: bool = False) -> dict[str, Any]:
        return ontology.assertion(
            subject, pred, obj, by="user", user=user, evidence=evidence, negated=negated
        )

    if old == new:
        return []
    if isinstance(old, list) or isinstance(new, list):
        before = set(cast("list[Any]", old or []))
        after = set(cast("list[Any]", new or []))
        added = [row(v) for v in sorted(after - before, key=str)]
        return added + [row(v, negated=True) for v in sorted(before - after, key=str)]
    return [row(new)]


def summary_text(summary: dict[str, dict[str, int]]) -> str:
    return ", ".join(
        f"{area} +{c['added']} ~{c['changed']} −{c['removed']}" for area, c in summary.items()
    )


def log_line(row: dict[str, Any]) -> str:
    """One Activity-log line for a change row."""
    source = f" ({row['file']})" if row.get("file") else ""
    who = row.get("user") or "system"
    return f"rev {row['seq']} by {who} via {row['via']}{source}: {summary_text(row['summary'])}"
