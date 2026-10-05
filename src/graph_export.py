"""Graph payload + deterministic analytics for the neural renderer.

The renderer is a *navigator into the wiki reader*, not a second knowledge model,
so this module derives **no structure of its own**: nodes and edges come verbatim
from `wiki_engine.build_typed_graph()` — the same typed graph the legacy vis.js
tab draws. This module only *enriches* that graph:

  * per-node frontmatter (type, confidence, created/updated, tags, staleness),
  * per-node analytics (degree, PageRank, betweenness, Louvain community).

Everything is computed in Python and stamped into the payload, never asked of a
model and never recomputed in JS — same discipline as OKF stamping and language
pinning. The output is **deterministic**: nodes and edges are sorted, Louvain is
seeded, floats are rounded, so `export()` is snapshot-testable.

Staleness reuses `wiki_engine.is_page_stale` rather than re-reading
`expires_after_days`, so the graph's amber pulse and the nav tree's ⚠️ can never
disagree.
"""

from __future__ import annotations

import os
from datetime import UTC, date, datetime, timedelta
from itertools import pairwise
from typing import Any, NamedTuple, cast

import networkx as nx
from networkx.algorithms.community import louvain_communities

import classification
import db_context
import lang
import wiki_engine

# Guardrail for very large bundles: keep the densest core, drop the rest. The
# renderer is interactive at a few thousand nodes; beyond that the force layout,
# not the analytics, is what falls over.
MAX_NODES = int(os.getenv("GRAPH_MAX_NODES", "4000"))

# "Recently touched" for the health panel's growth column.
HEALTH_WINDOW_DAYS = 30

# Louvain is stochastic; a fixed seed keeps the map recognisable run-to-run.
_LOUVAIN_SEED = 42

# Top-decile cutoffs for the "hub" and "bridge" overlays.
_HUB_QUANTILE = 0.9
_BRIDGE_QUANTILE = 0.9


# Edge types without a direction; the renderer draws `same-topic` (one topic at several
# classification levels) dashed and without an arrow.
_UNDIRECTED = ("related-to", "same-topic")


def _quantile_threshold(values: list[float], q: float) -> float:
    """Value at quantile ``q`` of ``values`` (nearest-rank, deterministic)."""
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = min(int(q * len(ordered)), len(ordered) - 1)
    return ordered[idx]


def _to_networkx(typed: dict[str, Any]) -> nx.Graph[str]:
    """Undirected view of the typed graph, for analytics only.

    Direction is preserved in the exported edge list (`derived-from` renders as
    an arrow); centrality and community detection want the undirected view —
    a page and the source it derives from belong to the same neighbourhood
    regardless of which way the arrow points.
    """
    G: nx.Graph[str] = nx.Graph()
    for node in typed["nodes"]:
        G.add_node(node["id"])
    for edge in typed["edges"]:
        G.add_edge(edge["from"], edge["to"])
    return G


def _cap(typed: dict[str, Any], limit: int) -> tuple[dict[str, Any], bool]:
    """Keep the ``limit`` best-connected nodes; drop edges that dangle after."""
    nodes = typed["nodes"]
    if len(nodes) <= limit:
        return typed, False
    degree: dict[str, int] = {n["id"]: 0 for n in nodes}
    for edge in typed["edges"]:
        degree[edge["from"]] = degree.get(edge["from"], 0) + 1
        degree[edge["to"]] = degree.get(edge["to"], 0) + 1
    ranked = sorted(nodes, key=lambda n: (-degree.get(n["id"], 0), n["id"]))
    keep = {n["id"] for n in ranked[:limit]}
    return (
        {
            "nodes": [n for n in nodes if n["id"] in keep],
            "edges": [e for e in typed["edges"] if e["from"] in keep and e["to"] in keep],
        },
        True,
    )


def _page_meta() -> dict[str, dict[str, Any]]:
    """Frontmatter per wiki page, keyed the way the typed graph keys its nodes."""
    return {p["filename"]: p for p in wiki_engine.list_pages(include_insights=True)}


def _analytics(G: nx.Graph[str]) -> tuple[dict[str, float], dict[str, float], list[set[str]]]:
    """PageRank, betweenness and Louvain communities (seeded) of the undirected graph."""
    if G.number_of_edges():
        pagerank: dict[str, float] = nx.pagerank(G)
        communities: list[set[str]] = louvain_communities(G, seed=_LOUVAIN_SEED)
    else:
        pagerank = dict.fromkeys(G, 0.0)
        communities = [set(G)] if G else []
    betweenness: dict[str, float] = (
        nx.betweenness_centrality(G) if G.number_of_nodes() > 2 else dict.fromkeys(G, 0.0)
    )
    return pagerank, betweenness, communities


