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

The `wiki/` folder is an **Open Knowledge Format (OKF v0.1)** bundle — see
[okf.md](okf.md) for the full mapping. Every wiki page starts with YAML
frontmatter; the author (LLM) writes `title`/`type`/`sources`/`related`, and
`src/okf.py` deterministically stamps the OKF-recommended fields
(`description`, `tags`, `resource`, `timestamp`) plus a `## Citations` section —
**do not author those by hand**. OKF's one hard rule is a non-empty `type`.

```yaml
---
title: "Page Title"
type: concept | entity | source-summary
sources: ["file1.md"]
related: ["other-page.md"]
created: "YYYY-MM-DD"
updated: "YYYY-MM-DD"
confidence: high | medium | low
# --- code-stamped (OKF) — do not author ---
description: "one sentence"
tags: [db, type]
timestamp: "YYYY-MM-DDT00:00:00Z"
---
```

Cross-references are markdown links (`[Title](other-page.md)`) plus the
`related:` frontmatter list — OKF treats both as relationships.

`related:` is written by the ingest LLM, so it is **directional and sparse**: a
page can only cite pages that already existed when it was written, and ~88% of
real edges are one-way. Retrieval therefore never reads `related:` directly — it
goes through `wiki_engine.linked_pages()`, which traverses the graph undirected
(in-links + out-links) and adds implicit shared-source edges. See
[retrieval.md](retrieval.md) §Link-aware retrieval.

## `index.md` and `log.md` formats (OKF; code-generated)

- `index.md` — bundle root. Frontmatter declares `okf_version: "0.1"`; body has
  `# Pages` / `# Insights` sections with `* [Title](filename.md) - one-line description`.
- `log.md` — date-grouped, newest first: `## YYYY-MM-DD` headings with
  `- HH:MM — <action>: <detail>` bullets.

Both are rewritten by `wiki_engine` (`_rebuild_index` / `_append_log`), never
hand-edited.

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
