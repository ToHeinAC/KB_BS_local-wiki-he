# AGENTS.md

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

§1–4 are adopted verbatim from [andrej-karpathy-skills](https://github.com/forrestchang/andrej-karpathy-skills)
(MIT, see [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)); do not edit them. §5 is this project's
contract; §5.4 lists what enforces it.

### 5.1 Documentation

Read [IMPLEMENTATION.md](IMPLEMENTATION.md) first (Claude Code auto-loads it via `CLAUDE.md`). Open the
other files only when the task needs them, to keep context small.

| File | Holds | Max lines |
|---|---|---|
| [PRD.md](PRD.md) | What and why: problem, non-goals, milestones with acceptance criteria. Changed only with the user's approval. | 800 |
| [IMPLEMENTATION.md](IMPLEMENTATION.md) | Current state: phase table (one row per PRD milestone), module map, run/verify. Only place for phase status. | 500 |
| [docs/architecture.md](docs/architecture.md) | Module responsibilities, data flow, design decisions. | 800 |
| `docs/<component>.md` | Deep docs of one component, linked from IMPLEMENTATION.md. | 800 |
| [README.md](README.md) | For humans: purpose, quickstart, where rules are enforced. | 300 |
| AGENTS.md | Rules (this file). | 200 |

- State each fact once; link to it instead of repeating it.
- After a change that affects docs, run `/documentation-update`.
- Exempt from the size limits: `ideas/` (raw notes), `.claude/skills/` references, `docs/_bup_*`
  (verbatim archives, e.g. the original PRD).

### 5.2 Conventions

- Python ≥ 3.11. Environment via `uv`: `uv sync` once, then `uv run <cmd>`. Add dependencies with
  `uv add <pkg>` (dev tools: `uv add --dev <pkg>`), never `pip install`. Commit `uv.lock`.
- Layout: domain modules flat in `src/` (one file per module; `src/app.py` is the Streamlit entry,
  so there is no `src/app/` package), tests in `tests/`, operational scripts in `scripts/`.
- Functions ≤ 50 lines, cyclomatic complexity ≤ 10.
- Type hints everywhere; `src/` passes pyright strict.
- I/O (network, files, databases) goes through the adapter modules (`ollama_client`, `db_context`,
  `lex_index`, `embed_index`, `auth`, …). Keep new core logic pure and test it without I/O.
- Configuration via environment variables, loaded with python-dotenv. Secrets only in `.env`;
  `.env.example` lists the keys without secret values. Runtime data goes in `data/`. Both are
  gitignored.
- Plan and implement token-efficiently. The first implementation must be review-ready: a second
  tool (e.g. Codex) reviews every change against this file.

### 5.3 Tech and hard rules
The project uses the following technology choices:
- All implementation must be in python and the pythonic way of implementation.
- LangChain/LangGraph are permitted **only** inside the agent layer (`src/agent.py`, `src/chat_agent.py`, `src/tools.py`, `src/deep_research_agent.py`) plus the vendored third-party tree `src/vendor/`. Everywhere else: no LangChain, no cloud LLM APIs, no external vector database or service.
- **`src/vendor/` is vendored third-party source — never hand-edit it.** It currently holds [`open_deep_research`](https://github.com/langchain-ai/open_deep_research) (MIT, pinned commit), which powers the Research page's Deep mode. Behaviour is changed only through `Configuration` from `src/deep_research_agent.py`; the sole modification to the files themselves is a mechanical import rewrite, recorded with the re-vendoring recipe in [src/vendor/README.md](src/vendor/README.md). It was vendored rather than `uv add`ed because upstream declares ~40 dependencies (Azure, Supabase, AWS, Vertex, `openai`) and pins the LangChain 0.3 line, which would downgrade this project's LangChain 1.x.
- **Async is permitted in `src/vendor/` and at the `deep_research_agent` boundary only** — an explicit, scoped waiver of the project's no-async rule, because the vendored graph is natively async. `run_deep_research` re-exposes it as a plain sync generator over a private event loop, so no other module sees `await`.
- **Local, file-backed embeddings for retrieval are permitted** (Stage C, `src/embed_index.py`). Constraints that keep them within the "fully local, low-admin" spirit: vectors are computed via the already-required local Ollama `/api/embed` (no cloud embedding API); stored as a per-DB **derived artifact** (`data/<DB>/index/vectors.npy` + `vectors.json`) that `build()` regenerates from `chunks/` + `wiki/` — a pure cache, never a source of truth; searched by **brute-force cosine** (no ANN index, no vector service). The semantic arm is **optional and graceful**: a DB with no vectors, or an unreachable embed model, degrades to the lexical arm with zero behaviour change. The lexical FTS5 arm remains the grounding/citation source of truth.
- **A local, in-process cross-encoder reranker is permitted** (Stage D, `src/rerank.py`). Same spirit, same guard rails: the model is a GGUF under `models/` (a re-downloadable artifact, never a source of truth), run **in-process** via `llama-cpp-python` — no second service, no cloud API. It is an **optional extra** (`uv sync --extra rerank`); without the runtime or the weights, retrieval is plain RRF fusion. It reorders only — it never introduces a document the two arms didn't already retrieve, so the lexical arm stays the citation source of truth.
- All domain Python modules live in `src/`. Run with `uv run streamlit run src/app.py --server.port 8520`.
- All LLM prompt strings must live in `src/prompts.py` as named module-level constants (e.g. `INGEST_PROMPT`, `CHAT_AGENT_SYSTEM`). Never embed prompt strings inline in other modules.

**Where the internals are documented:** the module map, dataflow diagrams and ingest/agent-loop internals live in [docs/architecture.md](docs/architecture.md), the retrieval layer (chunking, both arms, fusion, rerank, query dataflows) in [docs/retrieval.md](docs/retrieval.md), the Research page's web-only Deep mode in [docs/deep_research.md](docs/deep_research.md), GPU placement in [docs/gpu.md](docs/gpu.md); [IMPLEMENTATION.md](IMPLEMENTATION.md) §3 is the module map; the Streamlit chrome (layout, theming CSS, and the non-obvious framework behaviours below) lives in [docs/ui.md](docs/ui.md). Do not re-describe them here — read those. Hard rules an agent must not break:
- **An empty `lex_index.query()` does not mean "no match".** It also means *no index*: `query()` returns `[]` when the DB has no `index/chunks.sqlite`, which silently empties search, both chat modes, and the research agent. Use `lex_index.index_health()` to tell the two apart, and never report "no results" to a user without it. The fix is always a rebuild (`wiki_engine.rebuild_lex_index()`), never a change to the query path — the index is a derived cache.
- **UI chrome facts are documented, not re-derivable.** Before touching `src/app.py` layout, read [docs/ui.md](docs/ui.md) §Top-bar / chrome: Streamlit's fixed `stHeader` is opaque and overlays the top of the main column (hence `.block-container { padding-top: 4rem }`), the segmented control's testid is `stButtonGroup` with `button[kind="segmented_controlActive"]` for the selected pill, and primary navigation must not use `st.tabs` (it evaluates every branch per rerun, and Upload's `st.stop()` would blank the others). Each of these cost a debugging round-trip to establish; do not re-guess them.
- **BM25 index is scope-aware.** Query it via `lex_index.query(q, top_k, scope=…)` (`scope="raw"` for source chunks, `scope="wiki"` for page bodies). Never string-scan wiki pages or raw docs — `search_wiki` and the hybrid page-selector already go through the index.
- **Reranking fails open, and Ollama cannot do it.** `src/rerank.py` must return the unmodified fused order on *any* problem (no GGUF, no `llama-cpp-python`, decode error) — search reliability beats reranker quality. Two traps that cost a debugging round-trip each: Ollama exposes **no rerank endpoint**, and a reranker driven through `/api/generate` returns uniform noise instead of erroring, so "porting" this onto `ollama_client` fails *silently*; and `llama-cpp-python` does not expose `Llama.rank`, so scoring builds `[BOS] q [EOS] [SEP] doc [EOS]` on the ctypes layer under RANK pooling. Only the Deep answer paths rerank (`use_rerank=True`) — browsing and per-keystroke search must stay fusion-only.
- **Deep Research is web-only, and its citations come from `raw_notes`.** The Research page's Deep mode (`src/deep_research_agent.py`) never reads the wiki or `data/raw/` — don't "improve" it by adding local grounding; that is Quick mode's job. Three traps, each a debugging round-trip: the researcher subgraphs run via `researcher_subgraph.ainvoke(...)`, so their `web_search` tool messages **never** reach the parent stream even with `subgraphs=True` — URLs are parsed out of `raw_notes` instead; upstream's `Configuration.from_runnable_config` reads `os.environ[FIELD.upper()]` **before** our config dict, which is why every knob is namespaced `DEEP_RESEARCH_*`; and `final_report_generation` swallows its own exceptions into the report **string** rather than raising, so failure detection must test that prefix. On any failure Deep mode falls back to Quick — it must not error out. See [docs/deep_research.md](docs/deep_research.md).
- **Link traversal goes through `wiki_engine.linked_pages()` and is undirected.** Never read `related:` frontmatter directly for retrieval: it is LLM-written at ingest, so it is directional and ~88% of real edges are one-way — following out-links alone makes central hub pages look like dead ends. `linked_pages` unions out-links, in-links (`_backlink_map`), and clique-guarded shared-source edges. Both chat modes and the research agent consume it; keep link logic deterministic in code, never in prompts. See [docs/retrieval.md](docs/retrieval.md) §Link-aware retrieval.
- **Deep chat reads the wiki but is grounded in `data/raw/`.** `CHAT_TOOLS` includes `wiki_search`/`wiki_read` for navigation (the wiki is the map, the originals are the territory). `_submit_chat_impl` enforces this in code — a wiki-only answer is rejected — so don't relax the "≥1 `[Source: ...]` original" gate to a prompt instruction.
- **Ingest is three-stage** (`ingest_begin` / `ingest_piece` / `ingest_end`; legacy single-call `ingest()` wraps them). Page identity and merge are **deterministic in code** (`_route_page` / `_merge_pages`), not prompt-driven — don't push that logic into prompts.
- **Deletion goes through `wiki_engine.delete_source(name)`** — it cascades across every store (raw file, manifest, chunks, qa.jsonl, wiki pages, ontology ledger — retracted, never erased) and rebuilds the index. Never delete from one store alone.
- **Ontology writes go through `ontology_store` plans.** Shared modules `ontology/*.yaml` change via git only; a DB's binding and facts change only through `prepare_*` → `apply` (validated, maintainer-checked, revisioned, logged) or, for code, `ledger rows + record_change(via)`. The ledger is append-only. A revision is recorded only when the canonical hash moves. Page keys `class`/`work`/`version_date` are code-stamped from the ledger (`_okf_apply`), never LLM-written; an LLM may only *propose* a class, with a quote verified verbatim in code. Every search runs the ontology stage in code (`retrieval` + `ontology_query`): it adds only lexical hits, its briefing never carries document-derived text, and without an ontology results stay byte-identical. Valid time (sources' legal dates) is never compared with write dates (`updated`/`created`); superseded versions are demoted, never dropped. A class `rank` only orders and warns — it never decides a legal conflict; binding status is derived with its path (`ontology_graph.binding_of`), never stored. See [docs/ontology.md](docs/ontology.md).
- **Agent loop guard:** `src/run_memory.py` short-circuits duplicate reads/searches so weak local models can't loop. Section-aware reads and the 16 KB byte-offset window (`RAW_READ_CAP`) live in `src/tools.py`; if you change read/search behaviour, keep the visited-set keying intact.
- **GPU pinning is code-decided, and `CUDA_VISIBLE_DEVICES` alone is not enough.** Every locally loaded model goes on **one** card unless it cannot fit (`src/gpu_placement.py`): a split buys capacity, not speed, and costs a cross-device hop per token (94 → 170 tok/s here). Two traps, each a debugging round-trip: Ollama offers every card through CUDA *and* Vulkan, so a card hidden from CUDA **reappears as a Vulkan device and loads there anyway** — `OLLAMA_VULKAN=0` is what makes the filter authoritative; and CUDA orders devices fastest-first, so without `CUDA_DEVICE_ORDER=PCI_BUS_ID` index N is not nvidia-smi's GPU N. Reach Ollama only via `ollama_client.host()` (never `os.getenv("OLLAMA_HOST")`, or that caller silently lands on the unpinned shared daemon), and never reconfigure or restart the system daemon on `:11434` — the box's other apps depend on it, which is why `src/ollama_server.py` starts its own on a spare port instead. Every failure path falls back to the shared daemon; keep it that way. See [docs/gpu.md](docs/gpu.md).
- **OKF conformance is code-stamped, not prompt-driven.** The `wiki/` folder is an Open Knowledge Format (OKF v0.1) bundle; `src/okf.py` deterministically stamps OKF frontmatter + `## Citations` on every page write and formats `index.md`/`log.md`. Never ask the LLM to emit `okf_version`/`tags`/`resource`/`timestamp`/citations — keep it in code (small-model-safe). See [docs/okf.md](docs/okf.md).
- **Language pinning is code-detected, not model-guessed.** `src/lang.py` deterministically detects DE/EN (ingest → the *source* language; wiki-chat/agents → the *query* language) and injects the matching native-language directive from `prompts.py` (`RESPONSE_LANGUAGE_DIRECTIVE`/`INGEST_LANGUAGE_DIRECTIVE`). The ingest directive rides in the **system prompt** (survives the 40 KB-piece truncation), not the prompt tail. Structural `## Key facts`, citations, and numbers are directive-exempt. Don't ask the model to pick the language or add a translate tool — keep detection in code (small-model-safe). **A wiki page keeps the language it was created in** (`lang:` frontmatter, `src/page_lang.py`): every merge goes through `wiki_engine._align_language` (only new lines translated, numbers/§/citations verified in code, else a labelled `## Original (XX)` quote) — never append other-language lines raw, and never let a prompt decide a page's language. See [docs/architecture.md](docs/architecture.md) §Page language.

### 5.4 Testing and quality gate

- pytest; all tests live in `tests/` and are written in Python.
- The suite is offline: `tests/conftest.py` blocks sockets. Use synthetic fixtures; stub Ollama,
  Tavily and the pinned daemon (`ollama_client.host`).
- Red-green rule: a test counts only if it was seen failing against missing or wrong code, and
  passing against correct code. A repo-wide guard test also needs a test that feeds its detector
  a violating input.
- The gate is `.pre-commit-config.yaml`; its numbers live in `pyproject.toml`. `src/vendor/` and
  `data/` are excluded from every check and fixer.

| Rule | Enforced by |
|---|---|
| Format, lint, complexity ≤ 10 | ruff |
| Types (strict in `src/`) | pyright |
| Branch coverage ≥ 85 %, suite ≤ 60 s | pytest-cov `fail_under`, pytest-timeout `session_timeout` |
| Functions ≤ 50 lines | `tests/test_code_rules.py` |
| Doc size limits, no broken local links | `tests/test_docs.py` |
| No secrets, no `.env`, no private keys | gitleaks, `no-env-files`, `detect-private-key` |

- The gate runs on every commit (pre-commit), when Claude stops with changed `.py` files (Stop hook),
  and in CI. Never bypass it: `--no-verify` is denied.

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

### 5.6 Workflow and definition of done

1. **Shape**: a new product or large feature needs `PRD.md` first (README: "Skills and commands").
   Add its milestones to the phase table in IMPLEMENTATION.md.
2. **Red**: write the test first, run it, and confirm it fails for the expected reason.
3. **Green**: write the minimum code that makes it pass.
4. **Gate**: `uv run pre-commit run --all-files` passes.
5. **Docs**: `/documentation-update`.
6. **Commit**: `/commit-git`. Push only when the user asks.

A change is done when steps 2–6 are complete. Report the red and green results in the summary.

### 5.7 Licensing

The project is Apache-2.0 ([LICENSE](LICENSE)). Dependencies and copied code must use a permissive
license compatible with Apache-2.0 (MIT, BSD, ISC, PSF, Apache-2.0). Record copied code in
THIRD_PARTY_NOTICES.md (adapted or vendored code is also listed in [NOTICE](NOTICE)).
