# IMPLEMENTATION.md

State-of-implementation reference for **LocalWiki** — a local, Python-based, Karpathy-style self-compiling knowledge wiki driven by Ollama.

> **Authoritative spec:** [`PRD.md`](PRD.md). This file is a navigation map and current-status tracker. Must stay under 500 lines (CLAUDE.md §5.1).

---

## 1. Status

| Area | State |
|---|---|
| Repository | Initialised; remote `ToHeinAC/KB_BS_local-wiki-he` |
| Documentation skeleton | Complete |
| `pyproject.toml` / `uv.lock` | **Done** |
| `.env.example` | **Done** |
| `SCHEMA.md` | **Done** |
| `src/dedup.py` | **Done** |
| `src/file_processor.py` | **Done** |
| `src/md_convert.py` | **Done** |
| `src/schema_loader.py` | **Done** |
| `src/ollama_client.py` | **Done** |
| `src/wiki_engine.py` | **Done** |
| `src/app.py` (Streamlit, port 8520) | **Done** |
| `src/prompts.py` | **Done** |
| `src/tools.py` | **Done** |
| `src/agent.py` | **Done** |
| `src/template_loader.py` | **Done** |
| `src/chunker.py` | **Done** |
| `src/lex_index.py` | **Done** |
| `src/qa_gen.py` | **Done** |
| `src/run_memory.py` | **Done** |
| `src/db_context.py` (multi-DB path resolution) | **Done** |
| `src/auth.py` (users + bcrypt) | **Done** |
| `src/lang.py` (DE/EN detection + language directives) | **Done** |
| `src/metadata_extract.py` (regex effective-date detection) | **Done** |
| Test suite | **Done** (≈258 tests; 100-cap superseded — see §5 and [`docs/tests.md`](docs/tests.md)) |
| `.streamlit/config.toml` | **Done** |
| `tunnel.sh` (Cloudflare quick tunnel) | **Done** |

All planned modules implemented plus a retrieval layer: chunk store + BM25 lexical index + hypothetical-question chunks (1–5 per source). The earlier extractor (aliases/acronyms/terms/facts) and the trigram fuzzy-fallback were removed on 2026-05-16 as load-zero — they were emitted at ingest cost but did not improve answer quality.

---

## 2. Documentation Map

| Topic | File | PRD reference |
|---|---|---|
| Original product spec | [`PRD.md`](PRD.md) | (canonical) |
| Behavioural / process rules | [`CLAUDE.md`](CLAUDE.md) | — |
| Architecture (3-layer model, dataflows) | [`docs/architecture.md`](docs/architecture.md) | §2, §7 |
| Domain & rationale | [`docs/domain.md`](docs/domain.md) | §1, §10 |
| Tech stack & environment | [`docs/tech.md`](docs/tech.md) | §2.3, §4.4, §5 |
| UI design & pages | [`docs/ui.md`](docs/ui.md) | §2.4, §3.9 |
| Wiki / SCHEMA / storage | [`docs/wiki.md`](docs/wiki.md) | §2.1, §3.5, §6 |
| Open Knowledge Format (OKF v0.1) alignment | [`docs/okf.md`](docs/okf.md) | — |
| Testing strategy | [`docs/tests.md`](docs/tests.md) | §4.5 |
| Open issues | [`docs/openissues.md`](docs/openissues.md) | — |
| Dated change log | [`docs/changelog.md`](docs/changelog.md) | — |
| Critical analysis & roadmap (historical review, not current guidance) | `docs/LocalWiki Implementation — Critical Analysis & Improvement Roadmap.md` | — |

---

## 3. Module Inventory

All Python modules live under `src/`. Entry point: `uv run streamlit run src/app.py --server.port 8520`.

