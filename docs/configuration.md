# Configuration

`.env` is the only config surface; [`.env.example`](../.env.example) is the machine-readable template.
Copy it to `.env` (gitignored, never committed) and adjust.

| Var | Default | Purpose |
|---|---|---|
| `OLLAMA_MODEL` | `gemma4:e4b` | Override model |
| `OLLAMA_HOST` | `http://localhost:11434` | Ollama endpoint the app falls back to. A **remote** value is never hijacked by the pinned daemon. Callers must use `ollama_client.host()`, not this var. |
| `OLLAMA_PIN_GPU` | `auto` | GPU placement for Ollama. `auto` starts an app-managed `ollama serve` pinned to the emptiest card that fits the configured models; a bare index forces that card; `off` uses `OLLAMA_HOST` as-is. Every failure falls back to `OLLAMA_HOST`. See [docs/gpu.md](gpu.md). |
| `OLLAMA_PIN_PORT` | `11435` | Port for the pinned daemon. Deliberately not `11434` — the system daemon and the box's other apps keep that one. An already-serving port is adopted, not duplicated. |
| `QUERY_MODEL` | `OLLAMA_MODEL` | Per-role override for precision/selection calls (`_select_affected_pages`, query page-select) + agent loops. |
| `INGEST_MODEL` | `OLLAMA_MODEL` | Per-role override for wiki page synthesis during ingest. |
| `FAST_MODEL` | `OLLAMA_MODEL` | Per-role override for lightweight maintenance (lint). |
| `EMBED_MODEL` | `bge-m3` | Embedding model for the semantic arm (`src/embed_index.py`), called via local Ollama `/api/embed`. Changing it invalidates the vector cache — re-run `scripts/backfill_embeddings.py <DB>`. Vectors are optional: DBs without them degrade to lexical-only. |
| `RERANK_ENABLED` | `1` | Master switch for the Stage D cross-encoder. `0` forces plain RRF fusion. |
| `RERANK_MODEL` | `models/bge-reranker-v2-m3-Q8_0.gguf` | Reranker GGUF path. Absent ⇒ `rerank.available()` is False and retrieval silently stays fusion-only. |
| `RERANK_CANDIDATES` | `30` | Fused-list depth handed to the cross-encoder. Cost is linear in this number (~35 ms/pair on CPU). |
| `RERANK_THREADS` | `0` (auto) | Reranker thread count; `0` uses `min(16, cpu_count)`. |
| `RERANK_PIN_GPU` | `auto` | GPU placement for the reranker. `auto` pins it to the emptiest card that fits; a bare index (`0`, `1`) forces that card; `off` restores llama.cpp's layer split across all cards. `0` names GPU 0 — it is **not** an off-switch. |
| `ABSTAIN_ENABLED` | `1` | Master switch for Stage E abstention. `0` never abstains (still answers). |
| `ABSTAIN_TAU_DEFAULT` | — | Fallback abstention τ when a DB has no `index/calibration.json`. Unset ⇒ uncalibrated DBs never abstain (fail-safe). Per-DB τ from `scripts/calibrate_abstention.py` always wins. |
| `FRONTEND` | `broadsheet` | Which frontend `scripts/run_app.py` starts. `broadsheet` = the NiceGUI frontend (`src/gui_app.py`). `default` or `newspaper` = the Streamlit app with that skin (`src/theme.py`): `default` is the editorial Forest palette, `newspaper` the broadsheet skin (paper stock, Bodoni masthead, Garamond prose, mono figures, hairline rules) plus the paper graph canvas. Running Streamlit directly ignores `broadsheet` and uses its default skin. See [docs/ui.md](ui.md) §Broadsheet frontend and §Frontend skins. |
| `GUI_STORAGE_SECRET` | random per process | Signs the NiceGUI session cookie (`FRONTEND=broadsheet`). Set it to keep logins across restarts. |
| `GRAPH_RENDERER` | `legacy` | Wiki Explorer → Graph renderer. `legacy` = the vis.js typed graph; `neural` = the canvas neural renderer (`src/graph_widget.py`). Default stays `legacy` until parity is confirmed. |
| `GRAPH_BACKDROP` | `galaxy` | Backdrop behind the neural graph canvas: `galaxy` = the Hubble image in `src/assets/graph/` (credit NASA/ESA, see `NOTICE`), `none` = flat `--bg`. Decorative only. |
| `GRAPH_MAX_NODES` | `4000` | Guardrail for the neural renderer: above this the payload keeps the best-connected nodes and flags `truncated`. The force layout, not the analytics, is what degrades first. |
| `TAVILY_API_KEY` | — | Required for the Research page (web search). |
| `MAX_INGEST_CHARS` | `40000` | Chunk size for ingest; documents exceeding this are split into sequential chunks |
| `INGEST_NUM_CTX` | `32768` | KV context cap on every `generate()`/`chat()` call and on the Deep chat agent (one window everywhere: a different `num_ctx` makes Ollama reload the model) — bounds the ggml compute graph so wide-graph models (gemma4:e4b) don't hit `GGML_SCHED_MAX_SPLIT_INPUTS`. Allocated *per slot*, so the pinned daemon runs `OLLAMA_NUM_PARALLEL=1` on a single GPU — with the shared daemon's 4 slots the cap is multiplied away. A crashed worker is retried once at half this value. |
| `DATA_ROOT` | `data` | Root for all databases. Each DB is an isolated subtree `$DATA_ROOT/<db>/{raw,chunks,index,wiki}`; users live in `$DATA_ROOT/users.json`. Replaces the old per-dir `WIKI_DIR`/`RAW_DIR`/`CHUNKS_DIR`/`INDEX_DIR` vars (paths now derive from `db_context` + active DB). |
| `INGEST_QA` | `1` | Run `qa_gen` during ingest (hypothetical questions). Set `0` to disable. |
| `STALE_AFTER_DAYS` | `365` | Default freshness window: a page with no `expires_after_days` is flagged stale when `updated` is older than this. |
| `QA_BATCH_SIZE` | `12` | Number of chunks per `qa_gen` LLM batch. |
| `QA_MAX_PAIRS_PER_SOURCE` | `5` | Max hypothetical-question pairs `qa_gen` emits per source; drives the chunk-selection heuristic and slices the final output. |
| `RESEARCH_MIN_SEARCHES` | `6` | Deep researcher: minimum web searches before submitting. |
| `RESEARCH_MIN_URLS` | `4` | Deep researcher: minimum unique sources cited (URLs + `[Wiki: ...]` citations). |
| `RESEARCH_MAX_ITERATIONS` | `40` | Deep researcher: LangGraph recursion cap. |
| `RESEARCH_PARALLELISM` | `4` | Deep researcher: thread-pool size for parallel Tavily / page fetches. |
| `RESEARCH_LLM_TIMEOUT` | `300` | Deep researcher: per-LLM-call timeout in seconds. |
| `DEEP_RESEARCH_MODEL` | `QUERY_MODEL` | Deep Research (web): Ollama tag used for **all four** upstream roles (research / report / compression / summarization). |
| `DEEP_RESEARCH_CONCURRENCY` | `1` | `max_concurrent_research_units`. Ollama serialises requests on one model, so raising this costs VRAM without buying speed. |
| `DEEP_RESEARCH_MAX_ITERATIONS` | `3` | `max_researcher_iterations` — supervisor reflection rounds. |
| `DEEP_RESEARCH_MAX_TOOL_CALLS` | `5` | `max_react_tool_calls` per researcher subgraph. |
| `DEEP_RESEARCH_MAX_CONTENT_LENGTH` | `16000` | `max_content_length` — page characters per result URL handed to the summarisation model (upstream 50000). Every URL of every search is summarised, so this is the run's biggest latency lever. |
| `DEEP_RESEARCH_STRUCTURED_RETRIES` | `4` | `max_structured_output_retries` (upstream 3) — a small model misses the schema more often. |
| `DEEP_RESEARCH_MAX_TOKENS` | `8192` | Per-role `*_model_max_tokens`. **No-op on Ollama** — `ChatOllama` bounds output with `num_predict`, not `max_tokens`, and `Configuration` exposes only `model`/`max_tokens`/`api_key` as configurable. Kept for parity with upstream. |
| `DEEP_RESEARCH_CLARIFICATION` | `false` | `allow_clarification`. Keep off: the Research page is one-shot and cannot answer a clarifying turn. |
| `CHAT_MIN_SEARCHES` | `3` | Deep chat: minimum distinct searches (`raw_search`/`wiki_search` queries) before the submit gate accepts. The gate also requires that at least one cited original was opened with `raw_read`. |
| `ANSWER_WORDS_PER_SOURCE` | `40` | Deep chat and Quick research: an answer under this many words per cited source is sent back **once** to explain each source (no word floor: a fixed floor made E4B pad with uncited detail). Coverage of the levels read in code is the real gate ([retrieval.md](retrieval.md) §Levels read in code). |
| `CHAT_MIN_SOURCES` | `2` | Deep chat: minimum unique citations (`[Source: filename]` + `[Wiki: page.md]`; at least one must be a `[Source: ...]` original). |
| `CHAT_MAX_ITERATIONS` | `40` | Deep chat: step cap (each agent turn is two steps, so about 20 turns), raised by turns earned through `CHAT_REF_BONUS_MAX`. |
| `CHAT_NUDGE_AT` | `CHAT_MAX_ITERATIONS // 2 - 2` | Deep chat: agent turns after which the agent is told once (stored in the history) to submit now. |
| `CHAT_RAW_READ_NUDGE_AFTER` | `3` | Deep chat: byte-offset windows of one file after which `raw_read` suggests to stop paginating (section reads are exempt). |
| `CHAT_PROSE_RETRIES` | `2` | Deep chat: an answer written as prose runs the submit gate; this many rejections are sent back before it is shown labelled best-effort. |
| `CHAT_REF_BONUS_MAX` | `6` | Deep chat: extra agent turns a run may earn by following cross-file references in `raw_read` footers (+2 per followed reference). |
| `CHAT_LLM_TIMEOUT` | `180` | Deep chat: per-LLM-call timeout in seconds. |
