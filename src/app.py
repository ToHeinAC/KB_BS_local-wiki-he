"""LocalWiki — Streamlit UI."""

import gc
import os
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
    .block-container { max-width: 900px; padding-top: 2rem; }
    .stButton>button { border-radius: 2px; font-weight: 600; letter-spacing: 0.04em; text-transform: uppercase; font-size: 0.8rem; }
    hr { border-top: 2px solid #234637; margin: 1.5rem 0; }
    </style>
    """,
    unsafe_allow_html=True,
)


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
                    agg: dict = {"created": [], "updated": [], "contradictions": [], "affected": []}
                    if n > 1:
                        st.info(f"Dokument aufgeteilt in {n} Teile — jeder Teil wird separat verarbeitet.")
                        progress = st.progress(0)
                    for i, chunk in enumerate(chunks):
                        chunk_name = uploaded.name if n == 1 else f"{uploaded.name} [Teil {i + 1}/{n}]"
                        meta = user_meta or None if i == 0 else None
                        label = "Running LLM ingest (this may take a minute)…" if n == 1 else f"Teil {i + 1}/{n} wird verarbeitet…"
                        with st.spinner(label):
                            r = wiki_engine.ingest(chunk, chunk_name, meta)
                        for k in agg:
                            agg[k].extend(x for x in r[k] if x not in agg[k])
                        if n > 1:
                            progress.progress((i + 1) / n)
                    result = agg
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
            "View",
            ["Tree", "Graph"],
            horizontal=True,
            label_visibility="collapsed",
        )
        if view_mode == "Graph":
            try:
                import json as _json
                graph = wiki_engine.build_link_graph()
                title_map = {p["filename"]: p["title"] for p in pages}
                col1, col2 = st.columns(2)
                show_names = col1.toggle("Node names", value=True)
                show_themes = col2.toggle("Edge themes", value=False)

                def _abbrev(text: str, n: int = 3) -> str:
                    return " ".join(str(text).replace("-", " ").split()[:n])

                nodes_data, edges_data = [], []
                for node in graph:
                    bare = node.split("/")[-1]
                    title = title_map.get(bare) or title_map.get(node) or bare
                    nodes_data.append({
                        "id": node,
                        "label": _abbrev(title, 5) if show_names else "",
                        "title": title,
                    })
                for src, targets in graph.items():
                    for tgt in targets:
                        if tgt in graph:
                            edge: dict = {"from": src, "to": tgt}
                            if show_themes:
                                bare_tgt = tgt.split("/")[-1]
                                theme = title_map.get(bare_tgt) or title_map.get(tgt) or bare_tgt
                                edge["label"] = _abbrev(theme)
                            edges_data.append(edge)

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
  {{nodes:{{shape:"dot",size:18,font:{{size:14,color:"#234637"}},
           color:{{background:"#97c2fc",border:"#2B7CE9"}}}},
    edges:{{font:{{size:11,color:"#555",align:"middle"}},
            color:{{color:"#aaa",inherit:false}},
            smooth:{{type:"continuous"}}}},
    physics:{{barnesHut:{{gravitationalConstant:-5000,springLength:120,springConstant:0.04}},
              stabilization:{{fit:true,iterations:300}}}}}});
</script></body></html>"""
                st.components.v1.html(html, height=620, scrolling=True)
                orphans = wiki_engine.find_orphans()
                if orphans:
                    st.caption(f"**{len(orphans)} orphan(s)** (no in-links): " + ", ".join(f"`{o}`" for o in orphans[:20]))
            except Exception as exc:
                st.error(f"Graph render failed: {exc}")
            search = ""
            selected_file = None
        else:
            search = st.text_input(
                "Search pages",
                placeholder="Search titles and page bodies…",
            ).strip()
            selected_file = st.session_state.get("selected_page")

        if view_mode == "Tree" and search:
            results = wiki_engine.search_wiki(search)
            st.markdown(f"**{len(results)}** match{'es' if len(results) != 1 else ''} for *{search}*")
            for r in results:
                if st.button(r["title"], key=f"hit_{r['filename']}", use_container_width=True):
                    st.session_state["selected_page"] = r["filename"]
                    selected_file = r["filename"]
                st.markdown(f"<span style='color:#666;font-style:italic'>{r['excerpt']}</span>", unsafe_allow_html=True)
        elif view_mode == "Tree":
            tree = wiki_engine.get_wiki_tree()
            group_labels = {
                "concept": "Concepts",
                "entity": "Entities",
                "source-summary": "Source Summaries",
                "comparison": "Comparisons",
                "other": "Other",
            }
            order = ["concept", "entity", "source-summary", "comparison", "other"]
            for key in order:
                group = tree.get(key)
                if not group:
                    continue
                with st.expander(f"{group_labels[key]} ({len(group)})", expanded=(key == "concept")):
                    for p in group:
                        cols = st.columns([4, 1, 1])
                        title = p.get("title", p["filename"])
                        if cols[0].button(title, key=f"page_{p['filename']}", use_container_width=True):
                            st.session_state["selected_page"] = p["filename"]
                            selected_file = p["filename"]
                        cols[1].markdown(p.get("confidence", "—"))
                        cols[2].markdown(p.get("updated", "—"))

        if view_mode == "Tree" and selected_file:
            st.markdown("---")
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
                            st.markdown(f"- `data/raw/{s}`")
                    if related:
                        st.markdown("**Related wiki pages**")
                        for r in related:
                            st.markdown(f"- `data/wiki/{r}`")


elif page == "Chat":
    st.title("Chat with the Wiki")
    st.caption("Ask questions — answers are drawn from your wiki pages.")

    if "messages" not in st.session_state:
        st.session_state["messages"] = []

    for msg in st.session_state["messages"]:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    if prompt := st.chat_input("Ask something…"):
        st.session_state["messages"].append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)
        with st.chat_message("assistant"):
            with st.spinner("Thinking…"):
                try:
                    res = wiki_engine.query_with_sources(prompt)
                    answer = res["answer"]
                    sources = res["sources"]
                    raw_sources = res["raw_sources"]
                except RuntimeError as e:
                    answer, sources, raw_sources = f"Error: {e}", [], []
            st.markdown(answer)
            if sources or raw_sources:
                with st.expander("Sources", expanded=False):
                    if sources:
                        st.markdown("**Wiki pages (data/wiki/)**")
                        for s in sources:
                            st.markdown(f"- `data/wiki/{s}`")
                    if raw_sources:
                        st.markdown("**Original documents (data/raw/)**")
                        for r in raw_sources:
                            st.markdown(f"- `data/raw/{r}`")
        st.session_state["messages"].append(
            {"role": "assistant", "content": answer, "question": prompt, "sources": sources, "raw_sources": raw_sources}
        )

    # Save-to-Wiki button under the most recent assistant turn (Karpathy filing-back).
    last = st.session_state["messages"][-1] if st.session_state["messages"] else None
    if last and last["role"] == "assistant" and last.get("question") and not last["content"].startswith("Error:"):
        if st.button("Save answer to wiki", key="save_answer"):
            try:
                rel = wiki_engine.file_answer(last["question"], last["content"], last.get("sources", []))
                st.success(f"Filed as `{rel}`")
            except RuntimeError as e:
                st.error(str(e))


