"""LocalWiki — Streamlit UI."""

import gc
import os
import re
import tempfile
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

load_dotenv()

import auth
import db_context
import dedup
import file_processor
import ollama_client
import template_loader
import wiki_engine
import agent as research_agent
import chat_agent

st.set_page_config(
    page_title="LocalWiki",
    page_icon="📖",
    layout="wide",
    initial_sidebar_state="expanded",
)

# NYT-inspired editorial style
st.markdown(
    """
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Libre+Baskerville:ital,wght@0,400;0,700;1,400&family=Source+Sans+3:wght@400;600&display=swap');
    html, body, [class*="css"] { font-family: 'Source Sans 3', sans-serif; }
    h1, h2, h3 { font-family: 'Libre Baskerville', Georgia, serif; font-weight: 700; }
    .block-container { padding-top: 2rem; }
    .stButton>button { border-radius: 2px; font-weight: 600; letter-spacing: 0.04em; text-transform: uppercase; font-size: 0.8rem; }
    hr { border-top: 2px solid #234637; margin: 1.5rem 0; }
    </style>
    """,
    unsafe_allow_html=True,
)


_CHUNK_SUFFIX_RE = re.compile(r"\s*\[Teil\s+\d+/\d+\]\s*$")
_CITE_SECTION_SUFFIX_RE = re.compile(r"\s*[§#].*$")


@st.dialog("Source", width="large")
def _show_md_dialog(title: str, content: str) -> None:
    st.subheader(title)
    st.markdown(content)


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


def _raw_source_button(filename: str, key: str) -> None:
    base = _CHUNK_SUFFIX_RE.sub("", filename)
    base = _CITE_SECTION_SUFFIX_RE.sub("", base).strip()
    if base.lower().endswith((".md", ".txt")):
        data = wiki_engine.read_raw_source(base)
        if data is None:
            st.markdown(f"- `{filename}` *(not found)*")
            return
        if st.button(filename, key=key):
            _show_md_dialog(filename, data.decode("utf-8", errors="replace"))
    else:
        st.markdown(f"- `{filename}`")


def _render_wiki_nav(key_prefix: str) -> str | None:
    """Render wiki navigation tree in a narrow column. Returns clicked filename or None."""
    search = st.text_input(
        "Search pages", placeholder="Search…",
        key=f"{key_prefix}_nav_search", label_visibility="collapsed",
    ).strip()
    selected: str | None = None
    if search:
        results = wiki_engine.search_wiki(search)
        st.caption(f"{len(results)} result(s)")
        for r in results:
            if st.button(r["title"], key=f"{key_prefix}_hit_{r['filename']}", use_container_width=True):
                st.session_state[f"{key_prefix}_selected_page"] = r["filename"]
                selected = r["filename"]
    else:
        tree = wiki_engine.get_wiki_tree()
        group_labels = {
            "concept": "Concepts", "entity": "Entities",
            "source-summary": "Source Summaries", "comparison": "Comparisons", "other": "Other",
        }
        for grp in ["concept", "entity", "source-summary", "comparison", "other"]:
            group = tree.get(grp)
            if not group:
                continue
            with st.expander(f"{group_labels[grp]} ({len(group)})", expanded=(grp == "concept")):
                for p in group:
                    title = p.get("title", p["filename"])
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
                parsed = wiki_engine.read_page_parsed(s)
                _show_md_dialog(s, parsed["content"])
    if raw_sources:
        st.markdown("**Documents**")
        for r in raw_sources:
            _raw_source_button(r, f"cpanel_raw_{r}")


def _render_research_sources_panel() -> None:
    sources = st.session_state.get("research_sources", [])
    if not sources:
        st.caption("Sources appear here during research.")
        return
    for i, src in enumerate(sources):
        st.markdown(f"**{src['tool']}**")
        st.caption(src["query"])
        if i < len(sources) - 1:
            st.markdown("---")


