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
| `src/extractor.py` | **Done** |
| `src/qa_gen.py` | **Done** |
| Test suite | **Done** (135 tests; old 100-cap superseded — see [`docs/tests.md`](docs/tests.md)) |
| `.streamlit/config.toml` | **Done** |

All planned modules implemented plus a retrieval layer (Tiers 1.1–1.4 of the retrieval optimisation: chunk store + BM25 lexical index + ingest-time entity/term/fact extraction + hypothetical-question chunks).

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
| `src/dedup.py` | SHA-256 dedup; flat `data/raw/` store + `manifest.json` | Done |
| `src/file_processor.py` | Extract text from PDF/DOCX/MD/TXT/HTML; `chunk_text()` splits large docs at paragraph boundaries | Done |
| `src/chunker.py` | Structural chunker: legal `§` / markdown headings / paragraph windows with overlap. Content-addressable `chunk_id`. Persists to `data/chunks/<source-slug>.jsonl`. | Done |
| `src/lex_index.py` | BM25 lexical index over chunks. 4 normalized token variants (surface / NFKD / umlaut-digraph / stem) + trigram fuzzy fallback. Query expansion via aliases+acronyms. `facts_lookup()` shortcut for numeric questions. Persists to `data/index/`. | Done |
| `src/extractor.py` | Ingest-time structured-data extractor. One LLM call per source → strict JSON `{aliases, acronyms, terms, facts}`. Idempotent merge into `data/index/`. Best-effort. | Done |
| `src/qa_gen.py` | Ingest-time HyDE: 2–4 hypothetical questions per chunk via batched LLM calls. Persists to `data/index/qa.jsonl`. Folded into BM25 by `lex_index.build()`. Best-effort. | Done |
| `src/ollama_client.py` | `generate()` + `chat()` wrappers; `is_available()` health check | Done |
| `src/schema_loader.py` | `get_system_prompt()` — reads `SCHEMA.md` verbatim | Done |
| `src/wiki_engine.py` | `init_wiki`, `ingest` (now: chunker → extractor → qa_gen → lex_index.build → two-pass LLM page-synthesis), `rebuild_lex_index`, `query`/`query_with_sources`, `file_answer`, `lint`, `build_link_graph`, `find_orphans`, `resolve_contradiction`, `list_pages`, `read_page`, `read_page_parsed`, `stats`, `search_wiki`, `get_wiki_tree` | Done |
| `src/app.py` | Streamlit UI, 5 pages, port 8520, NYT editorial style | Done |
| `src/prompts.py` | All LLM prompt constants including `WIKI_SEARCH_DESCRIPTION`, `WIKI_READ_DESCRIPTION`, `RESEARCHER_INSTRUCTIONS`, `INGEST_PROMPT`, `EXTRACT_TERMS_PROMPT`, `GENERATE_QUESTIONS_PROMPT`, etc. | Done |
| `src/tools.py` | Deep-researcher tools: `wiki_search`/`wiki_read`, `tavily_search`, `fetch_webpage_content`, `think_tool`, `submit_final_answer`. Deep-chat tools: `raw_search` (BM25 via `lex_index.query()` + facts-lookup shortcut), `raw_read` (paginated), `submit_chat_answer` (halved gates). | Done |
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
| `INDEX_DIR` | `data/index` | Lexical index + sidecars path |
| `INGEST_EXTRACT` | `1` | Run `extractor` during ingest (aliases/acronyms/terms/facts). Set `0` to disable. |
| `INGEST_QA` | `1` | Run `qa_gen` during ingest (hypothetical questions). Set `0` to disable. |
| `QA_BATCH_SIZE` | `12` | Number of chunks per `qa_gen` LLM batch. |
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
