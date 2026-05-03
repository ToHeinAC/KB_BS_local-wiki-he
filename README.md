# LocalWiki

A fully local, Karpathy-style self-compiling knowledge wiki. Drop documents in; a local LLM (Ollama, default `gemma4:e4b`) compiles them into an interlinked Markdown wiki you can navigate, chat with, and challenge with web research.

> **Status:** All pages implemented — ingest (with optional metadata form) → wiki → chat → research (ReAct agent). 86-test suite.

## Documentation

- [`PRD.md`](PRD.md) — product requirements (authoritative spec)
- [`IMPLEMENTATION.md`](IMPLEMENTATION.md) — current state, module map, deviations from PRD
- [`CLAUDE.md`](CLAUDE.md) — collaboration rules for AI coding tools
- [`docs/`](docs/) — deep per-area reference (architecture, domain, tech, ui, wiki, tests)

## Prerequisites

- Python ≥ 3.11
- [`uv`](https://docs.astral.sh/uv/)
- [Ollama](https://ollama.ai), running locally with at least one model pulled
- *(Optional)* Tavily API key for the Research feature (not yet implemented)

## Setup

```bash
git clone https://github.com/ToHeinAC/KB_BS_local-wiki-he
cd KB_BS_local-wiki-he
uv sync
ollama pull gemma4:e4b          # or any model — set OLLAMA_MODEL in .env
cp .env.example .env
```

## Run

```bash
uv run streamlit run src/app.py --server.port 8520
```

Open [http://localhost:8520](http://localhost:8520).

## Configuration

Edit `.env` (copied from `.env.example`):

| Variable | Default | Purpose |
|---|---|---|
| `OLLAMA_MODEL` | `gemma4:e4b` | Ollama model to use |
| `OLLAMA_HOST` | `http://localhost:11434` | Ollama server URL |
| `MAX_INGEST_CHARS` | `40000` | Max characters extracted per document |
| `WIKI_DIR` | `data/wiki` | Wiki page storage |
| `RAW_DIR` | `data/raw` | Uploaded source storage |
| `TAVILY_API_KEY` | — | Required for Research (future) |

## License

Apache License 2.0.
