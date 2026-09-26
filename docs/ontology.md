# Ontology

Per-database ontology: a validated schema of document classes and relations, plus an
append-only ledger of facts about the DB's sources. Rationale:
[_idea-onthology.md](_idea-onthology.md). Phases and what is still to come (GUI workbench,
detection at ingest, ontology-aware search, time): [_plan-ontology.md](_plan-ontology.md).
Phase status: [IMPLEMENTATION.md](../IMPLEMENTATION.md) §2.

**Built so far (plan Phase 1):** shared schema modules, per-DB binding, schema validation,
the fact ledger with projection, and retraction on `delete_source`. Nothing reads the
ontology at ingest or search time yet, so a DB with or without one behaves the same.

## Storage

| Path | Owner | Content |
|---|---|---|
| `ontology/*.yaml` | git (edit via PR) | Shared schema modules; the file stem is the module id |
| `data/<DB>/ontology.yaml` | DB maintainers | Binding: which modules the DB uses, plus an optional `local` extension |
| `data/<DB>/ontology/assertions.jsonl` | code | Fact ledger, append-only |
| `data/<DB>/ontology/.lock` | code | `flock` for ledger writes |

- A DB has an ontology exactly when `data/<DB>/ontology.yaml` exists
  (`ontology_store.exists()`). Reading never creates files.
- `data/` has no backup (AGENTS.md §5.5); `data/<DB>/ontology/` must be in any future backup.

## Modules

- `src/ontology.py` is pure (no I/O): schema dataclasses (`Schema`, `ClassDef`,
  `RelationDef`), `parse_yaml`, `validate_module`, `build_schema`, `read_binding`, and the
  ledger helpers `assertion`, `retraction`, `live_rows`, `project`.
- `src/ontology_store.py` is the only I/O: `exists`, `available_modules`, `load`,
  `read_rows`, `append_rows`, `retract_subject`.

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

## Deletion

`wiki_engine.delete_source(name)` calls `ontology_store.retract_subject("src:<name>")`:
every live row about the source gets a `system` retraction, and the count is returned as
`ontology_rows` and written to `log.md`. A DB without a ledger gets no files.
