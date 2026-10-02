---
name: ui.md
description: comprehensive documentation of the project´s user interfaces (graphical, etc.)
version: 1.1.0
author: Tobias Hein
---

# UI

> Original spec: [`_bup_PRD.md`](_bup_PRD.md) §2.4 (GUI Design Direction) and §3.9 (Web Application).

## Visual style — New York Times editorial

The UI must feel like a premium digital publication, not a SaaS dashboard. Concretely (PRD §2.4):

- **Typography first.** Serif-forward or editorial pairing for headings, clean legible body font, strong hierarchy.
- **Generous whitespace**, narrow readable content widths, subtle dividers.
- **Restrained monochrome palette.** Emphasis comes from spacing/scale/rules — not bright accents or dense card grids.
- **No SaaS aesthetics.** No neon, no overly rounded chrome, no playful tone.
- **Documents/citations/research read like articles.** Whatever framework is chosen must be re-styled to this language; the framework's default look is not acceptable.

## Broadsheet frontend (NiceGUI, `FRONTEND=broadsheet`)

A second GUI, built from the mockups in [`ideas/gui-redesign/`](../ideas/gui-redesign/notes.md) and planned in
[_plan-gui-broadsheet.md](_plan-gui-broadsheet.md). It serves the same backend as the Streamlit app, which stays in
the codebase. `scripts/run_app.py` reads `FRONTEND` and starts the matching server on port 8520 under `/wiwi`.

- **Entry:** `src/gui_app.py` mounts NiceGUI with `ui.run_with(api, mount_path="/wiwi")`; pages register through
  `register()`, every page titled `L-Wiki` with a 🧠 favicon. Quasar's primary colour is the Streamlit theme's dark green
  `#234637` (`app.colors`). The stylesheet is `src/assets/broadsheet/broadsheet.css` (the mockup tokens plus Quasar
  overrides). NiceGUI 3 loads Quasar into CSS cascade layers, and unlayered rules beat every layer: the mockup's
  `* { margin: 0; padding: 0 }` reset therefore sits in `@layer base`, or it would erase Quasar's own spacing
  (`q-px-*`, menu items, fields). Conversely, Quasar's `!important` utilities (`text-primary` on flat buttons) sit in
  its last layer and outrank unlayered `!important`; an override that must win goes in `@layer theme`. Never name a
  class `xs`/`sm`/`md`/`lg`/`xl` (or `lt-*`/`gt-*`): Quasar shows such an element only at that screen size, which once
  hid every `btn sm` on desktop. Size modifiers are words (`btn small`); `tests/test_gui_classes.py` guards it.
- **Tests:** NiceGUI's `user` fixture (`-p nicegui.testing.user_plugin`, `asyncio_mode = "auto"`, `main_file = ""` in
  `pyproject.toml`). Tests call `gui_app.register()` after the fixture, because it resets NiceGUI per test.
- **Shared logic:** `src/ui_logic.py` holds what both frontends do the same way (ingest driver, save paths, level binding); `gpu_widget.gpu_payload()` and `graph_widget.render_args()` expose the GPU stats and the graph component arguments without Streamlit.
- **Session and sealing (`src/gui_session.py`):** NiceGUI runs every page build, handler and timer tick in its own
  task, and the classification gate lives in ContextVars, so **every entry point re-seals** the session's clearance
  before reading a path: pages through `guard(build)`, handlers and timer callbacks through `guarded(session)`
  (`Session.seal` re-reads `auth.clearance_map`, so a revocation applies at the next interaction and a shrunk grant
  drops the session's content). Blocking backend calls go through `in_worker` (`db_context.bind_context` carries the
  binding into the worker thread); agent generators through `stream_steps`, which consumes the generator and runs an
  `after` callback (e.g. the audit read) in the same worker. Only `gui_session.py` may seal clearance or touch
  `storage.user` (`tests/test_security_rules.py`, `tests/test_gui_session.py`).
- **What is persisted:** `app.storage.user` (a file under `.nicegui/`, gitignored) holds only `user`, `active_db` and an
  opaque `sid` (`PERSISTED_KEYS`). Everything document-derived lives in the in-memory `Session.state`, keyed by `sid`
  in a process-level registry so it survives page navigation but not a server restart.
- **Chrome (`src/gui_chrome.py`):** running head (nameplate, nav, edition = database picker, level stamp, user menu
  with Admin, Reset and Sign out) and a one-line folio (model and GPU pinning, GPU load, search-index size; refreshed
  in a worker every 5 s). The GPU segment shows the card the model works on (`gui_chrome.working_card`): the pinned
  card, else the busiest one, then named by its index. Pages are plain `ui.page` routes (`/`, `/explorer`, `/chat`, `/research`,
  `/maintenance`, `/admin`), each wrapped by `guard`; a signed-out visitor goes to `/login`, and Admin (admins) sends
  everyone else home. There is no separate Upload page: it is the right column of 2BrAIn. The selected database (edition) sits
  in a green box in the running head. `GET /wiwi/_api/gpu` serves the same JSON as the Streamlit route.
