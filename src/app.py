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
import gpu_widget
import md_convert
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

if "theme" not in st.session_state:
    st.session_state["theme"] = "Forest"

_THEMES = {
    "Forest": {
        "bg": "#f6f7f2",
        "sidebar_bg": "#eaf0ec",
        "widget_bg": "#ffffff",
        "text": "#1a1f1c",
        "text_muted": "#5a6b5e",
        "primary": "#234637",
        "border": "#d4dbd6",
        "hover": "rgba(35,70,55,0.10)",
        "metric_bg": "#ffffff",
    },
    "Slate": {
        "bg": "#0f1117",
        "sidebar_bg": "#1a1d27",
        "widget_bg": "#262b3a",
        "text": "#e8ecf0",
        "text_muted": "#8892a4",
        "primary": "#4f9cf9",
        "border": "#2e3347",
        "hover": "rgba(79,156,249,0.12)",
        "metric_bg": "#1e2233",
    },
}

_t = _THEMES.get(st.session_state.get("theme", "Forest"))

st.markdown(
    f"""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&family=Libre+Baskerville:ital,wght@0,400;0,700;1,400&display=swap');

    /* ── Global text & font ── */
    html, body {{
        font-family: 'Inter', system-ui, sans-serif;
        font-size: 15px;
    }}
    /* Catch ALL elements' color — overrides Streamlit's inline textColor from config.toml.
       Do NOT set font-family here: it breaks Material icon ligatures. */
    .stApp, .stApp * {{
        color: {_t['text']} !important;
    }}
    /* Re-assert the Material icon font so ligatures render as glyphs, not text */
    [data-testid="stIconMaterial"],
    span.material-icons,
    span.material-icons-outlined,
    .material-symbols-rounded,
    .material-symbols-outlined,
    [class*="material-symbols"] {{
        font-family: 'Material Symbols Rounded', 'Material Icons' !important;
    }}

    /* ── Backgrounds ── */
    .stApp {{
        background-color: {_t['bg']} !important;
    }}
    [data-testid="stSidebar"] {{
        background-color: {_t['sidebar_bg']} !important;
    }}
    /* Main content area & block containers */
    [data-testid="block-container"],
    [data-testid="stVerticalBlock"],
    section.main > div {{
        background-color: {_t['bg']} !important;
    }}

    /* ── Headings ── */
    h1, h2, h3 {{
        font-family: 'Libre Baskerville', Georgia, serif !important;
        font-weight: 700;
    }}
    h1 {{ font-size: 1.75rem; margin-bottom: 0.25rem; }}
    [data-testid="stSidebar"] h2 {{ white-space: nowrap; font-size: 1.25rem; }}

    /* ── Input widgets ── */
    .stTextInput > div > div > input,
    .stTextArea > div > div > textarea {{
        background-color: {_t['widget_bg']} !important;
        color: {_t['text']} !important;
        border-color: {_t['border']} !important;
        border-radius: 6px !important;
    }}
    .stTextInput > div > div > input::placeholder,
    .stTextArea > div > div > textarea::placeholder {{
        color: {_t['text_muted']} !important;
        opacity: 1 !important;
    }}
    /* Selectbox */
    .stSelectbox > div > div,
    .stSelectbox > div > div > div {{
        background-color: {_t['widget_bg']} !important;
        color: {_t['text']} !important;
        border-color: {_t['border']} !important;
        border-radius: 6px !important;
    }}

    /* ── Buttons ── */
    .stButton > button {{
        border-radius: 6px !important;
        font-weight: 500 !important;
        text-transform: none !important;
        font-size: 0.875rem !important;
        border: 1px solid {_t['border']} !important;
        background-color: {_t['widget_bg']} !important;
        color: {_t['text']} !important;
        transition: background-color 0.15s ease, box-shadow 0.15s ease !important;
    }}
    .stButton > button:hover {{
        background-color: {_t['hover']} !important;
        box-shadow: 0 1px 4px rgba(0,0,0,0.15) !important;
    }}
    .stButton > button[kind="primary"],
    .stButton > button[kind="primary"]:hover {{
        background-color: {_t['primary']} !important;
        color: #ffffff !important;
        border-color: {_t['primary']} !important;
    }}
    /* Form submit buttons (not caught by .stButton) */
    [data-testid="stFormSubmitButton"] button {{
        border-radius: 6px !important;
        font-weight: 500 !important;
        border: 1px solid {_t['border']} !important;
        background-color: {_t['widget_bg']} !important;
        color: {_t['text']} !important;
    }}
    [data-testid="stFormSubmitButton"] button[kind="primary"],
    [data-testid="stFormSubmitButton"] button[kind="primary"]:hover {{
        background-color: {_t['primary']} !important;
        color: #ffffff !important;
        border-color: {_t['primary']} !important;
    }}
    /* Download buttons */
    .stDownloadButton > button {{
        background-color: {_t['widget_bg']} !important;
        color: {_t['text']} !important;
        border: 1px solid {_t['border']} !important;
        border-radius: 6px !important;
    }}

    /* ── File uploader (dropzone uses config secondaryBackgroundColor — force theme) ── */
    [data-testid="stFileUploaderDropzone"],
    [data-testid="stFileUploader"] section {{
        background-color: {_t['widget_bg']} !important;
        border: 1px solid {_t['border']} !important;
    }}
    [data-testid="stFileUploaderDropzoneInstructions"],
    [data-testid="stFileUploaderDropzoneInstructions"] * {{
        color: {_t['text_muted']} !important;
    }}
    [data-testid="stFileUploader"] button {{
        background-color: {_t['bg']} !important;
        color: {_t['text']} !important;
        border: 1px solid {_t['border']} !important;
    }}

    /* ── Sidebar buttons (nav style) ── */
    [data-testid="stSidebar"] .stButton > button {{
        background: transparent !important;
        border: none !important;
        text-align: left !important;
        padding: 0.3rem 0.5rem !important;
        border-radius: 4px !important;
        width: 100% !important;
        color: {_t['text']} !important;
    }}
    [data-testid="stSidebar"] .stButton > button:hover,
    [data-testid="stSidebar"] .stButton > button:focus,
    [data-testid="stSidebar"] .stButton > button:active {{
        background: {_t['hover']} !important;
        color: {_t['text']} !important;
        box-shadow: none !important;
    }}
    /* Reset & Logout: identical boxed buttons (override transparent nav style) */
    [data-testid="stSidebar"] .st-key-reset_btn button,
    [data-testid="stSidebar"] .st-key-logout_btn button {{
        background-color: {_t['widget_bg']} !important;
        border: 1px solid {_t['border']} !important;
        text-align: center !important;
        padding: 0.35rem 0.75rem !important;
        border-radius: 6px !important;
    }}
    [data-testid="stSidebar"] .st-key-reset_btn button:hover,
    [data-testid="stSidebar"] .st-key-logout_btn button:hover {{
        background-color: {_t['hover']} !important;
        border-color: {_t['primary']} !important;
    }}
    /* Lint, Delete source, Start research: same boxed style as Reset/Logout */
    .st-key-run_lint_btn button,
    .st-key-delete_source_btn button,
    .st-key-start_research_btn button {{
        background-color: {_t['widget_bg']} !important;
        border: 1px solid {_t['border']} !important;
        text-align: center !important;
        padding: 0.35rem 0.75rem !important;
        border-radius: 6px !important;
        color: {_t['text']} !important;
    }}
    .st-key-run_lint_btn button:hover,
    .st-key-delete_source_btn button:hover,
    .st-key-start_research_btn button:hover {{
        background-color: {_t['hover']} !important;
        border-color: {_t['primary']} !important;
    }}

    /* ── Radio / Checkbox / Toggle ── */
    .stRadio > div, .stCheckbox > label, .stRadio label {{
        color: {_t['text']} !important;
    }}

    /* ── Tabs ── */
    [data-testid="stTabs"] button,
    [data-testid="stTabs"] button p {{
        color: {_t['text']} !important;
    }}
    [data-testid="stTabs"] [data-baseweb="tab-list"] {{
        background-color: {_t['bg']} !important;
    }}

    /* ── Expanders (use page bg so widget-bg buttons inside stand out as boxes) ── */
    [data-testid="stExpander"] {{
        border: 1px solid {_t['border']} !important;
        background-color: {_t['bg']} !important;
        border-radius: 6px !important;
    }}
    [data-testid="stExpander"] summary,
    [data-testid="stExpander"] summary p,
    [data-testid="stExpander"] summary span {{
        color: {_t['text']} !important;
    }}
    /* Nav/list buttons inside expanders: lighter than the expander, clear border */
    [data-testid="stExpander"] .stButton > button {{
        background-color: {_t['widget_bg']} !important;
        color: {_t['text']} !important;
        border: 1px solid {_t['border']} !important;
        margin-bottom: 0.25rem !important;
    }}
    [data-testid="stExpander"] .stButton > button:hover {{
        background-color: {_t['hover']} !important;
        border-color: {_t['primary']} !important;
    }}

    /* ── Chat messages ── */
    [data-testid="stChatMessage"],
    [data-testid="stChatMessage"] * {{
        background-color: {_t['widget_bg']} !important;
        color: {_t['text']} !important;
    }}

    /* ── Alert / info / warning / error boxes ── */
    [data-testid="stAlert"],
    [data-testid="stAlert"] * {{
        color: {_t['text']} !important;
    }}

    /* ── Metric cards ── */
    [data-testid="stMetric"] {{
        background: {_t['metric_bg']} !important;
        border: 1px solid {_t['border']};
        border-radius: 8px;
        padding: 0.75rem 1rem;
    }}
    [data-testid="stMetricValue"],
    [data-testid="stMetricLabel"] {{
        color: {_t['text']} !important;
    }}

    /* ── Dividers ── */
    hr {{ border: none; border-top: 1px solid {_t['border']}; margin: 1.25rem 0; }}

    /* ── Container borders (st.container(border=True)) ── */
    [data-testid="stVerticalBlockBorderWrapper"] > div {{
        border-color: {_t['border']} !important;
        background-color: {_t['widget_bg']} !important;
    }}

    /* ── Spinner ── */
    .stSpinner > div {{
        border-top-color: {_t['primary']} !important;
    }}

    .block-container {{ padding-top: 1.5rem; padding-bottom: 2rem; }}

    /* Multiselect selected-item tags: orange */
    [data-baseweb="tag"] {{
        background-color: #e07b20 !important;
    }}
    [data-baseweb="tag"] span {{
        color: #ffffff !important;
    }}
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
    st.download_button(
        "Download",
        data=content,
        file_name=title,
        mime="text/markdown",
        key=f"dl_src_{title}",
    )


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
    st.session_state["last_research_answer"] = ""
    st.session_state["last_research_error"] = ""
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
            elif stype == "error":
                st.error(step["content"])
                st.session_state["last_research_error"] = step["content"]


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

st.sidebar.caption("DATABASE")
_db_choice = st.sidebar.selectbox(
    "Database",
    options=_allowed_dbs,
    index=_allowed_dbs.index(st.session_state["active_db"]),
    key="db_selector",
    label_visibility="collapsed",
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

st.sidebar.caption("NAVIGATION")
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
st.sidebar.caption(f"Signed in as **{_user}**")
_rst_col, _logout_col = st.sidebar.columns(2)
if _rst_col.button("Reset", key="reset_btn", help="Unload model from VRAM and reset session. Server stays running."):
    _safe_reset()
if _logout_col.button("Logout", key="logout_btn"):
    for _k in ("user", "active_db", "messages", "chat_followup",
               "research_history", "last_research_q", "last_research_answer",
               "last_report", "research_sources"):
        st.session_state.pop(_k, None)
    st.rerun()


# --- pages ---

if page == "Upload":
    _page_header("Upload a Document", "Markdown, PDF, DOCX, and images — non-Markdown files are auto-converted before ingest.")
    if not _can_maintain:
        st.error("You are not a maintainer of this database. Ask an admin for maintainer rights.")
        st.stop()
    uploaded = st.file_uploader(
        "Choose file",
        type=["md", "pdf", "docx", "png", "jpg", "jpeg", "tiff", "tif", "bmp"],
        label_visibility="collapsed",
    )
    if uploaded:
        raw = uploaded.read()
        if dedup.is_duplicate(raw):
            st.warning(f"**{uploaded.name}** has already been ingested (duplicate detected).")
        else:
            st.info(f"New file: **{uploaded.name}** ({len(raw):,} bytes)")
            convertible = md_convert.is_convertible(uploaded.name)
            converted_md = None
            if convertible:
                key = dedup.sha256(raw)
                if st.session_state.get("convert_key") != key:
                    if not ollama_client.is_available():
                        st.error(
                            "Ollama is not reachable. Start it and run "
                            "`ollama pull deepseek-ocr:3b` to convert non-Markdown files."
                        )
                        st.stop()
                    prog = st.progress(0.0, text="Converting to Markdown…")

                    def _cb(done: int, total: int, label: str) -> None:
                        prog.progress(min(done / total, 1.0) if total else 1.0, text=label)

                    try:
                        md_text = md_convert.convert_to_markdown(raw, uploaded.name, _cb)
                    except (RuntimeError, ValueError) as e:
                        st.error(f"Conversion failed: {e}")
                        st.stop()
                    st.session_state["convert_key"] = key
                    st.session_state["convert_md"] = md_text
                st.markdown("**Converted Markdown** — review and edit before ingest.")
                converted_md = st.text_area(
                    "Converted Markdown",
                    value=st.session_state.get("convert_md", ""),
                    height=300,
                    label_visibility="collapsed",
                    key="convert_editor",
                )
            st.markdown("**Optional metadata** — fill in to make the ingest more reliable.")
            fields = template_loader.load_insert_template()
            with st.form("ingest_form"):
                values = {f: st.text_input(f.capitalize()) for f in fields}
                submitted = st.form_submit_button("Ingest into wiki", type="primary")
            if submitted:
                user_meta = {k: v.strip() for k, v in values.items() if v and v.strip()}
                if convertible:
                    md_name = Path(uploaded.name).stem + ".md"
                    with st.spinner("Saving file…"):
                        saved = dedup.register_file(raw, md_name, content=converted_md.encode())
                    text = converted_md
                else:
                    with st.spinner("Saving file…"):
                        saved = dedup.register_file(raw, uploaded.name)
                    with st.spinner("Extracting text…"):
                        text = file_processor.extract_text(saved)
                source_name = saved.name
                chunks = file_processor.chunk_text(text)
                n = len(chunks)
                try:
                    if n > 1:
                        st.info(f"Dokument aufgeteilt in {n} Teile — jeder Teil wird separat verarbeitet.")
                        progress = st.progress(0)
                    with st.spinner("Indexing document (chunker, lexical index, sidecars)…"):
                        ctx = wiki_engine.ingest_begin(text, source_name, user_meta or None)
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
    _page_header("Wiki Explorer")
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
    _page_header("Wiki Chat", "Fast mode reads wiki pages; Deep mode reasons over original documents.")

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
                    elif stype == "error" and not answer:
                        answer = f"Error: {step['content']}"
            st.session_state["messages"].append(
                {"role": "assistant", "content": answer or "(no answer)", "question": prompt,
                 "sources": [], "raw_sources": raw_sources, "steps": steps, "interpreted": interpreted}
            )
        st.rerun()


elif page == "Research":
    _page_header("Research Agent")
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
                       "last_research_error", "research_followup_input"):
                st.session_state.pop(_k, None)
            st.rerun()

        _q_col, _chk_col = st.columns([4, 2])
        question = _q_col.text_input("Research question", placeholder="e.g. What are the latest advances in RAG?")
        auto_save = _chk_col.checkbox("Auto-save to wiki", value=True)

        with st.expander("Extra wiki paste (optional — the agent browses the wiki on its own)"):
            wiki_context = st.text_area(
                "Optional extra context. Leave blank — the agent will run wiki_search first automatically.",
                height=120,
                label_visibility="collapsed",
            )

        if st.button("Start research", key="start_research_btn", use_container_width=True, disabled=not (tavily_key and question)):
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
        elif st.session_state.get("last_research_error"):
            st.markdown("---")
            st.error(st.session_state["last_research_error"])
            st.caption("The live trace above is cleared on refresh — the line above is why the run produced no answer.")

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
    _page_header("Maintenance")
    s = wiki_engine.stats()
    c1, c2, c3 = st.columns(3)
    c1.metric("Wiki pages", s["pages"])
    c2.metric("Raw sources", s["raw_files"])
    c3.metric("Data size (MB)", round(s["data_bytes"] / 1_048_576, 2))

    _tab_labels = ["Delete source", "Link graph health", "Lint", "Activity log", "Reset all data"]
    if auth.is_admin(_user):
        _tab_labels.append("Admin")
    _tabs = st.tabs(_tab_labels)
    tab_del, tab_graph, tab_lint, tab_log, tab_reset = _tabs[:5]

    with tab_graph:
        orphans = wiki_engine.find_orphans()
        if orphans:
            st.warning(f"**{len(orphans)} orphan(s)** — pages with no `related` in-links.")
            st.code("\n".join(orphans), language=None)
        else:
            st.success("No orphans — every page is linked from at least one other page.")

    with tab_lint:
        st.caption("Ask the LLM to review wiki quality: contradictions, orphans, gaps, suggestions.")
        if st.button("Run lint", key="run_lint_btn"):
            with st.spinner("Running lint (may take a minute)…"):
                try:
                    report = wiki_engine.lint()
                    st.markdown(report)
                except RuntimeError as e:
                    st.error(str(e))

    with tab_del:
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

    with tab_reset:
        if _can_maintain:
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
            st.info("Reset actions require maintainer rights for this database.")

    with tab_log:
        st.code(wiki_engine.read_log(), language=None)

    if auth.is_admin(_user):
        with _tabs[5]:
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
