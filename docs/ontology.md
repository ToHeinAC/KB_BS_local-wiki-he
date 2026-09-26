# Ontology

Per-database ontology: a validated schema of document classes and relations, plus an
append-only ledger of facts about the DB's sources. Rationale:
[_idea-onthology.md](_idea-onthology.md). Phases and what is still to come (GUI workbench,
detection at ingest, ontology-aware search, time): [_plan-ontology.md](_plan-ontology.md).
Phase status: [IMPLEMENTATION.md](../IMPLEMENTATION.md) §2.

**Built so far (plan Phases 1–2):** shared schema modules, per-DB binding, schema
validation, the fact ledger with projection, retraction on `delete_source`, and the
Maintenance → Ontology workbench (view, export, hand-edit, import, history, restore).
Nothing reads the ontology at ingest or search time yet, so a DB with or without one
answers searches the same.

## Storage

| Path | Owner | Content |
|---|---|---|
| `ontology/*.yaml` | git (edit via PR) | Shared schema modules; the file stem is the module id |
| `data/<DB>/ontology.yaml` | DB maintainers | Binding: which modules the DB uses, plus an optional `local` extension |
| `data/<DB>/ontology/assertions.jsonl` | code | Fact ledger, append-only |
| `data/<DB>/ontology/changes.jsonl` | code | One row per revision, append-only |
| `data/<DB>/ontology/history/<seq>-<hash>.yaml` | code | Full snapshot (exchange file) per revision |
| `data/<DB>/ontology/.lock` | code | `flock` for ledger writes |

- A DB has an ontology exactly when `data/<DB>/ontology.yaml` exists
  (`ontology_store.exists()`). Reading never creates files.
- `data/` has no backup (AGENTS.md §5.5); `data/<DB>/ontology/` must be in any future backup.

## Modules

- `src/ontology.py` is pure (no I/O): schema dataclasses (`Schema`, `ClassDef`,
  `RelationDef`), `parse_yaml`, `validate_module`, `build_schema`, `read_binding`, and the
  ledger helpers `assertion`, `retraction`, `live_rows`, `project`.
- `src/ontology_bundle.py` is pure: the exchange file (`render`, `parse`), `canonical` /
  `revision_hash`, `diff` / `summarize`, `merge3`, `bump`, `validate_facts`, `plan_import`,
  `fact_rows`, `log_line`.
- `src/ontology_store.py` is the only I/O: schema (`load`, `shared_modules`), ledger
  (`read_rows`, `append_rows`, `retract_subject`), state and revisions (`current_state`,
  `current_revision`, `history`, `last_change`, `snapshot_text`, `export_text`), plans
  (`prepare_import`, `prepare_state`, `prepare_restore`) and writes (`apply`,
  `record_change`).
- `src/ontology_ui.py` renders the Maintenance → Ontology section;
  `wiki_engine.apply_ontology` applies a plan and writes the Activity-log line.

## Schema modules

Shipped: `core` (domain-agnostic genres: `document` and its children `legal-instrument`,
`standard`, `guidance`, `decision`, `procedure`, `report`, `dataset`, `correspondence`,
`contract`; relations `is_part_of`, `cites`, `replaces`) and `legal-de` (the German/EU legal
hierarchy, requires `core@^1`; classes with `rank`, `norm` and provisional `cues`; relations
`based_on`, `transposes`, `amends`, `repeals`, `applies`, `incorporates`).

```yaml
id: legal-de              # lowercase id, equals the file stem
version: 0.1.0            # SemVer: patch = text/cues, minor = new ids, major = re-parenting/removals
requires: ["core@^1"]     # same major, at least this version; must be bound too
classes:
  ordinance:
    broader: legal-instrument          # SKOS-like; no cycles
    rank: 4                            # ordering/layout only, never decides conflicts
    norm: true                         # true | false | internal | individual
    labels: {en: Ordinance, de: Rechtsverordnung}   # both languages required
    definition: Rechtsverordnung issued on the basis of a statutory authorisation  # one line
    cues: ['\bverordnet\b']            # regexes on title/head (used from plan Phase 3)
relations:
  based_on: {domain: legal-instrument, range: legal-instrument, inverse: basis_for,
             target: work, eli: based_on}
```

