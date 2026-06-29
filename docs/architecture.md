---
name: architecture.md
description: System architecture — three-layer Karpathy knowledge model, module boundaries, dataflows
version: 1.2.0
author: Tobias Hein
---

# Architecture

> Authoritative spec: [`PRD.md`](../PRD.md) §2 (System Architecture) and §7 (Dataflow Diagrams).
> Implementation deviations from PRD are tracked in [`IMPLEMENTATION.md`](../IMPLEMENTATION.md) §4.

## Knowledge model

| Layer | Path | Owner | Mutability |
|---|---|---|---|
| 1. Raw sources | `data/raw/` | User uploads | Immutable; LLM **reads only** |
| 2. Retrieval layer | `data/chunks/` + `data/index/` | `chunker` / `lex_index` / `qa_gen` | Auto-rebuilt at ingest; content-addressed |
| 3. Wiki | `data/wiki/` | LLM | LLM owns entirely (ingest/query/lint write here) |
| 4. Schema | `SCHEMA.md` (project root) | Maintainer | Injected into every LLM system prompt |

Layer 2 is the *ground truth for retrieval*: every wiki claim should trace back to one or more chunk ids. Wiki pages are LLM summaries over chunks; the chunks themselves are the citation truth and are searched directly by the deep-chat agent's `raw_search`.

### `data/raw/` layout (current implementation)

Flat directory — no subdirectories:

```
data/raw/
  manifest.json          # SHA-256 → {filename, added_at}
  uploaded-file.pdf      # original upload (immutable)
  another-doc.md
  ...
```

> PRD planned `uploads/` + `extracted/` subdirs and `.manifest.json`. Mockup uses a flat layout. See IMPLEMENTATION.md §4.

### `data/chunks/` + `data/index/` layout

```
data/chunks/
  <source-slug>.jsonl       # one chunk per line, content-addressable chunk_id
data/index/
  postings.json             # BM25 inverted index (4 variants/token)
  stats.json                # N, avg_dl, df, chunk_meta, chunk_dl
  qa.jsonl                  # 1–5 hypothetical questions per source (HyDE)
```

Auto-built on `wiki_engine.ingest()` and rebuildable via
`wiki_engine.rebuild_lex_index()`. qa-gen failures don't break ingest;
the title fallback guarantees ≥1 question per source.

### `data/wiki/` layout

```
data/wiki/
  index.md               # master table of contents (auto-maintained)
  log.md                 # activity + lint log (append-only)
  concept-name.md        # concept pages
  entity-name.md         # entity pages
  summary-<source>.md    # source summary pages
```

## Module boundaries

All Python modules live in `src/`; one file per module, no sub-packages (PRD §4.4).

