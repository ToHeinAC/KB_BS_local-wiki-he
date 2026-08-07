---
name: idea.md
description: First-principles improvement proposal for LocalWiki — retrieval (QMD-class search) and UX
version: 1.2.0
status: proposal — Phases 0-4 original; Phase 5 scaffold; Phase 6 reconciled against source video
scope: src/lex_index.py, src/chunker.py, src/qa_gen.py, src/wiki_engine.py (query path),
  src/app.py, src/okf.py, src/gpu_widget.py (route-injection precedent), CLAUDE.md (search ladder)
supersedes: §3.5 abstention rationale (see §5.5), §4.1 VRAM row (see §5.4),
  §4.3 step 9 (see §6.9.3), ladder rung 4 (see §6.9.1)
---

# LocalWiki — Retrieval & UX, rebuilt from first principles

> This is a proposal, not a changelog. It follows the four-phase deconstruction:
> **facts → arbitrary assumptions → rebuild from zero → what actually blocks it.**
> Two areas only: **QMD-class search** and **UX**, inspiration from https://www.youtube.com/watch?v=mHSOsy_usAg&t=2070s, transscripted in ./youtube_transcript_formatted.md. Everything else in the repo
> (three-layer model, OKF stamping, deterministic language pinning, `evaluate_condition`)
> is treated as settled and is deliberately left alone.

---

## 0. AUSGANGSSITUATION

LocalWiki implements the Karpathy compile-time-synthesis pattern faithfully and, in
several places, better than the reference implementations: the `§`-aware structural
chunker, the German morphology folding in BM25, deterministic OKF stamping, and
deterministic language pinning are all real differentiators that `tobi/qmd`,
`NiharShrotri/llm-wiki` and `lucasastorian/llmwiki` do not have.

The retrieval layer, however, is **single-signal**. `src/lex_index.py` is a
hand-rolled BM25 over a JSON postings file. There is no embedding, no fusion, no
reranking, no score calibration. `src/qa_gen.py` implements HyDE *backwards* —
hypothetical questions are generated at **ingest** time and folded into term
frequencies, rather than generated at **query** time — and is capped at
`QA_MAX_PAIRS_PER_SOURCE = 5` per source. On a 488 KB legal document that yields
roughly 200 chunks, five of which carry retrieval hints: **~2.5 % coverage**. The
mechanism is sound; its dosage makes it decorative.

The UX is five Streamlit pages (Upload / Wiki Explorer / Wiki Chat / Research /
Maintenance) sharing one knowledge base but not sharing state, reading position, or
query context. The Explorer's search box calls `search_wiki()`, which computes an
`excerpt` for every hit — and `_render_wiki_nav()` then renders only `r["title"]` as
a button and **throws the excerpt away**. That single line is the whole UX thesis in
miniature: the system knows more than it shows.

Two concrete symptoms motivate everything below:

1. **The better the compiler works, the worse lexical search gets.** The wiki layer's
   value is that the LLM *rewrites* source vocabulary into synthesized prose. BM25
   scores exactly that rewriting as a miss. Retrieval quality degrades as a function
   of synthesis quality. This is structural, not a tuning problem.
2. **Adding one document costs a full corpus rebuild.** `ingest_end()` calls
   `lex_index.build()` with `chunks=None`, which reloads `chunker.all_chunks()` +
   `_wiki_chunks()` and rewrites `postings.json` and `stats.json` from scratch.

---

## PHASE 1 — DEKONSTRUKTION

### 1.1 What is objectively, irreducibly necessary?

Strip away "how retrieval is done." To put the right passage in front of a person or
a model, exactly five things must exist:

| # | Necessity | Why it is not negotiable |
|---|---|---|
| N1 | A representation of the **query's intent** | You cannot rank against nothing |
| N2 | A representation of each **candidate passage** | Same |
| N3 | A **comparison function** over N1 × N2 | Ranking is a total order; it needs a scalar |
| N4 | An **ordering** | Human and context-window attention are both scarce and sequential |
| N5 | A **cutoff** — including the empty cutoff | "Nothing here answers this" is a valid, and for a regulatory corpus a *required*, result |

Everything else in a retrieval stack — inverted indexes, ANN structures, RRF, cache
tiers — is an **implementation of N3 under a latency budget**, not a requirement.

For the UI, the irreducible set is equally short:

| # | Necessity |
|---|---|
| U1 | Get the question in |
| U2 | Show what was found **and why it was found** |
| U3 | Let the person verify the claim against the immutable source |
| U4 | Let the person act: save, correct, follow up, reconcile |

### 1.2 Which underlying laws actually bind here?

**Information-theoretic.** A surface-form token index can only recover documents that
share surface forms with the query. The wiki layer is a *lossy re-encoding* of the raw
layer into different surface forms. Therefore lexical-only retrieval over the wiki
layer has a hard recall ceiling that no amount of stemming, stopword tuning or
umlaut folding can raise. The current `variants()` function (surface / NFKD /
digraph-fold / stem) is a very good attack on **orthographic** variance; it does
nothing about **semantic** variance, which is the dominant failure mode in a
synthesized wiki.

**Computational.** The work required to make one new document searchable is
proportional to that document. Cost proportional to the *corpus* is process overhead,
not physics.

**Cognitive (this is the one the UX ignores).** Working memory holds roughly four
chunks. Every navigation act that forces a person to reconstruct where they were
consumes one. A five-tab application where reading (Explorer) and asking (Chat) are
different modal surfaces spends the user's scarcest resource on application topology
rather than on the knowledge.

**Trust.** Verification cost dominates adoption for a compliance corpus. A cited
answer whose citation costs three clicks and a modal dialog to check is, in practice,
an uncited answer. This is why U2 and U3 are necessities, not polish.

**Economic.** The value of the wiki is the *avoided* re-synthesis cost. That value is
only realised if retrieval reliably finds what was already compiled. Retrieval recall
is therefore the multiplier on the entire ingest investment — the highest-leverage
subsystem in the repo, and currently the thinnest.

### 1.3 Necessity vs. convention — the honest split

| Element in the current design | Necessity | Convention |
|---|---|---|
| Chunks as the citation ground truth | ✅ Physics of provenance | |
| `§`-aware / heading-aware boundaries | ✅ Semantic units are the retrievable units | |
| Markdown-first, files-over-database | ✅ For git-trackability, human readability, OKF | |
| Deterministic OKF stamping in code | ✅ Correct — never trust a 4B model with an invariant | |
| **BM25 as the *only* signal** | | ❌ Convention (inherited from "no vector DB") |
| **JSON postings file** | | ❌ Convention — a *storage format* masquerading as an architecture rule |
| **A 4B instruct model as the reranker** (`_select_pages`) | | ❌ Convention — reranking is a classification task, not a generation task |
| **Five-page tab navigation** | | ❌ Convention — inherited from Streamlit's `st.radio` idiom |
| **Full index rebuild per ingest** | | ❌ Convention — an artifact of choosing a write-whole-file format |
| **HyDE at ingest, capped at 5/source** | | ❌ Convention — a cost workaround that inverted the technique |

---

## PHASE 2 — ANNAHMEN-CHECK

Four assumptions carry the current design. Three do not survive inspection.

### A1. "No vector database" (PRD §2.3)

**Stated as an architectural law. It is a cost-avoidance heuristic.**

The rule was written to avoid Chroma / Qdrant / pgvector: a service to run, a schema
to migrate, a process to supervise, a second source of truth that can drift from the
markdown. Every one of those objections is about **operating a server**. None of them
is about **storing float arrays**.

An embedding table is a file. `postings.json` is a file. `vectors.npy` +
`sqlite-vec` is a file. The invariant that actually matters — *markdown on disk is the
only source of truth, and the index is a derived, disposable artifact* — is preserved
exactly. Under the PRD's own stated rationale ("every wiki page remains
human-readable, git-trackable, and low-admin"), a memory-mapped embedding file passes
and a Qdrant container does not. The rule should be restated as its actual intent:

> **No index may be a source of truth. No index may require a supervised process.**

Under that restatement, embeddings are permitted and the PRD gets *stronger*, not
weaker. `embeddinggemma-300M-Q8` is ~300 MB — smaller than the OCR model
(`deepseek-ocr:3b`) the project already requires for PDF upload.

### A2. "Ollama-native means Ollama-only for everything"

Ollama is already a dependency and already exposes an embeddings endpoint. There is no
new runtime, no Node, no `node-llama-cpp` needed to get arm two of a hybrid search.
This assumption is not arbitrary — it is simply **unexamined**, and examining it makes
the change nearly free.

### A3. "Retrieval quality requires an LLM call"

`_select_pages()` sends the candidate index block to a 4B instruct model at
`temperature=0.1`, parses filenames out of free text, and caps at 5. This is a
reranker built from the wrong primitive.

