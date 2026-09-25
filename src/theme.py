"""Frontend skins.

The app ships two visual frontends, chosen once per process by `FRONTEND` in
`.env`:

* `default`  — the New York Times-ish editorial palette (Forest / Slate) the app
  has always had. Unchanged.
* `newspaper` — a broadsheet skin: paper stock, Bodoni masthead, Garamond prose,
  mono figures, hairline rules, square corners.

Both are driven from the *same* token-parametric base CSS, so a Streamlit quirk
fixed for one is fixed for both. The newspaper skin then adds an override block
for the things a palette cannot express (masthead, rules, mono labels) and a
`masthead()` chrome function that `app.py` renders in place of the plain top bar.

The tokens keep the key names the default skin already used (`bg`, `primary`,
`border`, …) because `app.py` and `gpu_widget.render_gpu_sidebar(accent=…)` read
them by name.
"""

from __future__ import annotations

import datetime as _dt
import os
from typing import Any

import streamlit as st

FRONTEND = os.getenv("FRONTEND", "default").strip().lower()

_GOOGLE_FONTS = {
    "default": (
        "https://fonts.googleapis.com/css2?"
        "family=Inter:wght@400;500;600&"
        "family=Libre+Baskerville:ital,wght@0,400;0,700;1,400&display=swap"
    ),
    "newspaper": (
        "https://fonts.googleapis.com/css2?"
        "family=Bodoni+Moda:ital,opsz,wght@0,6..96,400;0,6..96,700;0,6..96,900;1,6..96,400&"
        "family=EB+Garamond:ital,wght@0,400;0,500;0,600;1,400&"
        "family=IBM+Plex+Mono:wght@400;500;600&display=swap"
    ),
}

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
        "font_body": "'Inter', system-ui, sans-serif",
        "font_head": "'Libre Baskerville', Georgia, serif",
        "font_mono": "ui-monospace, SFMono-Regular, monospace",
        "radius": "6px",
        "base_size": "15px",
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
        "font_body": "'Inter', system-ui, sans-serif",
        "font_head": "'Libre Baskerville', Georgia, serif",
        "font_mono": "ui-monospace, SFMono-Regular, monospace",
        "radius": "6px",
        "base_size": "15px",
    },
    # Broadsheet. `primary` is the rust accent (primary buttons, GPU widget);
    # the *ink* black is a separate token because the active nav pill and the
    # rules are ink, not accent.
    "Newspaper": {
        "bg": "#f4f1e6",
        "sidebar_bg": "#efeada",
        "widget_bg": "#faf8f0",
        "text": "#1c1a15",
        "text_muted": "#6b6355",
        "primary": "#7a3b2a",
        "border": "#b9b1a0",
        "hover": "rgba(122,59,42,0.10)",
        "metric_bg": "#efeada",
        "font_body": "'EB Garamond', Georgia, serif",
        "font_head": "'Bodoni Moda', 'Libre Baskerville', serif",
        "font_mono": "'IBM Plex Mono', ui-monospace, monospace",
        "radius": "0px",
        "base_size": "16px",
        "ink": "#1c1a15",
        "ink_soft": "#4a4438",
        "rule": "#b9b1a0",
        "dotted": "#c6bfae",
    },
}


def is_newspaper() -> bool:
    return FRONTEND == "newspaper"


def theme_name() -> str:
    """The palette this run uses. The Slate/Forest switch stays session state."""
    if is_newspaper():
        return "Newspaper"
    return st.session_state.get("theme", "Forest")


def tokens() -> dict[str, Any]:
    return _THEMES[theme_name()]


# ── CSS ──────────────────────────────────────────────────────────────────────