def _run_research_stream(question_to_run: str, display_q: str, wiki_context: str, auto_save: bool) -> None:
    st.session_state["research_sources"] = []
    st.session_state["last_research_q"] = display_q
    _interpreted = question_to_run if question_to_run.strip() != display_q.strip() else None
    st.session_state["last_research_interpreted"] = _interpreted
    st.markdown(f"**Research question:** {display_q}")
    steps_container = st.container()
    with steps_container:
        for step in research_agent.run_research_agent(question_to_run, wiki_context):
            stype = step["type"]
            if stype == "thought":
                with st.expander("Thought", expanded=False):
                    st.markdown(step["content"])
            elif stype == "tool_call":
                st.info(f"**{step['name']}** — `{step['args']}`")
                st.session_state.setdefault("research_sources", []).append(
                    {"tool": step["name"], "query": str(step["args"])[:80]}
                )
            elif stype == "tool_result":
                with st.expander(f"Result: {step['name']}", expanded=False):
                    st.text(step["result"][:800])
            elif stype == "final_answer":
                st.success("Research complete.")
                if step.get("report_path"):
                    st.session_state["last_report"] = step["report_path"]
                    try:
                        _rel = "comparisons/" + step["report_path"].split("comparisons/")[-1]
                        st.session_state["last_research_answer"] = wiki_engine.read_page_parsed(_rel)["content"]
                    except Exception:
                        st.session_state["last_research_answer"] = ""
                    if auto_save:
                        try:
                            from pathlib import Path as _P
                            import os as _os
                            wiki_dir = db_context.wiki_dir()
                            report_path = wiki_dir / "comparisons" / _P(step["report_path"].split("comparisons/")[-1])
                            if report_path.exists():
                                wiki_engine.ingest(report_path.read_text(), f"Research: {display_q[:60]}")
                                st.success("Report also ingested into wiki.")
                        except Exception as exc:
                            st.warning(f"Auto-save to wiki failed: {exc}")
                else:
                    st.session_state["last_research_answer"] = step.get("content", "")
                    if not step.get("content", "").strip():
                        st.warning("Agent completed but produced no answer text.")
                st.session_state.setdefault("research_history", []).append({
                    "q": display_q,
                    "a": st.session_state.get("last_research_answer", ""),
                    "interpreted": _interpreted,
                    "report": (("comparisons/" + step["report_path"].split("comparisons/")[-1])
                               if step.get("report_path") else None),
                })
            elif stype == "error":
                st.error(step["content"])


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


def _ollama_badge() -> None:
    ok = ollama_client.is_available()
    color = "#2d6a2d" if ok else "#a00"
    label = "Ollama online" if ok else "Ollama offline"
    st.sidebar.markdown(
        f'<span style="background:{color};color:#fff;padding:2px 8px;border-radius:2px;font-size:0.75rem;font-weight:600">{label}</span>',
        unsafe_allow_html=True,
    )
    st.sidebar.caption(f"Model: {ollama_client._MODEL}")


# --- bootstrap: migrate legacy data layout + seed default user ---
db_context.migrate_legacy_layout()
auth.ensure_seeded()
auth.backfill_maintainers()

# --- login gate ---
if not st.session_state.get("user"):
    st.title("📖 LocalWiki — Sign in")
    with st.form("login_form"):
        u = st.text_input("Username")
        p = st.text_input("Password", type="password")
        ok = st.form_submit_button("Sign in", type="primary")
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
_ollama_badge()

st.sidebar.caption(f"Signed in as **{_user}**")
if st.sidebar.button("Logout", key="logout_btn"):
    for _k in ("user", "active_db", "messages", "chat_followup",
               "research_history", "last_research_q", "last_research_answer",
               "last_report", "research_sources"):
        st.session_state.pop(_k, None)
    st.rerun()