Cross-encoder reranking is **binary relevance classification**, not generation. A
0.6B cross-encoder (`Qwen3-Reranker-0.6B`) does the same job with better precision,
an order of magnitude less latency, a **calibrated 0–1 score** instead of an
uncalibrated filename list, and no parse-failure mode. The current design pays more to
get less, and — critically — produces a score that **cannot be thresholded**, which
forecloses N5 (abstention) entirely.

### A4. "Streamlit's page model is the UI"

Streamlit's rerun-everything execution model is real. But this repo has **already
proven the escape hatch**: `src/gpu_widget.py` discovers the live Starlette app via
`gc.get_objects()` and inserts an `/_api/gpu` route ahead of the SPA catch-all, then
polls it from a `components.html` island. Same-origin, no extra port, works through
the nginx reverse proxy and through tunnels.

That precedent means the "Streamlit can't do incremental search" objection is already
falsified **inside this codebase**. The barrier is not the framework. It is that
nobody has pointed the existing trick at search.

---

## PHASE 3 — NEUAUFBAU

### 3.1 The retrieval layer, designed from N1–N5

Build only what N1–N5 demand, then stop.

```
                     ┌──────────────────────────────────┐
   query ──────────► │  intent shaping (N1)             │
                     │  • morphological variants (keep) │
                     │  • query-time HyDE (move here)   │
                     │  • OKF facet extraction          │
                     └───────────────┬──────────────────┘
              ┌──────────────────────┴──────────────────────┐
              ▼                                             ▼
   ┌─────────────────────┐                      ┌─────────────────────┐
   │ ARM A: lexical      │                      │ ARM B: semantic     │
   │ SQLite FTS5 / BM25  │                      │ embeddinggemma-300M │
   │ (existing German    │                      │ over the SAME       │
   │  morphology intact) │                      │ existing chunks     │
   └──────────┬──────────┘                      └──────────┬──────────┘
              └──────────────────┬─────────────────────────┘
                                 ▼
                     ┌──────────────────────────┐
                     │  RRF fusion (N3, k=60)   │   ← parameter-free,
                     │  original query ×2       │     handles a missing arm
                     └────────────┬─────────────┘
                                  ▼
                     ┌──────────────────────────┐
                     │  cross-encoder rerank    │   ← replaces the 4B
                     │  Qwen3-Reranker-0.6B     │     `_select_pages` call
                     │  → calibrated 0..1 (N4)  │
                     └────────────┬─────────────┘
                                  ▼
                     ┌──────────────────────────┐
                     │  threshold + ABSTAIN (N5)│   ← new, and the point
                     └──────────────────────────┘
```

**What is deliberately absent:** an ANN index (at 10⁴–10⁵ chunks, brute-force cosine
over a memory-mapped float16 matrix is single-digit milliseconds — HNSW is unearned
complexity); a vector *service*; a reranking cascade beyond one stage; any LLM call in
the ranking path at all.

**What is deliberately kept:** the `§`-aware chunker. This is the place where the
"just adopt qmd" answer is wrong. QMD chunks markdown at ~900 tokens using scored
regex break points. This repo chunks German statutes at `§` boundaries with exact
`char_start`/`char_end` anchors, which is what makes `[Source: StrlSchG.md §62]`
citations possible. Delegating chunking to qmd is a **downgrade**. Take qmd's
*pipeline*; keep this repo's *boundaries*.

### 3.2 Query-time HyDE — inverting the inversion

The current design generates hypothetical questions at ingest and folds them into
document TF. Consider what that costs and what it buys:

- **Cost:** one LLM call per source at ingest; storage in `qa.jsonl`; and — because it
  is expensive — a cap that reduces coverage to ~2.5 %.
- **Buys:** a small TF boost on five chunks per document.

