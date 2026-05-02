---
name: wiki.md
description: comprehensive documentation of the project´s database (here wiki and raw files)
version: 1.0.0
author: Tobias Hein
---

# Wiki & Storage

> Authoritative spec: [`PRD.md`](../PRD.md) §2.1 (Three-Layer Knowledge Model), §3.5 (`SCHEMA.md`), §6 (Schema Initialization).

## Layout

```
data/
├── raw/
│   ├── uploads/          # user originals (immutable)
│   ├── extracted/        # plain text per source (LLM reads)
│   └── .manifest.json    # SHA-256 dedup registry
└── wiki/                 # LLM owns entirely
    ├── index.md          # master catalog (updated every ingest)
    ├── log.md            # append-only activity log
    ├── overview.md       # high-level synthesis
    ├── concepts/         # concept/topic pages
    ├── entities/         # people, orgs, projects
    ├── sources/          # per-document summaries
    └── comparisons/      # cross-document analyses, filed from queries
```

`SCHEMA.md` lives at project root — not under `data/` — and is injected into every LLM system prompt so the model behaves as a wiki maintainer rather than a generic chatbot.

## Page conventions

Every wiki page **must** start with YAML frontmatter:

```yaml
---
title: "Page Title"
type: concept | entity | source-summary | comparison
sources: ["raw/extracted/file1.txt"]
related: ["wiki/concepts/other-page.md"]
created: "YYYY-MM-DD"
updated: "YYYY-MM-DD"
confidence: high | medium | low
---
```

Cross-references use `[[wikilinks]]` (e.g. `[[concepts/attention]]`).

## `index.md` and `log.md` formats

- `index.md` — categorised list. Each entry: `- [[path/to/page]] — one-line description (N sources)`.
- `log.md` — append-only. Each entry header: `## [YYYY-MM-DD HH:MM] TYPE | Title` where `TYPE ∈ {ingest, query, lint, research}`.

Full templates and examples: PRD §3.5.

## Ingest / Query / Lint workflows (LLM-side)

Defined in `SCHEMA.md` so the LLM follows them deterministically:

- **Ingest** — read extracted text → write source summary → create/update concept + entity pages → flag contradictions → update `index.md` → append `log.md` → return `{pages_created, pages_updated, contradictions}`.
- **Query** — read `index.md` → load relevant pages → synthesise answer with `[[wikilink]]` citations → ask "Want me to file this as a wiki page?".
- **Lint** — produce a markdown report with sections: *Contradictions*, *Orphan Pages*, *Missing Pages*, *Stale Claims*, *Suggested Investigations*.

## First-run initialisation

On first launch (PRD §6, §4.1), the app must create the `data/raw/...` and `data/wiki/...` subtrees, seed empty `index.md`, `log.md`, `overview.md`, copy a default `SCHEMA.md` if missing, and verify Ollama connectivity.

## Manifest schema

```json
{
  "<sha256>": {
    "filename": "my_paper.pdf",
    "original_name": "my_paper.pdf",
    "added_at": "2026-04-29T21:00:00",
    "extracted_path": "data/raw/extracted/my_paper.txt",
    "size_bytes": 48200
  }
}
```

Hash is computed over file bytes (not filename). Manifest writes are atomic. Detail: PRD §3.1.
