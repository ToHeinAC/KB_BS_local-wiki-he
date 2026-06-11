# LocalWiki

A fully local, Karpathy-style self-compiling knowledge wiki. Drop documents in — Markdown, or PDF / DOCX / images that are auto-converted to Markdown (local OCR + rewrite, vendored from [MD-maker](https://github.com/ToHeinAC/MD-maker)) — and a local LLM (Ollama, default `gemma4:e4b`) compiles them into an interlinked Markdown wiki you can navigate, chat with, and challenge with web research.

> **Status:** All pages implemented — three-stage ingest (`ingest_begin` / `ingest_piece` / `ingest_end`) drives a structural chunk store + BM25 lexical index + 1–5 hypothetical questions per source (folded into BM25 TF) under `data/chunks/` and `data/index/` → wiki (tree-by-type + BM25 full-text search over page bodies + typed-graph viz with `derived-from` source edges) → chat (Fast: one-shot RAG over wiki pages with hybrid BM25→LLM page selection + section-level chunk synthesis; **Deep**: LangGraph agent loop over `data/raw/` originals via BM25; live trace + download) → research (LangGraph deep researcher: plan → wiki-first → triage → web search → quality-gated report; inline report + download). Both agent modes include an `evaluate_condition` tool that deterministically evaluates logical / regulatory conditions (thresholds, membership, ranges, AND/OR/NOT trees) over LLM-extracted facts — Python does the comparison, not the model. Affected-page selection during ingest is BM25-driven (no extra LLM call) and merges into existing pages with a rank-weighted budget. Long-source ingest (e.g. 488 KB legal docs): ~7 min. 180+ test suite.

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
ollama pull deepseek-ocr:3b     # only needed to upload non-Markdown files (PDF/DOCX/images)
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
| `QUERY_MODEL` / `INGEST_MODEL` / `FAST_MODEL` | `OLLAMA_MODEL` | Optional per-role model overrides (page/source selection + agents / ingest synthesis / lint); each falls back to `OLLAMA_MODEL` |
| `MAX_INGEST_CHARS` | `40000` | Chunk size for ingest; large documents are split into sequential chunks |
| `OCR_MODEL` | `deepseek-ocr:3b` | Vision model for OCR of scanned PDF pages / images (Upload conversion) |
| `REWRITE_MODEL` | `OLLAMA_MODEL` | Model that reformats extracted PDF text into Markdown |
| `PDF_DPI` | `150` | Rasterization DPI for scanned PDF pages sent to OCR |
| `DATA_ROOT` | `data` | Root for all databases; each DB is an isolated subtree `$DATA_ROOT/<db>/{raw,chunks,index,wiki}`; `users.json` lives at `$DATA_ROOT/users.json` |
| `INGEST_QA` | `1` | Run hypothetical-question generator during ingest (`0` to disable) |
| `QA_BATCH_SIZE` | `12` | Chunks per QA-generator LLM batch |
| `QA_MAX_PAIRS_PER_SOURCE` | `5` | Max hypothetical-question pairs persisted per source (caps `qa_gen` cost) |
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

## Remote access (Cloudflare quick tunnel)

```bash
./tunnel.sh
```

Starts a temporary `*.trycloudflare.com` public URL for port 8520 — no Cloudflare account required. The tunnel stays up until port 8520 stops listening (or Ctrl-C). Requires [`cloudflared`](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/).

## License

Apache License 2.0.