- **`src/prompts.py`** is the *only* place that defines LLM prompt strings. All other modules import named constants from here: `RESEARCHER_INSTRUCTIONS`, `CHAT_AGENT_SYSTEM`, `INGEST_PROMPT`, `SELECT_PROMPT`, `ANSWER_PROMPT`, `LINT_PROMPT`, `WIKI_SEARCH_DESCRIPTION`, `WIKI_READ_DESCRIPTION`, `TAVILY_SEARCH_DESCRIPTION`, `FETCH_WEBPAGE_DESCRIPTION`, `RAW_SEARCH_DESCRIPTION`, `RAW_READ_DESCRIPTION`, `THINK_TOOL_DESCRIPTION`, `SUBMIT_FINAL_DESCRIPTION`, `SUBMIT_CHAT_DESCRIPTION`, `EVALUATE_CONDITION_DESCRIPTION`.
- **`src/dedup.py`** owns `manifest.json`. Every ingest must call `is_duplicate()` before `register_file()`. The manifest is keyed by `sha256(file_bytes)`; `register_file(file_bytes, filename, content=None)` writes `content` to disk when given (the converted Markdown) while still keying dedup on the original upload bytes. `list_sources()` returns all registered filenames; `deregister_source(name)` removes an entry by filename — used by the cascading delete flow.
- **`src/file_processor.py`** extracts full text from uploaded files (`extract_text()`) and splits large texts into paragraph-bounded chunks (`chunk_text(text, chunk_size=MAX_CHARS)`). Does not write to disk.
- **`src/md_convert.py`** converts non-Markdown uploads (PDF / DOCX / images) to Markdown, ported from [ToHeinAC/MD-maker](https://github.com/ToHeinAC/MD-maker) (Apache-2.0). `convert_to_markdown(file_bytes, filename, on_progress=None)` dispatches by extension: **PDF** → `iter_pdf_pages()` (pypdfium2; a page with ≥ `TEXT_THRESHOLD`=40 extractable chars is LLM-rewritten via `rewrite_text()`, otherwise rasterized at `PDF_DPI` and OCR'd via `convert_image()`); **DOCX** → deterministic `extract_docx_text()` (headings/lists/tables, no LLM); **image** → `convert_image()` OCR. `is_convertible(filename)` gates the uploader. All Ollama calls route through `ollama_client.ocr()` / `.rewrite()`; all prompts live in `prompts.py`. Env: `OCR_MODEL` (default `deepseek-ocr:3b`), `REWRITE_MODEL` (default `OLLAMA_MODEL`), `PDF_DPI` (default 150).
- **`src/chunker.py`** structural chunker. `split(text)` returns a list of `{chunk_id, anchor, heading_path, char_start, char_end, text, lang}` dicts using one of three strategies: legal `§` headers, markdown `##`/`###`, or paragraph windows with overlap. `chunk_id = sha256(normalized)[:16]` is content-addressable so re-ingest is idempotent and diffable. `write_chunks()`/`load_chunks()`/`all_chunks()` persist to `data/chunks/<source-slug>.jsonl`.
- **`src/lex_index.py`** BM25 lexical index over chunks. `build(chunks=None)` writes `postings.json` and `stats.json`; with no args it indexes raw source chunks (`scope="raw"`) **plus** wiki page pseudo-chunks (`scope="wiki"`, R-1) generated by `_wiki_chunks()` (each page body, prefixed with its title + filename stem, split via `chunker`; text stored inline in `chunk_meta` since these aren't in `data/chunks/`). `query(q, top_k, scope=None)` ranks chunks via BM25 (k1=1.5, b=0.75); `scope` filters to `"raw"` / `"wiki"` (a pre-R-1 chunk with no scope counts as `"raw"`). Each surface word is stored under up to four normalized variants — surface lower-cased, NFKD-strip (ü→u), umlaut digraph (ü→ue, ß→ss), and a light German+English suffix stem — so queries match regardless of writing style. No external NLP deps; built-in stopword list per language.
- **`src/qa_gen.py`** ingest-time hypothetical-question generator (HyDE, lexical-only). `_select_target_chunks` ranks chunks (anchored > densest > longest > stable) and keeps the top `QA_MAX_PAIRS_PER_SOURCE` (default 5). One batched LLM call asks for 2–4 short questions per kept chunk; the output is sliced to the per-source cap. If the LLM returns nothing usable, retries once at a higher temperature; if still empty, emits one source-title fallback question. Persists `(chunk_id, question)` rows to `data/index/qa.jsonl`. `lex_index.build()` folds question tokens into the parent chunk's term frequencies (but not its doc length, so BM25 b-normalization stays honest). `delete_source_entries(name)` rewrites `qa.jsonl` in place, removing rows for the given source.
- **`src/ollama_client.py`** is the *only* place that imports `ollama`. Exposes `generate(system, prompt, temperature, model_id=None)`, `chat()`, `is_available()`, plus `ocr(model_id, prompt, image_b64)` (vision call with one base64 image) and `rewrite(model_id, prompt)` (text reformat with a per-call model id) used by `md_convert.py`. Per-role model overrides `_QUERY_MODEL` / `_INGEST_MODEL` / `_FAST_MODEL` (env `QUERY_MODEL`/`INGEST_MODEL`/`FAST_MODEL`, each falling back to `OLLAMA_MODEL`) let selection, synthesis, and lint use different models; callers pass the resolved id as `model_id`.
- **`src/schema_loader.py`** is the *only* place that reads `SCHEMA.md` / `SCHEMA_QUERY.md`. `get_system_prompt(mode="full"|"query")`: `full` returns `SCHEMA.md` (page-type templates — for ingest and any call that writes pages); `query` returns the trimmed `SCHEMA_QUERY.md` (writing rules + confidence only — for read/answer/describe/lint), falling back to full if the query file is absent.
- **`src/wiki_engine.py`** is the *only* writer to `data/wiki/`. Owns `init_wiki()`, three-stage `ingest_begin` / `ingest_piece` / `ingest_end` (back-compat single-call `ingest()` still exists), `delete_source(name)` (cascading: unlinks raw file → `dedup.deregister_source` → chunk JSONL → `qa_gen.delete_source_entries` → all wiki pages whose `sources:` frontmatter starts with the source name → `lex_index.build()` + `_rebuild_index()` + log), `query()`, `lint()`, `list_pages()`, `read_page()`, `read_page_parsed()`, `stats()`, `search_wiki()`, `get_wiki_tree()`, `rebuild_lex_index()`, `build_link_graph()` (untyped, for `find_orphans`), `build_typed_graph()` (typed page + source nodes for the viz; `summary-*` sources are excluded from source nodes; `related-to` edges come only from explicit `related:` frontmatter — co-source implicit edges were removed). `ingest_piece` auto-merges `sources:` frontmatter on every page it writes so the typed graph can draw `derived-from` edges regardless of what the LLM emitted. `read_page_parsed()` strips YAML frontmatter and returns `{content, sources, related}` for clean UI rendering. The three-stage split keeps source-scoped work (chunker, qa_gen, the `_source_to_pages` reverse map) out of the per-piece loop, dropping long-source ingest from ~30 min to ~7 min. Affected-page selection is per-piece and BM25-driven (`_select_affected_pages` queries the prior lexical index `scope="raw"`, maps hit `source` fields back to wiki pages, ranks them; no LLM call), surfaced to the model as a cheap key-facts candidate index (`_build_candidate_index_block`) rather than full bodies — because **merge is now deterministic in code, not prompt-driven**. To survive a small model (`gemma4:e4b`), the engine decides page identity itself: one stable `summary-<source>.md` slug per document (killing the per-`[Teil n/m]` summary explosion), and `_route_page` redirects a freshly-synthesised concept/entity page into an existing near-duplicate (exact canonical-token match, or a subset specialization gated by ≥0.7 `key_terms` overlap; `_canonical_slug_tokens` uses the lex stemmer + a `_depluralize` pass so `dense-llms`≡`dense-llm`). The target is then merged with `_merge_pages` (section/line union — no prior fact dropped — + `_contradiction_check` that only auto-resolves numeric conflicts when a frontmatter date proves which source is newer, else flags `## Contradictions` and lowers confidence). Every page carries a leading `## Key facts` index + `key_terms:` frontmatter (the cheap update-vs-create signal). `consolidate(db, dry_run, llm_polish)` (+ `scripts/dedup_wiki.py` CLI, dry-run default) is the one-off pass that collapsed the pre-existing chunk-derived duplicates across all DBs using the same routing/merge primitives. `search_wiki()` is BM25 over the wiki-scoped index (R-1), not an O(n·m) string scan. `query_with_sources()` selects pages hybridly (Q-1): `_candidate_pages_for_query` builds a candidate set from wiki- and raw-scope BM25 hits, the LLM re-ranks only those (falling back to full-index selection when BM25 is empty), then synthesis injects the top `_QUERY_CHUNKS_PER_PAGE` wiki chunks per page with their anchors rather than full pages (Q-3), capped at `_QUERY_SYNTH_MAX_CHARS`. **Lifecycle (E-1/E-2):** `is_page_stale(meta, today)` / `stale_pages()` flag pages past their freshness window (`updated` + the page's `expires_after_days` frontmatter, else `STALE_AFTER_DAYS` default 365); `get_wiki_tree()` annotates each page `stale` (⚠️ in the UI tree) and `lint()` is date-aware and prepends a programmatic stale list. `list_pages(include_insights=True)` also lists `insights/*.md` (type forced to `insight`); `lint()` scans them and `_rebuild_index()` gives them a separate `## Insights` section — the default arg leaves all other consumers unchanged.
- **`src/template_loader.py`** reads `templates/insert.md` and returns the ordered list of user-fillable metadata field names via `load_insert_template()`.
- **`src/run_memory.py`** — per-invocation "visited" scratchpad shared by the chat and research agents. A `RunMemory` dataclass holds `reads: dict[str,int]` (key → step first seen) and `searches: dict[str,int]`, plus a monotonically-incrementing `step` counter. Scoped via a `contextvars.ContextVar`; `begin_run()` resets it at the top of `run_chat_agent` / `run_research_agent`, `current()` returns the active memory (or `None` for direct `tools.py` callers / tests that never started a run). Pure Python, no LangChain.
- **`src/tools.py`** — agent tools wired as `langchain_core.tools`. **Research tools** (`TOOLS`): `wiki_search`, `wiki_read`, `tavily_search`, `fetch_webpage_content`, `think_tool`, `submit_final_answer` (word/source gates → writes to `data/wiki/comparisons/`; counts `https://` URLs and `[Wiki: filename.md]` citations toward `RESEARCH_MIN_URLS`), `evaluate_condition`. **Chat tools** (`CHAT_TOOLS`): `raw_search` (BM25 over the chunk store via `lex_index.query()`; returns ranked hits with `chunk_id`, anchor, matched terms, score), `raw_read` (bulk read; a `§X`/`#section` suffix resolves to that section's chunk text via `chunker.load_chunks` — works for legal `§` and markdown headings — with a footer naming the next section; bare filenames use the `offset` parameter for 16000-char-window byte-pagination with a `[truncated; pass offset=N to continue]` footer), `think_tool`, `submit_chat_answer` (word/source gates; returns to caller, no file written), `evaluate_condition`. **Loop guard** — `wiki_read`, `raw_read`, `wiki_search`, and `raw_search` consult `run_memory.current()` before delegating to their `_impl` helper. Exact-duplicate calls return a one-line `[memory] Already read/searched … at step N` stub instead of re-fetching, breaking the "same doc over and over until `MAX_ITER`" loops weaker local models fall into. Keys: `wiki:{filename}`, `raw:{base}:{offset}` for bare reads (a fresh `offset` still paginates) and `raw:{base}|sec={canon}:{offset}` for section reads (distinct sections = distinct reads, so the guard no longer collapses every section to offset 0; a blocked section read lists the file's unread anchors), `wsearch:{q.lower()}`, `rsearch:{q.lower()}`. **Pagination nudge** — once `RAW_READ_NUDGE_AFTER` (default 2, env `CHAT_RAW_READ_NUDGE_AFTER`) distinct byte-offset windows of one file have been read in a run, the `raw_read` result appends a `[memory] … Stop paginating — call submit_chat_answer now …` line so a weak model answers instead of walking a whole document window-by-window (section reads are exempt — they're intentional). Multi-file / multi-query batches dedup per-item — unseen items still run through `_impl`, seen items are replaced with the stub and results joined. Pure wrapper layer; `_impl` helpers, BM25, and `wiki_engine` are untouched. **Shared tool — `evaluate_condition`**: accepts a `facts` dict of named values (numeric / string / list) extracted from source text and a nested-dict `condition` tree; the LLM only assembles facts and the tree, while Python deterministically walks the tree using `operator`-module dispatch. Node shapes: comparison (`>`,`>=`,`<`,`<=`,`==`,`!=`), `in` (membership), `contains` (substring), `between` (inclusive range), `not`, `and`/`or`. Returns a facts table, a per-leaf TRUE/FALSE trace, and a final `Result: PASS|FAIL`. Errors (missing fact, unknown op, type mismatch) become FALSE leaves with explanatory messages — the tool never raises. `_RAW_CITE_RE` accepts an optional trailing ` §...` / ` #...` section marker so distinct sections of the same long file count as distinct sources for `CHAT_MIN_SOURCES`. Descriptions imported from `prompts.py`. Only `agent.py`, `chat_agent.py`, and `tools.py` may import LangChain-family packages.
- **`src/agent.py`** — owns the deep-researcher LangGraph state machine (`ChatOllama.bind_tools(TOOLS)` agent node + `ToolNode`). `_load_wiki_index()` injects `data/wiki/index.md` into the system prompt so the agent knows which pages exist before any tool call. Public generator `run_research_agent(question, wiki_context)` yields `thought` / `tool_call` / `tool_result` / `final_answer` / `error` step dicts. Calls `run_memory.begin_run()` at the top of every invocation so the per-run visited-set starts empty.
- **`src/chat_agent.py`** — owns the deep-chat LangGraph state machine (`ChatOllama.bind_tools(CHAT_TOOLS)` agent node + `ToolNode`). `_build_raw_index()` injects a one-line-per-file index of `data/raw/` (first markdown heading per file) into the system prompt. Public generator `run_chat_agent(question)` yields the same step-dict shape as the research agent. **Stall recovery** mirrors `agent.py`: if the agent reaches a terminal no-answer state, `_synthesize_fallback(question, all_messages)` makes one plain `ollama_client.generate` call (`CHAT_FALLBACK_SYSTEM` / `CHAT_FALLBACK_PROMPT`, notes capped at `CHAT_FALLBACK_NOTES_CAP=12000`) to write a grounded answer from the gathered `ToolMessage` notes instead of discarding them — only a truly empty run still yields the bare error. On `GRAPH_RECURSION_LIMIT`, the loop surfaces a partial answer and `_with_iter_hint()` appends an end-of-answer `*Hint: … iteration limit (N) … may be partial.*` note to every final answer produced that way. Calls `run_memory.begin_run()` at the top of every invocation so the per-run visited-set starts empty.
- **`src/db_context.py`** — active-database context. Each DB is an isolated subtree `$DATA_ROOT/<db>/{raw,chunks,index,wiki}`; the active DB name is held in a `contextvars.ContextVar` so every data module resolves paths via the getters (`wiki_dir()`/`raw_dir()`/`chunks_dir()`/`index_dir()`, all derived from `get_active_db()`) instead of import-time constants. `set_active_db()`/`get_active_db()`, `list_dbs()`/`create_db()`, `is_valid_db_name()`, `users_json_path()` (shared `$DATA_ROOT/users.json`), `migrate_legacy_layout()` (moves pre-multi-DB top-level data into `data/Strahlenschutz/`). No LangChain.
- **`src/auth.py`** is the *only* reader/writer of `data/users.json` (gitignored). bcrypt password hashes; per-user `dbs` read-allowlist, global `is_admin` flag, and per-DB `maintains` write-list. **Access model:** access (`dbs`) lets a user read/chat against a DB; **maintainer** (`maintains`) lets them *change* it (upload sources, delete data). `is_maintainer(user, db)` is exactly `db in maintains` — admin is **not** an implicit maintainer (assignment is explicit per DB). `grant_maintainer(user, db)` adds a DB to both lists in one write (a maintainer must also have read access). `ensure_seeded()` creates default admin `T. Hein`/`k-wiki` (maintains `Strahlenschutz`); `backfill_maintainers()` is an idempotent migration giving pre-existing admins `maintains = dbs`. Other API: `verify`, `add_user`, `delete_user`, `set_user_dbs`, `set_user_maintains`, `change_password`, `user_dbs`, `user_maintains`, `is_admin`, `list_users`. No LangChain.
- **`src/app.py`** is the UI shell (Streamlit, port 8520). Calls `wiki_engine`, `agent`, and `chat_agent`; never writes wiki files directly. A login gate + sidebar DB selector (scoped to the user's `dbs` allowlist) front every page; the chosen DB is pushed to `db_context.set_active_db()` before any page handler runs. `_can_maintain = auth.is_maintainer(user, active_db)` gates write access: non-maintainers lose the "Upload" nav entry and the Maintenance Delete-Source/Reset-all sections (read-only tools — stats, lint, activity log — stay), and admins assign maintainers at DB creation and per-user in the admin-only Users panel. `_raw_source_button()` strips `§`/`#` section suffixes before resolving citations to files in `data/raw/`. Chat-Deep streams steps live (thought / tool_call / tool_result / final_answer) as they arrive; past answers include a "Download answer" button. Research page renders the saved report inline with a "Download report" button.

## Key dataflows

### Ingest

```
upload → dedup.is_duplicate()                  # keyed on original upload bytes
       → [non-.md] md_convert.convert_to_markdown()  # PDF/DOCX/image → Markdown, edited in UI preview
       → dedup.register_file(raw, name, content=md)  # stores converted .md in data/raw/
       → [.md] file_processor.extract_text()  # returns FULL text (no truncation)
       → file_processor.chunk_text(text)      # [text] if ≤MAX_INGEST_CHARS, else N chunks
       → [Upload UI] optional metadata form driven by template_loader.load_insert_template()
       → wiki_engine.ingest_begin(full_text, source_name, user_meta)   # ONCE per source
           → schema_loader.get_system_prompt()                          # mode="full"
           → chunker.split(full_text) → chunker.write_chunks()         # whole-document
           → qa_gen.generate() + persist()                              # if INGEST_QA=1, 1–QA_MAX_PAIRS_PER_SOURCE
           → _source_to_pages() + _build_registry()                     # reverse map + routing registry (cached in ctx)
           → summary_slug = one stable summary-<source>.md for the whole doc (NOT per-Teil)
           → return ctx (system, index_text, meta_block, src_to_pages, registry, summary_slug, affected[], chunks, …)
       → for each piece in file_processor.chunk_text(full_text):       # per 40 KB cut
           wiki_engine.ingest_piece(ctx, piece, i, n)
             → _select_affected_pages(piece, ctx[src_to_pages])         # BM25 over prior index → ranked pages (no LLM)
             → _build_candidate_index_block(ranked)                     # cheap key-facts index nudge (NOT full bodies)
             → ollama_client.generate(system, INGEST_PROMPT, temperature=0.3, model_id=_INGEST_MODEL)
             → parse "=== filename.md ===" blocks + UPDATE:/CONTRADICTION: lines
             → _ensure_key_terms + _ensure_index_block (## Key facts)
             → _resolve_target: source-summary→summary_slug; concept/entity→_route_page(registry) dedup
             → if target exists: _merge_pages (deterministic union + contradiction check); else write
             → update ctx[registry]; accumulate created/updated/contradictions
       → wiki_engine.ingest_end(ctx)                                    # ONCE per source
             → lex_index.build()                                        # single rebuild
             → _rebuild_index() + _append_log()
             → return {created, updated, contradictions, affected, chunks}
```

LLM output format for ingest:
```
=== filename.md ===
---
title: "..."
type: concept | entity | source-summary
...
---
Page content.
=== END ===
UPDATE: existing-page.md
CONTRADICTION: brief description
```

### Query

```
wiki_engine.query_with_sources(question)
  → read index.md
  → ollama_client.generate(select prompt, temperature=0.1)  # pick ≤5 filenames
  → load selected pages from data/wiki/
  → extract raw_sources from page frontmatter `sources` field
  → ollama_client.generate(answer prompt, temperature=0.7)
  → return {answer, sources (wiki filenames), raw_sources (original data/raw/ filenames)}
```

`app.py` Chat page and Wiki Explorer both render sources in a collapsible "Sources" expander (original `data/raw/` documents + related wiki pages).

### Deep chat (Chat page "Deep" mode, `src/chat_agent.py`)

Same LangGraph shape as the deep researcher but scoped to `data/raw/` only:

```
START → agent (ChatOllama.bind_tools(CHAT_TOOLS)) → conditional router
                                                     ├─ tools → agent (loop)
                                                     └─ END on no tool_calls
                                                              or submit_chat_answer ACCEPTED
```

Tools bound: `raw_search` (BM25 over `data/chunks/` via `lex_index.query()`; returns chunk-level hits with anchors and scores), `raw_read` (paginated bulk read; 16000-char window per call, `offset` param, footer with continuation hint, plus a "stop paginating / submit now" nudge after `RAW_READ_NUDGE_AFTER` windows of one file), `think_tool`, `submit_chat_answer` (gates: `CHAT_MIN_WORDS` / `CHAT_MIN_SOURCES`; section-suffixed citations count as distinct). No web tools. The system prompt (`prompts.CHAT_AGENT_SYSTEM`) pre-loads a one-line-per-file index of `data/raw/` and instructs the agent to use single-stem keywords (not full sentences) and to read distinct `§`/`#` sections taken verbatim from `raw_search` hits (with byte `offset` only as the fallback for section-less files).

Gates roughly halved vs research for ~2× speed, with one extra iteration headroom for pagination: `CHAT_MAX_ITERATIONS=25`, `CHAT_MIN_WORDS=300`, `CHAT_MIN_SOURCES=2`, `CHAT_MIN_SEARCHES=3`. On accept, the answer is returned to the UI (no file written); the existing manual "Save to wiki" button writes to `data/wiki/insights/` as in Fast mode. If the agent stalls without submitting, a fallback pass synthesises an answer from the gathered notes (tagged "assembled from gathered notes"); if the recursion limit is hit, every surfaced answer also carries an end-of-answer `*Hint: … iteration limit (N) … may be partial.*` note instead of a bare error.

The Chat page exposes a `Fast | Deep` radio toggle: Fast → `wiki_engine.query_with_sources` (existing one-shot RAG over wiki pages); Deep → `chat_agent.run_chat_agent` (this loop). In Deep mode, steps are streamed live as they arrive (thoughts in collapsible expanders, tool calls as info banners, tool results truncated to 800 chars in expanders) — no spinner wait. Past Deep-mode messages show a "Download answer" button alongside the "Agent trace" expander.

### Lint

```
wiki_engine.lint()
  → read all *.md in data/wiki/ + data/wiki/insights/ (except index + log)
  → ollama_client.generate(date-aware health-check prompt, temperature=0.3, model=FAST_MODEL)
  → prepend programmatic checks (orphans + possibly-stale pages)
  → append report to log.md
  → return report string
```

### Deep researcher (Research page, `src/agent.py`)

Ported from `ToHeinAC/deepagents_ollama`. LangGraph `StateGraph` over `MessagesState`, two nodes:

```
START → agent (ChatOllama.bind_tools) → conditional router
                                          ├─ tools (ToolNode) → agent      (loop)
                                          └─ END   when last AIMessage has no tool_calls,
                                                   or submit_final_answer returned ACCEPTED
```

Phases enforced via the system prompt (`prompts.RESEARCHER_INSTRUCTIONS`):
1. **PLAN** — `think_tool` once at the start; break question into 3–6 sub-questions.
2. **WIKI FIRST** — first non-think tool call **must** be `wiki_search` (parallel batch). The system prompt pre-loads `data/wiki/index.md` so the agent already knows which pages exist.
3. **TRIAGE** — `think_tool` after every tool result with three required sections: `Have:` / `Gaps vs original query:` / `Next:`. Tangential threads must be listed under `Parked (out of scope):` and not pursued.
4. **AUTONOMOUS EXPANSION** — `wiki_read` for promising hits; `tavily_search` only for gaps the wiki cannot fill; optional `fetch_webpage_content` for high-value URLs.
5. **SUBMIT** — `submit_final_answer(title, answer)`. Validates `>= RESEARCH_MIN_WORDS` words and `>= RESEARCH_MIN_URLS` unique sources (URLs + `[Wiki: filename.md]` citations). Rejected reports send the agent back to research.

Quality gates and recursion cap are env-tunable (`RESEARCH_MIN_SEARCHES`, `RESEARCH_MIN_WORDS`, `RESEARCH_MIN_URLS`, `RESEARCH_MAX_ITERATIONS`). LangChain/LangGraph imports are scoped to this module + `src/tools.py` only (CLAUDE.md §5.3).

## Concurrency & state

Synchronous everywhere except the agent I/O layer. `tavily_search`, `fetch_webpage_content`, `wiki_search`, `wiki_read`, `raw_search`, and `raw_read` fan out across a `concurrent.futures.ThreadPoolExecutor` (size = `RESEARCH_PARALLELISM`, default 4 — shared by research and chat tools). LLM calls remain sequential — local single-GPU; parallel LLM calls would just queue. No asyncio at any boundary.

State is files + JSON only — no database, no cache (PRD §4.4).
