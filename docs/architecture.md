---
name: architecture.md
description: System architecture — three-layer Karpathy knowledge model, module boundaries, dataflows
version: 1.0.0
author: Tobias Hein
---

# Architecture

> Authoritative spec: [`PRD.md`](../PRD.md) §2 (System Architecture) and §7 (Dataflow Diagrams).

## Three-layer knowledge model

| Layer | Path | Owner | Mutability |
|---|---|---|---|
| 1. Raw sources | `data/raw/` | User uploads | Immutable; LLM **reads only** |
| 2. Wiki | `data/wiki/` | LLM | LLM owns entirely (ingest/query/lint write here) |
| 3. Schema | `SCHEMA.md` (project root) | Maintainer | Injected into every LLM system prompt |

`data/raw/` splits into `uploads/` (originals), `extracted/` (plain text), and `.manifest.json` (SHA-256 dedup registry). `data/wiki/` splits into `index.md`, `log.md`, `overview.md`, plus `concepts/`, `entities/`, `sources/`, `comparisons/`. See PRD §2.1 for the full tree.

## Module boundaries

One Python file per module at project root; no sub-packages (PRD §4.4). Boundaries:

- **`dedup.py`** owns the manifest. Every ingest must pass through `is_duplicate()` first.
- **`file_processor.py`** is the only writer to `data/raw/extracted/`. Originals in `uploads/` stay untouched.
- **`ollama_client.py`** is the *only* place that imports `ollama`. All other modules consume `chat()` / `chat_text()`.
- **`schema_loader.py`** is the *only* place that reads `SCHEMA.md`. It produces ready-made system prompts for ingest, query, and lint.
- **`wiki_engine.py`** is the only writer to `data/wiki/`. It owns `ingest()`, `query()`, `lint()`, plus tree/stats/search helpers.
- **`tools.py`** wraps the two ReAct tools (`tavily_search`, `report_writer`) plus their JSON schemas; `report_writer` reuses `wiki_engine`-style writes.
- **`agent.py`** owns the ReAct loop. Hard cap: 8 iterations.
- **`app.py`** is the UI shell. It calls `wiki_engine` and `agent`; it never writes wiki files directly.

## Key dataflows

- **Ingest:** upload → `dedup.is_duplicate` → `file_processor.extract_text` → `wiki_engine.ingest` → Ollama call (temperature 0.3) → parse `### FILE:` / `### INDEX_UPDATE` / `### LOG_ENTRY` blocks → write pages, update `index.md`, append `log.md`. Detail: PRD §3.6.1, §7.1.
- **Query:** read `index.md` → load up to 5 most relevant pages (heuristic: title in question) → Ollama call (temperature 0.7) → optionally file response as comparison page. Total context capped ≈12 KB. Detail: PRD §3.6.2.
- **Lint:** read all wiki pages (or fall back to index-only if >15 KB) → Ollama call → markdown health report (contradictions / orphans / missing / stale / suggestions) → append to `log.md`. Detail: PRD §3.6.3.
- **ReAct:** alternate `ollama.chat(tools=…)` and tool execution; `tavily_search` keeps loop alive, `report_writer` ends it. Reflection prompt appended after each tool batch. Detail: PRD §3.8, §7.2.

## Concurrency & state

Synchronous everywhere. State is files + JSON only — no database, no cache, no async (PRD §4.4). Manifest writes are atomic (temp file + rename, PRD §3.1).
