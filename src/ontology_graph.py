"""Relations as a graph (plan Phase 6): chains, binding paths, deterministic lint.

Pure. Nodes are work ids, or "src:<file>" for a document without a work (e.g. a permit).
`binding_of` derives whether a standard is binding and *why*, as explanation paths
(report §9): it is binding only through an `incorporates` reference from a document
that is itself binding (a norm, an individual decision or an internal rule) and in force
at the point in time. A class `rank` orders and warns; it never decides a conflict.
See docs/ontology.md §Relations.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import ontology_detect
import ontology_query
import ontology_time
from ontology_query import View

TRANSITIVE = ("based_on", "replaces", "is_part_of", "repeals", "amends")
_BINDING_NORMS = (True, "individual", "internal")
_NORM_NOTES = {
    "individual": "binding for the addressee of this decision",
    "internal": "binding inside the organisation or administration",
}


def node_label(node: str) -> str:
    return node[4:] if node.startswith("src:") else node


def node_class(view: View, node: str) -> str | None:
    if node.startswith("src:"):
        return view.sources.get(node[4:], {}).get("class")
    work = view.works.get(node, {})
    sources: list[str] = work.get("sources", [])
    return work.get("class") or next(
        (view.sources[s].get("class") for s in sources if view.sources[s].get("class")), None
    )


def targets(view: View, node: str, rel: str) -> list[str]:
    return [e["to"] for e in view.edges if e["from"] == node and e["rel"] == rel]


def chain(view: View, start: str, rel: str) -> list[str]:
    """``start`` and every node reachable over ``rel`` (breadth-first, cycle-safe)."""
    order, queue = [start], [start]
    while queue:
        for nxt in targets(view, queue.pop(0), rel):
            if nxt not in order:
                order.append(nxt)
                queue.append(nxt)
    return order


def in_force(view: View, node: str, as_of: date) -> bool:
    """A document node holds at ``as_of`` (unknown validity counts as holding)."""
    if node.startswith("src:"):
        return ontology_time.validity(view, node[4:], as_of) != ontology_time.SUPERSEDED
    sources: list[str] = view.works.get(node, {}).get("sources", [])
    states = {ontology_time.validity(view, s, as_of) for s in sources}
    return not states or ontology_time.VALID in states or ontology_time.UNKNOWN in states


def _path(edge: dict[str, Any], cls: str | None, norm: bool | str | None) -> str:
    attrs = edge["attrs"]
    mode, effect = attrs.get("mode", "mode unknown"), attrs.get("effect", "effect unknown")
    text = f"{edge['to']} ◄ incorporates ({mode}, {effect}) ─ {node_label(edge['from'])} ({cls})"
    if mode == "static" and attrs.get("edition"):
        text += (
            f"; edition {attrs['edition']} pinned — newer editions are not binding "
            "through this reference"
        )
    if effect == "presumption":
        text += "; meeting it is presumed to satisfy the requirement"
    note = _NORM_NOTES.get(str(norm)) if isinstance(norm, str) else None
    return text + (f"; {note}" if note else "")


def binding_of(view: View, work: str, as_of: date) -> list[str]:
    """Explanation paths for why ``work`` (e.g. a DIN standard) is binding at ``as_of``."""
    paths: list[str] = []
    for edge in view.edges:
        if edge["to"] != work or edge["rel"] != "incorporates":
            continue
        cls = node_class(view, edge["from"])
        norm = (view.norms or {}).get(cls or "")
        if edge["attrs"].get("effect") == "guidance" or norm not in _BINDING_NORMS:
            continue
        if in_force(view, edge["from"], as_of):
            paths.append(_path(edge, cls, norm))
    if paths:
        return paths
    return [
        "Not binding by any reference in this database — interpretive / state of the art "
        "only (a binding reference comes from a norm, a decision or an internal rule)."
    ]


# --- lint (report §8) -----------------------------------------------------------------


def _finding(level: str, message: str) -> dict[str, str]:
    return {"level": level, "message": message}


def _cycles(view: View) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    reported: set[frozenset[str]] = set()
    for rel in TRANSITIVE:
        for start in sorted({e["from"] for e in view.edges if e["rel"] == rel}):
            back = [t for t in chain(view, start, rel)[1:] if start in targets(view, t, rel)]
            loop = frozenset([rel, start, *back])
            if back and loop not in reported:
                reported.add(loop)
                out.append(
                    _finding("warning", f"cycle in {rel}: {start} → … → {back[0]} → {start}")
                )
    return out


def _rank_violations(view: View) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    ranks = view.ranks or {}
    for e in view.edges:
        if (view.relation_lint or {}).get(e["rel"]) != "range_rank_not_lower":
            continue
        low, high = node_class(view, e["from"]), node_class(view, e["to"])
        r_from, r_to = ranks.get(low or ""), ranks.get(high or "")
        if r_from is not None and r_to is not None and r_to > r_from:
            out.append(
                _finding(
                    "warning",
                    f"{e['from']} ({low}, rank {r_from}) {e['rel']} {e['to']} ({high}, rank "
                    f"{r_to}): the basis ranks lower than the document built on it",
                )
            )
    return out


def _date_findings(view: View) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for wid, work in sorted(view.works.items()):
        start = ontology_time.parse(work.get("in_force_from"))
        end = ontology_time.parse(work.get("in_force_until"))
        if start and end and end < start:
            out.append(
                _finding("warning", f"{wid}: in_force_until {end} is before in_force_from {start}")
            )
        dates = [view.sources[s].get("version_date") for s in work.get("sources", [])]
        clashes = sorted({d for d in dates if d and dates.count(d) > 1})
        out += [_finding("warning", f"{wid}: two versions share version_date {d}") for d in clashes]
    return out


def _missing(view: View) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    referenced: dict[str, set[str]] = {}
    for e in view.edges:
        work = view.works.get(e["to"], {})
        editions = [str(view.sources[s].get("version_date") or "") for s in work.get("sources", [])]
        edition = e["attrs"].get("edition")
        if edition and not any(d.startswith(edition) for d in editions):
            out.append(
                _finding(
                    "info",
                    f"{node_label(e['from'])} pins {e['to']} edition {edition}, "
                    "which is not in this database",
                )
            )
        if not work.get("sources"):
            referenced.setdefault(e["to"], set()).add(e["from"])
    out += [
        _finding(
            "info", f"{target} is referenced by {len(src)} document(s) but not in this database"
        )
        for target, src in sorted(referenced.items())
    ]
    return out


def lint(view: View) -> list[dict[str, str]]:
    """Deterministic consistency findings: warnings (cycles, rank, dates) and infos
    (missing editions and documents). Ranks only ever warn, never fix (report §2.3)."""
    return _cycles(view) + _rank_violations(view) + _date_findings(view) + _missing(view)


def describe(view: View, term: str, as_of: date) -> str:
    """Extra `ontology_lookup` lines for ``term``: its based_on chain and, for a standard
    that documents reference, its binding paths."""
    frame = ontology_query.resolve(term, view, as_of)
    ids = list(frame.works) if frame else []
    known = {e["to"] for e in view.edges} | set(view.works)
    for candidate in (ontology_detect.standard_id(term), term.strip().lower()):
        if candidate and candidate in known and candidate not in ids:
            ids.append(candidate)
    lines: list[str] = []
    for wid in ids:
        steps = chain(view, wid, "based_on")
        if len(steps) > 1:
            lines.append("based_on chain: " + " → ".join(steps))
        if any(e["to"] == wid and e["rel"] == "incorporates" for e in view.edges):
            lines += [f"binding: {p}" for p in binding_of(view, wid, as_of)]
    return "\n".join(lines)
