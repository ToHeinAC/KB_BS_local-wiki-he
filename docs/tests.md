---
name: tests.md
description: Testing strategy, test cap, and coverage priorities
version: 1.0.0
author: Tobias Hein
---

# Tests

> Authoritative spec: [`PRD.md`](../PRD.md) §4.5 (Testing Strategy).

## Cap (relaxed)

**Originally 100 tests, current: ~170.** The original cap was relaxed in 2026-05 when the retrieval layer (chunker, lex_index, extractor, qa_gen) added 30 high-signal unit + end-to-end tests; Tier A ingest speedup added 5 more (qa_gen cap, anchored-preference selection, begin/piece/end roundtrip, single-select assertion, back-compat wrapper); the non-Markdown upload converter (`md_convert`) added 10 (plus a `dedup` content-param test). The relaxation principle: the cap exists to discourage low-value proliferation; whole new modules with verifiable behaviour are exempt.

## Allocation

- **Core (≈90 tests)** — highest-risk parts of the original system.
- **Retrieval layer (≈30 tests)** — chunker boundaries + chunk_id stability + persistence; BM25 ranking, diacritic/stem variants, fuzzy fallback; extractor JSON parsing + idempotent merge + alias/acronym query-expansion lift; qa-gen batching + persistence + question-fold rank lift.
- **New-feature buffer (~10 tests)** — recently changed UI/agent surfaces.

## Priority coverage areas

1. **`dedup.py`** — hash determinism, manifest atomicity, duplicate detection edges.
2. **`file_processor.py`** — per-format extraction (TXT, MD, PDF, DOCX, HTML), unsupported-type error, partial-extraction tolerance.
2b. **`md_convert.py`** — `is_convertible` extension map; deterministic DOCX→Markdown (headings + tables); PDF page routing (text→rewrite vs image→OCR) and progress callback with conversion fns monkeypatched; image→OCR dispatch; per-model OCR prompt selection; unsupported-type error. No real Ollama / pypdfium2 needed.
3. **`chunker.py`** — boundary detection per strategy (legal `§`, markdown, paragraph fallback); `chunk_id` content-addressability and stability.
4. **`lex_index.py`** — BM25 ranking, 4-variant token recall (NFKD vs. umlaut digraph vs. stem), trigram fuzzy fallback Jaccard threshold, query expansion via aliases/acronyms, `facts_lookup`.
5. **`extractor.py`** — JSON parse + fence stripping, swallow on LLM failure, idempotent merge across re-ingests, digest path for large sources.
6. **`qa_gen.py`** — JSON parse, unknown-chunk-id rejection, batching, end-to-end rank lift when questions are folded into BM25.
7. **`ollama_client.py`** — `is_available()` behaviour, error raised on failure, temperature defaults.
8. **`wiki_engine.py`** — ingest parses LLM output and writes files; query loads relevant pages; lint produces a report; helpers (`get_wiki_stats`, `search_wiki`, etc.).
9. **`auth.py`** — maintainer layer: `is_maintainer` true only for an assigned DB (admin is not implicit), `grant_maintainer` adds to both `dbs` + `maintains`, `backfill_maintainers` is idempotent and backfills admins only.
10. **Critical error handling** — Ollama down, model missing, `TAVILY_API_KEY` missing, malformed LLM output, extractor/qa-gen failures must never break ingest.

## What to avoid

- Broad low-value test proliferation.
- Snapshot sprawl.
- Exhaustive UI micro-tests.
- Tests that exist only to exercise framework defaults.

Prefer a compact suite of high-signal unit + integration tests over a large volume of shallow tests.

## Tooling

- `pytest ≥ 8.0` (dev dependency).
- Run with `uv run pytest`.
- Integration test (PRD §9 step 9): upload → ingest → chat → research, end-to-end.