def _base_css(t: dict[str, Any]) -> str:
    """Token-parametric chrome. Shared by every skin."""
    return f"""
    @import url('{_GOOGLE_FONTS["newspaper" if is_newspaper() else "default"]}');

    /* ── Global text & font ── */
    html, body {{
        font-family: {t["font_body"]};
        font-size: {t["base_size"]};
    }}
    /* Catch ALL elements' color — overrides Streamlit's inline textColor from config.toml.
       Do NOT set font-family here: it breaks Material icon ligatures. */
    .stApp, .stApp * {{
        color: {t["text"]} !important;
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
        background-color: {t["bg"]} !important;
    }}
    /* Narrower than Streamlit's ~21rem default: nothing in here needs the
       width, and the main column gets it instead. 280px is about the floor —
       the GPU line (gpu_widget.py, 13px monospace, nowrap) is ~225px wide and
       clips below roughly 260px. */
    [data-testid="stSidebar"] {{
        background-color: {t["sidebar_bg"]} !important;
        width: 280px !important;
        min-width: 280px !important;
    }}
    /* Main content area & block containers */
    [data-testid="block-container"],
    [data-testid="stVerticalBlock"],
    section.main > div {{
        background-color: {t["bg"]} !important;
    }}

    /* ── Headings ── */
    h1, h2, h3 {{
        font-family: {t["font_head"]} !important;
        font-weight: 700;
    }}
    h1 {{ font-size: 1.75rem; margin-bottom: 0.25rem; }}
    [data-testid="stSidebar"] h2 {{ white-space: nowrap; font-size: 1.25rem; }}

    /* ── Input widgets ── */
    .stTextInput > div > div > input,
    .stTextArea > div > div > textarea {{
        background-color: {t["widget_bg"]} !important;
        color: {t["text"]} !important;
        border-color: {t["border"]} !important;
        border-radius: {t["radius"]} !important;
    }}
    .stTextInput > div > div > input::placeholder,
    .stTextArea > div > div > textarea::placeholder {{
        color: {t["text_muted"]} !important;
        opacity: 1 !important;
    }}
    /* Selectbox */
    .stSelectbox > div > div,
    .stSelectbox > div > div > div {{
        background-color: {t["widget_bg"]} !important;
        color: {t["text"]} !important;
        border-color: {t["border"]} !important;
        border-radius: {t["radius"]} !important;
    }}

    /* ── Buttons ── */
    .stButton > button {{
        border-radius: {t["radius"]} !important;
        font-weight: 500 !important;
        text-transform: none !important;
        font-size: 0.875rem !important;
        border: 1px solid {t["border"]} !important;
        background-color: {t["widget_bg"]} !important;
        color: {t["text"]} !important;
        transition: background-color 0.15s ease, box-shadow 0.15s ease !important;
    }}
    .stButton > button:hover {{
        background-color: {t["hover"]} !important;
        box-shadow: 0 1px 4px rgba(0,0,0,0.15) !important;
    }}
    .stButton > button[kind="primary"],
    .stButton > button[kind="primary"]:hover {{
        background-color: {t["primary"]} !important;
        color: #ffffff !important;
        border-color: {t["primary"]} !important;
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
        border-radius: {t["radius"]} !important;
        font-weight: 500 !important;
        border: 1px solid {t["border"]} !important;
        background-color: {t["widget_bg"]} !important;
        color: {t["text"]} !important;
    }}
    [data-testid="stFormSubmitButton"] button[kind="primary"],
    [data-testid="stFormSubmitButton"] button[kind="primary"]:hover {{
        background-color: {t["primary"]} !important;
        color: #ffffff !important;
        border-color: {t["primary"]} !important;
    }}
    /* Download buttons */
    .stDownloadButton > button {{
        background-color: {t["widget_bg"]} !important;
        color: {t["text"]} !important;
        border: 1px solid {t["border"]} !important;
        border-radius: {t["radius"]} !important;
    }}

    /* ── File uploader (dropzone uses config secondaryBackgroundColor — force theme) ── */
    [data-testid="stFileUploaderDropzone"],
    [data-testid="stFileUploader"] section {{
        background-color: {t["widget_bg"]} !important;
        border: 1px solid {t["border"]} !important;
    }}
    [data-testid="stFileUploaderDropzoneInstructions"],
    [data-testid="stFileUploaderDropzoneInstructions"] * {{
        color: {t["text_muted"]} !important;
    }}
    [data-testid="stFileUploader"] button {{
        background-color: {t["bg"]} !important;
        color: {t["text"]} !important;
        border: 1px solid {t["border"]} !important;
    }}

    /* ── Sidebar buttons (nav style) ── */
    [data-testid="stSidebar"] .stButton > button {{
        background: transparent !important;
        border: none !important;
        text-align: left !important;
        padding: 0.3rem 0.5rem !important;
        border-radius: 4px !important;
        width: 100% !important;
        color: {t["text"]} !important;
    }}
    [data-testid="stSidebar"] .stButton > button:hover,
    [data-testid="stSidebar"] .stButton > button:focus,
    [data-testid="stSidebar"] .stButton > button:active {{
        background: {t["hover"]} !important;
        color: {t["text"]} !important;
        box-shadow: none !important;
    }}
    /* Reset & Logout: identical boxed buttons (override transparent nav style) */
    [data-testid="stSidebar"] .st-key-reset_btn button,
    [data-testid="stSidebar"] .st-key-logout_btn button {{
        background-color: {t["widget_bg"]} !important;
        border: 1px solid {t["border"]} !important;
        text-align: center !important;
        padding: 0.35rem 0.75rem !important;
        border-radius: {t["radius"]} !important;
    }}
    [data-testid="stSidebar"] .st-key-reset_btn button:hover,
    [data-testid="stSidebar"] .st-key-logout_btn button:hover {{
        background-color: {t["hover"]} !important;
        border-color: {t["primary"]} !important;
    }}
    /* Lint, Delete source, Start research: same boxed style as Reset/Logout */
    .st-key-run_lint_btn button,
    .st-key-delete_source_btn button,
    .st-key-start_research_btn button {{
        background-color: {t["widget_bg"]} !important;
        border: 1px solid {t["border"]} !important;
        text-align: center !important;
        padding: 0.35rem 0.75rem !important;
        border-radius: {t["radius"]} !important;
        color: {t["text"]} !important;
    }}
    .st-key-run_lint_btn button:hover,
    .st-key-delete_source_btn button:hover,
    .st-key-start_research_btn button:hover {{
        background-color: {t["hover"]} !important;
        border-color: {t["primary"]} !important;
    }}
    /* Collapsed explorer rail: its column is only a hair wider than the button,
       so pin the button to the right edge rather than leaving the slack sitting
       between it and the edge of the page. */
    .st-key-explorer_panel_expand {{
        display: flex !important;
        justify-content: flex-end !important;
    }}
    .st-key-explorer_panel_expand button {{
        min-width: 0 !important;
    }}

    /* ── Radio / Checkbox / Toggle ── */
    .stRadio > div, .stCheckbox > label, .stRadio label {{
        color: {t["text"]} !important;
    }}

    /* ── Tabs ── */
    [data-testid="stTabs"] button,
    [data-testid="stTabs"] button p {{
        color: {t["text"]} !important;
    }}
    [data-testid="stTabs"] [data-baseweb="tab-list"] {{
        background-color: {t["bg"]} !important;
    }}

    /* ── Segmented control (primary navigation) ──
       Streamlit's testid is stButtonGroup, and the selected pill is marked with
       kind="segmented_controlActive" — not aria-checked. */
    [data-testid="stButtonGroup"] button {{
        background-color: {t["widget_bg"]} !important;
        border-color: {t["border"]} !important;
    }}
    [data-testid="stButtonGroup"] button * {{
        color: {t["text"]} !important;
    }}
    [data-testid="stButtonGroup"] button:hover {{
        background-color: {t["hover"]} !important;
    }}
    [data-testid="stButtonGroup"] button[kind="segmented_controlActive"] {{
        background-color: {t["primary"]} !important;
        border-color: {t["primary"]} !important;
    }}
    [data-testid="stButtonGroup"] button[kind="segmented_controlActive"] * {{
        color: #ffffff !important;
    }}
    /* Full-width segmented controls: each option takes an equal share of the
       row. Scoped by widget key — the inline ones (chat Fast|Deep, Explorer
       Graph|Tree) must keep their content width. */
    .st-key-wiki_view [data-testid="stButtonGroup"],
    .st-key-maint_view [data-testid="stButtonGroup"],
    .st-key-explorer_view [data-testid="stButtonGroup"],
    .st-key-graph_layout [data-testid="stButtonGroup"] {{
        display: flex !important;
        width: 100% !important;
    }}
    .st-key-wiki_view [data-testid="stButtonGroup"] button,
    .st-key-maint_view [data-testid="stButtonGroup"] button,
    .st-key-explorer_view [data-testid="stButtonGroup"] button,
    .st-key-graph_layout [data-testid="stButtonGroup"] button {{
        flex: 1 1 0 !important;
        padding: 0.6rem 0.5rem !important;
    }}
    /* `Advanced` is a disclosure for refinements, not a section head — it should
       sit below the controls it hides in the type hierarchy. Class-scoped, so it
       also outranks the newspaper skin's blanket expander-summary rule. */
    .st-key-graph_advanced [data-testid="stExpander"] summary,
    .st-key-graph_advanced [data-testid="stExpander"] summary *,
    .st-key-chat_advanced [data-testid="stExpander"] summary,
    .st-key-chat_advanced [data-testid="stExpander"] summary * {{
        font-size: 0.78rem !important;
    }}
    /* Only the two page-level navs are set larger than a widget label; the
       graph Layout switch is a control inside a page, not a page header. */
    .st-key-wiki_view [data-testid="stButtonGroup"] button *,
    .st-key-maint_view [data-testid="stButtonGroup"] button * {{
        font-size: 1.02rem !important;
        font-weight: 600 !important;
    }}

    /* ── Expanders (use page bg so widget-bg buttons inside stand out as boxes) ── */
    [data-testid="stExpander"] {{
        border: 1px solid {t["border"]} !important;
        background-color: {t["bg"]} !important;
        border-radius: {t["radius"]} !important;
    }}
    [data-testid="stExpander"] summary,
    [data-testid="stExpander"] summary p,
    [data-testid="stExpander"] summary span {{
        color: {t["text"]} !important;
    }}
    /* Nav/list buttons inside expanders: lighter than the expander, clear border */
    [data-testid="stExpander"] .stButton > button {{
        background-color: {t["widget_bg"]} !important;
        color: {t["text"]} !important;
        border: 1px solid {t["border"]} !important;
        margin-bottom: 0.25rem !important;
    }}
    [data-testid="stExpander"] .stButton > button:hover {{
        background-color: {t["hover"]} !important;
        border-color: {t["primary"]} !important;
    }}

    /* ── Chat messages ── */
    [data-testid="stChatMessage"],
    [data-testid="stChatMessage"] * {{
        background-color: {t["widget_bg"]} !important;
        color: {t["text"]} !important;
    }}

    /* ── Alert / info / warning / error boxes ── */
    [data-testid="stAlert"],
    [data-testid="stAlert"] * {{
        color: {t["text"]} !important;
    }}

    /* ── Metric cards ── */
    [data-testid="stMetric"] {{
        background: {t["metric_bg"]} !important;
        border: 1px solid {t["border"]};
        border-radius: {t["radius"]};
        padding: 0.75rem 1rem;
    }}
    [data-testid="stMetricValue"],
    [data-testid="stMetricLabel"] {{
        color: {t["text"]} !important;
    }}

    /* ── Dividers ── */
    hr {{ border: none; border-top: 1px solid {t["border"]}; margin: 1.25rem 0; }}

    /* ── Container borders (st.container(border=True)) ── */
    [data-testid="stVerticalBlockBorderWrapper"] > div {{
        border-color: {t["border"]} !important;
        background-color: {t["widget_bg"]} !important;
    }}

    /* ── Spinner ── */
    .stSpinner > div {{
        border-top-color: {t["primary"]} !important;
    }}

    /* Streamlit's fixed stHeader is opaque and overlays the top of the main
       column — at 1.5rem the top bar's first line (the DATABASE / OPTIONS
       headings) was painted over and looked missing. Clear the header. */
    .block-container {{ padding-top: 4rem; padding-bottom: 2rem; }}

    /* Multiselect selected-item tags (Style Options, Maintainers, Search in …).
       They are selections, so they take the same accent as the active nav pill —
       not a colour of their own. */
    [data-baseweb="tag"] {{
        background-color: {t["primary"]} !important;
        border-color: {t["primary"]} !important;
    }}
    [data-baseweb="tag"] span {{
        color: #ffffff !important;
    }}
    """


