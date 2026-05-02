---
name: tests.md
description: Testing strategy, test cap, and coverage priorities
version: 1.0.0
author: Tobias Hein
---

# Tests

> Authoritative spec: [`PRD.md`](../PRD.md) §4.5 (Testing Strategy).

## Hard cap

**100 automated tests, total.** The cap is a feature, not an aspiration: it forces high-signal coverage and keeps the suite fast.

## Allocation

- **≈90 tests** — the most important and highest-risk parts of the system.
- **≈10 tests** — newly implemented or recently changed features.

## Priority coverage areas

1. **`dedup.py`** — hash determinism, manifest atomicity, duplicate detection edges.
2. **`file_processor.py`** — per-format extraction (TXT, MD, PDF, DOCX, HTML), unsupported-type error, 50 KB truncation marker, partial-extraction tolerance.
3. **`ollama_client.py`** — `is_available()` behaviour, `OllamaConnectionError` raised on failure, temperature defaults.
4. **`wiki_engine.py`** — ingest parses LLM output and writes files; query loads relevant pages; lint produces a report; helpers (`get_wiki_stats`, `search_wiki`, etc.).
5. **Critical error handling** — Ollama down, model missing, `TAVILY_API_KEY` missing, malformed LLM output.

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
