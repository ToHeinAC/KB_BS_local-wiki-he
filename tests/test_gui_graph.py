"""Pure helpers behind the Broadsheet Explorer's map (src/gui_graph.py)."""

import gui_graph

PAYLOAD = {
    "nodes": [
        {"id": "a.md", "label": "Alpha", "kind": "page", "cat": "concept", "pr": 0.4, "deg": 2},
        {"id": "b.md", "label": "Beta", "kind": "page", "cat": "entity", "pr": 0.2, "deg": 5},
        {"id": "c.md", "label": "Gamma", "kind": "page", "cat": "concept", "pr": 0.1, "deg": 1},
        {"id": "source::x.pdf", "label": "x.pdf", "kind": "source", "cat": "source", "pr": 0.9},
    ],
    "edges": [{"s": "a.md", "t": "b.md", "type": "related-to"}] * 3,
    "communities": 2,
}


def test_standings_rank_pages_by_the_chosen_metric_and_skip_sources() -> None:
    rows = gui_graph.standings(PAYLOAD, "pagerank", limit=2)
    assert [(r["rank"], r["id"], r["label"], r["type"]) for r in rows] == [
        (1, "a.md", "Alpha", "Concept"),
        (2, "b.md", "Beta", "Entity"),
    ]
    assert rows[0]["width"] == 1.0
    assert rows[1]["width"] == 0.5
    by_degree = gui_graph.standings(PAYLOAD, "degree", limit=3)
    assert [r["id"] for r in by_degree] == ["b.md", "a.md", "c.md"]
    assert by_degree[0]["value"] == "5"


def test_standings_of_an_empty_graph_is_empty() -> None:
    assert gui_graph.standings({"nodes": []}, "pagerank") == []
    assert gui_graph.standings({"nodes": [{"kind": "source", "cat": "source"}]}, "degree") == []


def test_caption_counts_pages_links_and_clusters() -> None:
    assert gui_graph.caption(PAYLOAD) == "3 pages, 3 links, 2 clusters"
    assert gui_graph.caption({"nodes": [], "edges": [], "communities": 0}) == (
        "0 pages, 0 links, 0 clusters"
    )


def test_a_double_clicked_page_opens_and_a_source_only_explains_itself() -> None:
    assert gui_graph.graph_click({"node": "a.md", "kind": "page", "n": 1}) == ("open", "a.md")
    notice = gui_graph.graph_click({"node": "source::x.pdf", "kind": "source", "n": 2})
    assert notice == ("notice", "x.pdf is an original document, not a wiki page.")


def test_malformed_component_values_are_ignored() -> None:
    assert gui_graph.graph_click(None) is None
    assert gui_graph.graph_click({}) is None
    assert gui_graph.graph_click({"node": "", "kind": "page"}) is None


def test_the_shim_answers_the_component_handshake_and_forwards_double_clicks() -> None:
    js = gui_graph.GRAPH_JS
    assert "streamlit:componentReady" in js
    assert "streamlit:render" in js
    assert "streamlit:setComponentValue" in js
    assert "emitEvent('graph_open'" in js
    assert "wikiGraphRender" in js