def _node_payload(
    node: dict[str, Any],
    fm: dict[str, Any],
    G: nx.Graph[str],
    scores: dict[str, float],
    today: date | None,
) -> dict[str, Any]:
    """One renderer node. ``scores`` holds pr/bridge/comm plus the hub/bridge cut-offs."""
    nid = node["id"]
    degree = cast(int, G.degree(nid)) if nid in G else 0  # networkx stubs leave it unknown
    tags: list[Any] = fm.get("tags") or []
    pr, bridge = scores["pr"], scores["bridge"]
    return {
        "id": nid,
        "label": node["label"],
        # `cat` drives colour: the page's own frontmatter type for pages,
        # a synthetic "source" category for raw documents.
        "cat": "source" if node["type"] == "source" else str(fm.get("type", "concept")).lower(),
        "kind": node["type"],
        "comm": int(scores["comm"]),
        "deg": degree,
        "pr": round(pr, 5),
        "bridge": round(bridge, 5),
        "confidence": str(fm.get("confidence", "")).lower() or None,
        "created": _iso_or_none(fm.get("created")),
        "updated": _iso_or_none(fm.get("updated")),
        "tags": [str(t) for t in tags],
        "stale": bool(fm) and wiki_engine.is_page_stale(fm, today),
        "outdated": bool(scores.get("outdated")),
        "orphan": degree == 0,
        "hub": bool(pr) and pr >= scores["hub_cut"],
        "bridgeHub": bool(bridge) and bridge >= scores["bridge_cut"],
    }


def _edges(typed: dict[str, Any]) -> list[dict[str, str]]:
    """`related-to` is undirected, and which end the typed graph emits first
    depends on `Path.glob` order — i.e. on the filesystem. Orient those pairs
    alphabetically so the payload is byte-identical across machines;
    `derived-from` keeps its page → source direction (the renderer arrows it)."""
    return sorted(
        (
            {"s": min(e["from"], e["to"]), "t": max(e["from"], e["to"]), "type": e["type"]}
            if e["type"] in _UNDIRECTED
            else {"s": e["from"], "t": e["to"], "type": e["type"]}
            for e in typed["edges"]
        ),
        key=lambda e: (e["s"], e["t"], e["type"]),
    )


def export(today: date | None = None) -> dict[str, Any]:
    """Build the renderer payload from the live wiki. Deterministic."""
    typed, truncated = _cap(wiki_engine.build_typed_graph(), MAX_NODES)
    return _assemble(
        typed,
        truncated,
        _page_meta(),
        set(wiki_engine.outdated_pages(today)),
        wiki_engine.source_ranks(),
        today,
    )


def _assemble(
    typed: dict[str, Any],
    truncated: bool,
    meta: dict[str, dict[str, Any]],
    outdated: set[str],
    ranks: dict[str, int],
    today: date | None,
) -> dict[str, Any]:
    G = _to_networkx(typed)
    pagerank, betweenness, communities = _analytics(G)
    # Sort communities by their smallest member so ids are stable across runs
    # even if Louvain returns them in a different order.
    community_of = {
        node: i
        for i, group in enumerate(sorted(communities, key=lambda c: min(c)))
        for node in group
    }
    cuts = {
        "hub_cut": _quantile_threshold(list(pagerank.values()), _HUB_QUANTILE),
        "bridge_cut": _quantile_threshold(list(betweenness.values()), _BRIDGE_QUANTILE),
    }
    nodes = [
        _node_payload(
            node,
            meta.get(node["id"], {}),
            G,
            {
                **cuts,
                "pr": pagerank.get(node["id"], 0.0),
                "bridge": betweenness.get(node["id"], 0.0),
                "comm": community_of.get(node["id"], 0),
                "outdated": float(node["id"] in outdated),
            },
            today,
        )
        for node in sorted(typed["nodes"], key=lambda n: n["id"])
    ]
    for n in nodes:  # the pyramid layout's rows; only nodes whose class has a rank
        if n["id"] in ranks:
            n["rank"] = ranks[n["id"]]
    return {
        "nodes": nodes,
        "edges": _edges(typed),
        "communities": len(communities),
        "truncated": truncated,
        # Widget chrome follows the bundle's own language, detected in code from
        # the page titles — the same DE/EN heuristic the rest of the app pins on.
        "lang": lang.detect(" ".join(n["label"] for n in nodes)),
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
    }


class _Part(NamedTuple):
    """One level's contribution to the merged graph, ids qualified `<shard>::<id>`."""

    typed: dict[str, Any]
    meta: dict[str, dict[str, Any]]
    outdated: set[str]
    ranks: dict[str, int]


