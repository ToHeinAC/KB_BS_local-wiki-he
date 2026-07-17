# LocalWiki

A fully local, Karpathy-style self-compiling knowledge wiki. Drop documents in — Markdown, or PDF / DOCX / images that are auto-converted to Markdown (local OCR + rewrite, vendored from [MD-maker](https://github.com/ToHeinAC/MD-maker)) — and a local LLM (Ollama, default `gemma4:e4b`) compiles them into an interlinked Markdown wiki you can navigate, chat with, and challenge with web research.

> **Status:** All pages implemented — three-stage ingest (`ingest_begin` / `ingest_piece` / `ingest_end`) drives a structural chunk store + BM25 lexical index + 1–5 hypothetical questions per source (folded into BM25 TF) under `data/chunks/` and `data/index/` → wiki (tree-by-type + BM25 full-text search over page bodies + typed-graph viz with `derived-from` source edges) → chat (Fast: one-shot RAG over wiki pages with hybrid BM25→LLM page selection + section-level chunk synthesis; **Deep**: LangGraph agent loop over `data/raw/` originals via BM25; live trace + download) → research (LangGraph deep researcher: plan → wiki-first → triage → web search → quality-gated report; inline report + download). Both agent modes include an `evaluate_condition` tool that deterministically evaluates logical / regulatory conditions (thresholds, membership, ranges, AND/OR/NOT trees) over LLM-extracted facts — Python does the comparison, not the model. Affected-page selection during ingest is BM25-driven (no extra LLM call) and merges into existing pages with a rank-weighted budget. Long-source ingest (e.g. 488 KB legal docs): ~7 min. ≈258-test suite.

The generated `wiki/` folder is a conformant **[Open Knowledge Format (OKF v0.1)](docs/okf.md)** bundle — typed markdown pages, `okf_version`-declaring `index.md`, date-grouped `log.md`, and `## Citations`. Conformance is stamped deterministically in code (`src/okf.py`), never by the LLM, so it holds even on `gemma4:e4b`.

Language is preserved deterministically too: `src/lang.py` detects the source language at ingest and the query language at chat/research time, then pins the wiki page or answer to that language (German ↔ English) — citations and numbers stay verbatim. Detection is code-side, never left to the model, so it holds on `gemma4:e4b`.

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

Open [http://localhost:8520/wiwi/](http://localhost:8520/wiwi/) — not the port
root, which returns 404. `.streamlit/config.toml` sets `baseUrlPath = "wiwi"` so
the app can be served under a path; see [Remote access](#remote-access).

Keep `--server.port 8520` on the command line: `tunnel.sh` and the `restart-app`
skill find the process by matching that flag.

## Configuration

Edit `.env` (copied from `.env.example`). The essentials to get started:

| Variable | Default | Purpose |
|---|---|---|
| `OLLAMA_MODEL` | `gemma4:e4b` | Ollama model to use |
| `OLLAMA_HOST` | `http://localhost:11434` | Ollama server URL |
| `TAVILY_API_KEY` | — | Required only for the Research page (web search) |

**Full configuration reference** (per-role model overrides, ingest/QA tuning, research + chat gates, all timeouts) lives in one place: [IMPLEMENTATION.md §6 Configuration](IMPLEMENTATION.md#6-configuration). `.env.example` is the machine-readable template.

## Remote access

The wiki is served publicly at **<https://ai.brenk.com/wiwi/>** by an nginx reverse proxy, which terminates TLS and maps that path onto port 8520. The URL is permanent. Two settings must agree, or the app renders blank — Streamlit's asset links are relative, and without the base path they resolve at the site root:

| Side | Setting |
|---|---|
| nginx | `location /wiwi/` → `proxy_pass http://172.16.4.112:8520;` |
| this app | `.streamlit/config.toml` → `[server] baseUrlPath = "wiwi"` |

`src/gpu_widget.py` reads the same value to register its `_api/gpu` route under the prefix, so changing `baseUrlPath` carries the widget along. The proxy config and the full reasoning live in the orchestrator repo: `local_app-orchestrator/deploy/ai.brenk.com.conf` and `docs/reverse-proxy.md`. The app directory at <https://ai.brenk.com/> links here.

### Cloudflare quick tunnel (retired)

```bash
./tunnel.sh
```

Superseded by the reverse proxy and **kept only as a fallback**. It still opens a temporary `*.trycloudflare.com` URL for port 8520 — no Cloudflare account required — and stays up until port 8520 stops listening (or Ctrl-C). Since `baseUrlPath` was introduced, the URL it prints points at the port root and 404s: append `/wiwi/`. `tunnel.sh` does not do that for you, and nothing reads `/tmp/wiki-app-url.txt` any more — the app directory uses the permanent URL above. Requires [`cloudflared`](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/).

## License

Apache License 2.0.