def _newspaper_css(t: dict[str, Any]) -> str:
    """What a palette alone cannot say: metal rules, cut corners, mono figures.

    Layered *after* the base block, so every selector here is deliberately
    re-stating a base rule rather than duplicating the whole sheet.
    """
    ink, soft, rule, dotted = t["ink"], t["ink_soft"], t["rule"], t["dotted"]
    return f"""
    /* Headlines are the Bodoni display cut; body copy is Garamond at a size
       that actually reads as print. */
    h1, h2, h3 {{ letter-spacing: -0.01em; }}
    h1 {{ font-weight: 900 !important; font-size: 2.1rem; }}
    h2 {{ font-weight: 700 !important; }}

    /* Figures, labels and identifiers run in mono — the paper's "agate" voice. */
    code, kbd, samp, pre,
    [data-testid="stMetricValue"] {{
        font-family: {t["font_mono"]} !important;
    }}
    [data-testid="stMetricLabel"] {{
        font-family: {t["font_mono"]} !important;
        font-size: 0.66rem !important;
        letter-spacing: 0.18em;
        text-transform: uppercase;
    }}
    [data-testid="stCaptionContainer"], [data-testid="stCaptionContainer"] * {{
        color: {t["text_muted"]} !important;
        font-family: {t["font_mono"]} !important;
        font-size: 0.68rem !important;
        letter-spacing: 0.06em;
    }}

    /* Boxes are ruled, not rounded or shaded. */
    [data-testid="stMetric"],
    [data-testid="stExpander"],
    [data-testid="stVerticalBlockBorderWrapper"] > div {{
        border: 1px solid {ink} !important;
        border-radius: 0 !important;
    }}
    [data-testid="stExpander"] summary {{
        font-family: {t["font_mono"]} !important;
        font-size: 0.72rem !important;
        letter-spacing: 0.14em;
        text-transform: uppercase;
    }}
    hr {{ border-top: 1px solid {ink}; opacity: 0.55; }}

    /* Inputs lose the box and keep a single baseline rule, like a filled-in form. */
    .stTextInput > div > div,
    .stSelectbox > div > div {{
        border-radius: 0 !important;
        border: none !important;
        border-bottom: 1px solid {ink} !important;
        background-color: transparent !important;
    }}
    .stTextInput > div > div > input {{
        background-color: transparent !important;
        font-style: italic;
    }}

    /* Primary navigation reads as section heads across the fold: no pills,
       uppercase mono, the active one set in reversed ink.
       (`segmented_controlActive` is the real hook — see docs/ui.md.) */
    [data-testid="stButtonGroup"] {{
        border-top: 1px solid {ink};
        border-bottom: 1px solid {ink};
        justify-content: center;
    }}
    [data-testid="stButtonGroup"] button {{
        background-color: transparent !important;
        border: none !important;
        border-radius: 0 !important;
        padding: 0.55rem 1.6rem !important;
    }}
    [data-testid="stButtonGroup"] button * {{
        font-family: {t["font_mono"]} !important;
        font-size: 0.72rem !important;
        letter-spacing: 0.2em;
        text-transform: uppercase;
    }}
    /* Section heads across the fold read larger than the inline controls. */
    .st-key-wiki_view [data-testid="stButtonGroup"] button *,
    .st-key-maint_view [data-testid="stButtonGroup"] button * {{
        font-size: 0.86rem !important;
        letter-spacing: 0.2em;
    }}
    [data-testid="stButtonGroup"] button[kind="segmented_controlActive"] {{
        background-color: {ink} !important;
    }}

    /* Buttons: cut corners, hairline rule, mono label. */
    .stButton > button, .stDownloadButton > button,
    [data-testid="stFormSubmitButton"] button {{
        border-radius: 0 !important;
        border-color: {rule} !important;
    }}
    .stButton > button:hover {{ box-shadow: none !important; border-color: {ink} !important; }}

    /* Sidebar is the left rail of the front page: ruled sections, no shading. */
    [data-testid="stSidebar"] {{ border-right: 1px solid {ink}; }}
    [data-testid="stSidebar"] h2 {{
        font-family: {t["font_head"]} !important;
        font-weight: 900 !important;
    }}
    [data-testid="stSidebar"] hr {{ border-top: 0.5px solid {rule}; opacity: 1; }}

    /* Result / source lists read as dotted-leader index entries. */
    [data-testid="stExpander"] .stButton > button {{
        background-color: transparent !important;
        border: none !important;
        border-bottom: 1px dotted {dotted} !important;
        text-align: left !important;
    }}

    /* The masthead supplies the top rule, so the header gap can close a little. */
    .block-container {{ padding-top: 3.2rem; }}

    /* Chat turns: ruled columns of type rather than tinted bubbles. */
    [data-testid="stChatMessage"] {{
        background-color: transparent !important;
        border-left: 2px solid {rule};
        border-radius: 0 !important;
        padding-left: 0.9rem;
    }}
    [data-testid="stChatMessage"] * {{ background-color: transparent !important; }}

    a {{ color: {t["primary"]} !important; border-bottom: 1px solid {t["hover"]}; }}
    a:hover {{ color: {ink} !important; border-bottom-color: {ink}; }}
    blockquote {{ border-left: 2px solid {soft}; font-style: italic; }}
    """


