# Plan: Broadsheet 2 GUI (NiceGUI) alongside the Streamlit app

## Context

`ideas/gui-redesign/` (merged in 734615f) holds five static mockups (Front page, Explorer, Chat,
Research, Upload), a shared `broadsheet.css`, and `notes.md` with a NiceGUI mapping. The goal is to
build that design as a **second frontend in NiceGUI**, keep the existing Streamlit app
(`src/app.py`) working and untouched in behaviour, and choose between them with one config value.
The new GUI becomes the default once it reaches parity.

Decisions already taken with the user:
- **Framework:** NiceGUI (MIT). Streamlit stays as a dependency.
- **Async:** a scoped waiver. `async def` is allowed only in the new `gui_*.py` modules and their
  tests; all domain logic stays sync.
- **Config:** extend `FRONTEND`. `FRONTEND=broadsheet` selects NiceGUI; `default` and `newspaper`
  keep today's Streamlit skins. One launcher starts the right server on port 8520 under `/wiwi`.
- **Maintenance and Admin:** ported as they are, restyled with broadsheet components. Maintenance is
  a sixth nav item; Admin lives in the user menu.
- **Implementation model:** Sonnet (medium effort). Every phase below is one self-contained Sonnet
  session with its own red → green → gate → docs → commit (AGENTS.md §5.6).

## Deviations found while building

- Phase 0: pages are plain `ui.page` routes (each wrapped by `gui_session.guard`), not `ui.sub_pages`.
- Phase 2: `Session` objects live in a process-level registry keyed by the opaque `sid` in `storage.user` (a
  per-page-load store would lose chat history on every navigation). `PERSISTED_KEYS` is `user`, `active_db`, `sid`.
  `Session.shard`/`scope` hold the level a page reads; `seal()` re-binds them and falls back to the normal level when
  the bound one was revoked. Reset unloads the model and signs out, as the Streamlit button clears the session.

- Phase 3: margin notes are numbered per file and section without the mockup's "Also cited" merge, and show no quotes
  (the backend returns none); uncited sources go in an "Also read" fold. `guard` resets `shard` and `scope` at every
  page build, so Chat's widened scope never reaches the next page.

- Phase 4: the map always uses the neural renderer on the paper palette (`GRAPH_RENDERER` applies to Streamlit only);
  the index is a Map/Index toggle in the bar rather than a left drawer; all six overlays are checkboxes; with nothing
  selected the reader column shows the bundle health (Map) or the overview (Index). The iframe handshake and the
  double-click event need a real browser to verify: unit tests cover `graph_click` and the shim's source text.

- Phase 5: the timeline stamps each step with its arrival time; "Pages consulted" (URLs not cited in the report) is a
  fold; the follow-up is a fold in the side column. The wiki-context paste of the Streamlit page is not ported: the
  agent browses the wiki on its own and Deep ignores it.

- Phase 6: files that are already ingested are skipped and named above the table, not shown as a "Duplicate" column;
  the review table is a CSS grid of inputs rather than `ui.table`; the uploader is Quasar's (`ui.upload`, batch mode).

- Phase 7a: Admin is its own `/admin` page (not a Maintenance section); the user allow-list editor shows a clearance
  select for every database and reveals the ones the user is allowed in. `Session.bind_shard` is shared by Explorer and
  Maintenance. The Ontology section is a placeholder until 7b.

- Phase 7b: the Edit view is rows of inputs with an explicit Preview step (Streamlit previewed on every edit); read-only
  tables are CSS grids of labels, as the test harness cannot read `ui.table` cells. The Streamlit helpers the port
  reuses became public in `ontology_ui.py`.

## Architecture (fixed; Sonnet must not re-decide)

### Files (flat `src/`, per AGENTS.md §5.2)

