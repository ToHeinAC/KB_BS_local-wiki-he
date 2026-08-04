---
name: tech.md
description: Technology stack, dependency management, and simplicity rules
version: 1.0.0
author: Tobias Hein
---

# Tech Stack

> Authoritative spec: [`PRD.md`](../PRD.md) §2.3 (Tech Stack), §4.4 (Simplicity Rules), §5 (Configuration & Environment).

## Runtime

- **Python ≥ 3.11**
- **`uv`** — mandatory for environment + dependency management. No `pip install -r requirements.txt` in the primary workflow (PRD §5.3).
- **Ollama** — local LLM server, default model `gemma4:e4b`.

## Libraries

| Component | Library | Min version |
|---|---|---|
| Local LLM SDK | `ollama` | 0.3 |
| Web search | `tavily-python` | 0.3 |
| Deep researcher graph | `langgraph` | 0.2 |
| Deep researcher LLM adapter | `langchain-ollama` | 0.2 |
| Deep researcher core | `langchain-core` | 0.3 |
| Deep Research (web) — `init_chat_model` | `langchain` | 0.3 |
| Deep Research (web) — vendored graph I/O | `aiohttp` | 3.9 |
| Deep Research (web) — vendored MCP import | `langchain-mcp-adapters` / `mcp` | 0.1.6 / ≥1.9.4,**<2** |
| Webpage fetch (research) | `httpx` | 0.27 |
| HTML→Markdown (research) | `markdownify` | 0.13 |
| PDF extraction (text path) | `pypdf` | 4.0 |
| PDF rasterization (OCR path) | `pypdfium2` | 4.0 |
| Image handling (OCR path) | `pillow` | 10.0 |
| DOCX extraction | `python-docx` | 1.1 |
| YAML frontmatter | `python-frontmatter` | 1.1 |
| Env variables | `python-dotenv` | 1.0 |
| Web UI | `streamlit` | 1.35 |
| Optional graph view | `pyvis` | 0.3 |
| Standard library | `hashlib`, `pathlib`, `json`, `re`, `shutil` | — |

Dev: `pytest ≥ 8.0`.

## Forbidden

- **No LangChain** outside the agent layer (`src/agent.py`, `src/chat_agent.py`, `src/tools.py`, `src/deep_research_agent.py`) and the vendored tree `src/vendor/`. See [`architecture.md`](architecture.md) §Deep researcher.
- **No vector database. No embeddings.** *(Superseded by Stage C: local file-backed embeddings are permitted — see [`retrieval.md`](retrieval.md).)*
- **No cloud LLM APIs** (OpenAI, Anthropic, Bedrock, …). Holds for Deep Research too: the vendored graph runs every model role on Ollama and reads no cloud key — see [`deep_research.md`](deep_research.md).
- **No asyncio.** Parallelism in the research layer uses `concurrent.futures.ThreadPoolExecutor` (I/O only); LLM calls stay sequential. **Scoped exception:** the vendored Deep-Research graph is natively async; `deep_research_agent.run_deep_research` keeps that behind a plain sync generator.
- **No hand-editing `src/vendor/`.** It is vendored third-party source, changed only by re-vendoring — see [`../src/vendor/README.md`](../src/vendor/README.md).
- **No database** of any kind — files + JSON only.
- **No Docker** in the primary workflow.
- **No configuration UI** — `.env` is the only config surface.
- **No sub-packages** — every module is one Python file at project root.

## Environment commands

```bash
uv sync                                             # create .venv, install locked deps
uv run pytest                                       # run tests
uv run streamlit run app.py --server.port 8520      # run app
```

`pyproject.toml` is checked in; `uv.lock` is gitignored (`.gitignore:16`), so `uv sync` resolves against the declared ranges.

## Streamlit notes

Streamlit is the chosen UI framework. Port is fixed at **8520** (8511 is reserved on this host). The app includes a safe-exit button using `lsof -ti:8520 | xargs -r kill -9`.

The app is served under the base path **`/wiwi/`** (`baseUrlPath` in `.streamlit/config.toml`), matching the nginx reverse proxy that publishes it at `https://ai.brenk.com/wiwi/`. The two must agree or the app renders blank. The port root 404s. `src/gpu_widget.py` reads the same option to place its injected `_api/gpu` route under the prefix — Streamlit only prefixes its *own* routes. Keep `--server.port 8520` on the command line: `tunnel.sh` and the `restart-app` skill match the process by that flag.

## Licensing

All implementation must be under Apache 2.0 or a more permissive licence (MIT) — CLAUDE.md §5.4.