_db_choice = st.sidebar.selectbox(
    "Database",
    options=_allowed_dbs,
    index=_allowed_dbs.index(st.session_state["active_db"]),
    key="db_selector",
)
if _db_choice != st.session_state["active_db"]:
    st.session_state["active_db"] = _db_choice
    db_context.set_active_db(_db_choice)
    # Clear per-DB session state to avoid cross-DB leakage.
    for _k in ("messages", "chat_followup", "research_history",
               "last_research_q", "last_research_answer", "last_report",
               "research_sources", "explorer_selected_page", "last_contradictions"):
        st.session_state.pop(_k, None)
    st.rerun()

st.sidebar.markdown("---")

_nav_options = ["Wiki Explorer", "Wiki Chat", "Research", "Maintenance"]
if _can_maintain:
    _nav_options.insert(0, "Upload")
page = st.sidebar.radio(
    "Navigate",
    _nav_options,
    label_visibility="collapsed",
    key="page_nav",
)

s = wiki_engine.stats()
st.sidebar.markdown(f"**{s['pages']}** pages &nbsp;·&nbsp; **{s['raw_files']}** sources", unsafe_allow_html=True)

st.sidebar.markdown("---")
if st.sidebar.button("Reset session", type="secondary",
                     help="Unload model from VRAM and reset session. Server stays running."):
    _safe_reset()


# --- pages ---

if page == "Upload":
    st.title("Upload a Document")
    if not _can_maintain:
        st.error("You are not a maintainer of this database. Ask an admin for maintainer rights.")
        st.stop()
    st.markdown("Upload a Markdown (.md) file to ingest into the wiki.")
    uploaded = st.file_uploader(
        "Choose file", type=["md"], label_visibility="collapsed"
    )
    if uploaded:
        raw = uploaded.read()
        if dedup.is_duplicate(raw):
            st.warning(f"**{uploaded.name}** has already been ingested (duplicate detected).")
        else:
            st.info(f"New file: **{uploaded.name}** ({len(raw):,} bytes)")
            st.markdown("**Optional metadata** — fill in to make the ingest more reliable.")
            fields = template_loader.load_insert_template()
            with st.form("ingest_form"):
                values = {f: st.text_input(f.capitalize()) for f in fields}
                submitted = st.form_submit_button("Ingest into wiki", type="primary")
            if submitted:
                user_meta = {k: v.strip() for k, v in values.items() if v and v.strip()}
                with st.spinner("Saving file…"):
                    saved = dedup.register_file(raw, uploaded.name)
                with st.spinner("Extracting text…"):
                    text = file_processor.extract_text(saved)
                chunks = file_processor.chunk_text(text)
                n = len(chunks)
                try:
                    if n > 1:
                        st.info(f"Dokument aufgeteilt in {n} Teile — jeder Teil wird separat verarbeitet.")
                        progress = st.progress(0)
                    with st.spinner("Indexing document (chunker, lexical index, sidecars)…"):
                        ctx = wiki_engine.ingest_begin(text, uploaded.name, user_meta or None)
                    for i, chunk in enumerate(chunks):
                        label = "Running LLM ingest (this may take a minute)…" if n == 1 else f"Teil {i + 1}/{n} wird verarbeitet…"
                        with st.spinner(label):
                            wiki_engine.ingest_piece(ctx, chunk, i, n)
                        if n > 1:
                            progress.progress((i + 1) / n)
                    with st.spinner("Finalising index…"):
                        result = wiki_engine.ingest_end(ctx)
                    st.success("Ingest complete.")
                    col1, col2, col3 = st.columns(3)
                    col1.metric("Created", len(result["created"]))
                    col2.metric("Updated", len(result["updated"]))
                    col3.metric("Contradictions", len(result["contradictions"]))
                    if result["created"]:
                        st.markdown("**New pages:** " + ", ".join(f"`{f}`" for f in result["created"]))
                    if result.get("affected"):
                        st.caption("Pre-loaded for merge: " + ", ".join(f"`{f}`" for f in result["affected"]))
                    if result["contradictions"]:
                        st.warning("Contradictions found:\n" + "\n".join(f"- {c}" for c in result["contradictions"]))
                        st.session_state["last_contradictions"] = result["contradictions"]
                        st.session_state["last_contradiction_pages"] = list({*result["created"], *result["updated"], *result.get("affected", [])})
                except RuntimeError as e:
                    st.error(str(e))

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
    st.title("Wiki Explorer")
    pages = wiki_engine.list_pages()
    if not pages:
        st.info("No wiki pages yet. Upload a document to get started.")
    else:
        view_mode = st.radio(
            "View", ["Tree", "Graph"],
            horizontal=True, label_visibility="collapsed",
        )

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

        else:  # Graph
            main_col, nav_col = st.columns([3, 1])
            with nav_col:
                clicked = _render_wiki_nav("explorer_graph")
                if clicked:
                    parsed = wiki_engine.read_page_parsed(clicked)
                    _show_md_dialog(clicked, parsed["content"])
            with main_col:
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


