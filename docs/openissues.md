---
name: openissues.md
description: comprehensive documentation of the project´s open issues and todos
version: 1.0.0
author: Tobias Hein
---

# Open Issues & TODOs

Track open work and resolved items here. Keep entries short; link to PRs/commits when relevant.

## Open

# Karpathy Wiki Knowledge System — Deep Dive & LocalWiki Implementation Review

## Executive Summary

Andrej Karpathy's "LLM Knowledge Bases" pattern, published as a GitHub Gist in April 2026, is a paradigm shift away from transient RAG toward a **persistent, self-compiling wiki** maintained entirely by an LLM. The `ToHeinAC/KB_BS_local-wiki-he` repository (LocalWiki) implements this pattern faithfully in many respects, using a Streamlit frontend, Ollama for local inference with `gemma4:e4b` as the default model, and a clean Python module architecture. However, several critical gaps in knowledge update mechanics, persistence discipline, and small-model adaptations prevent it from working seamlessly at the local scale the project targets.[1]

***

## 1. The Karpathy Wiki Pattern: Core Philosophy

### 1.1 The Fundamental Problem with RAG

Traditional RAG systems — ChatGPT file uploads, NotebookLM, and most vector database pipelines — re-derive knowledge from scratch on every query. A question requiring synthesis of five documents forces the model to retrieve and re-piece relevant fragments every time. Nothing accumulates. Karpathy describes this as a fundamental architectural defect: *"There is no accumulation. No compounding. No persistent artifact that grows richer with every source you read."*[2][1]

The LLM wiki pattern inverts this: instead of runtime retrieval, the LLM performs **compile-time synthesis** — building and maintaining a rich structured artifact once, then querying that artifact at runtime.[3]

### 1.2 The Compiler Analogy

Karpathy's framing is precise and consequential: raw source documents are *source code*, the LLM is the *compiler*, and the resulting wiki is the *executable*. Just as recompiling a program integrates all changes, ingesting a new document integrates its knowledge into the full existing structure — updating entity pages, revising topic summaries, noting contradictions. This analogy implies:[4][1]

- Raw sources are **immutable** — the compiler reads them but never modifies them
- The wiki is **owned entirely by the LLM** — humans read it but rarely write it
- Compilation is **incremental** — new sources update the existing artifact rather than triggering full reprocessing[5]

### 1.3 Three-Layer Architecture

| Layer | Path | Owner | Mutability |
|-------|------|-------|------------|
| Raw Sources | `raw/` | User | Immutable (LLM reads only) |
| Wiki | `wiki/` (markdown files) | LLM | LLM writes entirely |
| Schema | `SCHEMA.md` / `CLAUDE.md` | Maintainer | Co-evolved with LLM |

The schema layer is uniquely powerful: it is a configuration document injected into every LLM system prompt, transforming a generic chatbot into a disciplined wiki maintainer. Without the schema, the LLM defaults to conversational behavior; with it, the LLM knows page types, naming conventions, frontmatter structure, and linking rules.[5][1]

***

## 2. Knowledge Update & Persistence: The Deep Mechanics

This is the most nuanced part of the pattern and the most frequently misunderstood.

### 2.1 Ingest: Incremental Compilation, Not Indexing

When a new source is dropped into `raw/`, the LLM does **not** just create a summary page. The canonical ingest flow:[1]

1. Read the new source document
2. Discuss key takeaways (optionally, interactively)
3. Write a **source-summary** page for the new document
4. **Update the index** (`index.md`)
5. **Update all relevant entity and concept pages** across the existing wiki — a single source may touch 10–15 pages
6. Append an entry to the **log** (`log.md`)
7. Flag **contradictions** where new data conflicts with existing claims

Step 5 is the crucial differentiator. The LLM must read the existing wiki state, identify which pages are affected, and surgically update them. This is what makes knowledge compound rather than merely accumulate. An entity page for "Siemens AG" grows richer every time a new source mentioning Siemens is ingested, without requiring the user to manually merge the information.

### 2.2 Persistence via Structural Artifacts

