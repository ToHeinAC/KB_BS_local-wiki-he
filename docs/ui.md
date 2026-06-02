---
name: ui.md
description: comprehensive documentation of the project´s user interfaces (graphical, etc.)
version: 1.1.0
author: Tobias Hein
---

# UI

> Authoritative spec: [`PRD.md`](../PRD.md) §2.4 (GUI Design Direction) and §3.9 (Web Application).

## Visual style — New York Times editorial

The UI must feel like a premium digital publication, not a SaaS dashboard. Concretely (PRD §2.4):

- **Typography first.** Serif-forward or editorial pairing for headings, clean legible body font, strong hierarchy.
- **Generous whitespace**, narrow readable content widths, subtle dividers.
- **Restrained monochrome palette.** Emphasis comes from spacing/scale/rules — not bright accents or dense card grids.
- **No SaaS aesthetics.** No neon, no overly rounded chrome, no playful tone.
- **Documents/citations/research read like articles.** Whatever framework is chosen must be re-styled to this language; the framework's default look is not acceptable.

### Theme system (implementation)

The editorial language is delivered through a single theme-aware CSS block injected at the top of `src/app.py` (an f-string keyed on `_THEMES[st.session_state["theme"]]`). Two palettes:

| Token | **Forest** (default, light) | **Slate** (dark) |
|---|---|---|
| `bg` | `#f6f7f2` | `#0f1117` |
| `sidebar_bg` | `#eaf0ec` | `#1a1d27` |
| `widget_bg` | `#ffffff` | `#262b3a` |
| `text` | `#1a1f1c` | `#e8ecf0` |
| `primary` | `#234637` | `#4f9cf9` |
| `border` | `#d4dbd6` | `#2e3347` |

- **Typography:** **Inter** body (Google Fonts) + **Libre Baskerville** serif headings (the editorial pairing). Buttons are sentence-case with a subtle 6 px radius and hover transition (replacing the earlier all-caps treatment).
- **Toggle:** a sidebar button (`🌙 Dark` / `☀️ Light`, key `theme_toggle`) flips `st.session_state["theme"]` between `Forest` and `Slate` and reruns. Default is `Forest`.
- **`config.toml`:** `.streamlit/config.toml` sets the static base palette (`textColor=#1a1f1c`, `secondaryBackgroundColor=#eaf0ec`); the injected CSS overrides per-surface for dark mode because config theme values are not runtime-switchable. The wildcard rule sets only `color` (never `font-family`, which would break Material icon ligatures); an explicit rule re-asserts the Material Symbols font on icon spans. Component surfaces that pull from `secondaryBackgroundColor` (file-uploader dropzone, expanders, form-submit buttons) get explicit theme overrides so neither theme shows low-contrast text.
- **Expanders** use the page `bg` so the lighter `widget_bg` list buttons inside (e.g. the Wiki Explorer nav panel) stand out as distinct boxes.

## Framework choice

**Streamlit** is the chosen UI framework. Port is fixed at **8520** (8511 reserved on this host). Run with:

```bash
uv run streamlit run app.py --server.port 8520
```

## Access model (login + maintainer layer)

A login gate fronts every page; the sidebar DB selector is scoped to the signed-in user's `dbs` allowlist, and the chosen DB is applied to `db_context` before any page handler runs. Two write-access tiers per DB:

- **Reader** (DB in `dbs`): Wiki Explorer, Chat, Research only.
- **Maintainer** (DB in `maintains`): also sees **Upload** and the Maintenance **Delete Source** / **Reset all data** actions. Maintainer rights are explicit per DB — admin alone does **not** grant them.

Admins (`is_admin`) manage users/databases in the Maintenance admin panels: maintainers are assigned at DB creation (maintainers multiselect) and per user ("Maintained databases" multiselect). Non-maintainers simply don't see the Upload nav entry or the destructive Maintenance sections (read-only tools stay visible).

## Pages (primary navigation)