Optional keys: classes `applies_to` (`source`|`page`), relations `transitive`,
`attributes` (name → allowed values), `labels`, `definition`, `dct`, `lint`; both
`deprecated` + `replaced_by`, `note`, `change_note`. Ids are never deleted: deprecate them
with a `replaced_by`.

### Meta-rules (`build_schema`)

A schema is accepted only when all hold; otherwise every error is returned and the
schema is `None`:
- YAML parses, with no duplicate keys (PyYAML would silently keep the last one).
- No unknown keys (catches typos in hand edits); ids are lowercase `[a-z][a-z0-9_-]*`.
- `version` is `MAJOR.MINOR.PATCH`; every `requires` is bound and satisfied.
- A class or relation id is defined in one module only.
- `broader` exists and has no cycle; relation `domain`/`range` name existing classes; if
  a relation's `inverse` is itself a relation, that one's `inverse` points back.
- Classes have `labels` in `de` and `en` and a one-line `definition` (≤ 200 chars).
- Cues compile, are ≤ 200 chars and do not match the empty string.
- A deprecated id has a `replaced_by` that exists.

## Binding (`data/<DB>/ontology.yaml`)

```yaml
modules: [core, legal-de]
local:                      # optional, DB-specific; validated like a module with id `local`
  version: 0.1.0
  classes:
    radon-measurement-report: {broader: report, labels: {en: …, de: …}, definition: …}
```

`ontology_store.load()` returns `(None, [])` without a binding, `(None, errors)` when the
binding or any module is broken (unknown module, id mismatch with the file name, any
meta-rule), and `(schema, [])` otherwise. It never raises on content errors.

## Fact ledger

One JSON object per line. Rows are never edited or removed.

```json
{"id": "a-000812", "subject": "src:StrlSchV_Stand_2025.md", "predicate": "class",
 "object": "ordinance", "by": "rule", "user": null, "evidence": "…verordnet…",
 "status": "confirmed", "negated": false, "valid_from": null, "valid_until": null,
 "ontology": "legal-de@0.1.0", "retracts": null, "recorded_at": "2026-09-26T10:02:11Z"}
```

- Subjects start with `src:` (a raw source file), `work:` or `page:`.
- `by`: `user`, `rule`, `llm`; `system` only for retractions (e.g. `delete_source`).
- `status`: `confirmed` or `proposed`; proposals are never projected.
- A retraction is a new row with `retracts: <id>`.
- `append_rows` assigns sequential ids and `recorded_at` under the lock, and repairs a torn
  last line (crash mid-write) before appending. `read_rows` skips unreadable lines.

### Projection (`project(rows, multi)`)

Current confirmed facts per subject: `{subject: {predicate: value}}`.
- Per fact, the highest-precedence actor wins (**user > rule > llm**); among equals the
  later row wins. So user decisions are sticky against re-classification.
- Single-valued predicates (e.g. `class`, `work`): a user row with `object: null` unsets
  the fact and keeps blocking rule/llm rows.
- Multi-valued predicates (`Schema.multi_valued()`: every relation, plus `aliases`) hold a
  sorted list; each member is its own fact, and a user row with `negated: true` removes
  that member for good.

## Workbench (Maintenance → Ontology)

A segmented control (not `st.tabs`, see [ui.md](ui.md)) switches *Overview · Classes ·
Facts · History · Import*. Above it: the revision (`seq` + content hash), the **last
change** (newest `create`/`import`/`editor`/`restore` row: time, user, how, file, counts),
the **last automatic change** (newest row written by code, e.g. `delete_source`), and
*Export current (YAML)*. A DB without an ontology shows "No ontology for this database."
plus, for maintainers, *Create ontology* (module picker) and the import.