Persistence in this pattern is **structural, not vectorial**. The wiki consists of human-readable markdown files with YAML frontmatter storing:

- `sources`: which raw documents contributed to this page
- `related`: explicit cross-links to other pages
- `updated`: last modification timestamp
- `confidence`: epistemological confidence level (high/medium/low)[1]

This means the knowledge graph is always inspectable, editable, and version-controlled (the wiki is a git repo). The `index.md` file acts as a lightweight lookup table: when answering a query, the LLM reads the index first to find relevant pages, then drills into those pages — a two-stage retrieval that avoids needing a vector database at personal scale (~100 articles, ~400K words).[6][1]

### 2.3 Query: Explorations That Compound

The query loop is designed so that **every answer can become part of the wiki**:[1]

- The LLM reads the index, selects relevant pages, and synthesizes an answer
- Good answers — comparisons, analyses, discovered connections — get **filed back into the wiki as new pages**
- This means asking questions actively enriches the knowledge base, not just retrieves from it

Karpathy explicitly emphasizes: *"Your explorations compound in the knowledge base just like ingested sources do."* This filing-back mechanic is what distinguishes the pattern from a smarter RAG.[1]

### 2.4 Lint: Active Self-Healing

The lint operation is a periodic health check where the LLM scans the entire wiki and reports:[1]

- **Contradictions**: pages with conflicting facts (e.g., two sources giving different dates)
- **Orphans**: pages not linked from index or any other page
- **Gaps**: important concepts mentioned but lacking their own page
- **Stale claims**: information superseded by newer sources
- **Suggestions**: new sources to seek or questions to explore

This self-healing mechanic is what allows the wiki to remain coherent as it grows. Humans abandon wikis because maintenance burden grows faster than value — LLMs don't get bored and can touch 15 files in one pass.[1]

### 2.5 The Log as Provenance Chain

`log.md` is an append-only chronological record of all operations: ingests, queries, lint passes[1]. With structured prefixes (`## [2026-04-02] ingest | Article Title`), it becomes parseable with standard Unix tools. The log is both a debugging tool and an epistemic provenance chain — it records how the wiki evolved over time.

***

## 3. LocalWiki Implementation Analysis

### 3.1 What Is Well-Implemented

The `ToHeinAC/KB_BS_local-wiki-he` repository implements the Karpathy pattern with meaningful fidelity:

**Three-layer architecture**: The `data/raw/` (immutable source documents) / `data/wiki/` (LLM-owned markdown) / `SCHEMA.md` (injected schema) structure maps directly to Karpathy's three layers.[1]

**Schema injection**: `schema_loader.py` loads `SCHEMA.md` and injects it into every LLM system prompt via `ollama_client.generate(system, ...)`. The schema defines page types (`concept`, `entity`, `source-summary`, `report`), required YAML frontmatter, writing rules, and filename conventions — making the LLM a disciplined wiki maintainer.

**Ingest pipeline**: `wiki_engine.ingest()` passes the source text, current index state, and schema to the LLM, then parses the structured `=== filename.md ===` blocks from the response, writing or overwriting pages. It also detects `UPDATE:` and `CONTRADICTION:` lines from the LLM output.

**Index and log maintenance**: `_rebuild_index()` is called on every ingest; `_append_log()` appends structured entries to `log.md`. Both match the pattern's canonical mechanics.[1]

**Deduplication**: `dedup.py` uses SHA-256 hashing to prevent re-ingesting the same document — a practical robustness addition not in Karpathy's original sketch but aligned with its spirit.

**Query with page pre-selection**: `wiki_engine.query()` uses a two-stage approach — first a `SELECT_PROMPT` call to identify up to 5 relevant pages from the index, then an `ANSWER_PROMPT` call reading only those pages. This mirrors Karpathy's recommended index-first retrieval strategy.

**Lint operation**: `wiki_engine.lint()` reads all non-system pages and calls the LLM with `LINT_PROMPT`, checking for contradictions, orphans, gaps, stale claims, and suggestions — matching the five lint categories from the original gist.[1]

