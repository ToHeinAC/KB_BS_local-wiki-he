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

- **`src/prompts.py`** is the *only* place that defines LLM prompt strings. All other modules import named constants from here: `RESEARCHER_INSTRUCTIONS`, `INGEST_PROMPT`, `SELECT_PROMPT`, `ANSWER_PROMPT`, `LINT_PROMPT`, `TAVILY_SEARCH_DESCRIPTION`, `FETCH_WEBPAGE_DESCRIPTION`, `THINK_TOOL_DESCRIPTION`, `SUBMIT_FINAL_DESCRIPTION`.
- **`src/dedup.py`** owns `manifest.json`. Every ingest must call `is_duplicate()` before `register_file()`.
- **`src/file_processor.py`** extracts full text from uploaded files (`extract_text()`) and splits large texts into paragraph-bounded chunks (`chunk_text(text, chunk_size=MAX_CHARS)`). Does not write to disk.
- **`src/ollama_client.py`** is the *only* place that imports `ollama`. Exposes `generate()`, `chat()`, `is_available()`.
- **`src/schema_loader.py`** is the *only* place that reads `SCHEMA.md`. Returns the full content as a system prompt string via `get_system_prompt()`.
- **`src/wiki_engine.py`** is the *only* writer to `data/wiki/`. Owns `init_wiki()`, `ingest()`, `query()`, `lint()`, `list_pages()`, `read_page()`, `stats()`, `search_wiki()`, `get_wiki_tree()`.
- **`src/template_loader.py`** reads `templates/insert.md` and returns the ordered list of user-fillable metadata field names via `load_insert_template()`.
- **`src/tools.py`** — deep-researcher tools wired as `langchain_core.tools`: `tavily_search` (parallel batch when `queries=[...]`), `fetch_webpage_content` (parallel httpx + markdownify), `think_tool`, `submit_final_answer` (word/URL gates → writes to `data/wiki/comparisons/`). Descriptions imported from `prompts.py`. Only `agent.py` and `tools.py` may import LangChain-family packages.
- **`src/agent.py`** — owns the deep-researcher LangGraph state machine (`ChatOllama.bind_tools` agent node + `ToolNode`). Public generator `run_research_agent(question, wiki_context)` yields `thought` / `tool_call` / `tool_result` / `final_answer` / `error` step dicts.
- **`src/app.py`** is the UI shell (Streamlit, port 8520). Calls `wiki_engine` and `agent`; never writes wiki files directly.

## Key dataflows

### Ingest

```
upload → dedup.is_duplicate()
       → dedup.register_file()                # saves to data/raw/
       → file_processor.extract_text()        # returns FULL text (no truncation)
       → file_processor.chunk_text(text)      # [text] if ≤MAX_INGEST_CHARS, else N chunks
       → [Upload UI] optional metadata form driven by template_loader.load_insert_template()
       → for each chunk:
           wiki_engine.ingest(chunk, source_name, user_meta=None)
             → schema_loader.get_system_prompt()
             → inject user_meta as authoritative block into prompt (chunk 1 only)
             → ollama_client.generate(system, prompt, temperature=0.3)
             → parse "=== filename.md ===" blocks from LLM response
             → write pages to data/wiki/
             → _rebuild_index()
             → _append_log()
             → return {created, updated, contradictions}
       → aggregate results across chunks → display
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

### Deep researcher (Research page, `src/agent.py`)

Ported from `ToHeinAC/deepagents_ollama`. LangGraph `StateGraph` over `MessagesState`, two nodes:

```
START → agent (ChatOllama.bind_tools) → conditional router
                                          ├─ tools (ToolNode) → agent      (loop)
                                          └─ END   when last AIMessage has no tool_calls,
                                                   or submit_final_answer returned ACCEPTED
```

Phases enforced via the system prompt (`prompts.RESEARCHER_INSTRUCTIONS`):
1. **PLAN** — `think_tool` once at the start; 3–6 sub-questions.
2. **RESEARCH** — `tavily_search` (parallel batch via `queries=[...]`), optional `fetch_webpage_content` (parallel) for high-value URLs.
3. **REFLECT** — `think_tool` after every 2–3 searches.
4. **SUBMIT** — `submit_final_answer(title, answer)`. Validates `>= RESEARCH_MIN_WORDS` words and `>= RESEARCH_MIN_URLS` unique URLs. Rejected reports send the agent back to research.

Quality gates and recursion cap are env-tunable (`RESEARCH_MIN_SEARCHES`, `RESEARCH_MIN_WORDS`, `RESEARCH_MIN_URLS`, `RESEARCH_MAX_ITERATIONS`). LangChain/LangGraph imports are scoped to this module + `src/tools.py` only (CLAUDE.md §5.3).

## Concurrency & state

Synchronous everywhere except the deep-researcher I/O layer. `tavily_search` and `fetch_webpage_content` fan out across a `concurrent.futures.ThreadPoolExecutor` (size = `RESEARCH_PARALLELISM`, default 4). LLM calls remain sequential — local single-GPU; parallel LLM calls would just queue. No asyncio at any boundary.

State is files + JSON only — no database, no cache (PRD §4.4).