| File | Role |
|---|---|
| `scripts/run_app.py` | Launcher. Loads `.env` and reads `FRONTEND`. `broadsheet` runs `python src/gui_app.py --port 8520`; anything else runs `streamlit run src/app.py --server.port 8520 --server.headless true`. Uses `os.execvp`, so the PID is the server's own PID. Takes `--port` (default 8520). |
| `src/gui_app.py` | Entry point. `load_dotenv()` first (add an E402 per-file ignore like app.py). Bootstrap once: `db_context.migrate_legacy_layout()`, `auth.ensure_seeded()`, `auth.backfill_maintainers()`, `import audit`. `root()` builds the page shell plus `ui.sub_pages`. `main()` creates a FastAPI app, registers `GET /wiwi/_api/gpu`, calls `ui.run_with(fastapi_app, mount_path="/wiwi", root=root, storage_secret=…)`, and runs uvicorn on `--port`. |
| `src/gui_session.py` | The only GUI module that calls `db_context.seal_clearance`. Provides `Session` (per-client, in memory), `guarded` (decorator), `in_worker` (context-bound threads), `stream_steps` (generator to UI queue), `login`/`logout`, and the grant-shrink purge. |
| `src/gui_chrome.py` | Running head (plate, nav, edition = DB picker, classification stamp, user menu with Reset, Logout and Admin), folio (model, GPU, index health), shared components (`fold`, `toggle`, `agate_table`, `btn`, `page_title`). |
| `src/gui_cite.py` | **Pure.** Turns `[Source: file §x]` tags into numbered `<sup class="cite" data-n>` plus an ordered note list (dedup by file+section, "Also cited" merges). No UI imports. |
| `src/gui_front.py` | Front page. |
| `src/gui_explorer.py` | Map, standings table, reader, tree and search, level picker. |
| `src/gui_graph.py` | Iframe host for `src/assets/graph/index.html` plus the postMessage shim. |
| `src/gui_chat.py`, `src/gui_research.py`, `src/gui_upload.py` | One page each. |
| `src/gui_maint.py`, `src/gui_admin.py`, `src/gui_ontology.py` | Maintenance sections, Admin, and the ontology workbench (port of `ontology_ui.render`). |
| `src/ui_logic.py` | **UI-agnostic** logic extracted from `app.py` (Phase 1). Both GUIs import it. No `streamlit` or `nicegui` import. |
| `src/assets/broadsheet/broadsheet.css` | Copied from `ideas/gui-redesign/src/broadsheet.css`. Drop the mockup-only `body { width:1600px; height:1000px; overflow:hidden }`, then add Quasar overrides (square corners, no shadows, fonts). |

### Invariants (every phase)

1. **Sealing before every data access.** Clearance, active DB and scope are ContextVars. Every page
   builder, event handler and `ui.timer` callback is wrapped in `gui_session.guarded`, which
   re-runs, in order, `seal_clearance(auth.clearance_map(user), user)`, the purge check,
   `set_active_db(session.active_db)` and `set_search_scope(session.scope)`. This is the
   NiceGUI equivalent of app.py:1164-1176.