**Research agent with filing back**: The `src/agent.py` LangGraph deep-research agent writes reports to `data/wiki/comparisons/` — this is the "file explorations back into the wiki" mechanic from the pattern.[7]

**User metadata forms**: The optional metadata form (from `templates/insert.md`) allows users to provide authoritative metadata at ingest time, improving page title and frontmatter accuracy — a practical extension.

### 3.2 Critical Gaps in Knowledge Update & Persistence

Despite the structural correctness, several key mechanics are weak or missing:

#### Gap 1: Shallow Incremental Update (Most Critical)

The `INGEST_PROMPT` asks the LLM to "create or update concept/entity pages for key topics found in the source," but the **existing page content is never passed to the LLM**. The LLM only sees:

- The `index.md` (page titles + one-line summaries)
- The new source text

This means when updating an existing page, the LLM is effectively **rewriting from the index blurb and the new source alone**, not integrating with the existing page's full content. True incremental compilation requires reading the current page text, identifying what changes, and merging intelligently. The current implementation overwrites pages with potentially degraded content — losing nuance from previous ingests.

**Fix**: Before generating update content for an existing page, load its full current text and include it in the prompt as "existing content to update/merge."

#### Gap 2: No Answer Filing Back into Wiki

The `query()` function returns a string answer to the Streamlit UI but **never files the answer back into the wiki**. This omits the compounding mechanic that Karpathy explicitly calls out as critical. Every query result silently disappears into the chat history.[1]

**Fix**: After a query, offer a one-click "Save to wiki" action that calls a new `wiki_engine.file_answer(question, answer)` function, creating a page in a `comparisons/` or `insights/` subdirectory.

#### Gap 3: Orphan Detection Only at Lint Time

The `search_wiki()` function is pure keyword/BM25 search over page bodies. There is no link-graph tracking between pages. The `related` frontmatter field exists in the schema but is populated only by the LLM's best guess at ingest time — it is never maintained as pages are updated. The lint prompt asks the LLM to find orphans, but since the LLM reads all pages in one call, this becomes unreliable at scale (especially with small models).

**Fix**: Build a lightweight Python link-graph from `related` frontmatter fields after each ingest, detect orphans programmatically, and expose the graph in the Streamlit UI (the PRD mentions `pyvis` for this).

#### Gap 4: No Contradiction Resolution Loop

`wiki_engine.ingest()` extracts `CONTRADICTION:` lines from the LLM response but does only one thing with them: logs them. There is no workflow to surface contradictions to the user or to trigger a reconciliation prompt. Contradictions silently pile up in the log.

**Fix**: Surface contradictions in the Ingest UI result panel with a "Resolve" button that opens a focused reconciliation prompt allowing the user to guide the LLM on which claim is authoritative.

#### Gap 5: Log Not Machine-Parsed for Deduplication Awareness

The `log.md` contains ingest history with source names, but the ingest pipeline doesn't read the log to check which sources have already been processed or when they were last updated. The deduplication (`dedup.py`) operates on file hashes, not on conceptual source identity. If a document is re-uploaded with minor changes (e.g., updated version), it passes deduplication but the log provides no guidance on what changed since the last version.

### 3.3 gemma4:e4b Specific Challenges

`gemma4:e4b` has 4.5B effective parameters (8B with embeddings) and a 128K context window. This is a capable small model, but several characteristics create specific friction in the LocalWiki workflow:[8][9]

| Challenge | Root Cause | Impact on LocalWiki |
|-----------|-----------|---------------------|
| 512-token sliding window attention | Architectural constraint in E4B[8] | Local context within long prompts is limited even within 128K total |
| Instruction following reliability | Smaller models are less forgiving of imprecise prompts[10] | The `=== filename.md === ... === END ===` output format may be inconsistently followed |
| Structured output adherence | 4.5B effective params vs. frontier models[11] | YAML frontmatter may be malformed; `UPDATE:` / `CONTRADICTION:` markers may be omitted |
| Multi-file ingest quality | Synthesizing 10–15 page updates in one pass | At this parameter scale, cross-page coherence degrades significantly |
| Context stuffing | Lint passes load ALL wiki pages into one prompt | With a growing wiki, lint calls can easily exceed practical context limits |

