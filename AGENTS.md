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
- LangChain/LangGraph are permitted **only** inside the agent layer (`src/agent.py`, `src/chat_agent.py`, `src/tools.py`). Everywhere else: no LangChain, no cloud LLM APIs, no external vector database or service.
- **Local, file-backed embeddings for retrieval are permitted** (Stage C, `src/embed_index.py`). Constraints that keep them within the "fully local, low-admin" spirit: vectors are computed via the already-required local Ollama `/api/embed` (no cloud embedding API); stored as a per-DB **derived artifact** (`data/<DB>/index/vectors.npy` + `vectors.json`) that `build()` regenerates from `chunks/` + `wiki/` — a pure cache, never a source of truth; searched by **brute-force cosine** (no ANN index, no vector service). The semantic arm is **optional and graceful**: a DB with no vectors, or an unreachable embed model, degrades to the lexical arm with zero behaviour change. The lexical FTS5 arm remains the grounding/citation source of truth.
- **A local, in-process cross-encoder reranker is permitted** (Stage D, `src/rerank.py`). Same spirit, same guard rails: the model is a GGUF under `models/` (a re-downloadable artifact, never a source of truth), run **in-process** via `llama-cpp-python` — no second service, no cloud API. It is an **optional extra** (`uv sync --extra rerank`); without the runtime or the weights, retrieval is plain RRF fusion. It reorders only — it never introduces a document the two arms didn't already retrieve, so the lexical arm stays the citation source of truth.
- `uv` is used for the virtual python environment setup and the running. Dependencies shall be defined in `pyproject.toml` and installed via `uv`.
- Use python-dotenv for the environmental variable handling.
- All domain Python modules live in `src/`. Run with `uv run streamlit run src/app.py --server.port 8520`.
- All LLM prompt strings must live in `src/prompts.py` as named module-level constants (e.g. `INGEST_PROMPT`, `CHAT_AGENT_SYSTEM`). Never embed prompt strings inline in other modules.

