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
| Test suite | **Done** (130 tests; old 100-cap superseded — see [`docs/tests.md`](docs/tests.md)) |
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
| Testing strategy | [`docs/tests.md`](docs/tests.md) | §4.5 |
| Open issues | [`docs/openissues.md`](docs/openissues.md) | — |

---

## 3. Module Inventory

All Python modules live under `src/`. Entry point: `uv run streamlit run src/app.py --server.port 8520`.

| Module | Purpose | Status |
|---|---|---|
| `src/dedup.py` | SHA-256 dedup; flat `data/raw/` store + `manifest.json`. `list_sources()` / `deregister_source()` support cascading deletion. | Done |
| `src/file_processor.py` | Extract text from PDF/DOCX/MD/TXT/HTML; `chunk_text()` splits large docs at paragraph boundaries | Done |
| `src/md_convert.py` | Convert non-Markdown uploads (PDF/DOCX/images) to Markdown before ingest. Ported from [ToHeinAC/MD-maker](https://github.com/ToHeinAC/MD-maker) (Apache-2.0): per-page PDF routing (digital text → LLM rewrite, scanned/image → vision OCR), deterministic DOCX→MD, image OCR. `convert_to_markdown()` + `is_convertible()`; Ollama via `ollama_client.ocr()/.rewrite()`. Env: `OCR_MODEL`, `REWRITE_MODEL`, `PDF_DPI`. | Done |
| `src/chunker.py` | Structural chunker: legal `§` / markdown headings / paragraph windows with overlap. Content-addressable `chunk_id`. Persists to `data/chunks/<source-slug>.jsonl`. | Done |
| `src/lex_index.py` | BM25 lexical index over chunks. 4 normalized token variants (surface / NFKD / umlaut-digraph / stem). Persists `postings.json` + `stats.json` to `data/index/`. | Done |
| `src/qa_gen.py` | Ingest-time HyDE. `_select_target_chunks` picks the top-`QA_MAX_PAIRS_PER_SOURCE` heading-anchored, densest chunks; one batched LLM call asks for 2–4 questions each; output sliced to the cap. Guarantees ≥1 question per source via retry + title fallback. Persists to `data/index/qa.jsonl`. Folded into BM25 by `lex_index.build()`. `delete_source_entries(name)` rewrites the file in place. | Done |
| `src/ollama_client.py` | `generate(…, model_id=None)` + `chat()` wrappers; `is_available()` health check; `ocr()` (vision) + `rewrite()` (per-call model id) for `md_convert`. Per-role model overrides `_QUERY_MODEL`/`_INGEST_MODEL`/`_FAST_MODEL` (each falls back to `OLLAMA_MODEL`). | Done |
| `src/schema_loader.py` | `get_system_prompt(mode="full"\|"query")` — `full` reads `SCHEMA.md` (page templates, for ingest + page-writing); `query` reads trimmed `SCHEMA_QUERY.md` (writing rules + confidence only, for read/answer/describe/lint). | Done |
| `src/wiki_engine.py` | `condense_followup` (rewrites a follow-up + prior Q&A into a standalone question via one bare-`ollama_client` call; falls back to the raw follow-up on error), `init_wiki`, three-stage `ingest_begin` / `ingest_piece` / `ingest_end` (source-scoped chunker+qa_gen+`_source_to_pages` reverse map → per-piece BM25 affected-page selection + rank-weighted `_build_existing_block` merge context + LLM synthesis with auto-merged `sources:` frontmatter → single `lex_index.build()`), back-compat `ingest()` wrapper, `rebuild_lex_index`, `delete_source` (cascading: raw + manifest + chunks + qa rows + wiki pages + index rebuild), `query`/`query_with_sources`, `file_answer`, `lint`, `build_link_graph`, `build_typed_graph` (page + source nodes, typed edges), `find_orphans`, `resolve_contradiction`, `list_pages`, `read_page`, `read_page_parsed`, `stats`, `search_wiki`, `get_wiki_tree` | Done |
| `src/app.py` | Streamlit UI, 5 pages, port 8520, NYT editorial style with a **Forest (light) / Slate (dark)** theme toggle (theme-aware CSS keyed on `st.session_state["theme"]`; Inter body + Libre Baskerville headings — see [docs/ui.md](docs/ui.md) §Theme system). Chat-Deep renders live agent trace (thoughts, tool calls, results) during execution and a "Download answer" button on past messages. Per-answer "↪ Follow up" button opens a bordered original-question panel with a downward connector above the pinned chat input. Research page shows the saved report inline with a "Download report" button and an inline follow-up `text_input` rendered **below** the report (via `_run_research_stream` helper, so no scroll-up). Maintenance page includes "Delete Source" section with selectbox + confirmation checkbox, plus admin-only Users/Databases management. Login gate + sidebar DB selector (per-user allowlist) gate all pages; active DB is applied to `db_context` before any page handler runs. **Maintainer layer:** `_can_maintain = auth.is_maintainer(user, active_db)` gates write access — non-maintainers lose the "Upload" nav entry and the Maintenance Delete/Reset sections (read-only tools stay). Admins assign maintainers at DB creation (maintainers multiselect) and per-user in the Users panel ("Maintained databases"). **Sidebar:** `_ollama_badge()` shows a green/red Ollama status badge followed by a `st.sidebar.caption` with the active model name (`ollama_client._MODEL`). | Done |
| `src/prompts.py` | All LLM prompt constants including `WIKI_SEARCH_DESCRIPTION`, `WIKI_READ_DESCRIPTION`, `RESEARCHER_INSTRUCTIONS`, `INGEST_PROMPT`, `GENERATE_QUESTIONS_PROMPT`, `EVALUATE_CONDITION_DESCRIPTION`, `CONDENSE_PROMPT` (follow-up → standalone question), etc. | Done |
| `src/tools.py` | Deep-researcher tools: `wiki_search`/`wiki_read`, `tavily_search`, `fetch_webpage_content`, `think_tool`, `submit_final_answer`, `evaluate_condition`. Deep-chat tools: `raw_search` (BM25 via `lex_index.query()`), `raw_read` (section-suffixed reads resolve to that section's chunk text — legal `§` + markdown headings; byte `offset` fallback for section-less files), `submit_chat_answer` (halved gates), `evaluate_condition`. | Done |
| `src/agent.py` | LangGraph deep researcher (plan → wiki-first → triage → expand → submit), wiki index auto-injected into system prompt, ChatOllama backend | Done |
| `src/chat_agent.py` | LangGraph deep chat agent over `data/raw/` originals. Gates: `CHAT_MAX_ITERATIONS=25`, `CHAT_MIN_WORDS=300`, `CHAT_MIN_SOURCES=2`, `CHAT_MIN_SEARCHES=3`. Tokenized prefix-search + section-aware reads (read `§`/`#` sections by name) + section-suffixed citations. Recursion-limit surfaces partial answer. Used by the Chat page in "Deep" mode. Calls `run_memory.begin_run()` per invocation. | Done |
| `src/run_memory.py` | Per-invocation "visited" scratchpad shared by both agents. `RunMemory` dataclass + `ContextVar`. The four read/search tools in `tools.py` short-circuit exact-duplicate calls with a one-line `[memory] Already …` stub so weaker local models can't loop on the same doc until `MAX_ITER`. Section reads are keyed per-section (`raw:{base}|sec=…`) so distinct `§`/heading sections each pass through; byte `offset` is keyed separately so pagination of section-less files still works. | Done |
| `src/template_loader.py` | Reads `templates/insert.md` → ordered list of user-fillable metadata fields | Done |
| `src/db_context.py` | Active-database context. `ContextVar`-backed `set_active_db`/`get_active_db`; per-call path getters `wiki_dir()`/`raw_dir()`/`chunks_dir()`/`index_dir()` (all `$DATA_ROOT/<db>/…`) consumed by every data module instead of import-time constants. `list_dbs()`/`create_db()`; `migrate_legacy_layout()` moves pre-multi-DB `data/{raw,chunks,index,wiki}` into `data/Strahlenschutz/`. | Done |
| `src/auth.py` | Local user store at `data/users.json` (gitignored). bcrypt password hashes; per-user DB allowlist (`dbs`) + `is_admin` + per-DB maintainer list (`maintains`). `verify`, `add_user`, `delete_user`, `set_user_dbs`, `change_password`, `user_dbs`, `is_admin`. **Maintainer layer:** `user_maintains`, `is_maintainer(user, db)` (= `db in maintains`; admin does **not** imply maintainer), `set_user_maintains`, `grant_maintainer` (adds DB to both `dbs` + `maintains`). `ensure_seeded()` creates default admin `T. Hein`/`k-wiki` (maintains `Strahlenschutz`); `backfill_maintainers()` is an idempotent migration that grants pre-existing admins `maintains = dbs` (non-admins stay read-only). | Done |
| `SCHEMA.md` | Wiki schema injected into every LLM system prompt | Done |

---

## 4. Implementation Notes (deviations from PRD)

The mockup simplifies a few planned details — tracked here so future iterations can align:

| Area | PRD intent | Current implementation |
|---|---|---|
| `data/raw/` layout | `uploads/` + `extracted/` subdirs + `.manifest.json` | Flat dir: files + `manifest.json` directly in `data/raw/` |
| LLM page output format | `### FILE:` / `### INDEX_UPDATE` / `### LOG_ENTRY` blocks | `=== filename.md ===` … `=== END ===` blocks |
| `schema_loader.py` | Separate system prompts per operation (ingest/query/lint) | Done: `get_system_prompt(mode)` — `full` (ingest/page-writing) vs `query` (read/answer/describe/lint) |
| `file_processor.py` | Saves extracted text to `data/raw/extracted/` | Returns extracted text in memory; no write |
| Query page selection | Title-heuristic + LLM ranking | LLM selects filenames from index text |

---

## 5. Hard Constraints

- **No vector DB, no embeddings, no cloud LLM APIs** (PRD §2.3). Scoped exception: `langgraph` + `langchain-ollama` are permitted **only** inside the agent layer (`src/agent.py`, `src/chat_agent.py`, `src/tools.py`) — see `docs/architecture.md` §Deep researcher and §Deep chat.
- **No async** unless UI stack requires it at boundaries (PRD §4.4).
- **All modules in `src/`**, one file per module, no sub-packages (PRD §4.4). Prompts in `src/prompts.py`.
- **`uv` only** for env + deps (PRD §5.3).
- **Test cap: 100 automated tests**, ≈90% core / ≈10% new features (PRD §4.5).
- **NYT editorial UI style** (PRD §2.4).
- **Apache-2.0 / MIT-compatible licensing** (CLAUDE.md §5.4).
- **Streamlit port: 8520** (8511 reserved for another app on this host).

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
| `CHAT_MIN_SOURCES` | `2` | Deep chat: minimum unique `[Source: filename]` citations. |
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

---

## 8. Change Log

| Date | Change |
|---|---|
| 2026-05-02 | Initialised repo, documentation skeleton populated. |
| 2026-05-02 | First mockup: implemented all core modules + Streamlit UI (Research stubbed). |
| 2026-05-02 | Second mockup: implemented `tools.py` + `agent.py`; Research page now fully wired. |
| 2026-05-02 | Applied crportfolioapp colour palette (`.streamlit/config.toml`); implemented 84-test suite across all modules. |
| 2026-05-03 | Added `template_loader.py` + Upload-page metadata form driven by `templates/insert.md`; `wiki_engine.ingest()` now accepts `user_meta`. Test count: 86. |
| 2026-05-03 | Wiki Explorer: tree-by-type (Concepts/Entities/Source Summaries/Comparisons/Other) + full-text search across page bodies via new `wiki_engine.search_wiki` and `get_wiki_tree`. Test count: 90. |
| 2026-05-05 | Deep researcher: replaced ReAct loop with LangGraph state machine ported from `ToHeinAC/deepagents_ollama`. New tools: `tavily_search` (parallel batch), `fetch_webpage_content`, `think_tool`, `submit_final_answer` (word/URL gates). Parallel I/O via `concurrent.futures` thread pool; LLM calls remain sequential. Lifted `No LangChain` ban (scoped to agent layer). Added `langgraph`, `langchain-ollama`, `langchain-core`, `httpx`, `markdownify`. New env vars `RESEARCH_MIN_SEARCHES`/`MIN_WORDS`/`MIN_URLS`/`MAX_ITERATIONS`/`PARALLELISM`/`LLM_TIMEOUT`. Test count: 97. |
| 2026-05-06 | Karpathy-pattern compounding mechanics (closes openissues.md gaps 1–4 + priorities 4 & 7). Ingest is now two-pass: a `SELECT_AFFECTED_PROMPT` call identifies likely-updated pages, their bodies are loaded (capped at 8K chars) and merged into `INGEST_PROMPT` so the LLM merges instead of overwriting. Parse-retry on empty `=== filename.md ===` blocks. Added `file_answer()` (chat answers fileable as `insights/insight-*.md`), `build_link_graph()`/`find_orphans()` (programmatic orphan check now prepended to lint output), `resolve_contradiction()` (focused reconciliation). Streamlit: Save-to-Wiki button on Chat, contradiction-resolve panel on Upload, pyvis Graph view in Wiki Explorer, orphan summary in Maintenance. Test count: 102. |
| 2026-05-06 | Wiki Explorer graph view: replaced pyvis with direct vis.js HTML generation (eliminates broken `lib/bindings/utils.js` local-file reference in Streamlit iframe). Added **Node names** toggle (page title, ≤5 words) and **Edge themes** toggle (first 3 words of target page title as edge label). Tighter Barnes-Hut physics (springLength 120, gravitationalConstant −5000) prevents over-zooming and makes labels readable. |
| 2026-05-08 | Chunked ingest for large documents. `file_processor.extract_text()` now returns full text (no truncation). New `chunk_text(text, chunk_size=MAX_CHARS)` splits at paragraph boundaries with hard-split fallback. `app.py` Upload page loops over chunks with a progress bar; results aggregated. `MAX_INGEST_CHARS` now controls chunk size rather than a hard truncation limit. |
| 2026-05-11 | Wiki Explorer source linking. `wiki_engine.read_page_parsed()` strips YAML frontmatter and returns `{content, sources, related}`. Wiki Explorer article view now renders clean body markdown and shows a collapsible "Sources" expander (original `data/raw/` documents + related wiki pages) — matching Chat tab behaviour. |
| 2026-05-15 | Deep chat recall fix. `raw_search` rewritten as tokenized prefix-match (first 6 chars per token), returning up to 3 excerpts per file ranked by token-hit count — fixes zero-recall on German morphology / multi-word queries. `raw_read` now paginated via `offset` parameter (cap raised 4K→8K with `[truncated; pass offset=N to continue]` footer). `_RAW_CITE_RE` accepts optional `§...`/`#...` section suffix so distinct sections of the same long file count as distinct sources for the `CHAT_MIN_SOURCES=2` gate. Prompts (`CHAT_AGENT_SYSTEM`, `RAW_SEARCH_DESCRIPTION`, `RAW_READ_DESCRIPTION`) updated with single-stem search strategy + pagination guidance. `CHAT_MAX_ITERATIONS` 20→25. `chat_agent.run_chat_agent` now surfaces a partial answer instead of bare error on recursion-limit. `_raw_source_button` in app.py strips `§`/`#` section suffix for raw-file lookup. |
| 2026-05-15 | Deep chat mode. Chat page now has Fast/Deep toggle. Fast is the existing one-shot RAG over wiki pages. Deep is a new LangGraph agent (`src/chat_agent.py`) that searches/reads originals in `data/raw/` via new tools `raw_search` / `raw_read` and submits via `submit_chat_answer` (halved gates: 300 words / 2 sources / 20 iter / 3 searches). No Tavily, no web fetch. Manual "Save to wiki" → `insights/` flow unchanged. New env vars `CHAT_*`. New prompt constant `CHAT_AGENT_SYSTEM`. |
| 2026-05-11 | Wiki-first deep researcher. New tools `wiki_search` / `wiki_read` in `tools.py`; `RESEARCHER_INSTRUCTIONS` rewritten to wiki-first workflow with structured Have/Gaps/Next triage and tangent-parking. `agent.py` auto-injects `data/wiki/index.md` into every system prompt. `submit_final_answer` now counts `[Wiki: filename.md]` citations alongside URLs toward `RESEARCH_MIN_URLS` gate. `query_with_sources()` returns `raw_sources` (original filenames from page frontmatter); Chat page shows both wiki and raw sources in a "Sources" expander. New prompts constants: `WIKI_SEARCH_DESCRIPTION`, `WIKI_READ_DESCRIPTION`. Tests updated/added for new tools and source-counting. |
| 2026-05-15 | **Retrieval optimisation, Tiers 1.1–1.4.** New modules: `src/chunker.py` (structural chunker with stable `chunk_id`), `src/lex_index.py` (BM25 over chunks with 4-variant token normalisation + trigram fuzzy fallback + alias/acronym query expansion + numeric-fact direct-answer shortcut), `src/extractor.py` (ingest-time aliases/acronyms/terms/facts via one LLM call per source, idempotent merge), `src/qa_gen.py` (batched hypothetical-question generator, folded into BM25 postings without inflating doc length). `wiki_engine.ingest()` now drives the retrieval layer before the LLM page-synthesis pass; new `rebuild_lex_index()` helper. `tools._raw_search_one` replaced by `lex_index.query()` + `facts_lookup()` (dead helpers removed). New prompts `EXTRACT_TERMS_PROMPT`, `GENERATE_QUESTIONS_PROMPT`. New env vars `CHUNKS_DIR`, `INDEX_DIR`, `INGEST_EXTRACT`, `INGEST_QA`, `QA_BATCH_SIZE`. `tests/conftest.py` `wiki_dir` fixture extended to isolate retrieval-layer paths and disable the new ingest-time LLM passes. 30 new tests; suite at 135 passing. |
| 2026-05-16 | **Retrieval cleanup + typed graph viz.** Removed unused indexes — `src/extractor.py` (aliases/acronyms/terms/facts) deleted; `lex_index._expand_query`, `facts_lookup`, and the trigram fuzzy-fallback deleted; `INGEST_EXTRACT` env flag dropped; on-disk `data/index/{aliases,acronyms,terms,facts,trigrams}.{json,jsonl}` purged. `qa_gen.generate` now guarantees ≥1 question per source via retry + title fallback. `wiki_engine.ingest_piece` auto-merges `sources:` frontmatter on every page it writes. New `wiki_engine.build_typed_graph()` returns typed nodes (`page` / `source`) + typed edges (`related-to` / `derived-from`); Wiki Explorer Graph view renders blue dots for pages and orange diamonds for source documents, with dashed orange `derived-from` arrows. Suite at 130 passing (−10: extractor module removed, trigram fallback test removed, ollama-failure test inverted to assert fallback). |
| 2026-05-15 | **Tier A ingest speedup.** Long-source ingest dropped from ~30 min to ~7 min on a 488 KB legal doc (~65 LLM calls → ~16). `wiki_engine.ingest()` split into `ingest_begin` (source-scoped: one chunker pass over the whole document, one extractor call, one qa_gen call, one select-affected call), `ingest_piece` (per 40 KB cut: only `INGEST_PROMPT` synthesis + retry + page writes), `ingest_end` (single `lex_index.build()` + index rebuild + log). Back-compat `ingest()` wrapper preserved for tests and the Research auto-save path. `src/qa_gen.py` adds `MAX_PAIRS_PER_SOURCE=5` (env `QA_MAX_PAIRS_PER_SOURCE`) and a `_select_target_chunks` heuristic (anchored → densest → longest → stable) so qa_gen runs once per source against the top-k chunks instead of per-piece across all chunks. `src/app.py` Upload page now drives the three-stage pipeline with per-stage spinners. Suite at 140 passing (+5: qa cap, anchored preference, begin/piece/end roundtrip, single-select assertion, back-compat wrapper). |
| 2026-05-17 | **Cascading source deletion.** `dedup.list_sources()` / `deregister_source()` added. `qa_gen.delete_source_entries()` rewrites `qa.jsonl` in place. `wiki_engine.delete_source(name)` orchestrates full cascade: raw file → manifest → chunk JSONL → QA rows → all wiki pages whose `sources:` frontmatter references the source (including multi-source pages) → `lex_index.build()` + `_rebuild_index()` + log entry. Maintenance page gains a "Delete Source" section (selectbox + irreversibility warning + confirmation checkbox). |
| 2026-05-18 | **Graph viz cleanup.** `build_typed_graph()`: (1) `summary-*` filenames are now excluded from source nodes — they are synthesis artifacts, not raw sources. (2) Implicit co-source `related-to` edges removed — pages sharing the same source were generating O(n²) edges causing dense clusters (e.g. StrlSchG). Only explicit `related:` frontmatter now produces `related-to` edges. |
| 2026-05-19 | **`deep_calculate` tool + Chat-Deep UX.** New `deep_calculate` tool in `src/tools.py` (registered in both `TOOLS` and `CHAT_TOOLS`): accepts named numerical variables and labeled arithmetic expressions using +/-/*/÷ only; uses a safe `ast.NodeVisitor` evaluator (no `eval()`); returns a variables table, labeled results, and relative % shares for 2+ numeric results. Prompt constant `DEEP_CALCULATE_DESCRIPTION` added to `src/prompts.py`. Chat-Deep mode now renders live agent trace during execution (thoughts, tool calls, results in real-time rather than a spinner). "Download answer" button added to past Chat-Deep messages. Research page now shows the saved report inline with a "Download report" button (replaces the dialog-behind-a-button). |
| 2026-05-19 | **Math → logical-condition evaluator swap.** `deep_calculate` (arithmetic) replaced by `evaluate_condition` in both `TOOLS` and `CHAT_TOOLS`. The new tool takes a `facts` dict (numeric / string / list) and a nested-dict `condition` tree supporting comparison (`>`,`>=`,`<`,`<=`,`==`,`!=`), `in`, `contains`, `between`, `not`, and `and`/`or`. Python walks the tree via `operator`-module dispatch — the LLM (gemma4:e4b) only extracts facts and assembles the tree, so threshold/regulatory checks can no longer be hallucinated. Returns facts table + per-leaf TRUE/FALSE trace + `Result: PASS|FAIL`. Errors (missing fact, unknown op, type mismatch) become FALSE leaves with messages; the tool never raises. Old AST-based safe-arithmetic evaluator and `DEEP_CALCULATE_DESCRIPTION` removed. |
| 2026-05-19 | **Per-run visited memory (agent loop guard).** New module `src/run_memory.py`: `RunMemory` dataclass (`reads`, `searches`, `step`) scoped via a `contextvars.ContextVar`; `begin_run()` resets it, `current()` returns the active instance. `run_chat_agent` (`src/chat_agent.py`) and `run_research_agent` (`src/agent.py`) call `begin_run()` at the top of every invocation. `src/tools.py` wraps `wiki_read`, `raw_read`, `wiki_search`, and `raw_search` to check `run_memory.current()` before delegating to the existing `_impl` helpers — exact-duplicate calls now return a one-line `[memory] Already read/searched … at step N` stub instead of re-fetching. Keys: `wiki:{filename}`, `raw:{base}:{offset}` (different offset → fresh, so pagination still works), `wsearch:{q.lower()}`, `rsearch:{q.lower()}`. Multi-file / multi-query batches dedup per-item. `mem is None` short-circuit preserves direct `tools.py` callers / unit tests that never started a run. Fixes the "same doc read over and over until `MAX_ITER` is hit" loop observed on weaker local models / smaller machines (e.g. M3 Air 24 GB). No prompt or graph changes; the stub surfaces in the existing Chat-Deep live trace as a normal `tool_result`. |
| 2026-05-22 | **Follow-up questions (Chat + Research).** Users can ask a dependent question with the original Q&A as the starting point. Approach: a single cheap **condense pre-pass** — `wiki_engine.condense_followup(prev_q, prev_a, followup)` rewrites the trio into one self-contained standalone question (new `CONDENSE_PROMPT`, bare `ollama_client.generate` at temp 0.1, prior answer truncated ~900 chars), which is handed to the **unchanged** entrypoint (`query_with_sources` / `run_chat_agent` / `run_research_agent`). Chosen over transcript replay because each agent run stays **single-turn** — the shape `gemma4:e4b` handles best — with no looping risk and minimal added context; degrades gracefully (returns the raw follow-up if the model errors). GUI (`src/app.py`): Chat shows a per-answer "↪ Follow up" button → bordered panel with the original question + a downward "⬇ Type below" connector above the pinned chat input (Cancel clears it); Research renders an inline follow-up `text_input` **below** the report so no scroll-up is needed, backed by a new module-level `_run_research_stream` helper (the streaming/render block, extracted so both the top Start button and the below-report follow-up reuse it). No changes to `chat_agent.py` / `agent.py` / `tools.py`. |
| 2026-05-30 | **User management + multi-database.** New `src/db_context.py` (ContextVar-backed active-DB + per-call path getters) and `src/auth.py` (`data/users.json`, bcrypt hashes, per-user DB allowlist + admin flag, seeded `T. Hein`/`k-wiki`). Every data module (`wiki_engine`, `chunker`, `lex_index`, `qa_gen`, `dedup`, `tools`, `chat_agent`, `agent`) now resolves paths through `db_context` getters instead of import-time `WIKI_DIR`/`RAW_DIR`/`CHUNKS_DIR`/`INDEX_DIR` constants. Each database is an isolated `data/<db>/{raw,chunks,index,wiki}` subtree; `migrate_legacy_layout()` moves pre-existing top-level data into `data/Strahlenschutz/` on first run. `src/app.py` gains a login gate, sidebar DB selector (scoped to the user's allowlist, applied to the ContextVar before any page handler), logout, and admin-only Users/Databases subsections in Maintenance. New env var `DATA_ROOT` (replaces the four per-dir vars). `data/users.json` gitignored. Added `bcrypt`. `tests/conftest.py` + per-module test fixtures updated to patch `db_context.DATA_ROOT` + active DB. |
| 2026-05-20 | **Section-aware `raw_read` (fixes residual re-read loop).** Even with the visited guard, long legal docs still looped to `MAX_ITER`: section-suffixed reads (`raw_read(["StrlSchG.md § 62"])`) were stripped to the bare filename and read at offset 0, so every section collapsed to the same `raw:{base}:0` key and got blocked — leaving small models (`gemma4:e4b`) no productive path. `_raw_read_one` now resolves a `§`/`#` suffix to the matching chunk via `chunker.load_chunks` (new helpers `_split_filename`, `_norm_anchor`, `_resolve_section`, `_section_anchors`, `_format_section`) and returns just that section's text with a footer naming the next section; this also fixes markdown-heading reads, which previously returned "(not found)". The guard now keys per-section (`raw:{base}|sec={canon}:{offset}`, helpers `_read_key`/`_read_canons`) so distinct sections are distinct reads, and a blocked re-read lists the file's unread anchors. Prompts `RAW_READ_DESCRIPTION` + `CHAT_AGENT_SYSTEM` updated to steer section-by-name navigation (byte `offset` is now only the fallback for section-less files). New tests in `tests/test_tools.py` cover legal + markdown section resolution and per-section memory keying. |
| 2026-05-31 | **Cloudflare quick tunnel + sidebar model display.** New `tunnel.sh` at project root: kills stale tunnels for port 8520, temporarily moves `~/.cloudflared/config.yml` + named-tunnel credentials aside (so cloudflared enters true quick-tunnel mode), starts `cloudflared tunnel --url http://localhost:8520 > /tmp/wiki-tunnel.log 2>&1`, waits 8 s, restores config, extracts `*.trycloudflare.com` URL with grep, prints it, and monitors port 8520 every 3 s — killing the tunnel automatically when the app stops (or on Ctrl-C). `_ollama_badge()` in `src/app.py` now adds `st.sidebar.caption(f"Model: {ollama_client._MODEL}")` directly below the Ollama status badge. |
| 2026-05-31 | **Per-database maintainer layer.** Write access (upload sources, delete data) is now gated per DB. `data/users.json` gains a per-user `maintains: [db, …]` list (subset of `dbs`). `src/auth.py`: `user_maintains`, `is_maintainer(user, db)` (= `db in maintains`; **admin does not imply maintainer** — explicit per DB), `set_user_maintains`, `grant_maintainer` (adds a DB to both `dbs` + `maintains` in one write); `add_user`/`list_users` carry the field; `ensure_seeded` makes the default admin maintain `Strahlenschutz`; idempotent `backfill_maintainers()` grants pre-existing admins `maintains = dbs` so they keep upload rights (non-admins stay read-only until assigned). `src/app.py`: computes `_can_maintain` for the active DB after `set_active_db`; "Upload" nav entry shown only to maintainers (+ defensive page guard); Maintenance Delete-Source/Reset-all gated behind `_can_maintain` (read-only tools — stats, lint, log — stay); admins assign maintainers at DB creation (maintainers multiselect, granted via `grant_maintainer`) and per-user in the Users panel ("Maintained databases" multiselect, intersected against allowed DBs). Behavior change: pre-existing **non-admin** users with DB access become read-only until made maintainers. New `tests/test_auth.py` (12 tests). |
| 2026-06-11 | **Roadmap Phase 2 — Ingest Quality.** (I-2) Affected-page selection no longer uses an LLM excerpt call: new `_source_to_pages()` reverse map (page `sources:` frontmatter → pages) + `_select_affected_pages(query_text, src_to_pages, exclude_source)` query the prior BM25 index and rank pages by summed hit score. Now runs **per piece** (in `ingest_piece`) so later pieces of a long document surface pages the first piece didn't; the begin call drops one LLM round-trip. `SELECT_AFFECTED_PROMPT` removed (dead). (I-1) `_build_existing_block` replaces the flat 8K budget with rank-weighted per-page budgets `_EXISTING_BUDGET_BY_RANK=(4000,2000,2000,800,800)` so the top match merges faithfully; `INGEST_PROMPT` instruction 3 strengthened to a diff-aware "start FROM existing text, ADD/REVISE, never rewrite from scratch" merge. (Two-turn plan/write merge deferred — opt-in path, adds a round-trip.) (T-1) New `tests/test_integration.py`: deterministic prompt-routed mock drives a full ingest→query round-trip + a second-source merge-not-duplicate check. `tests/conftest.py` `wiki_dir` now also sets `INGEST_DESCRIPTION=0` (its documented intent — fixes 3 stale call-count failures). Suite 177 passing (3 unrelated pre-existing `test_file_processor` truncation failures remain). |
| 2026-06-11 | **Roadmap Phase 1 — Schema & Context.** (S-1) `SCHEMA.md` gains an "Operational Constraints" block (≤400-word concept/entity pages, ≤800 source-summary; when-NOT-to-create-a-page threshold; confidence criteria; related-link discipline) — kept under the 2500-char budget. (S-2) `schema_loader.get_system_prompt(mode)` now serves a trimmed `SCHEMA_QUERY.md` (596 chars, writing rules + confidence only) for read/answer/describe/lint calls; ingest + `resolve_contradiction` (which writes pages) keep full `SCHEMA.md`. (A-1) `ollama_client.generate(…, model_id=None)` + per-role overrides `QUERY_MODEL`/`INGEST_MODEL`/`FAST_MODEL` (each defaults to `OLLAMA_MODEL`): page/source selection + both agent loops use `QUERY_MODEL`, ingest synthesis uses `INGEST_MODEL`, lint uses `FAST_MODEL` — behaviour identical when unset. New `tests/test_schema_loader.py` (5) + 2 `test_ollama_client.py` tests; suite 170 passing (6 pre-existing unrelated failures untouched). |
| 2026-06-02 | **GUI theming pass (Forest/Slate themes + dark mode).** `src/app.py` CSS rewritten as a theme-aware f-string keyed on `st.session_state["theme"]` (`_THEMES` dict: `Forest` light default / `Slate` dark); sidebar `🌙 Dark` / `☀️ Light` toggle. Inter body font (was Source Sans 3) + Libre Baskerville headings; sentence-case 6 px buttons with hover (was all-caps). `.streamlit/config.toml`: `textColor` `#4909ea`→`#1a1f1c`, `secondaryBackgroundColor` `#4d905f`→`#eaf0ec`. Dark-mode fixes: color-only wildcard (font-family on `.stApp *` was breaking Material icon ligatures → showed raw `keyboard_double…`/`upload` text; now an explicit Material Symbols rule protects icon spans); per-surface overrides for file-uploader dropzone, expanders, chat messages, metrics, and **form-submit buttons** (`stFormSubmitButton` — the login "Sign in" was dark-on-green). Expander bg set to page `bg` so `widget_bg` nav-list buttons (Wiki Explorer panel) show as distinct boxes. Sidebar reorg: theme toggle above `DATABASE`, collapsed DB label, matching boxed Reset/Logout (`.st-key-*`). Login form centered in a constrained column. Chat: removed duplicate `**You:**` line (rerun already re-renders via `st.chat_message`); divider + follow-up tooltip. Research: question + auto-save on one row, full-width CTA. Visual/structural only — no backend logic touched. See [docs/ui.md](docs/ui.md) §Theme system. |