elif page == "Research":
    st.title("Research Agent")
    tavily_key = os.getenv("TAVILY_API_KEY", "")

    if not tavily_key:
        st.warning(
            "**TAVILY_API_KEY not set.** Add it to your `.env` file to enable web research.\n\n"
            "Get a free key at [tavily.com](https://tavily.com)."
        )

    question = st.text_input("Research question", placeholder="e.g. What are the latest advances in RAG?")

    with st.expander("Extra wiki paste (optional — the agent browses the wiki on its own)"):
        wiki_context = st.text_area(
            "Optional extra context. Leave blank — the agent will run wiki_search first automatically.",
            height=120,
            label_visibility="collapsed",
        )

    auto_save = st.checkbox("Auto-save final report to wiki", value=True)

    if st.button("Start research", type="primary", disabled=not (tavily_key and question)):
        steps_container = st.container()
        with steps_container:
            for step in research_agent.run_research_agent(question, wiki_context or ""):
                stype = step["type"]
                if stype == "thought":
                    with st.expander("Thought", expanded=False):
                        st.markdown(step["content"])
                elif stype == "tool_call":
                    st.info(f"**{step['name']}** — `{step['args']}`")
                elif stype == "tool_result":
                    with st.expander(f"Result: {step['name']}", expanded=False):
                        st.text(step["result"][:800])
                elif stype == "final_answer":
                    st.success("Research complete.")
                    if step.get("report_path"):
                        st.markdown(f"Report saved: `{step['report_path']}`")
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
