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

- **`src/prompts.py`** is the *only* place that defines LLM prompt strings. All other modules import named constants from here: `RESEARCHER_INSTRUCTIONS`, `CHAT_AGENT_SYSTEM`, `INGEST_PROMPT`, `SELECT_PROMPT`, `ANSWER_PROMPT`, `LINT_PROMPT`, `WIKI_SEARCH_DESCRIPTION`, `WIKI_READ_DESCRIPTION`, `TAVILY_SEARCH_DESCRIPTION`, `FETCH_WEBPAGE_DESCRIPTION`, `RAW_SEARCH_DESCRIPTION`, `RAW_READ_DESCRIPTION`, `THINK_TOOL_DESCRIPTION`, `SUBMIT_FINAL_DESCRIPTION`, `SUBMIT_CHAT_DESCRIPTION`.
- **`src/dedup.py`** owns `manifest.json`. Every ingest must call `is_duplicate()` before `register_file()`.
- **`src/file_processor.py`** extracts full text from uploaded files (`extract_text()`) and splits large texts into paragraph-bounded chunks (`chunk_text(text, chunk_size=MAX_CHARS)`). Does not write to disk.
- **`src/ollama_client.py`** is the *only* place that imports `ollama`. Exposes `generate()`, `chat()`, `is_available()`.
- **`src/schema_loader.py`** is the *only* place that reads `SCHEMA.md`. Returns the full content as a system prompt string via `get_system_prompt()`.
- **`src/wiki_engine.py`** is the *only* writer to `data/wiki/`. Owns `init_wiki()`, `ingest()`, `query()`, `lint()`, `list_pages()`, `read_page()`, `read_page_parsed()`, `stats()`, `search_wiki()`, `get_wiki_tree()`. `read_page_parsed()` strips YAML frontmatter and returns `{content, sources, related}` for clean UI rendering.
- **`src/template_loader.py`** reads `templates/insert.md` and returns the ordered list of user-fillable metadata field names via `load_insert_template()`.
- **`src/tools.py`** — agent tools wired as `langchain_core.tools`. **Research tools** (`TOOLS`): `wiki_search`, `wiki_read`, `tavily_search`, `fetch_webpage_content`, `think_tool`, `submit_final_answer` (word/source gates → writes to `data/wiki/comparisons/`; counts `https://` URLs and `[Wiki: filename.md]` citations toward `RESEARCH_MIN_URLS`). **Chat tools** (`CHAT_TOOLS`): `raw_search` (tokenized prefix-match grep over `data/raw/` — splits the query into whitespace tokens, matches first 6 chars of each as substring, returns up to 3 excerpts per file ranked by token-hit count; tolerant of German morphology), `raw_read` (bulk read with `offset` parameter; 8000-char window per call with `[truncated; pass offset=N to continue]` footer; strips `§X`/`#section` section suffixes from filenames), `think_tool`, `submit_chat_answer` (word/source gates; returns to caller, no file written). `_RAW_CITE_RE` accepts an optional trailing ` §...` / ` #...` section marker so distinct sections of the same long file count as distinct sources for `CHAT_MIN_SOURCES`. Descriptions imported from `prompts.py`. Only `agent.py`, `chat_agent.py`, and `tools.py` may import LangChain-family packages.
- **`src/agent.py`** — owns the deep-researcher LangGraph state machine (`ChatOllama.bind_tools(TOOLS)` agent node + `ToolNode`). `_load_wiki_index()` injects `data/wiki/index.md` into the system prompt so the agent knows which pages exist before any tool call. Public generator `run_research_agent(question, wiki_context)` yields `thought` / `tool_call` / `tool_result` / `final_answer` / `error` step dicts.
- **`src/chat_agent.py`** — owns the deep-chat LangGraph state machine (`ChatOllama.bind_tools(CHAT_TOOLS)` agent node + `ToolNode`). `_build_raw_index()` injects a one-line-per-file index of `data/raw/` (first markdown heading per file) into the system prompt. Public generator `run_chat_agent(question)` yields the same step-dict shape as the research agent. On `GRAPH_RECURSION_LIMIT`, the loop surfaces the last AIMessage as a partial answer rather than only an error.
- **`src/app.py`** is the UI shell (Streamlit, port 8520). Calls `wiki_engine`, `agent`, and `chat_agent`; never writes wiki files directly. `_raw_source_button()` strips `§`/`#` section suffixes before resolving citations to files in `data/raw/`.

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
wiki_engine.query_with_sources(question)
  → read index.md
  → ollama_client.generate(select prompt, temperature=0.1)  # pick ≤5 filenames
  → load selected pages from data/wiki/
  → extract raw_sources from page frontmatter `sources` field
  → ollama_client.generate(answer prompt, temperature=0.7)
  → return {answer, sources (wiki filenames), raw_sources (original data/raw/ filenames)}
