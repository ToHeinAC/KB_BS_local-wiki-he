"""Ontology-aware search, pure part (plan §4): view, query resolution, briefing, lookup.

Pure, no LLM. A `View` is built from a DB's schema, its confirmed facts and the wiki's
page→sources map. `resolve()` finds, word-bounded and longest-first, the Work aliases
and class labels a question mentions and returns a `QueryFrame`: the resolved works (an
ambiguous alias keeps all its works), their sources (newest version first), the sources
of the named classes and their descendants, and alias terms for the lexical ontology arm.
`briefing()` turns a frame into a short system-prompt block built only from ids, file
names, dates and the user's own words — never from document-derived names, so a
document cannot inject instructions. `lookup()` answers the `ontology_lookup` tool.
See docs/ontology.md §Search.
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass
from datetime import date
from typing import Any, cast

import ontology
import ontology_detect
import ontology_time
from prompts import (
    ONTOLOGY_BRIEFING_CLASS,
    ONTOLOGY_BRIEFING_HEADER,
    ONTOLOGY_BRIEFING_RELATIONS,
    ONTOLOGY_BRIEFING_RULE,
    ONTOLOGY_BRIEFING_TIME,
    ONTOLOGY_BRIEFING_VERSIONS,
    ONTOLOGY_BRIEFING_WORK,
)

BRIEFING_MAX_CHARS = 600
MAX_BRIEF_WORKS = 3
MAX_TERMS = 6
MAX_CLASS_WORKS = 15

_WORD_RE = re.compile(r"\w+")
_SECTION_RE = re.compile(r"\s+[§#].*$")

Key = tuple[str, ...]


@dataclass(frozen=True)
class View:
    aliases: dict[Key, tuple[str, ...]]  # alias tokens -> work ids
    class_labels: dict[Key, str]  # label tokens -> class id
    max_len: int
    works: dict[str, dict[str, Any]]  # id -> class, aliases, sources, relations
    sources: dict[str, dict[str, Any]]  # raw source -> its facts
    class_sources: dict[str, tuple[str, ...]]  # class -> sources of it or a descendant
    classes: dict[str, str]  # class id -> definition
    pages: dict[str, tuple[str, ...]]  # raw source -> wiki pages citing it
    # Plan Phase 6: relation edges (from a work id or "src:<file>"), class ranks/norms,
    # relation lint rules.
    edges: tuple[dict[str, Any], ...] = ()
    ranks: dict[str, int | None] | None = None
    norms: dict[str, bool | str] | None = None
    relation_lint: dict[str, str | None] | None = None
    domains: dict[str, tuple[str, ...]] | None = None  # relation -> domain classes
    broader: dict[str, str | None] | None = None  # class -> broader class


@dataclass(frozen=True)
class QueryFrame:
    matched: tuple[str, ...]  # the question's words that matched, as typed
    hits: tuple[tuple[str, str], ...]  # (matched words, "work:<id>" | "class:<id>")
    works: tuple[str, ...]
    classes: tuple[str, ...]
    sources: tuple[str, ...]  # of the resolved works, newest version first
    class_sources: tuple[str, ...]
    terms: tuple[str, ...]  # aliases of the resolved works, for the lexical arm
    as_of: str = ""  # ISO date the question is about (today unless it names one)
    explicit: bool = False  # the question named a date or year
    past: bool = False  # the question asks about an earlier state


def tokens(text: str) -> Key:
    return tuple(m.casefold() for m in _WORD_RE.findall(text))


# --- view ------------------------------------------------------------------------------


def _as_map(value: object) -> dict[str, Any]:
    return cast("dict[str, Any]", value) if isinstance(value, dict) else {}


def _as_list(value: object) -> list[Any]:
    return cast("list[Any]", value) if isinstance(value, list) else []


def _newest_first(names: list[str], sources: dict[str, dict[str, Any]]) -> list[str]:
    """By version date, newest first; undated last; ties by name (stable sorts)."""
    return sorted(
        sorted(names), key=lambda n: str(sources[n].get("version_date") or ""), reverse=True
    )


def _works(schema: ontology.Schema, facts: dict[str, Any]) -> dict[str, dict[str, Any]]:
    sources = _as_map(facts.get("sources"))
    ids = set(_as_map(facts.get("works"))) | {
        str(f["work"]) for f in map(_as_map, sources.values()) if f.get("work")
    }
    out: dict[str, dict[str, Any]] = {}
    for wid in sorted(ids):
        wf = _as_map(_as_map(facts.get("works")).get(wid))
        members = [s for s, f in sources.items() if _as_map(f).get("work") == wid]
        out[wid] = {
            "class": wf.get("class"),
            "aliases": [str(a) for a in _as_list(wf.get("aliases"))],
            "sources": _newest_first(members, sources),
            "relations": {
                r: [ontology.member_target(m) for m in _as_list(wf[r])]
                for r in schema.relations
                if wf.get(r)
            },
            "in_force_from": wf.get("in_force_from"),
            "in_force_until": wf.get("in_force_until"),
        }
    return out


def _class_sources(
    schema: ontology.Schema, sources: dict[str, dict[str, Any]]
) -> dict[str, tuple[str, ...]]:
    out: dict[str, tuple[str, ...]] = {}
    for cid in schema.classes:
        members = [
            s
            for s, f in sources.items()
            if f.get("class") in schema.classes and ontology_detect.is_a(schema, f["class"], cid)
        ]
        out[cid] = tuple(sorted(members))
    return out


def _class_labels(schema: ontology.Schema, class_sources: dict[str, Key]) -> dict[Key, str]:
    """Label tokens of every non-root, non-deprecated class that has sources."""
    labels: dict[Key, str] = {}
    for c in sorted(schema.classes.values(), key=lambda c: c.id):
        if c.broader is None or c.deprecated or not class_sources.get(c.id):
            continue
        for label in c.labels.values():
            for part in label.split("/"):
                if tokens(part):
                    labels.setdefault(tokens(part), c.id)
    return labels


def _genitives(key: Key) -> list[Key]:
    """The alias and its German genitive ("des Strahlenschutzgesetzes"): the last word
    takes -es/-s. Only for word-like endings, so abbreviations stay exact."""
    last = key[-1]
    if len(last) < 5 or not last.isalpha():
        return [key]
    return [key, (*key[:-1], last + "es"), (*key[:-1], last + "s")]


def _alias_map(works: dict[str, dict[str, Any]]) -> dict[Key, tuple[str, ...]]:
    aliases: dict[Key, list[str]] = {}
    for wid, work in works.items():
        for alias in work["aliases"]:
            for key in _genitives(tokens(alias)) if tokens(alias) else []:
                if wid not in aliases.setdefault(key, []):
                    aliases[key].append(wid)
    return {k: tuple(v) for k, v in aliases.items()}


def _edges(schema: ontology.Schema, facts: dict[str, Any]) -> tuple[dict[str, Any], ...]:
    """Relation edges from works (by id) and from sources without a work ("src:<file>")."""
    out: list[dict[str, Any]] = []
    subjects = [(w, _as_map(f)) for w, f in _as_map(facts.get("works")).items()]
    subjects += [(f"src:{s}", _as_map(f)) for s, f in _as_map(facts.get("sources")).items()]
    for node, subject_facts in sorted(subjects, key=lambda p: p[0]):
        for rel in sorted(schema.relations):
            for member in _as_list(subject_facts.get(rel)):
                attrs = {k: str(v) for k, v in _as_map(member).items() if k != "to"}
                out.append(
                    {"from": node, "rel": rel, "to": ontology.member_target(member), "attrs": attrs}
                )
    return tuple(out)


def _page_map(pages: dict[str, list[str]]) -> dict[str, tuple[str, ...]]:
    by_source: dict[str, set[str]] = {}
    for page, cited in pages.items():
        for source in cited:
            by_source.setdefault(_SECTION_RE.sub("", str(source)), set()).add(page)
    return {s: tuple(sorted(p)) for s, p in by_source.items()}


def build_view(schema: ontology.Schema, facts: dict[str, Any], pages: dict[str, list[str]]) -> View:
    """Everything search needs from one DB's ontology (a derived cache: rebuildable)."""
    sources = {s: _as_map(f) for s, f in _as_map(facts.get("sources")).items()}
    works = _works(schema, facts)
    class_sources = _class_sources(schema, sources)
    aliases = _alias_map(works)
    labels = _class_labels(schema, class_sources)
    return View(
        aliases=aliases,
        class_labels=labels,
        max_len=max((len(k) for k in (*aliases, *labels)), default=0),
        works=works,
        sources=sources,
        class_sources=class_sources,
        classes={c.id: c.definition for c in schema.classes.values()},
        pages=_page_map(pages),
        edges=_edges(schema, facts),
        ranks={c.id: c.rank for c in schema.classes.values()},
        norms={c.id: c.norm for c in schema.classes.values()},
        relation_lint={r.id: r.lint for r in schema.relations.values()},
        domains={r.id: r.domain for r in schema.relations.values()},
        broader={c.id: c.broader for c in schema.classes.values()},
    )


