# AGENTS.md

Vendor-neutral collaboration rules for AI coding tools working in this repo (Claude Code, Codex, Cursor, …). This is the single source of truth; `CLAUDE.md` imports it. Behavioral guidelines to reduce common LLM coding mistakes — merge with project-specific instructions as needed.

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
- All LLM prompt strings must live in `src/prompts.py` as named module-level constants (e.g. `INGEST_PROMPT`, `CHAT_AGENT_SYSTEM`). Never embed prompt strings inline in other modules.

**Where the internals are documented:** the full module map, dataflow diagrams, and the retrieval/ingest/agent-loop internals live in [docs/architecture.md](docs/architecture.md); [IMPLEMENTATION.md](IMPLEMENTATION.md) §3 is the module-status index. Do not re-describe them here — read those. Hard rules an agent must not break:
- **BM25 index is scope-aware.** Query it via `lex_index.query(q, top_k, scope=…)` (`scope="raw"` for source chunks, `scope="wiki"` for page bodies). Never string-scan wiki pages or raw docs — `search_wiki` and the hybrid page-selector already go through the index.
- **Ingest is three-stage** (`ingest_begin` / `ingest_piece` / `ingest_end`; legacy single-call `ingest()` wraps them). Page identity and merge are **deterministic in code** (`_route_page` / `_merge_pages`), not prompt-driven — don't push that logic into prompts.
- **Deletion goes through `wiki_engine.delete_source(name)`** — it cascades across every store (raw file, manifest, chunks, qa.jsonl, wiki pages) and rebuilds the index. Never delete from one store alone.
- **Agent loop guard:** `src/run_memory.py` short-circuits duplicate reads/searches so weak local models can't loop. Section-aware reads and the 16 KB byte-offset window (`RAW_READ_CAP`) live in `src/tools.py`; if you change read/search behaviour, keep the visited-set keying intact.
- **OKF conformance is code-stamped, not prompt-driven.** The `wiki/` folder is an Open Knowledge Format (OKF v0.1) bundle; `src/okf.py` deterministically stamps OKF frontmatter + `## Citations` on every page write and formats `index.md`/`log.md`. Never ask the LLM to emit `okf_version`/`tags`/`resource`/`timestamp`/citations — keep it in code (small-model-safe). See [docs/okf.md](docs/okf.md).

### 5.4 Licencing
All implementation must be under the Apache Licence 2.0 or more permissive (e.g. MIT).
