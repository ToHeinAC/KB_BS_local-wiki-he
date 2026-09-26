"""Ontology core: schema modules, their validation and merge, and the fact ledger's projection.

Pure: no file, network or LLM access (`ontology_store` does the I/O). The schema
(classes, relations) comes from SKOS-like YAML modules — shared ones in `ontology/`
plus an optional DB-local extension — and is only accepted when every meta-rule
holds. Facts are append-only ledger rows; `project()` derives their current values
with the precedence user > rule > llm, so user decisions are sticky.
See docs/_plan-ontology.md.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any, cast

import yaml

ACTORS = ("user", "rule", "llm", "system")  # "system" only retracts (e.g. delete_source)
_PRECEDENCE = {"user": 3, "rule": 2, "llm": 1}
STATUSES = ("confirmed", "proposed")
SUBJECT_PREFIXES = ("src:", "work:", "page:")
LANGS = ("en", "de")
TARGETS = ("work", "expression")
NORM_VALUES = (True, False, "internal", "individual")
APPLIES_TO = ("source", "page")
MAX_CUE = 200
MAX_DEFINITION = 200
LOCAL_ID = "local"

_ID_RE = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
_SEMVER_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")
_REQUIRES_RE = re.compile(r"^([a-z][a-z0-9_-]*)@\^(\d+)(?:\.(\d+))?(?:\.(\d+))?$")
_MODULE_KEYS = {"id", "version", "requires", "description", "change_note", "classes", "relations"}
_COMMON_KEYS = {"labels", "definition", "deprecated", "replaced_by", "note", "change_note"}
_CLASS_KEYS = _COMMON_KEYS | {"broader", "rank", "norm", "cues", "applies_to"}
_RELATION_KEYS = _COMMON_KEYS | {
    "domain",
    "range",
    "inverse",
    "target",
    "transitive",
    "attributes",
    "eli",
    "dct",
    "lint",
}
_BINDING_KEYS = {"modules", "local"}
_LOCAL_KEYS = {"version", "classes", "relations", "change_note"}
_BINDING = "ontology.yaml"


@dataclass(frozen=True)
class ClassDef:
    id: str
    module: str
    labels: dict[str, str]
    definition: str
    broader: str | None = None
    rank: int | None = None
    norm: bool | str = False
    cues: tuple[str, ...] = ()
    applies_to: str = "source"
    deprecated: bool = False
    replaced_by: str | None = None
    note: str = ""


@dataclass(frozen=True)
class RelationDef:
    id: str
    module: str
    domain: tuple[str, ...]
    range: tuple[str, ...]
    inverse: str | None = None
    target: str = "work"
    transitive: bool = False
    attributes: dict[str, tuple[str, ...]] = field(default_factory=lambda: {})
    labels: dict[str, str] = field(default_factory=lambda: {})
    definition: str = ""
    eli: str | None = None
    dct: str | None = None
    lint: str | None = None
    deprecated: bool = False
    replaced_by: str | None = None
    note: str = ""


@dataclass(frozen=True)
class Schema:
    modules: dict[str, str]  # module id -> version
    classes: dict[str, ClassDef]
    relations: dict[str, RelationDef]

    def multi_valued(self) -> set[str]:
        """Predicates that hold a set of objects (relations, aliases), not one value."""
        return {"aliases", *self.relations}


# --- small typed helpers ---------------------------------------------------------


def _as_map(value: object) -> dict[str, Any] | None:
    return cast("dict[str, Any]", value) if isinstance(value, dict) else None


def _as_list(value: object) -> list[Any] | None:
    return cast("list[Any]", value) if isinstance(value, list) else None


def _id_list(value: object) -> tuple[str, ...] | None:
    """A class id or a non-empty list of them, as a tuple; None when malformed."""
    if isinstance(value, str):
        return (value,)
    items = _as_list(value)
    if not items or not all(isinstance(v, str) for v in items):
        return None
    return tuple(cast("list[str]", items))


def _opt_str(value: object) -> bool:
    return value is None or isinstance(value, str)


def _unknown_keys(label: str, spec: dict[str, Any], allowed: set[str]) -> list[str]:
    return [f"{label}: unknown key {k!r}" for k in spec if k not in allowed]


def _semver(value: object) -> tuple[int, int, int] | None:
    m = _SEMVER_RE.match(value) if isinstance(value, str) else None
    return (int(m[1]), int(m[2]), int(m[3])) if m else None


# --- YAML --------------------------------------------------------------------------


class _StrictLoader(yaml.SafeLoader):
    """SafeLoader that refuses duplicate mapping keys (PyYAML keeps the last silently)."""


def _strict_mapping(loader: _StrictLoader, node: yaml.MappingNode) -> dict[Any, Any]:
    loader.flatten_mapping(node)
    seen: set[Any] = set()
    for key_node, _ in node.value:
        key = loader.construct_object(key_node, deep=True)  # pyright: ignore[reportUnknownMemberType]
        if key in seen:
            raise yaml.constructor.ConstructorError(
                None, None, f"duplicate key {key!r}", key_node.start_mark
            )
        seen.add(key)
    return loader.construct_mapping(node, deep=True)


_StrictLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _strict_mapping)


def parse_yaml(text: str) -> tuple[Any, list[str]]:
    """Parse YAML safely; duplicate keys and syntax errors come back as messages."""
    try:
        return yaml.load(text, Loader=_StrictLoader), []  # a SafeLoader subclass
    except yaml.YAMLError as exc:
        return None, [" ".join(str(exc).split())]


# --- per-module validation (report §5.4) -------------------------------------------


def _label_errors(label: str, spec: dict[str, Any], required: bool) -> list[str]:
    labels = spec.get("labels")
    if labels is None and not required:
        return []
    lmap = _as_map(labels) or {}
    missing = [lg for lg in LANGS if not (isinstance(lmap.get(lg), str) and lmap[lg].strip())]
    return [f"{label}: `labels` needs {', '.join(missing)}"] if missing else []


def _definition_errors(label: str, spec: dict[str, Any], required: bool) -> list[str]:
    definition = spec.get("definition")
    if definition is None and not required:
        return []
    if not isinstance(definition, str) or not definition.strip():
        return [f"{label}: `definition` is required"]
    text = definition.strip()
    if "\n" in text or len(text) > MAX_DEFINITION:
        return [f"{label}: `definition` must be one line (≤ {MAX_DEFINITION} chars)"]
    return []


def _common_errors(label: str, spec: dict[str, Any], required: bool) -> list[str]:
    errors = _label_errors(label, spec, required) + _definition_errors(label, spec, required)
    if not isinstance(spec.get("deprecated", False), bool):
        errors.append(f"{label}: `deprecated` must be true or false")
    if not _opt_str(spec.get("replaced_by")):
        errors.append(f"{label}: `replaced_by` must be an id")
    if spec.get("deprecated") and not spec.get("replaced_by"):
        errors.append(f"{label}: deprecated without `replaced_by`")
    if not _opt_str(spec.get("note")):
        errors.append(f"{label}: `note` must be text")
    return errors


def _cue_errors(label: str, cues: object) -> list[str]:
    items = _as_list(cues)
    if items is None:
        return [f"{label}: `cues` must be a list of regexes"]
    errors: list[str] = []
    for cue in items:
        if not isinstance(cue, str):
            errors.append(f"{label}: cue {cue!r} must be text")
            continue
        if len(cue) > MAX_CUE:
            errors.append(f"{label}: cue too long (> {MAX_CUE} chars)")
            continue
        try:
            rx = re.compile(cue)
        except re.error as exc:
            errors.append(f"{label}: cue {cue!r} is not a valid regex ({exc})")
            continue
        if rx.search(""):
            errors.append(f"{label}: cue {cue!r} matches the empty string")
    return errors


def _class_errors(label: str, spec: dict[str, Any]) -> list[str]:
    errors = _unknown_keys(label, spec, _CLASS_KEYS) + _common_errors(label, spec, True)
    if not _opt_str(spec.get("broader")):
        errors.append(f"{label}: `broader` must be a class id")
    rank = spec.get("rank")
    if rank is not None and (isinstance(rank, bool) or not isinstance(rank, int)):
        errors.append(f"{label}: `rank` must be an integer")
    if spec.get("norm", False) not in NORM_VALUES:
        errors.append(f"{label}: `norm` must be one of {NORM_VALUES}")
    if spec.get("applies_to", "source") not in APPLIES_TO:
        errors.append(f"{label}: `applies_to` must be one of {APPLIES_TO}")
    return errors + _cue_errors(label, spec.get("cues", []))


def _attribute_errors(label: str, attributes: object) -> list[str]:
    attrs = _as_map(attributes)
    if attrs is None:
        return [f"{label}: `attributes` must be a mapping"]
    return [
        f"{label}: attribute {name!r} needs a list of allowed values"
        for name, values in attrs.items()
        if _id_list(values) is None or isinstance(values, str)
    ]


def _relation_errors(label: str, spec: dict[str, Any]) -> list[str]:
    errors = _unknown_keys(label, spec, _RELATION_KEYS) + _common_errors(label, spec, False)
    errors += [
        f"{label}: `{key}` must be a class id or a list of them"
        for key in ("domain", "range")
        if _id_list(spec.get(key)) is None
    ]
    errors += [
        f"{label}: `{key}` must be text"
        for key in ("inverse", "eli", "dct", "lint")
        if not _opt_str(spec.get(key))
    ]
    if spec.get("target", "work") not in TARGETS:
        errors.append(f"{label}: `target` must be one of {TARGETS}")
    if not isinstance(spec.get("transitive", False), bool):
        errors.append(f"{label}: `transitive` must be true or false")
    return errors + _attribute_errors(label, spec.get("attributes", {}))


_KINDS = {"classes": "class", "relations": "relation"}


def _section_errors(
    where: str, module: dict[str, Any], key: str, check: Callable[[str, dict[str, Any]], list[str]]
) -> list[str]:
    items = _as_map(module.get(key, {}))
    if items is None:
        return [f"{where}: `{key}` must be a mapping"]
    errors: list[str] = []
    for item_id, spec in items.items():
        label = f"{where}: {_KINDS[key]} {item_id!r}"
        if not _ID_RE.match(str(item_id)):
            errors.append(f"{label}: invalid id (lowercase letters, digits, '-' and '_')")
        smap = _as_map(spec)
        errors += [f"{label}: must be a mapping"] if smap is None else check(label, smap)
    return errors


def _requires_errors(where: str, requires: object) -> list[str]:
    items = _as_list(requires)
    if items is None:
        return [f"{where}: `requires` must be a list like ['core@^1']"]
    return [
        f"{where}: bad requirement {r!r} (expected e.g. 'core@^1')"
        for r in items
        if not (isinstance(r, str) and _REQUIRES_RE.match(r))
    ]


def validate_module(data: object) -> list[str]:
    """Structural errors of one module (ids, keys, labels, definitions, cues, semver)."""
    module = _as_map(data)
    if module is None:
        return ["module: must be a mapping"]
    where = str(module.get("id", "?"))
    errors = _unknown_keys(where, module, _MODULE_KEYS)
    if not (isinstance(module.get("id"), str) and _ID_RE.match(where)):
        errors.append(f"{where}: `id` must be a lowercase id")
    if _semver(module.get("version")) is None:
        errors.append(f"{where}: `version` must be MAJOR.MINOR.PATCH")
    errors += _requires_errors(where, module.get("requires", []))
    errors += _section_errors(where, module, "classes", _class_errors)
    return errors + _section_errors(where, module, "relations", _relation_errors)


# --- cross-module checks and merge -------------------------------------------------


def _duplicate_errors(modules: list[dict[str, Any]]) -> list[str]:
    errors: list[str] = []
    owner: dict[tuple[str, str], str] = {}
    seen_modules: set[str] = set()
    for m in modules:
        if m["id"] in seen_modules:
            errors.append(f"module {m['id']!r} is bound twice")
        seen_modules.add(m["id"])
        for kind in ("classes", "relations"):
            for item_id in m.get(kind, {}):
                first = owner.setdefault((kind, item_id), m["id"])
                if first != m["id"]:
                    errors.append(
                        f"{_KINDS[kind]} {item_id!r} is defined in both {first} and {m['id']}"
                    )
    return errors


def _satisfies(version: str, match: re.Match[str]) -> bool:
    have = _semver(version)
    want = (int(match[2]), int(match[3] or 0), int(match[4] or 0))
    return have is not None and have[0] == want[0] and have >= want


def _requires_unmet(modules: list[dict[str, Any]]) -> list[str]:
    versions = {m["id"]: str(m["version"]) for m in modules}
    errors: list[str] = []
    for m in modules:
        for req in m.get("requires", []):
            match = _REQUIRES_RE.match(req)
            assert match is not None  # validate_module checked the format
            have = versions.get(match[1])
            if have is None:
                errors.append(f"{m['id']}: requires {req}, but {match[1]} is not bound")
            elif not _satisfies(have, match):
                errors.append(f"{m['id']}: requires {req}, but {match[1]} is {have}")
    return errors


def _class_def(cid: str, module: str, s: dict[str, Any]) -> ClassDef:
    return ClassDef(
        id=cid,
        module=module,
        labels=dict(s["labels"]),
        definition=str(s["definition"]).strip(),
        broader=s.get("broader"),
        rank=s.get("rank"),
        norm=s.get("norm", False),
        cues=tuple(s.get("cues", [])),
        applies_to=s.get("applies_to", "source"),
        deprecated=bool(s.get("deprecated", False)),
        replaced_by=s.get("replaced_by"),
        note=s.get("note") or "",
    )


def _relation_def(rid: str, module: str, s: dict[str, Any]) -> RelationDef:
    attrs = _as_map(s.get("attributes")) or {}
    return RelationDef(
        id=rid,
        module=module,
        domain=_id_list(s["domain"]) or (),
        range=_id_list(s["range"]) or (),
        inverse=s.get("inverse"),
        target=s.get("target", "work"),
        transitive=bool(s.get("transitive", False)),
        attributes={k: _id_list(v) or () for k, v in attrs.items()},
        labels=dict(s.get("labels") or {}),
        definition=str(s.get("definition") or "").strip(),
        eli=s.get("eli"),
        dct=s.get("dct"),
        lint=s.get("lint"),
        deprecated=bool(s.get("deprecated", False)),
        replaced_by=s.get("replaced_by"),
        note=s.get("note") or "",
    )


def _merge(modules: list[dict[str, Any]]) -> Schema:
    classes: dict[str, ClassDef] = {}
    relations: dict[str, RelationDef] = {}
    for m in modules:
        for cid, spec in m.get("classes", {}).items():
            classes[cid] = _class_def(cid, m["id"], spec)
        for rid, spec in m.get("relations", {}).items():
            relations[rid] = _relation_def(rid, m["id"], spec)
    versions = {m["id"]: str(m["version"]) for m in modules}
    return Schema(modules=versions, classes=classes, relations=relations)


def _cycle_errors(classes: dict[str, ClassDef]) -> list[str]:
    errors: list[str] = []
    reported: set[str] = set()
    for start in classes:
        path: list[str] = []
        cur = start
        while cur in classes and cur not in path:
            path.append(cur)
            cur = classes[cur].broader or ""
        if cur in path:
            cycle = path[path.index(cur) :]
            if min(cycle) not in reported:
                reported.add(min(cycle))
                errors.append(f"`broader` cycle: {' -> '.join([*cycle, cur])}")
    return errors


def _hierarchy_errors(classes: dict[str, ClassDef]) -> list[str]:
    dangling = [
        f"class {c.id!r} ({c.module}): `broader` {c.broader!r} does not exist"
        for c in classes.values()
        if c.broader and c.broader not in classes
    ]
    return dangling + _cycle_errors(classes)


def _relation_ref_errors(schema: Schema) -> list[str]:
    errors: list[str] = []
    for r in schema.relations.values():
        errors += [
            f"relation {r.id!r} ({r.module}): unknown class {cid!r} in domain/range"
            for cid in (*r.domain, *r.range)
            if cid not in schema.classes
        ]
        twin = schema.relations.get(r.inverse or "")
        if twin is not None and twin.inverse != r.id:
            errors.append(
                f"relation {r.id!r}: inverse {twin.id!r} declares inverse {twin.inverse!r}, "
                f"expected {r.id!r}"
            )
    return errors


def _deprecation_errors(schema: Schema) -> list[str]:
    items: Iterable[tuple[str, ClassDef | RelationDef, dict[str, Any]]] = [
        *(("class", c, schema.classes) for c in schema.classes.values()),
        *(("relation", r, schema.relations) for r in schema.relations.values()),
    ]
    return [
        f"{kind} {item.id!r}: `replaced_by` {item.replaced_by!r} does not exist"
        for kind, item, pool in items
        if item.deprecated and item.replaced_by not in pool
    ]


def build_schema(modules: list[Any]) -> tuple[Schema | None, list[str]]:
    """Validate and merge modules; (schema, []) or (None, every error found)."""
    errors = [e for m in modules for e in validate_module(m)]
    if errors:
        return None, errors
    maps = [cast("dict[str, Any]", m) for m in modules]
    errors = _duplicate_errors(maps) + _requires_unmet(maps)
    if errors:
        return None, errors
    schema = _merge(maps)
    errors = (
        _hierarchy_errors(schema.classes)
        + _relation_ref_errors(schema)
        + _deprecation_errors(schema)
    )
    return (None, errors) if errors else (schema, [])


# --- per-DB binding (data/<DB>/ontology.yaml) --------------------------------------


def _local_module(value: object) -> tuple[dict[str, Any] | None, list[str]]:
    if value is None:
        return None, []
    local = _as_map(value)
    if local is None:
        return None, [f"{_BINDING}: `local` must be a mapping"]
    module = {
        "id": LOCAL_ID,
        "version": local.get("version", "0.1.0"),
        "classes": local.get("classes", {}),
        "relations": local.get("relations", {}),
    }
    return module, _unknown_keys(f"{_BINDING}: local", local, _LOCAL_KEYS)


def read_binding(
    data: object, available: set[str]
) -> tuple[list[str], dict[str, Any] | None, list[str]]:
    """Bound module ids, the local extension as a module dict (or None), and errors."""
    binding = _as_map(data)
    if binding is None:
        return [], None, [f"{_BINDING}: must be a mapping with `modules`"]
    errors = _unknown_keys(_BINDING, binding, _BINDING_KEYS)
    ids = _id_list(binding.get("modules"))
    if ids is None:
        errors.append(f"{_BINDING}: `modules` must be a list of module ids")
        ids = ()
    errors += [f"{_BINDING}: unknown module {m!r}" for m in ids if m not in available]
    local, local_errors = _local_module(binding.get("local"))
    return list(ids), local, errors + local_errors


# --- ledger rows and projection (report §4.3) --------------------------------------


def assertion(
    subject: str,
    predicate: str,
    obj: Any,
    *,
    by: str,
    evidence: str = "",
    status: str = "confirmed",
    user: str | None = None,
    negated: bool = False,
    valid_from: str | None = None,
    valid_until: str | None = None,
    module: str | None = None,
) -> dict[str, Any]:
    """A new ledger row (without `id`/`recorded_at`, which the store assigns)."""
    if by not in _PRECEDENCE:
        raise ValueError(f"unknown actor {by!r}; expected one of {tuple(_PRECEDENCE)}")
    if not subject.startswith(SUBJECT_PREFIXES):
        raise ValueError(f"subject {subject!r} must start with one of {SUBJECT_PREFIXES}")
    if status not in STATUSES:
        raise ValueError(f"unknown status {status!r}; expected one of {STATUSES}")
    return {
        "subject": subject,
        "predicate": predicate,
        "object": obj,
        "by": by,
        "user": user,
        "evidence": evidence,
        "status": status,
        "negated": negated,
        "valid_from": valid_from,
        "valid_until": valid_until,
        "ontology": module,
        "retracts": None,
    }


def retraction(
    target: dict[str, Any], *, by: str, reason: str, user: str | None = None
) -> dict[str, Any]:
    """A row that withdraws ``target``; rows are never edited or deleted."""
    if by not in ACTORS:
        raise ValueError(f"unknown actor {by!r}; expected one of {ACTORS}")
    return {
        "subject": target["subject"],
        "predicate": target["predicate"],
        "object": target.get("object"),
        "by": by,
        "user": user,
        "reason": reason,
        "retracts": target["id"],
    }


def live_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Assertion rows (any status) that no retraction withdrew, in ledger order."""
    retracted = {r["retracts"] for r in rows if r.get("retracts")}
    return [r for r in rows if not r.get("retracts") and r.get("id") not in retracted]


