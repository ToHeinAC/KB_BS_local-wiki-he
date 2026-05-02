"""LocalWiki — Streamlit UI."""

import subprocess
import tempfile
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

load_dotenv()

import dedup
import file_processor
import ollama_client
import wiki_engine

APP_PORT = 8520

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
    hr { border-top: 2px solid #111; margin: 1.5rem 0; }
    </style>
    """,
    unsafe_allow_html=True,
)


# --- sidebar ---

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
if st.sidebar.button("Exit app", type="secondary"):
    subprocess.Popen(f"lsof -ti:{APP_PORT} | xargs -r kill -9", shell=True)
    st.sidebar.info("Shutting down…")


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
            if st.button("Ingest into wiki", type="primary"):
                with st.spinner("Saving file…"):
                    saved = dedup.register_file(raw, uploaded.name)
                with st.spinner("Extracting text…"):
                    text = file_processor.extract_text(saved)
                with st.spinner("Running LLM ingest (this may take a minute)…"):
                    try:
                        result = wiki_engine.ingest(text, uploaded.name)
                        st.success("Ingest complete.")
                        col1, col2, col3 = st.columns(3)
                        col1.metric("Created", len(result["created"]))
                        col2.metric("Updated", len(result["updated"]))
                        col3.metric("Contradictions", len(result["contradictions"]))
                        if result["created"]:
                            st.markdown("**New pages:** " + ", ".join(f"`{f}`" for f in result["created"]))
                        if result["contradictions"]:
                            st.warning("Contradictions found:\n" + "\n".join(f"- {c}" for c in result["contradictions"]))
                    except RuntimeError as e:
                        st.error(str(e))


elif page == "Wiki Explorer":
    st.title("Wiki Explorer")
    pages = wiki_engine.list_pages()
    if not pages:
        st.info("No wiki pages yet. Upload a document to get started.")
    else:
        search = st.text_input("Search pages", placeholder="Filter by title or keyword…")
        filtered = [p for p in pages if not search or search.lower() in str(p).lower()]
        st.markdown(f"**{len(filtered)}** pages")

        selected_file = st.session_state.get("selected_page")
        cols_header = st.columns([4, 1, 1, 1])
        cols_header[0].markdown("**Title**")
        cols_header[1].markdown("**Type**")
        cols_header[2].markdown("**Confidence**")
        cols_header[3].markdown("**Updated**")
        st.markdown("---")

        for p in filtered:
            cols = st.columns([4, 1, 1, 1])
            title = p.get("title", p["filename"])
            if cols[0].button(title, key=f"page_{p['filename']}", use_container_width=True):
                st.session_state["selected_page"] = p["filename"]
                selected_file = p["filename"]
            cols[1].markdown(f"`{p.get('type', '—')}`")
            cols[2].markdown(p.get("confidence", "—"))
            cols[3].markdown(p.get("updated", "—"))

        if selected_file:
            st.markdown("---")
            st.markdown(f"### {selected_file}")
            st.markdown(wiki_engine.read_page(selected_file))


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
                    answer = wiki_engine.query(prompt)
                except RuntimeError as e:
                    answer = f"Error: {e}"
            st.markdown(answer)
        st.session_state["messages"].append({"role": "assistant", "content": answer})


elif page == "Research":
    st.title("Research Agent")
    st.info(
        "The ReAct web-research agent is coming in the next iteration. "
        "It will run Tavily web searches and compile findings into new wiki pages."
    )


elif page == "Maintenance":
    st.title("Maintenance")
    s = wiki_engine.stats()
    c1, c2, c3 = st.columns(3)
    c1.metric("Wiki pages", s["pages"])
    c2.metric("Raw sources", s["raw_files"])
    c3.metric("Log size (bytes)", s["log_bytes"])

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
