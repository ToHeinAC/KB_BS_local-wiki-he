---
name: architecture.md
description: System architecture — three-layer Karpathy knowledge model, module boundaries, dataflows
version: 1.4.0
author: Tobias Hein
---

# Architecture

> Authoritative spec: [`PRD.md`](../PRD.md) §2 (System Architecture) and §7 (Dataflow Diagrams).
> Implementation deviations from PRD are tracked in [`IMPLEMENTATION.md`](../IMPLEMENTATION.md) §4.

## Knowledge model

| Layer | Path | Owner | Mutability |
|---|---|---|---|
| 1. Raw sources | `data/raw/` | User uploads | Immutable; LLM **reads only** |
| 2. Retrieval layer | `data/chunks/` + `data/index/` | `chunker` / `lex_index` (lexical) / `embed_index` (semantic) / `retrieval` (RRF fusion) / `qa_gen` | Auto-rebuilt at ingest; content-addressed |
| 3. Wiki | `data/wiki/` | LLM | LLM owns entirely (ingest/query/lint write here) |
| 4. Schema | `SCHEMA.md` (project root) | Maintainer | Injected into every LLM system prompt |

Layer 2 is the *ground truth for retrieval*: every wiki claim should trace back to one or more chunk ids. Wiki pages are LLM summaries over chunks; the chunks themselves are the citation truth and are searched directly by the deep-chat agent's `raw_search`. Retrieval is **hybrid** (Stage C): a lexical FTS5 arm — the grounding/citation source of truth — fused with an optional local-embedding arm via Reciprocal Rank Fusion (`src/retrieval.py`). The semantic arm is a pure derived cache and degrades gracefully to lexical-only when a DB has no vectors, so it can never regress the lexical baseline. On the Deep answer paths a third signal reorders the fused list: an optional in-process cross-encoder (`src/rerank.py`, Stage D), which likewise fails open to plain fusion.

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
  chunks.sqlite             # SQLite FTS5 index (4 variants/token in `terms`, bm25())
  vectors.npy               # semantic arm: float16 L2-normalized embedding matrix (Stage C, optional)
  vectors.json              # embedding model name + aligned per-row chunk meta
  qa.jsonl                  # 1–5 hypothetical questions per source (HyDE)
```

Auto-built on `wiki_engine.ingest()` and rebuildable via
`wiki_engine.rebuild_lex_index()`. qa-gen failures don't break ingest;
the title fallback guarantees ≥1 question per source.

### `data/wiki/` layout

Each `data/<db>/wiki/` is a conformant **Open Knowledge Format (OKF v0.1)**
bundle (see [okf.md](okf.md)): markdown *Concept* documents with a non-empty
`type`, reserved `index.md`/`log.md`, cross-links as relationships, and a
`## Citations` section. OKF fields are stamped deterministically by `src/okf.py`
(no LLM), so a small local model can't break conformance.

```
data/wiki/
  index.md               # OKF bundle root: frontmatter okf_version + # Pages/# Insights
  log.md                 # OKF date-grouped activity log (## YYYY-MM-DD, newest first)
  concept-name.md        # concept pages (type: concept)
  entity-name.md         # entity pages (type: entity)
  summary-<source>.md    # source summary pages (type: source-summary)
```

## Module boundaries

All Python modules live in `src/`; one file per module, no sub-packages (PRD §4.4).

