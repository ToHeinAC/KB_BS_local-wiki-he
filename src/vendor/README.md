# Vendored third-party source

Not domain code. Nothing here is edited by hand except the one mechanical rewrite recorded below.

## `open_deep_research/`

- **Upstream:** <https://github.com/langchain-ai/open_deep_research>
- **Licence:** MIT (Copyright (c) 2025 LangChain) — see `open_deep_research/LICENSE`.
  Compatible with this project's Apache-2.0 (`AGENTS.md` §5.4).
- **Pinned commit:** `d337ae32ed4ff8f4c6fbe192ba3bf1b2d6610799` (2026-07-25), version `0.0.16`
- **Files taken:** `src/open_deep_research/{deep_researcher,configuration,state,prompts,utils}.py`
  plus `LICENSE`. The `legacy/` and `security/` trees are *not* vendored.

### Why vendored instead of `uv add`

Upstream's `pyproject.toml` declares ~40 runtime dependencies — `azure-identity`,
`azure-search-documents`, `supabase`, `langchain-aws`, `langchain-google-vertexai`,
`openai`, `pandas`, `pymupdf`, `ipykernel`, `langgraph-cli[inmem]` — for a graph that
this project drives entirely through Ollama + Tavily. Two problems:

1. §5.3 forbids cloud LLM APIs; pulling those SDKs in as hard requirements contradicts that.
2. Upstream pins the LangChain 0.3 line (`langgraph>=0.5.4`, `langchain-community>=0.3.9`).
   This project runs `langchain-core` 1.x / `langgraph` 1.x, so resolving the package would
   likely downgrade both and break `src/agent.py` and `src/chat_agent.py`.

The five vendored modules' actual import surface is small: `langchain` (`init_chat_model`),
`aiohttp`, `langchain-mcp-adapters`, `mcp`, plus `langgraph` / `langchain-core` / `tavily-python`
which the project already had. Those four are the only additions in `pyproject.toml`.

### The one modification

Internal absolute imports were rewritten so the package resolves under `src/vendor/`:

```bash
sed -i 's/^from open_deep_research\./from vendor.open_deep_research./' *.py
```

Nothing else is patched. Behaviour is changed only through `Configuration` fields, from
`src/deep_research_agent.py`.

### Re-vendoring

```bash
git clone --depth 1 https://github.com/langchain-ai/open_deep_research /tmp/odr
cp /tmp/odr/src/open_deep_research/{deep_researcher,configuration,state,prompts,utils}.py \
   /tmp/odr/LICENSE src/vendor/open_deep_research/
sed -i 's/^from open_deep_research\./from vendor.open_deep_research./' \
   src/vendor/open_deep_research/*.py
```

Then re-confirm the licence is still MIT and update the pinned commit above.
