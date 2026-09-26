# PRD — LocalWiki

> Condensed from the original PRD v1.1 (2026-05-01), which is archived verbatim at
> [docs/_bup_PRD.md](docs/_bup_PRD.md); older docs that cite `PRD §x.y` refer to that file.
> IMPLEMENTATION.md maps one phase to each milestone below. Change this file only with the
> user's approval.

## 1. Problem & goal

Documents pile up faster than anyone can read, cross-reference or keep current, and search over
raw files returns fragments instead of understanding. LocalWiki implements Andrej Karpathy's
"LLM knowledge base" pattern fully locally: a local LLM (Ollama, default `gemma4:e4b`) compiles
uploaded documents into a persistent, interlinked Markdown wiki that users can navigate, chat
with, and challenge with web research. Solved means: drop in a document, and the wiki gains
correct, cited, deduplicated pages that answer later questions with traceable sources.

## 2. Non-goals

- Cloud LLM APIs, cloud embedding APIs, external vector databases or services.
- Multi-tenant hosting, Docker packaging, a configuration UI (`.env` is the only config surface).
- Fuzzy duplicate detection (dedup is hash-exact).
- Streaming or async product code outside the scoped exceptions in AGENTS.md §5.3.

## 3. Constraints

- Fully local: Ollama for every model; Tavily is the only external service, and only for the
  Research page. Scoped exceptions (local embeddings, in-process reranker, vendored deep
  research) are listed in AGENTS.md §5.3.
- Must work with a small local model (`gemma4:e4b`): format, routing, language and citation logic
  are deterministic in code, not prompt-driven.
- Python ≥ 3.11 with `uv`; files and JSON as storage (SQLite FTS5 only as a derived index).
- Apache-2.0, with permissively licensed dependencies (AGENTS.md §5.7).
- Editorial, New York Times-inspired UI: typography-first, restrained colour, content before
  chrome.

## 4. Milestones

### M1 — Foundations
- **Deliverable:** `dedup.py`, `file_processor.py`, `ollama_client.py`, `schema_loader.py` +
  `SCHEMA.md`.
- **Acceptance criteria:** identical bytes are detected as duplicates regardless of filename;
  PDF/DOCX/MD/TXT/HTML yield text and other types raise; every model call goes through
  `ollama_client` and reaches the host from `ollama_client.host()`; the schema is injected into
  every wiki-writing system prompt.
- **Edge cases:** empty or non-UTF-8 files are read with replacement; Ollama down → a clear error
  at the point of use, never a crash.
- **Dependencies:** none.

### M2 — Wiki engine
- **Deliverable:** `wiki_engine.py` with ingest, query, lint, cascading delete and the helpers the
  UI needs.
- **Acceptance criteria:** ingest writes one source summary plus concept/entity pages, updates
  `index.md` and `log.md`, and reports pages created/updated and contradictions; page identity and
  merges are decided in code; query answers with citations to wiki pages and originals;
  `delete_source` removes a source from every store.
- **Edge cases:** unparseable LLM output never corrupts existing pages; large documents are
  ingested in chunks; linting an empty wiki reports that instead of calling the model.
- **Dependencies:** M1.

### M3 — Research and chat agents
- **Deliverable:** `tools.py`, `agent.py` (Quick research), `chat_agent.py` (Deep chat),
  `deep_research_agent.py` (web-only Deep research).
- **Acceptance criteria:** agents yield step dicts for live display; iterations are capped;
  reports cite their sources and can be filed to the wiki; Deep chat answers cite at least one
  original from `data/raw/`; Deep research falls back to Quick mode on failure.
- **Edge cases:** missing `TAVILY_API_KEY` → setup guidance instead of an error; duplicate tool
  calls are short-circuited so weak models cannot loop.
- **Dependencies:** M2.

### M4 — Web UI
- **Deliverable:** Streamlit app (`src/app.py`, port 8520) with Upload, Wiki Explorer, Chat,
  Research and Maintenance, behind a local login.
- **Acceptance criteria:** upload shows duplicate status and never auto-ingests; ingest progress
  and a structured summary are visible; the explorer lists, searches and renders pages; chat and
  research show their traces; maintenance offers lint, activity log and guarded destructive
  actions.
- **Edge cases:** an empty wiki shows onboarding guidance; Ollama errors surface at the point of
  use; users only see the databases they are allowed to.
- **Dependencies:** M2, M3.

### M5 — Quality gate (claude-dev-schema)
- **Deliverable:** the repository follows the
  [claude-dev-schema](https://github.com/ToHeinAC/claude-dev-schema) scaffold: AGENTS.md rules,
  one pre-commit gate, CI, offline test suite.
- **Acceptance criteria:** `uv run pre-commit run --all-files` passes: ruff (lint, complexity
  ≤ 10), pyright strict on `src/`, branch coverage ≥ 85 %, suite ≤ 60 s, functions ≤ 50 lines,
  doc size limits and resolvable links, no secrets.
- **Edge cases:** `src/vendor/` (never hand-edited) and `data/` (user databases) are outside
  every check and every auto-fixer.
- **Dependencies:** M1–M4.

### M6 — Ontology
- **Deliverable:** per-DB ontology (shared schema modules in `ontology/*.yaml`, an append-only
  fact ledger per DB, code-stamped projections), a Maintenance → Ontology workbench (view,
  export, hand-edit, import, change history), and a mandatory ontology stage in every search.
  Plan and phases: [docs/_plan-ontology.md](docs/_plan-ontology.md); rationale:
  [docs/_idea-onthology.md](docs/_idea-onthology.md).
- **Acceptance criteria:** schema changes are validated before they are stored; every applied
  change is logged with who, when and what, and re-importing an unchanged file is not a change;
  user decisions survive re-classification; every search path runs the ontology stage in code;
  relevance with the stage is never worse than without it on the `bench/` gold set.
- **Edge cases:** a DB without an ontology, or with a broken one, behaves exactly as before; an
  import based on an older export does not undo newer changes; `delete_source` retracts the
  source's ledger rows.
- **Dependencies:** M2, M3, M4.

## 5. Open risks & assumptions

- Small-model output drifts in format → keep every structural decision in code, and add a
  regression test whenever a prompt-only rule fails.
- Retrieval quality depends on the corpus → measured with `scripts/bench_retrieval.py` against the
  fixtures in `bench/` before changing ranking.
- The optional reranker needs a native build (`llama-cpp-python`) → it fails open, so retrieval
  never depends on it.

## 6. Definition of done

All milestones are `done` in the IMPLEMENTATION.md phase table, the full gate is green, and the
docs match the code (`/documentation-update`).
