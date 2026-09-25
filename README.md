# LocalWiki

A fully local, Karpathy-style self-compiling knowledge wiki. Drop documents in — Markdown, or PDF / DOCX / images that are auto-converted to Markdown (local OCR + rewrite, vendored from [MD-maker](https://github.com/ToHeinAC/MD-maker)) — and a local LLM (Ollama, default `gemma4:e4b`) compiles them into an interlinked Markdown wiki you can navigate, chat with, and challenge with web research.

> **Status:** All pages implemented — three-stage ingest (`ingest_begin` / `ingest_piece` / `ingest_end`) drives a structural chunk store + a lexical FTS5/BM25 index + an optional local-embedding semantic arm fused with it via RRF (hybrid retrieval, degrades gracefully to lexical-only) + 1–5 hypothetical questions per source (folded into BM25 TF) under `data/chunks/` and `data/index/` → wiki (tree-by-type + BM25 full-text search over page bodies + typed-graph viz with `derived-from` source edges) → chat (Fast: one-shot RAG over wiki pages with hybrid BM25→LLM page selection + section-level chunk synthesis; **Deep**: LangGraph agent loop over `data/raw/` originals via BM25; live trace + download) → research (**Quick**: LangGraph deep researcher — plan → wiki-first → triage → web search → quality-gated report; **Deep**: a web-only supervisor pipeline that splits the question into sub-topics, researches each over Tavily and synthesises a URL-cited report, via the vendored [open_deep_research](https://github.com/langchain-ai/open_deep_research) graph run entirely on local Ollama — see [docs/deep_research.md](docs/deep_research.md); inline report + download). Both agent modes include an `evaluate_condition` tool that deterministically evaluates logical / regulatory conditions (thresholds, membership, ranges, AND/OR/NOT trees) over LLM-extracted facts — Python does the comparison, not the model. Affected-page selection during ingest is BM25-driven (no extra LLM call) and merges into existing pages with a rank-weighted budget. Long-source ingest (e.g. 488 KB legal docs): ~7 min; both local runtimes (Ollama and the in-process reranker) are pinned to a single GPU each — see [docs/gpu.md](docs/gpu.md).

The generated `wiki/` folder is a conformant **[Open Knowledge Format (OKF v0.1)](docs/okf.md)** bundle — typed markdown pages, `okf_version`-declaring `index.md`, date-grouped `log.md`, and `## Citations`. Conformance is stamped deterministically in code (`src/okf.py`), never by the LLM, so it holds even on `gemma4:e4b`.

Language is preserved deterministically too: `src/lang.py` detects the source language at ingest and the query language at chat/research time, then pins the wiki page or answer to that language (German ↔ English) — citations, numbers and original terms stay verbatim. **Each wiki page keeps the language it was created in** (`src/page_lang.py`): when a source in the other language adds to it, only the new lines are translated, with original terms kept in parentheses, and code checks that no number, § reference or citation was lost (otherwise the text is kept as a labelled original quote). Maintenance → *Page language* fixes existing pages. Detection is code-side, never left to the model, so it holds on `gemma4:e4b`.

## Documentation

- [`PRD.md`](PRD.md) — what and why: problem, non-goals, milestones (original spec archived in
  [`docs/_bup_PRD.md`](docs/_bup_PRD.md))
- [`IMPLEMENTATION.md`](IMPLEMENTATION.md) — current state: run/verify, phase table, module map
- [`AGENTS.md`](AGENTS.md) — rules for every AI coding tool (Claude Code reads it via
  [`CLAUDE.md`](CLAUDE.md), Codex natively)
- [`docs/`](docs/) — deep per-area reference (architecture, retrieval, configuration, ui, gpu, …)

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
ollama pull bge-m3              # semantic retrieval arm (optional; lexical-only without it)
cp .env.example .env
```

### Optional: cross-encoder reranking (Stage D)

Improves precision on the Deep chat/research answer paths. Entirely optional —
without it, retrieval uses lexical + semantic fusion and behaves exactly as before.

```bash
uv sync --extra rerank          # builds llama-cpp-python from source (needs a C compiler)
mkdir -p models && curl -L -o models/bge-reranker-v2-m3-Q8_0.gguf \
  https://huggingface.co/gpustack/bge-reranker-v2-m3-GGUF/resolve/main/bge-reranker-v2-m3-Q8_0.gguf
```

Install from sdist as shown: the project's prebuilt `linux_x86_64` wheels are
musl-linked and fail to import on glibc. Set `RERANK_ENABLED=0` to switch it off.

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
| `OLLAMA_HOST` | `http://localhost:11434` | Ollama server URL — the fallback when GPU pinning is off or impossible |
| `OLLAMA_PIN_GPU` | `auto` | Keeps models on **one** GPU: the app starts its own `ollama serve` pinned to the emptiest card that fits (94 → 170 tok/s here). `off` uses `OLLAMA_HOST` as-is. See [docs/gpu.md](docs/gpu.md) |
| `TAVILY_API_KEY` | — | Required only for the Research page (web search) |
| `FRONTEND` | `default` | Visual skin: `default` (editorial) or `newspaper` (broadsheet). Chrome only — same pages and behaviour |

**Full configuration reference** (per-role model overrides, ingest/QA tuning, research + chat gates, all timeouts) lives in one place: [docs/configuration.md](docs/configuration.md). `.env.example` is the machine-readable template.

## Development

The repo follows the [claude-dev-schema](https://github.com/ToHeinAC/claude-dev-schema)
scaffold: short rules in [AGENTS.md](AGENTS.md), and every rule that can be checked is checked by
one quality gate (`.pre-commit-config.yaml`, numbers in `pyproject.toml`).

```bash
uv sync --inexact && uv run pre-commit install   # --inexact keeps a hand-installed CUDA reranker
uv run pytest                                    # fast loop (offline: sockets are blocked)
uv run pre-commit run --all-files                # full gate
```

| Rule | Edit hook | Stop hook | Commit | CI |
|---|---|---|---|---|
| Formatting (ruff) | yes | yes | yes | yes |
| Lint, complexity ≤ 10 (ruff); types, strict in `src/` (pyright) | | yes | yes | yes |
| Tests, branch coverage ≥ 85 %, suite ≤ 60 s | | yes | yes | yes |
| Functions ≤ 50 lines; doc size limits and links | | yes | yes | yes |
| No `.env` files, no private keys | | yes | yes | yes |
| Secret scan of staged changes (gitleaks) | | | yes | |

The Stop hook runs only when `.py` files changed. `src/vendor/` and `data/` are outside every check.
The process rules (red-green, small commits, docs updates) live in [AGENTS.md](AGENTS.md) §5.6.

Skills and commands: `/commit-git` (small Conventional Commits through the gate, never pushes
without asking) and `/documentation-update` (docs in line with the code) ship in `.claude/`. New
products or large features are shaped with the `first-principles-mindmap` → `prd-from-mindmap`
skills (MINDMAP.md → PRD.md). Claude Code built-ins such as `/code-review`, `/security-review` and
`/simplify` need no setup.

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

Apache License 2.0, see [LICENSE](LICENSE). Adapted and vendored third-party code: [NOTICE](NOTICE)
and [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
