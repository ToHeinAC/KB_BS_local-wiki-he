# Ontology

Per-database ontology: a validated schema of document classes and relations, plus an
append-only ledger of facts about the DB's sources. Rationale:
[_idea-onthology.md](_idea-onthology.md). Phases and what is still to come (GUI workbench,
detection at ingest, ontology-aware search, time): [_plan-ontology.md](_plan-ontology.md).
Phase status: [IMPLEMENTATION.md](../IMPLEMENTATION.md) §2.

**Built so far (plan Phases 1–8):** shared schema modules, per-DB binding, schema
validation, the fact ledger with projection, retraction on `delete_source`, the
Maintenance → Ontology workbench (view, export, hand-edit, import, history, restore,
proposals), detection at upload, stamping of source-summary pages, and the ontology
stage in every search (§Search), valid time (§Time), relations with binding paths and lint (§Relations), the tools to evolve it (§Evolution), and classes for wiki concept pages plus an `ai-tech` module for the KI database (§Pages). §-level validity is not built.

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
- `src/ontology_detect.py` is pure: `detect` (class, work id, aliases from a document
  head), `parse_proposal` (verifies an LLM answer), `classify_options`, `upload_rows`.
- `src/ontology_query.py` is pure: the search `View`, `resolve` → `QueryFrame`,
  `briefing`, `lookup`, `badge`, `audit` (§Search).
- `src/ontology_time.py` is pure: `time_intent`, `validity`, `current_expression`,
  `outdated_pages`, `validity_order` (§Time).
- `src/ontology_graph.py` is pure: `chain`, `binding_of`, `describe`, `lint`
  (§Relations); relation detection is `ontology_detect.detect_relations`.
- `src/ontology_evolution.py` is pure: `editor_tables` / `state_from_tables`,
  `cue_matches`, `reclassify_changes` / `reclassify_rows`, `parse_class_suggestion`;
  `src/ontology_export.py` is pure: `skos_turtle`, `facts_jsonld` (§Evolution).
- `src/ontology_ui.py` renders the Maintenance → Ontology section and the Upload
  review-table columns. `wiki_engine` holds the orchestration: `apply_ontology`,
  `record_source_ontology`, `finish_ontology_batch`, `decide_proposal`,
  `restamp_summaries` (each writes its Activity-log line).

## Schema modules