elif page == "Wiki Chat":
    st.title("Wiki Chat")
    st.caption("Ask questions — Fast mode reads wiki pages; Deep mode reasons over the original documents.")

    if "messages" not in st.session_state:
        st.session_state["messages"] = []

    main_col, nav_col = st.columns([3, 1])

    with nav_col:
        st.markdown("#### Sources")
        _render_chat_sources_panel()

    with main_col:
        if st.button("🆕 New chat", key="new_chat"):
            st.session_state.pop("messages", None)
            st.session_state.pop("chat_followup", None)
            st.rerun()

        mode = st.radio(
            "Mode", ["Fast", "Deep"], horizontal=True, key="chat_mode",
            help="Fast: one-shot retrieval over wiki pages. Deep: agentic loop over data/raw/ originals (~2x slower than Research, but more grounded).",
        )

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
                if msg["role"] == "assistant" and msg.get("question") and not msg["content"].startswith("Error:"):
                    if st.button("↪ Follow up", key=f"followup_{i}"):
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
            if st.button("Save answer to wiki", key="save_answer"):
                try:
                    rel = wiki_engine.file_answer(last["question"], last["content"], last.get("sources", []))
                    st.success(f"Filed as `{rel}`")
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

    # chat_input at root level for sticky-bottom behavior
    if prompt := st.chat_input("Ask something…"):
        fu = st.session_state.pop("chat_followup", None)
        if fu:
            with st.spinner("Rephrasing follow-up…"):
                q_to_ask = wiki_engine.condense_followup(fu["q"], fu["a"], prompt)
        else:
            q_to_ask = prompt
        interpreted = q_to_ask if (fu and q_to_ask.strip() != prompt.strip()) else None
        st.session_state["messages"].append({"role": "user", "content": prompt})
        if st.session_state.get("chat_mode", "Fast") == "Fast":
            st.markdown(f"**You:** {prompt}")
            with st.spinner("Thinking…"):
                try:
                    res = wiki_engine.query_with_sources(q_to_ask)
                    answer = res["answer"]
                    sources = res["sources"]
                    raw_sources = res["raw_sources"]
                except RuntimeError as e:
                    answer, sources, raw_sources = f"Error: {e}", [], []
            st.session_state["messages"].append(
                {"role": "assistant", "content": answer, "question": prompt,
                 "sources": sources, "raw_sources": raw_sources, "interpreted": interpreted}
            )
        else:
            steps: list[dict] = []
            answer = ""
            raw_sources: list[str] = []
            st.markdown(f"**You:** {prompt}")
            _live = st.container()
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
                    elif stype == "error" and not answer:
                        answer = f"Error: {step['content']}"
            st.session_state["messages"].append(
                {"role": "assistant", "content": answer or "(no answer)", "question": prompt,
                 "sources": [], "raw_sources": raw_sources, "steps": steps, "interpreted": interpreted}
            )
        st.rerun()