def inject_css() -> dict[str, Any]:
    """Write this run's stylesheet and hand back the tokens app.py reads."""
    t = tokens()
    css = _base_css(t) + (_newspaper_css(t) if is_newspaper() else "")
    st.markdown(f"<style>{css}</style>", unsafe_allow_html=True)
    return t


# ── Newspaper chrome ─────────────────────────────────────────────────────────


def masthead(*, edition: str, pages: int, sources: int, model: str) -> None:
    """The broadsheet nameplate: rules, title, tagline, dateline.

    Only rendered under `FRONTEND=newspaper`; the default skin's top bar is the
    plain DATABASE / OPTIONS pair in `app.py`.
    """
    t = tokens()
    ink, soft, muted = t["ink"], t["ink_soft"], t["text_muted"]
    mono = t["font_mono"]
    today = _dt.date.today().strftime("%A, %d %B %Y")
    st.markdown(
        f"""
        <div style="font-family:{mono};font-size:0.62rem;letter-spacing:0.18em;
                    text-transform:uppercase;color:{muted} !important;
                    display:flex;justify-content:space-between;padding-bottom:6px">
          <span>Compiled locally &middot; no network required</span>
          <span>Self-compiling knowledge archive</span>
          <span>Open Knowledge Format v0.1</span>
        </div>
        <div style="border-top:2px solid {ink};border-bottom:0.5px solid {ink};height:3px"></div>
        <div style="text-align:center;padding:18px 0 10px">
          <div style="font-family:{t["font_head"]};font-weight:900;font-size:4.6rem;
                      line-height:0.92;color:{ink} !important">LocalWiki</div>
          <div style="font-family:{t["font_body"]};font-style:italic;font-size:1.05rem;
                      color:{soft} !important;padding-top:6px">
            Documents in, a linked knowledge archive out &mdash; local infrastructure, full data privacy
          </div>
        </div>
        <div style="border-top:0.5px solid {ink};border-bottom:2px solid {ink};height:3px"></div>
        <div style="display:flex;justify-content:space-between;align-items:center;
                    padding:8px 2px;font-family:{mono};font-size:0.68rem;
                    letter-spacing:0.08em;color:{soft} !important">
          <span>{today}</span>
          <span style="text-transform:uppercase;letter-spacing:0.16em">Edition &middot; {edition}</span>
          <span>{pages} pages &middot; {sources} sources</span>
          <span style="color:{t["primary"]} !important">{model}</span>
        </div>
        """,
        unsafe_allow_html=True,
    )


def colophon() -> None:
    """Footer rule the front page closes on."""
    t = tokens()
    st.markdown(
        f"""
        <div style="border-top:1px solid {t["ink"]};margin-top:26px;padding-top:8px;
                    display:flex;justify-content:space-between;font-family:{t["font_mono"]};
                    font-size:0.6rem;letter-spacing:0.16em;text-transform:uppercase;
                    color:{t["text_muted"]} !important">
          <span>OKF v0.1 conformant &middot; citations checked</span>
          <span>Language pinned per page &middot; DE &harr; EN</span>
        </div>
        """,
        unsafe_allow_html=True,
    )
