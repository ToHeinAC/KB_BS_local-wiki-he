# LocalWiki

A fully local, Karpathy-style self-compiling knowledge wiki. Drop documents in; a local LLM (Ollama, default `gemma4:e4b`) compiles them into an interlinked Markdown wiki you can navigate, chat with, and challenge with web research.

> **Status:** All pages implemented — ingest with chunked large-document support (progress bar, paragraph-boundary splits) plus a structural chunk store + BM25 lexical index + ingest-time entity/acronym/fact extraction + hypothetical-question chunks under `data/chunks/` and `data/index/` → wiki (tree-by-type + full-text search + interactive graph) → chat (Fast: one-shot RAG over wiki pages; **Deep**: LangGraph agent loop over `data/raw/` originals via BM25 + direct-fact lookup) → research (LangGraph deep researcher: plan → wiki-first → triage → web search → quality-gated report). 135-test suite.

## Documentation

- [`PRD.md`](PRD.md) — product requirements (authoritative spec)
- [`IMPLEMENTATION.md`](IMPLEMENTATION.md) — current state, module map, deviations from PRD
- [`CLAUDE.md`](CLAUDE.md) — collaboration rules for AI coding tools
- [`docs/`](docs/) — deep per-area reference (architecture, domain, tech, ui, wiki, tests)

## Prerequisites

- Python ≥ 3.11
- [`uv`](https://docs.astral.sh/uv/)
- [Ollama](https://ollama.ai), running locally with at least one model pulled
- *(Optional)* Tavily API key for the Research feature

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
| `MAX_INGEST_CHARS` | `40000` | Chunk size for ingest; large documents are split into sequential chunks |
| `WIKI_DIR` | `data/wiki` | Wiki page storage |
| `RAW_DIR` | `data/raw` | Uploaded source storage |
| `CHUNKS_DIR` | `data/chunks` | Chunk store (one JSONL per source) |
| `INDEX_DIR` | `data/index` | BM25 lexical index + extractor/QA sidecars |
| `INGEST_EXTRACT` | `1` | Run alias/acronym/fact extractor during ingest (`0` to disable) |
| `INGEST_QA` | `1` | Run hypothetical-question generator during ingest (`0` to disable) |
| `QA_BATCH_SIZE` | `12` | Chunks per QA-generator LLM batch |
| `TAVILY_API_KEY` | — | Required for the Research page (web search) |
| `RESEARCH_MIN_SEARCHES` | `6` | Min web searches before a report can be submitted |
| `RESEARCH_MIN_WORDS` | `600` | Min final-report word count |
| `RESEARCH_MIN_URLS` | `4` | Min unique sources cited (URLs + `[Wiki: ...]` citations) |
| `RESEARCH_PARALLELISM` | `4` | Thread-pool size for parallel Tavily / page fetches |
| `RESEARCH_MAX_ITERATIONS` | `40` | LangGraph recursion cap for the research agent |
| `RESEARCH_LLM_TIMEOUT` | `300` | Per-LLM-call timeout (seconds) |
| `CHAT_MIN_SEARCHES` | `3` | Deep chat: min tool calls before submission |
| `CHAT_MIN_WORDS` | `300` | Deep chat: min answer word count |
| `CHAT_MIN_SOURCES` | `2` | Deep chat: min unique `[Source: ...]` citations (section-suffixed forms count distinctly) |
| `CHAT_MAX_ITERATIONS` | `25` | Deep chat: LangGraph recursion cap |
| `CHAT_LLM_TIMEOUT` | `180` | Deep chat: per-LLM-call timeout (seconds) |

## License

Apache License 2.0.