Now consider the symmetric alternative: generate **one** hypothetical *answer* from
the query at search time, embed it, and search arm B with it. Cost: one small
generation per query (cacheable, and skippable when arm A returns a strong
signal — exactly qmd's "conditional query expansion"). Buys: full-corpus coverage,
because the expansion happens on the side of the equation that has one item instead of
N.

**The asymmetry is the whole insight.** Expanding the query is O(1). Expanding the
corpus is O(N) and is therefore always rationed into uselessness. `qa_gen.py` should
not be deleted — it should be **moved to the query side**, where its budget stops
fighting it. Its `_select_target_chunks()` density heuristic survives as a chunk-level
ranking feature.

### 3.3 OKF as a first-class retrieval signal — the free win

The repo already computes, deterministically and model-independently, exactly the
metadata that qmd asks users to hand-author via `qmd context add`:

| qmd concept | Already present in LocalWiki | Currently used for retrieval? |
|---|---|---|
| path context tree | OKF `description` (from `## Key facts`) | ❌ |
| collection context | per-DB `DESCRIPTION.md` | ❌ |
| — | OKF `tags` = `[db, type, part-of]` | ❌ |
| — | OKF `type` enum | ❌ (only for tree grouping) |
| — | OKF `resource` URI | ❌ |
| — | `okf_version`-stamped `index.md` | ❌ |

QMD's headline retrieval trick is `"title: {title} | text: {content}"` — prefixing
each chunk with its identity before embedding. Generalise it against OKF and it costs
nothing:

```python
# embedding text for a wiki chunk
f"type: {type} | title: {title} | about: {description} | tags: {', '.join(tags)}\n\n{text}"
```

Three consequences, all deterministic and all safe on `gemma4:e4b` because **no model
is asked for anything**:

1. Semantic recall improves for chunks whose body text lacks the page's own topic
   words — the single most common failure in a synthesized wiki.
2. `type` and `tags` become **search facets** in the UI for free.
3. Conformance and retrieval stop being separate concerns. Stamping OKF correctly
   *is* index quality. That is a much better argument for OKF than "we conform to a
   spec."

### 3.4 Incremental indexing — removing the O(corpus) tax

Necessary work to make one document searchable: chunk it, tokenize it, embed it, write
its rows. Proportional to the document.

`postings.json` forces a full rewrite because a single JSON object is not partially
writable. Moving arm A to **SQLite FTS5** (stdlib `sqlite3`, no service, single file,
`.gitignore`-able exactly like `data/index/`) makes indexing an `INSERT`/`DELETE` on
the affected rows. Delete-source becomes a `DELETE ... WHERE source = ?` instead of a
rebuild. The `_load()` function — which currently JSON-parses the entire postings and
stats file **on every single query**, including every keystroke in the Explorer — stops
existing.

This also fixes a latent correctness issue: `chunk_meta` currently stores full wiki
chunk text inline in `stats.json`, so the stats file grows with the corpus and is
re-parsed per query.

### 3.5 The UX, designed from U1–U4

**The single structural claim: reading a page and asking about it are one act, not
two.**

Karpathy's own setup is one surface (Obsidian) plus one agent. LocalWiki has five
surfaces and three agents. The tab bar is not information architecture — it is the
module boundary of the codebase leaking into the interface.

```
┌──────────────────────────────────────────────────────────────────────────┐
│  ⌘K  ask or search…                              [Forest]  [DB: legal ▾] │  ← one bar, everywhere
├────────────────┬───────────────────────────────────┬─────────────────────┤
│                │                                   │                     │
│  NAVIGATOR     │   READING SURFACE                 │   CONVERSATION RAIL │
│                │                                   │                     │
│  type facets   │   the wiki page, rendered         │  seeded with the    │
│  ▸ Concepts 12 │                                   │  page you are on    │
│  ▸ Entities  8 │   ── highlighted span ──          │                     │
│  ▸ Sources   4 │   ▲ scroll-to-cite target         │  answer text with   │
│                │                                   │  inline chips:      │
│  results with  │   ⟨ Sources ⟩ raw/StrlSchG.md §62 │  [§62] [Overview]   │
│  excerpt +     │                                   │  ↳ hover = preview  │
│  score bar     │                                   │  ↳ click = scroll   │
│                │                                   │     + highlight ◀───┤
└────────────────┴───────────────────────────────────┴─────────────────────┘
```

Four moves, each derived from exactly one necessity:

**U1 — one input, not five.** A `⌘K` command palette replaces the Explorer search box,
the chat input, and the research question field. It disambiguates by *shape*, not by
tab: a noun phrase searches; a question with a verb offers "answer from wiki" (Fast) /
"answer from sources" (Deep) / "research the web"; a `§` or filename jumps. The mode
toggle becomes a consequence of what was typed rather than a prerequisite to typing.

**U2 — show what was found and why.** Every result carries the excerpt that
`search_wiki()` already computes and `_render_wiki_nav()` currently discards, plus a
calibrated score bar, plus the matched terms (`matched_terms` is already returned by
`lex_index.query()` and never rendered). Add an `--explain`-equivalent disclosure — one
collapsed line per result showing lexical rank, semantic rank, and rerank score. In a
compliance context, "why did it rank this" is not a debug feature; it is the audit
trail.

**U3 — verification without losing your place.** Citations become chips, not a
footnote list. Hover previews the cited span; click scrolls the reading surface and
highlights it. The current `_show_md_dialog()` modal is the anti-pattern here: it
covers the thing you were reading in order to show you what you were reading about.

**U4 — the strongest part of the current UX; preserve it exactly.** "Save answer to
wiki", "↪ Follow up", and per-contradiction "Reconcile" are genuinely ahead of the
reference implementations. They are the compounding loop made visible. Do not touch
them; just relocate them into the rail so they are available while reading rather than
only after a chat turn.

**And the new one, which only exists once scores are calibrated: abstention.** When the
top reranked score falls below threshold, the correct output is not a synthesized
answer from weakly-matched pages. It is:

> *No page in **legal** confidently answers this. Closest: `StrlSchG-§62.md` (0.31).
> Search the raw sources instead → · Run web research → · Ingest a source →*

For a regulatory knowledge base, a confident answer assembled from a 0.2-relevance
context is worse than no answer. This is a **safety property** that the current
architecture cannot express, because BM25 produces unbounded, query-incomparable
scores. Calibration is what buys it.

> **Amended (§5.5):** the claim above is true of BM25 but overstated as a general bar.
> Cosine similarity *is* bounded and query-comparable, so a weaker abstention survives
> from the embedding arm alone even without a cross-encoder.

### 3.6 Where this departs sharply from the current implementation

| Current | Proposed | Why the departure is forced, not stylistic |
|---|---|---|
| BM25 only | BM25 + embeddings + RRF + cross-encoder | Lexical recall ceiling is structural over synthesized prose |
| 4B instruct model picks pages | 0.6B cross-encoder scores passages | Ranking is classification; generation is the wrong primitive |
| Uncalibrated scores | 0–1 calibrated | N5 (abstention) is otherwise inexpressible |
| HyDE at ingest, 5/source | HyDE at query, conditional | O(1) beats O(N); rationing destroyed the technique |
| JSON postings, full rebuild | SQLite FTS5, incremental | Work should scale with the document, not the corpus |
| OKF = conformance concern | OKF = retrieval signal | The metadata is already computed and already free |
| 5 modal pages | 1 surface + palette + rail | Reading and asking are one act |
| Excerpt computed, discarded | Excerpt + score + matched terms shown | U2 |
| Answer always produced | Abstain below threshold | Safety, in a compliance corpus |

### 3.7 What NOT to do: adopt `tobi/qmd` wholesale

Worth stating explicitly, because it is the obvious move and it is wrong here.

**Against:** it adds a Node ≥22 / Bun runtime beside `uv`, breaking the single-toolchain
invariant; it maintains a **second index** with a second lifecycle that can silently
drift from `data/chunks/`; it knows nothing about the per-DB multi-tenancy, the
maintainer/reader access model, OKF frontmatter, or the deterministic language pinning;
its default `embeddinggemma-300M` is English-optimised, which is the wrong default for
a German legal corpus (qmd's own docs recommend swapping to `Qwen3-Embedding-0.6B` for
non-English — do that directly through Ollama instead); and its chunker is worse than
this repo's for statutes.

**For:** its *design decisions* are excellent and well-validated at 26.8k stars.

**Therefore: steal the pipeline, not the process.** Specifically adopt — RRF with k=60
and ×2 weight on the original query; the top-rank bonus (+0.05 for rank 1, +0.02 for
ranks 2–3) that prevents expansion from diluting exact matches; position-aware blending
(trust retrieval at ranks 1–3, trust the reranker at rank 11+); conditional query
expansion; the `title | text` embedding prefix; typed sub-queries (`lex:` / `vec:` /
`hyde:`); and — most importantly — **`qmd bench`**. A fixture of German queries with
known-relevant files, scored as precision@k / recall / MRR across `bm25` / `vector` /
`hybrid` / `full`, is the only way to know whether any of this actually helped. Ship
the harness *before* the pipeline.

---

## PHASE 4 — IMPLEMENTIERUNG

### 4.1 Barriers: real vs. "we've always done it this way"

| Barrier | Verdict | Resolution |
|---|---|---|
| "PRD forbids a vector DB" | **Convention** | Restate the rule as its actual intent (§A1). One PRD amendment, and the PRD becomes more precise. |
| "No extra runtime" | **Real, and correct** | Honour it. Use Ollama for embeddings; use `sqlite3` from stdlib. Zero new services. |
| VRAM: three models resident | **Real** | ⚠️ **This row is factually wrong — see §5.4.** Ollama cannot host the reranker (no `/api/rerank`), so `keep_alive` tuning does not apply to it. Sizing and the degrade-to-RRF-only posture stand; the runtime does not. |
| Streamlit rerun-per-interaction | **Real, already solved in-repo** | `src/gpu_widget.py` proves the Starlette-route-injection pattern. Point it at `/_api/search`. |
| `⌘K` / hover / scroll-to-highlight | **Real for pure Streamlit** | One `components.html` island talking to `/_api/search`. No framework migration. |
| Re-embedding the existing corpus | **Real, one-off** | Chunks are already persisted in `data/chunks/*.jsonl` with stable content-addressed `chunk_id`s. A backfill script mirrors `scripts/okf_migrate.py`. |
| "gemma4:e4b can't be trusted with this" | **Correct — and irrelevant** | Every proposal here is deterministic or uses a task-specific model. The project's own strongest rule ("stamp it in code, never ask the LLM") extends cleanly to ranking. |
| ≈258-test suite must stay green | **Real** | `lex_index.query()` keeps its signature and hit-dict shape. The rewrite lives behind it. |

The pattern: **every barrier that is real is about runtime cost, and every barrier that
is about architecture is convention.**

### 4.2 Prototype — falsify cheaply before committing

The whole thesis reduces to one testable claim:

> **H:** On this corpus, hybrid retrieval with cross-encoder reranking beats BM25-only
> by a margin large enough to justify two extra models.

Test it in a weekend, offline, with no UI work:

1. **Build the fixture first.** 30–50 real German queries against the existing corpus,
   each with hand-labelled relevant `chunk_id`s. Split them by the qmd taxonomy —
   `exact` (a `§` lookup), `semantic` (paraphrase), `topical`, `cross-domain`, `alias`.
   *Expected shape of the result: BM25 wins `exact`, loses `semantic` badly.* If it does
   not lose `semantic`, stop — the thesis is false and this document is wrong.
2. **Baseline.** Run the fixture through today's `lex_index.query()`. Record
   precision@5, recall@10, MRR.
3. **Arm B alone.** `ollama embed` over `chunker.all_chunks()` into a `float16` `.npy`;
   brute-force cosine. Same metrics.
4. **Fusion.** RRF k=60. Same metrics.
5. **Rerank.** Cross-encoder over the top 30. Same metrics — plus **score
   separability**: the distribution gap between labelled-relevant and labelled-
   irrelevant scores. This is the number that decides whether abstention (§3.5) is
   viable, and it is the one no amount of BM25 tuning can produce.
6. **Cost.** p50/p95 latency and peak VRAM per configuration.

Kill criterion, stated up front: if fusion does not beat baseline by ≥15 points of
recall@10 on the `semantic` slice, the wiki layer's vocabulary drift is smaller than
assumed and the correct move is to invest in query-time HyDE alone (§3.2), which is a
tenth of the work.

The UX prototype is equally cheap and equally falsifiable: add `/_api/search` next to
`/_api/gpu`, put a `⌘K` palette island in front of it, and instrument
**time-to-verified-citation** — from question typed to source span visible on screen —
against today's Chat → Sources panel → modal path. If that number does not roughly
halve, the tab consolidation is aesthetics, not architecture, and should be dropped.

### 4.3 Sequence

Each step ships independently and is individually revertible.

| # | Step | Effort | Unlocks |
|---|---|---|---|
| 0 | **Bench harness + labelled fixture** | S | Everything below becomes measurable instead of arguable |
| 1 | **Render what already exists**: excerpt, `matched_terms`, result count in the Explorer | XS | U2, immediately, at near-zero risk |
| 2 | **OKF prefix on chunk index text** (§3.3) | S | Recall lift with no new dependency; validates the harness |
| 3 | **FTS5 migration** behind the existing `query()` signature | M | Kills the per-query JSON parse and the O(corpus) ingest tax |
| 4 | **Arm B: embeddings via Ollama + RRF** | M | The semantic recall ceiling |
| 5 | **Cross-encoder rerank**, replacing the `_select_pages` LLM call | M | Precision, latency, and calibrated scores |
| 6 | **Abstention + score display** | S | The safety property; only possible after 5 |
| 7 | **Query-time HyDE**, conditional on weak arm-A signal | S | Recall on paraphrased questions |
| 8 | **`/_api/search` + `⌘K` palette island** | M | U1 |
| 9 | **Reading surface + conversation rail + citation chips** | L | U3; collapses Explorer and Chat — **but see §6.9.3:** what collapses is the *page count*, not the *write permission*. The graph and reading area stay read-only; the rail is the answer surface and the only place a write may be proposed. |
| 10 | **Facets from OKF `type`/`tags`** | S | Falls out of 2 for free |

Steps 0–2 are worth doing regardless of whether anything after them is ever built.

### 4.4 The disruptive version

Follow the logic to its end and the interesting result is not "better search."

Today the system is *compile-time synthesis with query-time retrieval*. Retrieval is
where the failures live. But once retrieval produces a **calibrated 0–1 relevance
score over an OKF-typed corpus**, that score is not only usable at query time. It is
usable at **compile time** — and that changes what the compiler can be.

- **Ingest becomes retrieval-driven.** `_select_affected_pages()` currently uses BM25
  to choose merge targets. With a calibrated score it can be *correct* about them:
  merge above threshold, create a new page below it, and stop guessing at the boundary
  between "this updates Siemens AG" and "this needs its own page."
- **Lint becomes continuous and programmatic.** The still-deferred "chunked lint for
  small models" problem dissolves. Contradiction detection is a *high-similarity,
  low-agreement* pair search over the embedding matrix — a numerical operation, not an
  LLM pass over the whole wiki. Gap detection is the inverse: high-density regions of
  raw-chunk embedding space with no wiki chunk nearby. Both run in seconds and both
  scale.
- **The wiki gains a self-assessment.** Coverage (what fraction of raw-chunk embedding
  space has a wiki neighbour within threshold), redundancy (near-duplicate wiki
  chunks), and drift (pages whose embedding has moved far from their cited sources)
  become three numbers on the Maintenance page. `find_orphans()` becomes the trivial
  special case of a general structural health metric.
- **And the honest one:** the system can tell you what it does *not* know. A knowledge
  base that reports its own coverage gaps is a fundamentally different product from one
  that always answers. For a compliance corpus, it is the only defensible one.

That is the disruption. Not "add embeddings." **Make relevance a first-class,
calibrated, deterministic quantity, and then use it everywhere the system currently
guesses** — retrieval, merge routing, lint, contradiction detection, and the decision
to stay silent.

The repo's own best idea is already this idea, applied elsewhere: *stamp it in code,
never ask the model.* OKF conformance is deterministic. Language pinning is
deterministic. `evaluate_condition` is deterministic — Python does the comparison, not
the model. Relevance is the last major judgement still delegated to a 4B instruct model
in free text. Bringing it into the deterministic layer is not a new principle. It is
the existing principle, finished.

---

## PHASE 5 — IMPLEMENTATION SCAFFOLD

Phase 4 gave a *sequence*. This gives the *surface*: which file changes, what the
contract is, what breaks, and — marked **◆ DECISION** — every point where the design
genuinely forks and I am deliberately not choosing for you. Those are not gaps in the
analysis. They are places where the right answer depends on facts about your corpus,
your hardware, or your risk tolerance that no amount of code reading settles.

### 5.0 The invariant, restated as a build rule

Before any of this, make the rule from §A1 mechanically enforceable, because every
stage below leans on it:

> **Every byte outside `wiki/` and `raw/` must be reconstructible by one command.**

```
data/index/          → .gitignore   (postings.json, stats.json, *.sqlite, *.npy)
wiki/, raw/          → git          (the source of truth)
```

Add a CI job: delete `data/index/` in its entirety, run the rebuild, assert the wiki
renders identically. If that passes, embeddings are *provably* a cache and the "no
vector DB" objection is answered by construction rather than by argument. This single
test is what converts §A1 from a position into a property.

**◆ DECISION 1 — the fork this whole document hinges on.**
Either (a) adopt the restatement in §A1 and permit file-backed embeddings, or
(b) hold the literal "no vector DB" rule. Under (b), Stages C–E below are void:
you keep BM25 + query-time HyDE (§3.2) + FTS5 (Stage B) + the entire UX track
(Stage F), which is roughly 60 % of the value for 25 % of the work, and you
permanently forgo abstention. Both are defensible. **Nothing below is worth
starting until this is settled**, because Stage A's fixture is designed to
measure precisely the gap that (b) declines to close.

---

### 5.1 Stage A — zero-risk, do regardless of DECISION 1

Nothing here adds a dependency, changes an interface, or can regress retrieval.

**A.1 — The bench harness (`scripts/bench_retrieval.py` + `bench/fixture_de.json`)**

Mirror qmd's fixture shape so the taxonomy is comparable:

```json
{
  "description": "LocalWiki German retrieval fixture v1",
  "collection": "legal",
  "queries": [
    { "id": "strlschg-62-exact", "query": "§ 62 StrlSchG Genehmigung",
      "type": "exact",    "expected_chunks": ["StrlSchG.md#62"], "expected_in_top_k": 3 },
    { "id": "strlschg-62-para", "query": "Wann brauche ich eine Genehmigung für den Umgang?",
      "type": "semantic", "expected_chunks": ["StrlSchG.md#62"], "expected_in_top_k": 5 }
  ]
}
```

Report precision@5, recall@10, MRR **sliced by `type`**. The slice is the whole point:
an aggregate number will hide the fact that BM25 wins `exact` and loses `semantic`,
which is the only claim being tested.

Two rules, both learned from other implementations getting this wrong:
- **Label by hand.** 3–4 hours. Do not let `gemma4:e4b` generate the labels — they are
  the ground truth you are trying to measure the model against.
- **Assert the corpus is indexed before scoring.** qmd's own bench reports all zeros
  with no warning on an unindexed collection. Fail loudly instead.

**◆ DECISION 2 — fixture scope.** One fixture across all DBs, or one per DB? With
per-DB multi-tenancy the corpora differ in kind (statutes vs. correspondence vs.
technical notes), and a merged fixture will average away exactly the differences
that should drive per-DB tuning. *Lean: per-DB, starting with `legal`.*

**A.2 — Render what is already computed (`app.py`)**

`_render_wiki_nav()` (`app.py:418`) receives `excerpt` and discards it; `matched_terms`
comes back from `lex_index.query()` and is rendered nowhere. Show both, plus the result
count. This is U2 satisfied at near-zero risk and it is the cheapest credibility win in
the repo.

**A.3 — OKF prefix on index text (`okf.py` → `lex_index.build()`)**

Per §3.3, prefix each chunk's *indexed* text with its deterministic OKF identity:

```python
index_text = (
    f"type: {fm['type']} | title: {fm['title']} | "
    f"about: {fm.get('description','')} | tags: {', '.join(fm.get('tags',[]))}\n\n"
    f"{chunk.text}"
)
```

Critical constraint: this alters **indexed** text only. `chunk.text`, `char_start`,
`char_end` and the citation path must be untouched, or `[Source: StrlSchG.md §62]`
silently starts pointing at the wrong span. Keep the prefix out of any snippet
returned to the UI.

**Gate:** re-run A.1. If A.3 does not move recall, the OKF metadata is thinner than
assumed and §3.3's "free win" is not free. Revert it.

---

### 5.2 Stage B — index substrate (`lex_index.py`)

Replace the JSON postings with SQLite FTS5 behind the existing `query()` signature.

```sql
CREATE VIRTUAL TABLE chunks_fts USING fts5(
  chunk_id UNINDEXED, source UNINDEXED, db UNINDEXED,
  index_text,
  tokenize = 'unicode61 remove_diacritics 2'
);
```

**The trap nobody warns you about.** FTS5's built-in tokenizers do **not** stem German.
Your `variants()` (surface / NFKD / digraph-fold / stem) is real work that a naive
migration throws away — and you will not notice, because BM25 will still return
plausible results while quietly losing every compound and inflected match.
*Genehmigungsbedürftigkeit* vs. *Genehmigung* is the failure case, and German legal
prose is made of it.

**◆ DECISION 3 — how German morphology survives FTS5.** Three viable routes:
| Route | Cost | Risk |
|---|---|---|
| **Expand at index time** — write every `variants()` form into `index_text` | Index size ↑ ~2–3× | Dilutes BM25 term density (length normalization) |
| **Expand at query time** — keep `variants()`, emit an FTS5 `OR` query | No index change | Long queries; FTS5 term limits |
| **Custom tokenizer** | C extension or `fts5_tokenizer` API | Breaks the "stdlib sqlite3, no build step" property |
*Lean: query-time expansion — it preserves `variants()` verbatim as the single
source of morphological truth and keeps the index clean. But this is a real fork
and A.1's `alias` slice is the arbiter.*

**◆ DECISION 4 — test-suite blast radius.** `query()` keeps its signature and hit-dict
shape, so shape-asserting tests survive. Any test asserting *ranking order* or
*absolute score* will break, because FTS5's BM25 is not your BM25. Decide now
whether to (a) pin the old implementation as `lex_index_legacy.py` and run both
until the fixture agrees, or (b) accept a one-time re-baselining of order-dependent
tests. *Lean: (a) — with ~258 tests, dual-run is cheap insurance.*

Payoff, independent of everything downstream: `_load()`'s per-query JSON parse of
`postings.json` + `stats.json` disappears (it currently runs on **every keystroke**),
`chunk_meta` stops storing full chunk text inline, and `ingest_end()`'s O(corpus)
rebuild becomes `INSERT`/`DELETE` on affected rows.

---

### 5.3 Stage C — the semantic arm *(requires DECISION 1 = a)*

**C.1 — Embedding via Ollama** (`src/embed_index.py`, new). No new runtime: Ollama is
already a dependency and already exposes `/api/embed`.

**◆ DECISION 5 — which embedding model.** `embeddinggemma-300M` is the qmd default
and is **English-optimised** — the wrong default for a German legal corpus, as
§3.7 already notes. Candidates to benchmark via Ollama (verify exact tags against
the library — I am not certain of current naming): `bge-m3` (multilingual,
strong on German, ~568M), `snowflake-arctic-embed2`, `jina-embeddings-v2-base-de`
(German-specific), or a Qwen3-Embedding GGUF. **Do not take my ranking on faith
— this is a 30-minute A/B against the A.1 fixture with a real number at the end.**
Note that switching models later forces a full re-embed; vectors are not
cross-compatible.

**◆ DECISION 6 — storage layout under multi-tenancy.** One `vectors.npy` per DB, or
one `sqlite-vec` table with a `db` column? Per-DB `.npy` matches the existing
tenancy and access model, keeps each matrix small enough that brute-force cosine
is genuinely single-digit milliseconds, and makes "delete a DB" an `rm`. A shared
sqlite-vec table is tidier and enables cross-DB search — which your access model
may specifically *not* want. *Lean: per-DB `float16` `.npy`, memory-mapped.*

No ANN index. At 10⁴–10⁵ chunks per DB, brute force wins and HNSW is unearned
complexity — as §3.1 already argues.

**C.2 — RRF fusion.** k=60, ×2 weight on the original query, top-rank bonus (+0.05 rank
1, +0.02 ranks 2–3). Parameter-free and degrades gracefully if one arm returns nothing —
which matters during rollout, when arm B may be partially embedded.

**C.3 — Backfill.** Chunks are already persisted in `data/chunks/*.jsonl` with stable
content-addressed `chunk_id`s. The backfill script mirrors `scripts/okf_migrate.py`.
Make it resumable — a 488 KB legal document is ~200 chunks, and a multi-DB corpus will
take a while on CPU.

---

### 5.4 Stage D — ranking and calibration *(verified; corrects §4.1)*

§A3's *conclusion* is correct: a 4B instruct model returning free-text filenames is the
wrong primitive, and a small cross-encoder is the right one. Its *implied cost* is
understated, and §4.1 contains a factual error that follows from it. Both were checked
rather than assumed.

**⚠ Correction to §4.1.** The barrier table states, for VRAM: *"Mitigate via Ollama
`keep_alive` tuning; degrade to RRF-only when the reranker cannot load."* This presumes
Ollama hosts the reranker. **It cannot, as of this writing.**

- Ollama exposes **no `/api/rerank` endpoint**. A cross-encoder's relevance score comes
  from a *classification head*; Ollama surfaces only the embedding layer, not that head.
- `/api/embeddings` on a reranker returns embeddings, not relevance scores.
- `/api/generate` on a reranker returns **uniform ~0.5 for everything** — it does not
  error, it silently produces noise.
- Reranker GGUFs *are* pullable from Ollama's registry (`qwen3-reranker`,
  `dengcao/Qwen3-Reranker-*`), which is what makes this trap expensive: `ollama pull`
  succeeds, the code runs, and the scores are meaningless. Every community workaround
  fakes it by embedding a concatenated `"Query: … Document: … Relevance:"` string — a
  bi-encoder wearing a cross-encoder costume, and **specifically not calibrated**, which
  is the one property Stage E needs.

