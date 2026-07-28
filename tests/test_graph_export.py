"""Tests for the neural graph payload (src/graph_export.py)."""

from datetime import date

import pytest

import graph_export
import wiki_engine


def _page(wiki_dir, filename, *, title, ptype="concept", related=(), sources=(),
          confidence="high", updated=None, expires=None):
    fm = [
        "---",
        f'title: "{title}"',
        f"type: {ptype}",
        "related: [" + ", ".join(f'"{r}"' for r in related) + "]",
        "sources: [" + ", ".join(f'"{s}"' for s in sources) + "]",
        'created: "2026-01-01"',
        f'updated: "{updated or "2026-07-01"}"',
        f"confidence: {confidence}",
    ]
    if expires is not None:
        fm.append(f"expires_after_days: {expires}")
    fm.append("---")
    (wiki_dir / filename).write_text("\n".join(fm) + f"\n\n# {title}\n\nBody text.\n")


@pytest.fixture()
def bundle(wiki_dir):
    """A small typed bundle: a linked pair, a source, and an orphan."""
    _page(wiki_dir, "alpha.md", title="Alpha", related=["beta.md"], sources=["doc-a.pdf"])
    _page(wiki_dir, "beta.md", title="Beta", ptype="entity", related=["alpha.md"],
          sources=["doc-a.pdf"], confidence="low")
    _page(wiki_dir, "gamma.md", title="Gamma", sources=["doc-b.pdf"])
    _page(wiki_dir, "lonely.md", title="Lonely")
    return wiki_dir


def _by_id(payload):
    return {n["id"]: n for n in payload["nodes"]}


def test_nodes_cover_pages_and_sources(bundle):
    nodes = _by_id(graph_export.export())
    assert {"alpha.md", "beta.md", "gamma.md", "lonely.md"} <= set(nodes)
    assert "source::doc-a.pdf" in nodes
    assert nodes["source::doc-a.pdf"]["cat"] == "source"
    assert nodes["alpha.md"]["cat"] == "concept"
    assert nodes["beta.md"]["cat"] == "entity"


def test_system_pages_excluded(bundle):
    """index.md / log.md are wiki chrome, not knowledge nodes."""
    (bundle / "index.md").write_text("---\ntitle: Index\n---\n\n# Pages\n")
    (bundle / "log.md").write_text("## 2026-07-01\n- 10:00 — test\n")
    ids = set(_by_id(graph_export.export()))
    assert "index.md" not in ids and "log.md" not in ids


def test_edges_carry_type_and_are_sorted(bundle):
    edges = graph_export.export()["edges"]
    assert edges == sorted(edges, key=lambda e: (e["s"], e["t"], e["type"]))
    kinds = {(e["s"], e["t"]): e["type"] for e in edges}
    # `related-to` is oriented alphabetically so glob order cannot leak in.
    assert kinds.get(("alpha.md", "beta.md")) == "related-to"
    # `derived-from` keeps its page → source direction.
    assert kinds.get(("alpha.md", "source::doc-a.pdf")) == "derived-from"


def test_orphan_flag(bundle):
    nodes = _by_id(graph_export.export())
    assert nodes["lonely.md"]["orphan"] is True
    assert nodes["alpha.md"]["orphan"] is False


def test_analytics_present_and_rounded(bundle):
    payload = graph_export.export()
    nodes = _by_id(payload)
    assert payload["communities"] >= 1
    assert nodes["alpha.md"]["deg"] >= 2
    assert nodes["alpha.md"]["pr"] > 0
    # Every node carries a community id and rounded scores.
    for node in payload["nodes"]:
        assert isinstance(node["comm"], int)
        assert node["pr"] == round(node["pr"], 5)
        assert node["bridge"] == round(node["bridge"], 5)


def test_stale_crosses_the_date_boundary(wiki_dir):
    _page(wiki_dir, "fresh.md", title="Fresh", updated="2026-01-01", expires=90)
    on_boundary = graph_export.export(today=date(2026, 4, 1))  # 90 days
    after = graph_export.export(today=date(2026, 4, 2))        # 91 days
    assert _by_id(on_boundary)["fresh.md"]["stale"] is False
    assert _by_id(after)["fresh.md"]["stale"] is True