The current `MAX_INGEST_CHARS = 40000` limit (truncating source documents at 40K characters) is a reasonable safeguard, but the ingest prompt also includes the full `index.md` — which itself can grow substantially and eat into the effective context budget.

The `temperature=0.3` setting for ingest and lint (vs. `0.7` for queries) is a correct calibration choice: lower temperature improves structured output reliability for small models. However, the `SELECT_PROMPT` uses `temperature=0.1`, which is appropriate but may cause the model to always pick the same pages once it settles into a pattern.

***

## 4. Improvement Roadmap for Seamless Operation

### Priority 1 — Fix Incremental Update (High Impact, Medium Effort)

```python
# In wiki_engine.ingest(), for existing pages, load their current content:
def _load_existing_pages(index_text: str, source_text: str, system: str) -> dict[str, str]:
    """Pre-load existing page content for pages likely to be affected."""
    # Run a lightweight SELECT call to identify affected pages
    affected_raw = ollama_client.generate(system,
        f"Which pages in this index are likely affected by a new source?\n{index_text}\n\nSource excerpt:\n{source_text[:2000]}\n\nList filenames only.",
        temperature=0.1)
    filenames = [l.strip() for l in affected_raw.splitlines() if l.strip().endswith(".md")]
    return {f: (WIKI_DIR / f).read_text() for f in filenames if (WIKI_DIR / f).exists()}
```

The existing page content must be injected into the ingest prompt as a "current content" block for each affected page, so the LLM can perform a true merge rather than a blind overwrite.

### Priority 2 — Answer Filing Back into Wiki

Add a `file_answer(question, answer, source_pages)` function to `wiki_engine.py` that creates a structured `insights/insight-<slug>.md` page with `type: comparison` frontmatter. Expose this in the Chat UI as a **"Save to Wiki"** button after each answer. This is the single biggest behavioral gap from the Karpathy pattern.[7][1]

### Priority 3 — Chunked Lint for Small Models

The current `lint()` function passes all wiki pages in one prompt. With `gemma4:e4b`, this will degrade quickly:

- **Split lint into passes**: contradictions pass (compare pages pairwise for specific topics), orphan pass (check link graph), gaps pass (identify missing concepts)
- **Use the programmatic link-graph** for orphan detection rather than asking the LLM
- **Cap lint batch size** at ~5 pages per LLM call, then aggregate reports

### Priority 4 — Structured Output Robustness

The `_parse_llm_pages()` regex pattern is fragile for small models that may not consistently output the `=== filename.md ===` delimiter format. Improvements:

- Add a **retry loop** (max 2 retries) when `_parse_llm_pages()` returns empty — prompt the LLM to reformat its output
- Add a **JSON output mode** alternative: instruct the LLM to return a JSON array of `{filename, content}` objects, which is more reliably parseable
- Validate YAML frontmatter using `python-frontmatter` before writing, and fall back to injecting minimal frontmatter programmatically if the LLM omits it

### Priority 5 — Context Budget Management

Introduce a context budget manager that:

1. Estimates token count before each LLM call (rough heuristic: 1 token ≈ 4 chars)
2. If the combined prompt (schema + index + source + existing pages) approaches a configurable limit (e.g., 80K chars for `gemma4:e4b`), truncate the index to titles-only and limit the existing page context to the most relevant 2–3 pages
3. Exposes the current budget usage in the Streamlit sidebar

### Priority 6 — Contradiction Surface + Resolution UI

In the Upload page result, display a **Contradiction Panel** if `result["contradictions"]` is non-empty. Each contradiction should show:
- Which pages are in conflict
- A "Resolve" button that calls a `wiki_engine.resolve_contradiction(page_a, page_b, description)` function with a reconciliation prompt
- The resolution should be written back to the relevant pages with updated `confidence` and `updated` frontmatter

