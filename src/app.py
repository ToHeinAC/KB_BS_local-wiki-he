"""LocalWiki — Streamlit UI."""

import gc
import os
import re
import tempfile
from pathlib import Path
from urllib.parse import urlparse

import streamlit as st
from dotenv import load_dotenv

load_dotenv()

import auth
import db_context
import dedup
import file_processor
import gpu_widget
import graph_widget
import lex_index
import md_convert
import metadata_extract
import ollama_client
import theme
import tools
import wiki_engine
import agent as research_agent
import deep_research_agent
import chat_agent

st.set_page_config(
    page_title="LocalWiki",
    page_icon="📖",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Frontend skin (src/theme.py). `FRONTEND` in .env picks it: `default` keeps the
# editorial Forest/Slate palette, `newspaper` swaps in the broadsheet chrome.
# `_t` keeps the same token names either way — gpu_widget and the conditional
# style blocks below read them by name.
if "theme" not in st.session_state:
    st.session_state["theme"] = "Forest"

_t = theme.inject_css()
_NEWSPAPER = theme.is_newspaper()


_CHUNK_SUFFIX_RE = re.compile(r"\s*\[Teil\s+\d+/\d+\]\s*$")
_CITE_SECTION_SUFFIX_RE = re.compile(r"\s*[§#].*$")


@st.dialog("Source", width="large")
def _show_md_dialog(title: str, content: str) -> None:
    st.subheader(title)
    st.markdown(content)
    st.download_button(
        "Download",
        data=content,
        file_name=title,
        mime="text/markdown",
        key=f"dl_src_{title}",
    )


@st.dialog("Confirm ingest")
def _confirm_ingest_dialog(db_name: str, what: str) -> None:
    st.warning(f"Ingest **{what}** into database **{db_name}**?")
    st.caption("The document(s) will be written to the currently selected database. "
               "Make sure this is the right one.")
    c1, c2 = st.columns(2)
    if c1.button("Confirm", type="primary", key="confirm_ingest_btn"):
        st.session_state["batch_confirmed"] = True
        st.rerun()
    if c2.button("Cancel", key="cancel_ingest_btn"):
        st.session_state.pop("pending_batch", None)
        st.rerun()


@st.dialog("Concept", width="large")
def _show_node_details(node_id: str, graph: dict) -> None:
    nodes_by_id = {n["id"]: n for n in graph["nodes"]}
    node = nodes_by_id.get(node_id)
    if not node:
        st.error(f"Unknown node: {node_id}")
        return
    st.subheader(node["label"])
    if node["type"] == "page":
        try:
            parsed = wiki_engine.read_page_parsed(node_id)
            st.markdown(parsed["content"])
        except Exception as exc:
            st.warning(f"Could not load page body: {exc}")
    else:
        st.caption(f"Raw source document: `{node['label']}`")
    st.markdown("### Connections")
    rows = []
    for e in graph["edges"]:
        if e["from"] == node_id:
            other = nodes_by_id.get(e["to"], {}).get("label", e["to"])
            arrow = "→" if e["type"] == "derived-from" else "↔"
            rows.append(f"- {arrow} **{other}** — `{e['type']}`")
        elif e["to"] == node_id:
            other = nodes_by_id.get(e["from"], {}).get("label", e["from"])
            arrow = "←" if e["type"] == "derived-from" else "↔"
            rows.append(f"- {arrow} **{other}** — `{e['type']}`")
    if rows:
        st.markdown("\n".join(rows))
    else:
        st.caption("No connections.")


def _render_legacy_graph() -> None:
    """The original vis.js typed graph (GRAPH_RENDERER=legacy).

    Kept as the default until the neural renderer has parity; unchanged apart
    from being lifted out of the page body so the feature flag can pick one.
    """
    try:
        import json as _json
        graph = wiki_engine.build_typed_graph()
        tcol1, tcol2 = st.columns(2)
        show_names = tcol1.toggle("Node names", value=True)
        show_sources = tcol2.toggle("Source nodes", value=True)

        def _abbrev(text: str, n: int = 5) -> str:
            return " ".join(str(text).replace("-", " ").split()[:n])

        nodes_data: list[dict] = []
        edges_data: list[dict] = []
        keep_ids: set[str] = set()
        for node in graph["nodes"]:
            if node["type"] == "source" and not show_sources:
                continue
            keep_ids.add(node["id"])
            label = node["label"]
            nodes_data.append({
                "id": node["id"],
                "group": node["type"],
                "label": (_abbrev(label) if node["type"] == "page" else label) if show_names else "",
                "title": label,
            })
        for edge in graph["edges"]:
            if edge["from"] not in keep_ids or edge["to"] not in keep_ids:
                continue
            edges_data.append({
                "from": edge["from"],
                "to": edge["to"],
                "group": edge["type"],
                "dashes": edge["type"] == "derived-from",
                "color": "#d97a3a" if edge["type"] == "derived-from" else "#aaa",
                "arrows": "to" if edge["type"] == "derived-from" else "",
            })

        html = f"""<!DOCTYPE html><html><head>
<script src="https://cdnjs.cloudflare.com/ajax/libs/vis-network/9.1.2/dist/vis-network.min.js"
  integrity="sha512-LnvoEWDFrqGHlHmDD2101OrLcbsfkrzoSpvtSQtxK3RMnRV0eOkhhBN2dXHKRrUU8p2DGRTk35n4O8nWSVe1mQ=="
  crossorigin="anonymous" referrerpolicy="no-referrer"></script>
<style>body{{margin:0}}#g{{width:100%;height:595px;background:#fff;border:1px solid #ddd}}</style>
</head><body>
<div id="g"></div>
<script>
var net=new vis.Network(document.getElementById('g'),
  {{nodes:new vis.DataSet({_json.dumps(nodes_data)}),
    edges:new vis.DataSet({_json.dumps(edges_data)})}},
  {{groups:{{
      page:{{shape:"dot",size:18,color:{{background:"#97c2fc",border:"#2B7CE9"}}}},
      source:{{shape:"diamond",size:22,color:{{background:"#f3b27a",border:"#d97a3a"}}}}
    }},
    nodes:{{font:{{size:14,color:"#234637"}}}},
    edges:{{font:{{size:11,color:"#555",align:"middle"}},
            smooth:{{type:"continuous"}}}},
    physics:{{barnesHut:{{gravitationalConstant:-5000,springLength:120,springConstant:0.04}},
              stabilization:{{fit:true,iterations:300}}}}}});
</script></body></html>"""
        st.components.v1.html(html, height=620, scrolling=True)
        st.caption(
            "**Legend:** blue dot = concept/entity, orange diamond = source document. "
            "Solid grey = `related-to` (concept ↔ concept, incl. shared-source clique). "
            "Dashed orange → = `derived-from` (concept → source)."
        )
        orphans = wiki_engine.find_orphans()
        if orphans:
            st.caption(f"**{len(orphans)} orphan(s)** (no in-links): " + ", ".join(f"`{o}`" for o in orphans[:20]))

        st.markdown("### Inspect a node")
        node_options = {n["label"]: n["id"] for n in graph["nodes"]}
        picked_label = st.selectbox(
            "Open details for a node",
            options=["—"] + sorted(node_options.keys()),
            key="explorer_inspect_pick",
            label_visibility="collapsed",
        )
        if picked_label and picked_label != "—":
            _show_node_details(node_options[picked_label], graph)
    except Exception as exc:
        st.error(f"Graph render failed: {exc}")


_GRAPH_LAYOUTS = {"Galaxy": "galaxy", "Ranked": "arc", "Clusters": "radial"}


def _render_neural_graph(layout: str) -> None:
    """Canvas neural renderer over the same typed graph.

    `layout` arrives already resolved to its internal key: the switch is drawn by
    the Explorer page so it can share a row with the Graph|Tree toggle, which
    means this function no longer owns it.

    Overlays are a Streamlit widget (native chrome, and it persists in session
    state across reruns); pan/zoom/hover/search/selection stay inside the canvas.
    Only a *double* click comes back through the component protocol — no page
    reload, so the session survives (see src/graph_widget.py).

    An opened page lands in the side panel, never in a modal: a dialog hides the
    graph it was opened from, so the map and the page cannot be read together.
    The panel is **collapsed by default** — the map is the point of this view, so
    it gets the width until the reader or the health view is asked for; open, it
    takes a third of the row. Collapsed leaves a one-button rail (`«`); opening a
    node opens the panel with it.
    The controls stay above the split so the panel column never nests columns
    twice.
    """
    overlay_labels = {
        "Hubs": "hubs", "Bridges": "bridges", "Orphans": "orphans",
        "Stale": "stale", "Low confidence": "confidence",
    }
    # The metric and the overlays refine what is already drawn, so they live
    # behind a collapsed disclosure rather than competing with the layout switch.
    # Both still instantiate every run (an expander renders its body whether open
    # or shut), so their session-state persistence is unchanged.
    with st.expander("Advanced", expanded=False, key="graph_advanced"):
        acol1, acol2 = st.columns([1, 2])
    by_degree = acol1.toggle(
        "Connections", key="graph_by_degree",
        help="Off: dots and the ranked chart show PageRank. On: number of connections.",
    )
    picked = acol2.multiselect(
        "Style Options", list(overlay_labels), default=["Hubs"],
        key="graph_overlays", placeholder="Style Options",
        help=(
            "Highlights only — no node is added or hidden.\n\n"
            "- **Hubs** — pages in the top 10% by PageRank (most central): "
            "wider glow.\n"
            "- **Bridges** — pages in the top 10% by betweenness (they connect "
            "otherwise separate clusters): light ring.\n"
            "- **Orphans** — pages with no links at all, in or out: grey dot.\n"
            "- **Stale** — pages past their freshness window "
            "(`updated` + `expires_after_days`): pulsing amber ring.\n"
            "- **Low confidence** — pages with `confidence: low` in their "
            "frontmatter: dimmed dot."
        ),
    )
    panel_open = st.session_state.get("explorer_panel_open", False)
    graph_col, panel_col = st.columns(
        [2, 1] if panel_open else [30, 1], gap="medium" if panel_open else "small"
    )
    with graph_col:
        try:
            clicked = graph_widget.render_graph(
                overlays=[overlay_labels[p] for p in picked],
                size_by="degree" if by_degree else "pagerank",
                layout=layout,
                # Newspaper skin draws the same graph as an engraved plate; the
                # dark canvas would be a hole in the page.
                paper=_NEWSPAPER,
            )
        except Exception as exc:
            st.error(f"Graph render failed: {exc}")
            return

        stats = graph_widget.graph_stats()
        st.caption(
            f"{len(stats['nodes'])} nodes · {len(stats['edges'])} edges · "
            f"{stats['communities']} clusters. Hover for the 2-hop neighbourhood, "
            "click a node for its properties, double-click to open the page."
        )

    # `n` is a click counter: without it, clicking the same node twice would
    # send an identical value and Streamlit would not rerun. Handled between the
    # two columns so the panel below renders the page that was just opened —
    # unless the panel was collapsed, where the column widths for this run are
    # already fixed and only a rerun can widen it.
    if clicked and clicked.get("n") != st.session_state.get("graph_click_n"):
        st.session_state["graph_click_n"] = clicked["n"]
        if clicked.get("kind") == "page":
            st.session_state["explorer_selected_page"] = clicked["node"]
            if not panel_open:
                st.session_state["explorer_panel_open"] = True
                st.rerun()
        else:
            # A toast, not a panel message: the collapsed rail is too narrow to
            # read one, and this needs no space of its own.
            st.toast(f"{clicked['node'].removeprefix('source::')} is an original "
                     "document, not a wiki page.")

    with panel_col:
        if not panel_open:
            if st.button("«", key="explorer_panel_expand", help="Details"):
                st.session_state["explorer_panel_open"] = True
                st.rerun()
            return
        if st.button("»", key="explorer_panel_collapse", help="Collapse the side panel"):
            st.session_state["explorer_panel_open"] = False
            st.rerun()
        _render_explorer_panel()


def _render_explorer_panel() -> None:
    """The graph's side panel: the opened page, or the bundle's health view."""
    selected = st.session_state.get("explorer_selected_page")
    if not selected:
        _render_graph_health()
        return
    head_col, close_col = st.columns([5, 1])
    head_col.markdown(f"#### {selected}")
    if close_col.button("✕", key="explorer_panel_close", help="Back to health"):
        st.session_state.pop("explorer_selected_page", None)
        st.rerun()
    try:
        parsed = wiki_engine.read_page_parsed(selected)
    except Exception as exc:
        st.warning(f"Could not load page: {exc}")
        return
    with st.container(height=560, border=False):
        st.markdown(parsed["content"])
    st.download_button(
        "Download page", data=parsed["content"], file_name=selected,
        mime="text/markdown", key=f"dl_graph_page_{selected}",
    )
    if parsed["sources"] or parsed["related"]:
        with st.expander("Sources", expanded=False):
            for s in parsed["sources"]:
                _raw_source_button(s, f"dl_graph_{s}")
            for r in parsed["related"]:
                if st.button(r, key=f"open_related_{r}"):
                    st.session_state["explorer_selected_page"] = r
                    st.rerun()


def _render_graph_health() -> None:
    """Which clusters are growing, and what sits alone (idea.md §6.9.3).

    Reads the flags `graph_export` already stamped into the drawn payload, so
    the numbers here and the dots on the canvas cannot drift apart.
    """
    health = graph_widget.graph_health()
    st.markdown("#### Bundle health")
    st.caption("Double-click a node to read it here.")
    c1, c2, c3 = st.columns(3)
    c1.metric("Pages", health["pages"])
    c2.metric("Orphans", len(health["orphans"]))
    c3.metric("Stale", len(health["stale"]))

    st.markdown(f"**Clusters** — updated in the last {health['window_days']} days")
    for cluster in health["clusters"][:6]:
        growth = f" · **+{cluster['recent']}**" if cluster["recent"] else ""
        st.markdown(f"- {cluster['label']} — {cluster['size']} pages{growth}")
    if not health["clusters"]:
        st.caption("No pages yet.")

    for label, ids in (
        ("Orphaned", health["orphans"]),
        ("Stale", health["stale"]),
        ("Low confidence", health["low_confidence"]),
    ):
        if not ids:
            continue
        with st.expander(f"{label} ({len(ids)})", expanded=False):
            for page in ids[:25]:
                if st.button(page, key=f"health_open_{label}_{page}"):
                    st.session_state["explorer_selected_page"] = page
                    st.rerun()
            if len(ids) > 25:
                st.caption(f"…and {len(ids) - 25} more.")



def _raw_source_button(filename: str, key: str) -> None:
    db, ref = db_context.split_ref(filename)  # cross-DB chat cites as "DB::file.md"
    base = _CHUNK_SUFFIX_RE.sub("", ref)
    base = _CITE_SECTION_SUFFIX_RE.sub("", base).strip()
    if base.lower().endswith((".md", ".txt")):
        with db_context.using_db(db):
            data = wiki_engine.read_raw_source(base)
        if data is None:
            st.markdown(f"- `{filename}` *(not found)*")
            return
        if st.button(filename, key=key):
            _show_md_dialog(filename, data.decode("utf-8", errors="replace"))
    else:
        st.markdown(f"- `{filename}`")


def _warn_if_no_lex_index() -> bool:
    """Warn when the active DB has no lexical index. Returns True if it is missing.

    Databases last built before the FTS5 cutover (commit `d25fbe8`) have no
    `index/chunks.sqlite`, and `lex_index.query()` returns [] for them — every
    search and both chat modes come back empty with no error. Say so instead.
    """
    if lex_index.index_health()["wiki"]:
        return False
    st.warning(
        "**No search index for this database.** Search and chat answers will come "
        "back empty until it is rebuilt: sidebar → **🛠 Maintenance** → "
        "**Search index** → *Rebuild search index*."
    )
    return True


def _render_wiki_nav(key_prefix: str) -> str | None:
    """Render wiki navigation tree in a narrow column. Returns clicked filename or None."""
    search = st.text_input(
        "Search pages", placeholder="Search…",
        key=f"{key_prefix}_nav_search", label_visibility="collapsed",
    ).strip()
    selected: str | None = None
    if search:
        results = wiki_engine.search_wiki(search)
        if not results and _warn_if_no_lex_index():
            return None
        st.caption(f"{len(results)} result(s)")
        max_score = max((r.get("score", 0.0) for r in results), default=0.0)
        for _i, r in enumerate(results):
            if st.button(r["title"], key=f"{key_prefix}_hit_{r['filename']}", use_container_width=True):
                st.session_state[f"{key_prefix}_selected_page"] = r["filename"]
                selected = r["filename"]
            if max_score > 0:
                st.progress(min(r.get("score", 0.0) / max_score, 1.0))
            if r.get("excerpt"):
                # Strip markdown markers so a preview starting with "## …" renders
                # as small plain caption text, not a giant heading.
                plain = re.sub(r"[#*_`>]+", "", r["excerpt"])
                plain = re.sub(r"\s+", " ", plain).strip().lstrip("-* ")
                if plain:
                    st.caption(plain)
            terms = r.get("matched_terms") or []
            if terms:
                st.caption("matched: " + " ".join(f"`{t}`" for t in terms))
            if _i < len(results) - 1:
                st.markdown("---")
    else:
        tree = wiki_engine.get_wiki_tree()
        group_labels = {
            "concept": "Concepts", "entity": "Entities",
            "source-summary": "Source Summaries", "comparison": "Comparisons",
            "insight": "Insights", "other": "Other",
        }
        for grp in ["concept", "entity", "source-summary", "comparison", "insight", "other"]:
            group = tree.get(grp)
            if not group:
                continue
            with st.expander(f"{group_labels[grp]} ({len(group)})", expanded=(grp == "concept")):
                for p in group:
                    title = ("⚠️ " if p.get("stale") else "") + p.get("title", p["filename"])
                    if st.button(title, key=f"{key_prefix}_nav_{p['filename']}", use_container_width=True):
                        st.session_state[f"{key_prefix}_selected_page"] = p["filename"]
                        selected = p["filename"]
    return selected


def _render_chat_sources_panel() -> None:
    messages = st.session_state.get("messages", [])
    last = next((m for m in reversed(messages) if m["role"] == "assistant"), None)
    if not last:
        st.caption("Sources appear here after each answer.")
        return
    sources = last.get("sources", [])
    raw_sources = last.get("raw_sources", [])
    if not sources and not raw_sources:
        st.caption("No sources for the last answer.")
        return
    if sources:
        st.markdown("**Wiki pages**")
        for s in sources:
            if st.button(s, key=f"cpanel_wiki_{s}", use_container_width=True):
                _db, _name = db_context.split_ref(s)
                with db_context.using_db(_db):
                    parsed = wiki_engine.read_page_parsed(_name)
                _show_md_dialog(s, parsed["content"])
    if raw_sources:
        st.markdown("**Documents**")
        for r in raw_sources:
            _raw_source_button(r, f"cpanel_raw_{r}")


def _render_research_sources_panel() -> None:
    """Tool calls plus, in Deep mode, per-URL citation cards.

    Both modes append `{tool, query}` entries; Deep mode additionally appends
    `{url, title}` entries as web_search results stream in.
    """
    sources = st.session_state.get("research_sources", [])
    if not sources:
        st.caption("Sources appear here during research.")
        return
    for i, src in enumerate(sources):
        if src.get("url"):
            st.markdown(f"[{src.get('title') or src['url']}]({src['url']})")
            st.caption(urlparse(src["url"]).netloc)
        else:
            st.markdown(f"**{src['tool']}**")
            st.caption(src["query"])
        if i < len(sources) - 1:
            st.markdown("---")


def _record_research_urls(step: dict) -> None:
    """Append newly-seen web citations from a Deep-mode step, de-duped by URL."""
    panel = st.session_state.setdefault("research_sources", [])
    known = {s["url"] for s in panel if s.get("url")}
    for src in step.get("sources") or []:
        if src["url"] not in known:
            known.add(src["url"])
            panel.append(src)


def _render_research_step(step: dict) -> None:
    """One trace step. Intermediate results go in collapsed expanders; the
    one-line control-flow steps stay inline so the trace stays scannable.

    Used both live (as steps stream in) and on replay from session state, so a
    refresh shows exactly the trace the run produced.
    """
    stype = step["type"]
    if stype == "thought":
        with st.expander(step.get("label") or "Thought", expanded=False):
            st.markdown(step["content"])
    elif stype == "notice":
        # Deep mode could not finish on the local model; the generator
        # continues into Quick mode after this step.
        st.warning(step["content"])
    elif stype == "tool_call":
        args = step.get("args") or {}
        # `ResearchComplete` is a zero-field sentinel — rendering `— {}` for it
        # reads as a failed call. Show the name alone and explain it instead.
        if step.get("terminal"):
            st.success(f"**{step['name']}** — research phase finished")
        elif args:
            st.info(f"**{step['name']}** — `{str(args)[:300]}`")
        else:
            st.info(f"**{step['name']}**")
        if step.get("note"):
            st.caption(step["note"])
    elif stype == "tool_result":
        n = len(step.get("sources") or [])
        label = f"Result: {step['name']}" + (f" — {n} source(s)" if n else "")
        with st.expander(label, expanded=False):
            if step.get("note"):
                st.caption(step["note"])
            for src in step.get("sources") or []:
                st.markdown(f"- [{src['title'] or src['url']}]({src['url']})")
            st.text(step["result"][:2000])
    elif stype == "error":
        st.error(step["content"])


def _render_research_metrics(metrics: dict | None) -> None:
    """Key metrics for a finished Deep run. `Sources checked` is dropped when it
    would just repeat the search count (per the spec: only show it if it differs)."""
    if not metrics:
        return
    tiles = [("Sub-tasks", metrics.get("tasks", 0)),
             ("Web searches", metrics.get("searches", 0))]
    checked = metrics.get("sources_checked", 0)
    if checked != metrics.get("searches", 0):
        tiles.append(("Sources checked", checked))
    tiles.append(("Sources cited", metrics.get("sources_cited", 0)))
    cols = st.columns(len(tiles))
    for col, (label, value) in zip(cols, tiles):
        col.metric(label, value)


def _render_research_trace(steps: list[dict] | None) -> None:
    """Replay the persisted agent trace under the report."""
    if not steps:
        return
    st.markdown(f"**Agent trace** — {len(steps)} steps")
    st.caption("Each intermediate result is collapsed; expand to inspect.")
    for step in steps:
        _render_research_step(step)


def _run_research_stream(question_to_run: str, display_q: str, wiki_context: str,
                         deep: bool = False) -> None:
    st.session_state["research_sources"] = []
    st.session_state["last_research_answer"] = ""
    st.session_state["last_research_error"] = ""
    st.session_state["last_research_q"] = display_q
    st.session_state["last_research_audit"] = None
    st.session_state["last_research_steps"] = []
    st.session_state["last_research_metrics"] = None
    st.session_state.pop("research_saved", None)
    _interpreted = question_to_run if question_to_run.strip() != display_q.strip() else None
    st.session_state["last_research_interpreted"] = _interpreted
    st.markdown(f"**Research question:** {display_q}")
    steps_container = st.container()
    _runner = (deep_research_agent.run_deep_research if deep
               else research_agent.run_research_agent)
    _trace = st.session_state["last_research_steps"]
    with steps_container:
        for step in _runner(question_to_run, wiki_context):
            stype = step["type"]
            # Persist every step so the trace survives the caller's st.rerun().
            if stype != "final_answer":
                _trace.append(step)
            if stype in ("thought", "notice", "tool_call", "tool_result", "error"):
                _render_research_step(step)
            if stype == "tool_call":
                st.session_state.setdefault("research_sources", []).append(
                    {"tool": step["name"], "query": str(step["args"])[:80]}
                )
            elif stype == "tool_result":
                _record_research_urls(step)
            elif stype == "error":
                st.session_state["last_research_error"] = step["content"]

            if stype == "final_answer":
                _record_research_urls(step)
                st.session_state["last_research_metrics"] = step.get("metrics")
                st.success("Research complete.")
                if step.get("report_path"):
                    st.session_state["last_report"] = step["report_path"]
                    try:
                        _rel = "comparisons/" + step["report_path"].split("comparisons/")[-1]
                        st.session_state["last_research_answer"] = wiki_engine.read_page_parsed(_rel)["content"]
                    except Exception:
                        st.session_state["last_research_answer"] = ""
                else:
                    st.session_state["last_research_answer"] = step.get("content", "")
                    if not step.get("content", "").strip():
                        st.warning("Agent completed but produced no answer text.")
                        st.session_state["last_research_error"] = (
                            "The agent finished but produced no answer text. "
                            "Try rephrasing the question, or click 🆕 New research."
                        )
                st.session_state.setdefault("research_history", []).append({
                    "q": display_q,
                    "a": st.session_state.get("last_research_answer", ""),
                    "interpreted": _interpreted,
                    "report": (("comparisons/" + step["report_path"].split("comparisons/")[-1])
                               if step.get("report_path") else None),
                })
    # Search-ladder audit for the finished run (per-source scores vs τ).
    st.session_state["last_research_audit"] = tools.current_run_audit()


def _bar_label(text: str) -> None:
    """Small uppercase heading above a top-bar control.

    Rendered as markdown rather than the widget's own `label=`: Streamlit's
    widget labels do not surface here (both the selectbox and the segmented
    control came out label-less in the browser), and the inline `!important`
    is needed to beat the blanket `.stApp *` colour rule.
    """
    st.markdown(
        f"<div style='font-size:0.72rem;font-weight:600;letter-spacing:0.09em;"
        f"color:{_t['text_muted']} !important;margin:0 0 0.2rem 2px'>{text}</div>",
        unsafe_allow_html=True,
    )


def _page_header(title: str, subtitle: str = "") -> None:
    st.markdown(f"## {title}")
    if subtitle:
        st.caption(subtitle)
    st.markdown("---")


def _render_chat_sources(sources: list[str], raw_sources: list[str], key_prefix: str) -> None:
    if not (sources or raw_sources):
        return
    with st.expander("Sources", expanded=False):
        if sources:
            st.markdown("**Related wiki pages**")
            for s in sources:
                if st.button(s, key=f"{key_prefix}_wiki_{s}"):
                    parsed = wiki_engine.read_page_parsed(s)
                    _show_md_dialog(s, parsed["content"])
        if raw_sources:
            st.markdown("**Original documents (data/raw/)**")
            for r in raw_sources:
                _raw_source_button(r, f"{key_prefix}_raw_{r}")


def _render_why_sources(audit: dict | None) -> None:
    """Search-ladder audit panel (idea.md §6.9.1): which sources were kept vs dropped
    below the calibrated τ. Silent when no source carried a rerank score (τ off / no
    reranker), so a fusion-only DB shows no empty panel."""
    if not audit:
        return
    kept = audit.get("kept") or []
    below = audit.get("below_tau") or []
    over = audit.get("over_cap") or []
    if not (kept or below or over):
        return
    tau = audit.get("tau")

    def _fmt(s: float | None) -> str:
        return "n/a" if s is None else f"{s:.2f}"

    tau_txt = f", {len(below)} below τ={tau:.1f}" if (below and tau is not None) else ""
    with st.expander(f"Why these sources ({len(kept)} kept{tau_txt})", expanded=False):
        for name, s in kept:
            st.markdown(f"✓ `{name}` — {_fmt(s)}")
        for name, s in below:
            st.markdown(f"✗ `{name}` — {_fmt(s)} (below τ)")
        for name, s in over:
            st.markdown(f"✗ `{name}` — {_fmt(s)} (over cap)")


# --- sidebar ---

def _safe_reset() -> None:
    import requests as _req
    try:
        _req.post(
            f"{os.getenv('OLLAMA_HOST', 'http://localhost:11434')}/api/generate",
            json={"model": os.getenv("OLLAMA_MODEL", "gemma4:e4b"), "keep_alive": 0},
            timeout=5,
        )
    except Exception:
        pass
    gc.collect()
    for key in list(st.session_state.keys()):
        del st.session_state[key]
    st.rerun()


# --- bootstrap: migrate legacy data layout + seed default user ---
db_context.migrate_legacy_layout()
auth.ensure_seeded()
auth.backfill_maintainers()

# --- login gate ---
if not st.session_state.get("user"):
    _lc, _mid, _rc = st.columns([1, 1.4, 1])
    with _mid:
        st.markdown("## 📖 LocalWiki")
        st.caption("Sign in to continue")
        with st.form("login_form"):
            u = st.text_input("Username")
            p = st.text_input("Password", type="password")
            ok = st.form_submit_button("Sign in", type="primary", use_container_width=True)
        if ok:
            if auth.verify(u, p):
                dbs = auth.user_dbs(u)
                if not dbs:
                    st.error("This account has no database access. Ask an admin.")
                    st.stop()
                st.session_state["user"] = u
                st.session_state["active_db"] = dbs[0]
                st.rerun()
            else:
                st.error("Invalid username or password.")
    st.stop()

_user = st.session_state["user"]
_allowed_dbs = auth.user_dbs(_user)
if not _allowed_dbs:
    st.error("Your account has no database access. Contact an admin.")
    if st.button("Logout"):
        st.session_state.pop("user", None)
        st.rerun()
    st.stop()

# Keep active_db consistent with the allowlist
if st.session_state.get("active_db") not in _allowed_dbs:
    st.session_state["active_db"] = _allowed_dbs[0]

# Apply the active DB to the ContextVar BEFORE any page handler reads paths.
db_context.set_active_db(st.session_state["active_db"])
_can_maintain = auth.is_maintainer(_user, st.session_state["active_db"])
wiki_engine.init_wiki()

st.sidebar.markdown("## 📖 LocalWiki")
gpu_widget.render_gpu_sidebar(accent=_t["primary"])

st.sidebar.markdown("---")

# Newspaper skin only: the edition (= database) picker belongs in the left rail,
# where the mock puts it, and the main column belongs to the masthead. Claimed
# here so it lands under the logo; filled by the top-bar block further down.
_db_slot = st.sidebar.container() if _NEWSPAPER else None
if _NEWSPAPER:
    st.sidebar.markdown("---")

# Maintenance is the only sidebar destination: infrequent, admin-ish, kept away
# from the four daily-use wiki views in the main window.
_maint_active = st.session_state.get("nav_maintenance", False)
if _maint_active:
    st.markdown(
        f"""<style>
        [data-testid="stSidebar"] .st-key-maint_nav_btn button {{
            background-color: {_t['primary']} !important;
            border-color: {_t['primary']} !important;
        }}
        [data-testid="stSidebar"] .st-key-maint_nav_btn button * {{
            color: #ffffff !important;
        }}
        </style>""",
        unsafe_allow_html=True,
    )
if st.sidebar.button("🛠 Maintenance", key="maint_nav_btn", use_container_width=True):
    st.session_state["nav_maintenance"] = True
    st.rerun()

st.sidebar.markdown("---")
st.sidebar.caption(f"Signed in as **{_user}**")
_rst_col, _logout_col = st.sidebar.columns(2)
if _rst_col.button("Reset", key="reset_btn", help="Unload model from VRAM and reset session. Server stays running."):
    _safe_reset()
if _logout_col.button("Logout", key="logout_btn"):
    for _k in ("user", "active_db", "messages", "chat_followup", "chat_scope",
               "research_history", "last_research_q", "last_research_answer",
               "last_report", "research_sources", "last_research_steps",
               "last_research_metrics"):
        st.session_state.pop(_k, None)
    st.rerun()


# --- top bar: active database + primary navigation ---
# Runs before the page dispatch so `set_active_db` still lands before any page
# handler reads paths.
_s = wiki_engine.stats()

if _NEWSPAPER:
    # Nameplate takes the full width; the DB picker sits in the rail slot and
    # the nav rules span the fold, so no side-by-side columns here.
    theme.masthead(
        edition=st.session_state["active_db"],
        pages=_s["pages"],
        sources=_s["raw_files"],
        model=ollama_client._MODEL,
    )
    _bar_db, _bar_nav = _db_slot, st.container()
else:
    # The nav is the page's header, so it spans the full width on its own row;
    # the DB selector keeps a narrow column above it.
    _bar_db = st.columns([1, 3])[0]
    _bar_nav = st.container()

with _bar_db:
    _bar_label("EDITION" if _NEWSPAPER else "DATABASE")
    _db_choice = st.selectbox(
        "Database",
        options=_allowed_dbs,
        index=_allowed_dbs.index(st.session_state["active_db"]),
        key="db_selector",
        label_visibility="collapsed",
    )
    # The masthead dateline already carries the counts in newspaper mode.
    if not _NEWSPAPER:
        st.caption(f"**{_s['pages']}** pages &nbsp;·&nbsp; **{_s['raw_files']}** sources",
                   unsafe_allow_html=True)
if _db_choice != st.session_state["active_db"]:
    st.session_state["active_db"] = _db_choice
    db_context.set_active_db(_db_choice)
    # Clear per-DB session state to avoid cross-DB leakage.
    for _k in ("messages", "chat_followup", "research_history",
               "last_research_q", "last_research_answer", "last_report",
               "research_sources", "last_research_steps", "last_research_metrics",
               "explorer_selected_page", "last_contradictions",
               "pending_batch", "batch_confirmed", "batch_prepared", "batch_key",
               "convert_editor", "chat_scope"):
        st.session_state.pop(_k, None)
    st.rerun()

with _bar_nav:
    if not _maint_active and not _NEWSPAPER:
        _bar_label("OPTIONS")
    if _maint_active:
        page = "Maintenance"
        if st.button("← Back to Wiki", key="back_to_wiki"):
            st.session_state["nav_maintenance"] = False
            st.rerun()
    else:
        _nav_options = ["Wiki Explorer", "Wiki Chat", "Research"]
        if _can_maintain:
            _nav_options.insert(0, "Upload")
        # Upload disappears on a DB the user does not maintain. Written *before*
        # the widget: a post-instantiation write to a widget key raises.
        if st.session_state.get("wiki_view") not in _nav_options:
            st.session_state["wiki_view"] = _nav_options[0]
        # segmented_control, not st.tabs: tabs execute every branch on every rerun
        # and the Upload branch's st.stop() would blank the other tabs.
        page = st.segmented_control(
            "OPTIONS", _nav_options, required=True, key="wiki_view",
            label_visibility="collapsed", width="stretch",
        )


# --- pages ---

if page == "Upload":
    # No title: the active nav pill already names the page. Only the part the
    # pill cannot say stays.
    st.caption("Markdown, PDF, DOCX, and images — non-Markdown files are auto-converted before ingest.")
    if not _can_maintain:
        st.error("You are not a maintainer of this database. Ask an admin for maintainer rights.")
        st.stop()
    uploaded = st.file_uploader(
        "Choose files",
        type=["md", "pdf", "docx", "png", "jpg", "jpeg", "tiff", "tif", "bmp"],
        accept_multiple_files=True,
        label_visibility="collapsed",
    )
    if uploaded:
        # --- Phase 1: prepare each file (dedup, convert, extract, detect date) ---
        # Cached under the exact set of uploaded SHAs so Streamlit reruns (editing
        # the review table, opening the confirm dialog) never re-run OCR.
        raws = {f.name: f.getvalue() for f in uploaded}
        batch_key = "|".join(sorted(dedup.sha256(b) for b in raws.values()))
        if st.session_state.get("batch_key") != batch_key:
            st.session_state["batch_key"] = batch_key
            st.session_state.pop("batch_prepared", None)
            st.session_state.pop("convert_editor", None)

        prepared = st.session_state.get("batch_prepared")
        if prepared is None:
            dupes = [n for n, b in raws.items() if dedup.is_duplicate(b)]
            todo = [n for n in raws if n not in dupes]
            if dupes:
                st.warning("Skipped (already ingested): " + ", ".join(f"**{n}**" for n in dupes))
            if not todo:
                st.info("Nothing new to ingest.")
                st.stop()
            if any(md_convert.is_convertible(n) for n in todo) and not ollama_client.is_available():
                st.error("Ollama is not reachable. Start it to convert non-Markdown files.")
                st.stop()
            prog = st.progress(0.0, text="Preparing files…")
            prepared = []
            for i, name in enumerate(todo):
                b = raws[name]
                convertible = md_convert.is_convertible(name)
                if convertible:
                    def _cb(done, total, label, _n=name, _i=i, _t=len(todo)):
                        frac = (_i + (done / total if total else 1.0)) / _t
                        prog.progress(min(frac, 1.0), text=f"{_n}: {label}")
                    try:
                        text = md_convert.convert_to_markdown(b, name, _cb)
                    except (RuntimeError, ValueError) as e:
                        st.warning(f"Skipped **{name}** — conversion failed: {e}")
                        continue
                    save_name = Path(name).stem + ".md"
                    content_bytes = text.encode()
                else:
                    prog.progress((i + 1) / len(todo), text=f"{name}: reading…")
                    text = b.decode(errors="replace")
                    save_name = name
                    content_bytes = None  # write the original bytes as-is
                prepared.append({
                    "save_name": save_name,
                    "raw": b,
                    "text": text,
                    "content_bytes": content_bytes,
                    "convertible": convertible,
                    "detected_date": metadata_extract.extract_effective_date(text) or "",
                })
            prog.empty()
            if not prepared:
                st.stop()
            st.session_state["batch_prepared"] = prepared

        # --- Phase 2: review (effective date is the only per-file editable field) ---
        st.info(f"{len(prepared)} file(s) ready to ingest.")
        single_md_edit = len(prepared) == 1 and prepared[0]["convertible"]
        if single_md_edit:
            st.markdown("**Converted Markdown** — review and edit before ingest.")
            if "convert_editor" not in st.session_state:
                st.session_state["convert_editor"] = prepared[0]["text"]
            st.text_area("Converted Markdown", height=300,
                         label_visibility="collapsed", key="convert_editor")

        st.markdown("**Effective date** — auto-detected from each document; correct any before ingest.")
        edited = st.data_editor(
            [{"File": f["save_name"], "effective as of": f["detected_date"]} for f in prepared],
            key="date_editor", hide_index=True, use_container_width=True,
            disabled=["File"],
            column_config={
                "File": st.column_config.TextColumn("File"),
                "effective as of": st.column_config.TextColumn("effective as of (YYYY-MM-DD)"),
            },
        )
        with st.expander("Optional shared metadata (applied to all files)"):
            shared_part = st.text_input("part of", key="batch_part_of")
            shared_desc = st.text_input("description", key="batch_description")

        if st.button(f"Ingest {len(prepared)} file(s) into wiki", type="primary"):
            files = prepared
            if single_md_edit:
                files[0]["text"] = st.session_state.get("convert_editor", files[0]["text"])
                files[0]["content_bytes"] = files[0]["text"].encode()
            st.session_state["pending_batch"] = {
                "files": files,
                "dates": {r["File"]: str(r.get("effective as of") or "").strip() for r in edited},
                "shared": {"part of": shared_part.strip(), "description": shared_desc.strip()},
            }
            _confirm_ingest_dialog(st.session_state["active_db"], f"{len(files)} file(s)")

        # --- Phase 3: ordered batch ingest (oldest-first so newer supersedes) ---
        if st.session_state.pop("batch_confirmed", False):
            pending = st.session_state.pop("pending_batch", None)
            if pending:
                files, dates, shared = pending["files"], pending["dates"], pending["shared"]
                files.sort(key=lambda f: dates.get(f["save_name"]) or "")
                agg = {"created": [], "updated": [], "contradictions": [], "failed": []}
                finalized = False
                prog = st.progress(0.0, text="Ingesting…")
                for i, f in enumerate(files):
                    is_last = i == len(files) - 1
                    with st.spinner(f"Ingesting {f['save_name']} ({i + 1}/{len(files)})…"):
                        try:
                            saved = dedup.register_file(f["raw"], f["save_name"], content=f["content_bytes"])
                            chunks = file_processor.chunk_text(f["text"])
                            per_meta = {k: v for k, v in {
                                "effective as of": dates.get(f["save_name"], ""),
                                "part of": shared["part of"],
                                "description": shared["description"],
                            }.items() if v}
                            ctx = wiki_engine.ingest_begin(f["text"], saved.name, per_meta or None)
                            for j, chunk in enumerate(chunks):
                                wiki_engine.ingest_piece(ctx, chunk, j, len(chunks))
                            res = wiki_engine.ingest_end(ctx, finalize=is_last)
                            finalized = finalized or is_last
                            agg["created"] += res["created"]
                            agg["updated"] += res["updated"]
                            agg["contradictions"] += res["contradictions"]
                        except Exception as e:
                            agg["failed"].append(f"{f['save_name']}: {e}")
                    prog.progress((i + 1) / len(files))
                if not finalized and (agg["created"] or agg["updated"]):
                    wiki_engine.rebuild_lex_index()  # last file failed before finalize
                st.session_state.pop("batch_prepared", None)
                st.session_state.pop("batch_key", None)
                st.success("Ingest complete.")
                c1, c2, c3 = st.columns(3)
                c1.metric("Created", len(dict.fromkeys(agg["created"])))
                c2.metric("Updated", len(dict.fromkeys(agg["updated"])))
                c3.metric("Contradictions", len(agg["contradictions"]))
                if agg["created"]:
                    st.markdown("**New pages:** " + ", ".join(f"`{f}`" for f in dict.fromkeys(agg["created"])))
                if agg["failed"]:
                    st.error("Failed:\n" + "\n".join(f"- {x}" for x in agg["failed"]))
                if agg["contradictions"]:
                    st.warning("Contradictions found:\n" + "\n".join(f"- {c}" for c in agg["contradictions"]))
                    st.session_state["last_contradictions"] = agg["contradictions"]
                    st.session_state["last_contradiction_pages"] = list({*agg["created"], *agg["updated"]})

    if st.session_state.get("last_contradictions"):
        st.markdown("---")
        st.subheader("Resolve contradictions")
        for i, desc in enumerate(st.session_state["last_contradictions"]):
            with st.expander(desc, expanded=False):
                pages = st.multiselect(
                    "Pages to reconcile",
                    options=st.session_state.get("last_contradiction_pages", []),
                    default=st.session_state.get("last_contradiction_pages", []),
                    key=f"resolve_pages_{i}",
                )
                guidance = st.text_area(
                    "Guidance (optional — which claim is authoritative? what is the resolution?)",
                    key=f"resolve_guidance_{i}",
                    height=80,
                )
                if st.button("Reconcile", key=f"resolve_btn_{i}", type="primary"):
                    with st.spinner("Reconciling pages…"):
                        try:
                            res = wiki_engine.resolve_contradiction(desc, pages, guidance)
                            if res["updated"]:
                                st.success("Updated: " + ", ".join(f"`{f}`" for f in res["updated"]))
                            else:
                                st.info("No pages were rewritten.")
                        except RuntimeError as e:
                            st.error(str(e))


elif page == "Wiki Explorer":
    pages = wiki_engine.list_pages()
    if not pages:
        st.info("No wiki pages yet. Upload a document to get started.")
    else:
        # One control row: the view toggle, a rule, then the layout switch —
        # they pick the same thing (what the main area shows), so they read as
        # one decision rather than two stacked ones. The layout switch is drawn
        # here, not inside `_render_neural_graph`, so it can share this row; the
        # columns are laid out before `view_mode` is known, which is fine —
        # nothing is written into them until after.
        _vcol, _sepcol, _lcol = st.columns([5, 0.25, 5])
        with _vcol:
            view_mode = st.segmented_control(
                "View", ["Graph", "Tree"], required=True, default="Graph",
                key="explorer_view", label_visibility="collapsed", width="stretch",
            )
        _neural = graph_widget.RENDERER == "neural"
        graph_layout = "galaxy"
        if view_mode == "Graph" and _neural:
            _sepcol.markdown(
                "<div style='text-align:center;padding-top:0.4rem;opacity:0.45;"
                "font-size:1.15rem'>|</div>",
                unsafe_allow_html=True,
            )
            with _lcol:
                _picked_layout = st.segmented_control(
                    "Layout", list(_GRAPH_LAYOUTS), default="Galaxy",
                    key="graph_layout", label_visibility="collapsed", width="stretch",
                    help="Galaxy: force layout. Ranked: the metric's head as a stable "
                         "column. Clusters: pages on a ring by cluster, links bundled.",
                )
            # Clearing the control returns None; the map still has to be drawn
            # in *some* geometry.
            graph_layout = _GRAPH_LAYOUTS.get(_picked_layout, "galaxy")
        # Switching into Tree always lands on the database overview: both views
        # share `explorer_selected_page`, so without this a node opened in the
        # graph would silently preselect the reader instead.
        if view_mode != st.session_state.get("explorer_view_mode"):
            st.session_state["explorer_view_mode"] = view_mode
            if view_mode == "Tree":
                st.session_state.pop("explorer_selected_page", None)

        if view_mode == "Tree":
            main_col, nav_col = st.columns([2, 1])
            with nav_col:
                _render_wiki_nav("explorer")
            selected_file = st.session_state.get("explorer_selected_page")
            with main_col:
                if selected_file:
                    st.markdown(f"### {selected_file}")
                    parsed = wiki_engine.read_page_parsed(selected_file)
                    st.markdown(parsed["content"])
                    st.download_button(
                        "Download page",
                        data=parsed["content"],
                        file_name=selected_file,
                        mime="text/markdown",
                        key=f"dl_wiki_page_{selected_file}",
                    )
                    raw_sources = parsed["sources"]
                    related = parsed["related"]
                    if raw_sources or related:
                        with st.expander("Sources", expanded=False):
                            if raw_sources:
                                st.markdown("**Original documents (data/raw/)**")
                                for s in raw_sources:
                                    _raw_source_button(s, f"dl_wiki_{s}")
                            if related:
                                st.markdown("**Related wiki pages**")
                                for r in related:
                                    if st.button(r, key=f"view_related_{r}"):
                                        parsed = wiki_engine.read_page_parsed(r)
                                        _show_md_dialog(r, parsed["content"])
                else:
                    st.info("Select a page from the navigation panel on the right.")
                    wiki_engine.ensure_description()
                    overview = wiki_engine.read_description()
                    if overview:
                        st.markdown("---")
                        st.markdown(overview)

        else:  # Graph — full width; the nav tree and its search live in Tree view.
            if _neural:
                _render_neural_graph(graph_layout)
            else:
                _render_legacy_graph()


elif page == "Wiki Chat":
    st.caption("Fast mode reads wiki pages; Deep mode reasons over original documents.")
    _warn_if_no_lex_index()

    if "messages" not in st.session_state:
        st.session_state["messages"] = []

    # Bind the search scope before anything renders: the sources panel resolves
    # DB-qualified refs through it. Written before the widget is instantiated, so
    # an empty selection self-heals to the active DB on the next run.
    if "chat_scope" not in st.session_state:
        st.session_state["chat_scope"] = [st.session_state["active_db"]]
    st.session_state["chat_scope"] = [
        d for d in st.session_state["chat_scope"] if d in _allowed_dbs
    ] or [st.session_state["active_db"]]
    db_context.set_search_scope(st.session_state["chat_scope"])

    main_col, nav_col = st.columns([3, 1])

    with nav_col:
        st.markdown("#### Sources")
        _render_chat_sources_panel()

    with main_col:
        # The mode is the one control every turn depends on, so it stands alone
        # as a two-option toggle; the caption above the page already explains
        # what Fast and Deep do.
        mode = st.segmented_control(
            "Mode", ["Fast", "Deep"], required=True, default="Fast",
            key="chat_mode", label_visibility="collapsed",
        )

        # Scope and reset are per-session decisions, not per-turn ones.
        with st.expander("Advanced", expanded=False, key="chat_advanced"):
            st.multiselect(
                "Search in", options=_allowed_dbs, key="chat_scope",
                help="Databases this chat searches. Answers cite cross-database results "
                     "as `Database::file.md`. Uploads and 'Save answer to wiki' still go "
                     "to the active database in the sidebar.",
            )
            if st.button("🆕 New chat", key="new_chat"):
                st.session_state.pop("messages", None)
                st.session_state.pop("chat_followup", None)
                st.rerun()

        # Kept outside the expander: a scope wider than the active DB changes how
        # every answer is cited, so it must stay visible when Advanced is shut.
        if len(st.session_state["chat_scope"]) > 1:
            st.caption(
                f"🔎 Searching {len(st.session_state['chat_scope'])} databases: "
                + ", ".join(st.session_state["chat_scope"])
            )

        st.markdown("---")

        _msgs = st.session_state["messages"]
        _current_start = len(_msgs) - 2 if len(_msgs) > 2 else 0
        if _current_start > 0:
            with st.expander(f"📜 Conversation history ({_current_start // 2} earlier turn(s))", expanded=False):
                for _m in _msgs[:_current_start]:
                    _role = "You" if _m["role"] == "user" else "Assistant"
                    if _m["role"] == "assistant" and _m.get("interpreted"):
                        st.caption(f"🔎 Interpreted as: {_m['interpreted']}")
                    st.markdown(f"**{_role}:** {_m['content']}")
                    if _m["role"] == "assistant":
                        st.markdown("---")

        for i in range(_current_start, len(_msgs)):
            msg = _msgs[i]
            with st.chat_message(msg["role"]):
                if msg["role"] == "assistant" and msg.get("interpreted"):
                    st.caption(f"🔎 Interpreted as: {msg['interpreted']}")
                st.markdown(msg["content"])
                if msg["role"] == "assistant":
                    _render_why_sources(msg.get("audit"))
                if msg["role"] == "assistant" and msg.get("question") and not msg["content"].startswith("Error:"):
                    if st.button("↪ Follow up", key=f"followup_{i}", help="Continue from this answer"):
                        st.session_state["chat_followup"] = {"q": msg["question"], "a": msg["content"]}
                        st.rerun()
                if msg["role"] == "assistant" and msg.get("steps"):
                    st.download_button(
                        "Download answer",
                        data=msg["content"],
                        file_name="answer.md",
                        mime="text/markdown",
                        key=f"dl_answer_{i}",
                    )
                    with st.expander("Agent trace", expanded=False):
                        for step in msg["steps"]:
                            stype = step["type"]
                            if stype == "thought":
                                st.markdown(f"> {step['content']}")
                            elif stype == "tool_call":
                                st.info(f"**{step['name']}** — `{step['args']}`")
                            elif stype == "tool_result":
                                st.text(step["result"][:600])
                            elif stype == "error":
                                st.error(step["content"])

        last = st.session_state["messages"][-1] if st.session_state["messages"] else None
        if last and last["role"] == "assistant" and last.get("question") and not last["content"].startswith("Error:"):
            _active = st.session_state["active_db"]
            if st.button("Save answer to wiki", key="save_answer",
                         help=f"Files the answer into the active database ({_active})."):
                # `related:` links are intra-DB, so a cross-DB answer only carries
                # over the pages that actually live in the DB being written to.
                _refs = [db_context.split_ref(s) for s in last.get("sources", [])]
                _related = [_name for _db, _name in _refs if _db == _active]
                try:
                    rel = wiki_engine.file_answer(last["question"], last["content"], _related)
                    st.success(f"Filed as `{rel}` in **{_active}**")
                except RuntimeError as e:
                    st.error(str(e))

    _followup = st.session_state.get("chat_followup")
    if _followup:
        with st.container(border=True):
            st.markdown("**↪ Follow-up — original question:**")
            st.markdown(f"> {_followup['q']}")
            c1, c2 = st.columns([5, 1])
            c1.caption("⬇ Type your follow-up below — the original Q&A is used as context.")
            if c2.button("Cancel", key="clear_chat_followup"):
                st.session_state.pop("chat_followup", None)
                st.rerun()

    # In the page flow, not pinned to the viewport: `st.chat_input` only sticks
    # to the bottom of the window when it is a direct child of the main body, so
    # a plain container puts it inline — under the conversation and above the
    # newspaper colophon, instead of floating over it.
    with st.container():
        prompt = st.chat_input("Ask something…")
    if prompt:
        fu = st.session_state.pop("chat_followup", None)
        if fu:
            with st.spinner("Rephrasing follow-up…"):
                q_to_ask = wiki_engine.condense_followup(fu["q"], fu["a"], prompt)
        else:
            q_to_ask = prompt
        interpreted = q_to_ask if (fu and q_to_ask.strip() != prompt.strip()) else None
        st.session_state["messages"].append({"role": "user", "content": prompt})
        if st.session_state.get("chat_mode", "Fast") == "Fast":
            with st.spinner("Thinking…"):
                try:
                    res = wiki_engine.query_with_sources(q_to_ask)
                    answer = res["answer"]
                    sources = res["sources"]
                    raw_sources = res["raw_sources"]
                    audit = res.get("audit")
                except RuntimeError as e:
                    answer, sources, raw_sources, audit = f"Error: {e}", [], [], None
            st.session_state["messages"].append(
                {"role": "assistant", "content": answer, "question": prompt,
                 "sources": sources, "raw_sources": raw_sources, "interpreted": interpreted,
                 "audit": audit}
            )
        else:
            steps: list[dict] = []
            answer = ""
            raw_sources: list[str] = []
            wiki_pages: list[str] = []
            _live = st.container()
            with _live:
                st.markdown(f"**Question:** {prompt}")
                if interpreted:
                    st.caption(f"🔎 Researching as: {interpreted}")
            for step in chat_agent.run_chat_agent(q_to_ask):
                steps.append(step)
                stype = step["type"]
                with _live:
                    if stype == "thought":
                        with st.expander("Thought", expanded=False):
                            st.markdown(step["content"])
                    elif stype == "tool_call":
                        st.info(f"**{step['name']}** — `{step['args']}`")
                    elif stype == "tool_result":
                        with st.expander(f"Result: {step['name']}", expanded=False):
                            st.text(step["result"][:800])
                    elif stype == "final_answer":
                        answer = step["content"]
                        raw_sources = step.get("sources", []) or []
                        wiki_pages = step.get("wiki_sources", []) or []
                    elif stype == "error" and not answer:
                        answer = f"Error: {step['content']}"
            # Deep chat: audit-log only (loop/abstention unchanged) — read the per-source
            # scores the run accumulated in run memory (idea.md §6.9.1 guardrail).
            _audit = tools.current_run_audit()
            st.session_state["messages"].append(
                {"role": "assistant", "content": answer or "(no answer)", "question": prompt,
                 "sources": wiki_pages, "raw_sources": raw_sources, "steps": steps,
                 "interpreted": interpreted, "audit": _audit}
            )
        st.rerun()


elif page == "Research":
    st.caption(
        "**Quick** starts at the local wiki, then searches the web to fill the gaps. "
        "**Deep** is web-only: it splits the question into sub-topics, researches each "
        "one, and writes a report cited to web URLs — slower, and it ignores the wiki."
    )
    tavily_key = os.getenv("TAVILY_API_KEY", "")

    if not tavily_key:
        st.warning(
            "**TAVILY_API_KEY not set.** Add it to your `.env` file to enable web research.\n\n"
            "Get a free key at [tavily.com](https://tavily.com)."
        )

    main_col, nav_col = st.columns([3, 1])

    with nav_col:
        st.markdown("#### Sources")
        _render_research_sources_panel()

    with main_col:
        # Mirrors the Chat page's Fast/Deep toggle — the mode is the one control
        # every run depends on, so it stands alone above the question.
        research_mode = st.segmented_control(
            "Research mode", ["Quick", "Deep"], required=True, default="Quick",
            key="research_mode", label_visibility="collapsed",
        )
        _deep = research_mode == "Deep"

        if st.button("🆕 New research", key="new_research"):
            for _k in ("research_history", "last_research_q", "last_research_answer",
                       "last_research_interpreted", "last_report", "research_sources",
                       "last_research_error", "research_followup_input", "research_saved",
                       "last_research_steps", "last_research_metrics"):
                st.session_state.pop(_k, None)
            st.rerun()

        question = st.text_input("Research question", placeholder="e.g. What are the latest advances in RAG?")

        _paste_label = ("Extra wiki paste (unused in Deep mode — it is web-only)" if _deep
                        else "Extra wiki paste (optional — the agent browses the wiki on its own)")
        with st.expander(_paste_label):
            wiki_context = st.text_area(
                "Optional extra context. Leave blank — the agent will run wiki_search first automatically.",
                height=120,
                label_visibility="collapsed",
            )

        # Gated on the API key only, never on `question`. A `st.text_input`
        # returns the value from the last *completed* rerun, and typing does not
        # rerun — so mid-typing `question` is still "" and a
        # `disabled=not question` button shows a not-allowed cursor while being
        # perfectly clickable (the click blurs the input, which commits the text
        # and reruns). Validate on click instead; an empty box is rare and a
        # message beats a lying cursor.
        if st.button("Start research", key="start_research_btn",
                     use_container_width=True, disabled=not tavily_key):
            if not question.strip():
                st.warning("Enter a research question first.")
            else:
                _run_research_stream(question, question, wiki_context or "", deep=_deep)
                st.rerun()

        _rhist = st.session_state.get("research_history", [])
        if len(_rhist) > 1:
            with st.expander(f"📜 Conversation history ({len(_rhist) - 1} earlier turn(s))", expanded=False):
                for _h in _rhist[:-1]:
                    st.markdown(f"**Q:** {_h['q']}")
                    if _h.get("interpreted"):
                        st.caption(f"🔎 Interpreted as: {_h['interpreted']}")
                    if _h.get("report"):
                        st.caption(f"Report: `{_h['report']}`")
                    st.markdown(_h["a"])
                    st.markdown("---")

        if st.session_state.get("last_research_answer"):
            st.markdown("---")
            if st.session_state.get("last_research_interpreted"):
                st.caption(f"🔎 Interpreted as: {st.session_state['last_research_interpreted']}")
            if st.session_state.get("last_report"):
                _rel = "comparisons/" + st.session_state["last_report"].split("comparisons/")[-1]
                st.markdown(f"Report saved: `{_rel}`")
            _render_research_metrics(st.session_state.get("last_research_metrics"))
            _ans = st.session_state["last_research_answer"]
            st.markdown(_ans)
            _render_why_sources(st.session_state.get("last_research_audit"))
            _dl_col, _save_col = st.columns(2)
            _dl_col.download_button(
                "Download report",
                data=_ans,
                file_name=(st.session_state["last_report"].split("comparisons/")[-1]
                           if st.session_state.get("last_report") else "research-answer.md"),
                mime="text/markdown",
                key="dl_report",
                use_container_width=True,
            )
            if st.session_state.get("research_saved"):
                _save_col.success("Saved to wiki.")
            elif _save_col.button("Save to wiki", key="save_research_btn",
                                  use_container_width=True,
                                  help="Ingest this result into the wiki as new/updated pages."):
                with st.spinner("Ingesting result into wiki…"):
                    try:
                        wiki_engine.ingest(_ans, f"Research: {st.session_state['last_research_q'][:60]}")
                        st.session_state["research_saved"] = True
                        st.rerun()
                    except Exception as exc:
                        st.error(f"Save to wiki failed: {exc}")
            st.markdown("---")
            _render_research_trace(st.session_state.get("last_research_steps"))
        elif st.session_state.get("last_research_error"):
            st.markdown("---")
            st.error(st.session_state["last_research_error"])
            _render_research_trace(st.session_state.get("last_research_steps"))

        if st.session_state.get("last_research_q"):
            st.markdown("---")
            st.markdown("**↪ Follow-up research**")
            fq = st.text_input("Ask a follow-up about the last research answer", key="research_followup_input")
            # Same stale-widget-value reasoning as "Start research" above.
            if st.button("Ask follow-up", key="research_followup_go",
                         disabled=not tavily_key):
                if not fq.strip():
                    st.warning("Enter a follow-up question first.")
                else:
                    with st.spinner("Rephrasing follow-up…"):
                        standalone = wiki_engine.condense_followup(
                            st.session_state["last_research_q"],
                            st.session_state.get("last_research_answer", ""), fq)
                    _run_research_stream(standalone, fq, "", deep=_deep)
                    st.rerun()


elif page == "Maintenance":
    _page_header("Maintenance")
    s = wiki_engine.stats()
    c1, c2, c3 = st.columns(3)
    c1.metric("Wiki pages", s["pages"])
    c2.metric("Raw sources", s["raw_files"])
    c3.metric("Data size (MB)", round(s["data_bytes"] / 1_048_576, 2))

    # Same segmented control as the primary nav, for the same reason (see
    # docs/ui.md §Pages): st.tabs evaluates every branch on every rerun, so the
    # index health read, the orphan scan and the log read all ran on each click.
    _maint_options = ["Search index", "Delete source", "Link graph health", "Lint",
                      "Activity log"]
    if auth.is_admin(_user):
        _maint_options.append("Admin")
    # Admin disappears when the user is not one. Written *before* the widget:
    # a post-instantiation write to a widget key raises.
    if st.session_state.get("maint_view") not in _maint_options:
        st.session_state["maint_view"] = _maint_options[0]
    _maint_view = st.segmented_control(
        "Maintenance section", _maint_options, required=True, key="maint_view",
        label_visibility="collapsed", width="stretch",
    )

    if _maint_view == "Search index":
        _health = lex_index.index_health()
        st.caption(
            "Lexical BM25 index (`index/chunks.sqlite`) — the grounding source for "
            "search, both chat modes, and the research agent. It is a derived cache: "
            "rebuilding reads `chunks/` + `wiki/` only, never the LLM."
        )
        _ic1, _ic2 = st.columns(2)
        _ic1.metric("Source chunks indexed", _health["raw"])
        _ic2.metric("Wiki page chunks indexed", _health["wiki"])
        if not _health["wiki"]:
            st.warning(
                "**No index for this database.** Databases last built before the FTS5 "
                "cutover have none, so every search and chat answer comes back empty. "
                "Rebuild to fix it."
            )
        if _can_maintain:
            if st.button("Rebuild search index", key="rebuild_index_btn"):
                with st.spinner("Rebuilding index…"):
                    _res = wiki_engine.rebuild_lex_index()
                st.success(f"Indexed {_res['chunks']} chunks.")
                st.rerun()
        else:
            st.info("Only maintainers of this database can rebuild the index.")

    elif _maint_view == "Link graph health":
        orphans = wiki_engine.find_orphans()
        if orphans:
            st.warning(f"**{len(orphans)} orphan(s)** — pages with no `related` in-links.")
            st.code("\n".join(orphans), language=None)
        else:
            st.success("No orphans — every page is linked from at least one other page.")

    elif _maint_view == "Lint":
        st.caption("Ask the LLM to review wiki quality: contradictions, orphans, gaps, suggestions.")
        if st.button("Run lint", key="run_lint_btn"):
            with st.spinner("Running lint (may take a minute)…"):
                try:
                    report = wiki_engine.lint()
                    st.markdown(report)
                except RuntimeError as e:
                    st.error(str(e))

    elif _maint_view == "Delete source":
        if _can_maintain:
            _sources = dedup.list_sources()
            if not _sources:
                st.info("No sources ingested yet.")
            else:
                _selected = st.selectbox("Source to delete", _sources)
                st.warning(
                    "Deletes the raw file, all chunks, QA pairs, and **all wiki pages** "
                    "that reference this source. This cannot be undone."
                )
                _confirmed = st.checkbox("I understand this is irreversible")
                if st.button("Delete source", key="delete_source_btn", disabled=not _confirmed):
                    with st.spinner("Deleting…"):
                        _result = wiki_engine.delete_source(_selected)
                    st.success(
                        f"Deleted **{_selected}**. "
                        f"Wiki pages removed: {len(_result['wiki_pages'])}. "
                        f"QA rows removed: {_result['qa_rows']}. "
                        "Index rebuilt."
                    )
                    st.rerun()
        else:
            st.info("Delete actions require maintainer rights for this database.")

    elif _maint_view == "Activity log":
        st.code(wiki_engine.read_log(), language=None)

    elif _maint_view == "Admin" and auth.is_admin(_user):
        # `st.container()` only to keep this block's indentation; it was
        # previously mis-wired to `_tabs[5]` (Reset all data), which is why the
        # Admin tab rendered empty.
        with st.container():
            st.subheader("Databases (admin)")
            _existing_dbs = db_context.list_dbs()
            st.markdown("**Existing:** " + (", ".join(f"`{d}`" for d in _existing_dbs) or "(none)"))
            _all_usernames = [u["username"] for u in auth.list_users()]
            with st.form("create_db_form"):
                _new_db = st.text_input("New database name (letters, digits, _ - space)")
                _new_maintainers = st.multiselect(
                    "Maintainers (may upload/delete in this database)",
                    options=_all_usernames,
                    default=[_user],
                )
                _create_db = st.form_submit_button("Create database")
            if _create_db:
                try:
                    _name = _new_db.strip()
                    db_context.create_db(_name)
                    for _m in {_user, *_new_maintainers}:
                        auth.grant_maintainer(_m, _name)
                    st.success(f"Created `{_name}` and assigned maintainers.")
                    st.rerun()
                except ValueError as e:
                    st.error(str(e))

            st.markdown("---")
            st.subheader("Users (admin)")
            _users = auth.list_users()
            for _ud in _users:
                with st.expander(f"{_ud['username']}  ·  dbs: {_ud['dbs']}  ·  admin: {_ud['is_admin']}"):
                    _all_dbs = db_context.list_dbs()
                    _new_dbs = st.multiselect(
                        "Allowed databases",
                        options=_all_dbs,
                        default=[d for d in _ud["dbs"] if d in _all_dbs],
                        key=f"udbs_{_ud['username']}",
                    )
                    _new_maint = st.multiselect(
                        "Maintained databases (may upload/delete)",
                        options=_new_dbs,
                        default=[d for d in _ud["maintains"] if d in _new_dbs],
                        key=f"umaint_{_ud['username']}",
                    )
                    _new_pw = st.text_input(
                        "New password (leave blank to keep)",
                        type="password",
                        key=f"upw_{_ud['username']}",
                    )
                    c1, c2, c3 = st.columns(3)
                    if c1.button("Save", key=f"usave_{_ud['username']}"):
                        auth.set_user_dbs(_ud["username"], _new_dbs)
                        auth.set_user_maintains(
                            _ud["username"], [d for d in _new_maint if d in _new_dbs]
                        )
                        if _new_pw:
                            auth.change_password(_ud["username"], _new_pw)
                        st.success("Updated.")
                        st.rerun()
                    if c2.button("Delete", key=f"udel_{_ud['username']}",
                                 disabled=_ud["username"] == _user):
                        auth.delete_user(_ud["username"])
                        st.success(f"Deleted {_ud['username']}.")
                        st.rerun()

            st.markdown("**Add user**")
            with st.form("add_user_form"):
                _nu = st.text_input("Username")
                _np = st.text_input("Password", type="password")
                _ndbs = st.multiselect("Allowed databases", options=db_context.list_dbs())
                _nmaint = st.multiselect(
                    "Maintained databases (may upload/delete)", options=db_context.list_dbs()
                )
                _nadm = st.checkbox("Admin")
                _add = st.form_submit_button("Add user")
            if _add:
                try:
                    _maint = [d for d in _nmaint if d in _ndbs]
                    auth.add_user(_nu.strip(), _np, _ndbs, is_admin=_nadm, maintains=_maint)
                    st.success(f"Added user `{_nu.strip()}`.")
                    st.rerun()
                except ValueError as e:
                    st.error(str(e))


if _NEWSPAPER:
    theme.colophon()