elif page == "Research":
    st.title("Research Agent")
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
        if st.button("🆕 New research", key="new_research"):
            for _k in ("research_history", "last_research_q", "last_research_answer",
                       "last_research_interpreted", "last_report", "research_sources",
                       "research_followup_input"):
                st.session_state.pop(_k, None)
            st.rerun()

        question = st.text_input("Research question", placeholder="e.g. What are the latest advances in RAG?")

        with st.expander("Extra wiki paste (optional — the agent browses the wiki on its own)"):
            wiki_context = st.text_area(
                "Optional extra context. Leave blank — the agent will run wiki_search first automatically.",
                height=120,
                label_visibility="collapsed",
            )

        auto_save = st.checkbox("Auto-save final report to wiki", value=True)

        if st.button("Start research", type="primary", disabled=not (tavily_key and question)):
            _run_research_stream(question, question, wiki_context or "", auto_save)
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
            _ans = st.session_state["last_research_answer"]
            st.markdown(_ans)
            st.download_button(
                "Download report",
                data=_ans,
                file_name=(st.session_state["last_report"].split("comparisons/")[-1]
                           if st.session_state.get("last_report") else "research-answer.md"),
                mime="text/markdown",
                key="dl_report",
            )

        if st.session_state.get("last_research_q"):
            st.markdown("---")
            st.markdown("**↪ Follow-up research**")
            fq = st.text_input("Ask a follow-up about the last research answer", key="research_followup_input")
            if st.button("Ask follow-up", key="research_followup_go", disabled=not (tavily_key and fq)):
                with st.spinner("Rephrasing follow-up…"):
                    standalone = wiki_engine.condense_followup(
                        st.session_state["last_research_q"],
                        st.session_state.get("last_research_answer", ""), fq)
                _run_research_stream(standalone, fq, "", auto_save)
                st.rerun()


elif page == "Maintenance":
    st.title("Maintenance")
    s = wiki_engine.stats()
    c1, c2, c3 = st.columns(3)
    c1.metric("Wiki pages", s["pages"])
    c2.metric("Raw sources", s["raw_files"])
    c3.metric("Data size (MB)", round(s["data_bytes"] / 1_048_576, 2))

    st.markdown("---")
    st.subheader("Link graph health")
    orphans = wiki_engine.find_orphans()
    if orphans:
        st.warning(f"**{len(orphans)} orphan(s)** — pages with no `related` in-links.")
        st.code("\n".join(orphans), language=None)
    else:
        st.success("No orphans — every page is linked from at least one other page.")

    st.markdown("---")
    st.subheader("Lint")
    st.caption("Ask the LLM to review wiki quality: contradictions, orphans, gaps, suggestions.")
    if st.button("Run lint", type="primary"):
        with st.spinner("Running lint (may take a minute)…"):
            try:
                report = wiki_engine.lint()
                st.markdown(report)
            except RuntimeError as e:
                st.error(str(e))

    if _can_maintain:
        st.markdown("---")
        st.subheader("Delete Source")
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
            if st.button("Delete source", disabled=not _confirmed, type="primary"):
                with st.spinner("Deleting…"):
                    _result = wiki_engine.delete_source(_selected)
                st.success(
                    f"Deleted **{_selected}**. "
                    f"Wiki pages removed: {len(_result['wiki_pages'])}. "
                    f"QA rows removed: {_result['qa_rows']}. "
                    "Index rebuilt."
                )
                st.rerun()

        st.markdown("---")
        st.subheader("Reset all data")
        st.error(
            "Deletes EVERY raw source, chunk, QA pair, lexical index entry, and "
            "wiki page. Wiki is re-initialised empty. Used to start tests fresh."
        )
        _reset_ok = st.checkbox("I understand this wipes all ingested data")
        if st.button("Reset all data", disabled=not _reset_ok):
            with st.spinner("Wiping…"):
                _counts = wiki_engine.reset_all_data()
            st.success(f"Cleared: {_counts}")
            st.rerun()
    else:
        st.markdown("---")
        st.info("Delete and reset actions require maintainer rights for this database.")

    st.markdown("---")
    st.subheader("Activity Log")
    st.code(wiki_engine.read_log(), language=None)

    if auth.is_admin(_user):
        st.markdown("---")
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
                # Grant the creator plus any chosen maintainers access + maintainer rights.
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
