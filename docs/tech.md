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
| PDF extraction | `pypdf` | 4.0 |
| DOCX extraction | `python-docx` | 1.1 |
| YAML frontmatter | `python-frontmatter` | 1.1 |
| Env variables | `python-dotenv` | 1.0 |
| Optional graph view | `pyvis` | 0.3 |
| Standard library | `hashlib`, `pathlib`, `json`, `re`, `shutil` | — |

Dev: `pytest ≥ 8.0`. UI dependencies are added per the implementer's framework choice (PRD §3.9).

## Forbidden

- **No LangChain.**
- **No vector database. No embeddings.**
- **No cloud LLM APIs** (OpenAI, Anthropic, Bedrock, …).
- **No async** (unless the chosen UI stack strictly requires it at boundaries).
- **No database** of any kind — files + JSON only.
- **No Docker** in the primary workflow.
- **No configuration UI** — `.env` is the only config surface.
- **No sub-packages** — every module is one Python file at project root.

## Environment commands (target)

```bash
uv sync           # create .venv, install locked deps
uv run pytest     # run tests
uv run python app.py   # run app (or framework-specific launcher, see ui.md)
```

`pyproject.toml` and `uv.lock` are checked in. A representative dependency block is in PRD §5.2.

## Streamlit notes (if chosen)

If Streamlit is the UI choice, follow the user's global rule: **always use ports > 8510**, and include a safe-exit button that uses `lsof -ti:<port> | xargs -r kill -9` (without killing SSH).

## Licensing

All implementation must be under Apache 2.0 or a more permissive licence (MIT) — CLAUDE.md §5.4.
