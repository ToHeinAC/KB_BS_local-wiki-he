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
| `src/embed_index.py` (semantic arm, Stage C) | **Done** |
| `src/retrieval.py` (hybrid RRF fusion, Stage C) | **Done** |
| `src/rerank.py` (cross-encoder rerank, Stage D) | **Done** (optional extra) |
| `src/calibrate.py` (calibrated abstention, Stage E) | **Done** |
| `src/qa_gen.py` | **Done** |
| `src/run_memory.py` | **Done** |
| `src/db_context.py` (multi-DB path resolution) | **Done** |
| `src/auth.py` (users + bcrypt) | **Done** |
| `src/lang.py` (DE/EN detection + language directives) | **Done** |
| `src/metadata_extract.py` (regex effective-date detection) | **Done** |
| Test suite | **Done** (446 tests, 443 passing — see §5 and [`docs/tests.md`](docs/tests.md)) |
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
| Retrieval layer (arms, fusion, rerank, query flows) | [`docs/retrieval.md`](docs/retrieval.md) | §2, §7 |
| Deep Research, web mode (vendored supervisor graph) | [`docs/deep_research.md`](docs/deep_research.md) | §3.7–3.8 |
| Domain & rationale | [`docs/domain.md`](docs/domain.md) | §1, §10 |
| Tech stack & environment | [`docs/tech.md`](docs/tech.md) | §2.3, §4.4, §5 |
| UI design & pages | [`docs/ui.md`](docs/ui.md) | §2.4, §3.9 |
| Wiki / SCHEMA / storage | [`docs/wiki.md`](docs/wiki.md) | §2.1, §3.5, §6 |
| Open Knowledge Format (OKF v0.1) alignment | [`docs/okf.md`](docs/okf.md) | — |
| Testing strategy | [`docs/tests.md`](docs/tests.md) | §4.5 |
| Open issues | [`docs/openissues.md`](docs/openissues.md) | — |
| Dated change log | [`docs/changelog.md`](docs/changelog.md) | — |
| Change log archive | [`docs/changelog-archive.md`](docs/changelog-archive.md) | — |
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
| `src/lex_index.py` | Lexical index over chunks in a single SQLite **FTS5** store (`data/<DB>/index/chunks.sqlite`); `bm25()` scoring over the pre-expanded variant `terms` column. 4 normalized token variants (surface / NFKD / umlaut-digraph / stem). Scoped (R-1): `build()` full-rebuilds raw chunks (`scope="raw"`) + wiki page bodies (`scope="wiki"`, via `_wiki_chunks()`, text inline); `index_replace_source` / `index_replace_wiki_page` / `index_delete` do per-source incremental updates (used by ingest + `delete_source`, no corpus rebuild); `index_health()` returns per-scope row counts so the UI can distinguish *no index* from *no match*; `query(q, top_k, scope=None)` filters by scope and dedups by `chunk_id`. | Done |
| `src/embed_index.py` | **Semantic arm (Stage C).** Local, file-backed dense-vector index over the same chunks: per-DB `vectors.npy` (float16, L2-normalized) + `vectors.json` (model + aligned row meta), embedded via local Ollama `/api/embed` (`EMBED_MODEL`, default `bge-m3`). Brute-force cosine `query(q, top_k, scope)` (lex-index hit shape). Wiki chunks embedded with a deterministic OKF identity prefix (§3.3), never leaked into hit text. Optional/graceful: `available()` gates use; a pure derived cache rebuilt by `build()` / `scripts/backfill_embeddings.py`. Per-source **incremental** updates (`index_replace_source` / `index_replace_wiki_page` / `index_delete`, mirroring `lex_index`) keep an already-embedded DB current — best-effort and gated on an existing model-matching index, so ingest never fails on embeddings and a never-backfilled DB never gets partial coverage. | Done |
| `src/retrieval.py` | **Hybrid entry point (Stage C/D).** `search(q, top_k, scope, use_rerank=False)` fuses the lexical + semantic arms via weighted RRF (k=60, dense arm 2×, top-rank bonus), then optionally applies the Stage D cross-encoder. `use_rerank` encodes the Fast/Deep split: browsing/per-keystroke paths stay fusion-only; the Deep answer paths (which commit to a citation) pay for precision. Degrades to exactly `lex_index.query` when the semantic arm is unavailable, so embeddings can never regress the lexical baseline; the lexical arm stays the citation source of truth. Consumed by the chat/agent answer paths; ingest routing and the Explorer's `search_wiki` stay lexical. See [docs/retrieval.md](docs/retrieval.md). | Done |
| `src/rerank.py` | **Cross-encoder reranker (Stage D).** Reorders the fused candidate list with `bge-reranker-v2-m3` (GGUF in `models/`) run **in-process** via `llama-cpp-python` — no second service. `available()` gates use (`RERANK_ENABLED`, runtime installed, GGUF present); `score_pairs()` returns relevance logits; `rerank()` blends normalized fused + reranker scores **position-awarely** (0.25 / 0.40 / 0.50 by rank tier) and attaches `rerank_score`, which Stage E (`calibrate.py`) thresholds for abstention. **Fails open on everything** — no model, no runtime, or any error mid-scoring returns the fused order untouched, so a down reranker degrades ranking but never breaks search. Two non-obvious runtime facts (D.0): `Llama.rank` is *not* exposed, so scoring drives the ctypes layer and builds `[BOS] q [EOS] [SEP] doc [EOS]` itself under RANK pooling; and **Ollama cannot host a reranker at all** — never "simplify" this onto `ollama_client`. See [docs/retrieval.md](docs/retrieval.md). | Done |
| `src/calibrate.py` | **Calibrated abstention (Stage E).** `assess(hits, db)` → `(confident, relevance, closest_hit)`: abstains only when a per-DB τ exists **and** the best passage's `rerank_score` is below it. τ is a per-DB derived artifact (`data/<db>/index/calibration.json`) calibrated offline by `scripts/calibrate_abstention.py` from should-answer vs should-abstain fixture separability (DECISION 8: per-DB, conservative default = max-margin midpoint; KI: query-AUC 1.0, τ −4.14). `relevance()` is a display-only logistic. **Fail-safe:** uncalibrated DB / no `rerank_score` / `ABSTAIN_ENABLED=0` ⇒ confident (never abstains on an uncalibrated score). Consumed by Deep answer paths only — `wiki_engine.query_with_sources` (deterministic, skips synthesis) and `tools._submit_chat_impl` (one bounded soft nudge via `run_memory.best_relevance`). | Done |
| `src/qa_gen.py` | Ingest-time HyDE. `_select_target_chunks` picks the top-`QA_MAX_PAIRS_PER_SOURCE` heading-anchored, densest chunks; one batched LLM call asks for 2–4 questions each; output sliced to the cap. Guarantees ≥1 question per source via retry + title fallback. Persists to `data/index/qa.jsonl`. Folded into BM25 by `lex_index.build()`. `delete_source_entries(name)` rewrites the file in place. | Done |
| `src/ollama_client.py` | `generate(…, model_id=None)` + `chat()` wrappers; `is_available()` health check; `ocr()` (vision) + `rewrite()` (per-call model id) for `md_convert`. Per-role model overrides `_QUERY_MODEL`/`_INGEST_MODEL`/`_FAST_MODEL` (each falls back to `OLLAMA_MODEL`). | Done |
| `src/schema_loader.py` | `get_system_prompt(mode="full"\|"query")` — `full` reads `SCHEMA.md` (page templates, for ingest + page-writing); `query` reads trimmed `SCHEMA_QUERY.md` (writing rules + confidence only, for read/answer/describe/lint). | Done |
| `src/lang.py` | Layer-1 language pinning (deterministic, no deps). `detect(text, default="de")` — umlaut/ß + DE/EN function-word heuristic, robust on short queries; `response_directive`/`ingest_directive` return the native-language directive constant from `prompts.py`. Ingest pins the **source** language into the system prompt (`wiki_engine.ingest_begin`); wiki-chat/`agent`/`chat_agent` pin the **query** language into the answer prompt + budget-nudge + fallback. Structural `## Key facts`, citations, and numbers are directive-exempt. | Done |
| `src/metadata_extract.py` | Deterministic effective-date detection (regex-only, no LLM — small-model-safe). `extract_effective_date(text)` scans the document head for German/legal vintage cues (`in Kraft getreten`, `gültig ab`, `Stand:`, `Fassung vom`, `vom TT.MM.JJJJ`, ISO) and normalizes `TT.MM.JJJJ` / `TT. Monat JJJJ` / ISO → `YYYY-MM-DD` (the shape `wiki_engine._parse_date` accepts), else `None`. Recovers the one metadata field with algorithmic weight (`effective as of` → `_is_newer`) so multi-file ingest needs no per-file form; the Upload review table lets the user correct it. | Done |
| `src/okf.py` | Open Knowledge Format (OKF v0.1) conformance — deterministic, no-LLM. `apply_to_page` stamps recommended frontmatter (`description`/`tags`/`resource`/`timestamp`) + regenerates a `## Citations` section from `sources`; `enrich_frontmatter`, `render_citations`, `add_log_entry`/`reformat_log` (date-grouped OKF log), `okf_validate(wiki_dir)` (conformance gate). Called by **every** wiki-page writer — `wiki_engine` (ingest/merge/insight/contradiction resolution) and the research-report tool in `tools.py` — plus `scripts/okf_migrate.py`. See [docs/okf.md](docs/okf.md). | Done |
| `src/wiki_engine.py` | `condense_followup` (follow-up + prior Q&A → standalone question; falls back to the raw follow-up on error), `init_wiki`, three-stage `ingest_begin` / `ingest_piece` / `ingest_end` (source-scoped chunker+qa_gen+`_source_to_pages` reverse map + one stable `summary-<source>.md` slug + per-ingest routing `registry` → per-piece BM25 candidate-index nudge + LLM synthesis → deterministic code-side `_route_page` dedup + `_merge_pages` merge + `_ensure_key_terms`/`_ensure_index_block` (`## Key facts`) → single `lex_index.build()`; `ingest_end(ctx, finalize=…)` — `finalize=False` defers the corpus-wide `lex_index.build()`+`update_description` so batch ingest runs them once after the last file), `consolidate(db, dry_run, llm_polish)` (one-off legacy-duplicate cleanup, see `scripts/dedup_wiki.py`), back-compat `ingest()` wrapper, `ingest_as_source(text, title)` (registers the text in `data/raw/` via `dedup` **before** ingesting, so a saved research answer becomes a first-class source rather than a `source::` graph node with no file behind it), `rebuild_lex_index`, `delete_source` (cascading: raw + manifest + chunks + qa rows + wiki pages + index rebuild), `query`/`query_with_sources`, `file_answer`, `lint` (date-aware + programmatic orphan/stale lists), `build_link_graph`, `build_typed_graph`, `find_orphans`, `linked_pages` (1-hop, **undirected**: out-links + in-links + shared-source edges), `is_page_stale`/`stale_pages` (E-1), `resolve_contradiction`, `list_pages`, `read_page(_parsed)`, `stats`, `search_wiki`, `get_wiki_tree`. See [docs/architecture.md](docs/architecture.md). | Done |
| `src/graph_export.py` | **Graph payload for the neural renderer.** `export(today=None)` wraps `wiki_engine.build_typed_graph()` (the single structural source of truth — this module derives no edges of its own) and enriches it: per-node frontmatter (`cat`/`confidence`/`created`/`updated`/`tags`, staleness via `wiki_engine.is_page_stale`) plus networkx analytics (degree, PageRank, betweenness, seeded Louvain communities, `hub`/`bridgeHub`/`orphan` flags at the top decile). Deterministic by construction: nodes/edges sorted, `related-to` pairs oriented alphabetically (so `Path.glob` order can't leak in), Louvain seeded at 42, floats rounded ⇒ snapshot-testable. `GRAPH_MAX_NODES` keeps the best-connected core and sets `truncated`. `health(payload, today=None)` derives the Explorer's health view from an exported payload — pure, pages-only: orphan/stale/low-confidence lists plus per-cluster size and growth (`HEALTH_WINDOW_DAYS`=30), clusters labelled by their most central page and ranked growth-first. It re-reads nothing, so the panel and the canvas overlays cannot disagree. | Done |
| `src/graph_widget.py` | **Streamlit mount for the graph renderer.** Declares `src/assets/graph/` as a **static-path custom component** (`declare_component(path=…)` — no npm build; Streamlit serves it under `baseUrlPath`, so `/wiwi/` and the reverse proxy work without `gpu_widget.py`-style route injection). Chosen over `components.html` because a static component is **bidirectional**: a node click returns to Python, whereas the obvious `?page=<slug>` top-window navigation is a full page load that would drop `st.session_state["user"]` and bounce the user to the login screen. `render_graph(overlays, size_by, layout)` returns `{node, kind, n}`; `layout` (`galaxy` / `arc` / `radial`) is a pure frontend switch over the same payload — see [docs/ui.md](docs/ui.md) §Graph view. The payload is `@st.cache_data`-keyed on the wiki bundle signature (file count + newest mtime), so an ingest invalidates it by touching files — no hook in `ingest_end` to keep in sync. `graph_health()` runs `graph_export.health()` over that same cached payload for the side panel. | Done |
| `src/assets/graph/index.html` | Self-contained canvas renderer (force layout, 2-hop hover focus, search, info panel, pan/zoom, hub/bridge/orphan/stale/low-confidence overlays, dot size by PageRank or degree via a toggle, plus a ranked-circle chart that recolours a selected subgraph by rank). Nodes sit at fixed layout coordinates — focus changes brightness only, never positions. No CDN, no build step, system font stack; honours `prefers-reduced-motion` (freezes pulses). Renders only what Python stamped — it re-derives no graph structure — and talks to Streamlit over the component protocol (`componentReady` / `setFrameHeight` / `setComponentValue`), hand-rolled rather than via `streamlit-component-lib` to keep Node out of a `uv`-only project. | Done |
| `src/theme.py` | **Frontend skins.** Holds the palette tokens (`Forest` / `Slate` / `Newspaper`) and the single token-parametric base stylesheet both skins share, so a Streamlit-quirk fix lands in one place. `inject_css()` writes this run's `<style>` and returns the token dict `app.py` and `gpu_widget.render_gpu_sidebar(accent=…)` read by name; `is_newspaper()` gates the chrome differences; `masthead()` / `colophon()` draw the broadsheet nameplate and footer rule. Selected once per process by `FRONTEND`. | Done |
| `src/app.py` | Streamlit UI shell, 5 pages, port 8520, NYT editorial style. Login gate + a main-window top bar (per-user DB selectbox; `OPTIONS` `st.segmented_control` — Upload / Wiki Explorer / Wiki Chat / Research) drive every page; the active DB reaches `db_context` before any page handler runs. **Maintenance** is a sidebar entry taking over the main window. **Chat** streams the Deep agent trace live; **Research** has a `Quick` / `Deep` toggle (`_run_research_stream(…, deep=)`), per-URL citation cards in the Sources panel, and an inline follow-up below the report. **Upload** is a multi-file batch: SHA-keyed prepare pass (dedup / `md_convert` / extract / `metadata_extract` date detect) → `st.data_editor` review table → oldest-first ingest loop calling `ingest_end(finalize=is_last)`. **Maintainer layer:** `_can_maintain = auth.is_maintainer(user, active_db)` hides the Upload segment and the Maintenance Delete/Reset sections from non-maintainers. Two framework facts that cost a debugging round-trip each: `st.tabs` is rejected for navigation (it evaluates every branch per rerun, and Upload's `st.stop()` would blank the others), and the pills are styled via `[data-testid="stButtonGroup"]` + `button[kind="segmented_controlActive"]`. Layout, theming, panels and page-by-page detail: [docs/ui.md](docs/ui.md). | Done |
| `src/gpu_widget.py` | Live sidebar GPU monitor. `render_gpu_sidebar(accent)` injects a same-origin `/_api/gpu` route into the running Starlette app (gc-discovered, inserted at index 0 of `app.router.routes`) and renders a `components.html` iframe that polls it every second; payload = per-GPU `nvidia-smi` stats + research timer. `set_research_start/end` + `reset_research_timer` drive the timer. Hidden gracefully when no GPU. | Done |
| `src/prompts.py` | All LLM prompt constants including `WIKI_SEARCH_DESCRIPTION`, `WIKI_READ_DESCRIPTION`, `RESEARCHER_INSTRUCTIONS`, `INGEST_PROMPT`, `GENERATE_QUESTIONS_PROMPT`, `EVALUATE_CONDITION_DESCRIPTION`, `CONDENSE_PROMPT` (follow-up → standalone question), plus `RESPONSE_LANGUAGE_DIRECTIVE`/`INGEST_LANGUAGE_DIRECTIVE` (per-language native strings selected by `lang.py`), etc. | Done |
| `src/tools.py` | Deep-researcher tools (`TOOLS`): `wiki_search` (appends `[Wiki linked N]` results — 1-hop `related:` neighbours of top hits via `wiki_engine.linked_pages`; gated by `WIKI_LINK_EXPANSION`/`WIKI_LINK_SEEDS`/`WIKI_LINK_MAX`)/`wiki_read`, **`raw_search`/`raw_read`** (drill into the original `data/raw/` docs the wiki only summarizes — same tools as deep-chat), `tavily_search`, `fetch_webpage_content`, `think_tool`, `submit_final_answer`, `evaluate_condition`. Deep-chat tools (`CHAT_TOOLS`): `raw_search` (BM25 via `lex_index.query()`), `raw_read` (section-suffixed reads resolve to that section's chunk text — legal `§` + markdown headings; 16 KB byte-`offset` window fallback, with a "stop paginating / submit now" nudge after `RAW_READ_NUDGE_AFTER` windows), **`wiki_search`/`wiki_read`** (the wiki is the map used to find which originals matter; grounding still comes from `data/raw/`), `submit_chat_answer` (halved gates; `[Wiki: page.md]` cites count toward `CHAT_MIN_SOURCES` but ≥1 `[Source: ...]` original is always required), `evaluate_condition`. | Done |
| `src/agent.py` | LangGraph deep researcher (plan → wiki-first → triage → expand → submit), wiki index auto-injected into system prompt, ChatOllama backend. Drives the Research page's **Quick** mode. | Done |
| `src/deep_research_agent.py` | **Research page → Deep mode (web-only).** Adapter over the vendored `open_deep_research` supervisor graph: decomposes the question, fans researcher subgraphs out over Tavily, synthesises a URL-cited report. All four model roles pinned to local Ollama via `Configuration`; clarification off; budgets from `DEEP_RESEARCH_*`. `run_deep_research(question, wiki_context="")` is a plain **sync** generator emitting `agent.py`'s step-dict shape plus a `notice` type, pumping the natively-async graph on a private event loop. **Never touches the wiki or `data/raw/`.** Falls back to Quick mode on failure rather than erroring; report saved to `comparisons/` in the Quick path's shape. Internals, config table and the non-obvious upstream behaviours: [docs/deep_research.md](docs/deep_research.md). | Done |
| `src/vendor/open_deep_research/` | Vendored [langchain-ai/open_deep_research](https://github.com/langchain-ai/open_deep_research) (MIT, commit `d337ae3`, v0.0.16) — 5 modules, unmodified except a mechanical import rewrite. Vendored rather than `uv add`ed: upstream declares ~40 deps (Azure, Supabase, AWS, Vertex, `openai`) and pins the LangChain 0.3 line, which would contradict §5 and downgrade this project's LangChain 1.x. See [`src/vendor/README.md`](src/vendor/README.md). | Done |
| `src/chat_agent.py` | LangGraph deep chat agent over `data/raw/` originals, with wiki access for navigation (`wiki_search`/`wiki_read`) — `final_answer` splits citations into `sources` (raw originals) and `wiki_sources` (wiki pages) via `_cites`. Gates: `CHAT_MAX_ITERATIONS=25`, `CHAT_MIN_WORDS=300`, `CHAT_MIN_SOURCES=2`, `CHAT_MIN_SEARCHES=3`. Tokenized prefix-search + section-aware reads (read `§`/`#` sections by name) + section-suffixed citations. Stall recovery: `_synthesize_fallback` writes a grounded answer from gathered notes when the agent never submits; recursion-limit surfaces a partial answer with an end-of-answer "may be partial" hint (`_with_iter_hint`). Used by the Chat page in "Deep" mode. Calls `run_memory.begin_run()` per invocation. | Done |
| `src/run_memory.py` | Per-invocation "visited" scratchpad shared by both agents. `RunMemory` dataclass + `ContextVar`. The four read/search tools in `tools.py` short-circuit exact-duplicate calls with a one-line `[memory] Already …` stub so weaker local models can't loop on the same doc until `MAX_ITER`. Section reads are keyed per-section (`raw:{base}|sec=…`) so distinct `§`/heading sections each pass through; byte `offset` is keyed separately so pagination of section-less files still works. | Done |
| `src/template_loader.py` | Reads `templates/insert.md` → ordered list of user-fillable metadata fields | Done |
| `src/db_context.py` | Active-database context **+ multi-DB search scope**. `ContextVar`-backed `set_active_db`/`get_active_db`; per-call path getters `wiki_dir()`/`raw_dir()`/`chunks_dir()`/`index_dir()` (all `$DATA_ROOT/<db>/…`) consumed by every data module instead of import-time constants. `list_dbs()`/`create_db()`; `migrate_legacy_layout()` moves pre-multi-DB `data/{raw,chunks,index,wiki}` into `data/Strahlenschutz/`. **Scope layer** (Wiki Chat cross-DB search): `set_search_scope`/`search_scope` (a second `ContextVar`, defaults to the active DB alone), `using_db(name)` context manager for one-DB-at-a-time fan-out, and `qualify`/`split_ref` for `DB::file.md` cross-DB identity (prefix applied **only** under a >1-DB scope, so single-DB behaviour is byte-identical). Active DB = the single write target; scope = read-only retrieval only. See [docs/retrieval.md](docs/retrieval.md) §Multi-database chat. | Done |
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

- **No cloud LLM APIs, no external vector DB/service** (PRD §2.3). Scoped exceptions: (1) `langgraph` + `langchain-ollama` are permitted **only** inside the agent layer (`src/agent.py`, `src/chat_agent.py`, `src/tools.py`) — see `docs/architecture.md` §Deep researcher and §Deep chat. (2) **Local, file-backed embeddings for retrieval** (Stage C, `src/embed_index.py`, AGENTS.md §5.3): vectors computed via the already-required local Ollama `/api/embed`, stored as a per-DB derived cache (`vectors.npy` + `vectors.json`), searched by brute-force cosine — no ANN index, no vector service, no cloud embedding API. The semantic arm is optional and degrades to the lexical FTS5 arm (the citation source of truth) with zero behaviour change. (3) **The Stage D cross-encoder** (`src/rerank.py`): `llama-cpp-python` runs the reranker GGUF **in-process** — no service, no cloud API, weights are a re-downloadable artifact under `models/`. It is an **optional extra** (`uv sync --extra rerank`); without it retrieval is plain RRF fusion. Ollama is *not* an option here — it exposes no rerank endpoint and returns uniform noise rather than erroring. (4) **Deep Research, web mode** (`src/deep_research_agent.py` + `src/vendor/`): every model role is set to `ollama:<tag>`, and upstream's `get_api_key_for_model` returns `None` for any non-`openai:`/`anthropic:`/`google:` prefix, so **no cloud key is ever read or required** (verified end-to-end with `OPENAI_API_KEY` unset); no cloud SDK is a dependency. Web *search* via Tavily was already permitted for the Research page.
- **No async** unless UI stack requires it at boundaries (PRD §4.4). **Scoped exception:** Deep Research (web mode). The vendored `open_deep_research` graph is natively async (`asyncio.gather` across researcher subgraphs) and is adopted as-is; the async surface is confined to `src/vendor/`, and `deep_research_agent.run_deep_research` re-exposes it as a plain sync generator over a private event loop, so nothing else in the app sees `await`.
- **All modules in `src/`**, one file per module, no sub-packages (PRD §4.4). Prompts in `src/prompts.py`. **Scoped exception:** `src/vendor/` holds vendored third-party source (currently `open_deep_research`) as a package; it is not domain code and is never hand-edited — see [`src/vendor/README.md`](src/vendor/README.md).
- **`uv` only** for env + deps (PRD §5.3).
- **Test suite: 446 tests, no hard cap** — the source-of-truth count. PRD §4.5's original 100-cap was superseded 2026-05 (new modules with verifiable behaviour are exempt); keep the suite lean and high-signal, no low-value proliferation.
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
| `EMBED_MODEL` | `bge-m3` | Embedding model for the semantic arm (`src/embed_index.py`), called via local Ollama `/api/embed`. Changing it invalidates the vector cache — re-run `scripts/backfill_embeddings.py <DB>`. Vectors are optional: DBs without them degrade to lexical-only. |
| `RERANK_ENABLED` | `1` | Master switch for the Stage D cross-encoder. `0` forces plain RRF fusion. |
| `RERANK_MODEL` | `models/bge-reranker-v2-m3-Q8_0.gguf` | Reranker GGUF path. Absent ⇒ `rerank.available()` is False and retrieval silently stays fusion-only. |
| `RERANK_CANDIDATES` | `30` | Fused-list depth handed to the cross-encoder. Cost is linear in this number (~35 ms/pair on CPU). |
| `RERANK_THREADS` | `0` (auto) | Reranker thread count; `0` uses `min(16, cpu_count)`. |
| `ABSTAIN_ENABLED` | `1` | Master switch for Stage E abstention. `0` never abstains (still answers). |
| `ABSTAIN_TAU_DEFAULT` | — | Fallback abstention τ when a DB has no `index/calibration.json`. Unset ⇒ uncalibrated DBs never abstain (fail-safe). Per-DB τ from `scripts/calibrate_abstention.py` always wins. |
| `FRONTEND` | `default` | Visual skin (`src/theme.py`). `default` = the editorial Forest palette; `newspaper` = the broadsheet skin (paper stock, Bodoni masthead, Garamond prose, mono figures, hairline rules) plus the paper graph canvas. Same pages, same behaviour — chrome only. See [docs/ui.md](docs/ui.md) §Frontend skins. |
| `GRAPH_RENDERER` | `legacy` | Wiki Explorer → Graph renderer. `legacy` = the vis.js typed graph; `neural` = the canvas neural renderer (`src/graph_widget.py`). Default stays `legacy` until parity is confirmed. |
| `GRAPH_BACKDROP` | `galaxy` | Backdrop behind the neural graph canvas: `galaxy` = the Hubble image in `src/assets/graph/` (credit NASA/ESA, see `NOTICE`), `none` = flat `--bg`. Decorative only. |
| `GRAPH_MAX_NODES` | `4000` | Guardrail for the neural renderer: above this the payload keeps the best-connected nodes and flags `truncated`. The force layout, not the analytics, is what degrades first. |
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
| `DEEP_RESEARCH_MODEL` | `QUERY_MODEL` | Deep Research (web): Ollama tag used for **all four** upstream roles (research / report / compression / summarization). |
| `DEEP_RESEARCH_CONCURRENCY` | `1` | `max_concurrent_research_units`. Ollama serialises requests on one model, so raising this costs VRAM without buying speed. |
| `DEEP_RESEARCH_MAX_ITERATIONS` | `4` | `max_researcher_iterations` — supervisor reflection rounds. |
| `DEEP_RESEARCH_MAX_TOOL_CALLS` | `6` | `max_react_tool_calls` per researcher subgraph. |
| `DEEP_RESEARCH_MAX_TOKENS` | `8192` | Per-role `*_model_max_tokens`. **No-op on Ollama** — `ChatOllama` bounds output with `num_predict`, not `max_tokens`, and `Configuration` exposes only `model`/`max_tokens`/`api_key` as configurable. Kept for parity with upstream. |
| `DEEP_RESEARCH_CLARIFICATION` | `false` | `allow_clarification`. Keep off: the Research page is one-shot and cannot answer a clarifying turn. |
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
