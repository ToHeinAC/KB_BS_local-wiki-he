# Security — classification levels

Milestone and acceptance criteria: [PRD.md](../PRD.md) M7. Status: [IMPLEMENTATION.md](../IMPLEMENTATION.md)
§2. This file holds the design, the gate API, the threat model and the residual risks.

## Why physical separation

Within one DB the read paths are many (lexical and semantic index, chunk store, page and raw
readers, `index.md`/`DESCRIPTION.md`/`log.md`, the graph, the ontology view, agent system
prompts), there are process-wide caches (`graph_widget._payload`), and `_merge_bodies` unions
lines from several sources into one page without recording which line came from which source. A
per-path filter over labelled content could not be shown to be complete. Instead every level is
its own sub-store ("shard"), and one gate decides whether a path into a shard resolves at all.

## Shards

| Shard id | Path | Level |
|---|---|---|
| `KI` | `data/KI/` (existing data is the normal level; no migration) | 0 Normal |
| `KI@confidential` | `data/KI/_levels/confidential/` | 1 Confidential |
| `KI@strict` | `data/KI/_levels/strict/` | 2 Strictly confidential |

- Each shard has its own `raw/` + `manifest.json`, `chunks/`, `index/`, `wiki/` (with `index.md`,
  `log.md`, `DESCRIPTION.md`) and `ontology/` ledger. The binding `ontology.yaml` exists once per
  DB and every level reads it; `ontology_store._write_binding` refuses above the normal level.
- `src/classification.py` (pure) names things: `LEVELS`, `LEVEL_LABELS`, `shard_id`,
  `parse_shard` (only canonical ids parse), `label`, `high_water`, `plan_upload`.
- `@` separates the level: `#`/`§` already mark citation sections, and `@` is not allowed in DB
  names, so a shard id collides with neither.
- Pages of different levels are never merged. A topic can have one page per level.
- Shards are created on first use (`db_context.ensure_shard`); `reachable_shards(db)` lists the
  normal shard plus existing higher ones up to the clearance.

## Gate (`src/db_context.py`)

- **Clearance** is a ContextVar mapping DB → highest level. Unsealed (tests, scripts, worker
  threads) it grants level 0 of every DB. The app calls `seal_clearance(grants, user=…)` at the
  top of every rerun — first `{}` (nothing reachable), then after login `auth.clearance_map(user)`
  — so a sealed session reaches exactly its allowed DBs at their levels, and a revoked grant takes
  effect at the next interaction.
- `require(shard)` raises `AccessDenied` (a `PermissionError`). It runs in `data_root()` — which
  every path getter goes through — and in `set_active_db`, `using_db` and `set_search_scope`,
  which raise instead of silently filtering.
- `confine(base, name)` rejects names that resolve outside their directory (`../`, absolute
  paths); the page and raw readers treat that as "not found", with the same message as a real
  miss, so there is no existence oracle.
- `bind_context(fn)` carries clearance, user, active DB and scope into thread-pool workers; a
  worker without it falls back to level 0.
- `write_target(db, scope)` is the high-water mark: the shard of `db` at the highest level in the
  scope, or `AccessDenied` if that shard is not reachable.
- `base_db()` / `level()` split the active shard; maintainer checks, OKF tags and prompts use the
  base DB.
- `tests/test_security_rules.py` forbids product code to touch `DATA_ROOT`, `shard_path` or the
  gate's private state, lets only `app.py` seal, and lets nothing in `src/` elevate.

## Users and audit

- `users.json` gains `"clearance": {"<db>": "<level>"}`; missing or invalid means normal. Only
  admins set it (Maintenance → Admin); being an admin grants no clearance.
- `src/audit.py` appends to `data/security_audit.jsonl` — who, when, action, target, shard, never
  content: `clearance_set`, `classified` (with the file's SHA-256), `source_moved`, and every
  `access_denied` in a signed-in session (`db_context.set_denial_listener`). Admins see it in
  Maintenance → Admin.
- When the grants shrink between reruns, the app drops content-bearing session state
  (`_CONTENT_KEYS`: chat, research, explorer selection, pending uploads).

## Reads

- **Wiki Explorer** and **Maintenance** show one level at a time: a level control (only when more
  than one level is reachable) binds that shard as active DB and scope for the rest of the rerun,
  so the existing single-DB views — tree, search, page reader, graph, overview, stats, log, lint,
  ontology — run unchanged on it. The graph cache key contains the shard id and is computed through
  the gate.
- **Wiki Chat** "Search in" lists every reachable shard of the user's DBs (default: all levels of
  the active DB); Fast and Deep mode already fan out over the scope.