2. **Worker threads use `bind_context`.** `run.io_bound` uses `run_in_executor`, which does not
   copy ContextVars, so always call `await run.io_bound(db_context.bind_context(fn), …)` through
   `gui_session.in_worker`. A generator from an agent is consumed and audited in the **same**
   worker (`tools.current_run_audit()` and `retrieval.last_frame()` read that thread's context).
   `stream_steps` does this: the worker pushes steps into a `queue.Queue` and returns the audit;
   the UI drains the queue every 0.1 s.
3. **Nothing document-derived is persisted by NiceGUI.** `app.storage.user` (written to
   `.nicegui/` on disk) may only hold `{"user", "active_db"}`. Everything else (messages, reports,
   upload batches) lives in the in-memory `Session` object. `gui_session.PERSISTED_KEYS` holds that
   allowlist, and a test enforces it. Add `.nicegui/` to `.gitignore`.
4. **A denied DB behaves exactly like a missing one.** Web tools stay off while a classified level
   is in scope. Writes go through `db_context.write_target`. These are the same rules as the
   Streamlit app; reuse its code paths through `ui_logic` and don't re-implement them.
5. **Rules from AGENTS.md:** functions ≤ 50 lines, complexity ≤ 10, pyright strict, all prompts in
   `prompts.py` (the GUI adds none), no LangChain outside the agent layer, never touch non-KI
   `data/`.

## Phases (each is one Sonnet session; commit at the end of each)

### Phase 0: PRD, dependencies, harness spike (gate: everything below works)
1. **PRD and docs (the user approved this plan, so the PRD change is approved):**
   - `PRD.md`: add **M8 — Broadsheet GUI**. Deliverable: a NiceGUI frontend, selected by
     `FRONTEND=broadsheet`, at parity with M4. Acceptance: every M4 criterion, plus the front page,
     numbered citations, and the classification stamp.
   - `IMPLEMENTATION.md` phase table: row 8, `in progress`.
   - Copy this plan to `docs/_plan-gui-broadsheet.md` (≤ 800 lines).
2. **AGENTS.md §5.3:**
   - Add one bullet: *Async is also permitted in `src/gui_*.py` and `tests/test_gui_*.py`; domain
     modules stay sync.*
   - Extend the run line: `uv run python scripts/run_app.py` (reads `FRONTEND`); the direct
     Streamlit command stays valid.
   - Keep AGENTS.md ≤ 200 lines.
3. **Dependencies:**
   - `uv add nicegui` (≥ 3.x) and `uv add --dev pytest-asyncio`.
   - Check both licences (MIT and Apache-2.0) and record NiceGUI in THIRD_PARTY_NOTICES.md only if
     code is copied (it isn't; it is a dependency).
4. **Harness spike** (write it as `tests/test_gui_app.py`, a login-page smoke test):
   - Register `pytest_plugins = ["nicegui.testing.user_plugin"]` and whatever ini keys it needs in
     `pyproject.toml`. `--strict-config` is on, so only use keys the plugin registers.
   - Set `asyncio_mode = "auto"` if needed.
   - Confirm that the `User` fixture works with `tests/conftest.py`'s socket block (ASGITransport
     makes no `connect`).
   - Confirm the suite stays ≤ 60 s under `-n auto`.
   - If the plugin needs `main_file`, point it at `src/gui_app.py` with `root()` and no mount.
     Tests never use `/wiwi`.
5. **Mount spike:** `uv run python scripts/run_app.py` with `FRONTEND=broadsheet`, then:
   - `curl -s -o /dev/null -w '%{http_code}' http://localhost:8520/wiwi/` returns 200.
   - The browser at `http://localhost:8520/wiwi/` shows the login and the websocket connects (no
     reconnect banner).
   - Ask the user to check `https://ai.brenk.com/wiwi/` (nginx passes the prefix through, as it
     does for Streamlit's `baseUrlPath`).
   - If the websocket fails behind the prefix, stop and report. Don't change nginx.
6. **Security rule:** in `tests/test_security_rules.py`, set
   `ONLY_IN["seal_clearance"] = {"app.py", "gui_session.py"}`. First add a test showing that
   `gui_chat.py` calling `seal_clearance` is a violation (red), then widen the set (green).
7. **Config:**
   - Add `FRONTEND` value `broadsheet` and `GUI_STORAGE_SECRET` to `docs/configuration.md` and
     `.env.example`. If the secret is unset, use `secrets.token_urlsafe()` per process, so logins
     drop on restart.
   - `theme.py`: treat `broadsheet` like `default` (Streamlit never runs with it through the
     launcher). This is a one-line docstring note, with no code change if unknown values already
     fall back.

### Phase 1: Extract shared logic into `src/ui_logic.py` (behaviour-preserving)
Refactor rule: run `tests/test_app.py` green before the change, and green after it, unchanged.
Add direct unit tests in `tests/test_ui_logic.py` for every new parameter.

| From `app.py` | To `ui_logic` | Change |
|---|---|---|
| `_CHUNK_SUFFIX_RE`, `_CITE_SECTION_SUFFIX_RE`, `_NAV_GROUPS`, `_GRAPH_LAYOUTS`, `_OVERLAY_LABELS`, `_OVERLAY_HELP`, `_RESOLVE_HELP`, `_CONTENT_KEYS` | public constants | none |
| `_ontology_line`, `_level_name`, `_level_key_label`, `_shard_ref`, `_report_ref` | same, public | none |
| `_visible_duplicate(data)` | `visible_duplicate(data, active_db)` | pass the DB in |
| `_ingest_file`, `_ingest_level` | `ingest_file`, `ingest_level(…, on_file: Callable[[str], None])` | the spinner becomes a callback |
| `_resolve_by_shard(desc, refs, guidance)` | `resolve_by_shard(desc, refs, guidance, active_db)` | pass the DB in |
| `_convert_progress` | `convert_progress(on_progress: Callable[[float, str], None], …)` | callback |
| `_safe_reset` (pure part) | `unload_model()` | POST `keep_alive:0` to `ollama_client.host()`, then `gc.collect()` |
| `_purge_if_downgraded` (pure part) | `grants_shrank(before, after) -> bool` | none |
| `_raw_source_button` (logic) | `resolve_raw_source(ref) -> tuple[str, bytes \| None]` | `split_ref` → strip suffixes → `using_db` → `read_raw_source` |
| Chat send (1862-1939) | `answer_fast(q) -> dict` | also `save_answer(q, msg, active_db) -> str` (the `write_target` + `file_answer` path) |
| `_finish_research`, the save branch | `load_report(path, active_db)`, `save_research(ans, title, as_source, active_db) -> dict` | none |

In `app.py`, the old private names become thin calls into `ui_logic`, or are replaced at their
call sites. Don't move renderers. `gpu_widget`: add a public `gpu_payload() -> dict` wrapping
`_build_payload()`. `graph_widget`: add `render_args(overlays, size_by, layout, paper, selected)
-> dict`, the args dict `render_graph` already builds; `render_graph` then uses it.

### Phase 2: Session, chrome, CSS, login, empty pages
- **`gui_session`:**
  - `Session` dataclass: `user`, `active_db`, `scope`, `grants`, and per-page state dicts. Store it
    per client in `app.storage.client`, created at root build.
  - `guarded`, `in_worker`, `stream_steps`.
  - `login(u, p)`: `auth.verify` → `auth.user_dbs`. Empty → error. Otherwise store the user and
    `active_db = dbs[0]`.
  - `logout()` clears the Session and `storage.user`.
  - Purge: if `grants_shrank(old, new)`, clear the page-state dicts (the NiceGUI equivalent of
    `_CONTENT_KEYS`).
- **Login page:** a centered plate, username and password fields, one primary button. No
  sub_pages until signed in.
- **Running head, following `ideas/gui-redesign/src/*.html`:**
  - Plate "LocalWiki", using the Bodoni opsz-11 rule from `notes.md`.
  - Nav: Front page · Explorer · Chat · Research · Upload (maintainers only) · Maintenance.
  - Edition: DB `ui.select` from `auth.user_dbs`. On change, set `active_db`, clear the page
    state, and navigate to the current route.
  - Stamp: level of the active shard (`plain` / `.conf` violet / `.strict` reversed).
  - User menu: Reset (`ui_logic.unload_model` then clear the Session), Admin (if
    `auth.is_admin`), Logout.
- **Folio:**
  - Model and pinning: `ollama_server.status()`, `ollama_client.MODEL`.
  - GPU: `ui.timer(2.0)` → `in_worker(gpu_widget.gpu_payload)`. Hidden if there are no GPUs.
  - Index health: `lex_index.index_health()`.
  - Static text "Open Knowledge Format v0.1".
- **FastAPI `/wiwi/_api/gpu`:** returns `gpu_widget.gpu_payload()`, so external scripts that use the
  Streamlit route keep working.
- **Tests (User fixture; stub `ollama_server.status`, `gpu_widget.gpu_payload` and
  `lex_index.index_health` like `test_app.py` does):**
  - Login ok and bad.
  - User with no DBs.
  - Nav hides Upload for a non-maintainer.
  - DB switch.
  - Stamp text per level.
  - `PERSISTED_KEYS` guard: a test writes a disallowed key and expects the helper to raise.
  - **Two-client isolation canary:** `create_user` twice, a strict-cleared and a normal-cleared
    user interleave actions, and the normal user never sees the strict canary. Mirror
    `tests/test_classification_leaks.py` fixtures and use `data/KI`-style tmp roots via
    `db_context.DATA_ROOT` monkeypatching, as `test_app.py` does.

### Phase 3: Chat (mockup `03-chat.html`)
- **Layout:** a 3-column grid. Rail: Fast/Deep toggle, "Search in" checkboxes, conversation
  history, New conversation. Centre: a 66ch column with the answer. Right: the Sources note column.
- **"Search in":** one checkbox per reachable shard across `auth.user_dbs` (label from
  `classification.label`). Default: all levels of the active DB. Set the scope with
  `set_search_scope`. If the scope spans more than one DB, show a caption naming the DBs.
- **Fast:**
  - `in_worker(ui_logic.answer_fast, q)`.
  - Deep: `stream_steps(chat_agent.run_chat_agent, q)`, rendering step types `thought`,
    `tool_call`, `tool_result`, `ontology` and `error` into the "How this answer was made" fold
    (`ui.expansion`).
  - `final_answer` becomes the answer.
- **Citations:** `gui_cite.number_citations(answer)` produces the prose (`ui.markdown` with
  `extras`, sanitized) plus notes. Each note shows the file (mono), the section, and
  `ontology_ui.source_badge(ref)`. It shows **no invented quotes**: only text present in the
  step or source data. Hover linking: a small `ui.add_body_html` script that toggles `.hl` on the
  `sup.cite[data-n]` and `.note[data-n]` pairs.
- **Actions:**
  - Save to wiki (maintainers): `ui_logic.save_answer`. Its tooltip names the target level;
    `AccessDenied` becomes a note.
  - Download (`ui.download`).
  - Copy with citations (clipboard with the raw `[Source: …]` text).
  - Follow-up: the next question goes through `wiki_engine.condense_followup(prev_q, prev_a, q)`.
  - "Why these sources" fold: port `_render_why_sources` (kept, below τ, over cap, ontology frame).
- **Empty index:** use `lex_index.index_health()` for the warning (AGENTS.md hard rule).
- **Tests:**
  - `tests/test_gui_cite.py` (pure; red first): numbering, dedup, "Also cited", no tags, and
    `DB::file.md` refs.
  - `tests/test_gui_chat.py`: Fast answer rendered, Deep trace, follow-up condensed, save at the
    high-water level, non-maintainer sees no Save, and empty-index warning.

### Phase 4: Explorer (mockup `02-explorer.html`)
- **`gui_graph`:**
  - Serve `src/assets/graph/` with `app.add_static_files('/graph-assets', …)`. Embed it as an
    `<iframe>`.
  - A host shim in the parent page does two things:
    - It answers the iframe's `streamlit:componentReady` with
      `{type:"streamlit:render", args: graph_widget.render_args(…, paper=True) + {accent:"#8f2d1a"}}`.
    - It forwards `streamlit:setComponentValue` (`{node, kind, n}`, sent on double-click) via
      `emitEvent('graph_open', value)` → `ui.on('graph_open', guarded(handler))`.
  - Do **not** edit `index.html`.
  - The graph data comes from `graph_widget.graph_stats()`. It reuses the per-level cache that
    `test_classification_leaks.py` covers, so don't add a second cache.
- **Layout:**
  - Left: the map with layout toggle (Galaxy/Ranked/Clusters/Pyramid) and overlays (the
    Advanced fold).
  - Below the map: a standings table (top pages by degree from the payload).
  - Right: the reader as an article (`wiki_engine.read_page_parsed`, with Sources and Related
    folds; raw sources open in a `ui.dialog` via `ui_logic.resolve_raw_source`).
  - Nothing selected: `graph_widget.graph_health()` figures.
  - Index drawer (`ui.left_drawer`, toggled): tree via `wiki_engine.get_wiki_tree()` grouped by
    `ui_logic.NAV_GROUPS`, plus search via `wiki_engine.search_wiki` with
    `retrieval.last_frame()` → `ui_logic.ontology_line`.
  - Level picker when more than one shard is reachable (the `_level_picker` logic: `set_active_db`
    + `set_search_scope([shard])`).
  - Empty wiki: onboarding text.
- **Tests:** select a page (emit the event directly), search hit, empty-index warning, level
  switch changes the page list, empty wiki.

### Phase 5: Research (mockup `04-research.html`)
- **Page gates:**
  - `TAVILY_API_KEY` missing → notice, and the buttons are disabled with a reason ("dashed but
    readable").
  - Quick/Deep toggle.
  - "Include classified levels (web search off)" appears when more than one shard is reachable;
    locked after a classified run until New research; forces Quick.
- **Run:**
  - `stream_steps(agent.run_research_agent | deep_research_agent.run_deep_research, q, ctx)`.
  - `research_level = max(prev, classification.high_water(search_scope()))`.
  - A `notice` step (Deep falling back to Quick) renders as a warning line.
- **Output as a feature article:**
  - Figures box for metrics: Sub-tasks, Web searches, Sources checked only if it differs,
    Sources cited.
  - Report prose with `gui_cite`.
  - Timeline of the trace (the step list; `ResearchComplete` shows as a success line, never
    `— {}`).
  - URL cards de-duplicated by URL.
  - Download report.
  - Save (maintainers) with "Register as a source document" via `ui_logic.save_research`; a
    duplicate shows a notice.
  - Follow-up field below the report (`condense_followup`).
  - Wiki-context paste fold (label says Deep ignores it).
- **Tests:** Quick run, Deep run with metrics, fallback notice, classified opt-in disables Deep
  and web, missing key, save as source.

### Phase 6: Upload (mockup `05-upload.html`, maintainers only)
- **Phase A, prepare:**
  - `ui.upload(multiple=True, auto_upload=True)` collects bytes. Check the NiceGUI 3 upload event
    API in the docs first.
  - Skip duplicates with `ui_logic.visible_duplicate`.
  - Convertibles: if `ollama_client.is_available()` is false, show an error. Otherwise
    `in_worker(md_convert.convert_to_markdown, …)` with a progress bar fed through a queue.
  - `metadata_extract.extract_effective_date`, `ontology_ui.upload_schema/detected`.
- **Phase B, one review table** (a `ui.grid` of inputs per file):
  - Columns: File (mono) · Effective as of · Level (select, **no default**, capped at the
    uploader's grant) · Class · Work · Other versions (read-only) · Duplicate.
  - An editable Markdown preview when a single file was converted.
  - Shared "part of" and description.
  - Button: disabled with the reason taken from `classification.plan_upload(...).missing/.denied`.
- **Phase C, ingest:**
  - `in_worker(ui_logic.ingest_level, …)` per level, oldest date first, with the per-file status
    callback marshalled through a queue.
  - Summary: Created / Updated / Contradictions, new pages, failures, and ignored ontology values.
- **Resolve contradictions:**
  - Titles set as sentences.
  - Per item: a pages multiselect plus guidance, then Reconcile, which calls
    `ui_logic.resolve_by_shard`.
  - Dismiss.
- **Tests:** non-maintainer has no route, duplicate skipped, missing level blocks with a reason,
  ingest calls `ingest_begin/piece/end` per level (stub `wiki_engine`), contradictions resolve.

### Phase 7a: Maintenance and Admin
- **Maintenance page:**
  - Section toggle (`ui.toggle`, the same sections as today's `maint_view`), with the level picker
    and stats line on top.
  - **Search index:** health table, Rebuild (maintainer) → `wiki_engine.rebuild_lex_index()`.
  - **Delete source:** a select, an irreversibility note and a confirm checkbox →
    `wiki_engine.delete_source`. Below it, Move → `wiki_engine.move_source`.
  - **Link graph:** `find_orphans`.
  - **Lint:** `wiki_engine.lint()`, run in a worker.
  - **Page language:** dry-run table, then Normalize N.
  - **Activity log:** `read_log()`.
  - **Ontology:** Phase 7b.
- **Admin (`auth.is_admin`):**
  - Databases: `db_context.list_dbs`, and `create_db` + `auth.grant_maintainer`.
  - Users: port app.py 2300-2437. Edit DBs, maintains, clearance per DB, password; delete (never
    yourself); add a user.
  - `audit.recent()` table.
- **Tests:** one per section plus the admin guards (a non-admin gets no route; you cannot delete
  yourself).

### Phase 7b: Ontology workbench (`gui_ontology.py`)
- Port `ontology_ui.render` view by view: Overview, Classes, Facts, Edit, Proposals, Cues, Lint,
  History, Import.
- Reuse the pure helpers in `ontology_ui.py` (`_bullets`, `_when`, `_fmt`, `_change_line`,
  `_class_usage`, `_class_line`, `review_rows`, `source_badge`). Make the ones you need public
  there, in a surgical rename with call sites updated.
- Every write goes through the same `ontology_store.prepare_*` → `wiki_engine.apply_ontology` /
  `_apply` path. Catch `StaleRevisionError`/`PermissionError` → notice.
- **Tests:** create, import preview + apply, confirm a proposal, cue tester, restore; mirror the
  ontology tests in `test_app.py`.

### Phase 8: Front page (mockup `01-front-page.html`)
- The full nameplate (only here).
- Recent activity: the last N entries of `wiki_engine.read_log()`.
- Most connected page: the top degree node from `graph_widget.graph_stats()`, linking to Explorer.
- "Ask the archive": the input navigates to `/chat` with the question queued in the Session and
  runs it in Fast mode.
- Figures from `graph_widget.graph_health()`: pages, orphans, stale, outdated, low confidence,
  clusters.
- Empty wiki: onboarding text.
- **Tests:** renders the figures, ask routes to chat, empty wiki.

### Phase 9: Cutover and docs
- The code default of `FRONTEND` in `scripts/run_app.py` becomes `broadsheet`. `.env.example`
  and `docs/configuration.md` follow.
- `tunnel.sh` and `.claude/skills/restart-app/scripts/restart_app.sh`:
  - Launch with `uv run python scripts/run_app.py --port "$PORT"`.
  - Change `APP_PATTERN` to a regex matching both servers:
    `src/(app|gui_app)\.py.*port $PORT`.
  - Keep SIGTERM to the app's own PID first (user rule).
  - Update the SKILL.md wording.
- **Safe exit button** (user's global Streamlit rule, applied here too): the user menu gets
  "Stop server" for admins only. It calls `app.shutdown()`, which ends the app's own process; never
  kill by port.
- **Docs:**
  - `docs/ui.md`: a new section "Broadsheet frontend (NiceGUI)" covering the chrome, the sealing
    invariant, the storage rule, the graph shim and citations. Mark the Streamlit-only chrome
    facts as such.
  - `IMPLEMENTATION.md`: run table, module map rows for `gui_*.py` and `ui_logic.py`, and phase 8
    `done`.
  - README quickstart and `docs/changelog.md`.
  - Add a hard rule to AGENTS.md §5.3: *GUI handlers must be `gui_session.guarded`; worker calls go
    through `gui_session.in_worker`; `app.storage.user` holds only `PERSISTED_KEYS`.*
  - Run `/documentation-update`.
- **Manual parity walk-through** (the user, in a browser at `http://localhost:8520/wiwi/` and via
  the proxy), against the checklist in the appendix.

## Execution protocol for Sonnet (paste at the top of each phase session)

- Read `AGENTS.md`, `IMPLEMENTATION.md` and `docs/_plan-gui-broadsheet.md` (this plan), then only
  the files that phase names. Look up the NiceGUI 3 API through context7
  (`/zauberzeug/nicegui`) before using an element you haven't used in this repo yet.
- Red → green: write the phase's tests first, run them, and see them fail for the expected reason.
- Gate: `uv run pre-commit run --all-files`. Coverage must stay ≥ 85 % and the suite ≤ 60 s.
- Never read or write `data/` outside `data/KI`. Tests use tmp roots.
- Don't change `src/app.py` behaviour. `tests/test_app.py` must pass unchanged, except for
  Phase 1's thin-wrapper edits.
- Stop and report instead of guessing if a NiceGUI mechanism doesn't work as planned: the mount
  under `/wiwi`, the User fixture, ContextVar isolation, or the iframe postMessage shim.
- Finish with `/documentation-update` and `/commit-git`. Report the red and green results. Don't
  push.

## Verification (end to end)

1. `uv run pre-commit run --all-files` is green after every phase.
2. `FRONTEND=broadsheet uv run python scripts/run_app.py`: then
   `http://localhost:8520/wiwi/` → log in as a KI user and walk every page. The folio shows the
   model and GPU. `/wiwi/_api/gpu` returns JSON.
3. `FRONTEND=newspaper uv run python scripts/run_app.py`: the Streamlit app starts as before on the
   same URL.
4. Security: a normal-cleared user on KI never sees `KI@strict` content (the canary test, plus a
   manual check with two browser profiles).
5. `./tunnel.sh` and the restart-app skill start, stop and restart both frontends.
6. Nothing under `.nicegui/` contains document text: `grep` it for a known page title after a chat
   session.

## Appendix: parity checklist (from today's Streamlit app)

- **Session:** login and logout; no-DB user; DB switch clears content; grant downgrade purges
  content; reset unloads the model; maintainer vs reader vs admin gating.
- **Upload:** md/pdf/docx/images; duplicate status; conversion progress plus an editable preview;
  effective date; ontology class, work and other versions; per-file level, required and capped;
  per-level ingest, oldest first; summary; contradictions resolve and dismiss; never auto-ingest.
- **Explorer:** level picker; graph layouts and overlays; double-click opens the reader; tree by
  type; search with excerpt and ontology line; reader with Sources, Related and raw-source dialog;
  download; description when nothing is selected; health figures; onboarding.
- **Chat:** Fast and Deep; multi-DB and multi-level scope with its caption; follow-up condensation;
  Deep trace; why-sources; Save at the high-water level (maintainers); download; empty-index
  warning.
- **Research:** Tavily gate; Quick and Deep; classified opt-in (web off, Deep off, locked);
  fallback notice; metrics; URL cards; trace replay; save and register-as-source; follow-up;
  download.
- **Maintenance:** index health and rebuild; delete and move source; orphans; lint; page language;
  ontology workbench (all views); activity log.
- **Admin:** DBs, users, clearance, passwords, audit log.