def test_stale_matches_wiki_engine(bundle):
    """The graph's amber layer and the nav tree's ⚠️ must never disagree."""
    today = date(2030, 1, 1)
    expected = set(wiki_engine.stale_pages())
    flagged = {n["id"] for n in graph_export.export(today=today)["nodes"] if n["stale"]}
    assert flagged >= expected & {"alpha.md", "beta.md", "gamma.md", "lonely.md"}


def test_confidence_is_carried_through(bundle):
    nodes = _by_id(graph_export.export())
    assert nodes["beta.md"]["confidence"] == "low"
    # Source nodes have no frontmatter of their own.
    assert nodes["source::doc-a.pdf"]["confidence"] is None


def test_export_is_deterministic(bundle):
    a, b = graph_export.export(), graph_export.export()
    a.pop("generated_at"), b.pop("generated_at")
    assert a == b


def test_every_page_node_opens(bundle):
    """Navigation contract: a page node id must resolve in the reader."""
    for node in graph_export.export()["nodes"]:
        if node["kind"] != "page":
            assert node["id"].startswith("source::")
            continue
        parsed = wiki_engine.read_page_parsed(node["id"])
        assert parsed["content"].strip()


def test_max_nodes_guardrail(wiki_dir, monkeypatch):
    for i in range(12):
        _page(wiki_dir, f"p{i:02d}.md", title=f"P{i}", related=["p00.md"] if i else [])
    monkeypatch.setattr(graph_export, "MAX_NODES", 5)
    payload = graph_export.export()
    assert payload["truncated"] is True
    assert len(payload["nodes"]) == 5
    # The best-connected node survives; dangling edges are dropped.
    kept = {n["id"] for n in payload["nodes"]}
    assert "p00.md" in kept
    assert all(e["s"] in kept and e["t"] in kept for e in payload["edges"])


def test_empty_wiki_is_safe(wiki_dir):
    payload = graph_export.export()
    assert payload["nodes"] == [] and payload["edges"] == []


# --- health view (§6.9.3 item 5) ---------------------------------------------


def test_health_counts_pages_not_sources(bundle):
    h = graph_export.health(graph_export.export(), today=date(2026, 7, 28))
    assert h["pages"] == 4
    assert h["sources"] == 2
    assert h["orphans"] == ["lonely.md"]
    assert h["low_confidence"] == ["beta.md"]


def test_health_growth_window(bundle):
    payload = graph_export.export()
    recent = graph_export.health(payload, today=date(2026, 7, 28))
    # All four pages carry updated: 2026-07-01 — inside a 30-day window …
    assert sum(c["recent"] for c in recent["clusters"]) == 4
    # … and outside it once the window has passed.
    later = graph_export.health(payload, today=date(2026, 12, 31))
    assert sum(c["recent"] for c in later["clusters"]) == 0
    assert recent["window_days"] == graph_export.HEALTH_WINDOW_DAYS


def test_health_clusters_are_labelled_and_ranked(bundle):
    h = graph_export.health(graph_export.export(), today=date(2026, 7, 28))
    assert h["clusters"], "every page belongs to a cluster"
    # Labelled by their most central page, never by a source document.
    for cluster in h["clusters"]:
        assert cluster["size"] >= 1
        assert not cluster["label"].startswith("source::")
    # Ranked by growth, then size — the "which clusters are growing" question.
    ranked = [(-c["recent"], -c["size"], c["label"]) for c in h["clusters"]]
    assert ranked == sorted(ranked)
    # Pages are partitioned across clusters, sources excluded.
    assert sum(c["size"] for c in h["clusters"]) == h["pages"]


def test_health_stale_agrees_with_the_payload(wiki_dir):
    _page(wiki_dir, "fresh.md", title="Fresh", updated="2026-01-01", expires=90)
    payload = graph_export.export(today=date(2026, 4, 2))
    assert graph_export.health(payload)["stale"] == ["fresh.md"]


def test_health_on_empty_wiki(wiki_dir):
    h = graph_export.health(graph_export.export())
    assert h["pages"] == 0 and h["clusters"] == [] and h["orphans"] == []