| Action | Reader | Maintainer |
|---|---|---|
| View, export current or past revision | yes | yes |
| Create, import, restore | — | yes (checked again in `ontology_store.apply`) |
| Change shared modules | — | — (git only) |

### Exchange file

One YAML file per DB: `format: localwiki-ontology/1`, `db`, `base_revision`
(`<seq>-<hash>`), `exported_at`/`_by`, `schema` (the binding: `modules` + `local`),
`facts` (`sources` / `works` / `pages` → `{key: {predicate: value}}`; relations and
`aliases` are lists) and a read-only `reference` (the bound shared modules). No YAML
anchors/aliases; files over 2 MB are refused. Comments are not kept (use `note:`).
Example: [_plan-ontology.md](_plan-ontology.md) §3.2.

**What counts as a change.** `canonical()` keeps only `schema.modules`, `schema.local`
without `version`, and `facts`; strips strings, turns dates into ISO strings, treats every
list of scalars as a set (sorted, de-duplicated), and drops empty values, `null` and
`false`. The revision hash is the first 12 hex chars of SHA-256 over its sorted JSON.
Formatting, comments, key order, quoting, duplicates and export metadata never change it.

### Import pipeline (`prepare_import` → preview → `apply`)

1. Parse: size, no aliases, known `format`, same `db` unless *This file comes from another
   database* is ticked.
2. Base: the snapshot whose hash matches `base_revision`; without one the merge is 2-way,
   with a warning that newer edits may be undone.
3. `merge3` on leaf paths: your edits relative to the base are applied onto the current
   state, so changes made since your export (e.g. by code) survive. A leaf both sides
   changed differently is a **conflict**; the UI offers *Keep current* (default) or
   *Use mine* per conflict.
4. Unchanged hash → "Identical to revision N — nothing changed": nothing is written or
   logged.
5. Validate: the schema meta-rules; facts (known class, known source, `YYYY-MM-DD` dates,
   `in_force` ∈ in-force / not-in-force / partially-in-force, lowercase work ids, lists for
   relations and `aliases`, no unknown predicate or section); a relation target that is not
   a known work is only a warning. Facts on a deprecated class move to its `replaced_by`.
   Removing a local class/relation that any ledger row ever used is refused (deprecate it).
6. Preview: counts per area, the new `local.version` (patch: text/cues; minor: new ids;
   major: removed ids or re-parenting/domain/range/inverse/target changes) and a
   leaf-level diff table.
7. `apply` (maintainers, under the lock): refuses if the content changed since the
   preview (`StaleRevisionError`); writes the binding atomically when the schema changed;
   turns fact edits into `user` ledger rows (a removed value is a `null` or `negated`
   row, so it stays removed); records the revision.

*Restore* of a past revision runs the same pipeline with the snapshot as the new content,
so it becomes a new revision; history is never rewritten.

### Revisions and logging

A revision is recorded only when the content hash moves: a snapshot
`history/<seq>-<hash>.yaml` and a `changes.jsonl` row with `seq`, `hash`, `parent`, `at`,
`user`, `via` (`create`/`import`/`restore` by people; `delete_source` and later `ingest`
by code), `file`, `file_sha256`, `summary` (entity counts), `local_version` and the first
200 leaf changes. Each also adds an Activity-log line, e.g. `Ontology changed: rev 2 by
T. Hein via import (ontology-KI-edited.yaml): schema +1 ~0 −0, facts +2 ~0 −0`.
Automatic writers call `record_change(via)`, which diffs against the last snapshot. If
the content moved without a recorded revision, the header says so.

## Deletion

`wiki_engine.delete_source(name)` calls `ontology_store.retract_subject("src:<name>")`:
every live row about the source gets a `system` retraction, the count is returned as
`ontology_rows`, and `record_change("delete_source")` records a revision. A DB without an
ontology gets no files.
