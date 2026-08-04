---
name: deep_research.md
description: Research page "Deep" mode — a web-only Open Deep Research supervisor pipeline (vendored, Ollama + Tavily)
version: 2.0.0
author: Tobias Hein
status: Implemented
---

# Deep Research (web mode)

The Research page runs **two** agents, chosen by a `Quick` / `Deep` segmented control:

| | Quick | Deep |
|---|---|---|
| Module | `src/agent.py` | `src/deep_research_agent.py` |
| Topology | one ReAct loop (`agent → tools → agent`) | supervisor → N researcher subgraphs → report |
| Sources | wiki/raw **first**, web for gaps | **web only** |
| Citations | `[Wiki: …]`, `[Source: …]`, URLs | web URLs |
| Quality gate | `RESEARCH_MIN_*` in `tools.submit_final_answer` | none (upstream pipeline) |

Deep mode is the vendored [`open_deep_research`](https://github.com/langchain-ai/open_deep_research)
graph pointed at local Ollama + Tavily. It does **not** touch the wiki or `data/raw/`.

## Why the package is vendored, not depended on

Upstream's `pyproject.toml` declares ~40 runtime dependencies — `azure-identity`,
`azure-search-documents`, `supabase`, `langchain-aws`, `langchain-google-vertexai`,
`openai`, `pandas`, `pymupdf`, `ipykernel`, `langgraph-cli[inmem]` — and pins the
LangChain **0.3** line. `uv add`ing it would (a) contradict IMPLEMENTATION.md §5's
no-cloud-LLM-APIs rule with a wall of cloud SDKs, and (b) very likely downgrade this
project's `langchain-core` 1.x / `langgraph` 1.x, breaking `src/agent.py` and
`src/chat_agent.py`.

The five modules we actually need import very little: `langchain` (`init_chat_model`),
`aiohttp`, `langchain-mcp-adapters`, `mcp` — the only four additions to `pyproject.toml`.
Provenance, licence (MIT), the pinned commit and the single mechanical edit are recorded
in [`src/vendor/README.md`](../src/vendor/README.md).

`mcp` is pinned `<2`: 2.x dropped `mcp.shared.context.RequestContext`, which
`langchain-mcp-adapters` imports at module load. MCP itself is unused (`mcp_config`
stays `None`) — the import is simply unavoidable in upstream's `utils.py`.

## Architecture

```
deep_researcher                                    (src/vendor/open_deep_research/)
  START
   → clarify_with_user        (disabled — allow_clarification=False, the page is one-shot)
   → write_research_brief     (ResearchQuestion schema)
   → research_supervisor      ── supervisor_subgraph ───────────────────────────┐
   → final_report_generation                                                    │
   → END                                                                        │
                                                                                │
  supervisor_subgraph:                                                          │
     supervisor        (tools: ConductResearch, ResearchComplete, think_tool)   │
     supervisor_tools  → asyncio.gather → N × researcher_subgraph  ◄────────────┘
                                (researcher → researcher_tools → compress_research)
```

`src/deep_research_agent.py` is the only thing we wrote: it builds the `Configuration`,
pumps the graph, and maps its events onto the Research page's step-dict contract.

### Configuration (upstream field → our value)

| Upstream field | Upstream default | Ours |
|---|---|---|
| `research_model` / `final_report_model` / `compression_model` / `summarization_model` | `openai:gpt-4.1(-mini)` | `ollama:<DEEP_RESEARCH_MODEL>` |
| `search_api` | `TAVILY` | `TAVILY` (reuses `TAVILY_API_KEY`) |
| `allow_clarification` | `True` | **`False`** |
| `max_concurrent_research_units` | 5 | `DEEP_RESEARCH_CONCURRENCY` (1) |
| `max_researcher_iterations` | 6 | `DEEP_RESEARCH_MAX_ITERATIONS` (4) |
| `max_react_tool_calls` | 10 | `DEEP_RESEARCH_MAX_TOOL_CALLS` (6) |
| `*_model_max_tokens` | 8192–10000 | `DEEP_RESEARCH_MAX_TOKENS` (8192) |

All `DEEP_RESEARCH_*` vars are registered in IMPLEMENTATION.md §6 and `.env.example`.

## Non-obvious facts (each cost a debugging round-trip — do not re-guess)

- **`Configuration.from_runnable_config` reads `os.environ[FIELD.upper()]` *before* the
  `configurable` dict.** A stray `RESEARCH_MODEL` or `SEARCH_API` in the environment
  silently overrides our config. This is why every knob is namespaced `DEEP_RESEARCH_*`
  rather than reusing the upstream field names.

- **Ollama's `base_url` is not configurable, so it is wired through `$OLLAMA_HOST`.**
  `Configuration` makes only `model` / `max_tokens` / `api_key` configurable.
  `init_chat_model("ollama:<tag>")` builds a `ChatOllama` with `base_url=None`, and the
  ollama SDK then falls back to `host or os.getenv("OLLAMA_HOST")`. `run_deep_research`
  therefore sets `os.environ["OLLAMA_HOST"] = ollama_client._HOST` before streaming.

- **`max_tokens` is a no-op on Ollama.** `ChatOllama` bounds output with `num_predict`;
  `max_tokens` is accepted and ignored. `DEEP_RESEARCH_MAX_TOKENS` sets the upstream
  config fields (which feed upstream's token-limit retry logic) but does not bound
  generation. Don't "fix" this by patching the vendored tree.

- **Web citations arrive via `raw_notes`, not via tool messages.** `supervisor_tools`
  runs the researcher subgraphs with `researcher_subgraph.ainvoke(...)` — they are not
  wired as graph nodes — so their `web_search` `ToolMessage`s never reach the parent
  stream, *even with `subgraphs=True`*. What does come back is `raw_notes`: the
  concatenated researcher tool output, still carrying upstream's
  `--- SOURCE n: <title> ---` / `URL: <url>` blocks. That is what
  `_extract_sources` parses into the per-URL citation cards.

- **Parent nodes replay their subgraph's state.** The `research_supervisor` update
  re-emits every supervisor message the subgraph already streamed, so the same thought
  or tool call arrives two or three times. `_step_key` de-duplicates before yielding.

- **`final_report_generation` never raises.** It catches its own exceptions and returns
  them *as the report string* (`"Error generating final report: …"`), so a failed run
  looks like a successful one. The fallback check tests that prefix explicitly.

- **`ResearchComplete` is a zero-field sentinel, not a broken call.** It is a pydantic model
  with **no fields** (`state.py`), so its `args` are correctly and always `{}`; and
  `supervisor_tools` matches on its *name* and jumps straight to `END` without appending a
  `ToolMessage`, so it is the one tool call that never gets a result. Empty args + no result is
  the expected shape. The adapter marks it `terminal: True` and attaches an explanatory `note`
  (`TOOL_NOTES`) so the UI renders "research phase finished" instead of `ResearchComplete — {}`,
  which reads as a failure. Note it is only *one* of three exit paths — the supervisor may also
  stop by emitting no tool calls, or by exceeding `max_researcher_iterations`, in which case no
  `ResearchComplete` appears in the trace at all.

- **Search effort is counted from tool output, not tool calls.** The researcher subgraphs never
  stream, so `tavily_search` invocations are invisible; `compress_research`'s prose "queries I
  ran" list is LLM-written and unreliable. `_SEARCH_CALL_RE` counts `Search results:` /
  `No valid search results found` headers in `raw_notes` — upstream emits exactly one per
  `tavily_search` call. The number of *queries* inside a batched call is not recoverable: the
  formatted output drops the per-result `query` field.

- **Failure falls back to Quick, it does not error.** Small local models are weak at the
  structured output and tool calling this graph leans on. On any graph exception, an
  empty report, or the error-prefix above, `run_deep_research` emits a `notice` step and
  then delegates to `agent.run_research_agent`, so the user still gets an answer. The
  Research page renders `notice` as `st.warning`.

## Integration seams

- **Step-dict contract.** `run_deep_research(question, wiki_context="") -> Generator[dict]`
  emits the same shapes as `src/agent.py:3-9`, plus `{"type": "notice"}` for the
  mode-level fallback. Additive keys the Quick path does not set, all optional so the
  shared renderer stays backward-compatible:

  | Key | On | Meaning |
  |---|---|---|
  | `label` | `thought` | Expander title — `Research brief` / `Sub-topic findings` / `Supervisor reasoning` |
  | `note` | `tool_call`, `tool_result` | Plain-English gloss of the tool (`TOOL_NOTES`) |
  | `terminal` | `tool_call` | `True` only for `ResearchComplete` (see above) |
  | `sources` | `tool_result`, `final_answer` | `[{url, title}]` citation cards |
  | `searches` | `tool_result` | `tavily_search` calls represented by this result |
  | `metrics` | `final_answer` | `{tasks, searches, sources_checked, sources_cited}` |

  `wiki_context` is ignored by Deep mode itself (it is web-only) and passed through only
  to the Quick fallback, so `app._run_research_stream` can dispatch to either mode with
  one call signature.

- **Trace + metrics in the UI.** `app._render_research_step` is shared between the live
  stream and the replay from `st.session_state["last_research_steps"]`, so the trace
  survives the caller's `st.rerun()` instead of vanishing. Intermediate results
  (thoughts, tool results) render as **collapsed** `st.expander`s; one-line control-flow
  steps stay inline. `_render_research_metrics` shows the run's key figures as
  `st.metric` tiles, dropping **Sources checked** when it would merely repeat **Web
  searches**. Because `st.expander` cannot nest, the trace is a flat sequence of
  expanders under a heading rather than one outer expander.

- **De-duplication is content-based.** `_step_key` keys text-bearing steps on their body
  alone: `supervisor_tools` re-wraps each researcher's `compressed_research` in a
  `ConductResearch` `ToolMessage`, so the identical text would otherwise appear twice —
  once as the labelled thought, once as a tool result.

- **Sync/async bridge.** The graph is natively async; Streamlit reruns are synchronous.
  `_astream_sync` creates a private event loop, pumps `astream(..., stream_mode="updates",
  subgraphs=True)` one event at a time via `run_until_complete(agen.__anext__())`, and
  closes the loop in a `finally`. No background thread, no queue. This is the approved
  async exception (IMPLEMENTATION.md §5).

- **Report persistence.** `_save_report` writes `comparisons/report-<slug>.md` with the
  same frontmatter shape as the Quick path's `tools._submit_final_impl`, stamped through
  `okf.apply_to_page`, so the Research page reads it back unchanged.

  **Frontmatter must be YAML-serialised, never f-string interpolated.** Both writers use
  `frontmatter.Post(...)` + `frontmatter.dumps(...)`. Hand-built `title: "{question}"`
  breaks on any question containing a double quote (`… the thesis "potential 100x
  baggers"`), and the failure is silent in three stages: `okf.apply_to_page` catches the
  parse error and **fails open**, writing the invalid YAML through unchanged; the write
  succeeds so a valid-looking `report_path` comes back; and `wiki_engine.read_page_parsed`
  then raises when the page is read back. The UI used to swallow that and render nothing.
  A missing file is *not* the same case — `read_page_parsed` returns a "Page not found"
  string rather than raising, so it would have been visible.

- **The report text is never lost to a file problem.** The `final_answer` step carries the
  report in `content`; the file is only a nicer-formatted copy. `app._run_research_stream`
  falls back to the in-memory text if read-back fails, and a post-run safety net sets
  `last_research_error` whenever a run finishes with neither an answer nor an error — the
  result and error blocks are the only places the trace is rendered, so without it a
  failed run showed a completely blank page.

- **Language pinning.** `lang.response_directive(question)` is appended to the user turn
  via `prompts.DEEP_RESEARCH_QUESTION`, so it reaches both the research brief and the
  final report. Prompt strings stay in `src/prompts.py`; the vendored node prompts are
  not edited.

## Verification

Covered by `tests/test_deep_research_agent.py` (25 tests). `_astream_sync` is the seam —
tests script `(node, delta)` events, so the graph itself never runs: event mapping, trace
labels, `raw_notes` citation extraction, replay and content de-duplication, the
`ResearchComplete` sentinel, metric counting, report persistence, the fallback contract,
and event-loop cleanup.

End-to-end, confirmed on `gemma4:e4b` with `OPENAI_API_KEY` unset: a current-events
question streams brief → `think_tool` → `ConductResearch` ×2 → `web_search` results →
report, yielding 15 unique web citations and a saved `comparisons/` report, served by
local Ollama throughout (`ollama_client.loaded_model()`).

## Known limits

- **Concurrency is not speedup.** Ollama serialises requests on a single model; raising
  `DEEP_RESEARCH_CONCURRENCY` costs VRAM without buying wall-clock.
- **The supervisor sometimes skips research entirely** on a small model, writing the
  report from model knowledge with no web sources (observed on `gemma4:e4b`). The run
  still succeeds, so the fallback does not trigger — an all-zero metrics row
  (0 sub-tasks, 0 searches, 0 sources cited) is the tell. A stronger tool-calling tag is
  the mitigation.
- **The vendored tree emits deprecation warnings** under LangChain/LangGraph 1.x
  (`config_schema`, `input`/`output`, pydantic `Field(metadata=…)`). Functional today;
  it will break at LangGraph 2.0 and need a re-vendor.

## Non-goals

- No wiki/raw grounding, no hybrid, no `CHAT_TOOLS` changes — Deep mode is web-only.
- No replacement of the Quick researcher (`src/agent.py`).