This is the same failure shape as DECISION 3's German stemming: it does not crash, it
quietly degrades, and the fixture from Stage A is the only thing that catches it.

**What does work.** `llama-server` (ships with llama.cpp) exposes a real
`/v1/rerank` (aliases `/rerank`, `/reranking`, `/v1/reranking`), returning
`{results: [{index, relevance_score}]}`. It requires **three** flags together:

```bash
llama-server -m reranker.gguf --reranking --embedding --pooling rank
```

Miss any one and the server answers *"This server does not support reranking."* That is
the good failure — loud. The bad one is documented too: **Qwen3-Reranker GGUFs can emit
near-zero scores (~4.5e-23)** unless converted with `convert_hf_to_gguf.py` carrying
`cls.output.weight`. `bge-reranker-v2-m3` is the lower-risk starting point and is
**multilingual**, which matters more here than model novelty.

**◆ DECISION 7 — the reranker runtime (now evidence-based).**
| Route | Adds | vs. §4.1 "zero new services" | Calibrated? |
|---|---|---|---|
| **`llama-server --reranking`** as a sidecar | a second HTTP service | ✗ violates literally | ✅ real cross-encoder |
| **`llama-cpp-python`** in-process | one `uv` dep + GGUF | ✅ no service | ⚠️ verify rank pooling is exposed — it was an open request upstream |
| **`sentence-transformers` CrossEncoder** | **torch** (~2 GB) | ✅ no service | ✅ the reference implementation |
| **Skip it** — RRF-fused bi-encoder cosine | nothing | ✅ | ⚠️ partially — see Stage E |
*Lean: try `llama-cpp-python` first because it alone satisfies §4.1 literally; fall
back to `llama-server` as a sidecar and amend §4.1 to "no new **runtime**, one
optional local service." Do not spend a day on ONNX before checking the first two.*
**This is your call, and it is the most consequential one in Phase 5** — it cascades
into §3.5, §3.6 row 3, and the whole of §4.4.

