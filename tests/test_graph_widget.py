"""Contract tests for the graph component mount (src/graph_widget.py).

Runs the widget through Streamlit's own `AppTest`, so the assertions cover the
real script-run path: the component gets declared (which is what registers its
static route), and the payload the renderer reads actually reaches the frontend
with the keys `assets/graph/index.html` expects.
"""

import json

import pytest
from streamlit.testing.v1 import AppTest

import graph_export
import graph_widget

SCRIPT = """
import sys
from pathlib import Path
sys.path.insert(0, "src")
import db_context, graph_widget
db_context.DATA_ROOT = Path({root!r})
db_context.set_active_db("test")
graph_widget.render_graph(overlays={overlays!r}, size_by={size_by!r})
"""


@pytest.fixture()
def app(wiki_dir, tmp_path):
    (wiki_dir / "alpha.md").write_text(
        '---\ntitle: "Alpha"\ntype: concept\nrelated: ["beta.md"]\n'
        'sources: ["doc.pdf"]\ncreated: "2026-01-01"\nupdated: "2026-07-01"\n'
        "confidence: high\n---\n\nAlpha body.\n"
    )
    (wiki_dir / "beta.md").write_text(
        '---\ntitle: "Beta"\ntype: entity\nrelated: ["alpha.md"]\n'
        'sources: ["doc.pdf"]\ncreated: "2026-01-01"\nupdated: "2026-07-01"\n'
        "confidence: low\n---\n\nBeta body.\n"
    )

    def _run(overlays=("hubs",), size_by="pagerank"):
        graph_widget._payload.clear()  # the fixture wiki is new on every test
        src = SCRIPT.format(root=str(tmp_path), overlays=list(overlays), size_by=size_by)
        return AppTest.from_string(src, default_timeout=60).run()

    return _run


def _component_args(at):
    instances = list(at.get("component_instance"))
    assert len(instances) == 1, "the graph must mount exactly one component"
    return instances[0].proto, json.loads(instances[0].proto.json_args)


def test_component_mounts_with_payload(app):
    at = app()
    assert not at.exception
    proto, args = _component_args(at)
    assert proto.component_name.endswith("wiki_graph")
    ids = {n["id"] for n in args["graph"]["nodes"]}
    assert {"alpha.md", "beta.md", "source::doc.pdf"} <= ids


def test_payload_carries_every_key_the_renderer_reads(app):
    """index.html reads these by name; a rename here is a silently blank canvas."""
    _, args = _component_args(app())
    assert {"graph", "overlays", "sizeBy", "backdrop", "strings", "accent", "height"} <= set(args)
    node = args["graph"]["nodes"][0]
    assert {"id", "label", "cat", "kind", "comm", "deg", "pr", "bridge",
            "confidence", "stale", "orphan", "hub", "bridgeHub", "tags"} <= set(node)
    edge = args["graph"]["edges"][0]
    assert {"s", "t", "type"} <= set(edge)


def test_controls_reach_the_renderer(app):
    _, args = _component_args(app(overlays=["stale", "bridges"], size_by="pagerank"))
    assert args["overlays"] == ["stale", "bridges"]
    assert args["sizeBy"] == "pagerank"


def test_chrome_language_follows_the_bundle(app):
    """Widget strings are pinned in code, like every other language decision."""
    _, args = _component_args(app())
    assert args["graph"]["lang"] in ("de", "en")
    assert args["strings"]["search"] == graph_widget._STRINGS[args["graph"]["lang"]]["search"]


def test_accent_comes_from_the_streamlit_theme(app):
    _, args = _component_args(app())
    assert args["accent"].startswith("#")


def test_health_reads_the_drawn_payload(app):
    """The side panel must summarise the same payload the canvas got."""
    app()  # populates the cache for the fixture bundle
    health = graph_widget.graph_health()
    assert health == graph_export.health(graph_widget.graph_stats())
    assert health["pages"] == 2 and health["low_confidence"] == ["beta.md"]
