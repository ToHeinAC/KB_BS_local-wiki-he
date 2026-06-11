# LocalWiki Implementation — Critical Analysis & Improvement Roadmap

**Repository:** [ToHeinAC/KB_BS_local-wiki-he](https://github.com/ToHeinAC/KB_BS_local-wiki-he)  
**Analysis date:** 2026-06-11  
**Reviewer:** Deep technical audit for Claude Code implementation handoff

***

## Executive Summary

The LocalWiki implementation (`KB_BS_local-wiki-he`) is a technically well-structured Python/Streamlit project that maps the Karpathy LLM Wiki pattern faithfully at the architectural level. The three-layer model (`raw/` → `wiki/` → `SCHEMA.md`), index maintenance, log provenance, and BM25 retrieval layer are all present and functional. However, a careful reading of the source code against the Karpathy pattern's design intent reveals **eight substantive improvement areas** — some critical to correctness, others important for local-model robustness, and several relevant to the long-term health of the knowledge base.

This report categorises each gap, explains its root cause in the code, and provides detailed conceptual suggestions for remediation. It is intended as a planning document for a subsequent Claude Code implementation pass.

***

## Category 1: Ingest Fidelity — Incremental Compilation

*The most critical category. These gaps cause knowledge to be shallow or overwritten rather than compounded.*

### I-1 · Shallow Page Merging During Ingest *(Critical)*

**Problem.** The `INGEST_PROMPT` template in `prompts.py` instructs the LLM to "create or update concept/entity pages for key topics found in the source" and includes an `{existing_block}` placeholder. However, `_build_existing_block()` in `wiki_engine.py` only populates this block for the up-to-5 pages identified by `_select_affected_pages()`. Crucially, the affected-page selection is done by a single, fast LLM call that only sees a short excerpt (2000 chars) of the new source — making it structurally likely to *miss* relevant existing pages, especially for semantically rich sources that touch many topics.

The deeper issue is that `existing_block` is capped at `_MAX_EXISTING_CHARS = 8000` chars spread across potentially 5 pages, meaning each affected page gets at most ~1600 chars of its own prior content injected into the merge context. For domain-dense pages (e.g., a full Strahlenschutzgesetz concept page), this is far too little. The LLM effectively rewrites the page from just the index blurb plus a fragment of its prior text.

**Root cause.** `_build_existing_block()` applies a flat character budget. The `SELECT_AFFECTED_PROMPT` only sees 2000 chars of the source excerpt, not the full chunk embeddings or BM25-ranked matches.

**Conceptual fix.** Replace the excerpt-based affected-page selector with a BM25-driven pre-selection step: take the top-K chunks from `lex_index.query()` for the new source, extract their `source` fields, map those back to existing wiki pages (via frontmatter `sources:` provenance), and use that ranked list as the candidate set. This guarantees that the LLM merge context is semantically anchored.

For the merge budget, consider per-page budgeting: if a page is surfaced as a top-1 candidate, give it 4000 chars of existing content; if top-2-3, give 2000; if top-4-5, give 800. The total budget may increase, but the most important merge stays accurate.

Additionally, consider splitting the ingest into two explicit LLM turns for each affected page: (a) a *planning* call that reads the full existing page and the new source and produces a structured diff/patch plan, and (b) a *writing* call that executes the plan. This mirrors the "think before you write" principle from `CLAUDE.md §1`.

***

### I-2 · Affected Page Selection Bottleneck *(High)*

**Problem.** `_select_affected_pages()` fires a single LLM call with only a 2000-char excerpt. For 40 KB+ ingests split into multiple pieces (`ingest_piece` calls), the affected-page list is computed *once* during `ingest_begin` and reused for all pieces — meaning later pieces in a long document cannot discover newly-relevant pages that were not apparent from the first 2000 chars.

**Conceptual fix.** Move affected-page selection to *per-piece* granularity, or alternatively run a BM25 query per piece using the piece's own chunk tokens against the existing wiki index (bypassing the LLM entirely for this step). The BM25 approach is both faster and more precise than a one-shot LLM selection from a small excerpt.

***

### I-3 · Contradiction Tracking is Passive *(Medium)*

**Problem.** `INGEST_PROMPT` instructs the LLM to output `CONTRADICTION: <brief description>` lines. These are collected in `ctx["contradictions"]` and written to the log in `ingest_end`. However, contradictions are never surfaced to the user in the UI (the Streamlit app only shows "Created" / "Updated" page counts), and no automated resolution is triggered. The `resolve_contradiction()` function exists in `wiki_engine.py` but must be invoked manually from the Maintenance page — it is never called from the ingest flow.

**Conceptual fix.** After `ingest_end`, if `ctx["contradictions"]` is non-empty, surface them visually in the upload result panel (a collapsible "⚠️ Contradictions detected" section). Provide a one-click "Resolve now" action per contradiction that pre-populates the Maintenance → Resolve Contradiction form, identifying the affected pages from the contradiction's source and existing pages list. This closes the compile-fix-recompile loop that Karpathy considers essential.

***

## Category 2: Query Path — Retrieval Quality

*These gaps affect the accuracy and completeness of answers returned from the wiki.*

### Q-1 · Query Page Selector Limited to Index Blurbs *(High)*

**Problem.** `query_with_sources()` runs `SELECT_PROMPT` against the full text of `index.md` — which contains only one-line descriptions per page. If the relevant answer is in a page whose description does not closely match the query keywords, the selector misses it. This is especially problematic for detail-heavy domains like radiation protection law, where the relevant page may have a generic description ("Strahlenschutzgesetz — radiation protection law overview") that doesn't match a specific query ("Was ist der zulässige Jahresdosiswert für beruflich exponierte Personen?").

**Conceptual fix.** Replace (or augment) the `SELECT_PROMPT` single-LLM-call with a two-tier approach:
1. **BM25 pre-selection**: run `lex_index.query()` on the question to get top-K chunks, extract the corresponding wiki page filenames (by matching `source` fields in chunk metadata).
2. **LLM re-ranking**: pass only the BM25-candidate page names (with their brief descriptions) to the LLM selector, which then filters to the most semantically relevant 3–5 pages.

This hybrid approach leverages lexical recall from BM25 and LLM reasoning for precision — much more robust than either alone, especially for local small models.

***

### Q-2 · `file_answer` / Insight Filing Not Integrated into Query UI *(Medium)*

**Problem.** `file_answer()` in `wiki_engine.py` implements the Karpathy "explorations compound" mechanic — storing a Q&A as a wiki insight page. However, examining the codebase, this function is called by the Chat agent's `submit_chat_answer` tool only when invoked via the Deep Chat mode. The standard Query path (the simple Chat → Fast mode using `wiki_engine.query()`) never calls `file_answer`. This means Fast mode queries never accumulate as wiki knowledge, which contradicts the pattern's core compounding intent.

**Conceptual fix.** After every `query_with_sources()` call, present a lightweight "💾 Save this answer as an insight" toggle in the chat interface. When toggled, call `file_answer()` with the question, answer, and `used_sources` as the `related` list. This should be the default for answers marked as "good" by the user (thumbs up, or a configurable auto-save threshold).

***

### Q-3 · `query_with_sources` Uses Full Page Text Without Chunking *(Medium)*

**Problem.** In `query_with_sources()`, all selected wiki pages are concatenated raw into `pages_text` with no length guard (beyond the implicit LLM context window). For 5 pages averaging 1500 words each, this can easily exceed 7000 tokens before the question is even added — hitting gemma4's effective context window at local inference speeds.

The `wiki_engine.search_wiki()` function does return excerpts with 160-char windows, but these are used only for search hit display, not for the answer synthesis.

**Conceptual fix.** For each selected page, extract only the sections (via `read_page_parsed()`) most relevant to the query using a lightweight BM25 sub-query within the page's chunk store. Cap each page's contribution at 2 chunks (top-k=2 per page), and pass those chunks with their `anchor` headers rather than full page text. This dramatically reduces the synthesis context while improving precision.

***

## Category 3: Schema & Context Budget

*The schema layer is the "operating system" for the LLM. Inefficiencies here compound across every single LLM call.*

### S-1 · SCHEMA.md Is Minimal — Missing Operational Constraints for Small Models *(High)*

**Problem.** `SCHEMA.md` is only ~1930 chars — compact, which is good — but lacks several constraints essential for small-model discipline:
- No explicit **page length limit** (small models like gemma4:e4b will hallucinate detail if pages are unbounded).
- No guidance on **when NOT to create a new page** (models tend to over-create thin pages for every passing noun).
- No instruction on **citation format within page body** (the schema specifies `[source-summary title]` but this is not enforced).
- No **confidence level criteria** (when is a claim "high" vs "medium"?).
- No guidance for **related link discipline** (the INGEST_PROMPT has a detailed instruction, but SCHEMA.md does not, so the system prompt available outside ingest lacks it).

**Conceptual fix.** Expand `SCHEMA.md` with a compact "Operational Constraints for Small Models" section (keeping total under 2500 chars):
- Max page body: 400 words for concept/entity pages; 800 for source-summary.
- New page threshold: only create a standalone page if a topic is mentioned substantively in 2+ sources OR is a primary subject of the current source.
- Confidence criteria table: high = explicitly stated in 2+ sources; medium = stated in 1 source; low = inferred or partially supported.
- Related link rule: add a link only if the other page is explicitly named or directly discussed in the current source section — never add purely by semantic association.

***

### S-2 · Ingest System Prompt Budget Not Controlled *(Medium)*

**Problem.** `schema_loader.get_system_prompt()` reads `SCHEMA.md` verbatim. This same schema is injected as the system prompt for *every* LLM call in `wiki_engine.py`, `tools.py`, and `agent.py`. For a small model with a ~8K context window (e.g., a 4B parameter Qwen), the system prompt alone consumes ~500 tokens, leaving less room for the actual content.

More critically, the `INGEST_PROMPT` is already very long (over 700 tokens), and when combined with `{existing_block}` content and a 40 KB source chunk, even large models may be close to their effective generation limit before producing output.

**Conceptual fix.** Create two schema variants:
- `SCHEMA.md` — full schema for ingest (needs all page type details, template structures).
- `SCHEMA_QUERY.md` — trimmed variant (~600 chars) for query/lint/chat calls (drops page templates, keeps only writing rules and confidence criteria).

`schema_loader.py` should expose `get_system_prompt(mode="full"|"query")` and all non-ingest call sites should use `mode="query"`. This alone saves ~200 tokens per query/chat/lint call.

***

## Category 4: Retrieval Architecture

*These gaps affect the BM25 index quality and multi-modal retrieval completeness.*

### R-1 · Wiki Pages Not Indexed in BM25 — Only Raw Chunks Are *(High)*

**Problem.** The BM25 index in `lex_index.py` is built exclusively over `data/chunks/` — the structural chunks of raw source documents. Wiki pages in `data/wiki/` are NOT indexed in BM25. This means:
- `wiki_search()` in `wiki_engine.py` uses a naive Python `str.find()` loop over all wiki pages, which is O(n·m) and case-sensitive by default (it lowercase-normalizes, so it's case-insensitive, but it's still O(n·m)).
- The Deep Researcher agent's `wiki_search` tool calls `wiki_engine.search_wiki()` which uses this naive search.
- HyDE questions from `qa_gen.py` are indexed, but they are always generated from raw chunks, so they inherit any gaps in chunking quality.

**Conceptual fix.** After each ingest (in `ingest_end`), serialize wiki page bodies as pseudo-chunks and add them to a separate wiki-content index (or add a `scope="wiki"` dimension to the existing BM25 index). `wiki_search` tools should query this index instead of the naive string scan. This improves recall especially for synthetic/merged content in concept and entity pages that may use different vocabulary than the original source.

***

### R-2 · No Cross-Document De-duplication of Concepts *(Medium)*

**Problem.** When multiple sources describe the same concept or entity, the ingest flow may create separate concept pages (e.g., `strahlenschutz.md`, `strahlenschutz-grundlagen.md`, `strahlenexposition.md`) that partially overlap without the LLM reliably recognising them as duplicates. The `_scrub_related` function prevents dead links, but there is no mechanism to detect or merge semantically-equivalent pages.

Over time — especially with many domain sources — this creates concept fragmentation: the same entity or concept is partially described across several thin pages instead of one authoritative one.

**Conceptual fix.** Add a `merge_candidates` step to the lint operation: when lint detects two pages with high title similarity (e.g., edit distance < 30%, or a prefix/suffix relationship), flag them as potential merge candidates. Provide a UI action that runs a focused LLM call to determine whether they should be merged and, if so, generate a merged page. The lint report already exists as structured text — extending `LINT_PROMPT` to include a "Potential duplicates" category is a minimal change.

***

## Category 5: Agent Robustness

*These gaps affect the reliability of the LangGraph agent loops under local-model constraints.*

### A-1 · Agent Loop Uses Single Model for All Roles *(High)*

**Problem.** Both the research agent (`agent.py`) and the chat agent (`chat_agent.py`) use the same `OLLAMA_MODEL` (default `gemma4:e4b`) for all tool calls: planning, wiki search, raw document reading, web search synthesis, and final answer generation. Small local models have inconsistent function-calling reliability — `gemma4:e4b` in particular has known issues with parallel tool calls and multi-step JSON schemas.

The `RESEARCH_BUDGET_NUDGE` mechanic (injected as a HumanMessage at `NUDGE_AT` iterations) is a reasonable safeguard, but the fundamental issue is that the same model is used for high-precision reasoning (SELECT which 5 pages are most relevant) and low-precision generation (write a source summary).

**Conceptual fix.** Introduce a `QUERY_MODEL` environment variable (defaults to `OLLAMA_MODEL`). Use this model for all disambiguation and selection calls (`SELECT_PROMPT`, `_select_affected_pages`). Consider a `FAST_MODEL` for the lint operation (lighter, faster) and `INGEST_MODEL` for the full synthesis. The architecture already isolates all Ollama calls in `ollama_client.py` — adding per-call model dispatch (pass `model_id` to `generate()`) requires minimal changes.

***

### A-2 · `run_memory` De-duplication Does Not Persist Across Streamlit Sessions *(Medium)*

**Problem.** `run_memory.py` uses `contextvars.ContextVar` for per-invocation loop guard, which correctly prevents within-run loops. However, between Streamlit re-runs (e.g., user presses "Run again" or refreshes), the ContextVar is re-initialized. This is intentional for fresh runs, but means the agent has no memory of which pages it already read in a *previous* session.

More practically, if a user runs a research query, sees a partial answer, and presses "Continue", the new agent invocation re-reads the same pages from scratch — consuming context budget and slowing down the run.

**Conceptual fix.** Persist the `RunMemory` state to `data/wiki/log.md` or a lightweight session store as a summary of "already-retrieved pages for query X". On re-run, if the same query (or a sufficiently similar one via BM25) is detected, inject the previously-retrieved page list as a "already known" hint in the system prompt. This is optional for fresh queries but valuable for continuation scenarios.

***

## Category 6: Epistemic Lifecycle

*These gaps concern the long-term health of the knowledge base — how knowledge ages, decays, and gets superseded.*

### E-1 · No Temporal Decay or Staleness Tracking *(High)*

**Problem.** Wiki pages store `created` and `updated` timestamps in frontmatter, but there is no mechanism to flag pages as potentially stale. In compliance-heavy domains (radiation protection, EEG renewable energy law), regulations change frequently. A concept page last updated in 2024 with `confidence: high` may contain outdated regulatory thresholds — but nothing in the system signals this to the user.

The `lint()` function does ask the LLM to identify "stale claims," but this is purely semantic (the LLM guesses from page content alone without date awareness), and the lint results are not stored back into pages as structured metadata.

**Conceptual fix.**
1. Add an `expires_after_days` optional frontmatter field with a default (e.g., 365 for regulatory content, 90 for market data). The schema should guide the LLM to set this at ingest time based on the source type.
2. Add a scheduled lint trigger: at app startup, if any page's `updated` date is older than its `expires_after_days`, add it to the lint queue and visually flag it in the wiki tree view with a ⚠️ "Possibly stale" badge.
3. Extend `LINT_PROMPT` to include date-aware staleness detection: pass the current date alongside all pages so the LLM can evaluate whether `updated` dates, referenced document versions, or numeric thresholds are likely outdated.

***

### E-2 · `insights/` Directory Not Integrated into Full Wiki Health *(Low)*

**Problem.** `file_answer()` writes insight pages to `data/wiki/insights/` — a subdirectory. However:
- `lint()` only scans `_wiki().glob("*.md")` (top-level), so insight pages are never linted.
- `_rebuild_index()` calls `list_pages()`, which in turn only scans the top-level `wiki/` directory — insight pages are absent from `index.md`.
- `build_link_graph()` does include insights via a secondary `insights.glob("*.md")` pass, but `find_orphans()` operates on `build_link_graph()` output, so insights are orphan-checked. This is inconsistent.

**Conceptual fix.** Unify the `list_pages()` function to include `insights/` as a tagged group (type `insight`). Add `insight` to `_TYPE_GROUPS` in `wiki_engine.py`. Extend lint to scan all page types including insights. Update `_rebuild_index()` to include a separate `## Insights` section. This makes the compounding mechanic visible and maintains health parity between ingested and query-derived knowledge.

***

## Category 7: UI / UX Gaps

*These gaps reduce the usefulness of the interface for day-to-day use.*

### U-1 · No Ingest Progress Feedback Beyond Spinner *(Medium)*

**Problem.** The three-stage ingest (`ingest_begin` / `ingest_piece` / `ingest_end`) can take 7+ minutes for a 488 KB legal document. The Streamlit UI shows a spinner, but provides no granular feedback about which stage is running, how many pieces remain, or which wiki pages are being updated. This makes long ingests feel stalled and unpredictable.

**Conceptual fix.** Leverage Streamlit's `st.progress()` and `st.status()` to emit stage-level messages: "🔍 Chunking document (N chunks)...", "❓ Generating hypothetical questions...", "📄 Selecting affected wiki pages...", "✍️ Synthesising wiki pages (piece 1/3)...", "🔗 Rebuilding index...". The three-stage design already provides natural progress milestones; the UI simply needs to consume them via a generator pattern from `wiki_engine.py`.

***

### U-2 · Wiki Tree View Missing Source-Page Relationship *(Low)*

**Problem.** The wiki tree groups pages by type (concept/entity/source-summary/other). There is no view showing which concept/entity pages were derived from a specific source — the `derived-from` edges in `build_typed_graph()` exist but are only visible in the graph visualization, not as navigable filters in the tree.

**Conceptual fix.** Add a "By Source" tab/filter to the wiki tree view. For each source in `data/raw/`, list all wiki pages whose `sources:` frontmatter includes that source. This allows users to quickly audit what knowledge was derived from a given document — important for compliance use cases (StrlSchG, EEG) where source provenance must be traceable.

***

## Category 8: Testing & Observability

*These gaps affect the ability to verify system correctness and debug failures.*

### T-1 · No Integration Tests for the Full Ingest→Query Round Trip *(Medium)*

**Problem.** The test suite has 130 tests (per `IMPLEMENTATION.md`), but based on the module structure and the test descriptions in `docs/tests.md`, these are predominantly unit tests for individual functions (chunker, lex_index, qa_gen, dedup). There is no end-to-end integration test that:
1. Ingests a minimal test document.
2. Verifies that a concept/entity page was created with correct frontmatter.
3. Queries the wiki for a fact from the test document.
4. Verifies the answer is grounded in the wiki page (not hallucinated).

Without this, regressions in `INGEST_PROMPT` wording or `_parse_llm_pages()` parsing logic can silently degrade knowledge quality.

**Conceptual fix.** Add a `tests/test_integration.py` module with at least one round-trip test using a mock `ollama_client.generate()` that returns a deterministic `=== filename.md === ... === END ===` response. This test can run without a live Ollama instance (set `INGEST_QA=0`, mock the LLM call). Verify that `list_pages()` returns the expected page, frontmatter is valid YAML, and `query_with_sources()` selects the correct page.

***

### T-2 · No LLM Output Quality Metrics *(Low)*

**Problem.** There is no mechanism to measure whether ingest quality is improving or degrading across model upgrades. When the user switches from `gemma4:e4b` to `qwen3:8b`, they have no objective signal about whether the new model produces better wiki pages.

**Conceptual fix.** After each ingest, compare the created/updated pages against a lightweight rubric: page has valid frontmatter (programmatic), page body length is within schema bounds (programmatic), `related` links all resolve (programmatic from `_scrub_related`), confidence is set and not all "high" (heuristic). Expose these as a quality score in the log and optionally in the UI upload result.

***

## Priority Matrix

| # | Issue | Category | Severity | Effort |
|---|-------|----------|----------|--------|
| I-1 | Shallow page merging during ingest | Ingest Fidelity | Critical | High |
| I-2 | Affected-page selection bottleneck | Ingest Fidelity | High | Medium |
| Q-1 | Query selector limited to index blurbs | Query Path | High | Medium |
| R-1 | Wiki pages not in BM25 index | Retrieval | High | Medium |
| A-1 | Single model for all agent roles | Agent Robustness | High | Low |
| E-1 | No temporal decay / staleness | Epistemic Lifecycle | High | Medium |
| S-1 | SCHEMA.md missing small-model constraints | Schema/Context | High | Low |
| I-3 | Contradiction tracking passive | Ingest Fidelity | Medium | Low |
| Q-2 | `file_answer` not wired to Fast mode | Query Path | Medium | Low |
| Q-3 | No section-level chunking in query synthesis | Query Path | Medium | Medium |
| S-2 | Ingest system prompt budget uncontrolled | Schema/Context | Medium | Low |
| R-2 | No cross-document concept de-duplication | Retrieval | Medium | Medium |
| A-2 | `run_memory` not persisted across sessions | Agent Robustness | Medium | Low |
| U-1 | No granular ingest progress UI | UI/UX | Medium | Low |
| T-1 | No integration tests for ingest→query loop | Testing | Medium | Medium |
| E-2 | Insights not fully integrated in wiki health | Epistemic Lifecycle | Low | Low |
| U-2 | Wiki tree missing source-page filter | UI/UX | Low | Low |
| T-2 | No LLM output quality metrics | Testing | Low | Medium |

***

## Recommended Implementation Order

The following sequencing minimises rework and maximises impact-per-session:

**Phase 1 — Schema & Context (quick wins, no core logic change)**
1. **S-1**: Expand `SCHEMA.md` with small-model constraints and confidence criteria.
2. **S-2**: Split `schema_loader.py` into `full`/`query` modes; update all non-ingest callers.
3. **A-1**: Add `QUERY_MODEL`/`INGEST_MODEL` env vars; pass model_id to `ollama_client.generate()`.

**Phase 2 — Ingest Quality (core correctness)**
4. **I-2**: Replace excerpt-based affected-page selector with BM25-driven pre-selection.
5. **I-1**: Implement per-page budget for existing content; add diff-aware merge instruction to `INGEST_PROMPT`.
6. **I-3**: Surface contradictions in upload UI; wire to Contradiction Resolution form.

**Phase 3 — Retrieval Quality**
7. **Q-1**: Add BM25 pre-selection stage to `query_with_sources()`; keep LLM as re-ranker.
8. **R-1**: Add wiki page content to BM25 index as a separate namespace.
9. **Q-3**: Replace full-page concatenation in query synthesis with top-K chunk injection.

**Phase 4 — Lifecycle & Robustness**
10. **E-1**: Add `expires_after_days` frontmatter; startup staleness checker; date-aware lint prompt.
11. **Q-2**: Wire `file_answer()` to Fast mode with opt-in "Save insight" toggle.
12. **E-2**: Unify `list_pages()` to include `insights/`; extend lint scope.

**Phase 5 — UX & Testing**
13. **U-1**: Emit stage-level progress from `ingest_begin/piece/end`; Streamlit progress bar.
14. **T-1**: Add integration test with mocked Ollama for ingest→query round-trip.
15. **U-2 / R-2 / T-2**: Low-priority improvements at maintainer's discretion.

***

## Key Design Principles for the Next Implementation Pass

- **Never break the immutability of `data/raw/`** — all improvements must read from raw but never write to it.
- **Keep `prompts.py` as the single source of truth** for all prompt strings — any new prompts from this analysis go there, not inline.
- **LangChain/LangGraph remain agent-only** — BM25 improvements in phases 2–3 use only `lex_index.py`, never introduce a vector DB.
- **`uv` + `pyproject.toml` dependency discipline** — any new utility (e.g., a session cache for A-2) should use standard library (`json`, `sqlite3`) rather than new dependencies.
- **All new LLM calls are guarded with a try/except fallback** consistent with the existing `qa_gen` pattern — never fail an ingest due to a non-critical LLM sidecar.
- **Schema changes to `SCHEMA.md` should be reviewed against the 2500-char budget** — context economy is especially important for 4B models with 8K context windows.