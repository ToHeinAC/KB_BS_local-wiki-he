# Security — classification layer (M7)

Status and phase: [IMPLEMENTATION.md](../IMPLEMENTATION.md) §2. Milestone and acceptance
criteria: [PRD.md](../PRD.md) M7. This file holds the design, the gate API and the threat model.

## Why physical separation

Within one DB the read paths are many (≈20 chokepoints: the lexical and semantic index, chunk
store, page and raw readers, `index.md`/`DESCRIPTION.md`/`log.md`, the graph, the ontology view,
agent system prompts), there are process-wide caches (`graph_widget._payload`), and
`_merge_bodies` unions lines from several sources into one page without recording which line came
from which source. A per-path filter over labelled content could not be shown to be complete.
Instead every level is its own sub-store ("shard"), and one gate decides whether a path into a
shard can be resolved at all.

## Shards

| Shard id | Path | Level |
|---|---|---|
| `KI` | `data/KI/` (unchanged; existing data is the normal level) | 0 normal |
| `KI@confidential` | `data/KI/_levels/confidential/` | 1 confidential |
| `KI@strict` | `data/KI/_levels/strict/` | 2 strictly confidential |

- Each shard has its own `raw/` + `manifest.json`, `chunks/`, `index/`, `wiki/` (with `index.md`,
  `log.md`, `DESCRIPTION.md`) and `ontology/` ledger. The ontology binding `ontology.yaml` exists
  once per DB and is read by every level; schema changes are only accepted at the normal level.
- `@` is the level separator: `#` and `§` already mark citation sections, and `@` is not allowed
  in DB names, so a shard id never collides with a DB.
- Pages of different levels are never merged. A topic can therefore have one page per level;
  the UI shows a level badge.

## Gate (`src/db_context.py`)

- A clearance ContextVar maps DB → highest level. Unsealed (tests, scripts) it grants level 0 of
  every DB; sealed (the app, per rerun) it grants exactly the user's allowed DBs at their level.
- `require(shard)` raises `AccessDenied`. It runs in `data_root()` — which every path getter goes
  through — and in `set_active_db`, `using_db` and `set_search_scope`.
- `confine(base, name)` rejects names that resolve outside their directory (traversal,
  absolute paths). Tools answer a denied name exactly like a missing one.
- `bind_context` carries clearance, active DB and scope into worker threads; a worker without it
  falls back to level 0.
- `write_target(db, scope)` is the high-water mark: derived content is saved to the highest level
  it read from.

## Threat model

- **Adversary:** a logged-in user below the required clearance — including admins and maintainers
  without it — acting through any UI feature, crafted questions, or tool arguments steered by
  prompt injection from normal-level documents (guessed names, forged `@` prefixes, traversal).
- **Guarantees:** G1 no path into a shard above clearance; G2 no automatic write-down; G3 no
  existence oracle; G4 no classified content to the web without an explicit opt-in.
- **Non-goals:** OS-level file access, encryption at rest, backups, Ollama server-side logs, the
  tunnel transport, an admin granting themselves clearance (trusted, and audited), covert
  channels, content authorised users copy out, a run already in progress when clearance is
  revoked.

## Decisions

- Clearance is hierarchical and per DB; admin does not imply clearance; only admins set it.
- Upload requires an explicit level per file (no default), at most the uploader's clearance.
- Wiki Chat searches every reachable level by default; saved answers go to the high-water mark.
- Research searches the normal level by default; including classified levels removes the web
  tools, and Deep research (web-only) is then disabled.
- Saving answers or reports to the wiki requires maintainer rights and clearance for the target.
- Moving a source up purges its traces from the lower level: pages that merged it are rebuilt
  from their other sources, derived insights and reports (`derived_from`) are removed, its ledger
  rows and history snapshots are removed (the one exception to the append-only ledger), log lines
  are redacted and `DESCRIPTION.md` is rebuilt.
- Duplicate checks only look at levels the uploader can see; a silent second copy is recorded in
  the audit log by hash only.
- `data/security_audit.jsonl` records clearance changes, classifications, moves, denied access and
  duplicates — who, when, what, never content.

## Phases

| Phase | Content |
|---|---|
| P0 | `confine()` in the page and raw readers; tools map denial to "not found" |
| P1 | `classification.py`; the gate in `db_context`; `base_db()` for maintainer checks, OKF tags and prompts; AST security rules; canary fixture |
| P2 | Clearance in `auth`; Admin UI; per-rerun sealing; audit log |
| P3 | Read fan-out over reachable shards: Explorer, graph (one level at a time), Chat, Research |
| P4 | Upload classification column, per-shard ingest, dedup over visible levels |
| P5 | High-water writes, maintainer-only save, `derived_from` provenance, web egress policy |
| P6 | Maintenance level selector, ontology schema lock above normal, `move_source`, purge on upgrade |
| P7 | Docs |
