# IMPLEMENTATION

Current state of **LocalWiki**, and the only place for phase status. What and why: [PRD.md](PRD.md).
Rules: [AGENTS.md](AGENTS.md). Design: [docs/architecture.md](docs/architecture.md).

## 1. Run and verify

| Task | Command |
|---|---|
| Install (once per clone) | `uv sync && uv run pre-commit install` |
| Run the app | `uv run streamlit run src/app.py --server.port 8520`, then open `http://localhost:8520/wiwi/` |
| Tests (fast loop) | `uv run pytest` or `uv run pytest tests/test_wiki_engine.py` |
| Full gate | `uv run pre-commit run --all-files` |
| Ontology detection bench | `uv run python scripts/bench_ontology_detect.py` (see [docs/ontology.md](docs/ontology.md)) |
| Ontology export (SKOS / JSON-LD) | `uv run python scripts/export_ontology.py --db <DB> --out <dir>` |
| Ontology search eval | `uv run python scripts/eval_ontology_search.py --root <scratch dir>` (downloads public law texts; never writes `data/`) |
| Optional reranker | `uv sync --inexact --extra rerank` (see [docs/retrieval.md](docs/retrieval.md)) |

- Port 8520 (8511 belongs to another app on this host). `.streamlit/config.toml` sets
  `baseUrlPath = "wiwi"` to match the nginx proxy at `https://ai.brenk.com/wiwi/`, so the port
  root returns 404. Keep `--server.port 8520` on the command line: `tunnel.sh` and the
  `restart-app` skill find the process by that flag.
- `uv sync` removes packages that are not in the lock, including a hand-installed CUDA build of
  `llama-cpp-python`; use `uv sync --inexact` on a machine that has one.
- Configuration: [docs/configuration.md](docs/configuration.md).

## 2. Phase status

One row per PRD milestone. Status: `planned`, `in progress`, `done`.

| Phase | Milestone | Status | Verified by |
|---|---|---|---|
| 1 | M1: Foundations | done | `test_dedup`, `test_file_processor`, `test_ollama_client`, `test_schema_loader` |
| 2 | M2: Wiki engine | done | `test_wiki_engine`, `test_integration`, `test_consolidate`, `test_okf` |
| 3 | M3: Research and chat agents | done | `test_agent`, `test_chat_agent`, `test_tools`, `test_deep_research_agent` |
| 4 | M4: Web UI | done | `test_app` |
| 5 | M5: Quality gate (claude-dev-schema) | done | `uv run pre-commit run --all-files` green (3.11, 3.13) |
| 6 | M6: Ontology ([plan](docs/_plan-ontology.md) phases 1–8) | in progress (plan phases 1–7 done) | `test_ontology`, `test_ontology_store`, `test_ontology_bundle`, `test_ontology_detect`, `test_ontology_ingest`, `test_ontology_query`, `test_ontology_search`, `test_ontology_time`, `test_ontology_time_search`, `test_ontology_merge`, `test_ontology_outdated`, `test_ontology_relations`, `test_ontology_relations_flow`, `test_ontology_evolution`, `test_ontology_evolution_flow`, `test_ontology_export`, `test_delete_source`, `test_app`; `scripts/bench_ontology_detect.py`, `scripts/eval_ontology_search.py` |
| – | Extensions beyond the original spec (no PRD milestone): hybrid retrieval stages A–F, multi-DB + auth, OKF bundle, language pinning, GPU pinning | done | `test_lex_index`, `test_embed_index`, `test_rerank`, `test_calibrate`, `test_multi_db`, `test_auth`, `test_lang`, `test_page_language`, `test_gpu_placement` |

## 3. Module map

All modules live in `src/` (flat, no `src/app/` package: `src/app.py` is the Streamlit entry).
Full responsibilities per module: [docs/architecture.md](docs/architecture.md) §Module inventory.