Shipped: `ai-tech` (plan Phase 8: AI/technology genres `research-paper`,
`research-report`, `talk-transcript`, `technical-guide`, `buying-advice`,
`organisation-profile` with cues, and page classes under `topic` — `ai-model`,
`technique`, `organisation`, `product`, `person`, `phenomenon` — with `applies_to: page`
and no cues; bound to KI only), `core` (domain-agnostic genres: `document` and its children `legal-instrument`,
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

## Detection at upload (`ontology_detect`)

Only for a DB with a valid ontology; otherwise the Upload page is unchanged.
- **Class:** every cue of every non-deprecated class is matched on the first 4000
  characters; the match that *ends* first wins, ties go to the deeper class, then the
  lower `rank`. Title-line cues are `^`-anchored and greedy, so "ends first" separates
  "Allgemeine Verwaltungsvorschrift zum …gesetz" from a statute.
- **Work** (legal instruments only): German law → `de-<abbr>-<year of Ausfertigung>` from
  the title's "(Name - ABBR)" or a standalone abbreviation line (aliases: both names);
  EU acts → `eu-dir-<year>-<n>-<org>` / `eu-reg-<year>-<n>`. Titles with an en dash
  ("… – TA Luft") yield no work id.
- **Review table:** columns *Class* (select), *Work* (text) and read-only *Other versions
  in this DB* (sources already filed under that work); the existing *effective as of*
  column becomes the `version_date` fact.
- **At ingest** (`record_source_ontology`, before `ingest_begin` so the summary page is
  stamped at creation): a value equal to the detected one is a `rule` fact with the
  matched line as evidence; a corrected one a `user` fact; invalid values are skipped
  with a warning. With no class, one small LLM call (`ONTOLOGY_CLASSIFY_PROMPT`,
  `FAST_MODEL`, leaf classes only) may add a **proposal**, kept only if its quote occurs
  verbatim in the head. After the batch, `finish_ontology_batch` records one `ingest`
  revision.
- **Proposals** appear under Ontology → *Proposals* (and as a count in the header).
  Confirm turns one into a `user` fact (revision `via: review`); reject only withdraws it.

**Measured** (`uv run python scripts/bench_ontology_detect.py`, gold set
`bench/fixture_ontology_detect.json`): class precision 8/8, work id 8/8 on the heads of
StrlSchG, StrlSchV, AtG, GG, BImSchG, TA Luft, Directive 2013/59/Euratom and Regulation
(EU) 2016/679; 0 of the 18 KI documents got a legal class. The set has no permits,
guidelines, technical rules or internal procedures yet. A live run of the LLM proposal
with gemma4:e4b on 6 KI documents gave 5 verified proposals (about 5 s each).

## Stamping

`wiki_engine._okf_apply` (every page write) calls `_ontology_stamp`: on a
`source-summary` page, the keys `class`, `work`, `version_date` are set from the source's
current facts and removed when a fact is gone (`ontology.stamp_meta`). An LLM rewrite
therefore cannot drop or invent them (finding F7). `restamp_summaries()` re-stamps all
summary pages after an import, restore, review or ingest batch. Without an ontology,
pages are left byte-identical.

## Search (plan Phase 4)

The check is enforced in code on every search path, not left to the model (plan §4.1).
A DB without an ontology, or a question that names no work or class, gets exactly
today's results (tested byte-for-byte).

- **View** (`ontology_store.view()`): per DB, built by `ontology_query.build_view` from
  the schema, the projected facts and the wiki pages' `sources:`; cached in memory and
  rebuilt when the binding, ledger, modules or wiki pages change.
- **Resolution** (`resolve`, no LLM): word-bounded, longest-first match of Work aliases
  and class labels (labels split on "/"; root classes and classes without sources are
  never matched). An ambiguous alias keeps all its works. Works' sources come newest
  version first; a class covers its descendants.
- **S1, ontology arm** (`retrieval._ontology_lists`, shared by `retrieval.search` and
  `wiki_engine.search_wiki`): one extra ranked list for RRF (`W_ONTOLOGY = 1.0`) —
  `lex_index.query(question + aliases, sources=<the works' sources>)`, then
  `lex_index.query(question, sources=<the classes' sources>)`. Wiki scope maps sources to
  the pages that cite them. Only lexical hits, so the lexical arm stays the citation
  truth; RRF bounds the arm's influence. Reranking (Deep paths) runs after fusion.
- **S2, briefing** (`retrieval.ontology_briefing`): before the first LLM call, Deep chat
  and Quick research append it to the system prompt (and yield an `ontology` step);
  Quick chat appends it to the synthesis system prompt. It holds only ids, source file
  names, dates and the user's matched words — no document-derived names (injection
  containment) — at most 3 works, ≤ 600 characters. Texts: `ONTOLOGY_BRIEFING_*` in
  `prompts.py`.
- **S3, `ontology_lookup(term)`**: works (aliases, versions, relations both ways) or
  classes (definition, members), else the nearest aliases. Offered only when a DB in the
  search scope has an ontology (`tools.with_ontology`); duplicates are short-circuited by
  `run_memory` like other searches.
- **Visible to users:** raw hits carry `ontology: class · work · date`; Explorer search
  shows "Ontology — “StrlSchV” → `de-strlschv-2018`; n source(s) favoured"; agent traces
  show the *Ontology frame*; *Why these sources* lists every frame of the run.

**Measured** (`uv run python scripts/eval_ontology_search.py --root <scratch dir>`):
a throwaway DB outside `data/` built from the full public texts of StrlSchG, StrlSchV,
AtG, GG, BImSchG and TA Luft (1,179 chunks; typed by Phase 3 detection, all six
correct), lexical + ontology arms only, 18 hand-labelled questions
(`bench/fixture_ontology_search.json`):

| Group | hit@1 off → on | MRR off → on |
|---|---|---|
| (a) names a law by abbreviation (10) | 80 % → 100 % | 0.86 → 1.00 |
| (b) names a document class (4) | 50 % → 100 % | 0.63 → 1.00 |
| (d) names nothing (4) | 75 % → 75 % (rankings identical) | 0.81 → 0.81 |

Limits: the metric is "right document", not "right passage"; the set is small and was
written by the implementer; no semantic arm or reranker in the run. Detection depends on
the title being at the top of the text — the first eval run, with site-menu text before
the title, typed four of six laws wrongly and found no works.

## Time (plan Phase 5)

Valid time (when a version holds in the world) is never compared with transaction time
(when the wiki wrote a page).
- **Validity is derived, not stored:** a *work* may carry `in_force_from` /
  `in_force_until`; each version (raw source) holds from its `version_date` until the
  next version's date within the work, bounded by the work's interval (a source's own
  `in_force_until` wins). `validity(view, source, as_of)` → `valid` / `superseded` /
  `not-yet` / `unknown`; unknown never demotes anything.