def in_class(view: View, cid: str | None, ancestor: str) -> bool:
    """``cid`` is ``ancestor`` or one of its narrower classes."""
    seen: set[str] = set()
    while cid and cid not in seen:
        if cid == ancestor:
            return True
        seen.add(cid)
        cid = (view.broader or {}).get(cid)
    return False


def pages_for(view: View, sources: tuple[str, ...]) -> tuple[str, ...]:
    """Wiki pages that cite any of ``sources``."""
    return tuple(sorted({p for s in sources for p in view.pages.get(s, ())}))


# --- resolution ----------------------------------------------------------------------


def _longest(toks: Key, i: int, view: View) -> tuple[int, list[str]] | None:
    """Length and targets ("work:…"/"class:…") of the longest match starting at ``i``."""
    for n in range(min(view.max_len, len(toks) - i), 0, -1):
        key = toks[i : i + n]
        if key in view.aliases:
            return n, [f"work:{w}" for w in view.aliases[key]]
        if key in view.class_labels:
            return n, [f"class:{view.class_labels[key]}"]
    return None


def _scan(q: str, view: View) -> list[tuple[str, str]]:
    spans = list(_WORD_RE.finditer(q))
    toks = tuple(m.group(0).casefold() for m in spans)
    found: list[tuple[str, str]] = []
    i = 0
    while i < len(toks):
        match = _longest(toks, i, view)
        if match is None:
            i += 1
            continue
        n, targets = match
        surface = q[spans[i].start() : spans[i + n - 1].end()]
        found += [(surface, t) for t in targets]
        i += n
    return found