- **Research** searches the normal level unless *Include classified levels* is ticked; the Quick
  agent's system prompt carries each shard's `index.md` with qualified links.

## Writes

- **Upload:** every file needs an explicit level (no default, at most the uploader's clearance);
  the batch is ingested one level at a time into its shard. Duplicates are checked only in levels
  the uploader can see, so a copy above them is stored silently; the audit log's hashes reveal it
  to admins.
- **High-water mark:** Research reports (`tools._submit_final_impl`, Deep `_save_report`), Chat
  "Save answer to wiki" and Research "Save to wiki" write to `write_target`. Saving from Chat and
  Research needs maintainer rights. Filed answers record `derived_from` (the pages and originals
  cited).
- **No web with classified scope (G4)**, in three layers: the Quick agent unbinds `tavily_search`
  and `fetch_webpage_content`, those tools refuse anyway, and Deep research (web-only) refuses. Once
  a classified run is in the Research history the choice is locked until *New research*, since
  follow-ups carry earlier answers.

## Moving a source

`wiki_engine.move_source(name, target, user)` (Maintenance → Delete source → *Move to another
classification level*) needs maintainer rights and clearance for both levels. It registers the file
in the target under its original dedup key, copies its live ontology rows, ingests it, and only then
removes it below. Moving down is a plain `delete_source`. Moving up runs `purge_upgraded`:

1. `delete_source` (raw, manifest, chunks, QA rows, pages it alone built).
2. Pages it shared with other sources are deleted and rebuilt by re-ingesting those sources.
3. Pages anywhere in the wiki that cite it or a removed page (`derived_from`, `sources`, including
   `comparisons/` reports) are deleted.
4. Ledger rows mentioning it or a removed page are erased, change rows redacted, history snapshots
   mentioning them deleted (`ontology_store.purge_mentions`) — the only exception to the
   append-only ledger.
5. Log lines naming it or a removed page are redacted; `DESCRIPTION.md` is dropped and rebuilt.
6. The report lists filed answers without `derived_from` created after the upload, for review.

## Threat model

- **Adversary:** a logged-in user below the required clearance — including admins and maintainers
  without it — acting through any UI feature, crafted questions, or tool arguments steered by
  prompt injection from normal-level documents (guessed names, forged `@` prefixes, traversal).
- **Guarantees:** G1 no path into a shard above clearance; G2 no automatic write-down; G3 no
  existence oracle; G4 no classified content to the web without an explicit opt-in.
- **Non-goals:** OS-level file access (the tree is plain text), encryption at rest, backups
  (including manual `wiki.bak*` copies), Ollama server-side logs, the tunnel transport, an admin
  granting themselves clearance (trusted, and audited), covert channels, content authorised users
  copy out, a run already in progress when clearance is revoked.

## Residual risks

- Filed answers created before `derived_from` existed cannot be traced; `purge_upgraded` lists
  them for manual review instead of deleting them.
- `resolve_contradiction` rewrites several selected pages with one LLM call; a page that does not
  cite the source can absorb its content that way and is not found by the purge.
- Purging deletes ontology history snapshots that mention the source, so earlier revisions of other
  facts are lost with them.

## Tests

| Suite | Checks |
|---|---|
| `test_confine` | Traversal and absolute names read as missing (was a live leak) |
| `test_classification`, `test_classification_gate`, `test_classification_shards` | Model, gate, fail-closed threads, base-DB concepts |
| `test_classification_leaks` | Canary tokens in every store of the higher shards appear in no output and no LLM prompt of the engine, tools, fast chat and both agents; positive twins; gate-bypass meta-test; graph cache order |
| `test_classification_writes`, `test_classification_move` | High-water writes, web off, provenance; move and a byte-level scan of the lower shard after a purge |
| `test_security_rules`, `test_audit`, `test_auth`, `test_app` | AST rules with violating inputs; audit; clearance; UI gating |