- **Point in time** (`time_intent`, code only): an explicit date (`2017-06-01`,
  `01.06.2017`, `1. Juni 2017`), or a year after a cue word (`im Jahr 2017`, `Stand
  2019`, `vor 2018` → end of the previous year); else today. "damals" / "alte Fassung" /
  "vor der Novelle" mean *past without a date*: nothing is reordered or rejected. A bare
  year is ignored (`Richtlinie 2013/59/Euratom` is not a date). Agents keep the
  question's point in time for their sub-queries (`run_memory.as_of`).
- **Resolution:** an alias naming several works keeps the one in force at the point in
  time ("StrlSchV" in 2017 → StrlSchV 2001; today → StrlSchV 2018).
- **Search:** after fusion and rerank, hits from versions not in force are moved to the
  end (never dropped, D3); in wiki scope, *outdated* pages are. Raw-hit badges, chat
  source captions, the briefing and `ontology_lookup(term, as_of)` say `in force` /
  `superseded` / `not yet in force`.
- **S4 answer check** (`tools._superseded_nudge`): a Deep-chat answer whose dated raw
  citations are all superseded, while the version in force is in the DB, is rejected
  once with the current file named; the second submit passes. Silent for questions about
  the past and without an ontology.
- **Merges** (finding F2): `_is_newer` compares only legal dates — the sources' version
  dates, else `effective as of` — and never `updated`/`created`; unknown means
  unresolved. When both sides are dated versions of the same work, a changed number is a
  *change note* under `## Changes` and confidence is not lowered; across works it stays a
  contradiction.
- **Outdated:** a page is *outdated* when its dated sources are all superseded
  (`wiki_engine.outdated_pages`) — separate from *stale* (not re-checked lately). It is a
  graph overlay (dashed ring), a health-panel list and a Lint section.

**Measured** (same eval as §Search, plus group (c) on a synthetic older StrlSchV
version): (c) asks about a point in time, hit@1 50 % → 100 %, MRR 0.75 → 1.00; (a) and
(b) stay at 100 %; one control moved (rank 4 → 3) only because superseded duplicates were
demoted.

## Relations (plan Phase 6)