def _unique(items: list[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(items))


def _in_force_only(hits: list[tuple[str, str]], view: View, as_of: date) -> list[tuple[str, str]]:
    """For an alias naming several works, keep those in force at ``as_of`` (if any is)."""
    out: list[tuple[str, str]] = []
    for surface in dict.fromkeys(s for s, _ in hits):
        group = [t for s, t in hits if s == surface]
        works = [t for t in group if t.startswith("work:")]
        live = [t for t in works if ontology_time.work_in_force(view, t[5:], as_of)]
        keep = live if len(works) > 1 and live else works
        out += [(surface, t) for t in group if not t.startswith("work:") or t in keep]
    return out


def resolve(q: str, view: View, today: date | None = None) -> QueryFrame | None:
    """The works and classes ``q`` names, at the point in time it asks about;
    None when it names none."""
    intent = ontology_time.time_intent(q, today or date.today())
    hits = _in_force_only(_scan(q, view), view, intent.as_of)
    if not hits:
        return None
    works = _unique([t[5:] for _, t in hits if t.startswith("work:")])
    classes = _unique([t[6:] for _, t in hits if t.startswith("class:")])
    return QueryFrame(
        matched=_unique([s for s, _ in hits]),
        hits=tuple(hits),
        works=works,
        classes=classes,
        sources=_unique([s for w in works for s in view.works[w]["sources"]]),
        class_sources=_unique([s for c in classes for s in view.class_sources.get(c, ())]),
        terms=_unique([a for w in works for a in view.works[w]["aliases"]])[:MAX_TERMS],
        as_of=intent.as_of.isoformat(),
        explicit=intent.explicit,
        past=intent.past,
    )


def audit(frame: QueryFrame | None) -> dict[str, Any]:
    """Render-ready record of what the stage did (for "Why these sources")."""
    if frame is None:
        return {}
    return {
        "matched": list(frame.matched),
        "works": list(frame.works),
        "classes": list(frame.classes),
        "sources": list(frame.sources) + [s for s in frame.class_sources if s not in frame.sources],
        "as_of": frame.as_of,
    }


# --- briefing (S2) -------------------------------------------------------------------


def _version(source: str, view: View, as_of: date) -> str:
    parts = [str(view.sources[source].get("version_date") or "")]
    parts.append(ontology_time.LABELS.get(ontology_time.validity(view, source, as_of), ""))
    shown = ", ".join(p for p in parts if p)
    return f"{source} ({shown})" if shown else source


def _versions(work: dict[str, Any], view: View, as_of: date) -> str:
    return ", ".join(_version(s, view, as_of) for s in work["sources"])


def _work_lines(surface: str, wid: str, view: View, as_of: date) -> list[str]:
    work = view.works[wid]
    cls = f", class {work['class']}" if work.get("class") else ""
    lines = [ONTOLOGY_BRIEFING_WORK.format(matched=surface, work=wid, cls=cls)]
    if work["sources"]:
        lines.append(ONTOLOGY_BRIEFING_VERSIONS.format(versions=_versions(work, view, as_of)))
    relations = "; ".join(f"{r}: {', '.join(map(str, t))}" for r, t in work["relations"].items())
    if relations:
        lines.append(ONTOLOGY_BRIEFING_RELATIONS.format(relations=relations))
    return lines


def briefing(frame: QueryFrame | None, view: View) -> str:
    """System-prompt block for a frame (≤ BRIEFING_MAX_CHARS); "" without a frame."""
    if frame is None:
        return ""
    as_of = ontology_time.parse(frame.as_of) or date.today()
    origin = "from the question" if frame.explicit else "today"
    if frame.past and not frame.explicit:
        origin = "the question asks about an earlier version; no date given"
    body = [ONTOLOGY_BRIEFING_TIME.format(as_of=frame.as_of, origin=origin)]
    works_done = 0
    for surface, target in frame.hits:
        kind, _, ident = target.partition(":")
        if kind == "work" and works_done < MAX_BRIEF_WORKS:
            body += _work_lines(surface, ident, view, as_of)
            works_done += 1
        elif kind == "class":
            count = len(view.class_sources.get(ident, ()))
            body.append(ONTOLOGY_BRIEFING_CLASS.format(matched=surface, cls=ident, count=count))
    head, tail = ONTOLOGY_BRIEFING_HEADER, ONTOLOGY_BRIEFING_RULE
    while len(body) > 1 and len("\n".join([head, *body, tail])) > BRIEFING_MAX_CHARS:
        body.pop()
    return "\n".join([head, *body, tail]) if len(body) > 1 else ""


# --- lookup (S3) ---------------------------------------------------------------------


def _incoming(wid: str, view: View) -> list[str]:
    return [
        f"{rel} ← {other}"
        for other, work in view.works.items()
        for rel, targets in work["relations"].items()
        if wid in targets
    ]


def _lookup_work(wid: str, view: View, as_of: date) -> str:
    work = view.works[wid]
    lines = [f"Work {wid}" + (f" (class {work['class']})" if work.get("class") else "")]
    if work["aliases"]:
        lines.append("  aliases: " + ", ".join(work["aliases"]))
    versions = _versions(work, view, as_of) or "none in this DB"
    lines.append(f"  versions (newest first, validity at {as_of.isoformat()}): {versions}")
    outgoing = [f"{r} → {t}" for r, ts in work["relations"].items() for t in ts]
    related = outgoing + _incoming(wid, view)
    if related:
        lines.append("  relations: " + "; ".join(related))
    return "\n".join(lines)


def _lookup_class(cid: str, view: View) -> str:
    members = sorted(
        {view.sources[s].get("work") or s for s in view.class_sources.get(cid, ())}, key=str
    )
    shown = ", ".join(map(str, members[:MAX_CLASS_WORKS])) or "none"
    return f"Class {cid}: {view.classes.get(cid, '')}\n  works/sources: {shown}"


def lookup(term: str, view: View, today: date | None = None) -> str:
    """Tool answer for ``term``: its works (versions, relations) and/or classes; a date in
    ``term`` ("StrlSchV 2017") sets the point in time for validity."""
    frame = resolve(term, view, today)
    if frame is None:
        names = sorted({a for w in view.works.values() for a in w["aliases"]})
        near = difflib.get_close_matches(term, names, n=3, cutoff=0.6)
        hint = f" Did you mean: {', '.join(near)}?" if near else ""
        return f"No ontology entry for {term!r}.{hint}"
    as_of = ontology_time.parse(frame.as_of) or date.today()
    parts = [_lookup_work(w, view, as_of) for w in frame.works]
    parts += [_lookup_class(c, view) for c in frame.classes]
    return "\n".join(parts)


def badge(view: View, source: str, as_of: date | None = None) -> str:
    """One line for a search hit: "ontology: class · work · date · validity" or ""."""
    facts = view.sources.get(source, {})
    parts = [str(facts[k]) for k in ("class", "work", "version_date") if facts.get(k)]
    if parts and as_of is not None:
        state = ontology_time.LABELS.get(ontology_time.validity(view, source, as_of))
        parts += [state] if state else []
    return "ontology: " + " · ".join(parts) if parts else ""