### Priority 7 — Graph View (PRD-Listed, Not Implemented)

The PRD references `pyvis` for a wiki graph view. Building the link-graph from `related` frontmatter enables:

- Visual orphan detection
- Navigation by concept proximity
- Identification of hub pages (high in-degree = core concepts)

This is purely additive and significantly improves wiki usability as the knowledge base grows.

***

## 5. Assessment Summary

| Dimension | Assessment | Score |
|-----------|-----------|-------|
| Three-layer architecture | ✅ Correctly implemented | Strong |
| Schema injection into LLM | ✅ Every call includes SCHEMA.md | Strong |
| Source immutability | ✅ Raw files never modified | Strong |
| Index maintenance | ✅ Rebuilt on every ingest | Strong |
| Log maintenance | ✅ Append-only, structured | Strong |
| Lint operation | ✅ Five-category check implemented | Strong |
| Incremental page updates | ⚠️ Updates without reading existing content | Weak |
| Answer filing back into wiki | ❌ Not implemented | Missing |
| Contradiction resolution workflow | ❌ Detected but not surfaced | Missing |
| Link-graph / orphan tracking | ❌ No graph; lint-only | Missing |
| gemma4:e4b output reliability | ⚠️ No retry/validation on structured output | Needs hardening |
| Context budget management | ⚠️ Fixed char truncation only | Needs hardening |
| Research report filing | ✅ `comparisons/` directory in agent | Strong |

The implementation captures ~70% of the Karpathy pattern's structure correctly and is a solid foundation. The missing 30% is concentrated in the knowledge-update feedback loops — the mechanics that make knowledge compound rather than merely accumulate.

## Resolved

### 2026-05-06 — Karpathy-pattern compounding mechanics

| Gap / Priority | Status | Implementation |
|---|---|---|
| Gap 1 — shallow incremental update | ✅ Resolved | `wiki_engine._select_affected_pages()` runs a lightweight LLM select; affected page bodies loaded (capped at 8K chars) and injected into `INGEST_PROMPT` as an `Existing page content (MERGE…)` block. Result includes `affected` filenames; UI shows them on Upload. |
| Gap 2 — answer filing back into wiki | ✅ Resolved | `wiki_engine.file_answer(question, answer, related)` writes `data/wiki/insights/insight-<slug>.md` with `type: comparison`. Chat page now exposes a **Save answer to wiki** button using the page filenames returned by `query_with_sources()`. |
| Gap 3 — link graph / orphan tracking | ✅ Resolved | `build_link_graph()` reads `related` frontmatter (drops nonexistent / system targets); `find_orphans()` returns pages with zero in-edges; `lint()` prepends a programmatic orphan section; Maintenance page surfaces orphans inline. |
| Gap 4 — contradiction resolution loop | ✅ Resolved | `resolve_contradiction(description, page_filenames, user_guidance)` reconciles via `RESOLVE_CONTRADICTION_PROMPT`; Upload page now exposes a **Reconcile** action per detected contradiction with editable page list + free-text guidance. |
| Priority 4 — structured-output robustness | ✅ Resolved | Single retry in `ingest()` when `_parse_llm_pages()` returns empty (stricter reformatting prompt at temp 0.2). `_ensure_frontmatter()` injects minimal YAML when the LLM omits it. |
| Priority 7 — pyvis graph view | ✅ Resolved | Wiki Explorer adds a **Tree / Graph** toggle. Graph is rendered from `build_link_graph()` and embedded via `st.components.v1.html`. Orphans listed below the canvas. |

### Still open

| Gap / Priority | Notes |
|---|---|
| Priority 3 — chunked lint for small models | Deferred. Programmatic orphan check (above) reduces lint reliance for that category, but contradictions/gaps passes still load all pages in one prompt. |
| Priority 5 — context budget management | Deferred. The new ingest path bounds existing-content injection to 8K chars; index is still full-text. A first-class budget manager remains a future cleanup. |
| Gap 5 — log not machine-parsed for source-version awareness | Deferred. Low-impact for the current scale. |
