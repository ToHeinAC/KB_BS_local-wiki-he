---
name: tests.md
description: Testing strategy, test cap, and coverage priorities
version: 1.0.0
author: Tobias Hein
---

# Tests

> Original spec: [`_bup_PRD.md`](_bup_PRD.md) §4.5 (Testing Strategy).

## Cap (relaxed)

**Originally capped at 100; cap relaxed 2026-05.** The suite is now gated by coverage instead of a count (AGENTS.md §5.4). The original cap was relaxed in 2026-05 when the retrieval layer (chunker, lex_index, extractor, qa_gen) added 30 high-signal unit + end-to-end tests; Tier A ingest speedup added 5 more (qa_gen cap, anchored-preference selection, begin/piece/end roundtrip, single-select assertion, back-compat wrapper); the non-Markdown upload converter (`md_convert`) added 10 (plus a `dedup` content-param test); the Stage D cross-encoder (`rerank`) added 14, all mocked so the suite needs no GGUF; page-language pinning (`tests/test_page_language.py`) added 22 with a prompt-routed fake LLM and a stubbed embedder, so they need no Ollama. The relaxation principle: the cap exists to discourage low-value proliferation; whole new modules with verifiable behaviour are exempt.

## Allocation

~660 tests; branch coverage ≥ 85 % is the gate (currently ≈ 89 %), not a count.

- **Core modules** — one `tests/test_<module>.py` per `src/` module (`wiki_engine`, `tools`,
  retrieval, multi-DB, auth, OKF, language, GPU placement, …).
- **Characterization tests** pin behaviour before a refactor where none existed:
  `test_delete_source.py` (the cross-store cascade) and `test_evaluate_condition.py`.
- **UI** — `tests/test_app.py` drives `src/app.py` through Streamlit's in-process `AppTest`
  (login, Upload, Explorer, Chat, Research, Maintenance, sidebar) against a temp `DATA_ROOT`,
  with the daemon, GPU widget and LLM-facing engine calls stubbed.
- **Native reranker** — `test_rerank_native.py` runs `_load`/`_tokenize`/`_score_one` against
  a pure-Python stand-in for the `llama_cpp` ctypes surface.
- **Gate rules** — `test_code_rules.py` (functions ≤ 50 lines) and `test_docs.py` (doc size
  limits, resolvable links), each with a test that feeds its detector a violating input.

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

- pytest with pytest-cov and pytest-timeout (`[dependency-groups] dev` in `pyproject.toml`).
- Fast loop: `uv run pytest`; full gate: `uv run pre-commit run --all-files` (branch coverage
  ≥ 85 %, suite ≤ 60 s; numbers in `pyproject.toml`).
- Offline: `tests/conftest.py` blocks every socket connect. Stub Ollama, Tavily and the pinned
  daemon (`ollama_client.host`) instead of reaching them.
- Hermetic: `conftest.py` disables `load_dotenv`, so the developer's `.env` never changes test
  results (CI has none), and hashes test passwords at bcrypt's minimum cost.
- The gate runs the suite in parallel (`pytest-xdist`, `-n auto`): `AppTest` is ~3.5× slower
  under coverage, and the suite must stay ≤ 60 s.
- Integration test (PRD §9 step 9): upload → ingest → chat → research, end-to-end.