| Page | Purpose | PRD §§ |
|---|---|---|
| **Upload** | *Maintainer-only.* Drag-and-drop ingest with explicit dedup confirmation. Accepts Markdown plus **PDF / DOCX / images** (`png/jpg/jpeg/tiff/tif/bmp`): non-Markdown files are auto-converted to Markdown by `md_convert.convert_to_markdown` (local Ollama OCR + rewrite; progress bar per page) and shown in an **editable preview** before ingest — only the converted `.md` is stored (`dedup` keys on the original bytes). Before ingesting, shows an optional metadata form (fields from `templates/insert.md`: name, fullname, description, effective as of, part of) to make LLM output more precise. Shows ingest summary (created / updated / contradictions). Never auto-ingest. | 3.9.2 |
| **Wiki Explorer** | Tree-by-`type` navigator (Concepts / Entities / Source Summaries / Comparisons / Other) when search is empty; full-text search across titles, filenames, and page bodies (excerpt highlighted) when active. Rendered Markdown viewer: body rendered clean (no YAML frontmatter); collapsible **Sources** expander at the bottom lists original `data/raw/` documents and related wiki pages. Graph view: interactive vis.js network rendered inline (no pyvis dependency); two toggles — **Node names** (shows page title, up to 5 words) and **Edge themes** (shows first 3 words of linked page's title as edge label). Orphan count shown below graph. | 3.9.3 |
| **Chat** | Chatbot with a **Fast | Deep** mode toggle. **Fast** (default): one-shot 2-stage RAG over wiki pages (`wiki_engine.query_with_sources`); answer appears with a Sources panel listing the wiki pages and original `data/raw/` documents used. **Deep**: agentic LangGraph loop over `data/raw/` originals only (`chat_agent.run_chat_agent`) — no web, halved quality gates vs Research for ~2× speed, paginated reads of long docs, section-suffixed citations (e.g. `[Source: StrlSchG.md §62]`); each Deep answer renders an Agent trace expander with the step-by-step tool feed. Both modes share the same "Save answer to wiki" button (`insights/insight-*.md`). Each answer also has a **"↪ Follow up"** button: it opens a bordered panel showing the original question with a downward connector to the input, and the next message is rewritten into a standalone question (`wiki_engine.condense_followup`) using the prior Q&A before being sent. | 3.9.4 |
| **Research** | Run the ReAct agent (max 8 iterations); show step-by-step progress; gate behind `TAVILY_API_KEY`. Optional wiki context injection; auto-save final report to wiki. A **follow-up input** is rendered directly below the saved report (no scroll-up); the entered question is condensed against the prior question + report before a new run. | 3.9.5 |
| **Maintenance** | Wiki stats, link-graph health (orphan check), lint, activity log (all readers). *Maintainer-only:* **Delete Source** (selectbox of registered sources + irreversibility warning + confirmation checkbox → cascading delete of raw file, chunks, QA rows, wiki pages, then index rebuild) and **Reset all data**. *Admin-only:* Users / Databases management (create DB + assign maintainers, edit per-user access + maintained DBs). | 3.9.6 |

## Top-bar / chrome

Logo + nav + live wiki stats (`N pages | N sources | last updated`) + Ollama connectivity indicator. PRD §3.9.1.

The sidebar Ollama indicator (`_ollama_badge()`) shows a green/red badge ("Ollama online / offline") followed by a `st.sidebar.caption` with the active model name (e.g. `Model: gemma4:e4b` from `ollama_client._MODEL`).

**Sidebar layout (top → bottom):** logo + Ollama badge in a row; the theme toggle; a `DATABASE` caption + DB selectbox (label collapsed); divider; a `NAVIGATION` caption + the page radio; live `N pages · M sources` stats; divider; `Signed in as …` + matching boxed **Reset** / **Logout** buttons side-by-side (`st.columns(2)`, styled via their `.st-key-reset_btn` / `.st-key-logout_btn` classes to override the transparent nav-button style).

The **login gate** is centered in a constrained middle column (`st.columns([1, 1.4, 1])`) with a `## 📖 LocalWiki` heading, a "Sign in to continue" caption, and a full-width primary submit button.

## Error states (UI surface)

Connectivity and config errors must be visible, not silent (PRD §4.2): Ollama down → offline indicator + `ollama serve` hint; missing model → `ollama pull gemma4:e4b`; converting a non-Markdown upload while Ollama is unreachable → error with `ollama pull deepseek-ocr:3b` hint (ingest blocked until conversion succeeds); missing `TAVILY_API_KEY` → Research page disabled with setup steps; partial PDF extraction → `Partial extraction: N pages read`.
