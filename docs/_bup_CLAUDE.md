# CLAUDE.md

Behavioral guidelines to reduce common LLM coding mistakes. Merge with project-specific instructions as needed.

**Tradeoff:** These guidelines bias toward caution over speed. For trivial tasks, use judgment.

## 1. Think Before Coding

**Don't assume. Don't hide confusion. Surface tradeoffs.**

Before implementing:
- State your assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them - don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.

## 2. Simplicity First

**Minimum code that solves the problem. Nothing speculative.**

- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.

Ask yourself: "Would a senior engineer say this is overcomplicated?" If yes, simplify.

## 3. Surgical Changes

**Touch only what you must. Clean up only your own mess.**

When editing existing code:
- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- If you notice unrelated dead code, mention it - don't delete it.

When your changes create orphans:
- Remove imports/variables/functions that YOUR changes made unused.
- Don't remove pre-existing dead code unless asked.

The test: Every changed line should trace directly to the user's request.

## 4. Goal-Driven Execution

**Define success criteria. Loop until verified.**

Transform tasks into verifiable goals:
- "Add validation" → "Write tests for invalid inputs, then make them pass"
- "Fix the bug" → "Write a test that reproduces it, then make it pass"
- "Refactor X" → "Ensure tests pass before and after"

For multi-step tasks, state a brief plan:
```
1. [Step] → verify: [check]
2. [Step] → verify: [check]
3. [Step] → verify: [check]
```

Strong success criteria let you loop independently. Weak criteria ("make it work") require constant clarification.

---

**These guidelines are working if:** fewer unnecessary changes in diffs, fewer rewrites due to overcomplication, and clarifying questions come before implementation rather than after mistakes.

## 5. Project specific instructions

### 5.1 Documentation
For the project´s documentation, use IMPLEMENTATION.md as your main reference. Keep this one very compact and readable (under 500 lines). This one shall refer to the deep documentation of each component, which is under docs/ folder, e.g. docs/architecture.md etc. Generate a README.md

### 5.2 Efficency
This project must be implemented efficiently, without unnecessary code or complexity. For this follow the rules:
- Keep implementation and documentation precision such that the author as well as Claude Code etc. do not get confused.
- Whenever AI coding tools are used, those must plan and implement token-efficient. Usefull documentation hierarchy:
    - PRD.md as the main reference for the project's original purpose and goals
    - IMPLEMENTATION.md as the main reference for the current implementation state; also referencing specific details documented in the docs/ folder.
    - docs/ folder for detailed documentation of each component
- Be aware that whenever the project is progressed by using AI coding tools, a different AI coding tool may be used to confirm best implementation according to the rules, e.g. new code by Claude Code will be critically reviewed by Codex. It is important that the first implementation is as good as possible, to avoid unnecessary work.

### 5.3 Tech
The project uses the following technology choices:
- All implementation must be in python and the pythonic way of implementation.
- LangChain/LangGraph are permitted **only** inside the agent layer (`src/agent.py`, `src/chat_agent.py`, `src/tools.py`). Everywhere else: no LangChain, no vector DB, no embeddings, no cloud LLM APIs.
- `uv` is used for the virtual python environment setup and the running. Dependencies shall be defined in `pyproject.toml` and installed via `uv`.
- Use python-dotenv for the environmental variable handling.
- All domain Python modules live in `src/`. Run with `uv run streamlit run src/app.py --server.port 8520`.
- All LLM prompt strings must live in `src/prompts.py` as named module-level constants (e.g. `AGENT_SYSTEM`, `INGEST_PROMPT`). Never embed prompt strings inline in other modules.

See [docs/architecture.md](docs/architecture.md) for the full module map and dataflow diagrams, including the retrieval layer (`data/chunks/` + `data/index/`) driven by `src/chunker.py`, `src/lex_index.py`, and `src/qa_gen.py`. The BM25 index is scoped: `lex_index.query(q, top_k, scope=…)` searches raw source chunks (`scope="raw"`) and/or wiki page bodies (`scope="wiki"`); `search_wiki` and the hybrid query-page selector use it instead of string scans. Ingest is split into `ingest_begin` (source-scoped: chunker, qa_gen, build source→page reverse map — runs once) / `ingest_piece` (per 40 KB cut: BM25 affected-page selection over the prior index + rank-weighted existing-content merge context + the LLM wiki synthesis) / `ingest_end` (final `lex_index.build()` + index rebuild). The legacy `ingest(text, source, meta)` remains as a single-call wrapper. `qa_gen` is capped at `QA_MAX_PAIRS_PER_SOURCE=5` targeted pairs per source. Disable the LLM-driven sidecar in tests/CI by exporting `INGEST_QA=0`. Deletion: `wiki_engine.delete_source(name)` cascades across all stores (raw file, manifest, chunks, qa.jsonl, wiki pages) and rebuilds the index. Lifecycle: pages carry an optional `expires_after_days` frontmatter; `is_page_stale`/`stale_pages` flag overdue pages (default window `STALE_AFTER_DAYS=365`), surfaced as ⚠️ in the wiki tree and in date-aware `lint()`. `list_pages(include_insights=True)` folds `insights/*.md` into the tree, index (`## Insights`), and lint. Upload supports non-Markdown files: `src/md_convert.py` (vendored from [ToHeinAC/MD-maker](https://github.com/ToHeinAC/MD-maker), Apache-2.0 — see `NOTICE`) converts PDF / DOCX / images to Markdown via local Ollama (`ollama_client.ocr`/`.rewrite`, **not** LangChain) before ingest; the UI shows an editable preview, then only the converted `.md` is stored (dedup keyed on the original bytes via `dedup.register_file(..., content=)`). Env: `OCR_MODEL` (default `deepseek-ocr:3b`), `REWRITE_MODEL` (default `OLLAMA_MODEL`), `PDF_DPI` (default 150). Agent loop guard: `src/run_memory.py` provides a per-invocation visited-set (`ContextVar`-scoped) consulted by `wiki_read` / `raw_read` / `wiki_search` / `raw_search` in `src/tools.py`; exact-duplicate reads/searches short-circuit with a one-line `[memory] Already …` stub so weaker local models can't loop on the same document until `MAX_ITER` is hit. Section reads (e.g. `raw_read(["StrlSchG.md § 62"])`, legal `§` or markdown headings) resolve to that section's chunk text and are keyed per-section (`raw:{base}|sec=…`) so distinct sections are distinct reads; a blocked re-read lists the file's unread section anchors. Byte `offset` is keyed separately and remains the fallback for section-less files; a blocked section-less re-read names the exact next unread offset to call (`_next_unread_offset`), or says the whole file is read, so a weak model breaks the offset-0 loop in one step. The byte-offset window is 16 KB (`RAW_READ_CAP`), and after `RAW_READ_NUDGE_AFTER` (default 2) distinct windows of one file the read appends a "stop paginating — call submit_chat_answer now" nudge. If the deep-chat agent still stalls without submitting, `chat_agent._synthesize_fallback` writes a grounded answer from the gathered notes (mirrors `agent.py`) rather than discarding them; when the iteration limit is hit, an end-of-answer "may be partial" hint is appended to the final answer.

### 5.4 Licencing
All implementation must be under the Apache Licence 2.0 or more permissive (e.g. MIT). 