Relations point to works (a law as such), or to `src:<file>` for a document without a work
(e.g. a permit). A member of a relation list may carry attributes:
`incorporates: [{to: din-6812, mode: static, edition: "2013-06", effect: mandatory}]`
(`mode`/`effect` from the schema's `attributes`, `edition` free and date-like). In the
ledger they sit in the row's `attributes`; confirming a proposal keeps them.

**Detection at upload** (`detect_relations`, code only, one finding per relation and
target, only for classes in the relation's domain):

| Relation | Formula (verbatim in the text) | Stored as |
|---|---|---|
| `transposes` | "… der Umsetzung der Richtlinie 2013/59/Euratom …" (first 20,000 chars) | fact (`rule`) |
| `based_on` | Eingangsformel "Auf Grund des … des Bundes-Immissionsschutzgesetzes … verordnet" naming a known work (genitive handled) | fact (`rule`) |
| `repeals` | "… außer Kraft" / "… wird aufgehoben" in a sentence naming a known work | proposal |
| `incorporates` | "DIN [EN] [ISO] n[-part]" / "KTA n", edition from ":2013-06" or "(Ausgabe März 2017)" → `static`, "in der jeweils geltenden Fassung" → `dynamic`; "gilt als erfüllt" → `presumption`, "einzuhalten/muss/…" → `mandatory`; ≤ 25 per document | proposal |

Evidence is the sentence or clause, verbatim (a period after a number or an abbreviation
does not end it). On the full texts of the eval corpus: the StrlSchV's transposition
clause; 19 static DIN references in TA Luft; one mandatory DIN EN 15376 reference in the
BImSchG. Limits: consolidated texts from gesetze-im-internet.de carry no Eingangsformel
(it is in the Federal Law Gazette version), and footnote notes such as "Umsetzung der
EARL 59/2013" are not recognised.

**Binding** (`binding_of(view, work, as_of)`, report §9): a standard is binding only
through an `incorporates` edge from a document that is itself binding — class `norm`
`true`, `individual` (a decision: binding for its addressee) or `internal` — and in force
at the point in time; `effect: guidance` never binds. Each path explains itself, e.g.
`din-6812 ◄ incorporates (static, mandatory) ─ permit.md (permit); edition 2013-06 pinned —
newer editions are not binding through this reference; binding for the addressee of this
decision`. Without such an edge: "Not binding by any reference in this database —
interpretive / state of the art only". `ontology_lookup` adds these paths and the
`based_on chain` (`chain`) to its answer; "DIN 6812" is looked up as `din-6812`.

**Lint** (`lint(view)`, deterministic; Ontology → *Lint*, and a section of Maintenance →
Lint): warnings for cycles in `based_on`/`replaces`/`is_part_of`/`repeals`/`amends`, a
`based_on` target whose class ranks lower (relation `lint: range_rank_not_lower`, e.g. an
ordinance based on an administrative regulation), `in_force_until` before
`in_force_from`, two versions with the same version date; infos for a pinned edition not
in the DB and for works referenced by n documents but missing. A rank only orders and
warns; it never decides a legal conflict.

**Graph:** relation edges are directed edges between source nodes (a work is drawn by its
version in force today), coloured apart and with arrowheads in the Galaxy and Pyramid
layouts. *Pyramid* puts documents in rows by their class `rank` (1 = top; unranked last)
and hides pages.

## Evolution (plan Phase 7)

Every change below goes through the one write path (`prepare_*` → preview → `apply`:
validated, maintainer-checked, revisioned, logged).

- **Editor** (Ontology → *Edit*): two tables — local classes (id, broader, labels, one-line
  definition, cues separated by ` || `, deprecated, replaced_by) and one row per document
  (class, work, version date). Fields the table does not show (rank, norm, notes,
  relations, aliases) are kept. The preview is the import preview; *Apply changes*
  records a `via: editor` revision. Deprecating a used class with a `replaced_by` moves
  its facts to the replacement.
- **Cue tester** (Ontology → *Cues*): "Matches n of m documents" with the matching line,
  on the same 4000-character heads detection reads; invalid or empty-matching patterns
  are refused.
- **Re-classify** (same view): a dry-run table of what the current cues would change —
  `update` / `withdraw` for facts code made, `kept-user` for decisions a person made,
  which are never touched. *Apply re-classify* retracts the outdated rule rows, asserts
  the new ones and records a `via: reclassify` revision. Covers `class` and `work`.
- **Class suggestions** (Ontology → *Proposals*): for an unclassified document a
  maintainer can ask the model (`ONTOLOGY_SUGGEST_CLASS_PROMPT`, one call) for a new class.
  Code rejects it unless the id is new and well-formed, the broader class exists, the
  definition is one line, both labels are given, and the cue compiles and matches the
  document. Valid suggestions wait in `data/<DB>/ontology/schema_proposals.jsonl`
  (append-only); *Accept* adds the class to the local extension and types the document
  (a `via: review` revision), *Reject* only closes it. A live run with gemma4:e4b on a KI
  document produced a valid but broad cue (`YouTube|World's Fair`) — test cues before
  accepting.
- **Standard exports** (Overview buttons, or
  `uv run python scripts/export_ontology.py --db <DB> --out <dir>`): the schema as a SKOS
  concept scheme in Turtle (`skos:broader`, de/en `skos:prefLabel`, `owl:deprecated` +
  `dct:isReplacedBy`, relations as `owl:ObjectProperty` mapped to ELI), the facts as
  JSON-LD with schema.org `Legislation` terms (`legislationTransposes`,
  `legislationDateVersion`, `exampleOfWork`, `legislationLegalForce`) and `eli:based_on`.
  Relation attributes are not exported. Both parse with rdflib (tested).

## Pages (plan Phase 8)

Classes with `applies_to: page` describe what a wiki concept/entity page is about; classes
with `applies_to: source` (the default) describe documents. Detection cues and the
document classification prompt only ever use document classes.
- **Proposals only:** Ontology → *Proposals* → *Classify concept pages* asks the model for
  up to 10 unclassified concept/entity pages (one call each, `ONTOLOGY_CLASSIFY_PROMPT`
  with the page classes). An answer is kept only as a proposal with a quote found
  verbatim in the page; pages with a class or an open proposal are skipped.
- **Facts** live under `page:<file>` (exchange file: `facts.pages`). A confirmed class is
  stamped as `class:` on the page (`_ontology_stamp` knows the file name at ingest and in
  `restamp_summaries`, which now covers every page).
- **Search:** a class word ("Verfahren", "KI-Modell") also lifts the pages of that class
  in wiki scope (the ontology arm), lexical hits only.

**KI (the only database this phase touched):** `ai-tech` bound (revision 3), re-classify
applied (revision 4: 14 rule facts; 3 earlier manual facts kept as user decisions), and
7 page-class proposals from 10 pages asked (gemma4:e4b, ~52 s) waiting for review.
Detection on KI's 18 documents (`bench/fixture_ontology_detect_KI.json`, names only —
texts stay in `data/KI`): precision 16/16, coverage 16/18 (two architecture explainers
have no genre words in their head) — **in-sample**, since the cues were written after
reading these documents.

## Deletion

`wiki_engine.delete_source(name)` calls `ontology_store.retract_subject("src:<name>")`:
every live row about the source gets a `system` retraction, the count is returned as
`ontology_rows`, and `record_change("delete_source")` records a revision. A DB without an
ontology gets no files.
