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
import lex_index
import md_convert
import metadata_extract
import ollama_client
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
    /* The label lives in a nested <p>, which `.stApp *` would paint dark. */
    .stButton > button[kind="primary"] *,
    .stButton > button[kind="primary"]:hover *,
    [data-testid="stFormSubmitButton"] button[kind="primary"] *,
    [data-testid="stFormSubmitButton"] button[kind="primary"]:hover * {{
        color: #ffffff !important;
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

    /* ── Segmented control (primary navigation) ──
       Streamlit's testid is stButtonGroup, and the selected pill is marked with
       kind="segmented_controlActive" — not aria-checked. */
    [data-testid="stButtonGroup"] button {{
        background-color: {_t['widget_bg']} !important;
        border-color: {_t['border']} !important;
    }}
    [data-testid="stButtonGroup"] button * {{
        color: {_t['text']} !important;
    }}
    [data-testid="stButtonGroup"] button:hover {{
        background-color: {_t['hover']} !important;
    }}
    [data-testid="stButtonGroup"] button[kind="segmented_controlActive"] {{
        background-color: {_t['primary']} !important;
        border-color: {_t['primary']} !important;
    }}
    [data-testid="stButtonGroup"] button[kind="segmented_controlActive"] * {{
        color: #ffffff !important;
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

    /* Streamlit's fixed stHeader is opaque and overlays the top of the main
       column — at 1.5rem the top bar's first line (the DATABASE / OPTIONS
       headings) was painted over and looked missing. Clear the header. */
    .block-container {{ padding-top: 4rem; padding-bottom: 2rem; }}

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
    sources = st.session_state.get("research_sources", [])
    if not sources:
        st.caption("Sources appear here during research.")
        return
    for i, src in enumerate(sources):
        st.markdown(f"**{src['tool']}**")
        st.caption(src["query"])
        if i < len(sources) - 1:
            st.markdown("---")


def _run_research_stream(question_to_run: str, display_q: str, wiki_context: str) -> None:
    st.session_state["research_sources"] = []
    st.session_state["last_research_answer"] = ""
    st.session_state["last_research_error"] = ""
    st.session_state["last_research_q"] = display_q
    st.session_state.pop("research_saved", None)
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
               "last_report", "research_sources"):
        st.session_state.pop(_k, None)
    st.rerun()


# --- top bar: active database + primary navigation ---
# Runs before the page dispatch so `set_active_db` still lands before any page
# handler reads paths.
_bar_db, _bar_nav = st.columns([1, 3])

with _bar_db:
    _bar_label("DATABASE")
    _db_choice = st.selectbox(
        "Database",
        options=_allowed_dbs,
        index=_allowed_dbs.index(st.session_state["active_db"]),
        key="db_selector",
        label_visibility="collapsed",
    )
    _s = wiki_engine.stats()
    st.caption(f"**{_s['pages']}** pages &nbsp;·&nbsp; **{_s['raw_files']}** sources",
               unsafe_allow_html=True)
if _db_choice != st.session_state["active_db"]:
    st.session_state["active_db"] = _db_choice
    db_context.set_active_db(_db_choice)
    # Clear per-DB session state to avoid cross-DB leakage.
    for _k in ("messages", "chat_followup", "research_history",
               "last_research_q", "last_research_answer", "last_report",
               "research_sources", "explorer_selected_page", "last_contradictions",
               "pending_batch", "batch_confirmed", "batch_prepared", "batch_key",
               "convert_editor", "chat_scope"):
        st.session_state.pop(_k, None)
    st.rerun()

with _bar_nav:
    if not _maint_active:
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
            label_visibility="collapsed",
        )


# --- pages ---

if page == "Upload":
    _page_header("Upload a Document", "Markdown, PDF, DOCX, and images — non-Markdown files are auto-converted before ingest.")
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
        if st.button("🆕 New chat", key="new_chat"):
            st.session_state.pop("messages", None)
            st.session_state.pop("chat_followup", None)
            st.rerun()

        mode = st.radio(
            "Mode", ["Fast", "Deep"], horizontal=True, key="chat_mode",
            help="Fast: one-shot retrieval over wiki pages. Deep: agentic loop over data/raw/ originals (~2x slower than Research, but more grounded).",
        )

        st.multiselect(
            "Search in", options=_allowed_dbs, key="chat_scope",
            help="Databases this chat searches. Answers cite cross-database results "
                 "as `Database::file.md`. Uploads and 'Save answer to wiki' still go "
                 "to the active database in the sidebar.",
        )
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
            st.session_state["messages"].append(
                {"role": "assistant", "content": answer or "(no answer)", "question": prompt,
                 "sources": wiki_pages, "raw_sources": raw_sources, "steps": steps,
                 "interpreted": interpreted}
            )
        st.rerun()


elif page == "Research":
    _page_header("Research Agent")
    st.caption(
        "Research mode includes web search — the agent starts at the local wiki, "
        "then searches the web and fetches pages to fill the gaps."
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
        if st.button("🆕 New research", key="new_research"):
            for _k in ("research_history", "last_research_q", "last_research_answer",
                       "last_research_interpreted", "last_report", "research_sources",
                       "last_research_error", "research_followup_input", "research_saved"):
                st.session_state.pop(_k, None)
            st.rerun()

        question = st.text_input("Research question", placeholder="e.g. What are the latest advances in RAG?")

        with st.expander("Extra wiki paste (optional — the agent browses the wiki on its own)"):
            wiki_context = st.text_area(
                "Optional extra context. Leave blank — the agent will run wiki_search first automatically.",
                height=120,
                label_visibility="collapsed",
            )

        if st.button("Start research", key="start_research_btn", use_container_width=True, disabled=not (tavily_key and question)):
            _run_research_stream(question, question, wiki_context or "")
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
                _run_research_stream(standalone, fq, "")
                st.rerun()


elif page == "Maintenance":
    _page_header("Maintenance")
    s = wiki_engine.stats()
    c1, c2, c3 = st.columns(3)
    c1.metric("Wiki pages", s["pages"])
    c2.metric("Raw sources", s["raw_files"])
    c3.metric("Data size (MB)", round(s["data_bytes"] / 1_048_576, 2))

    _tab_labels = ["Search index", "Delete source", "Link graph health", "Lint",
                   "Activity log", "Reset all data"]
    if auth.is_admin(_user):
        _tab_labels.append("Admin")
    _tabs = st.tabs(_tab_labels)
    tab_index, tab_del, tab_graph, tab_lint, tab_log, tab_reset = _tabs[:6]

    with tab_index:
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
