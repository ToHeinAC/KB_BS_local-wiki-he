---
name: tests.md
description: Testing strategy, test cap, and coverage priorities
version: 1.0.0
author: Tobias Hein
---

# Tests

> Authoritative spec: [`PRD.md`](../PRD.md) §4.5 (Testing Strategy).

## Cap (relaxed)

**Originally capped at 100; cap relaxed 2026-05. Current suite 364 tests (361 passing)** (canonical count: [IMPLEMENTATION.md](../IMPLEMENTATION.md) §5). The original cap was relaxed in 2026-05 when the retrieval layer (chunker, lex_index, extractor, qa_gen) added 30 high-signal unit + end-to-end tests; Tier A ingest speedup added 5 more (qa_gen cap, anchored-preference selection, begin/piece/end roundtrip, single-select assertion, back-compat wrapper); the non-Markdown upload converter (`md_convert`) added 10 (plus a `dedup` content-param test); the Stage D cross-encoder (`rerank`) added 14, all mocked so the suite needs no GGUF. The relaxation principle: the cap exists to discourage low-value proliferation; whole new modules with verifiable behaviour are exempt.

## Allocation

- **Core (≈290 tests)** — highest-risk parts of the original system; `wiki_engine` alone carries 72, `tools` 31, and the multi-DB / auth / OKF / language layers a further ~80.
- **Retrieval layer (43 tests)** — `chunker` boundaries + chunk_id stability + persistence (6); `lex_index` BM25 ranking, diacritic/stem variants, scope filtering, incremental updates, index health (13); `embed_index` semantic arm + RRF fusion, all with mocked embeddings (15); `qa_gen` batching + persistence + question-fold rank lift (9).
- **New-feature buffer (~15 tests)** — recently changed UI/agent surfaces. The Streamlit UI itself is exercised ad hoc via `streamlit.testing.v1.AppTest` (page dispatch, nav state, warning banners) rather than by committed tests — see [ui.md](ui.md).

## Priority coverage areas

1. **`dedup.py`** — hash determinism, manifest atomicity, duplicate detection edges.
2. **`file_processor.py`** — per-format extraction (TXT, MD, PDF, DOCX, HTML), unsupported-type error, partial-extraction tolerance.
2b. **`md_convert.py`** — `is_convertible` extension map; deterministic DOCX→Markdown (headings + tables); PDF page routing (text→rewrite vs image→OCR) and progress callback with conversion fns monkeypatched; image→OCR dispatch; per-model OCR prompt selection; unsupported-type error. No real Ollama / pypdfium2 needed.
3. **`chunker.py`** — boundary detection per strategy (legal `§`, markdown, paragraph fallback); `chunk_id` content-addressability and stability.
4. **`lex_index.py`** — BM25 ranking, 4-variant token recall (NFKD vs. umlaut digraph vs. stem), scope filtering, per-source incremental replace/delete, and `index_health()` (missing index reports zeros — the signal that separates *no index* from *no match*).
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
