# IMPLEMENTATION.md

State-of-implementation reference for **LocalWiki** — a local, Python-based, Karpathy-style self-compiling knowledge wiki driven by Ollama (`gemma4:e4b`).

> **Authoritative spec:** [`PRD.md`](PRD.md). This file is a navigation map and current-status tracker. It must stay under 500 lines (see CLAUDE.md §5.1).

---

## 1. Status

| Area | State |
|---|---|
| Repository | Initialised; remote `ToHeinAC/KB_BS_local-wiki-he` |
| Documentation skeleton | Populated (this commit) |
| Source code | **Not started** |
| Dependencies (`pyproject.toml`, `uv.lock`) | **Not created** |
| `SCHEMA.md` | **Not created** |
| `.env.example` | **Not created** |
| Test suite | **Not started** |

Nothing is implemented yet. All module references below are forward-looking.

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

## 3. Module Inventory (planned)

From PRD §2.2. Each is a single Python file at project root, no sub-packages (PRD §4.4).

| Module | Purpose | PRD §§ |
|---|---|---|
| `dedup.py` | SHA-256 deduplication for uploaded files | 3.1 |
| `file_processor.py` | Extract plain text from PDF/DOCX/MD/TXT/HTML | 3.2 |
| `ollama_client.py` | Thin wrapper around Ollama Python SDK | 3.3 |
| `schema_loader.py` | Load `SCHEMA.md`; produce ingest/query/lint system prompts | 3.4 |
| `wiki_engine.py` | Core ops: `ingest()`, `query()`, `lint()`, helpers | 3.6 |
| `tools.py` | `tavily_search` + `report_writer` tool definitions | 3.7 |
| `agent.py` | ReAct loop using Ollama native tool calling | 3.8 |
| `app.py` | Web UI (framework not forced) | 3.9 |
| `SCHEMA.md` | Wiki schema injected into every LLM system prompt | 3.5 |

---

## 4. Implementation Order

Per PRD §9 — implement bottom-up to keep each step independently verifiable:

1. `dedup.py` + tests
2. `file_processor.py` + tests
3. `ollama_client.py` (verify connectivity to `gemma4:e4b`)
4. `schema_loader.py` + `SCHEMA.md`
5. `wiki_engine.py` (ingest → query → lint)
6. `tools.py` (`tavily_search`, `report_writer`)
7. `agent.py` (ReAct loop)
8. `app.py` (NYT-style UI; see `docs/ui.md`)
9. Integration test: upload → ingest → chat → research
10. Test-suite review against the 100-test cap and 90/10 split

---

## 5. Hard Constraints (extracted from PRD)

- **No LangChain, no vector DB, no embeddings, no cloud LLM APIs** (PRD §2.3).
- **No async** unless the chosen UI stack requires it at boundaries (PRD §4.4).
- **One file per module**, no sub-packages (PRD §4.4).
- **`uv` only** for env + deps; no `requirements.txt` workflow (PRD §4.4, §5.3).
- **Streamlit not required** — UI framework is implementer's choice as long as UX + style hold (PRD §3.9, §4.4).
- **Test cap: 100 automated tests**, ≈90% core / ≈10% new features (PRD §4.5).
- **NYT editorial UI style**, content-first, restrained palette (PRD §2.4).
- **Apache-2.0 / MIT-compatible licensing** for everything added (CLAUDE.md §5.4).

---

## 6. Configuration (planned, not yet present)

Only `.env` is the user-facing config surface (PRD §4.4). Template will live in `.env.example`. Variables:

| Var | Default | Purpose |
|---|---|---|
| `TAVILY_API_KEY` | — | Web research (Research page only) |
| `OLLAMA_MODEL` | `gemma4:e4b` | Override model |
| `OLLAMA_HOST` | `http://localhost:11434` | Override Ollama endpoint |
| `MAX_INGEST_CHARS` | `50000` | Extract truncation threshold |
| `MAX_CONTEXT_CHARS` | `12000` | Query-time context cap |
| `AGENT_MAX_ITERATIONS` | `8` | ReAct safety limit |

Full reference: PRD §5.1.

---

## 7. Setup (target workflow)

See [`README.md`](README.md). End-state developer commands (PRD §8):

```bash
uv sync
ollama pull gemma4:e4b
cp .env.example .env  # add TAVILY_API_KEY if using Research
uv run python app.py   # or framework-specific launcher
```

---

## 8. Change Log

| Date | Change |
|---|---|
| 2026-05-02 | Initialised repo, documentation skeleton populated. |
