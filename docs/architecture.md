---
name: architecture.md
description: System architecture — three-layer Karpathy knowledge model, module boundaries, dataflows
version: 1.1.0
author: Tobias Hein
---

# Architecture

> Authoritative spec: [`PRD.md`](../PRD.md) §2 (System Architecture) and §7 (Dataflow Diagrams).
> Implementation deviations from PRD are tracked in [`IMPLEMENTATION.md`](../IMPLEMENTATION.md) §4.

## Three-layer knowledge model

| Layer | Path | Owner | Mutability |
|---|---|---|---|
| 1. Raw sources | `data/raw/` | User uploads | Immutable; LLM **reads only** |
| 2. Wiki | `data/wiki/` | LLM | LLM owns entirely (ingest/query/lint write here) |
| 3. Schema | `SCHEMA.md` (project root) | Maintainer | Injected into every LLM system prompt |

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

- **`src/prompts.py`** is the *only* place that defines LLM prompt strings. All other modules import named constants from here (e.g. `AGENT_SYSTEM`, `INGEST_PROMPT`, `SELECT_PROMPT`, `ANSWER_PROMPT`, `LINT_PROMPT`, `TAVILY_SEARCH_DESCRIPTION`, `REPORT_WRITER_DESCRIPTION`).
- **`src/dedup.py`** owns `manifest.json`. Every ingest must call `is_duplicate()` before `register_file()`.
- **`src/file_processor.py`** extracts text from uploaded files and returns it as a string (does not write to disk).
- **`src/ollama_client.py`** is the *only* place that imports `ollama`. Exposes `generate()`, `chat()`, `is_available()`.
- **`src/schema_loader.py`** is the *only* place that reads `SCHEMA.md`. Returns the full content as a system prompt string via `get_system_prompt()`.
- **`src/wiki_engine.py`** is the *only* writer to `data/wiki/`. Owns `init_wiki()`, `ingest()`, `query()`, `lint()`, `list_pages()`, `read_page()`, `stats()`, `search_wiki()`, `get_wiki_tree()`.
- **`src/template_loader.py`** reads `templates/insert.md` and returns the ordered list of user-fillable metadata field names via `load_insert_template()`.
- **`src/tools.py`** — wraps `tavily_search` and `report_writer` tool definitions for the ReAct agent. Descriptions imported from `prompts.py`.
- **`src/agent.py`** — owns the ReAct loop (hard cap: 8 iterations).
- **`src/app.py`** is the UI shell (Streamlit, port 8520). Calls `wiki_engine` and `agent`; never writes wiki files directly.

## Key dataflows

### Ingest

```
upload → dedup.is_duplicate()
       → dedup.register_file()           # saves to data/raw/
       → file_processor.extract_text()   # returns string
       → [Upload UI] optional metadata form driven by template_loader.load_insert_template()
       → wiki_engine.ingest(text, source_name, user_meta=None)
         → schema_loader.get_system_prompt()
         → inject user_meta as authoritative block into prompt (if provided)
         → ollama_client.generate(system, prompt, temperature=0.3)
         → parse "=== filename.md ===" blocks from LLM response
         → write pages to data/wiki/
         → _rebuild_index()
         → _append_log()
         → return {created, updated, contradictions}
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
wiki_engine.query(question)
  → read index.md
  → ollama_client.generate(select prompt, temperature=0.1)  # pick ≤5 filenames
  → load selected pages from data/wiki/
  → ollama_client.generate(answer prompt, temperature=0.7)
  → return answer string
```

### Lint

```
wiki_engine.lint()
  → read all *.md in data/wiki/ (except index + log)
  → ollama_client.generate(health-check prompt, temperature=0.3)
  → append report to log.md
  → return report string
```

### ReAct (not yet implemented)

```
agent.run(question)
  → alternate ollama.chat(tools=[tavily_search, report_writer]) and tool execution
  → max 8 iterations
  → report_writer saves final report to data/wiki/
```

Detail: PRD §3.8, §7.2.

## Concurrency & state

Synchronous everywhere. State is files + JSON only — no database, no cache, no async (PRD §4.4).
