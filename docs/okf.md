# Open Knowledge Format (OKF v0.1) alignment

This project's per-database `wiki/` folder is a conformant **OKF v0.1 Knowledge
Bundle**. OKF is a deliberately minimal convention (spec:
`GoogleCloudPlatform/knowledge-catalog/okf/SPEC.md`): a bundle is a directory of
markdown *Concept* documents, each with YAML frontmatter whose only hard
requirement is a non-empty `type`, plus reserved `index.md`/`log.md`, markdown
cross-links as relationships, and an optional `## Citations` section.

**Design rule:** every OKF field/section is stamped **deterministically in code**
(`src/okf.py`), never asked of the LLM — so a small local model (gemma 4b) can
never break conformance. This mirrors the existing model-independent
`_route_page`/`_merge_pages`/frontmatter-patching in `wiki_engine`.

**Every** page-writing path routes through `okf.apply_to_page`, not just the
main ingest loop: `ingest_piece` + `_merge_pages` (ingest/consolidate),
`file_answer` (Chat "Save to wiki" insights), `resolve_contradiction`, and the
research-report writer (`tools.py` → `comparisons/`). So any page created after
2026-07 is conformant and enriched regardless of which feature made it.

## Mapping (OKF ↔ this project)

| OKF concept | This project |
|---|---|
| Knowledge Bundle | `data/<db>/wiki/` |
| Concept | a `wiki/*.md` page |
| Concept ID (path − `.md`) | filename slug |
| required `type` (non-empty) | frontmatter `type` (`concept`/`entity`/`source-summary`/`report`/`insight`) |
| `okf_version` (bundle-root `index.md`) | stamped by `_rebuild_index` |
| recommended `description` | derived from first `## Key facts` bullet / first sentence |
| recommended `tags` | coarse deterministic: `[<db>, <type>, <part of>]` |
| recommended `resource` (URI) | `raw/<source>` for source-summary/report; source URL when it is one |
| recommended `timestamp` (ISO 8601) | `updated` promoted to `…T00:00:00Z` |
| `## Citations` | regenerated from the `sources:` list |
| cross-links = relationships | `related:` frontmatter + `[Title](file.md)` links |
| reserved `index.md` | OKF `# Pages`/`# Insights` sections, `* [Title](file.md) - desc` |
| reserved `log.md` | date-grouped `## YYYY-MM-DD`, newest first |

## Deliberate deviations (still OKF-conformant)

OKF is permissive — consumers MUST NOT reject a bundle for unknown types/keys,
missing optional fields, or broken links. We use that latitude:

- **`type` stays lowercase enum**, not OKF's capitalized examples. The engine
  matches on it (`_route_page`, `build_typed_graph`); OKF only needs a non-empty
  short string.
- **`# Schema` / `# Examples` sections are omitted** — domain-inapplicable
  (this is an encyclopedic wiki, not an asset catalog). OKF permits missing
  sections.
- **Load-bearing keys kept alongside OKF ones** (`sources`, `related`,
  `key_terms`, `confidence`, `expires_after_days`) — additive, since OKF allows
  unknown keys.
- **Internal `## Key facts` heading retained** (drives merge/index-block logic);
  OKF `## Citations` is added as a separate trailing section.

## Conformance gate

`okf.okf_validate(wiki_dir) -> list[str]` returns issues (empty == conformant):
every non-reserved `.md` parses and has a non-empty `type`; bundle-root
`index.md` declares `okf_version: "0.1"`. Broken links are **not** failures
(OKF §9). Run the backfill with `scripts/okf_migrate.py` (dry-run by default;
`--apply` writes, backing `wiki/` up to `wiki.bak_<date>/` and rebuilding the
BM25 index).