def _shard_part(shard: str, today: date | None) -> _Part:
    def q(ident: str) -> str:
        return f"{shard}::{ident}"

    with db_context.using_db(shard):  # the gate: a level above the clearance raises
        typed = wiki_engine.build_typed_graph()
        meta = _page_meta()
        outdated = wiki_engine.outdated_pages(today)
        ranks = wiki_engine.source_ranks()
    nodes = [{**n, "id": q(n["id"]), "_raw": n["id"], "_shard": shard} for n in typed["nodes"]]
    edges = [{**e, "from": q(e["from"]), "to": q(e["to"])} for e in typed["edges"]]
    return _Part(
        {"nodes": nodes, "edges": edges},
        {q(k): v for k, v in meta.items()},
        {q(o) for o in outdated},
        {q(k): v for k, v in ranks.items()},
    )


def _same_topic_edges(nodes: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Link the copies of one page or source that live at several levels (lowest first)."""
    copies: dict[str, list[tuple[int, str]]] = {}
    for n in nodes:
        level = classification.parse_shard(n["_shard"])[1]
        copies.setdefault(n["_raw"], []).append((level, n["id"]))
    edges: list[dict[str, str]] = []
    for group in copies.values():
        ordered = [nid for _, nid in sorted(group)]
        edges += [{"from": a, "to": b, "type": "same-topic"} for a, b in pairwise(ordered)]
    return edges


def export_levels(shards: tuple[str, ...], today: date | None = None) -> dict[str, Any]:
    """One payload over several classification levels of a DB (the Explorer's "All levels").

    Node ids are `<shard>::<id>` so equal page names at two levels stay two nodes; each node
    carries its `level`, `shard` and unqualified `name`. Links stay inside a level, and a
    `same-topic` edge joins the copies of one page or source across levels. Every shard is
    read through the gate: the caller passes only `db_context.reachable_shards(...)`.
    """
    parts = [_shard_part(shard, today) for shard in shards]
    nodes = [n for p in parts for n in p.typed["nodes"]]
    edges = [e for p in parts for e in p.typed["edges"]] + _same_topic_edges(nodes)
    typed, truncated = _cap({"nodes": nodes, "edges": edges}, MAX_NODES)
    payload = _assemble(
        typed,
        truncated,
        {k: v for p in parts for k, v in p.meta.items()},
        {o for p in parts for o in p.outdated},
        {k: v for p in parts for k, v in p.ranks.items()},
        today,
    )
    by_id = {n["id"]: n for n in typed["nodes"]}
    for node in payload["nodes"]:
        src = by_id[node["id"]]
        node["shard"], node["name"] = src["_shard"], src["_raw"]
        node["level"] = classification.parse_shard(src["_shard"])[1]
    levels = sorted({n["level"] for n in payload["nodes"]})
    payload["levels"] = {str(lv): classification.level_label(lv) for lv in levels}
    return payload


def health(payload: dict[str, Any], today: date | None = None) -> dict[str, Any]:
    """Bundle health from an exported payload: what is growing, what sits alone.

    Pure and deterministic — it reads only what `export()` already stamped, so
    the panel can never disagree with the dots on the canvas (orphan, stale and
    low-confidence are the payload's own flags, not a second computation).
    Counts cover *pages* only: a raw source document has no health of its own.
    """
    pages = [n for n in payload["nodes"] if n["kind"] == "page"]
    cutoff = (today or datetime.now(UTC).date()) - timedelta(days=HEALTH_WINDOW_DAYS)

    clusters: dict[int, dict[str, Any]] = {}
    for node in pages:
        c = clusters.setdefault(node["comm"], {"size": 0, "recent": 0, "top": node})
        c["size"] += 1
        if _is_recent(node["updated"], cutoff):
            c["recent"] += 1
        if node["pr"] > c["top"]["pr"]:
            c["top"] = node

    return {
        "pages": len(pages),
        "sources": len(payload["nodes"]) - len(pages),
        "orphans": sorted(n["id"] for n in pages if n["orphan"]),
        "stale": sorted(n["id"] for n in pages if n["stale"]),
        "outdated": sorted(n["id"] for n in pages if n.get("outdated")),
        "low_confidence": sorted(n["id"] for n in pages if n["confidence"] == "low"),
        # Growth first, then size: the panel answers "which clusters are moving".
        "clusters": sorted(
            (
                {"id": cid, "label": c["top"]["label"], "size": c["size"], "recent": c["recent"]}
                for cid, c in clusters.items()
            ),
            key=lambda c: (-c["recent"], -c["size"], c["label"]),
        ),
        "window_days": HEALTH_WINDOW_DAYS,
    }


def _is_recent(updated: str | None, cutoff: date) -> bool:
    """`updated` is the ISO date `export()` stamped, or None on a bare page."""
    if not updated:
        return False
    try:
        return date.fromisoformat(updated) >= cutoff
    except ValueError:
        return False


def _iso_or_none(value: object) -> str | None:
    """Frontmatter dates arrive as `date` or `str`; normalise to ISO or None."""
    if not value:
        return None
    return str(value)[:10]
