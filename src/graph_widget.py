"""Streamlit mount for the neural graph renderer.

Declared as a **static-path** component (`src/assets/graph/`), not a
`components.html` srcdoc, for one reason: a static component is bidirectional,
so a node double-click comes back into Python as a return value (a single
click only selects, and never leaves the canvas).

The obvious alternative — navigating the top window to `?page=<slug>` — is a
full page load, and this app gates on `st.session_state["user"]` (app.py) with
the active DB in session state too. A click would therefore bounce the user to
the login screen. The component protocol reruns the script instead: the session,
the chat history and the reader position all survive. `declare_component(path=…)`
serves the directory through Streamlit itself, so it inherits `baseUrlPath`
(`/wiwi/`) and stays same-origin behind the reverse proxy without any of
`gpu_widget.py`'s route injection.

The payload is cached on the wiki bundle's signature (file count + newest mtime),
so an ingest invalidates it by touching files — no explicit hook in `ingest_end`
to keep in sync.
"""

from __future__ import annotations

import os
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

import db_context
import graph_export

_ASSETS = Path(__file__).parent / "assets" / "graph"

RENDERER = os.getenv("GRAPH_RENDERER", "legacy").strip().lower()

# Backdrop behind the canvas: `galaxy` (the Hubble image shipped in the asset
# dir) or `none` (flat `--bg`). Decorative only — nothing about the graph, its
# analytics or its interactions changes with it.
BACKDROP = os.getenv("GRAPH_BACKDROP", "galaxy").strip().lower()

# Widget chrome only. Page labels are already language-correct — they come from
# the pages' own `title` — so this is the same DE/EN split the rest of the app
# pins, applied to the handful of strings the renderer draws itself.
_STRINGS = {
    "de": {
        "search": "Seite suchen…", "type": "Typ", "links": "Verbindungen",
        "pagerank": "PageRank", "bridge": "Brücken-Score", "community": "Cluster",
        "confidence": "Konfidenz", "updated": "Aktualisiert",
        "nodes": "Knoten", "edges": "Kanten", "clusters": "Cluster",
        "truncated": "gekürzt", "opened": "Doppelklick öffnet die Seite im Reader",
        "sourceNode": "Quelldokument (keine Wiki-Seite)",
        "rankPr": "Nach PageRank sortiert", "rankDeg": "Nach Verbindungen sortiert",
        "rankAll": "gesamter Graph", "rankSel": "Auswahl",
        "empty": "Noch keine verknüpften Seiten.",
    },
    "en": {
        "search": "Search pages…", "type": "Type", "links": "Links",
        "pagerank": "PageRank", "bridge": "Bridge score", "community": "Cluster",
        "confidence": "Confidence", "updated": "Updated",
        "nodes": "nodes", "edges": "edges", "clusters": "clusters",
        "truncated": "truncated", "opened": "Double-click opens the page in the reader",
        "sourceNode": "Source document (not a wiki page)",
        "rankPr": "Ranked by PageRank", "rankDeg": "Ranked by connections",
        "rankAll": "whole graph", "rankSel": "selection",
        "empty": "No linked pages yet.",
    },
}


_COMPONENT = None


def _component():
    """Declare once per process, lazily.

    `declare_component` only registers the `<base>/component/…` route when it
    runs inside a ScriptRunContext (it silently skips otherwise, leaving the
    iframe on a 404). Declaring here rather than at import time guarantees that
    context, since this is only ever reached from a script run.
    """
    global _COMPONENT
    if _COMPONENT is None:
        _COMPONENT = components.declare_component("wiki_graph", path=str(_ASSETS))
    return _COMPONENT


def _bundle_signature() -> str:
    """Cheap change detector for the wiki bundle: count + newest mtime."""
    wiki = db_context.wiki_dir()
    files = list(wiki.rglob("*.md")) if wiki.exists() else []
    newest = max((f.stat().st_mtime_ns for f in files), default=0)
    return f"{db_context.get_active_db()}:{len(files)}:{newest}"


@st.cache_data(show_spinner=False)
def _payload(signature: str) -> dict:
    return graph_export.export()


def render_graph(
    *, overlays: list[str], size_by: str = "pagerank", height: int = 720
) -> dict | None:
    """Draw the graph. Returns the double-clicked node `{node, kind, n}` or None.

    `size_by` picks the metric a dot's radius and the ranked-circle chart show:
    `pagerank` (default) or `degree`.
    """
    payload = _payload(_bundle_signature())
    strings = _STRINGS.get(payload["lang"], _STRINGS["en"])
    return _component()(
        graph=payload,
        overlays=overlays,
        sizeBy=size_by,
        backdrop=BACKDROP,
        strings=strings,
        accent=st.get_option("theme.primaryColor") or "#4a9eff",
        selected=st.session_state.get("explorer_selected_page"),
        height=height,
        default=None,
    )


def graph_stats() -> dict:
    """Payload-level counts for captions, without re-exporting."""
    return _payload(_bundle_signature())