**Two design notes worth stealing regardless of route:**

- **Fail open, always.** On any reranker error — network, timeout, malformed response,
  model not loaded — log it and return the RRF order unchanged. Search reliability beats
  reranker quality; a down reranker must degrade ranking, never break search. This makes
  §4.1's "degrade to RRF-only" real rather than aspirational, and it is the correct
  posture whichever route DECISION 7 takes.
- **One model family for both arms.** `bge-m3` embeds *and* reranks. If DECISION 5 lands
  on `bge-m3` for arm B, `bge-reranker-v2-m3` shares its lineage and multilingual
  coverage — one family, one tokenizer, one German-quality question instead of two.

**D.1 — Position-aware blending** (steal directly from qmd): trust retrieval at ranks
1–3 (75 % RRF / 25 % reranker), balance at 4–10, trust the reranker at 11+. This exists
to stop expansion from diluting exact matches — and `exact` is precisely the slice a
statute corpus cannot afford to lose. Watch it in the A.1 `exact` slice specifically.

**D.2 — Retire `_select_pages()`** (`wiki_engine.py:1253`). Keep it behind a flag for
one release so the fixture can score old-vs-new on the same queries.

**D.0 — Ten-minute check before any of this.** Serve `bge-reranker-v2-m3` with the three
flags, `curl` `/v1/rerank` with one obviously-relevant and one obviously-irrelevant
German passage, and confirm the scores separate. If they do not, stop: the problem is
conversion or pooling, not architecture, and Stage E is unreachable until it is fixed.

---

### 5.5 Stage E — abstention *(after D — but partially reachable without it)*

The safety property from §3.5. Mechanically trivial; the calibration is the entire
difficulty.

**Partial reachability without DECISION 7.** §3.5 says abstention is impossible because
"BM25 produces unbounded, query-incomparable scores." True of BM25 — but **not** of arm
B. Cosine similarity is bounded [-1, 1] and *is* comparable across queries. So even under
the "skip the cross-encoder" route, a weaker abstention is available from the embedding
arm alone. It will separate less cleanly than a cross-encoder, but "less separable" is a
measurement, not a verdict. Measure it before concluding abstention is off the table.

**◆ DECISION 8 — who sets the threshold, and at what granularity.** It cannot be
guessed; it comes from the **score separability** measurement in §4.2 step 5 — the
distribution gap between labelled-relevant and labelled-irrelevant scores. Then:
per-DB thresholds (a statute corpus should abstain far more readily than a notes
corpus) or one global? Configurable by the maintainer, or fixed in code per the
repo's own "stamp it, don't ask" instinct? *Lean: per-DB, maintainer-visible,
defaulting conservative — for §-level regulatory questions, a false answer costs
more than a false abstention.*