**Where the internals are documented:** the module map, dataflow diagrams and ingest/agent-loop internals live in [docs/architecture.md](docs/architecture.md), the retrieval layer (chunking, both arms, fusion, rerank, query dataflows) in [docs/retrieval.md](docs/retrieval.md); [IMPLEMENTATION.md](IMPLEMENTATION.md) §3 is the module-status index; the Streamlit chrome (layout, theming CSS, and the non-obvious framework behaviours below) lives in [docs/ui.md](docs/ui.md). Do not re-describe them here — read those. Hard rules an agent must not break:
- **An empty `lex_index.query()` does not mean "no match".** It also means *no index*: `query()` returns `[]` when the DB has no `index/chunks.sqlite`, which silently empties search, both chat modes, and the research agent. Use `lex_index.index_health()` to tell the two apart, and never report "no results" to a user without it. The fix is always a rebuild (`wiki_engine.rebuild_lex_index()`), never a change to the query path — the index is a derived cache.
- **UI chrome facts are documented, not re-derivable.** Before touching `src/app.py` layout, read [docs/ui.md](docs/ui.md) §Top-bar / chrome: Streamlit's fixed `stHeader` is opaque and overlays the top of the main column (hence `.block-container { padding-top: 4rem }`), the segmented control's testid is `stButtonGroup` with `button[kind="segmented_controlActive"]` for the selected pill, and primary navigation must not use `st.tabs` (it evaluates every branch per rerun, and Upload's `st.stop()` would blank the others). Each of these cost a debugging round-trip to establish; do not re-guess them.
- **BM25 index is scope-aware.** Query it via `lex_index.query(q, top_k, scope=…)` (`scope="raw"` for source chunks, `scope="wiki"` for page bodies). Never string-scan wiki pages or raw docs — `search_wiki` and the hybrid page-selector already go through the index.
- **Reranking fails open, and Ollama cannot do it.** `src/rerank.py` must return the unmodified fused order on *any* problem (no GGUF, no `llama-cpp-python`, decode error) — search reliability beats reranker quality. Two traps that cost a debugging round-trip each: Ollama exposes **no rerank endpoint**, and a reranker driven through `/api/generate` returns uniform noise instead of erroring, so "porting" this onto `ollama_client` fails *silently*; and `llama-cpp-python` does not expose `Llama.rank`, so scoring builds `[BOS] q [EOS] [SEP] doc [EOS]` on the ctypes layer under RANK pooling. Only the Deep answer paths rerank (`use_rerank=True`) — browsing and per-keystroke search must stay fusion-only.
- **Link traversal goes through `wiki_engine.linked_pages()` and is undirected.** Never read `related:` frontmatter directly for retrieval: it is LLM-written at ingest, so it is directional and ~88% of real edges are one-way — following out-links alone makes central hub pages look like dead ends. `linked_pages` unions out-links, in-links (`_backlink_map`), and clique-guarded shared-source edges. Both chat modes and the research agent consume it; keep link logic deterministic in code, never in prompts. See [docs/retrieval.md](docs/retrieval.md) §Link-aware retrieval.
- **Deep chat reads the wiki but is grounded in `data/raw/`.** `CHAT_TOOLS` includes `wiki_search`/`wiki_read` for navigation (the wiki is the map, the originals are the territory). `_submit_chat_impl` enforces this in code — a wiki-only answer is rejected — so don't relax the "≥1 `[Source: ...]` original" gate to a prompt instruction.
- **Ingest is three-stage** (`ingest_begin` / `ingest_piece` / `ingest_end`; legacy single-call `ingest()` wraps them). Page identity and merge are **deterministic in code** (`_route_page` / `_merge_pages`), not prompt-driven — don't push that logic into prompts.
- **Deletion goes through `wiki_engine.delete_source(name)`** — it cascades across every store (raw file, manifest, chunks, qa.jsonl, wiki pages) and rebuilds the index. Never delete from one store alone.
- **Agent loop guard:** `src/run_memory.py` short-circuits duplicate reads/searches so weak local models can't loop. Section-aware reads and the 16 KB byte-offset window (`RAW_READ_CAP`) live in `src/tools.py`; if you change read/search behaviour, keep the visited-set keying intact.
- **OKF conformance is code-stamped, not prompt-driven.** The `wiki/` folder is an Open Knowledge Format (OKF v0.1) bundle; `src/okf.py` deterministically stamps OKF frontmatter + `## Citations` on every page write and formats `index.md`/`log.md`. Never ask the LLM to emit `okf_version`/`tags`/`resource`/`timestamp`/citations — keep it in code (small-model-safe). See [docs/okf.md](docs/okf.md).
- **Language pinning is code-detected, not model-guessed.** `src/lang.py` deterministically detects DE/EN (ingest → the *source* language; wiki-chat/agents → the *query* language) and injects the matching native-language directive from `prompts.py` (`RESPONSE_LANGUAGE_DIRECTIVE`/`INGEST_LANGUAGE_DIRECTIVE`). The ingest directive rides in the **system prompt** (survives the 40 KB-piece truncation), not the prompt tail. Structural `## Key facts`, citations, and numbers are directive-exempt. Don't ask the model to pick the language or add a translate tool — keep detection in code (small-model-safe).

### 5.4 Licencing
All implementation must be under the Apache Licence 2.0 or more permissive (e.g. MIT).

### 5.5 Databases in `data/` are off-limits — except `KI`

**`data/KI` is the only database an AI coding tool may touch at all — read or write.** It is the test database, kept deliberately disposable for development work. Every other database under `data/` (`Strahlenschutz`, `Investing`, `AVE`, `AVE_RAG`, `Fusion`, `NORM`, `STA-QS`, `BGEconnect`, `Labor`, `CO2-Zertifikate_BECV`, `Abluftreinigung`, …) holds real user content and is **not yours to open**: do not read, list, search, summarise, cite, or quote anything inside it, and do not create, edit, move, or delete anything inside it.

This applies to any AI coding tool (Claude Code, Codex, Cursor, …) and to every mechanism: the file tools, shell commands (`cat`, `less`, `grep`, `ls`, `rm`, `mv`, `>`, `sed -i`), and scripts you write and run. If a task seems to require reading or writing a non-KI database, stop and ask; do not proceed on your own judgement. "The user asked me a question I could answer by reading it" is not authorization — ask first.

**Why this is a hard rule, not a preference:**
- **Writes:** `data/` is gitignored (except for stale tracked files under `Strahlenschutz`/`Investing` predating commit `7ab6176`). These databases exist **only on the local disk — there is no backup and no git history to restore from.** A wrong write is permanent data loss, not a revertable commit.
- **Reads:** these are the user's real working corpora — legal texts, permits, internal material. They stay out of coding-tool context unless the user puts them there deliberately.

Scope — what the rule does *not* restrict:
- **`data/KI` is fully open** — read and write it freely. Point development, testing, and any "show me how a DB is structured" work at it.
- **The application itself** (ingest, retrieval, wiki writes, `delete_source`, index rebuilds via `uv run streamlit …`) reads and writes whatever DB the user selects at runtime. This rule constrains the *coding tool*, not the running app. Never "fix" app code to stop it reaching `data/`.
- **User-directed, database-specific instructions win.** If the user explicitly names a non-KI database and asks you to read or write it, that is authorization — confirm the target once, then proceed.

Claude Code additionally enforces this mechanically via `PreToolUse` hooks in `.claude/settings.json`: file tools (`Read`/`Grep`/`Glob`/`Write`/`Edit`/`NotebookEdit`) are **denied** under `data/` outside `data/KI`, and `Bash` commands naming a non-KI `data/` path are escalated to **ask** (they cannot be auto-denied without also blocking legitimate app runs). The hooks are a backstop for one tool and are not airtight — an unscoped `grep` from the repo root can still surface `data/` content incidentally. The rule above is what actually binds.
