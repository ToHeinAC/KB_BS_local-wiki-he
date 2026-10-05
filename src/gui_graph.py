"""The Explorer's map: the existing canvas renderer in an iframe, plus the numbers beside it.

`src/assets/graph/index.html` speaks the Streamlit component protocol over `postMessage`.
`GRAPH_JS` plays the host's side of it in the page: it answers the component's handshake with
the current arguments and forwards a double-click to Python as the `graph_open` event, so no
page reload happens (docs/ui.md §Graph view). The renderer itself is not touched.
"""

import json
from pathlib import Path
from typing import Any

from nicegui import app, ui

import classification
import graph_widget
import ui_logic

ASSETS = Path(__file__).parent / "assets" / "graph"
ASSET_URL = "graph-assets"
ACCENT = "#8f2d1a"  # the Broadsheet oxide; the paper palette draws the map on paper
MAP_HEIGHT = 560
_METRIC = {"pagerank": "pr", "degree": "deg"}

GRAPH_JS = """<script>
(function () {
  let ready = false;
  let pending = null;
  const frame = () => document.getElementById('wiki-graph');
  const send = () => {
    const f = frame();
    if (ready && pending && f && f.contentWindow) {
      f.contentWindow.postMessage({type: 'streamlit:render', args: pending}, '*');
    }
  };
  window.wikiGraphRender = (args) => { pending = args; send(); };
  window.addEventListener('message', (e) => {
    const f = frame();
    if (!f || e.source !== f.contentWindow || !e.data) return;
    if (e.data.type === 'streamlit:componentReady') { ready = true; send(); }
    else if (e.data.type === 'streamlit:setComponentValue') {
      emitEvent('graph_open', e.data.value);
    }
  });
})();
</script>"""


def register_assets() -> None:
    """Serve the renderer next to the pages (relative to the mount path)."""
    app.add_static_files(f"/{ASSET_URL}", ASSETS)


def _type_label(node: dict[str, Any]) -> str:
    label = str(node["cat"]).replace("-", " ").capitalize()
    level = int(node.get("level", 0))
    return f"{label} · {classification.level_label(level)}" if level else label


def standings(payload: dict[str, Any], size_by: str, limit: int = 10) -> list[dict[str, Any]]:
    """The top pages by PageRank or connections, for the table beside the map."""
    key = _METRIC[size_by]
    pages = [n for n in payload["nodes"] if n.get("kind") == "page"]
    ranked = sorted(pages, key=lambda n: (-n[key], n["label"]))[:limit]
    top = max((n[key] for n in ranked), default=0)
    return [
        {
            "rank": i,
            "id": n["id"],
            "label": n["label"],
            "type": _type_label(n),
            "value": f"{n[key]:.3f}" if size_by == "pagerank" else str(int(n[key])),
            "width": n[key] / top if top else 0.0,
        }
        for i, n in enumerate(ranked, start=1)
    ]


def caption(payload: dict[str, Any]) -> str:
    pages = sum(1 for n in payload["nodes"] if n.get("kind") == "page")
    text = f"{pages} pages, {len(payload['edges'])} links, {payload['communities']} clusters"
    levels = len(payload.get("levels") or {})
    return f"{text}, {levels} levels" if levels > 1 else text


def graph_click(value: dict[str, Any] | None) -> tuple[str, str] | None:
    """What a double-click on the map means: open a page, or explain a source node."""
    node = (value or {}).get("node")
    if not node:
        return None
    if value and value.get("kind") == "page":
        return "open", str(node)
    return (
        "notice",
        f"{str(node).rpartition('source::')[2]} is an original document, not a wiki page.",
    )


def map_data(
    *,
    overlays: list[str],
    size_by: str,
    layout: str,
    selected: str | None,
    all_levels: bool = False,
) -> dict[str, Any]:
    """Renderer arguments, standings and caption for the bound level, or for every reachable
    level merged when `all_levels` (blocking: run in a worker)."""
    args = graph_widget.render_args(
        overlays=[ui_logic.OVERLAY_LABELS[p] for p in overlays],
        size_by=size_by,
        layout=layout,
        height=MAP_HEIGHT,
        paper=True,
        accent=ACCENT,
        selected=selected,
        all_levels=all_levels,
    )
    payload = args["graph"]
    return {"args": args, "standings": standings(payload, size_by), "caption": caption(payload)}


def push_args(args: dict[str, Any]) -> None:
    """Hand the renderer its arguments (it draws when its iframe has announced itself)."""
    ui.run_javascript(f"wikiGraphRender({json.dumps(args)})")