If separability is poor (heavy overlap between the two distributions), **abstention is
not yet viable and shipping it anyway is worse than not having it** — an abstention
threshold that fires randomly destroys trust faster than an occasional weak answer.
Report the number, then decide.

---

### 5.6 Stage F — UX *(independent of DECISION 1; can run in parallel)*

Worth stating clearly: **the entire UX track is orthogonal to the vector question.**
If DECISION 1 lands on (b), Stage F still ships in full, minus the score bar.

**F.1 — `/_api/search`** beside `/_api/gpu`, using the Starlette route-injection pattern
already proven in `gpu_widget.py`. This is the load-bearing step: it is what makes every
subsequent UX move possible without a framework migration, and the precedent is already
in your repo.

**F.2 — `⌘K` palette** as a `components.html` island against that endpoint. Shape-based
dispatch per §3.5: noun phrase → search; question with a verb → Fast / Deep / Web;
`§` or filename → jump.

**◆ DECISION 9 — HyDE on the interactive path.** §3.2 makes query-time HyDE the
centrepiece, but it costs one generation per query. On the ⌘K instant tier that is
fatal. Options: fire HyDE only on the *considered* tier (Enter, not keystroke);
or gate it on a weak arm-A signal (qmd's conditional expansion); or cache
aggressively by normalised query. *Lean: all three — instant tier is FTS5-only,
always; HyDE only on Enter, only when arm A is weak, always cached.*

**F.3 — reading surface + conversation rail + citation chips.** The largest item and
the one to do last. §3.5's rule stands: hover previews, click scrolls and highlights,
`_show_md_dialog()` retires. Preserve "Save answer to wiki", "↪ Follow up" and
"Reconcile" **exactly** — §3.5 is right that these are ahead of the reference
implementations — and relocate them into the rail.

**◆ DECISION 10 — how far to collapse the tabs.** Full consolidation (steps 8–10) is
an L-sized commitment against a Streamlit app with a working five-page model. The
falsifiable test from §4.2 stands: instrument **time-to-verified-citation** and
require it to roughly halve. If it does not, stop at F.1+F.2 and keep the tabs —
the palette alone captures most of U1.

---

### 5.7 Decision register

| # | Decision | Blocks | My lean | Decided by |
|---|---|---|---|---|
| 1 | ~~Restate or hold "no vector DB"~~ | — | — | **CLOSED §6.1** — video states the derivability rule and ships embeddings. Stages C/D/E proceed. |
| 2 | Fixture: per-DB or merged | A.1 | per-DB | corpus heterogeneity |
| 3 | German morphology under FTS5 | Stage B | query-time expansion | A.1 `alias` slice |
| 4 | Legacy index dual-run | Stage B | yes, one release | test-suite tolerance |
| 5 | Embedding model | Stage C | benchmark, don't guess | A.1, German slices |
| 6 | Vector storage under multi-tenancy | Stage C | per-DB `.npy` | access model |
| 7 | ~~Reranker runtime~~ | — | — | **CLOSED 2026-07-24** — `llama-cpp-python` in-process. D.0 passed (German legal pairs separate by 6.9 logits, ~35 ms/pair CPU). `Llama.rank` is not exposed ⇒ ctypes RANK-pooling path; prebuilt wheels are musl-linked ⇒ build from sdist. |
| 8 | Abstention threshold + granularity — **also gates ladder rung 4 (§6.9.1)** | Stages E + ladder | per-DB, conservative | separability number |
| 9 | ~~HyDE placement~~ | — | — | **CLOSED §6.4** — split by consumer: Explorer = Fast path, agent = full hybrid. |
| 10 | Tab consolidation depth | Stage F | method superseded by §6.5 (image-first); measurement stands | time-to-verified-citation |

### 5.9 Source precedence — how to reconcile this document with the video

**The rule, as given:** *where the video differs, and its position is compatible with
all the findings in this document, the video wins.*

That is conjunctive, and the second clause is load-bearing. It means the video governs
**design choices** but cannot overturn **verified facts about tools**. Applying it
sorts the ten decisions into three buckets.

**Bucket 1 — video wins outright.** Pure design preference; no factual conflict is
possible. Adopt whatever the video does, without argument:

- DECISION 2 (fixture scope), 6 (vector storage layout), 9 (HyDE placement),
  10 (tab consolidation depth)
- The entire Stage F UX model — single surface vs. tabs, palette vs. search box
- Whether query answers are filed back as pages (§4.4's open question)
- Ingest supervision: one-at-a-time vs. batch

**Bucket 2 — video wins, and the cost should be written down.** Compatible, because a
*stricter* constraint is not a factual contradiction — but it voids work downstream:

- **DECISION 1.** If the video states a literal no-float-arrays rule, that is a
  legitimate constraint and it wins. Consequence: Stages C, D and E are void, and
  abstention is lost **entirely** — not just the cross-encoder form, but the weaker
  bi-encoder form in §5.5 too, since that also needs embeddings. §3.5's safety property
  becomes unreachable. Record it as a chosen trade, not an oversight.
- Corollary: if the video instead means *no vector **service*** (no Qdrant, no Chroma),
  it is already in agreement with §A1 and there is nothing to reconcile.

**Bucket 3 — the compatibility test fails; the finding stands.** These are properties of
tools, not opinions about design. A video cannot overturn them, and if one appears to,
the more likely explanation is that it is demonstrating something subtly different — or
a silent failure:

| Finding | Status |
|---|---|
| Ollama exposes no `/api/rerank`; only the embedding layer, not the classification head | verified |
| A reranker on `/api/generate` returns uniform ~0.5 — no error, just noise | verified |
| `llama-server` needs `--reranking` + `--embedding` + `--pooling rank` together | verified |
| Qwen3-Reranker GGUFs can emit ~4.5e-23 without correct `cls.output.weight` conversion | verified |
| FTS5's `unicode61` / `porter` tokenizers do not stem German | verified |
| BM25 produces unbounded, query-incomparable scores | property of BM25 |
| Karpathy's gist recommends `qmd` — BM25 + `sqlite-vec` + embeddings + reranker | quoted from source |

**Why this bucket matters most.** The compatibility clause is precisely what stops a
convincing demo from importing a silent failure. A video showing a reranker "working"
on Ollama looks correct on screen — scores appear, results reorder — while every score
is ~0.5 and the ordering is noise. Same shape as the FTS5 German-stemming trap: nothing
crashes, quality quietly degrades, and only the Stage A fixture catches it.

**So the reconciliation procedure is:** take the video's design decisions wholesale
(Bucket 1), take its constraints and write down what they cost (Bucket 2), and for
anything touching Bucket 3, run the D.0 smoke test before believing the screen.

---

### 5.10 Kill criteria

Stated in advance so they cannot be rationalised away later:

- **Stage A.3** — no recall movement from the OKF prefix ⇒ revert; §3.3 was wrong.
- **Stage C** — fusion fails to beat baseline by ≥15 points recall@10 on the `semantic`
  slice ⇒ the wiki's vocabulary drift is smaller than §1.2 assumes. Stop; invest in
  query-time HyDE alone, at a tenth of the cost.
- **Stage D** — cross-encoder fails to improve precision@5 over RRF alone ⇒ keep fusion,
  drop the third model, accept less separable scores and revisit Stage E.
- **Stage E** — poor score separability ⇒ do not ship abstention. A threshold that fires
  unpredictably is worse than none.
- **Stage F** — time-to-verified-citation does not roughly halve ⇒ consolidation is
  aesthetics. Ship F.1+F.2 and the read-only Explorer (§6.9.3); leave the answer surface
  where it is.

**Measured set** (extended per §6.8 — the video measures two things Stage A originally
did not, and they are the two that decide whether the system gets used):

| Metric | Why |
|---|---|
| recall@10, precision@5, MRR — **sliced by fixture type** | retrieval quality; the slice is the claim |
| score separability (relevant vs. irrelevant distributions) | gates Stage E *and* ladder rung 4 |
| **tokens per question** | the video's headline result; ~50 % reduction attributed to the ladder |
| **wall-clock per question** | ~40 % in the video; and the ladder's real payoff is fewer search rounds |
| answer correctness (n of n) | a token saving that costs correctness is not a saving |
| p50/p95 interactive latency | Fast path must stay sub-second |
| peak VRAM per configuration | decides whether three models co-reside with `gemma4:e4b` |

Every one of these is measured by the harness built in Stage A. That is why Stage A is
step zero and why it is worth building even if you stop immediately afterwards.

---

## PHASE 6 — RECONCILIATION WITH THE SOURCE VIDEO

Applying §5.9's precedence rule against the transcript. The video's system: ~2 000 notes
/ 4 000+ files in an Obsidian vault, Claude Code as the agent, QMD as search, a custom
graph web app as the front end. Different stack from LocalWiki — no OKF, no
multi-tenancy, no statutes, no Streamlit, no Ollama — so its **process** transfers whole
and its **architecture** transfers selectively.

### 6.1 DECISION 1 — RESOLVED, in favour of §A1

**The video does not contain a "no vector database" rule.** Its rule is:

> Markdown is the only truth. Every other part of the architecture is a derived view of
> those files and can be thrown away and rebuilt at any time without losing a single
> piece of knowledge.

That is §A1's restatement and §5.0's derivability invariant, arrived at independently.
Lesson 5 of the closing seven repeats it: no database, no format prison, everything else
is a replaceable view. The same pattern is credited to the two projects reviewed but not
copied (gbrain, Graphify) — *markdown as single truth, the graph merely a derived
intermediate state.*

Decisively: **the video's own system runs an embedding index and three local models.**
QMD downloads a query expander, an embedding model and a reranker (~3 GB total, all
on-device) and the presenter treats this as fully consistent with "markdown is the only
truth" — because the index is derived and disposable.

**Therefore PRD §2.3's "no vector DB" is not inherited from this source.** It is a
local invention, and §A1 was right to challenge it. Under §5.9 this is Bucket 2
collapsing to "already in agreement": there is nothing to reconcile, and Stages C, D
and E are unblocked. This was the hinge of the entire document; it is now settled.

### 6.2 Bucket 3 survives untouched

The video contradicts none of the verified findings. It never uses Ollama at all — the
agent is Claude Code, and every local model runs inside QMD's own runtime. So the
finding that Ollama exposes no `/api/rerank` is confirmed by omission, and the video
demonstrates the working alternative: **let QMD own embedding and reranking.** FTS5
stemming, BM25 unboundedness and the llama.cpp flag requirements are simply not
addressed either way. §5.9's Bucket 3 stands in full.

### 6.3 What the video settles

| Decision | Resolution from the video |
|---|---|
| **1** | Resolved — derivability rule, not no-vectors. Stages C/D/E unblocked. |
| **7** | Partially — a three-model local stack (expander + embedder + reranker) runs on a Mac at ~2 s/search inside `node-llama-cpp`. Existence proof that Stage D is achievable locally; still open *whether LocalWiki gets there via QMD or its own Python.* |
| **9** | Resolved, and better than my framing — see §6.4. |
| **10** | Superseded by a stronger method — see §6.5. |

### 6.4 Two-tier search — independently confirmed, split by *consumer* not keystroke

Phase 5's U1/DECISION 9 proposed splitting search at the latency cliff. The video does
exactly this, and its split is cleaner:

- **Web app search box** → QMD's *fast* path. Query expander + embedding comparison.
  **The reranker is deliberately excluded.** ~2 s CPU, no API tokens, works offline.
- **Claude Code via the search ladder** → the *full* hybrid, reranker included.

So the tier boundary is **who is asking**, not keystroke-vs-Enter. A human scanning
results tolerates approximate ranking; an agent about to commit an answer to the wiki
does not. Adopt this framing over Phase 5's — it is simpler to implement and it maps
onto LocalWiki's existing split between the Explorer and `wiki_engine`'s query path.

### 6.5 The UX method — this replaces Stage F's approach, not its content

The video's largest self-reported failure is directly relevant to Stage F. Describing
the target in prose ("denser, 3D, more depth, less glow") and letting the agent build
cost hours and produced nothing usable. The fix:

1. Generate **target-state images** first, in a separate tool (ChatGPT's image engine).
2. Hand those images to Claude Code as a **visual specification** — not "make it nice."
3. Build **one step at a time**, checking each result in the browser against the target
   image, with explicit human acceptance before the next step.

Stated as the lesson: don't tell the AI in words how it should look; have images of the
finished state generated first and pass those as reference. Two AIs, clear division of
labour — one produces the target, the other builds it.

**This is a Bucket 1 item and it wins outright.** Phase 5's Stage F says *what* to build
and how to falsify it (time-to-verified-citation); it says nothing about how to get an
agent to build it. This fills that gap. DECISION 10's measurement still applies — the
two are complementary.

Design details worth importing wholesale, since they were arrived at empirically:
clusters kept spatially separate so content does not blend; **edges hidden until hover**,
otherwise the graph becomes restless; node size proportional to knowledge volume; detail
panel opening calmly at the side rather than as a modal — which independently confirms
§3.5's objection to `_show_md_dialog()`.

### 6.6 What the video adds that Phase 5 lacks

**(a) The search ladder ("Brain First") — a retrieval *policy*, not a pipeline.**
This is the most important architectural addition. The rulebook in `CLAUDE.md` forbids
the agent from searching freely or reading the vault wholesale. It must descend:

```
1. read index.md            (the catalogue — a few hundred lines)
2. check the wiki           (is this knowledge already condensed?)
3. QMD search               (full hybrid, reranker included)
4. open exactly ONE file    (the best one)   ← NOT adopted; see §6.9
5. answer
```

idea.md has a retrieval *pipeline* (arm A / arm B / RRF / rerank) but no policy deciding
**when to escalate**. These are orthogonal and both are needed. The video attributes its
token result directly to this: without the system, search ran long and each round
re-read the entire prior history; with it, search was over after two rungs.

The framing worth stealing: the answer to "how do I get the whole vault into the context
window" is *you don't* — the trick is a system that needs no larger context window.

**(b) The indexer is deterministic and writes a catalogue, not an inventory.**
No AI anywhere in it. It emits two files: a map file for the graph, and `index.md` —
**one line per area and important file, not per note**, explicitly so the catalogue does
not itself become a book. Every run identical, seconds, free. This is LocalWiki's own
"stamp it in code, never ask the model" principle applied to indexing, and it answers the
scale question Phase 5 left open: the catalogue does not grow per page.

**(c) Conflict marking that refuses to resolve.** The wiki flags contradictions on every
page where they surface — but overwrites nothing and decides nothing. Both claims remain,
each with its source, and the human decides. A planted note with three false claims was
caught three times over; a fourth harmless claim was *not* flagged but folded in as
confirmation of an open point. On the real corpus this surfaced **52 conflict sites** —
genuine contradictions, stale states, and cases where target and actual were not cleanly
separated.

Two operational rules come with it, and both belong in LocalWiki:
- **Repair the source, not the warning.** Deleting the marker just means the next pass
  rediscovers the same conflict, because the files still disagree.
- **Every ingest run is logged** — when, which source, which pages changed. The stated
  reason is exactly §1.2's trust argument: the difference between a system you must
  believe and one you can check.

Note how this differs from §3.5's abstention. Abstention says *"nothing here answers
this."* Conflict marking says *"these two things disagree — you decide."* They are
complementary safety properties, and LocalWiki should have both.

**(d) The window must be earned.** The web app sits at the edge of the architecture
diagram and does exactly three things: draw the graph from the map file, open a clicked
note, host the search box. **It never writes and never decides**; ingest deliberately
never runs there. Blocks 1–4 (vault, indexer, search, rulebook) *are* the system, and
none of them require the user to program. This independently validates Phase 5's staging
— substrate first, interface last.

**(e) The three reference roles.** Presented as the most transferable idea in the video,
and it is: **Baustein** (adopt ready-made — QMD), **Muster** (adapt the idea — Karpathy's
wiki pattern), **Messlatte** (defines how good the result must be — the mockups).
Copying links and saying "build me this" fails because other people's solutions solve
other people's problems.

### 6.7 Where the video and §3.7 diverge — and why both are right

The video's Baustein rule is: don't build yourself what already exists as a maintained,
finished part. It therefore adopts QMD wholesale. §3.7 argues the opposite for LocalWiki.

**The divergence is constraint-driven, not a disagreement.** §3.7's objections are all
LocalWiki-specific and all remain factually true: the Node/Bun runtime beside `uv`, a
second index lifecycle, no awareness of OKF frontmatter, per-DB multi-tenancy, language
pinning, and — the load-bearing one — QMD's ~900-token regex chunking versus
`_chunk_legal`'s `§`-anchored boundaries with exact `char_start`/`char_end`, which are
what make `[Source: StrlSchG.md §62]` possible at all. The video's system has none of
these constraints: no OKF, one user, no statutes.

Under §5.9 the video therefore wins on the **principle** (don't rebuild maintained
components) but not on the **application**, because the compatibility clause fails
against the chunker finding. §3.7's conclusion stands, and gains a caveat: *the burden
of proof is now on building rather than adopting.* If Stage C/D in LocalWiki's own Python
proves harder than budgeted, adopting QMD for the **wiki layer only** — where pages are
small, one-concept-per-file, and citation anchoring matters less than over `raw/` — is a
legitimate fallback rather than a defeat.

### 6.8 What the video does not touch — LocalWiki's actual differentiators

Confirmed absent from the source, which makes them yours rather than gaps:

- **OKF conformance.** Never mentioned. §3.3's "OKF as retrieval signal" is unchallenged
  and remains a genuine differentiator.
- **Abstention.** The system marks conflicts but never declines to answer. Stage E has no
  precedent here.
- **Calibrated relevance as a compile-time quantity** (§4.4). No precedent.
- **German-specific retrieval tuning.** The presenter runs German content on QMD's
  defaults and reports it working — but on personal notes, not statutory language. This
  softens DECISION 5's urgency without settling it; it remains a measurement question.
- **A retrieval benchmark with labelled ground truth.** The video's test is five real
  questions run twice (≈50 % fewer tokens, ≈40 % less time, 5/5 correct both runs), and
  is explicitly described as a practical comparison rather than a study. Phase 5's Stage A
  fixture is strictly stronger. Keep it — but note the video measures something Stage A
  does not: **token and latency cost**, not just recall. Add both to §5.10's metrics.

### 6.9 Amendment — evidence-gated stopping, and the Explorer's remit

Two corrections to §6.6(a) and §6.5, both driven by LocalWiki's corpus rather than by
disagreement with the video.

#### 6.9.1 Rung 4 is a cost rule, not a correctness rule — replace it

"Open exactly one file" is a **stopping condition for context growth**, and for the
video's corpus (personal notes, largely single-fact lookup) it is a reasonable one. For a
statutory corpus it is wrong by construction: a *Genehmigung* question spans several `§`,
`§ 62` refers to `§ 61`, and any answer grounded in one file is either incomplete or
silently omits the qualifying paragraph. The failure is invisible — the answer reads
fluently and is missing an exception.

What is genuinely transferable from the ladder is **escalate late, stop early, never read
the vault wholesale**. Keep all three. Replace the count with evidence:

```
1. read index.md              catalogue only, a few hundred lines
2. check the wiki             is this already condensed? if yes and sufficient → 5
3. retrieve                   Fast or Deep (see 6.9.2)
4. open the JUSTIFIED SET     all hits with score ≥ τ, capped at N files
                              and a hard token budget; log which and why
5. answer, or ABSTAIN         if nothing clears τ (Stage E)
```

Rung 4 is the payoff for Stage D that §4.4 already anticipated. A count-based cutoff is
what you are forced into when scores are uncalibrated — you cannot ask "is this one
relevant enough" so you fall back on "take the top one." A calibrated 0–1 score turns the
stopping rule into a question about evidence: *take everything that clears the bar, up to
what the budget allows.* Same token discipline, no truncation of multi-source answers.

Two guardrails, both cheap:

- **Log the set, not just the answer.** Which files were opened, their scores, which were
  excluded by τ and which by the cap. If the cap ever binds before τ does, the budget is
  too tight for the corpus and should be raised — that is a measurable signal, not a
  judgement call.
- **τ and N are per-DB** (DECISION 8). A statutes DB will want a lower τ and higher N
  than a notes DB; the whole point of per-DB calibration is that these differ.

#### 6.9.2 Fast and Deep survive — and now differ by stopping rule, not just corpus

§3.5's palette distinction holds and gets sharper. The two modes differ along three axes:

| | **Fast** | **Deep** |
|---|---|---|
| Scope | wiki layer (condensed) | wiki + `raw/` sources |
| Retrieval | arm A + arm B + RRF, **no reranker** | full pipeline, reranker included |
| Rung 4 | first page clearing τ, or top-k small | full justified set, τ-gated, budget-capped |
| Latency | sub-second | seconds |
| Answers | "what do I already know about X" | "what is the position on X, with citations" |

This aligns with §6.4's consumer split without contradicting it: Fast is what a human
scanning tolerates, Deep is what an agent committing an answer requires. The useful
consequence for sequencing — **Fast needs only Stage C; Deep needs Stage D.** The
Explorer can therefore ship one full stage earlier than the answer surface.

#### 6.9.3 The Wiki Explorer adopts the video's app wholesale

The Explorer becomes what the video's web app is, with one boundary made explicit.

**Remit — three things only:**
1. Render the graph from the indexer's map file (§6.6b — deterministic, no AI)
2. Open any clicked note in a **side panel**, beside the graph — this retires
   `_show_md_dialog()`, which §3.5 already condemned and the video independently
   confirms
3. Host the search box, running the **Fast** path

**Behaviour, taken from the video:**
- Edges hidden until hover — permanently-drawn edges make the graph restless
- Clusters spatially separated, each with its own colour, not blended
- Node size proportional to knowledge volume
- Click a result → the graph focuses that node and opens the file
- A health view: which clusters are growing, what sits orphaned. `find_orphans()` already
  exists; this gives it a home
- Built via the image-first method of §6.5

**The write boundary — and how U4 survives.** The video's rule is that the app never
writes and never decides; ingest deliberately never runs there. Adopt it for the
Explorer, because the reason generalises: ingest is a long, multi-file, transactional
operation touching 10–15 pages, and a browsing surface is the wrong place to launch
something that needs a review gate.

But §3.5's U4 — "Save answer to wiki", "↪ Follow up", per-contradiction "Reconcile" — is
the compounding loop made visible and must not be lost. The line that keeps both:

> **The Explorer never mutates the wiki. The answer surface may propose a mutation,
> which the human accepts.**

So: browsing and reading are read-only; a *single reviewed page write* originating from
an answer is permitted on the answering surface; a *full ingest* runs only in the agent
context (terminal, Claude Code, or the Obsidian sidebar). That is a sharper rule than
either source states alone, and it preserves both the video's safety boundary and
LocalWiki's strongest existing feature.

#### 6.9.4 Consequences for the scaffold

| Item | Change |
|---|---|
| Ladder rung 4 | count → τ-gated justified set with budget cap; logged |
| DECISION 8 | now governs **both** abstention *and* rung-4 inclusion — same τ, one calibration |
| Stage E | unchanged, and now the ladder's rung 5 has an explicit abstain branch |
| §3.5 U4 | preserved, relocated to the answering surface per §6.9.3 |

---

### 6.10 Net effect on the scaffold

| Item | Change |
|---|---|
| DECISION 1 | **Closed.** Derivability rule confirmed; Stages C/D/E proceed. |
| DECISION 9 | **Closed.** Split by consumer: app = fast path, agent = full hybrid. |
| DECISION 10 | Method superseded by §6.5; the measurement stands. |
| DECISION 7 | Narrowed — local three-model stacks demonstrably work; route still open. |
| DECISION 5 | Softened — defaults may suffice; still a measurement. |
| Stage A | Add token-cost and latency to the measured set, per §6.8. |
| Stage B–C | Unblocked and unchanged. |
| Stage D | Now load-bearing for **two** things: answer precision *and* rung-4 gating (§6.9.1). |
| Stage F | Prepend the image-first method (§6.5). Explorer ships after Stage C; answer surface after Stage D. |
| **New work** | Search ladder (§6.6a, as amended by §6.9.1), deterministic catalogue writer (§6.6b), non-destructive conflict marking + run log (§6.6c). |

The search ladder is the single highest-value import, and it is nearly free: it is a
rulebook change, not code. Note what §6.9.1 does to the dependency graph, though — once
rung 4 gates on τ rather than on a count, the ladder's *quality* depends on Stage D's
calibration. The ladder can ship immediately in count-based form and be upgraded to
evidence-gated when Stage D lands; it should not wait.

---

## Appendix — verified findings from the current code

Cited so the proposal can be checked rather than trusted.

| Finding | Location |
|---|---|
| `search_wiki()` returns `excerpt`; `_render_wiki_nav()` renders only `title` | `wiki_engine.py:1543`, `app.py:418` |
| `matched_terms` returned by `lex_index.query()`, never rendered anywhere | `lex_index.py` (`query`) |
| `_load()` JSON-parses `postings.json` + `stats.json` on **every** query — no cache | `lex_index.py` (`_load`) |
| `chunk_meta` stores full wiki chunk text inline in `stats.json` | `lex_index.py` (`build`) |
| `ingest_end()` → `lex_index.build()` → `all_chunks()` = full corpus rebuild per ingest/batch | `wiki_engine.py:813–826` |
| `QA_MAX_PAIRS_PER_SOURCE = 5` — total per source, not per chunk | `qa_gen.py` |
| Reranking is a 4B instruct call returning free-text filenames, capped at 5 | `wiki_engine.py:1253` (`_select_pages`) |
| No embeddings, vectors, reranking or RRF anywhere in `src/` | `grep -rin "embed\|vector\|rerank\|rrf" src/*.py` → 0 hits |
| Starlette route-injection precedent for a same-origin JSON API | `gpu_widget.py` (`render_gpu_sidebar`) |
| OKF `description` / `tags` / `type` computed deterministically, unused for retrieval | `okf.py`, `docs/okf.md` |
| Chunker produces `§`-anchored chunks with exact `char_start`/`char_end` | `chunker.py` (`_chunk_legal`) |
