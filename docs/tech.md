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
| Webpage fetch (research) | `httpx` | 0.27 |
| HTML→Markdown (research) | `markdownify` | 0.13 |
| PDF extraction | `pypdf` | 4.0 |
| DOCX extraction | `python-docx` | 1.1 |
| YAML frontmatter | `python-frontmatter` | 1.1 |
| Env variables | `python-dotenv` | 1.0 |
| Web UI | `streamlit` | 1.35 |
| Optional graph view | `pyvis` | 0.3 |
| Standard library | `hashlib`, `pathlib`, `json`, `re`, `shutil` | — |

Dev: `pytest ≥ 8.0`.

## Forbidden

- **No LangChain** outside the deep-research agent layer (`src/agent.py`, `src/tools.py`). LangGraph + `langchain-ollama` are scoped to that layer only — see [`architecture.md`](architecture.md) §Deep researcher.
- **No vector database. No embeddings.**
- **No cloud LLM APIs** (OpenAI, Anthropic, Bedrock, …).
- **No asyncio.** Parallelism in the research layer uses `concurrent.futures.ThreadPoolExecutor` (I/O only); LLM calls stay sequential.
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

`pyproject.toml` and `uv.lock` are checked in.

## Streamlit notes

Streamlit is the chosen UI framework. Port is fixed at **8520** (8511 is reserved on this host). The app includes a safe-exit button using `lsof -ti:8520 | xargs -r kill -9`.

## Licensing

All implementation must be under Apache 2.0 or a more permissive licence (MIT) — CLAUDE.md §5.4.