```

`app.py` Chat page and Wiki Explorer both render sources in a collapsible "Sources" expander (original `data/raw/` documents + related wiki pages).

### Deep chat (Chat page "Deep" mode, `src/chat_agent.py`)

Same LangGraph shape as the deep researcher but scoped to `data/raw/` only:

```
START → agent (ChatOllama.bind_tools(CHAT_TOOLS)) → conditional router
                                                     ├─ tools → agent (loop)
                                                     └─ END on no tool_calls
                                                              or submit_chat_answer ACCEPTED
```

Tools bound: `raw_search` (tokenized prefix-match grep over `data/raw/` — see `src/tools.py` description for `RAW_TOKEN_PREFIX` semantics; returns up to 3 excerpts per file), `raw_read` (paginated bulk read; 8000-char window per call, `offset` param, footer with continuation hint), `think_tool`, `submit_chat_answer` (gates: `CHAT_MIN_WORDS` / `CHAT_MIN_SOURCES`; section-suffixed citations count as distinct). No web tools. The system prompt (`prompts.CHAT_AGENT_SYSTEM`) pre-loads a one-line-per-file index of `data/raw/` and instructs the agent to use single-stem keywords (not full sentences) and to paginate long documents via `offset`.

Gates roughly halved vs research for ~2× speed, with one extra iteration headroom for pagination: `CHAT_MAX_ITERATIONS=25`, `CHAT_MIN_WORDS=300`, `CHAT_MIN_SOURCES=2`, `CHAT_MIN_SEARCHES=3`. On accept, the answer is returned to the UI (no file written); the existing manual "Save to wiki" button writes to `data/wiki/insights/` as in Fast mode. If the recursion limit is hit before submission, the loop surfaces the last AIMessage as a `(partial — recursion limit hit)` answer instead of a bare error.

The Chat page exposes a `Fast | Deep` radio toggle: Fast → `wiki_engine.query_with_sources` (existing one-shot RAG over wiki pages); Deep → `chat_agent.run_chat_agent` (this loop). The Deep-mode message renders an "Agent trace" expander with the step-by-step thought / tool_call / tool_result feed.

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
1. **PLAN** — `think_tool` once at the start; break question into 3–6 sub-questions.
2. **WIKI FIRST** — first non-think tool call **must** be `wiki_search` (parallel batch). The system prompt pre-loads `data/wiki/index.md` so the agent already knows which pages exist.
3. **TRIAGE** — `think_tool` after every tool result with three required sections: `Have:` / `Gaps vs original query:` / `Next:`. Tangential threads must be listed under `Parked (out of scope):` and not pursued.
4. **AUTONOMOUS EXPANSION** — `wiki_read` for promising hits; `tavily_search` only for gaps the wiki cannot fill; optional `fetch_webpage_content` for high-value URLs.
5. **SUBMIT** — `submit_final_answer(title, answer)`. Validates `>= RESEARCH_MIN_WORDS` words and `>= RESEARCH_MIN_URLS` unique sources (URLs + `[Wiki: filename.md]` citations). Rejected reports send the agent back to research.

Quality gates and recursion cap are env-tunable (`RESEARCH_MIN_SEARCHES`, `RESEARCH_MIN_WORDS`, `RESEARCH_MIN_URLS`, `RESEARCH_MAX_ITERATIONS`). LangChain/LangGraph imports are scoped to this module + `src/tools.py` only (CLAUDE.md §5.3).

## Concurrency & state

Synchronous everywhere except the agent I/O layer. `tavily_search`, `fetch_webpage_content`, `wiki_search`, `wiki_read`, `raw_search`, and `raw_read` fan out across a `concurrent.futures.ThreadPoolExecutor` (size = `RESEARCH_PARALLELISM`, default 4 — shared by research and chat tools). LLM calls remain sequential — local single-GPU; parallel LLM calls would just queue. No asyncio at any boundary.

State is files + JSON only — no database, no cache (PRD §4.4).
