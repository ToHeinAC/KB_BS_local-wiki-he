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
| Test suite | **Done** (130 tests; old 100-cap superseded — see [`docs/tests.md`](docs/tests.md)) |
| `.streamlit/config.toml` | **Done** |

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
| `src/chunker.py` | Structural chunker: legal `§` / markdown headings / paragraph windows with overlap. Content-addressable `chunk_id`. Persists to `data/chunks/<source-slug>.jsonl`. | Done |
| `src/lex_index.py` | BM25 lexical index over chunks. 4 normalized token variants (surface / NFKD / umlaut-digraph / stem). Persists `postings.json` + `stats.json` to `data/index/`. | Done |
| `src/qa_gen.py` | Ingest-time HyDE. `_select_target_chunks` picks the top-`QA_MAX_PAIRS_PER_SOURCE` heading-anchored, densest chunks; one batched LLM call asks for 2–4 questions each; output sliced to the cap. Guarantees ≥1 question per source via retry + title fallback. Persists to `data/index/qa.jsonl`. Folded into BM25 by `lex_index.build()`. `delete_source_entries(name)` rewrites the file in place. | Done |
| `src/ollama_client.py` | `generate()` + `chat()` wrappers; `is_available()` health check | Done |
| `src/schema_loader.py` | `get_system_prompt()` — reads `SCHEMA.md` verbatim | Done |
| `src/wiki_engine.py` | `init_wiki`, three-stage `ingest_begin` / `ingest_piece` / `ingest_end` (source-scoped chunker+qa_gen+select-affected → per-piece LLM synthesis with auto-merged `sources:` frontmatter → single `lex_index.build()`), back-compat `ingest()` wrapper, `rebuild_lex_index`, `delete_source` (cascading: raw + manifest + chunks + qa rows + wiki pages + index rebuild), `query`/`query_with_sources`, `file_answer`, `lint`, `build_link_graph`, `build_typed_graph` (page + source nodes, typed edges), `find_orphans`, `resolve_contradiction`, `list_pages`, `read_page`, `read_page_parsed`, `stats`, `search_wiki`, `get_wiki_tree` | Done |
| `src/app.py` | Streamlit UI, 5 pages, port 8520, NYT editorial style. Maintenance page includes "Delete Source" section with selectbox + confirmation checkbox. | Done |
| `src/prompts.py` | All LLM prompt constants including `WIKI_SEARCH_DESCRIPTION`, `WIKI_READ_DESCRIPTION`, `RESEARCHER_INSTRUCTIONS`, `INGEST_PROMPT`, `GENERATE_QUESTIONS_PROMPT`, etc. | Done |
| `src/tools.py` | Deep-researcher tools: `wiki_search`/`wiki_read`, `tavily_search`, `fetch_webpage_content`, `think_tool`, `submit_final_answer`. Deep-chat tools: `raw_search` (BM25 via `lex_index.query()`), `raw_read` (paginated), `submit_chat_answer` (halved gates). | Done |
| `src/agent.py` | LangGraph deep researcher (plan → wiki-first → triage → expand → submit), wiki index auto-injected into system prompt, ChatOllama backend | Done |
| `src/chat_agent.py` | LangGraph deep chat agent over `data/raw/` originals. Gates: `CHAT_MAX_ITERATIONS=25`, `CHAT_MIN_WORDS=300`, `CHAT_MIN_SOURCES=2`, `CHAT_MIN_SEARCHES=3`. Tokenized prefix-search + paginated reads + section-suffixed citations. Recursion-limit surfaces partial answer. Used by the Chat page in "Deep" mode. | Done |
| `src/template_loader.py` | Reads `templates/insert.md` → ordered list of user-fillable metadata fields | Done |
| `SCHEMA.md` | Wiki schema injected into every LLM system prompt | Done |

---

## 4. Implementation Notes (deviations from PRD)

The mockup simplifies a few planned details — tracked here so future iterations can align:

| Area | PRD intent | Current implementation |
|---|---|---|
| `data/raw/` layout | `uploads/` + `extracted/` subdirs + `.manifest.json` | Flat dir: files + `manifest.json` directly in `data/raw/` |
| LLM page output format | `### FILE:` / `### INDEX_UPDATE` / `### LOG_ENTRY` blocks | `=== filename.md ===` … `=== END ===` blocks |
| `schema_loader.py` | Separate system prompts per operation (ingest/query/lint) | Single `get_system_prompt()` returns full `SCHEMA.md` |
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
| `TAVILY_API_KEY` | — | Required for the Research page (web search). |
| `MAX_INGEST_CHARS` | `40000` | Chunk size for ingest; documents exceeding this are split into sequential chunks |
| `WIKI_DIR` | `data/wiki` | Wiki page storage path |
| `RAW_DIR` | `data/raw` | Raw source file storage path |
| `CHUNKS_DIR` | `data/chunks` | Chunk store path (one JSONL per source) |
| `INDEX_DIR` | `data/index` | Lexical index path (`postings.json`, `stats.json`, `qa.jsonl`) |
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
