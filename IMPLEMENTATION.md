# IMPLEMENTATION.md

State-of-implementation reference for **LocalWiki** — a local, Python-based, Karpathy-style self-compiling knowledge wiki driven by Ollama.

> **Authoritative spec:** [`PRD.md`](PRD.md). This file is a navigation map and current-status tracker. Must stay under 500 lines (CLAUDE.md §5.1).

---

## 1. Status

| Area | State |
|---|---|
| Repository | Initialised; remote `ToHeinAC/KB_BS_local-wiki-he` |
| Documentation skeleton | Complete |
| `pyproject.toml` / `uv.lock` | **Done** |
| `.env.example` | **Done** |
| `SCHEMA.md` | **Done** |
| `dedup.py` | **Done** |
| `file_processor.py` | **Done** |
| `schema_loader.py` | **Done** |
| `ollama_client.py` | **Done** |
| `wiki_engine.py` | **Done** |
| `app.py` (Streamlit, port 8520) | **Done** |
| `tools.py` | **Done** |
| `agent.py` | **Done** |
| Test suite | **Done** (84 tests) |
| `.streamlit/config.toml` | **Done** |

All planned modules are implemented. Test suite complete (84 tests, ≤100 cap).

---

## 2. Documentation Map

| Topic | File | PRD reference |
|---|---|---|
| Original product spec | [`PRD.md`](PRD.md) | (canonical) |
| Behavioural / process rules | [`CLAUDE.md`](CLAUDE.md) | — |
| Architecture (3-layer model, dataflows) | [`docs/architecture.md`](docs/architecture.md) | §2, §7 |
| Domain & rationale | [`docs/domain.md`](docs/domain.md) | §1, §10 |
| Tech stack & environment | [`docs/tech.md`](docs/tech.md) | §2.3, §4.4, §5 |
| UI design & pages | [`docs/ui.md`](docs/ui.md) | §2.4, §3.9 |
| Wiki / SCHEMA / storage | [`docs/wiki.md`](docs/wiki.md) | §2.1, §3.5, §6 |
| Testing strategy | [`docs/tests.md`](docs/tests.md) | §4.5 |
| Open issues | [`docs/openissues.md`](docs/openissues.md) | — |

---

## 3. Module Inventory

Each module is a single Python file at project root (PRD §4.4).

| Module | Purpose | Status |
|---|---|---|
| `dedup.py` | SHA-256 dedup; flat `data/raw/` store + `manifest.json` | Done |
| `file_processor.py` | Extract text from PDF/DOCX/MD/TXT/HTML; returns string | Done |
| `ollama_client.py` | `generate()` + `chat()` wrappers; `is_available()` health check | Done |
| `schema_loader.py` | `get_system_prompt()` — reads `SCHEMA.md` verbatim | Done |
| `wiki_engine.py` | `init_wiki`, `ingest`, `query`, `lint`, `list_pages`, `read_page`, `stats` | Done |
| `app.py` | Streamlit UI, 5 pages, port 8520, NYT editorial style | Done |
| `SCHEMA.md` | Wiki schema injected into every LLM system prompt | Done |
| `tools.py` | `tavily_search` + `report_writer` tool definitions | Done |
| `agent.py` | ReAct loop (max 8 iterations) | Done |

---

## 4. Implementation Notes (deviations from PRD)

The mockup simplifies a few planned details — tracked here so future iterations can align:

| Area | PRD intent | Current implementation |
|---|---|---|
| `data/raw/` layout | `uploads/` + `extracted/` subdirs + `.manifest.json` | Flat dir: files + `manifest.json` directly in `data/raw/` |
| LLM page output format | `### FILE:` / `### INDEX_UPDATE` / `### LOG_ENTRY` blocks | `=== filename.md ===` … `=== END ===` blocks |
| `schema_loader.py` | Separate system prompts per operation (ingest/query/lint) | Single `get_system_prompt()` returns full `SCHEMA.md` |
| `file_processor.py` | Saves extracted text to `data/raw/extracted/` | Returns extracted text in memory; no write |
| Query page selection | Title-heuristic + LLM ranking | LLM selects filenames from index text |

---

## 5. Hard Constraints

- **No LangChain, no vector DB, no embeddings, no cloud LLM APIs** (PRD §2.3).
- **No async** unless UI stack requires it at boundaries (PRD §4.4).
- **One file per module**, no sub-packages (PRD §4.4).
- **`uv` only** for env + deps (PRD §5.3).
- **Test cap: 100 automated tests**, ≈90% core / ≈10% new features (PRD §4.5).
- **NYT editorial UI style** (PRD §2.4).
- **Apache-2.0 / MIT-compatible licensing** (CLAUDE.md §5.4).
- **Streamlit port: 8520** (8511 reserved for another app on this host).

---

## 6. Configuration

`.env` is the only config surface (PRD §4.4). Template: `.env.example`.

| Var | Default | Purpose |
|---|---|---|
| `OLLAMA_MODEL` | `gemma3:4b` | Override model |
| `OLLAMA_HOST` | `http://localhost:11434` | Override Ollama endpoint |
| `TAVILY_API_KEY` | — | Web research (Research page, not yet implemented) |
| `MAX_INGEST_CHARS` | `40000` | Text truncation threshold at extraction |
| `WIKI_DIR` | `data/wiki` | Wiki page storage path |
| `RAW_DIR` | `data/raw` | Raw source file storage path |

---

## 7. Setup

```bash
git clone https://github.com/ToHeinAC/KB_BS_local-wiki-he
cd KB_BS_local-wiki-he
uv sync
ollama pull gemma3:4b          # or set OLLAMA_MODEL to any pulled model
cp .env.example .env           # add TAVILY_API_KEY when Research is implemented
uv run streamlit run app.py --server.port 8520
```

---

## 8. Change Log

| Date | Change |
|---|---|
| 2026-05-02 | Initialised repo, documentation skeleton populated. |
| 2026-05-02 | First mockup: implemented all core modules + Streamlit UI (Research stubbed). |
| 2026-05-02 | Second mockup: implemented `tools.py` + `agent.py`; Research page now fully wired. |
| 2026-05-02 | Applied crportfolioapp colour palette (`.streamlit/config.toml`); implemented 84-test suite across all modules. |
