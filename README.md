# LocalWiki

A fully local, Karpathy-style self-compiling knowledge wiki. Drop documents in; a local LLM (Ollama, default `gemma4:e4b`) compiles them into an interlinked Markdown wiki you can navigate, chat with, and challenge with web research.

> Status: documentation skeleton only — implementation has not started yet. See [`IMPLEMENTATION.md`](IMPLEMENTATION.md).

## Documentation

- [`PRD.md`](PRD.md) — product requirements (authoritative spec)
- [`IMPLEMENTATION.md`](IMPLEMENTATION.md) — current implementation state and module map
- [`CLAUDE.md`](CLAUDE.md) — collaboration rules for AI coding tools
- [`docs/`](docs/) — deep per-area reference (architecture, domain, tech, ui, wiki, tests)

## Prerequisites

- Python ≥ 3.11
- [`uv`](https://docs.astral.sh/uv/)
- [Ollama](https://ollama.ai), running locally
- *(Optional)* Tavily API key for the Research feature

## Setup (planned)

```bash
git clone https://github.com/ToHeinAC/KB_BS_local-wiki-he
cd KB_BS_local-wiki-he
uv sync
ollama pull gemma4:e4b
cp .env.example .env   # add TAVILY_API_KEY if you want web research
```

## Run (planned)

```bash
uv run python app.py
```

If the chosen UI framework needs its own launcher, document the equivalent `uv run …` command (e.g. `uv run streamlit run app.py`).

## License

Apache License 2.0 (or compatible permissive license, e.g. MIT).