def _winners(rows: list[dict[str, Any]], multi: set[str]) -> dict[tuple[str, ...], dict[str, Any]]:
    won: dict[tuple[str, ...], dict[str, Any]] = {}
    for r in live_rows(rows):
        if r.get("status") != "confirmed":
            continue
        subject, pred = str(r.get("subject")), str(r.get("predicate"))
        key = (subject, pred, repr(r.get("object"))) if pred in multi else (subject, pred)
        current = won.get(key)
        rank = _PRECEDENCE.get(str(r.get("by")), 0)
        if current is None or rank >= _PRECEDENCE.get(str(current.get("by")), 0):
            won[key] = r
    return won


def project(rows: list[dict[str, Any]], multi: set[str]) -> dict[str, dict[str, Any]]:
    """Current confirmed facts per subject: {subject: {predicate: value | sorted list}}.

    Per fact the highest-precedence actor wins (user > rule > llm), the later row among
    equals. A user row with object None unsets a single-valued fact; a user row with
    `negated` removes one member of a multi-valued fact. Both stay sticky against later
    rule/llm rows.
    """
    out: dict[str, dict[str, Any]] = {}
    for key, r in _winners(rows, multi).items():
        subject, pred = key[0], key[1]
        if pred in multi:
            if not r.get("negated") and r.get("object") is not None:
                out.setdefault(subject, {}).setdefault(pred, []).append(r["object"])
        elif r.get("object") is not None:
            out.setdefault(subject, {})[pred] = r["object"]
    for facts in out.values():
        for pred, value in facts.items():
            if isinstance(value, list):
                facts[pred] = sorted(cast("list[Any]", value), key=str)
    return out


# --- page stamping (report §4.4) ---------------------------------------------------

STAMP_KEYS = ("class", "work", "version_date")


def stamp_meta(meta: dict[str, Any], facts: dict[str, Any]) -> dict[str, Any]:
    """Frontmatter with the code-owned ontology keys set from ``facts`` (a source's
    projection) and removed where the fact is absent. Other keys are untouched."""
    out = {k: v for k, v in meta.items() if k not in STAMP_KEYS}
    out.update({k: facts[k] for k in STAMP_KEYS if facts.get(k) is not None})
    return out