- **Chat (`src/gui_chat.py`, `src/gui_cite.py`):** three columns (1/4, 1/2, 1/4, as on Research): a rail (Fast/Deep toggle, "Search in" checkboxes per
  reachable level, folded into one line such as "Deep · KI" once a question is asked; then a Deep answer's timeline
  "How the answer ran", live while it runs, so it sits at the top; the conversation's questions, New conversation), the reading column (question as headline, answer, actions, the follow-up banner, the input)
  and a margin column of numbered source notes. The timeline is `src/gui_trace.py`, shared with Research: agent steps
  stamped with their arrival time become dated items that fold open to the detail. `gui_cite.number_citations` turns `[Source: file §x]` / `[Wiki: page.md]` tags into
  `<sup class="cite" data-n>` numerals plus notes (same file and section reuse a number; one bracket naming several
  sources, `[Source: a.md; Source: b.md]`, gives several numerals; Markdown escapes such as `JEN\_KOINNO.md` are undone);
  hovering a numeral lights its note (`gui_app.CITE_JS`). LaTeX in `$…$`, `$$…$$`, `\(…\)`, `\[…\]` becomes MathML
  (`gui_cite.render_math`, `latex2mathml`) in Chat, Research and the Explorer reader, but only spans that contain a
  `\command`, `^`, `_` or braces and never inside code, so `$5 and $10` stays text; a formula that fails to convert
  is left as written. The answer is rendered through `ui.markdown` with client-side sanitising, so LLM output
  cannot inject script. Fast runs `ui_logic.answer_fast` in a worker. Its prompt asks for `[page title]` citations,
  and small models also write `[file.md Section (Teil 4)]` or comma lists; `ui_logic.tag_wiki_citations` turns every
  bracket that names one of the database's pages (file, stem or title) or one of the answer's originals into a
  `[Wiki: …]` / `[Source: …]` tag in code, and leaves any other bracket alone. *Export .md* downloads the answer as a
  standalone file (`gui_cite.answer_markdown`: question as title, a meta line, citations as Markdown footnotes under
  Sources), named after the question. Deep consumes `chat_agent.run_chat_agent` through
  `stream_steps` (steps appear live, the audit is read in the same worker). Follow-ups go through
  `wiki_engine.condense_followup`; Save (maintainers) files at the highest level searched via `ui_logic.save_answer`.
  Opening a note reads the document in a worker; a denied name looks exactly like a missing one. The conversation is a
  `Chat` in `Session.state`, so it is dropped with the session's content. Each page starts at the base level with no
  widened scope (`guard`); Chat sets its own scope for its handlers.
- **Explorer (`src/gui_explorer.py`, `src/gui_graph.py`):** a bar (level picker when more than one level is reachable,
  Map/Index, layout, Find, and a right-aligned *Advanced* menu with size-by and the overlays), the left column and the
  reader on the right. The bar uses the same two-column grid as the content, so Find (dark-green rule) ends exactly at
  the map column's edge. **Map** is the existing
  canvas renderer (`src/assets/graph/index.html`, served from `graph-assets/`) in an iframe on the paper palette, with a
  standings table (top pages by PageRank or connections) beside it. `gui_graph.GRAPH_JS` plays the Streamlit component
  host's side of the `postMessage` protocol: it answers `streamlit:componentReady` with the arguments from
  `graph_widget.render_args` and forwards `streamlit:setComponentValue` (a double-click) as the `graph_open` event, so
  no page reloads; `graph_click` decides between opening a page and a notice for a source node. **Index** is the tree by
  type (`get_wiki_tree`); **Find** shows hits with an excerpt and the ontology line, and reports a missing index instead
  of "no results". The reader shows the page with its citations numbered as in Chat (`cite_page`: a bracket naming
  one of the page's sources or a wiki page becomes a `[Source: …]`/`[Wiki: …]` tag; the page's own References and OKF
  Citations blocks are left out of the view, the stored page is unchanged), the numbered notes and then its other
  original documents (opened in a dialog through `gui_chat.open_source`), and linked pages; with nothing selected it shows the bundle health (Map) or the database overview (Index). One level
  at a time: switching binds that shard as the active DB and the only scope. Graph data is computed in a worker and
  cached per shard by `graph_widget._payload`, the cache the classification leak suite covers.
- **Research (`src/gui_research.py`):** a question bar (question, Quick/Deep method, "Include classified levels", Start,
  New research) above three columns (1/4, 1/2, 1/4). Left: the figures box (sub-tasks, web searches, pages read,
  sources cited; from a Deep run's metrics), a timeline "How the research ran" built from the persisted steps
  (`gui_trace`; `ResearchComplete` is a finished-phase line, never `— {}`; a Deep to Quick fallback `notice` is shown)
  and a follow-up. Middle: the report, the agent's answer with numbered citations (`gui_cite`), Save to wiki with "Also
  register as a source document" (maintainers) and Download. Right: the sources exactly as in Chat
  (`gui_chat.render_note`: web notes with page title and host, originals opening in a dialog), the pages read but not
  cited under "Also read", and the search-ladder audit. Runs stream through
  `gui_session.stream_steps` with `agent.run_research_agent` or `deep_research_agent.run_deep_research`; the audit is
  read in the same worker. Including classified levels widens the scope to every reachable level, forces Quick (web
  tools stay off, Deep is not run) and locks the choice until New research. Everything is gated on `TAVILY_API_KEY`; a
  run that ends with neither a result nor an error says so instead of showing a blank page.
- **Upload (`src/gui_upload.py`, the right column of 2BrAIn, maintainers only):** three steps, never automatic. *Prepare* (in a worker,
  `prepare_batch`): duplicates at levels the user can see are skipped and named, PDF/DOCX/images are converted through
  `md_convert` with a progress bar (Ollama must be reachable), the effective date and, in a database with an ontology,
  the class, work and other versions are detected. *Review*: one table (file, date, class, work, other versions, and a
  classification toggle per file with no default and levels only up to the uploader's clearance); a single converted
  file has an editable Markdown preview (three lines, scrolling, so the metadata and Ingest stay in view); the
  effective date is an outlined YYYY-MM-DD field with a calendar picker, marked in oxide while missing or malformed,
  and a hint line names the undated files and why the date matters (`date_problem`, `undated`); the ingest button is dashed and disabled until every file is classified, with the
  reason beside it (`block_reason`). *Ingest* (`run_ingest`): oldest first, one level at a time through
  `ui_logic.ingest_level`, each level into its own shard, then a summary (created, updated, contradictions, failures,
  ignored ontology values). Reported contradictions feed a **Resolve contradictions** panel (pages, guidance, Reconcile
  through `ui_logic.resolve_by_shard`, Dismiss); a new ingest resets it. *Discard* drops a prepared batch unwritten. While a batch is prepared or ingested, a progress bar
  and a spinner beside the current step show it is working. Progress is a plain object the worker writes and
  a timer reads, so no widget is touched from a thread.
- **Maintenance (`src/gui_maint.py`):** statistics (pages, raw sources, data size), a level picker when more than one
  level is reachable (`Session.bind_shard`: that shard becomes the active DB and the only scope, so every section
  follows it), and a section toggle: *Search index* (counts, a missing-index warning, Rebuild), *Delete source* (a
  confirmation checkbox enables the dashed button; below it *Move to another classification level* with the purge
  warning when moving up), *Link graph health* (orphans), *Lint*, *Page language* (scan, then Normalize), *Ontology* (the
  workbench, below) and the *Activity log*, plus *Admin* for admins (`gui_maint.sections`: the Admin view below,
  as in Streamlit). Destructive actions are maintainer-only and re-checked in the
  handler (`_maintainer_only`), not just hidden; long backend calls run in workers.
- **Admin (`src/gui_admin.py`, admins only, reached from the user menu and Maintenance → Admin):** databases (create, with maintainers), users
  (allowed databases, maintained databases, clearance per allowed database, a new password, Save, Delete, never your own
  account) and the security audit log. Every action goes through a function that re-checks `auth.is_admin(actor)`
  (`require_admin`) and is tested to refuse a non-admin; clearance changes are audit-logged by `auth.set_clearance`.
- **Ontology workbench (`src/gui_ontology.py`, Maintenance → Ontology):** a port of `ontology_ui.render` reusing its
  pure helpers (`bullets`, `when`, `fmt`, `change_line`, `class_usage`, `class_line`). Without an ontology: create
  from modules (warns when none has detection cues) or import. With one: the revision header (open proposals, last
  manual and automatic change, YAML export) and nine views: Overview (counts, SKOS and JSON-LD downloads), Classes
  (tree and relations), Facts, Edit (local classes and per-document facts as rows of inputs, Preview then Apply),
  Proposals (confirm or reject fact proposals, classify concept pages, request and accept class suggestions), Cues (cue
  tester, re-classify preview and apply), Lint, History (diff, download, restore as a new revision) and Import (upload,
  conflict choices, preview, apply). Every write goes through the same plans and `wiki_engine` calls, which check
  maintainer rights and record a revision; model calls run in a worker.
- **2BrAIn (`src/gui_front.py`, `/`):** the front page and the start of the user flow. A dateline (the date left, the
  tagline right; no nameplate, so the galaxy fits on screen), then three columns: recent activity parsed from the wiki's OKF `log.md` (`log_entries`; one collapsed fold, one line per entry, times converted from the log's UTC to local time by `local_time`) above the archive's
  figures and the clusters growing in the health window (`graph_widget.graph_health`); the galaxy map
  (`gui_graph.map_data`, Hubs overlay, the same iframe renderer as the Explorer; a double-click on a page opens it in the
  Explorer reader); and the upload (`gui_upload.UploadView`) for maintainers, a note for readers. While a batch is
  prepared or reviewed (`on_review`), the upload takes the galaxy's place; when it ends, the columns reload. The upload column is
  built at once, so an empty wiki still offers it.
- **Cutover:** `broadsheet` is the default `FRONTEND`; `tunnel.sh` and the `restart-app` skill launch through
  `scripts/run_app.py` and stop either server by `src/(app|gui_app).py … port 8520` (SIGTERM first). Admins have a
  *Stop server* item in the user menu (`gui_chrome.stop_server`: SIGTERM to the server's own process, never a kill by
  port; the admin check is in the function).
- **Status:** plan phases 0–9 done. The Streamlit app stays in the codebase behind `FRONTEND=default` or `newspaper`.

## Frontend skins (`FRONTEND`)

Two Streamlit frontends ship, chosen once per process by `FRONTEND` in `.env`. They render the **same pages, widgets and
behaviour** — only the chrome differs, so nothing below §Pages depends on which is active.

| `FRONTEND` | Look |
|---|---|
| `default` | The editorial Forest/Slate palette described below. Unchanged. |
| `newspaper` | Broadsheet: paper stock `#f4f1e6`, ink `#1c1a15`, rust accent `#7a3b2a`, Bodoni Moda masthead + headlines, EB Garamond prose, IBM Plex Mono for figures and labels, hairline rules, square corners. |

Both come out of `src/theme.py`, which is deliberately **one** token-parametric base stylesheet plus a newspaper
override block — not two sheets. The base sheet encodes every Streamlit quirk this app has had to fix (the opaque
`stHeader`, the Material-icon font re-assertion, the `stButtonGroup` hooks); forking it would mean fixing each one
twice. The tokens keep the names the default skin already used (`bg`, `primary`, `border`, …) because `app.py` and
`gpu_widget.render_gpu_sidebar(accent=…)` read them by name.

What the newspaper skin changes structurally, beyond colour and type:

* **A masthead replaces the `DATABASE` / `OPTIONS` top bar** (`theme.masthead()`): double rules, the nameplate, the
  tagline, and a mono dateline carrying date · edition · page/source counts · model. `theme.colophon()` closes the
  page with the OKF/language footer rule.
* **The database selector moves into the sidebar**, labelled `EDITION`. The mock's left-hand column *is* this app's
  sidebar, and the nameplate needs the full width. The slot is claimed in the sidebar block (`_db_slot`) and filled
  by the top-bar block further down, so it lands under the logo rather than at the foot of the rail.
* **Primary navigation loses its pills**: the same `st.segmented_control` is restyled as centred uppercase mono
  section heads between two rules, the active one reversed out in ink. The hook is still
  `button[kind="segmented_controlActive"]` — see §Top-bar / chrome.
* **The graph canvas goes to paper** (`graph_widget.render_graph(paper=True)`). The canvas is dark *by default* on
  purpose (§Graph view), but a night-black panel inside a printed page reads as a hole, so paper mode swaps a
  `PALETTES.paper` entry into the renderer's CSS custom properties, drops the galaxy backdrop and veil, and replaces
  the bloom with a thin ink outline so dots stay crisp discs. The dark palette is byte-identical to before.
* Inputs lose their box for a single baseline rule; expanders, metrics and bordered containers become ruled boxes;
  chat turns become ruled columns of type instead of tinted bubbles.

### Theme system (implementation)

The editorial language is delivered through a single theme-aware CSS block built in `src/theme.py` (an f-string keyed on `_THEMES[theme.theme_name()]`). Two palettes:

| Token | **Forest** (default, light) | **Slate** (dark) |
|---|---|---|
| `bg` | `#f6f7f2` | `#0f1117` |
| `sidebar_bg` | `#eaf0ec` | `#1a1d27` |
| `widget_bg` | `#ffffff` | `#262b3a` |
| `text` | `#1a1f1c` | `#e8ecf0` |
| `primary` | `#234637` | `#4f9cf9` |
| `border` | `#d4dbd6` | `#2e3347` |

- **Typography:** **Inter** body (Google Fonts) + **Libre Baskerville** serif headings (the editorial pairing); both are tokens (`font_body` / `font_head`), which is what the newspaper skin re-points. Buttons are sentence-case with a subtle 6 px radius and hover transition (replacing the earlier all-caps treatment).
- **Toggle:** the runtime theme switch is currently disabled — the app stays on the default `Forest` palette. The `Slate` (dark) palette and the full `_THEMES` switching machinery (CSS keyed on `st.session_state["theme"]`) remain in `src/app.py` so a `theme_toggle` sidebar button can be re-added later without rework.
- **`config.toml`:** `.streamlit/config.toml` sets the static base palette (`textColor=#1a1f1c`, `secondaryBackgroundColor=#eaf0ec`); the injected CSS overrides per-surface for dark mode because config theme values are not runtime-switchable. The wildcard rule sets only `color` (never `font-family`, which would break Material icon ligatures); an explicit rule re-asserts the Material Symbols font on icon spans. Component surfaces that pull from `secondaryBackgroundColor` (file-uploader dropzone, expanders, form-submit buttons) get explicit theme overrides so neither theme shows low-contrast text.
- **Expanders** use the page `bg` so the lighter `widget_bg` list buttons inside (e.g. the Wiki Explorer nav panel) stand out as distinct boxes.

## Framework choice

**Streamlit** is the chosen UI framework. Port is fixed at **8520** (8511 reserved on this host). Run with:

```bash
uv run streamlit run app.py --server.port 8520
```

Open `http://localhost:8520/wiwi/`; the port root 404s. The app is served under the base path `/wiwi/` to match the nginx reverse proxy — see [tech.md](tech.md#streamlit-notes).

## Access model (login + maintainer layer)

A login gate fronts every page; the top-bar DB selector is scoped to the signed-in user's `dbs` allowlist, and the chosen DB is applied to `db_context` before any page handler runs. It selects the **active** database — the single write target. Wiki Chat's separate "Search in" multiselect (same allowlist, one entry per reachable classification level) widens *reads* across databases without changing where writes land. Two write-access tiers per DB:

- **Reader** (DB in `dbs`): Wiki Explorer, Chat, Research only.
- **Maintainer** (DB in `maintains`): also sees **Upload** and the Maintenance **Delete source** action. Maintainer rights are explicit per DB — admin alone does **not** grant them.

Admins (`is_admin`) manage users/databases in the Maintenance admin panels: maintainers are assigned at DB creation (maintainers multiselect) and per user ("Maintained databases" multiselect). Non-maintainers simply don't see the Upload segment, the destructive Maintenance sections or the save buttons of Chat and Research (read-only tools stay visible).

**Classification levels.** Each DB has three levels (Normal / Confidential / Strictly confidential); admins set a user's **clearance** per DB (a *Clearance · DB* selectbox per allowed DB, and one for the Add-user form), and the Admin section shows the **security audit log**. Where a user reaches more than one level, **Wiki Explorer** and **Maintenance** show a level control and work on one level at a time; Chat's "Search in" lists levels; Research includes them only on opt-in. Design and rules: [security.md](security.md).

## Pages (primary navigation)

The four wiki views are selected by a horizontal `st.segmented_control` under an `OPTIONS` heading at the top of the main window (`key="wiki_view"`, `required=True` so the active pill cannot be deselected); **Maintenance** is a separate sidebar entry that takes over the main window and offers a `← Back to Wiki` link. `st.tabs` is deliberately *not* used: it evaluates every branch on each rerun, and the Upload branch's `st.stop()` calls would blank the other tabs.

| Page | Purpose | PRD §§ |
|---|---|---|
| **Upload** | *Maintainer-only.* Drag-and-drop ingest with explicit dedup confirmation. In a DB with an ontology, the review table adds *Class*, *Work* and read-only *Other versions* columns prefilled by detection ([ontology.md](ontology.md) §Detection at upload). Accepts Markdown plus **PDF / DOCX / images** (`png/jpg/jpeg/tiff/tif/bmp`): non-Markdown files are auto-converted to Markdown by `md_convert.convert_to_markdown` (local Ollama OCR + rewrite; progress bar per page) and shown in an **editable preview** before ingest — only the converted `.md` is stored (`dedup` keys on the original bytes). Before ingesting, shows an optional metadata form (fields from `templates/insert.md`: name, fullname, description, effective as of, part of) to make LLM output more precise. Shows ingest summary (created / updated / contradictions). Never auto-ingest. Every file needs a **classification** (one segmented control per file, no default, levels up to the uploader's clearance); ingest is refused until each is chosen, then runs one level at a time into that level's store. Contradictions the ingest reported feed a **Resolve contradictions** panel (one expander per item: pages multiselect, optional guidance, *Reconcile*); its heading carries a help tooltip with the options and an example, a **Dismiss** button clears it, and each new ingest resets it. A Reconcile reply that switched a page's language is not saved (warning names the page). | 3.9.2 |
| **Wiki Explorer** | One classification level at a time (a level control above the view when more than one is reachable). Tree-by-`type` navigator (Concepts / Entities / Source Summaries / Comparisons / Other) when search is empty; full-text search across titles, filenames, and page bodies (excerpt highlighted) when active — consecutive hits are separated by a horizontal rule so the button / score bar / excerpt / matched-terms stack of each result reads as one block. Rendered Markdown viewer: body rendered clean (no YAML frontmatter); collapsible **Sources** expander at the bottom lists original `data/raw/` documents and related wiki pages. Graph view: renderer selected by `GRAPH_RENDERER` (see §Graph view below) — `legacy` is the interactive vis.js network rendered inline (no pyvis dependency), two toggles — **Node names** (shows page title, up to 5 words) and **Edge themes** (shows first 3 words of linked page's title as edge label). Orphan count shown below graph. | 3.9.3 |
| **Chat** | Chatbot with a **Fast | Deep** two-option segmented control (label and help collapsed — the page caption already explains the two modes). `st.chat_input` is wrapped in a `st.container()` so it renders **in the page flow** rather than pinned to the viewport bottom: it only sticks when it is a direct child of the main body, and pinned it floated over the newspaper colophon. The multi-database caption stays outside the Advanced expander, because a scope wider than the active DB changes how every answer is cited. **Fast** (default): one-shot 2-stage RAG over wiki pages (`wiki_engine.query_with_sources`); answer appears with a Sources panel listing the wiki pages and original `data/raw/` documents used. **Deep**: agentic LangGraph loop over `data/raw/` originals only (`chat_agent.run_chat_agent`) — no web, halved quality gates vs Research for ~2× speed, paginated reads of long docs, section-suffixed citations (e.g. `[Source: StrlSchG.md §62]`); each Deep answer renders an Agent trace expander with the step-by-step tool feed. Both modes share the same maintainer-only "Save answer to wiki" button (`insights/insight-*.md`, with `derived_from`), which files at the highest level searched. Each answer also has a **"↪ Follow up"** button: it opens a bordered panel showing the original question with a downward connector to the input, and the next message is rewritten into a standalone question (`wiki_engine.condense_followup`) using the prior Q&A before being sent. A **"Search in"** multiselect (inside the collapsed **Advanced** expander below the mode toggle, alongside **New chat**; options = the user's `dbs` allowlist, default = the active DB) lets both modes search several databases — and every reachable classification level (default: all levels of the active DB) — at once; with >1 selected, results and citations are qualified as `Database::file.md` and a caption names the databases being searched. Writes stay single-DB: uploads and "Save answer to wiki" always target the sidebar's active database, at the highest level searched (the button's help text names it), and a cross-DB answer keeps only that level's pages as `related:`. See [retrieval.md](retrieval.md) §Multi-database chat. | 3.9.4 |
| **Research** | Two agents behind a **Quick / Deep** segmented control (label collapsed; the page caption explains both), mirroring Chat's Fast/Deep. Whole page gated behind `TAVILY_API_KEY`. **Quick** (default): the local-first ReAct agent (`agent.run_research_agent`) — wiki → raw → web for gaps; optional wiki-context paste. **Deep**: web-only (`deep_research_agent.run_deep_research`) — a supervisor pipeline over the vendored `open_deep_research` graph that decomposes the question and cites web URLs; it ignores the wiki paste (the expander label says so). Both stream through the same `_run_research_stream`, which takes `deep=` and shows step-by-step progress. The **Sources** panel renders tool calls for both modes and, for Deep, **per-URL citation cards** (linked title + host, de-duped by URL via `_record_research_urls`). A Deep run that fails falls back to Quick mid-stream: the new `notice` step-dict renders as `st.warning`, then Quick's steps continue in the same trace. Reports save to `comparisons/` and render inline with download + maintainer-only "Save to wiki". **Include classified levels (web search off)** (checkbox, shown when more than one level is reachable) adds the user's classified levels to Quick mode, removes its web tools and disables Deep; after a classified run it stays locked until *New research*. **"Register as a source document"** (checkbox beside Save, off by default) switches the save from `wiki_engine.ingest` to `wiki_engine.ingest_as_source`: the report is written into `data/raw/` through the manifest first, so it behaves like an uploaded file — `raw_read` opens it, Deep chat can ground on it, Maintenance → Delete source cascades it, and the typed graph's `source::` node points at a document that exists. Left off, the wiki pages are still written but the source node is a bare name with no file behind it. Saving the identical text twice is a no-op (`duplicate: True`). **Agent trace + metrics:** every step is persisted to `st.session_state["last_research_steps"]`, so `_render_research_trace` can replay it below the report instead of it vanishing on the caller's `st.rerun()`; `_render_research_step` is the single renderer used both live and on replay. Intermediate results (thoughts, tool results) are **collapsed `st.expander`s**, one-line control-flow steps stay inline, and the trace is a *flat* sequence of expanders under a heading because `st.expander` cannot nest. `_render_research_metrics` shows `st.metric` tiles for the finished Deep run — sub-tasks, web searches, sources checked, sources cited — dropping "Sources checked" when it would merely repeat "Web searches". `ResearchComplete` is rendered as a success line, never as `— {}`: it is a zero-field sentinel that by design carries no arguments and returns no result (see [deep_research.md](deep_research.md)). A **follow-up input** is rendered directly below the saved report (no scroll-up); the entered question is condensed against the prior question + report before a new run in the currently-selected mode. See [deep_research.md](deep_research.md). | 3.9.5 |
| **Maintenance** | Wiki stats, **Search index** (per-scope row counts from `lex_index.index_health()`, a warning when the DB has no `chunks.sqlite`, and a maintainer-only *Rebuild search index* button → `wiki_engine.rebuild_lex_index()`), link-graph health (orphan check), lint, **Page language** (*Scan* = dry-run table of pages to stamp / translate / de-`[Teil]`; maintainer-only *Normalize N pages* → `wiki_engine.normalize_pages`), **Ontology** (revision, last manual and last automatic change, export, class tree, facts, proposals, history with diff/download; *Create*, *Import* with preview and conflict choices, *Confirm/Reject* of proposals, and *Restore* are maintainer-only — see [ontology.md](ontology.md) §Workbench), activity log (all readers). Sections are picked by the **same `st.segmented_control`** as the primary nav, not `st.tabs` — for the same reason (tabs evaluate every branch per rerun, so the index-health read, the orphan scan and the log read all ran on every click). *Maintainer-only:* **Delete source** (selectbox of registered sources + irreversibility warning + confirmation checkbox → cascading delete of raw file, chunks, QA rows, wiki pages, then index rebuild), and below it **Move to another classification level** when a second level is reachable (`wiki_engine.move_source`; moving up purges the lower level, see [security.md](security.md) §Moving a source). *Admin-only:* the **Admin** section — Users / Databases management (create DB + assign maintainers, edit per-user access + maintained DBs). | 3.9.6 |

## Top-bar / chrome

Main window: `DATABASE` selector + stats + the `OPTIONS` view switcher. Sidebar: logo + live GPU widget + Maintenance + account. PRD §3.9.1.

**Live GPU widget (`src/gpu_widget.py`).** Replaces the former text-only Ollama badge with a real-time monitor: per-GPU temperature / fan / load (from `nvidia-smi`) plus the active model (`llm: …` from `ollama_client.MODEL`) and, during a research run, an elapsed timer. Because Streamlit 1.57 serves via **Starlette/uvicorn** (not Tornado), `render_gpu_sidebar()` injects a same-origin `/_api/gpu` route into the live Starlette app (discovered through `gc.get_objects()`, inserted at index 0 of `app.router.routes` so it precedes the SPA catch-all). A small `components.html` iframe polls that relative URL every second — no extra port, no CORS, works over SSH/Cloudflare tunnels. The widget is hidden gracefully when no GPU / `nvidia-smi` is present. Colors track the Streamlit theme: GPU rows use the muted grey of the `llm:` line, and the normal temp/load state uses the `primaryColor` (`#234637`, passed via `render_gpu_sidebar(accent=_t["primary"])`) — the same dark green as the radio buttons; warning thresholds stay orange (≥70 °C / ≥50 %) and red (≥80 °C / ≥80 %).

**Never gate a button's `disabled=` on a text widget's value.** `st.text_input` returns the value from the last *completed* rerun, and typing does not rerun the script — so mid-typing the variable is still `""`. A `disabled=not question` button therefore renders with a `not-allowed` cursor while being perfectly clickable: the click blurs the input, which commits the text and reruns, and the click lands. The affordance lies about the state. Both Research buttons (`start_research_btn`, `research_followup_go`) gate only on `TAVILY_API_KEY` — a precondition that really is known at render time, and one the page's warning banner already explains — and validate the text on click with an `st.warning`. Widgets that commit immediately (checkboxes, selectboxes, segmented controls) rerun on interaction and *are* safe to gate on, which is why Maintenance's `delete_source_btn` correctly keys off its confirmation checkbox.

**Main-window top bar:** a narrow `DATABASE` heading + DB selectbox with the live `N pages · M sources` stats caption beneath it, and **below it, spanning the full page width**, the `OPTIONS` segmented control (Upload · Wiki Explorer · Wiki Chat · Research; Upload only for maintainers) — `width="stretch"` plus a `.st-key-wiki_view` / `.st-key-maint_view` CSS rule that gives each option an equal `flex: 1 1 0` share and a larger type size. That scoping matters: the rule must not reach the inline segmented controls (graph *Layout*, chat *Fast | Deep*), which keep their content width. The nav **is** the page header, so the four wiki pages render no title of their own — the active pill already names the page, and only the part it cannot say (Upload's accepted formats, Chat's Fast/Deep distinction) stays as a caption. `_page_header()` survives for Maintenance, which is reached from the sidebar and has no pill. When Maintenance is active the segmented control is replaced by the `← Back to Wiki` button and the DB selectbox stays (Delete Source / Lint / Reset are DB-scoped). Both headings come from `_bar_label()` (markdown `<div>` with an inline `!important` colour, since the blanket `.stApp *` rule would repaint it) with the widgets' own `label_visibility="collapsed"`. `.block-container` needs `padding-top: 4rem` for them to be visible at all: Streamlit's fixed `stHeader` is **opaque** in the theme's background colour and overlays the top ~46 px of the main column, so at the old 1.5 rem the top bar's first line was painted over and looked like it had never rendered — widget labels, captions and raw HTML alike. The pills are styled through `[data-testid="stButtonGroup"]`, and the selected one through `button[kind="segmented_controlActive"]`; **not** `stSegmentedControl` / `aria-checked`, which match nothing. The block runs before the page dispatch so `set_active_db()` still lands before any page handler reads paths. A stale `wiki_view` (e.g. `Upload` after switching to a DB the user does not maintain) is reset **before** the widget is instantiated — a post-instantiation write to a widget key raises.

**Sidebar layout (top → bottom):** `## 📖 LocalWiki` logo + the GPU widget; divider; the **🛠 Maintenance** entry (`.st-key-maint_nav_btn`, given a primary-colour active state by a small conditional `<style>` block, since the sidebar's generic button rule outranks `type="primary"`); divider; `Signed in as …` + matching boxed **Reset** / **Logout** buttons side-by-side (`st.columns(2)`, styled via their `.st-key-reset_btn` / `.st-key-logout_btn` classes to override the transparent nav-button style).

The **login gate** is centered in a constrained middle column (`st.columns([1, 1.4, 1])`) with a `## 📖 LocalWiki` heading, a "Sign in to continue" caption, and a full-width primary submit button.

## Graph view (Wiki Explorer)

**Graph is the Explorer's default view** (first radio option). Under `legacy` it spans the full page width; under
`neural` the canvas takes ~92 % of the width with the **side panel** collapsed to a one-button rail, and drops to
`st.columns([3, 1])` when the panel is opened (see §Side panel below). The tree
navigator and its page search stay in Tree view rather than being duplicated in a side column.

Both views share `st.session_state["explorer_selected_page"]`, so switching **into Tree clears it** (`explorer_view_mode` tracks the transition): Tree always opens on the database overview rather than on whatever node was opened in the graph.

Two renderers behind `GRAPH_RENDERER` (`.env`), both drawing the **same** typed graph from `wiki_engine.build_typed_graph()`:

* `legacy` (default) — the inline vis.js network, `_render_legacy_graph()` in `app.py`.
* `neural` — the canvas neural renderer, `_render_neural_graph()` → `src/graph_widget.py` → `src/assets/graph/index.html`.

Facts that cost a debugging round-trip each; do not re-derive them:

* **Single click selects, double click opens.** A click fills the canvas's own info panel (top right) with the node's properties and lights its 2-hop neighbourhood, entirely client-side — no rerun. Only a double click posts back to Python to open the page, so reading the graph is free and opening is deliberate.
* **Node opening must NOT navigate the top window.** The tempting design — `window.top.location = "<base>/?page=<slug>"` plus `st.query_params` — is a full page load, and this app gates on `st.session_state["user"]` with the active DB in session state. The click would therefore land the user on the login screen. Navigation instead goes through the **Streamlit component protocol**: the iframe posts `streamlit:setComponentValue` on double click, Streamlit reruns the script, and `_render_neural_graph()` sets `explorer_selected_page` and the side panel renders it. Session, chat history and reader position all survive.
* **The returned value carries a click counter (`n`).** Streamlit only reruns when a component's value *changes*, so double-clicking the same node twice with a bare id would be a no-op the second time.
* **The component is declared, not `components.html`-embedded.** `declare_component(path=…)` serves `src/assets/graph/` through Streamlit itself, which is what makes it bidirectional *and* base-path-correct under `/wiwi/` — no `gpu_widget.py`-style Starlette route injection needed. It needs **no npm build**: the directory is plain static files and the four protocol messages (`componentReady`, `setFrameHeight`, `setComponentValue`, and the inbound `streamlit:render`) are hand-rolled in the page.
* **`declare_component` silently skips registration outside a ScriptRunContext**, leaving the iframe on a 404. Hence `graph_widget._component()` declares lazily on first render rather than at import time.
* **The canvas is dark on purpose**, against the app's light Forest palette — the neural aesthetic depends on it. Only the accent tracks the theme (`theme.primaryColor`). The one exception is `render_graph(paper=True)`, which the newspaper frontend passes: colours come from `PALETTES.paper` instead of `PALETTES.dark`, applied through the same CSS custom properties, with the backdrop and the bloom off. Every colour literal routes through the palette object, so there is no `if (paper)` scattered through the draw calls and the dark default cannot drift.
* **The galaxy opens fully in frame.** The force layout's extent is only known once it settles, so `fitAll()` re-frames the visible nodes (centred, zoomed out to fit with a 64 px margin, never zoomed in) on every simulation tick until the layout settles or the reader pans or zooms (`S.userView`); a relayout re-arms it. The closed-form layouts keep their one-shot `fitTo`.
* **The backdrop is a Hubble galaxy image** (`src/assets/graph/galaxy.jpg`, credit NASA/ESA — see `NOTICE`), served from the component directory like everything else, so it stays same-origin and CDN-free. It is **optional**: `GRAPH_BACKDROP=galaxy` (default) or `none` for flat black — decorative only, nothing about the graph or its interactions changes. It is heavily dimmed (`filter: brightness(.42)`) under a radial `#veil`, because the dots must remain the brightest thing on screen, and it parallaxes at 12 % of the pan and 8 % of the zoom (`parallax()`, written only when the transform actually changes). The canvas itself is now **cleared, not filled** — `html/body` keep `--bg` so a failed image load degrades to the old flat black.
* **Analytics are computed in Python and stamped into the payload** (`src/graph_export.py`) — PageRank, betweenness, Louvain, staleness, orphan/hub flags. The renderer re-derives nothing, matching the OKF/language rule that structure is decided in code. Staleness in particular reuses `wiki_engine.is_page_stale`, so the amber ring and the nav tree's ⚠️ cannot disagree.
* **One metric at a time, chosen by a toggle** (off = `pagerank`, the default; on = `degree` → `size_by`). A dot's radius therefore means exactly one thing. Switching only re-radiuses nodes in place — `applySizes()` never touches coordinates.
* **A ranked-circle chart sits in the canvas's bottom-right corner** (`#rank`, `renderRank()`): the top 15 nodes ordered by the selected metric, circle diameter ∝ √metric, rank spectrum violet → red, with the value beside each name. It answers the ordering question ("which pages carry this wiki?") that a force layout cannot. It is **scoped to the selection**: with a node selected it ranks that node's 2-hop neighbourhood, otherwise the whole graph. Rows are handles like the dots themselves — **hover lights the same 2-hop neighbourhood the dot would** (the row writes `S.hover`; the pointer is over the panel, so the canvas's own `mousemove` cannot fight it), click selects, double click opens the page. Without that hover binding the chart is a list *beside* the map instead of a way into it.
* **Three layouts over one payload** (`layout` → `relayout()`: `galaxy` | `arc` | `radial`; Streamlit segmented control *Galaxy / Ranked / Clusters*). Nothing about the analytics changes with the layout — only where the dots land, and the renderer still derives no structure of its own.
  * `galaxy` (default) — the force layout. Returning to it **restores the map that was already read** (`n.gx/gy`, written by `tick()`), because a reseed is random and would silently relocate every page.
  * `arc` — the metric's head (`ARC_MAX = 60`) as a single ranked column with edges bowing right as arcs, spacing scaled to the radii, every row labelled. Closed-form and **byte-identical on every visit**, which a force layout can never be; that stability is the whole reason it exists. It colours by rank rather than category, so `renderLegend()` swaps the category key for the rank ramp — a category swatch there would explain an encoding the canvas is not using — and the ramp spans the arc column, so a row and its dot stay the same colour.
  * `radial` — hierarchical edge bundling: pages on a ring ordered by `(comm, metric, label)`, every link routed as a cubic Bézier through its endpoints' **community centroids** (`S.parents`, at 0.42 R). Within-community links collapse into short inward loops, so what still crosses the middle is exactly the cross-cluster structure the `bridge` metric measures. Community members are contiguous on the ring by construction, so the centroid is a plain angular midpoint — no wrap-around case.
* **`tick()` returns immediately outside `galaxy`.** The deterministic layouts are closed-form; simulating them would undo them. For the same reason the synapse pulse is drawn only on straight edges — it interpolates a line, so on an arc or a bundle it would visibly leave the wire.
* **A layout that drops nodes drops them everywhere.** `arc` shows only its head, so `n.vis` gates drawing, edge drawing *and* `nodeAt()` hit-testing together — an invisible node with a stale position would otherwise stay clickable.
* **A metric change is a layout change in the deterministic modes.** In `galaxy` switching the metric only re-radiuses (`applySizes()`); `arc` and `radial` order *by* the metric, so `onRender()` re-runs `relayout()` there.
* **A selection recolours its own subgraph by rank** (`S.rankColors`, consumed by `nodeColor()`): the selected node's neighbourhood takes the same violet → red rank colours as the chart rows, so a row and its dot are the same colour. With nothing selected the map stays categorical (`CAT_COLOR`). The scale spans the *visible* rows; anything ranked below them shares the tail colour.
* **Overlays are a Streamlit widget, not canvas buttons** — they persist in `st.session_state` across the reruns that clicks and ingest cause; pan / zoom / hover / search stay inside the canvas, where a rerun would be wasteful.
* **The controls are ranked, not laid out side by side.** Graph|Tree is a two-option segmented control (it was a radio, which read as a form field), and under Graph it shares one row with *Galaxy / Ranked / Clusters* — `st.columns([2, 0.2, 5])` with a dimmed `|` rule between them, since both pick what the main area shows and read better as one decision than two stacked ones. The layout switch is therefore drawn by the **Explorer page**, not by `_render_neural_graph()`, which now takes the resolved key as an argument (`_GRAPH_LAYOUTS` sits at module level). The columns are created before `view_mode` is known, which is fine: nothing is written into them until after. **Connections** and **Style Options** refine what is already drawn, so they sit in a collapsed `Advanced` expander. They still instantiate on every run — an expander renders its body whether open or shut — so nothing about their session-state persistence changes.
* **Node positions never drift.** The default view draws every node and edge fully lit; hover/selection only changes brightness, never coordinates, so clicking a node cannot appear to reshuffle the map.

### Side panel (neural renderer)

**The panel is collapsed by default** (`explorer_panel_open`, default `False`): the map is what this view is for, so
it keeps the width until the reader or the health view is asked for. Collapsed, the right column is a `«` rail
(`st.columns([12, 1])`); open, it is `st.columns([3, 1])` with a `»` at the top of the panel. Streamlit has no drawer
widget — the "drawer" *is* the column ratio, re-picked each run from that flag.

Double-clicking a node opens the panel with it. Because the widths for a run are fixed **before** the component
renders, that path sets the flag and `st.rerun()`s (the payload is cached, so the extra run is cheap); the
already-open case renders in the same run. A source-node double click reports through `st.toast()`, not the panel —
the collapsed rail is too narrow to read a message in.

`_render_explorer_panel()` then has exactly two states, so the open panel is never empty:

* **A page is open** (`explorer_selected_page`) → the reader: title, `✕` back button, the page body inside a fixed-height `st.container(height=560)` scroll region beside the canvas, a download button, and the Sources expander (originals via `_raw_source_button`, related pages as buttons that re-target the panel).
* **Nothing open** → the **health view** (`_render_graph_health()`): Pages / Orphans / Stale metrics, the top clusters ranked by growth (`+N` = pages updated inside `graph_export.HEALTH_WINDOW_DAYS`, 30), and expanders listing orphaned / stale / low-confidence pages whose entries open in the reader.

Two rules behind this:

* **No modal.** A page opened from the graph must render *beside* it, not over it — `st.dialog` hides the map the node was clicked on, which defeats reading the two together. `_show_md_dialog()` remains for the Tree view and the chat/research source lists, where there is no map to occlude.
* **The health view reads the drawn payload, never the wiki again.** `graph_widget.graph_health()` → `graph_export.health()` consumes the flags already stamped into the cached payload (`orphan` / `stale` / `confidence` / `comm`), so the panel's counts and the canvas's overlays cannot drift apart, and the panel costs no extra graph build. Clusters are labelled by their highest-PageRank *page*, and counts exclude source nodes — a raw document has no health of its own.

Click handling sits **between** the two columns (`with graph_col:` … process click … `with panel_col:`), which is what lets an open panel render the just-opened page on the same run.

## Error states (UI surface)

Connectivity and config errors must be visible, not silent (PRD §4.2): Ollama down → error surfaced at point of use (chat/research/conversion) with an `ollama serve` hint; missing model → `ollama pull gemma4:e4b`; converting a non-Markdown upload while Ollama is unreachable → error with `ollama pull deepseek-ocr:3b` hint (ingest blocked until conversion succeeds); missing `TAVILY_API_KEY` → Research page disabled with setup steps; partial PDF extraction → `Partial extraction: N pages read`.

**Ontology in search results** (DBs with an ontology): Explorer search shows a caption line "Ontology — “…” → `work`; n source(s) favoured"; Deep chat and Research traces show an *Ontology frame* expander; *Why these sources* lists the ontology frames of the answer. See [ontology.md](ontology.md) §Search. The graph's **Outdated** overlay (dashed ring) and the health panel's *Outdated* list mark pages built only on superseded versions; document captions under chat answers say which version is in force ([ontology.md](ontology.md) §Time). The graph's **Pyramid** layout rows documents by the rank of their ontology class and draws relations as arrows; Maintenance → Ontology has a *Lint* view ([ontology.md](ontology.md) §Relations). The Ontology section also has *Edit* (tables), *Cues* (cue tester and re-classify) and, under *Proposals*, model-suggested classes; the Overview offers SKOS and JSON-LD downloads ([ontology.md](ontology.md) §Evolution). *Proposals* can also send concept pages to the model for a class ([ontology.md](ontology.md) §Pages).