| Module | Purpose | Status |
|---|---|---|
| `src/dedup.py` | SHA-256 dedup; flat `data/raw/` store + `manifest.json`. `list_sources()` / `deregister_source()` support cascading deletion. | Done |
| `src/file_processor.py` | Extract text from PDF/DOCX/MD/TXT/HTML; `chunk_text()` splits large docs at paragraph boundaries | Done |
| `src/md_convert.py` | Convert non-Markdown uploads (PDF/DOCX/images) to Markdown before ingest. Ported from [ToHeinAC/MD-maker](https://github.com/ToHeinAC/MD-maker) (Apache-2.0): per-page PDF routing (digital text → LLM rewrite, scanned/image → vision OCR), deterministic DOCX→MD, image OCR. `convert_to_markdown()` + `is_convertible()`; Ollama via `ollama_client.ocr()/.rewrite()`. Env: `OCR_MODEL`, `REWRITE_MODEL`, `PDF_DPI`. | Done |
| `src/chunker.py` | Structural chunker: legal `§` / markdown headings / paragraph windows with overlap. Content-addressable `chunk_id`. Persists to `data/chunks/<source-slug>.jsonl`. | Done |
| `src/lex_index.py` | BM25 lexical index over chunks. 4 normalized token variants (surface / NFKD / umlaut-digraph / stem). Persists `postings.json` + `stats.json` to `data/index/`. Scoped (R-1): `build()` indexes raw chunks (`scope="raw"`) + wiki page bodies (`scope="wiki"`, via `_wiki_chunks()`, text inline in meta); `query(q, top_k, scope=None)` filters by scope. | Done |
| `src/qa_gen.py` | Ingest-time HyDE. `_select_target_chunks` picks the top-`QA_MAX_PAIRS_PER_SOURCE` heading-anchored, densest chunks; one batched LLM call asks for 2–4 questions each; output sliced to the cap. Guarantees ≥1 question per source via retry + title fallback. Persists to `data/index/qa.jsonl`. Folded into BM25 by `lex_index.build()`. `delete_source_entries(name)` rewrites the file in place. | Done |
| `src/ollama_client.py` | `generate(…, model_id=None)` + `chat()` wrappers; `is_available()` health check; `ocr()` (vision) + `rewrite()` (per-call model id) for `md_convert`. Per-role model overrides `_QUERY_MODEL`/`_INGEST_MODEL`/`_FAST_MODEL` (each falls back to `OLLAMA_MODEL`). | Done |
| `src/schema_loader.py` | `get_system_prompt(mode="full"\|"query")` — `full` reads `SCHEMA.md` (page templates, for ingest + page-writing); `query` reads trimmed `SCHEMA_QUERY.md` (writing rules + confidence only, for read/answer/describe/lint). | Done |
| `src/lang.py` | Layer-1 language pinning (deterministic, no deps). `detect(text, default="de")` — umlaut/ß + DE/EN function-word heuristic, robust on short queries; `response_directive`/`ingest_directive` return the native-language directive constant from `prompts.py`. Ingest pins the **source** language into the system prompt (`wiki_engine.ingest_begin`); wiki-chat/`agent`/`chat_agent` pin the **query** language into the answer prompt + budget-nudge + fallback. Structural `## Key facts`, citations, and numbers are directive-exempt. | Done |
| `src/metadata_extract.py` | Deterministic effective-date detection (regex-only, no LLM — small-model-safe). `extract_effective_date(text)` scans the document head for German/legal vintage cues (`in Kraft getreten`, `gültig ab`, `Stand:`, `Fassung vom`, `vom TT.MM.JJJJ`, ISO) and normalizes `TT.MM.JJJJ` / `TT. Monat JJJJ` / ISO → `YYYY-MM-DD` (the shape `wiki_engine._parse_date` accepts), else `None`. Recovers the one metadata field with algorithmic weight (`effective as of` → `_is_newer`) so multi-file ingest needs no per-file form; the Upload review table lets the user correct it. | Done |
| `src/okf.py` | Open Knowledge Format (OKF v0.1) conformance — deterministic, no-LLM. `apply_to_page` stamps recommended frontmatter (`description`/`tags`/`resource`/`timestamp`) + regenerates a `## Citations` section from `sources`; `enrich_frontmatter`, `render_citations`, `add_log_entry`/`reformat_log` (date-grouped OKF log), `okf_validate(wiki_dir)` (conformance gate). Called by **every** wiki-page writer — `wiki_engine` (ingest/merge/insight/contradiction resolution) and the research-report tool in `tools.py` — plus `scripts/okf_migrate.py`. See [docs/okf.md](docs/okf.md). | Done |
| `src/wiki_engine.py` | `condense_followup` (rewrites a follow-up + prior Q&A into a standalone question via one bare-`ollama_client` call; falls back to the raw follow-up on error), `init_wiki`, three-stage `ingest_begin` / `ingest_piece` / `ingest_end` (source-scoped chunker+qa_gen+`_source_to_pages` reverse map + one stable `summary-<source>.md` slug + per-ingest routing `registry` → per-piece BM25 candidate-index nudge + LLM synthesis → deterministic code-side `_route_page` dedup + `_merge_pages` merge + `_ensure_key_terms`/`_ensure_index_block` (`## Key facts`) → single `lex_index.build()`; `ingest_end(ctx, finalize=…)` — `finalize=False` defers the corpus-wide `lex_index.build()`+`update_description` so batch ingest runs them once after the last file), `consolidate(db, dry_run, llm_polish)` (one-off legacy-duplicate cleanup, see `scripts/dedup_wiki.py`), back-compat `ingest()` wrapper, `rebuild_lex_index`, `delete_source` (cascading: raw + manifest + chunks + qa rows + wiki pages + index rebuild), `query`/`query_with_sources`, `file_answer`, `lint` (date-aware + programmatic orphan/stale lists, scans insights), `build_link_graph`, `build_typed_graph` (page + source nodes, typed edges), `find_orphans`, `linked_pages` (1-hop link expansion for link-aware retrieval: **undirected** — out-links + in-links (`_backlink_map`) — plus implicit `_shared_source_siblings` edges; insights included), `is_page_stale`/`stale_pages` (E-1 temporal decay), `resolve_contradiction`, `list_pages(include_insights=False)`, `read_page`, `read_page_parsed`, `stats`, `search_wiki`, `get_wiki_tree` (annotates `stale`, includes Insights group) | Done |
| `src/app.py` | Streamlit UI, 5 pages, port 8520, NYT editorial style on the **Forest (light)** palette (theme-aware CSS keyed on `st.session_state["theme"]`; `Slate` dark palette + switching machinery retained but the runtime toggle is currently disabled; Inter body + Libre Baskerville headings — see [docs/ui.md](docs/ui.md) §Theme system). Chat-Deep renders live agent trace (thoughts, tool calls, results) during execution and a "Download answer" button on past messages. Per-answer "↪ Follow up" button opens a bordered original-question panel with a downward connector above the pinned chat input. Research page states up front that research includes web search, and shows the saved report inline with "Download report" + "Save to wiki" buttons (explicit opt-in ingest of the result — replaces the former always-on "Auto-save to wiki" checkbox) and an inline follow-up `text_input` rendered **below** the report (via `_run_research_stream` helper, so no scroll-up). Maintenance page includes "Delete Source" section with selectbox + confirmation checkbox, plus admin-only Users/Databases management. Login gate + sidebar DB selector (per-user allowlist) gate all pages; active DB is applied to `db_context` before any page handler runs. **Upload:** multi-file batch (`accept_multiple_files`) — a SHA-keyed prepare pass dedups/converts (`md_convert`)/extracts/auto-detects `effective as of` (`metadata_extract`), a `st.data_editor` review table exposes each file's editable detected date, an "Apply to all" expander sets shared `part of`/`description`, then an oldest-first ingest loop (per-file `try/except`) calls `ingest_end(finalize=is_last)`. **Maintainer layer:** `_can_maintain = auth.is_maintainer(user, active_db)` gates write access — non-maintainers lose the "Upload" nav entry and the Maintenance Delete/Reset sections (read-only tools stay). Admins assign maintainers at DB creation (maintainers multiselect) and per-user in the Users panel ("Maintained databases"). **Sidebar:** `gpu_widget.render_gpu_sidebar(accent=_t["primary"])` shows the live GPU widget (per-GPU temp/fan/load + `llm:` model + research timer) in place of the former Ollama text badge. | Done |
| `src/gpu_widget.py` | Live sidebar GPU monitor. `render_gpu_sidebar(accent)` injects a same-origin `/_api/gpu` route into the running Starlette app (gc-discovered, inserted at index 0 of `app.router.routes`) and renders a `components.html` iframe that polls it every second; payload = per-GPU `nvidia-smi` stats + research timer. `set_research_start/end` + `reset_research_timer` drive the timer. Hidden gracefully when no GPU. | Done |
| `src/prompts.py` | All LLM prompt constants including `WIKI_SEARCH_DESCRIPTION`, `WIKI_READ_DESCRIPTION`, `RESEARCHER_INSTRUCTIONS`, `INGEST_PROMPT`, `GENERATE_QUESTIONS_PROMPT`, `EVALUATE_CONDITION_DESCRIPTION`, `CONDENSE_PROMPT` (follow-up → standalone question), plus `RESPONSE_LANGUAGE_DIRECTIVE`/`INGEST_LANGUAGE_DIRECTIVE` (per-language native strings selected by `lang.py`), etc. | Done |
| `src/tools.py` | Deep-researcher tools (`TOOLS`): `wiki_search` (appends `[Wiki linked N]` results — 1-hop `related:` neighbours of top hits via `wiki_engine.linked_pages`; gated by `WIKI_LINK_EXPANSION`/`WIKI_LINK_SEEDS`/`WIKI_LINK_MAX`)/`wiki_read`, **`raw_search`/`raw_read`** (drill into the original `data/raw/` docs the wiki only summarizes — same tools as deep-chat), `tavily_search`, `fetch_webpage_content`, `think_tool`, `submit_final_answer`, `evaluate_condition`. Deep-chat tools (`CHAT_TOOLS`): `raw_search` (BM25 via `lex_index.query()`), `raw_read` (section-suffixed reads resolve to that section's chunk text — legal `§` + markdown headings; 16 KB byte-`offset` window fallback for section-less files, with a "stop paginating / submit now" nudge after `RAW_READ_NUDGE_AFTER` windows of one file), **`wiki_search`/`wiki_read`** (same tools as research — the wiki is the map used to find which originals matter and how topics connect; grounding still comes from `data/raw/`), `submit_chat_answer` (halved gates; `[Wiki: page.md]` cites count toward `CHAT_MIN_SOURCES` but ≥1 `[Source: ...]` original is always required), `evaluate_condition`. | Done |
| `src/agent.py` | LangGraph deep researcher (plan → wiki-first → triage → expand → submit), wiki index auto-injected into system prompt, ChatOllama backend | Done |
| `src/chat_agent.py` | LangGraph deep chat agent over `data/raw/` originals, with wiki access for navigation (`wiki_search`/`wiki_read`) — `final_answer` splits citations into `sources` (raw originals) and `wiki_sources` (wiki pages) via `_cites`. Gates: `CHAT_MAX_ITERATIONS=25`, `CHAT_MIN_WORDS=300`, `CHAT_MIN_SOURCES=2`, `CHAT_MIN_SEARCHES=3`. Tokenized prefix-search + section-aware reads (read `§`/`#` sections by name) + section-suffixed citations. Stall recovery: `_synthesize_fallback` writes a grounded answer from gathered notes when the agent never submits; recursion-limit surfaces a partial answer with an end-of-answer "may be partial" hint (`_with_iter_hint`). Used by the Chat page in "Deep" mode. Calls `run_memory.begin_run()` per invocation. | Done |
| `src/run_memory.py` | Per-invocation "visited" scratchpad shared by both agents. `RunMemory` dataclass + `ContextVar`. The four read/search tools in `tools.py` short-circuit exact-duplicate calls with a one-line `[memory] Already …` stub so weaker local models can't loop on the same doc until `MAX_ITER`. Section reads are keyed per-section (`raw:{base}|sec=…`) so distinct `§`/heading sections each pass through; byte `offset` is keyed separately so pagination of section-less files still works. | Done |
| `src/template_loader.py` | Reads `templates/insert.md` → ordered list of user-fillable metadata fields | Done |
| `src/db_context.py` | Active-database context **+ multi-DB search scope**. `ContextVar`-backed `set_active_db`/`get_active_db`; per-call path getters `wiki_dir()`/`raw_dir()`/`chunks_dir()`/`index_dir()` (all `$DATA_ROOT/<db>/…`) consumed by every data module instead of import-time constants. `list_dbs()`/`create_db()`; `migrate_legacy_layout()` moves pre-multi-DB `data/{raw,chunks,index,wiki}` into `data/Strahlenschutz/`. **Scope layer** (Wiki Chat cross-DB search): `set_search_scope`/`search_scope` (a second `ContextVar`, defaults to the active DB alone), `using_db(name)` context manager for one-DB-at-a-time fan-out, and `qualify`/`split_ref` for `DB::file.md` cross-DB identity (prefix applied **only** under a >1-DB scope, so single-DB behaviour is byte-identical). Active DB = the single write target; scope = read-only retrieval only. See [docs/architecture.md](docs/architecture.md) §Multi-database chat. | Done |
| `src/auth.py` | Local user store at `data/users.json` (gitignored). bcrypt password hashes; per-user DB allowlist (`dbs`) + `is_admin` + per-DB maintainer list (`maintains`). `verify`, `add_user`, `delete_user`, `set_user_dbs`, `change_password`, `user_dbs`, `is_admin`. **Maintainer layer:** `user_maintains`, `is_maintainer(user, db)` (= `db in maintains`; admin does **not** imply maintainer), `set_user_maintains`, `grant_maintainer` (adds DB to both `dbs` + `maintains`). `ensure_seeded()` creates default admin `T. Hein`/`k-wiki` (maintains `Strahlenschutz`); `backfill_maintainers()` is an idempotent migration that grants pre-existing admins `maintains = dbs` (non-admins stay read-only). | Done |
| `SCHEMA.md` | Wiki schema; the mode-appropriate variant (`SCHEMA.md` full for ingest/page-writing, `SCHEMA_QUERY.md` trimmed for read/answer/lint) is injected into the LLM system prompt via `schema_loader.get_system_prompt` | Done |

---

## 4. Implementation Notes (deviations from PRD)

The mockup simplifies a few planned details — tracked here so future iterations can align:

| Area | PRD intent | Current implementation |
|---|---|---|
| `data/raw/` layout | `uploads/` + `extracted/` subdirs + `.manifest.json` | Flat dir: files + `manifest.json` directly in `data/raw/` |
| LLM page output format | `### FILE:` / `### INDEX_UPDATE` / `### LOG_ENTRY` blocks | `=== filename.md ===` … `=== END ===` blocks |
| `schema_loader.py` | Separate system prompts per operation (ingest/query/lint) | Done: `get_system_prompt(mode)` — `full` (ingest/page-writing) vs `query` (read/answer/describe/lint) |
| `file_processor.py` | Saves extracted text to `data/raw/extracted/` | Returns extracted text in memory; no write |
| Query page selection | Title-heuristic + LLM ranking | Hybrid (Q-1): BM25 candidate set (wiki + raw scope) → LLM re-rank; full-index LLM fallback when BM25 empty |

---

## 5. Hard Constraints

- **No vector DB, no embeddings, no cloud LLM APIs** (PRD §2.3). Scoped exception: `langgraph` + `langchain-ollama` are permitted **only** inside the agent layer (`src/agent.py`, `src/chat_agent.py`, `src/tools.py`) — see `docs/architecture.md` §Deep researcher and §Deep chat.
- **No async** unless UI stack requires it at boundaries (PRD §4.4).
- **All modules in `src/`**, one file per module, no sub-packages (PRD §4.4). Prompts in `src/prompts.py`.
- **`uv` only** for env + deps (PRD §5.3).
- **Test suite: ≈258 tests, no hard cap** — the source-of-truth count. PRD §4.5's original 100-cap was superseded 2026-05 (new modules with verifiable behaviour are exempt); keep the suite lean and high-signal, no low-value proliferation.
- **NYT editorial UI style** (PRD §2.4).
- **Apache-2.0 / MIT-compatible licensing** (CLAUDE.md §5.4).
- **Streamlit port: 8520** (8511 reserved for another app on this host), served
  under the base path **`/wiwi/`** to match the nginx reverse proxy that publishes
  it at `https://ai.brenk.com/wiwi/`. The port root 404s.

---

## 6. Configuration

`.env` is the only config surface (PRD §4.4). Template: `.env.example`.

| Var | Default | Purpose |
|---|---|---|
| `OLLAMA_MODEL` | `gemma4:e4b` | Override model |
| `OLLAMA_HOST` | `http://localhost:11434` | Override Ollama endpoint |
| `QUERY_MODEL` | `OLLAMA_MODEL` | Per-role override for precision/selection calls (`_select_affected_pages`, query page-select) + agent loops. |
| `INGEST_MODEL` | `OLLAMA_MODEL` | Per-role override for wiki page synthesis during ingest. |
| `FAST_MODEL` | `OLLAMA_MODEL` | Per-role override for lightweight maintenance (lint). |
| `TAVILY_API_KEY` | — | Required for the Research page (web search). |
| `MAX_INGEST_CHARS` | `40000` | Chunk size for ingest; documents exceeding this are split into sequential chunks |
| `DATA_ROOT` | `data` | Root for all databases. Each DB is an isolated subtree `$DATA_ROOT/<db>/{raw,chunks,index,wiki}`; users live in `$DATA_ROOT/users.json`. Replaces the old per-dir `WIKI_DIR`/`RAW_DIR`/`CHUNKS_DIR`/`INDEX_DIR` vars (paths now derive from `db_context` + active DB). |
| `INGEST_QA` | `1` | Run `qa_gen` during ingest (hypothetical questions). Set `0` to disable. |
| `STALE_AFTER_DAYS` | `365` | Default freshness window: a page with no `expires_after_days` is flagged stale when `updated` is older than this. |
| `QA_BATCH_SIZE` | `12` | Number of chunks per `qa_gen` LLM batch. |
| `QA_MAX_PAIRS_PER_SOURCE` | `5` | Max hypothetical-question pairs `qa_gen` emits per source; drives the chunk-selection heuristic and slices the final output. |
| `RESEARCH_MIN_SEARCHES` | `6` | Deep researcher: minimum web searches before submitting. |
| `RESEARCH_MIN_WORDS` | `600` | Deep researcher: minimum final-report word count. |
| `RESEARCH_MIN_URLS` | `4` | Deep researcher: minimum unique sources cited (URLs + `[Wiki: ...]` citations). |
| `RESEARCH_MAX_ITERATIONS` | `40` | Deep researcher: LangGraph recursion cap. |
| `RESEARCH_PARALLELISM` | `4` | Deep researcher: thread-pool size for parallel Tavily / page fetches. |
| `RESEARCH_LLM_TIMEOUT` | `300` | Deep researcher: per-LLM-call timeout in seconds. |
| `CHAT_MIN_SEARCHES` | `3` | Deep chat: minimum tool calls before submitting. |
| `CHAT_MIN_WORDS` | `300` | Deep chat: minimum answer word count. |
| `CHAT_MIN_SOURCES` | `2` | Deep chat: minimum unique citations (`[Source: filename]` + `[Wiki: page.md]`; at least one must be a `[Source: ...]` original). |
| `CHAT_MAX_ITERATIONS` | `25` | Deep chat: LangGraph recursion cap (~⅝ of research; allows pagination of long docs). |
| `CHAT_LLM_TIMEOUT` | `180` | Deep chat: per-LLM-call timeout in seconds. |

---

## 7. Setup

```bash
git clone https://github.com/ToHeinAC/KB_BS_local-wiki-he
cd KB_BS_local-wiki-he
uv sync
ollama pull gemma4:e4b          # or set OLLAMA_MODEL to any pulled model
cp .env.example .env           # add TAVILY_API_KEY when Research is implemented
uv run streamlit run src/app.py --server.port 8520
```

Open `http://localhost:8520/wiwi/` — the port root 404s (`baseUrlPath` in
`.streamlit/config.toml`, matching the nginx path).

---

## 8. Change Log

The full dated change log lives in [docs/changelog.md](docs/changelog.md) (@docs/changelog.md — newest entries at the bottom).