- **`src/prompts.py`** is the *only* place that defines LLM prompt strings. All other modules import named constants from here: `RESEARCHER_INSTRUCTIONS`, `CHAT_AGENT_SYSTEM`, `INGEST_PROMPT`, `SELECT_PROMPT`, `ANSWER_PROMPT`, `LINT_PROMPT`, `WIKI_SEARCH_DESCRIPTION`, `WIKI_READ_DESCRIPTION`, `TAVILY_SEARCH_DESCRIPTION`, `FETCH_WEBPAGE_DESCRIPTION`, `RAW_SEARCH_DESCRIPTION`, `RAW_READ_DESCRIPTION`, `THINK_TOOL_DESCRIPTION`, `SUBMIT_FINAL_DESCRIPTION`, `SUBMIT_CHAT_DESCRIPTION`, `EVALUATE_CONDITION_DESCRIPTION`, and the per-language `RESPONSE_LANGUAGE_DIRECTIVE` / `INGEST_LANGUAGE_DIRECTIVE` maps (selected in code by `src/lang.py`).
- **`src/dedup.py`** owns `manifest.json`. Every ingest must call `is_duplicate()` before `register_file()`. The manifest is keyed by `sha256(file_bytes)`; `register_file(file_bytes, filename, content=None)` writes `content` to disk when given (the converted Markdown) while still keying dedup on the original upload bytes. `list_sources()` returns all registered filenames; `deregister_source(name)` removes an entry by filename — used by the cascading delete flow.
- **`src/file_processor.py`** extracts full text from uploaded files (`extract_text()`) and splits large texts into paragraph-bounded chunks (`chunk_text(text, chunk_size=MAX_CHARS)`). Does not write to disk.
- **`src/md_convert.py`** converts non-Markdown uploads (PDF / DOCX / images) to Markdown, ported from [ToHeinAC/MD-maker](https://github.com/ToHeinAC/MD-maker) (Apache-2.0). `convert_to_markdown(file_bytes, filename, on_progress=None)` dispatches by extension: **PDF** → `iter_pdf_pages()` (pypdfium2; a page with ≥ `TEXT_THRESHOLD`=40 extractable chars is LLM-rewritten via `rewrite_text()`, otherwise rasterized at `PDF_DPI` and OCR'd via `convert_image()`); **DOCX** → deterministic `extract_docx_text()` (headings/lists/tables, no LLM); **image** → `convert_image()` OCR. `is_convertible(filename)` gates the uploader. All Ollama calls route through `ollama_client.ocr()` / `.rewrite()`; all prompts live in `prompts.py`. Env: `OCR_MODEL` (default `deepseek-ocr:3b`), `REWRITE_MODEL` (default `LiquidAI/lfm2.5-1.2b-instruct:latest` — a small fixed model, since the rewrite only adds structure and never rewords; ~8x faster than a large model at equal fidelity and independent of `OLLAMA_MODEL`), `PDF_DPI` (default 150).
- **Retrieval layer** (`src/chunker.py`, `src/lex_index.py`, `src/embed_index.py`, `src/retrieval.py`, `src/rerank.py`, `src/qa_gen.py`) — chunk store, lexical + semantic arms, RRF fusion and the cross-encoder reranker. Documented in [retrieval.md](retrieval.md).
- **`src/ollama_client.py`** is the *only* place that imports `ollama`. Exposes `generate(system, prompt, temperature, model_id=None)`, `chat()`, `is_available()`, plus `ocr(model_id, prompt, image_b64)` (vision call with one base64 image) and `rewrite(model_id, prompt)` (text reformat with a per-call model id) used by `md_convert.py`. Per-role model overrides `_QUERY_MODEL` / `_INGEST_MODEL` / `_FAST_MODEL` (env `QUERY_MODEL`/`INGEST_MODEL`/`FAST_MODEL`, each falling back to `OLLAMA_MODEL`) let selection, synthesis, and lint use different models; callers pass the resolved id as `model_id`.
- **`src/okf.py`** enforces Open Knowledge Format (OKF v0.1) conformance — deterministic, no LLM, no prompt strings (never imports `wiki_engine`). `apply_to_page(content, db)` stamps recommended frontmatter (`description`/`tags`/`resource`/`timestamp`), guarantees a non-empty `type` (OKF's one hard rule), and regenerates a `## Citations` section from `sources:`; `enrich_frontmatter`, `render_citations`, `add_log_entry`/`reformat_log` (OKF date-grouped log), and `okf_validate(wiki_dir)` (conformance gate). **Every** wiki-page writer routes through `apply_to_page` — `wiki_engine` (`ingest_piece`/`_merge_pages`/`file_answer`/`resolve_contradiction`) and the research-report tool in `tools.py`; `scripts/okf_migrate.py` backfills existing DBs. See [okf.md](okf.md).
- **`src/schema_loader.py`** is the *only* place that reads `SCHEMA.md` / `SCHEMA_QUERY.md`. `get_system_prompt(mode="full"|"query")`: `full` returns `SCHEMA.md` (page-type templates — for ingest and any call that writes pages); `query` returns the trimmed `SCHEMA_QUERY.md` (writing rules + confidence only — for read/answer/describe/lint), falling back to full if the query file is absent.
- **`src/lang.py`** — deterministic language pinning (Layer 1; no external deps, imports only `prompts`). `detect(text, default="de")` classifies DE/EN by function-word counts over start/middle/end windows (an English abstract can't decide a German paper); an umlaut/ß only breaks a tie (so "Jürgen Müller" can't flip an English sentence), no signal → German, the corpus language. `response_directive(text)` / `ingest_directive(text)` return the matching **native-language** directive constant (`prompts.RESPONSE_LANGUAGE_DIRECTIVE` / `INGEST_LANGUAGE_DIRECTIVE`). Ingest pins the **source** language; wiki-chat + both agents pin the **query** language. Detection stays in code (small-model-safe); the wording lives in `prompts.py`; `## Key facts`, citations, and numbers are exempt from translation. Consumed by `wiki_engine` (ingest system prompt + answer prompt), `agent`, and `chat_agent` (system prompt + budget nudge + stall fallback).
- **`src/page_lang.py`** — page-language pinning (see §Page language): a page's pinned language, foreign-line runs, original-term extraction, the verified `translate()` call and the labelled-quote fallback. Pure helpers; `wiki_engine` does all writing.
- **`src/wiki_engine.py`** is the *only* writer to `data/wiki/`. Owns `init_wiki()`, three-stage `ingest_begin` / `ingest_piece` / `ingest_end` (back-compat single-call `ingest()`; `ingest_as_source()` registers the text in `data/raw/` first), `delete_source(name)` (cascading: raw file → `dedup.deregister_source` → chunk JSONL → `qa_gen.delete_source_entries` → wiki pages whose `sources:` start with the name → index rebuild + log), `query()` / `query_with_sources()`, `lint()`, `list_pages()`, `read_page(_parsed)()` (frontmatter stripped → `{content, sources, related}`), `stats()`, `search_wiki()` (BM25 over the wiki scope, not a string scan), `get_wiki_tree()`, `rebuild_lex_index()`, `build_link_graph()` (for `find_orphans`) and `build_typed_graph()` (page + source nodes; `related-to` edges only from explicit `related:`; `summary-*` excluded from source nodes), `normalize_pages(dry_run)` (§Page language). **Page identity and merge are deterministic in code**, not prompt-driven, so they survive a 4B model: one stable `summary-<source>.md` per document; `_route_page` redirects a new concept/entity page into an existing near-duplicate (exact canonical-token match on title or `aliases`, or a subset specialization gated by ≥0.7 `key_terms` overlap; `_canonical_slug_tokens` folds umlauts, stems and depluralizes so `dense-llms`≡`dense-llm`), `_route_cross_language` catches the other-language twin; `_merge_pages` unions sections/lines (no prior fact dropped) and `_contradiction_check` auto-resolves a numeric conflict only when a frontmatter date proves which source is newer, else flags `## Contradictions` and lowers confidence. The three-stage split keeps source-scoped work out of the per-piece loop (~30 → ~7 min on long sources); affected pages are picked per piece by BM25 (`_select_affected_pages`, no LLM) and shown to the model only as a key-facts candidate index. Every page carries a leading `## Key facts` index + `key_terms:` frontmatter; `ingest_piece` auto-merges `sources:` so the typed graph can draw `derived-from` edges. `consolidate(db, dry_run, llm_polish)` (+ `scripts/dedup_wiki.py`) is the one-off pass that collapsed legacy chunk-derived duplicates with the same primitives. Query-path selection and synthesis (Q-1 hybrid candidates incl. `linked_pages` 1-hop neighbours, Q-3 section-level synthesis): [retrieval.md](retrieval.md). **Lifecycle (E-1/E-2):** `is_page_stale(meta, today)` / `stale_pages()` flag pages past `updated` + `expires_after_days` (else `STALE_AFTER_DAYS`, 365) — ⚠️ in the tree and a programmatic list in `lint()`; `list_pages(include_insights=True)` adds `insights/*.md` (type `insight`), which `lint()` scans and `_rebuild_index()` lists under `# Insights`. **OKF (v0.1):** every page write passes through `_okf_apply` → `okf.apply_to_page`; `_rebuild_index()` emits the OKF `index.md` and `_append_log()` the date-grouped log — see [okf.md](okf.md).
- **`src/template_loader.py`** reads `templates/insert.md` and returns the ordered list of user-fillable metadata field names via `load_insert_template()`.
- **`src/run_memory.py`** — per-invocation "visited" scratchpad shared by the chat and research agents. A `RunMemory` dataclass holds `reads: dict[str,int]` (key → step first seen) and `searches: dict[str,int]`, plus a monotonically-incrementing `step` counter. Scoped via a `contextvars.ContextVar`; `begin_run()` resets it at the top of `run_chat_agent` / `run_research_agent`, `current()` returns the active memory (or `None` for direct `tools.py` callers / tests that never started a run). Pure Python, no LangChain.
- **`src/tools.py`** — agent tools wired as `langchain_core.tools`. **Research tools** (`TOOLS`): `wiki_search`, `wiki_read`, `tavily_search`, `fetch_webpage_content`, `think_tool`, `submit_final_answer` (word/source gates → writes an OKF-stamped report to `data/wiki/comparisons/` via `okf.apply_to_page`; counts `https://` URLs and `[Wiki: filename.md]` citations toward `RESEARCH_MIN_URLS`), `evaluate_condition`. **Chat tools** (`CHAT_TOOLS`): `raw_search` (BM25 over the chunk store via `lex_index.query()`; returns ranked hits with `chunk_id`, anchor, matched terms, score), `raw_read` (bulk read; a `§X`/`#section` suffix resolves to that section's chunk text via `chunker.load_chunks` — works for legal `§` and markdown headings — with a footer naming the next section; bare filenames use the `offset` parameter for 16000-char-window byte-pagination with a `[truncated; pass offset=N to continue]` footer), `wiki_search` / `wiki_read` (shared with the research tools — Deep chat navigates the wiki to find which originals matter; see §Deep chat "map vs territory"), `think_tool`, `submit_chat_answer` (word/source gates; returns to caller, no file written), `evaluate_condition`. **Loop guard** — `wiki_read`, `raw_read`, `wiki_search`, and `raw_search` consult `run_memory.current()` before delegating to their `_impl` helper. Exact-duplicate calls return a one-line `[memory] Already read/searched … at step N` stub instead of re-fetching, breaking the "same doc over and over until `MAX_ITER`" loops weaker local models fall into. Keys: `wiki:{filename}`, `raw:{base}:{offset}` for bare reads (a fresh `offset` still paginates) and `raw:{base}|sec={canon}:{offset}` for section reads (distinct sections = distinct reads, so the guard no longer collapses every section to offset 0; a blocked section read lists the file's unread anchors), `wsearch:{q.lower()}`, `rsearch:{q.lower()}`. **Pagination nudge** — once `RAW_READ_NUDGE_AFTER` (default 2, env `CHAT_RAW_READ_NUDGE_AFTER`) distinct byte-offset windows of one file have been read in a run, the `raw_read` result appends a `[memory] … Stop paginating — call submit_chat_answer now …` line so a weak model answers instead of walking a whole document window-by-window (section reads are exempt — they're intentional). Multi-file / multi-query batches dedup per-item — unseen items still run through `_impl`, seen items are replaced with the stub and results joined. Pure wrapper layer; `_impl` helpers, BM25, and `wiki_engine` are untouched. **Shared tool — `evaluate_condition`**: accepts a `facts` dict of named values (numeric / string / list) extracted from source text and a nested-dict `condition` tree; the LLM only assembles facts and the tree, while Python deterministically walks the tree using `operator`-module dispatch. Node shapes: comparison (`>`,`>=`,`<`,`<=`,`==`,`!=`), `in` (membership), `contains` (substring), `between` (inclusive range), `not`, `and`/`or`. Returns a facts table, a per-leaf TRUE/FALSE trace, and a final `Result: PASS|FAIL`. Errors (missing fact, unknown op, type mismatch) become FALSE leaves with explanatory messages — the tool never raises. `_RAW_CITE_RE` accepts an optional trailing ` §...` / ` #...` section marker so distinct sections of the same long file count as distinct sources for `CHAT_MIN_SOURCES`; `[Wiki: page.md]` cites also count, but `_submit_chat_impl` rejects any answer that cites no raw original. Descriptions imported from `prompts.py`. Only `agent.py`, `chat_agent.py`, and `tools.py` may import LangChain-family packages.
- **`src/agent.py`** — owns the deep-researcher LangGraph state machine (`ChatOllama.bind_tools(TOOLS)` agent node + `ToolNode`). `_load_wiki_index()` injects `data/wiki/index.md` into the system prompt so the agent knows which pages exist before any tool call. Public generator `run_research_agent(question, wiki_context)` yields `thought` / `tool_call` / `tool_result` / `final_answer` / `error` step dicts. Calls `run_memory.begin_run()` at the top of every invocation so the per-run visited-set starts empty.
- **`src/chat_agent.py`** — owns the deep-chat LangGraph state machine (`ChatOllama.bind_tools(CHAT_TOOLS)` agent node + `ToolNode`). `_build_raw_index()` injects a one-line-per-file index of `data/raw/` (first markdown heading per file) into the system prompt. Public generator `run_chat_agent(question)` yields the same step-dict shape as the research agent; `_cites()` splits each final answer's citations into `sources` (raw originals, `[Source: ...]`) and `wiki_sources` (`[Wiki: page.md]`) so the UI can panel them separately. **Stall recovery** mirrors `agent.py`: if the agent reaches a terminal no-answer state, `_synthesize_fallback(question, all_messages)` makes one plain `ollama_client.generate` call (`CHAT_FALLBACK_SYSTEM` / `CHAT_FALLBACK_PROMPT`, notes capped at `CHAT_FALLBACK_NOTES_CAP=12000`) to write a grounded answer from the gathered `ToolMessage` notes instead of discarding them — only a truly empty run still yields the bare error. On `GRAPH_RECURSION_LIMIT`, the loop surfaces a partial answer and `_with_iter_hint()` appends an end-of-answer `*Hint: … iteration limit (N) … may be partial.*` note to every final answer produced that way. Calls `run_memory.begin_run()` at the top of every invocation so the per-run visited-set starts empty.
- **`src/db_context.py`** — active-database context. Each DB is an isolated subtree `$DATA_ROOT/<db>/{raw,chunks,index,wiki}`; the active DB name is held in a `contextvars.ContextVar` so every data module resolves paths via the getters (`wiki_dir()`/`raw_dir()`/`chunks_dir()`/`index_dir()`, all derived from `get_active_db()`) instead of import-time constants. `set_active_db()`/`get_active_db()`, `list_dbs()`/`create_db()`, `is_valid_db_name()`, `users_json_path()` (shared `$DATA_ROOT/users.json`), `migrate_legacy_layout()` (moves pre-multi-DB top-level data into `data/Strahlenschutz/`). No LangChain.
- **`src/auth.py`** is the *only* reader/writer of `data/users.json` (gitignored). bcrypt password hashes; per-user `dbs` read-allowlist, global `is_admin` flag, and per-DB `maintains` write-list. **Access model:** access (`dbs`) lets a user read/chat against a DB; **maintainer** (`maintains`) lets them *change* it (upload sources, delete data). `is_maintainer(user, db)` is exactly `db in maintains` — admin is **not** an implicit maintainer (assignment is explicit per DB). `grant_maintainer(user, db)` adds a DB to both lists in one write (a maintainer must also have read access). `ensure_seeded()` creates default admin `T. Hein`/`k-wiki` (maintains `Strahlenschutz`); `backfill_maintainers()` is an idempotent migration giving pre-existing admins `maintains = dbs`. Other API: `verify`, `add_user`, `delete_user`, `set_user_dbs`, `set_user_maintains`, `change_password`, `user_dbs`, `user_maintains`, `is_admin`, `list_users`. No LangChain.
- **`src/app.py`** is the UI shell (Streamlit, port 8520). Calls `wiki_engine`, `agent`, `chat_agent` and `deep_research_agent`; never writes wiki files directly. A login gate + main-window top bar (DB selector scoped to the user's `dbs` allowlist, `OPTIONS` segmented control: Upload / Wiki Explorer / Wiki Chat / Research) front every page, and the chosen DB reaches `db_context.set_active_db()` before any page handler runs; Maintenance is a sidebar entry. `_can_maintain = auth.is_maintainer(user, active_db)` gates writes (Upload, Delete source, Page language). `_raw_source_button()` strips `§`/`#` suffixes before resolving citations to `data/raw/` files. Page-by-page behaviour, streaming traces, source panels and the framework traps (no `st.tabs`, opaque `stHeader`, `stButtonGroup` styling): [ui.md](ui.md).

## Key dataflows

### Ingest

```
# Upload is a MULTI-FILE batch (accept_multiple_files). Phase 1 prepares each file
# (dedup/convert/extract/date-detect, SHA-keyed cache); Phase 2 is one review table;
# Phase 3 ingests the files ORDERED oldest-first, looping the per-source flow below.
upload[N] → dedup.is_duplicate()               # keyed on original upload bytes; dupes skipped
       → [non-.md] md_convert.convert_to_markdown()  # PDF/DOCX/image → Markdown (no per-file review in batch)
       → dedup.register_file(raw, name, content=md)  # stores converted .md in data/raw/
       → [.md] file_processor.extract_text()  # returns FULL text (no truncation)
       → metadata_extract.extract_effective_date(text)  # regex, per file → prefilled review table (editable)
       → [Upload UI] st.data_editor review table (editable effective-date) + optional shared part-of/description
       → file_processor.chunk_text(text)      # [text] if ≤MAX_INGEST_CHARS, else N chunks
       → wiki_engine.ingest_begin(full_text, source_name, user_meta)   # ONCE per source
           → schema_loader.get_system_prompt() + lang.ingest_directive(full_text)  # mode="full"; source-language directive appended to system prompt (truncation-safe)
           → chunker.split(full_text) → chunker.write_chunks()         # whole-document
           → qa_gen.generate() + persist()                              # if INGEST_QA=1, 1–QA_MAX_PAIRS_PER_SOURCE
           → _source_to_pages() + _build_registry()                     # reverse map + routing registry (cached in ctx)
           → summary_slug = one stable summary-<source>.md for the whole doc (not per-Teil; für→fuer, legacy f-r slug reused)
           → ctx[lang] = lang.detect(full_text)                         # source language (new pages)
           → return ctx (system, index_text, meta_block, src_to_pages, registry, summary_slug, affected[], chunks, …)
       → for each piece in file_processor.chunk_text(full_text):       # per 40 KB cut
           wiki_engine.ingest_piece(ctx, piece, i, n)
             → _select_affected_pages(piece, ctx[src_to_pages])         # BM25 over prior index → ranked pages (no LLM)
             → _build_candidate_index_block(ranked)                     # cheap key-facts index nudge (NOT full bodies)
             → ollama_client.generate(system, INGEST_PROMPT, temperature=0.3, model_id=_INGEST_MODEL)  # cites [source_name]; part given as "(part i of n)"
             → parse "=== filename.md ===" blocks + UPDATE:/CONTRADICTION: lines ("None found"-style CONTRADICTION: lines dropped)
             → _write_piece_page per page: _clean_refs ([Teil n/m] / .md.md stripped) + _ensure_key_terms + _ensure_index_block (## Key facts)
             → _resolve_target: source-summary→summary_slug; concept/entity→_route_page(registry: title or alias tokens)
                 → else _route_cross_language (bge-m3 title cosine ≥0.80, lead ≥0.05 over runner-up; skipped on any error)
             → if target exists: _align_language (other-language new lines translated) → _merge_pages (deterministic union + contradiction check)
               else: stamp lang (page body's language) and write
             → update ctx[registry]; accumulate created/updated/contradictions
       → wiki_engine.ingest_end(ctx, finalize=is_last_file)             # ONCE per source
             → _rebuild_index() + _append_log()                         # always (cheap; keeps batch coherent)
             → [finalize only] lex_index.build() + update_description()  # corpus-wide; deferred to the last file
             → return {created, updated, contradictions, affected, chunks}
# Batch: finalize=False for every file but the last, so the one costly lex_index.build()
# runs once at the end. rebuild_lex_index() is the fallback if the last file fails first.
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

### Page language

A page keeps the language it was created in; the wiki as a whole may be bilingual. All decisions are code (`src/page_lang.py`) — safe with a 4B model.

- **Stamp.** New page → `lang: de|en` from its body. Every write goes through `_okf_apply`, which stamps a missing `lang` from the page's **first three sizable lines** — the creator's, since merges append below them.
- **Cross-language merge** (`_align_language`). Contribution language ≠ page `lang` → only the lines not already on the page go through `TRANSLATE_CONTRIBUTION_PROMPT` (page-language directive). Original terms (**bold**, *italic*, `code`, „quoted“) are passed as a keep-verbatim list and stay inline as "translation (*Original*)"; dropped list markers are restored in code. The contribution's **title** is recorded in `aliases:` — titles only, because aliases drive routing and search indexes the body, not frontmatter. A reply that is empty, echoes the input, loses a number / § reference / citation, or is clearly in the wrong language is rejected → the new lines stay as a `## Original (DE|EN)` blockquote. No fact is dropped; mixing is only explicit and labelled. Same-language merges cost nothing.
- **Routing across languages.** `aliases` make `Ontologie` route into `concept-ontology.md` by tokens. First contact uses `_route_cross_language`: bge-m3 cosine of titles against other-language pages of the same type. Measured on DE/EN pairs: true 0.62–0.95, false 0.38–0.64, hence the conservative 0.80 + 0.05 lead; a miss only leaves a separate monolingual page.
- **Other writers.** `resolve_contradiction` sends each page with its `lang`, pins the majority language and does not save a rewrite that changed a page's language (`skipped`); `_polish_page` likewise; `_contradiction_check` notes follow the page language.
- **Existing pages.** Maintenance → *Page language* runs `normalize_pages(dry_run)`: clean references, stamp `lang`, translate runs of foreign lines in place (a heading goes along when its whole section is foreign; `## Citations`/`## Contradictions`/`## Original (…)`, quotes, tables and code are exempt), labelled quote on failure.

### Query, multi-database chat, link-aware retrieval

Moved to [retrieval.md](retrieval.md) — the query dataflow, the cross-DB search
scope, and `wiki_engine.linked_pages()` 1-hop expansion.

### Deep chat (Chat page "Deep" mode, `src/chat_agent.py`)

Same LangGraph shape as the deep researcher, grounded in `data/raw/` and with no web access:

```
START → agent (ChatOllama.bind_tools(CHAT_TOOLS)) → conditional router
                                                     ├─ tools → agent (loop)
                                                     └─ END on no tool_calls
                                                              or submit_chat_answer ACCEPTED
```

Tools bound: `raw_search` (BM25 over `data/chunks/` via `lex_index.query()`; returns chunk-level hits with anchors and scores), `raw_read` (paginated bulk read; 16000-char window per call, `offset` param, footer with continuation hint, plus a "stop paginating / submit now" nudge after `RAW_READ_NUDGE_AFTER` windows of one file), `wiki_search` / `wiki_read`, `think_tool`, `submit_chat_answer` (gates: `CHAT_MIN_WORDS` / `CHAT_MIN_SOURCES`; section-suffixed citations count as distinct). No web tools. The system prompt (`prompts.CHAT_AGENT_SYSTEM`) pre-loads a one-line-per-file index of `data/raw/` and instructs the agent to use single-stem keywords (not full sentences) and to read distinct `§`/`#` sections taken verbatim from `raw_search` hits (with byte `offset` only as the fallback for section-less files).

**Wiki access — map vs territory.** Deep chat can read the wiki, and this is how it follows cross-references: `wiki_search` surfaces `[Wiki linked N]` neighbours (see §Link-aware retrieval), a page's `sources:` names the originals behind it, and the agent drills into those with `raw_search`/`raw_read`. The split is enforced in code, not just prompt text: `_submit_chat_impl` counts `[Wiki: page.md]` cites toward `CHAT_MIN_SOURCES` but **rejects any answer citing no `[Source: ...]` original**, so the wiki can orient the answer while `data/raw/` still grounds it. `chat_agent._cites` splits the two citation kinds into the `sources` / `wiki_sources` keys of the `final_answer` step, which the UI renders as the "Documents" and "Wiki pages" source panels. The first non-think call remains `raw_search`; the wiki is for gaps about *which* document covers a topic or *how* two topics connect (and as the recovery path when `raw_search` returns no results).

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

### Deep researcher (Research page → **Quick** mode, `src/agent.py`)

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

The report is pinned to the query's language: `run_research_agent` detects it once via `lang.response_directive(question)` and injects the native-language directive into the system prompt, the budget nudge, and the stall fallback (`src/chat_agent.py` does the same for deep chat). Citations, `§`/`#` markers, and numbers stay verbatim.

### Deep Research, web mode (Research page → **Deep** mode, `src/deep_research_agent.py`)

The Research page's second agent, chosen by a `Quick` / `Deep` segmented control. Instead of one
ReAct loop it runs a supervisor pipeline — the **vendored, unmodified** `open_deep_research` graph
(`src/vendor/`, MIT, pinned commit):

```
START → write_research_brief → research_supervisor → final_report_generation → END
                                     │
                                     └─ supervisor ⇄ supervisor_tools
                                                      └─ asyncio.gather → N × researcher_subgraph
                                                            (researcher → researcher_tools → compress_research)
```

`deep_research_agent.py` only configures and adapts it: all four upstream model roles are pinned to
local Ollama, clarification is disabled (the page is one-shot), budgets come from `DEEP_RESEARCH_*`,
and graph events are mapped onto the same step-dict contract the Quick path emits.

The two modes differ in kind, not degree: **Quick is local-first** (wiki → raw → web for gaps),
**Deep is web-only** — it never reads the wiki or `data/raw/`, and its citations are web URLs. On
any graph failure Deep emits a `notice` step and falls back to Quick rather than erroring.

This is the one place `asyncio` appears (the vendored graph gathers its researcher subgraphs); the
async surface is confined to `src/vendor/`, and `run_deep_research` re-exposes it as a plain sync
generator over a private event loop. Full internals, configuration table, and the non-obvious
upstream behaviours are in [deep_research.md](deep_research.md).

## Concurrency & state

Synchronous everywhere except the agent I/O layer and the vendored Deep-Research graph (above). `tavily_search`, `fetch_webpage_content`, `wiki_search`, `wiki_read`, `raw_search`, and `raw_read` fan out across a `concurrent.futures.ThreadPoolExecutor` (size = `RESEARCH_PARALLELISM`, default 4 — shared by research and chat tools). LLM calls remain sequential — local single-GPU; parallel LLM calls would just queue. No asyncio at any boundary except Deep Research, where the vendored graph's `asyncio.gather` stays behind `run_deep_research`'s sync generator; the same single-GPU reality applies, so `DEEP_RESEARCH_CONCURRENCY` defaults to 1.

State is files + JSON only — no database, no cache (PRD §4.4).
