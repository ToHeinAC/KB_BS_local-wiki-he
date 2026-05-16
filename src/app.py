"""LocalWiki — Streamlit UI."""

import gc
import os
import re
import tempfile
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

load_dotenv()

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


wiki_engine.init_wiki()

st.sidebar.markdown("## 📖 LocalWiki")
_ollama_badge()

page = st.sidebar.radio(
    "Navigate",
    ["Upload", "Wiki Explorer", "Chat", "Research", "Maintenance"],
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
    st.markdown("Upload a PDF, Word document, Markdown, or plain-text file to ingest into the wiki.")
    uploaded = st.file_uploader(
        "Choose file", type=["pdf", "docx", "md", "txt", "html"], label_visibility="collapsed"
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
                        "**Legend:** blue dot = wiki page, orange diamond = source document. "
                        "Solid grey = `related-to` (page ↔ page). "
                        "Dashed orange → = `derived-from` (page → source)."
                    )
                    orphans = wiki_engine.find_orphans()
                    if orphans:
                        st.caption(f"**{len(orphans)} orphan(s)** (no in-links): " + ", ".join(f"`{o}`" for o in orphans[:20]))
                except Exception as exc:
                    st.error(f"Graph render failed: {exc}")


elif page == "Chat":
    st.title("Chat with the Wiki")
    st.caption("Ask questions — Fast mode reads wiki pages; Deep mode reasons over the original documents.")

    if "messages" not in st.session_state:
        st.session_state["messages"] = []

    main_col, nav_col = st.columns([3, 1])

    with nav_col:
        st.markdown("#### Sources")
        _render_chat_sources_panel()

    with main_col:
        mode = st.radio(
            "Mode", ["Fast", "Deep"], horizontal=True, key="chat_mode",
            help="Fast: one-shot retrieval over wiki pages. Deep: agentic loop over data/raw/ originals (~2x slower than Research, but more grounded).",
        )

        for i, msg in enumerate(st.session_state["messages"]):
            with st.chat_message(msg["role"]):
                st.markdown(msg["content"])
                if msg["role"] == "assistant" and msg.get("steps"):
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

    # chat_input at root level for sticky-bottom behavior
    if prompt := st.chat_input("Ask something…"):
        st.session_state["messages"].append({"role": "user", "content": prompt})
        if st.session_state.get("chat_mode", "Fast") == "Fast":
            with st.spinner("Thinking…"):
                try:
                    res = wiki_engine.query_with_sources(prompt)
                    answer = res["answer"]
                    sources = res["sources"]
                    raw_sources = res["raw_sources"]
                except RuntimeError as e:
                    answer, sources, raw_sources = f"Error: {e}", [], []
            st.session_state["messages"].append(
                {"role": "assistant", "content": answer, "question": prompt,
                 "sources": sources, "raw_sources": raw_sources}
            )
        else:
            steps: list[dict] = []
            answer = ""
            raw_sources: list[str] = []
            with st.spinner("Deep chat — agent is searching originals…"):
                for step in chat_agent.run_chat_agent(prompt):
                    steps.append(step)
                    if step["type"] == "final_answer":
                        answer = step["content"]
                        raw_sources = step.get("sources", []) or []
                    elif step["type"] == "error" and not answer:
                        answer = f"Error: {step['content']}"
            st.session_state["messages"].append(
                {"role": "assistant", "content": answer or "(no answer)", "question": prompt,
                 "sources": [], "raw_sources": raw_sources, "steps": steps}
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
        question = st.text_input("Research question", placeholder="e.g. What are the latest advances in RAG?")

        with st.expander("Extra wiki paste (optional — the agent browses the wiki on its own)"):
            wiki_context = st.text_area(
                "Optional extra context. Leave blank — the agent will run wiki_search first automatically.",
                height=120,
                label_visibility="collapsed",
            )

        auto_save = st.checkbox("Auto-save final report to wiki", value=True)

        if st.button("Start research", type="primary", disabled=not (tavily_key and question)):
            st.session_state["research_sources"] = []
            steps_container = st.container()
            with steps_container:
                for step in research_agent.run_research_agent(question, wiki_context or ""):
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
                            if auto_save:
                                try:
                                    from pathlib import Path as _P
                                    import os as _os
                                    wiki_dir = _P(_os.getenv("WIKI_DIR", "data/wiki"))
                                    report_path = wiki_dir / "comparisons" / _P(step["report_path"].split("comparisons/")[-1])
                                    if report_path.exists():
                                        wiki_engine.ingest(report_path.read_text(), f"Research: {question[:60]}")
                                        st.success("Report also ingested into wiki.")
                                except Exception as exc:
                                    st.warning(f"Auto-save to wiki failed: {exc}")
                        else:
                            st.markdown(step["content"])
                    elif stype == "error":
                        st.error(step["content"])

        if st.session_state.get("last_report"):
            _rp = st.session_state["last_report"]
            _report_filename = _rp.split("comparisons/")[-1]
            _report_rel = f"comparisons/{_report_filename}"
            st.markdown(f"Report saved: `{_report_rel}`")
            if st.button(_report_filename, key="view_report"):
                _parsed = wiki_engine.read_page_parsed(_report_rel)
                _show_md_dialog(_report_filename, _parsed["content"])


elif page == "Maintenance":
    st.title("Maintenance")
    s = wiki_engine.stats()
    c1, c2, c3 = st.columns(3)
    c1.metric("Wiki pages", s["pages"])
    c2.metric("Raw sources", s["raw_files"])
    c3.metric("Log size (bytes)", s["log_bytes"])

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

    st.markdown("---")
    st.subheader("Activity Log")
    st.code(wiki_engine.read_log(), language=None)