| Module | Responsibility |
|---|---|
| `app.py`, `theme.py`, `gpu_widget.py`, `graph_widget.py` | Streamlit UI shell, skins, GPU monitor, graph component ([docs/ui.md](docs/ui.md)) |
| `wiki_engine.py` | The only wiki writer: three-stage ingest, merge, query, lint, delete, link graph |
| `dedup.py`, `file_processor.py`, `md_convert.py`, `metadata_extract.py`, `template_loader.py` | Upload path: hash dedup, text extraction, PDF/DOCX/image → Markdown, effective date |
| `chunker.py`, `lex_index.py`, `embed_index.py`, `retrieval.py`, `rerank.py`, `calibrate.py`, `qa_gen.py` | Retrieval layer ([docs/retrieval.md](docs/retrieval.md)) |
| `ollama_client.py`, `ollama_server.py`, `gpu_placement.py` | Model access and single-GPU pinning ([docs/gpu.md](docs/gpu.md)) |
| `agent.py`, `chat_agent.py`, `tools.py`, `run_memory.py` | LangGraph agents (Quick research, Deep chat), their tools and loop guard |
| `deep_research_agent.py`, `vendor/` | Web-only Deep research over vendored `open_deep_research` ([docs/deep_research.md](docs/deep_research.md)) |
| `okf.py`, `lang.py`, `page_lang.py`, `graph_export.py` | OKF stamping, language pinning, graph analytics |
| `ontology.py`, `ontology_bundle.py`, `ontology_store.py`, `ontology_detect.py`, `ontology_query.py`, `ontology_time.py`, `ontology_graph.py`, `ontology_evolution.py`, `ontology_export.py`, `ontology_ui.py`, `ontology/*.yaml` | Ontology schema modules, validation, per-DB fact ledger, export/import with revisions, detection at upload, page stamping, the ontology stage in every search, valid time, relations/binding/lint, editor/cue tester/re-classify/suggestions, SKOS/JSON-LD export, Maintenance → Ontology ([docs/ontology.md](docs/ontology.md)) |
| `db_context.py`, `auth.py` | Per-DB paths and search scope; users, bcrypt, DB allowlists |
| `prompts.py`, `schema_loader.py` | All prompt strings; `SCHEMA.md` / `SCHEMA_QUERY.md` injection |
| `tests/test_code_rules.py`, `tests/test_docs.py` | Gate rules: functions ≤ 50 lines; doc size limits and local links |
| `.claude/hooks/format_on_edit.py` | PostToolUse hook: ruff-formats each `.py` file Claude edits |
| `.claude/hooks/stop_gate.py` | Stop hook: runs the gate if `.py` files changed; blocks the stop on failure |

## 4. Open issues

Tracked in [docs/openissues.md](docs/openissues.md).

## 5. Deviations from the original PRD

| Area | PRD intent | Current implementation |
|---|---|---|
| `data/raw/` layout | `uploads/` + `extracted/` subdirs + `.manifest.json` | Flat dir: files + `manifest.json` directly in `data/raw/` |
| LLM page output format | `### FILE:` / `### INDEX_UPDATE` / `### LOG_ENTRY` blocks | `=== filename.md ===` … `=== END ===` blocks |
| `schema_loader.py` | Separate system prompts per operation (ingest/query/lint) | `get_system_prompt(mode)` — `full` (ingest/page-writing) vs `query` (read/answer/describe/lint) |
| `file_processor.py` | Saves extracted text to `data/raw/extracted/` | Returns extracted text in memory; no write |
| Query page selection | Title-heuristic + LLM ranking | Hybrid: BM25 candidate set (wiki + raw scope) → LLM re-rank; full-index LLM fallback when BM25 is empty |
| Test suite | Capped at 100 tests | No cap; lean and high-signal, gated by coverage (AGENTS.md §5.4) |

## 6. Documentation map

| Topic | File |
|---|---|
| Architecture, module inventory, dataflows | [docs/architecture.md](docs/architecture.md) |
| Retrieval layer (arms, fusion, rerank, query flows) | [docs/retrieval.md](docs/retrieval.md) |
| Deep Research, web mode | [docs/deep_research.md](docs/deep_research.md) |
| Configuration (every `.env` variable) | [docs/configuration.md](docs/configuration.md) |
| Domain and rationale | [docs/domain.md](docs/domain.md) |
| Tech stack and environment | [docs/tech.md](docs/tech.md) |
| GPU placement | [docs/gpu.md](docs/gpu.md) |
| UI design, pages and Streamlit chrome facts | [docs/ui.md](docs/ui.md) |
| Wiki, SCHEMA and storage | [docs/wiki.md](docs/wiki.md) |
| Open Knowledge Format (OKF v0.1) | [docs/okf.md](docs/okf.md) |
| Ontology (schema, ledger); plan and rationale | [docs/ontology.md](docs/ontology.md), [plan](docs/_plan-ontology.md), [concept](docs/_idea-onthology.md) |
| Testing strategy | [docs/tests.md](docs/tests.md) |
| Dated change log | [docs/changelog.md](docs/changelog.md), archives [2](docs/changelog-archive-2.md), [1](docs/changelog-archive.md) |
| Original PRD (archived) | [docs/_bup_PRD.md](docs/_bup_PRD.md) |
| Critical analysis and roadmap (historical, not current guidance) | `docs/LocalWiki Implementation — Critical Analysis & Improvement Roadmap.md` |
