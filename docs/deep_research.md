---
name: deep_research.md
description: Implementation plan for a second Research mode — a web-only Open Deep Research supervisor pipeline (vendored, Ollama + Tavily)
version: 1.0.0
author: Tobias Hein
status: Planned — design only, not yet built
---

# Deep Research (web mode)

> **Status: PLAN, not implemented.** This document is a forward-looking design for a *new* Research mode.
> No code described here exists yet (`src/deep_research_agent.py` is unbuilt).
> Authoritative spec for the existing researcher: [`PRD.md`](../PRD.md) §3.7–3.8; current implementation
> map: [`IMPLEMENTATION.md`](../IMPLEMENTATION.md) §3. The current single-loop researcher is documented in
> [architecture.md](architecture.md) §Deep researcher.

## Intent

The Research page today runs **one** agent: `src/agent.py`, a LangGraph `StateGraph(MessagesState)`
ReAct loop (`agent → tools → agent`) that is **local-first** — it consults the wiki/raw KB first and
uses Tavily only for gaps. That becomes the **"Quick"** mode.

This plan adds a second, **"Deep Research"** mode: a **web-only, Perplexity-style** multi-agent pipeline
that decomposes a question, researches sub-topics in parallel, and synthesises a cited report — by
**vendoring [`open_deep_research`](https://github.com/langchain-ai/open_deep_research)** (langchain-ai)
and pointing it at local Ollama + Tavily. Deep mode does **not** touch the wiki/raw KB; its citations are
web URLs only.

Guard rails this plan stays inside:
- **Licence.** `open_deep_research` is **MIT** — a strict subset of "Apache-2.0 or more permissive"; OK. *(Re-confirm at pin time.)*
- **Agent-layer only.** All LangGraph/LangChain lives in the new agent-layer module `src/deep_research_agent.py`, consistent with the §5.3 scope rule.
- **Async is permitted for this feature.** The project's general "no async" rule (`AGENTS.md`/`IMPLEMENTATION.md` §5) is **waived here** by explicit decision — the vendored graph is natively async and is adopted as-is.
- **No new network dependency.** Tavily is already used and gated on `TAVILY_API_KEY`; Deep mode reuses it.

## Architecture — the vendored graph

Upstream topology (adopt as-is, override only config):

```
deep_researcher            state: AgentState / AgentInputState        exported graph var: deep_researcher
  START
   → clarify_with_user        (disabled here — Research is one-shot)
   → write_research_brief      (ResearchQuestion schema)
   → research_supervisor       ── supervisor_subgraph ──────────────────────────────┐
   → final_report_generation                                                        │
   → END                                                                            │
                                                                                    │
  supervisor_subgraph:                                                              │
     supervisor        (tools: ConductResearch, ResearchComplete, think_tool)       │
     supervisor_tools  → asyncio.gather → N × researcher_subgraph  ◄────────────────┘
                                            (researcher → researcher_tools → compress_research)
```

- **Supervisor** plans and delegates via the `ConductResearch` tool; `supervisor_tools` fans out up to
  `max_concurrent_research_units` researcher subgraphs concurrently and gathers their compressed findings.
- **Each researcher** is its own small ReAct loop over the search tools, then `compress_research`
  summarises its findings.
- **`final_report_generation`** synthesises all compressed findings into the cited markdown report
  (with token-limit retry).

### Configuration surface (upstream field → our setting)

`open_deep_research`'s `Configuration` exposes model choices as `"provider:model"` strings plus per-role
max-token caps, built through `init_chat_model(configurable_fields=("model", "max_tokens", "api_key"))`.

| Upstream field | Upstream default | Our setting | Why |
|---|---|---|---|
| `research_model` / `final_report_model` / `compression_model` | `openai:gpt-4.1` | `ollama:<_QUERY_MODEL>` | local only |
| `summarization_model` | `openai:gpt-4.1-mini` | `ollama:<_QUERY_MODEL>` (or `_FAST_MODEL`) | local only |
| `research_model_max_tokens` etc. | 8192–10000 | cap to fit `num_ctx` / VRAM | small-model safety |
| `search_api` | `SearchAPI.TAVILY` | keep `TAVILY` | reuse `TAVILY_API_KEY` |
| `allow_clarification` | `True` | **`False`** | Research page is one-shot; no interactive turn |
| `max_concurrent_research_units` | 5 | **1–2** | Ollama serialises; VRAM |
| `max_researcher_iterations` | 6 | env-tunable | budget |
| `max_react_tool_calls` | 10 | env-tunable | budget |

**Model base_url note.** `Configuration` makes only `model` / `max_tokens` / `api_key` configurable — Ollama's
`base_url` is *not* a config field. Wire it by setting the model strings to `ollama:<_QUERY_MODEL>` and
ensuring `langchain_ollama` targets `ollama_client._HOST` (set `OLLAMA_HOST` before graph build, or pass
`base_url` as a default kwarg). The chosen mechanism is verified end-to-end via `ollama_client.loaded_model()`.

## Integration seams (what the build will add)

- **New module `src/deep_research_agent.py`** (agent layer). Public entry:
  `run_deep_research(question: str) -> Generator[dict, None, None]`, emitting the **same step-dict shape**
  the Research page already renders (`thought`, `tool_call`, `tool_result`, `final_answer` + `report_path`,
  `error` — the contract at `src/agent.py:3-9`). It builds the vendored `deep_researcher` graph with our
  `Configuration` (Ollama models, Tavily, clarification off, concurrency/iteration budgets from env).

- **Sync/async bridge (lightweight — async is allowed).** The vendored graph is async (`asyncio.gather`);
  Streamlit reruns are synchronous, so `run_deep_research` stays a plain **sync generator** that pumps
  `deep_researcher.astream(...)` on a dedicated event loop (`run_until_complete(anext(...))` per event,
  mapping each to a step-dict). No background thread, no queue — the event loop is created and closed
  within the generator's lifetime.

- **Streaming / citation adapter.** Map LangGraph node events → step-dicts, and extract web URLs + titles
  from researcher tool results so the Research page can render **per-URL Perplexity-style citation cards**.
  Today `_render_research_sources_panel` (`src/app.py:487-497`) records only `{tool, query}`; this is where
  URL/title enrichment lands. The `final_report_generation` markdown is saved to `comparisons/` and read
  back exactly like the Quick path (`src/app.py:528-532`).

- **UI: a Quick / Deep toggle on the Research page**, mirroring the Chat Fast/Deep pattern
  (`src/app.py:1099-1102`). Page dispatch stays at `elif page == "Research":` (`src/app.py:1266`); the nav
  string (`src/app.py:783`) is unchanged. Quick → `research_agent.run_research_agent(...)`; Deep →
  `deep_research_agent.run_deep_research(...)`, both through the existing `_run_research_stream`
  (`src/app.py:499-552`). Add a per-mode session-state key alongside the reset lists
  (`src/app.py:721-724, 767-771, 1287-1290`).

### Reuse map (don't reinvent)

| Need | Reuse |
|---|---|
| Local model + host | `ollama_client._QUERY_MODEL` / `_HOST` / `_FAST_MODEL` (`src/ollama_client.py:9-17`) |
| Web search | Tavily gate on `TAVILY_API_KEY`; upstream `SearchAPI.TAVILY` |
| Streaming render | step-dict contract + `_run_research_stream` / `_render_research_sources_panel` (`src/app.py`) |
| Report persistence | `comparisons/` save + readback (`src/app.py:528-532`) |
| Language pinning | `lang.response_directive()` to pin the final report to the query language (DE/EN) |
| Prompts | any node system-prompt overrides go in `src/prompts.py` (the "no inline prompts" rule holds) |

## Configuration & env

New `DEEP_RESEARCH_*` keys, added next to the existing `RESEARCH_*` block in `.env.example` (~L71-78) and
registered in `IMPLEMENTATION.md` §6:

| Var | Default | Purpose |
|---|---|---|
| `DEEP_RESEARCH_MODEL` | `<QUERY_MODEL>` | Override the Ollama tag for all four roles |
| `DEEP_RESEARCH_CONCURRENCY` | `1` | `max_concurrent_research_units` (Ollama serialises; keep low) |
| `DEEP_RESEARCH_MAX_ITERATIONS` | `4` | `max_researcher_iterations` budget |
| `DEEP_RESEARCH_MAX_TOOL_CALLS` | `6` | `max_react_tool_calls` per researcher |
| `DEEP_RESEARCH_MAX_TOKENS` | `8192` | per-role `*_model_max_tokens` cap |
| `DEEP_RESEARCH_CLARIFICATION` | `false` | `allow_clarification` (keep off for one-shot) |

## Risks & mitigations

1. **Small local models (gemma3:4b / e4b) are weak at structured output + tool calling**, which this graph
   leans on heavily (`ResearchQuestion` schema, `ConductResearch` tool, `max_structured_output_retries`).
   Mitigate: prefer a tool-calling-capable tag; `allow_clarification=False`; low concurrency; **fall back to
   Quick mode** on repeated structured-output failure rather than erroring.
2. **"Parallel" sub-researchers serialise on one Ollama instance** (single model, VRAM, request
   serialisation) — set `max_concurrent_research_units` to 1–2 and document that concurrency ≠ speedup here.
3. **Dependency surface.** Vendoring pulls extra LangChain packages (e.g. `langchain-openai`, upstream pins)
   into a project whose §5 rules forbid cloud LLM APIs. Cloud deps stay **optional/unused** (all models
   overridden to Ollama). Record this in `IMPLEMENTATION.md` §4 (deviations) / §5 (scoped exception),
   as the current LangGraph researcher already is. *(Async is not a deviation — it is approved for this
   feature.)*
4. **Package identity / licence to verify at build time.** The repo installs via `uv sync`; confirm the
   exact spec — likely `uv add "open-deep-research @ git+https://github.com/langchain-ai/open_deep_research"`
   — and re-confirm MIT before pinning.

## Verification (for the future build)

- `uv sync` resolves the dep; `uv run python -c "from open_deep_research.deep_researcher import deep_researcher"` imports.
- Unit: `run_deep_research("<current-events question>")` yields step-dicts ending in `final_answer` with a
  non-empty report and ≥1 web URL; the event loop closes cleanly after the generator is exhausted. Mock
  Tavily as in `tests/test_tools.py:12-49`.
- End-to-end: `uv run streamlit run src/app.py --server.port 8520` → Research page → **Deep** toggle → ask a
  current-events question → confirm streamed steps, per-URL citation cards, and a saved `comparisons/` report.
  Confirm **Quick** mode still behaves unchanged.
- Confirm the run was served locally via `ollama_client.loaded_model()` and that **no OpenAI key** was required.

## Non-goals

- No wiki/raw grounding, no hybrid, no `CHAT_TOOLS` changes — Deep mode is web-only.
- No replacement of the Quick researcher (`src/agent.py`).
- This document is design only; it does not build `src/deep_research_agent.py` or add the dependency.
