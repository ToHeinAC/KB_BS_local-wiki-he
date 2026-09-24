# Ontology for LocalWiki: Concept Report

**Status:** proposal, nothing implemented · **Date:** 2026-09-24 · **Checked against:** commit `67f35f3`
**Input:** the first-principles concept comparison (Concepts A/B/C, recommending *B: SKOS-Lite overlay*), checked against the current code.
**Questions answered:** (1) How do we build an ontology that users can add to and update, and that serves present and future databases? (2) Should the agentic system update ontologies, for example when a newer version of a document arrives? (3) How do ontologies handle time?

---

## 0. The answers in short

1. **User-editable ontologies.** Split the ontology into three layers with different owners:
   - **Schema modules** (`ontology/*.yaml`): git-tracked, validated by code, semantically versioned. There is one domain-agnostic `core` module plus domain modules such as `legal-de`. Each database picks its modules.
   - **Assertions**: an append-only, bitemporal ledger per DB (`data/<DB>/ontology/assertions.jsonl`). Each row records who made it (`rule` / `llm` / `user`) and the evidence.
   - **Derived views**: page frontmatter stamped by code (the same pattern as OKF) and a rebuildable `index/ontology.json`.

   Users edit the schema in a Maintenance → Ontology section (admins) and edit assertions inline (maintainers). Every save is validated, shows an impact preview, bumps the version and is logged. User decisions are sticky, so no agent or re-classification ever overwrites them.
2. **Agentic updates.** The agent may update **facts** but not the **schema**. When a newer version of a known document arrives, code closes the old version's validity interval and opens the new one: automatically, append-only and reversibly, and never by deleting. The LLM only *proposes* classes and relations. A proposal becomes active after code has verified its evidence as a verbatim quote, or after a user confirms it. Changes to the schema (new classes, relations or cues) are only ever *proposals* that an admin approves.
3. **Time.** OWL/RDF have no native notion of time. Everything is monotonic, so facts never "stop" being true, and time must be modelled explicitly. There are three separate problems:
   - **valid time**: when a norm or fact holds in the world;
   - **transaction time**: when the wiki learned it;
   - **schema evolution**: the ontology itself changes.

   The legal standards solve the first problem the same way: a *Work* (the law as such) has dated *Expressions* (versions), each carrying entry-into-force, applicability and end dates (ELI / FRBR, Akoma Ntoso). Temporal agent memories such as Graphiti use bitemporal edges that are *invalidated, never deleted*. LocalWiki should adopt exactly this: Work/Expression on sources, validity intervals in the ledger, and "as of" resolution at query time.

**Recommendation.** Keep Concept B's spirit (lightweight, SKOS-like, ELI terms, code-validated, no OWL/triple store), but make five corrections (§2). Build it as the three-layer design above, in five verifiable phases (§10). The biggest immediate win is **time, not taxonomy**: today the wiki cannot tell a repealed version from a current one, and its date comparison is subtly wrong (finding F2).

---

## 1. Starting point: what the code does today (verified)

| # | Finding | Evidence | Consequence |
|---|---|---|---|
| F1 | There is no semantic typing. `type` is a structural 5-value enum that the engine keys on: routing merges same-type pages only, the typed graph drops every other type, and the Explorer groups by it. | `_route_page` wiki_engine.py:353, `build_typed_graph` :2076, `_TYPE_GROUPS` :1807 | Ontology classes need a **separate key**. Overloading `type` (as Concepts A/B propose) would silently remove pages from the graph and change merge routing. |
| F2 | **Valid time and transaction time are conflated.** `_is_newer` compares `effective as of` but falls back to `updated`/`created`, which are wiki write dates. Tested on this machine: a contribution from a 2021 amendment is judged *not newer* than a page merged on 2026-09-01. An undated upload, possibly of older text, is judged *newer*. | `_is_newer` wiki_engine.py:427 | The contradiction note ("now X per the newer source") can point the wrong way. Comparisons must use the legal dates of **sources** only. |
| F3 | "Stale" is a transaction-time TTL (`updated` + `expires_after_days`). A page merged yesterday from a repealed law counts as fresh. An unchanged page based on valid law turns stale after 365 days. | `is_page_stale` :122 | *Stale* (not re-checked lately) and *outdated* (built on superseded law) are different signals, and the second one needs validity data. |
| F4 | Versions coexist without any link between them. A new version under a new filename is just another source. Under the same filename, `register_file` stores `name_<sha8>.md`. Both stay in BM25 and vectors with equal weight, and concept pages merge the facts of both. This is the "source-version awareness" gap that openissues.md defers. | dedup.py:61 | There is no Work with successive versions, so retrieval can cite repealed text as current. |
| F5 | Some precursors already exist. `effective as of` is regex-detected, corrected by the user in the upload review table, and drives oldest-first batch ingest. `part of` is shared metadata that becomes an OKF tag. | metadata_extract.py; app.py:1015, :1055; okf.py:93 | The **upload review table** is the cheapest point to put a human in the loop, because the user already looks at it for every file. |
| F6 | The graph already has typed nodes (`page`, `source::…`) and typed edges (`related-to`, `derived-from`). | `build_typed_graph` :2033 | Document relations (`based_on`, `transposes`, …) are edges between the existing `source::` nodes, so no new node kind is needed. |
| F7 | Frontmatter can be lost when the LLM rewrites a page. `resolve_contradiction` writes whatever frontmatter the LLM echoes back, plus `lang` and the OKF stamping. Any key the LLM drops is lost. | :2163 | Ontology facts must be **re-stamped by code** on every write, from a store the LLM never rewrites. This is the same reasoning as for OKF. |
| F8 | `evaluate_condition` checks facts that the **LLM supplies** against a condition tree. It never reads the wiki. | tools.py:756 | It is the wrong engine for "is rule X binding?". That question is a graph walk over confirmed relations, done in code. |
| F9 | `data/KI`, the only DB coding tools may touch, does not exist on this machine. | `ls data/` | The prototype needs a fresh KI DB seeded with public texts (§10, Phase 0). |

---

## 2. Review of the input concept (B: "SKOS-Lite overlay")

**Keep:**
- Reject OWL-DL, reasoners and a triple store: they add infrastructure without adding value in a local, single-owner, Markdown-first system.
- Use SKOS semantics for navigation (`broader` is not `subClassOf`, so it carries no entailment obligations).
- Use the **ELI vocabulary for names**. I verified ELI ontology v1.4, which has:
  - FRBR classes `Work` / `Expression` / `Manifestation` plus `LegalResource` / `LegalExpression` / `LegalResourceSubdivision`;
  - relations `based_on`, `transposes`, `amends`, `repeals`, `consolidates`, `applies`, `cites`, `implements`, `ensures_implementation_of`, `is_part_of`;
  - dates `first_date_entry_in_force`, `date_applicability`, `date_no_longer_in_force`;
  - `in_force` with the values `inForce` / `notInForce` / `partiallyInForce`.
- Let the LLM propose and have code validate against controlled lists.
- Keep norm traversal **directed** and separate from the undirected `linked_pages()`.
- Keep RDF/JSON-LD **export** as a later adapter only.

**Correct:**
1. **Don't overload `type`** (F1). Use a separate `class:` key; OKF allows unknown keys.
2. **Norm classes belong to documents, not to concept pages.** A concept page such as *Dosisgrenzwerte* merges facts from StrlSchG, StrlSchV and the Directive, so it has no rank. A class like `ordinance` describes a *source*, and therefore its 1:1 `summary-<doc>.md` page.
3. **Rank is not a total order and is not a truth.**
   - EU law takes precedence *in application* (Anwendungsvorrang), not in validity, and the BVerfG keeps identity and ultra-vires review. "EU above GG" is not a clean order.
   - Land law (Art. 31 GG) is a second axis.
   - A permit is a concrete-individual act, not a lower level of abstract norms.
   - Technical rules are not legal norms at all.

   So `rank` should be a **class attribute** used for ordering, pyramid layout and lint heuristics. It must never be used to decide conflicts.
4. **"Binding" is not a node attribute.** It is:
   - relational: a DIN standard binds *the addressee of permit X*, not everyone;
   - contextual;
   - temporal: a *static* reference pins an edition ("DIN 6812:2013-06"), while a *dynamic* one ("in der jeweils geltenden Fassung") follows new editions.

   Store `incorporates` edges with `mode` / `effect` / `scope`, and **derive** the binding status together with its explanation chain. Constitutional doctrine limits dynamic references to privately set standards, so most binding references are static or go through "Stand der Technik" clauses. That is a domain call, but the model must be able to store `mode`.
5. **Relations must target Works, not page slugs.** The target may not have been uploaded yet (future files), and it has versions. The version is resolved at query time.
6. **Missing entirely: time, the ontology's own lifecycle, agentic update rules, and reuse across DBs.** Those are exactly your three questions. The 8-level pyramid is also specific to Strahlenschutz, while Investing, Labor, Fusion and other DBs need a domain-agnostic core.
7. Minor: `broader`/`narrower` per *document* (as in Concept B) mixes schema and instance. The hierarchy belongs to classes.

---

## 3. Design principles (carried over from the project's own rules)

| # | Principle | Precedent in this repo |
|---|---|---|
| P1 | **The LLM proposes and code decides.** Enumerations are validated, evidence is checked verbatim, and anything unknown becomes a proposal, never a fact. | OKF stamping, `lang.py`, `_route_page` |
| P2 | **Schema ≠ facts.** The TBox (classes, relations) and the ABox (this document is an ordinance) have different owners and different update rules. | — |
| P3 | **Relations point to Works, and versions are resolved at query time.** Static references are the only exception: they pin an Expression. | — |
| P4 | **Never delete, close intervals instead.** Supersession sets an end date, and a retraction is a new row. | Graphiti edge invalidation |
| P5 | **Valid time ≠ transaction time.** Never compare across the two. | fixes F2 |
| P6 | **Derived views are caches** and can be rebuilt from ledger + sources. | `lex_index`, `embed_index` |
| P7 | **Fail open.** A DB without an ontology behaves exactly as today. | semantic arm, reranker |
| P8 | **Safe for small models:** at most ~12 options per LLM decision, one-line definitions, strict JSON, evidence as a verbatim quote. | `page_lang` verification |

---

## 4. Architecture: three layers

```
ontology/core.yaml, ontology/legal-de.yaml, …   (schema, git-tracked, semver)
data/<DB>/ontology.yaml                          (which modules this DB uses + small local extensions)
          │  load + validate (code)
          ▼
┌──────────────────────── src/ontology.py  (no LLM, no LangChain) ────────────────────────┐
│ detect(): cue regexes on title/head ─┐                                                   │
│ LLM proposal (called from wiki_engine; prompt in prompts.py) ─► verify evidence quote ──┤
│                                       ▼                                                  │
│      data/<DB>/ontology/assertions.jsonl   append-only · bitemporal · by rule|llm|user   │
│            │ project()                                   │ build()                       │
└────────────┼─────────────────────────────────────────────┼───────────────────────────────┘
             ▼                                             ▼
  summary-*.md frontmatter                        index/ontology.json  (derived cache:
  (code-stamped in _okf_apply, like OKF)          works, versions, validity, typed edges)
                                                           │
     retrieval (as_of demotion) · agents (citation badges) · contradiction check · graph (typed edges,
     pyramid) · lint · Explorer badges · optional SKOS / ELI JSON-LD export
```

### 4.1 Schema modules (SKOS-like YAML)

A class has these parts:
- a stable id;
- `labels` (de+en; pages are DE/EN);
- `definition`, a single line that is also what the LLM sees;
- `broader`;
- optional `rank` and `norm`;
- `cues`, which are regexes on title and head. Cues are the deterministic detectors, the equivalent of SKOS `altLabel` put to work.

A relation has these parts:
- `domain` / `range`;
- `inverse`;
- `target: work|expression`;
- an `eli:` mapping;
- optional typed attributes.

```yaml
# ontology/core.yaml — domain-agnostic document genres, used by every DB
id: core
version: 1.0.0
classes:
  document:         {labels: {en: Document, de: Dokument}, applies_to: source}
  legal-instrument: {broader: document, labels: {en: Legal instrument, de: Rechtsakt}}
  standard:         {broader: document, labels: {en: Technical standard, de: Technische Regel/Norm}}
  guidance:         {broader: document, labels: {en: Guidance, de: Leitfaden/Empfehlung}}
  decision:         {broader: document, labels: {en: Decision/permit, de: Bescheid/Genehmigung}}
  procedure:        {broader: document, labels: {en: Internal procedure, de: Betriebliche Regelung/SOP}}
  report:           {broader: document, labels: {en: Report/study, de: Bericht/Studie}}
  dataset:          {broader: document, labels: {en: Data/measurements, de: Daten/Messwerte}}
  correspondence:   {broader: document, labels: {en: Correspondence/minutes, de: Schriftverkehr/Protokoll}}
  contract:         {broader: document, labels: {en: Contract, de: Vertrag}}
relations:
  is_part_of: {domain: document, range: document, inverse: has_part,    target: work, eli: is_part_of, transitive: true}
  cites:      {domain: document, range: document, inverse: cited_by,    target: work, eli: cites}
  replaces:   {domain: document, range: document, inverse: replaced_by, target: work, dct: replaces}
```

```yaml
# ontology/legal-de.yaml — the Strahlenschutz pyramid (excerpt; full table in §9)
id: legal-de
version: 0.1.0
requires: ["core@^1"]
classes:
  eu-directive:
    broader: legal-instrument
    rank: 1
    norm: true
    definition: "EU/Euratom directive; binds member states, needs national transposition"
    cues: ['Richtlinie\s+\d{4}/\d+/(EU|EG|Euratom)']
  ordinance:
    broader: legal-instrument
    rank: 4
    norm: true
    definition: "Rechtsverordnung issued on the basis of a statutory authorisation"
    cues: ['\bverordnet\b', '^[^\n]*Verordnung\b']
relations:
  based_on:     {domain: legal-instrument, range: legal-instrument, inverse: basis_for,     target: work, eli: based_on, lint: range_rank_not_lower}
  transposes:   {domain: legal-instrument, range: eu-directive,     inverse: transposed_by, target: work, eli: transposes}
  incorporates:
    domain: [legal-instrument, decision, procedure]
    range: [standard, guidance]
    inverse: incorporated_by
    target: work            # overridden to the pinned expression when mode = static
    attributes: {mode: [static, dynamic], effect: [mandatory, presumption, guidance]}
```

Two files serve **present and future DBs**. The core carries the genres every corpus has. Domain modules add depth, for example `legal-de` for Strahlenschutz / NORM / CO2-Zertifikate_BECV / Abluftreinigung, and later perhaps `finance` or `lab-qm`. Because class ids are shared, multi-DB chat can filter uniformly.

### 4.2 Per-DB binding

```yaml
# data/<DB>/ontology.yaml
modules: [core, legal-de]
local:                      # optional, DB-specific; promote to a shared module once it proves useful
  classes:
    radon-measurement-report: {broader: report, cues: ['Radonmessung']}
```

### 4.3 Assertions ledger: why not only frontmatter?

With frontmatter alone, ontology values would sit next to `title`/`sources`. That fails four requirements:
- **LLM rewrites can drop keys (F7).**
- User decisions would not be sticky across merge, consolidate or re-ingest.
- There is no place for *proposals* that are not yet facts.
- There is no history, so the wiki cannot answer "what did it assert in March?".

An append-only JSONL ledger costs little and solves all four:

```json
{"id":"a-000812","subject":"src:StrlSchV_Stand_2025.md","predicate":"work","object":"de-strlschv-2018",
 "by":"rule","evidence":"Strahlenschutzverordnung vom 29. November 2018","status":"confirmed",
 "valid_from":null,"valid_until":null,"recorded_at":"2026-09-24T10:02:11Z","retracts":null,
 "ontology":"legal-de@0.1.0","user":null}
```

- **Subjects:** `src:<file>` (an Expression/Manifestation), `work:<id>`, and later `page:<file>`.
- **Operations:** *assert* and *retract*. A retraction is a new row with `retracts: <id>`. Rows are never edited.
- **Projection** picks, for each subject and predicate, the latest non-retracted confirmed row, with **precedence user > rule > llm**. `proposed` rows are left out of the projection and show up in the review panel instead.
- **Bitemporal:** `valid_from/until` holds legal validity and `recorded_at` plus retractions hold transaction time.
- **Deletion:** `delete_source` must also retract every row about that source. This extends the AGENTS.md "cascade across every store" rule.
- **Backup:** `data/` has no backup (AGENTS §5.5), and the ledger inherits that risk. Append-only writes limit corruption. Include `data/<DB>/ontology/` in any future backup.

### 4.4 Projection into pages

`wiki_engine._okf_apply` calls `ontology.stamp(content)`. This means every writer (ingest, merge, insight, contradiction resolution, research report) re-stamps the same keys from the ledger. It is the exact pattern OKF uses, so an LLM can never break them. Example for a source-summary:

```yaml
class: ordinance
work: de-strlschv-2018
version_date: "2025-…"          # "Fassung vom" / "Stand" (identifies the Expression)
in_force_from: "2018-12-31"     # ELI first_date_entry_in_force
in_force_until: null            # ELI date_no_longer_in_force
in_force: in-force              # ELI in_force (derived from dates + as_of; "partial" only when asserted)
based_on: [de-strlschg-2017]    # Work ids; resolved to versions at query time
transposes: [eu-dir-2013-59-euratom]
```

`okf.tags` can also carry the class id (deterministic), and a code-generated read-only `ontology.md` in the bundle can orient humans and LLMs, in the same way as `DESCRIPTION.md`. The ontology itself should **not** live as wiki pages: it would pass through LLM merge and translation paths it must never touch.

### 4.5 `src/ontology.py`: API sketch (one module, no LLM)

```python
load(db=None) -> Ontology                      # modules + DB binding, validated, cached on mtimes
validate_module(text) -> list[str]             # meta-rules, §5.4
detect(text, filename) -> list[Proposal]       # cues → class, work id, dates, relation formulas (§7.3)
assert_(subject, predicate, obj, *, by, evidence, status="confirmed", valid_from=None, valid_until=None) -> str
retract(assertion_id, *, by, reason) -> str
project(subject) -> dict                       # confirmed current values → frontmatter keys
stamp(content, source) -> str                  # called from wiki_engine._okf_apply
build() -> dict                                # index/ontology.json (derived cache)
current_expression(work, as_of=None) -> str | None
validity(source, as_of=None) -> str            # "valid" | "superseded" | "not-yet" | "unknown"
chain(work, relation, as_of=None) -> list      # directed walk, e.g. based_on*
binding_of(work, context=None, as_of=None) -> list[list]   # explanation paths, §9
lint() -> list[str]                            # consistency, §8
```

The LLM classification call belongs in `wiki_engine` (like every other ingest LLM call), and its prompt goes in `prompts.py` (`ONTOLOGY_CLASSIFY_PROMPT`). LangChain stays out, since this is not the agent layer.

---

## 5. Question 1: ontologies that users can add and update

### 5.1 Who edits what (mapped onto `auth.py`)

| Object | Admin | DB maintainer | Reader | Agent |
|---|---|---|---|---|
| Shared modules `ontology/*.yaml` | edit | propose | — | propose |
| DB binding / local extension | edit | edit | — | propose |
| Assertions in a DB | confirm/override | confirm/override | — | assert (rule) / propose (LLM) |

### 5.2 Editing surfaces

1. **YAML in the repo.** For power users: reviewed in git and checkable by Codex/Claude like any other code.
2. **Maintenance → Ontology** (a new sidebar section next to *Page language*):
   - class and relation tables (`st.data_editor`);
   - a **cue tester** ("this regex matches 14 of 212 sources: …");
   - module selection per DB;
   - the proposal queue;
   - re-classify with dry-run/apply;
   - the lint report.
3. **Inline edits.** An assertion (class / work / validity / relation) can be edited on a source page in the Explorer, and in the upload review table (§7.3). Each edit becomes a ledger row with `by: user`.

### 5.3 Save pipeline for schema changes

**Validate** (§5.4) → **impact preview** (dry-run re-classify: "7 sources change class, 2 user assertions now point at a deprecated class") → **version bump** (below) → **backup** of the old file → **write** → **`log.md` entry** → optional **re-classify apply**. This is the same shape as `normalize_pages(dry_run)` and `okf_migrate.py`.

### 5.4 Meta-validation (the rules the schema itself must obey)

- The YAML parses.
- Ids are unique within a module and namespaced across modules.
- `broader` targets exist, and there are **no cycles**.
- Relation `domain`/`range` refer to existing classes, and `inverse` pairs are symmetric.
- Every deprecated id names an existing `replaced_by`.
- Labels exist in de+en. `definition` is at most one line (it goes into small-model prompts).
- Every cue compiles as a regex and does not match the empty string.
- `requires` resolves, and the version was bumped if the content changed.

The save is refused if any rule fails.

### 5.5 Versioning and evolution (the TBox side of "time")

- **SemVer per module:**
  - *patch*: labels, definitions, cues;
  - *minor*: additive classes or relations;
  - *major*: re-parenting, changed relation semantics, removals.
- **Never delete an id.** Mark it `deprecated: true` with `replaced_by: <id>`, following OWL's `owl:deprecated` and Dublin Core's `dct:isReplacedBy`. Record history with `change_note` (SKOS `changeNote` / `historyNote`).
- **Every assertion records `module@version`.** After an upgrade, only rule and LLM assertions that touch changed classes are re-derived. Assertions pointing at a deprecated id migrate automatically when `replaced_by` is 1:1; otherwise they are flagged.
- Classification is a **derived** layer (P6), so a schema change is a rebuild, like `rebuild_lex_index()`, not a manual migration.

### 5.6 Sticky user decisions

User rows win the projection (4.3). Re-classify, re-ingest and agents never retract them. If new evidence disagrees, the agent files a *conflict proposal* ("cue says `permit`, user said `guidance`"), and the user decides.

### 5.7 Adding a module for a new DB

1. Copy a module template.
2. Define 5–12 classes with cues.
3. Test the cues in the cue tester against the DB.
4. Bind the module to the DB.
5. Run re-classify in dry-run.

`create_db` can offer module selection. An import script from SKOS/CSV (for example an EuroVoc subset) is optional and can come later.

---

## 6. Question 3: how ontologies handle time

### 6.1 Three different temporal problems

| Problem | Question it answers | Example |
|---|---|---|
| **Valid time** (ABox) | When does/did this hold in the world? | StrlSchV 2001 was valid until 2018-12-30; the 2018 StrlSchV has applied since 2018-12-31 |
| **Transaction time** (ABox) | When did the wiki learn or believe it? | "On 2026-03-01 the wiki did not yet know the 2025 version" |
| **Schema evolution** (TBox) | How did the vocabulary change? | `technical-rule` split into `din-standard` and `kta-rule` in legal-de 0.2.0 |

Plain OWL/RDF is **atemporal and monotonic**: an asserted triple never stops being true, and reasoners do no temporal reasoning. Every approach below therefore models time *explicitly*.

### 6.2 How the established approaches do it

| Approach | Mechanism | What LocalWiki takes from it |
|---|---|---|
| **ELI 1.4** (EU, verified) | FRBR `Work` → `Expression` (version, language) → `Format`. Dates: `first_date_entry_in_force`, `date_applicability`, `date_no_longer_in_force`. `in_force` = inForce/notInForce/partiallyInForce. Relations `amends`, `repeals`, `consolidates`, `commences`, `version`. | Names for attributes and relations, 1:1. Work/Expression identity. |
| **Akoma Ntoso** (OASIS LegalDocML) | A document `<lifecycle>` of dated events. `<temporalData>` intervals per *provision*, separating *in force* from *efficacy* (application). Point-in-time version identifiers. | Later: §-level validity for transitional provisions. The event list corresponds to our ledger. |
| **schema.org `Legislation`** (derived from ELI, verified) | `legislationDateVersion`, `legislationDateOfApplicability`, `legislationLegalForce`, `legislationAmends`, `legislationRepeals`, `legislationConsolidates`, `legislationTransposes` | A cheap JSON-LD export target. |
| **Bitemporal data** (Snodgrass) / **Graphiti** (Zep, verified) | Every fact edge has `valid_at`/`invalid_at` (world) and `created_at`/`expired_at` (system). A contradicting fact *invalidates* the old edge instead of deleting it. | Ledger fields `valid_from/until` + `recorded_at`/retraction. Close intervals, never delete (P4). |
| **W3C OWL-Time** | Instants, intervals and Allen's 13 interval relations (before, meets, overlaps, during, …) | Only intervals, plus overlap and ordering checks in lint. |
| RDF patterns (reification, n-ary relations, 4D fluents, named graphs, RDF-star) | Ways to attach time to a triple | Not needed: a ledger row *is* an n-ary relation with time columns. |
| **SKOS/OWL versioning** | `owl:versionInfo`, `owl:priorVersion`, `owl:deprecated`, `dct:replaces`, `skos:changeNote` | Schema evolution (§5.5). |

### 6.3 The LocalWiki temporal model

**The FRBR/ELI model mapped onto LocalWiki:**
- **Work:** a stable id (`de-strlschv-2018`), aliases (`StrlSchV`), and a class.
- **Expression:** one raw source file, i.e. one version. It carries `version_date`, `in_force_from`, `applicable_from`, `in_force_until` and `in_force`.
- **Manifestation:** the PDF → Markdown file in `data/raw/` (already content-addressed by SHA-256 in `manifest.json`).
- **Concept pages** are the *interpretation layer* above the Expressions.

**Work identity is deterministic in German law.** The citation form "*Strahlenschutzverordnung vom 29. November 2018 (BGBl. I S. 2034, 2036), die zuletzt durch … geändert worden ist*" contains:
- the **Ausfertigungsdatum**, which identifies the Work;
- the "zuletzt geändert" / "Stand" part, which identifies the Expression.

This matters because the abbreviation alone is ambiguous. StrlSchV 2001 and StrlSchV 2018 are two different Works: the 2018 ordinance replaced the 2001 ordinance and the RöV. Where a publication carries an ELI URI, it can serve as the id.

**Example:**

```
Work de-strlschv-2001  "StrlSchV"  in_force_until 2018-12-30   replaced_by de-strlschv-2018
Work de-strlschv-2018  "StrlSchV"  in_force_from  2018-12-31   based_on de-strlschg-2017, transposes eu-dir-2013-59-euratom
  ├─ Expression StrlSchV_Stand_A.md   version_date A   valid [2018-12-31, B)
  └─ Expression StrlSchV_Stand_B.md   version_date B   valid [B, open)
(dates illustrative — confirm against BGBl before seeding)
```

**Reference resolution depends on time.** A 2015 permit that cites "§ 20 StrlSchV" means StrlSchV **2001**. The resolver maps an alias to the Work that was in force *at the citing document's `version_date`*. This is deterministic and needs no LLM.

**Static and dynamic references.** A `static` reference pins an Expression ("DIN 6812:2013-06"). A `dynamic` reference follows `current_expression(work, as_of)`.

**Validity by provenance for concept pages.** Facts on concept pages do **not** get their own timestamps. Every fact line already cites its source (`[StrlSchV_Stand_A.md]`), and every source has a validity interval, so a line's validity is the validity of its citations. When a line's sources are all superseded, it is labelled "(superseded; valid until …)" in answer contexts, and a page whose `sources` include only superseded Expressions of a Work gets an **`outdated`** flag. Lines without citations stay `unknown`: the behaviour is honest and fails open. This avoids asking a 4B model to date every fact.

**Point-in-time queries.** Every consumer takes an `as_of` parameter (default: today). Time intent in a question is detected deterministically, in the same style as `lang.py`: explicit dates, years, "damals", "alte Fassung", "vor/nach der Novelle", "as of". "What applied on 2017-06-01?" then selects StrlSchV 2001 automatically.

**Bitemporal audit.** Because the ledger keeps transaction time, the wiki can answer "what did it state on date *T* about the law valid on date *V*?". That is useful when a past answer given for compliance has to be justified.

### 6.4 Fixes to existing behaviour

| Today | With the ontology |
|---|---|
| `_is_newer` falls back to write dates (F2) | Compare only the valid dates of the two **sources** (`version_date`, then `in_force_from`). If either is unknown, the result is *unresolved*, which is honest. My F2 check becomes the regression test. |
| A numeric difference between two versions of one law is reported as a *contradiction* and sets `confidence: low` | Values from two Expressions of the same Work (or from an amending act) produce a **change note**: "changed with version B (previously X)". Confidence is not lowered. This removes a class of false-positive contradictions. |
| `stale` = TTL on `updated` | Keep `stale` (not re-checked lately) and **add** `outdated` (built on superseded law) as a separate graph overlay and lint section. |
| Old versions rank equally in BM25/vectors | Chunks from Expressions that are not valid at `as_of` are **demoted, not removed** (fail open), and citations carry a version badge. |

### 6.5 Later: validity at section (§) level

Transitional provisions (Übergangsvorschriften) make parts of a law valid at different times (ELI `partiallyInForce`; Akoma Ntoso per-provision intervals). The chunker already cuts at `§` boundaries, so per-§ intervals can be added later as `subject: src:<file>#§12`. Version 1 stays at document level and uses `partially-in-force` plus a note.

---

## 7. Question 2: should the agentic system update ontologies?

### 7.1 Verdict

**Yes for facts (ABox), under rules. No for the schema (TBox), beyond proposals.** There are five reasons against autonomous schema changes:
1. **Drift.** A 4B model would add a near-duplicate class for every odd document.
2. **Blast radius.** One schema change re-classifies the whole corpus.
3. **No backup.** `data/` has no backup (§5.5 of AGENTS.md).
4. **Prompt injection.** A document's own text could say "this supersedes StrlSchG".
5. **Reproducibility.** Classification must be explainable from rules and evidence.

On the fact side, however, the tedious and error-prone human work (typing documents, dating them, linking versions) is exactly what code does best when the evidence is formulaic. German legal texts are highly formulaic.

### 7.2 Autonomy matrix

| Change | Evidence | Actor | Applied |
|---|---|---|---|
| New class / relation / cue (schema) | Documents no cue matches | agent **proposes** | **Never automatic.** An admin approves in the Ontology editor (§5.3). |
| Class / work / dates, cue hit | Regex on title/head (§7.3) | code | Automatically (`by: rule`), visible in the upload table, user can override. |
| Class / work / dates, no cue hit | LLM picks from the enum, plus a verbatim quote | LLM proposes | `proposed`, not used for filtering until confirmed. |
| Version succession within a Work | Same work id, newer `version_date` | code | Automatically. The predecessor's interval is closed; reversible via retraction. |
| `based_on`, `transposes` | Eingangsformel / transposition clause matched verbatim | code | Automatically. Otherwise LLM-proposed. |
| `repeals` / `replaces` across Works | "tritt … außer Kraft", "wird aufgehoben" | code proposes | `proposed` (high impact: demotes a whole law). One-click confirm. |
| `incorporates` (binding) | "nach DIN …", "ist einzuhalten", "gilt als erfüllt, wenn" | LLM + cues | `proposed` |
| Class of a concept or entity page | LLM | LLM proposes | `proposed` (Phase 5) |
| User assertion | user | user | Final and sticky. Agents may only raise a conflict proposal. |
| Deletion | — | never an agent | Only through `delete_source`, which retracts the source's rows. |

The Research agents (Quick mode writing `comparisons/`, and web-only Deep mode) **never** assert legal relations. Their reports are classified `report`, and nothing more.

### 7.3 Walkthrough: a newer version of the StrlSchV is uploaded

1. **Prepare** (the existing Phase 1 of Upload). `metadata_extract` already finds `Stand`/`Fassung vom`. The new `ontology.detect()` adds the following, deterministically:
   - class (cue `verordnet`);
   - Work identity (title + Ausfertigungsdatum "vom 29. November 2018" → `de-strlschv-2018`);
   - `based_on` from the Eingangsformel "*Auf Grund des § … des Strahlenschutzgesetzes … verordnet*";
   - `transposes` from "*dient der Umsetzung der Richtlinie 2013/59/Euratom*";
   - the **predecessor**: the current Expression of that Work already in the DB.
2. **Review** (the existing Phase 2 table). It gains the columns *Class*, *Work*, *Version date* and *Supersedes*, all prefilled. The user confirms or corrects them at the moment they are already looking at the file. Confirmed values are written with `by: user`.
3. **Ingest.** Ledger rows are appended, and the predecessor gets `in_force_until`. **Nothing is deleted**: the old file stays, for point-in-time queries.
4. **Merge.** On concept pages, number changes between A and B become *change notes*, not contradictions (§6.4).
5. **Rebuild the caches.** `ontology.build()` runs, and retrieval now demotes Expression A by default.
6. **Proposals.** LLM-extracted `incorporates` and other relations arrive with verbatim quotes and appear in a **"Review ontology proposals"** panel next to the existing *Resolve contradictions* panel.
7. **Schema gap.** If the document matched no class, a schema proposal ("new class `kta-rule` under `standard`, cue `\bKTA\s+\d{4}`") goes to the admin queue.

### 7.4 Safeguards

- **Evidence verification in code.** A proposal's quote must occur verbatim in the source (after whitespace normalisation). Cited `§`/numbers must exist. Relation targets must resolve to a known Work or be kept as *dangling* (an info item, not an error). Otherwise the proposal is discarded. This mirrors `page_lang`'s number/§ verification.
- **Injection containment.** Document text can only produce *evidence-bearing proposals*. It never creates schema, never retracts, and never overrides user rows.
- **Reversibility.** A retraction is a new row, and every automatic action is listed in `log.md` with its ledger id.
- **Bounded cost.** At most one extra LLM call per source, only when cues are inconclusive. The output is strict JSON with enums; a parse failure means no proposal (fail open).
- **No background autonomy.** Ontology updates happen at ingest, or on explicit re-classify. There is no crawler loop.

---

## 8. Consumers: where the ontology pays off

| Consumer | Change | Guard rail |
|---|---|---|
| `retrieval.search(…, as_of=None)` | Demote chunks from Expressions not valid at `as_of` | Reorders only; a DB without an ontology gets byte-identical results. The lexical arm remains the citation truth. |
| Agents (`tools.py`) | `raw_search`/`raw_read` hits carry badges such as `[StrlSchV, Stand B, in force]` / `[superseded 20xx]`. Later, an `ontology_lookup(work, as_of)` tool returning class, versions, validity, `based_on`/`transposes` chains and binding paths. | Badges first: the small model gets them for free, with no new tool to learn. |
| Contradiction check | Aware of succession (§6.4) | — |
| Graph (`build_typed_graph`, neural renderer) | Typed **directed** edges between `source::` nodes. Class colour. **Pyramid layout** (y = rank). Overlays for `outdated` and superseded items. | `linked_pages` stays undirected for retrieval. Norm walks use `ontology.chain`. |
| Lint (deterministic) | Cycles in `replaces`/`based_on`; overlapping validity intervals within a Work; `in_force_until < in_force_from`; rank violations (an ordinance `based_on` a VwV); a static reference to an edition missing from the DB; dangling Works referenced by N documents (the "missing sources" suggestion from Karpathy's lint). | Rank checks are *warnings*, never automatic fixes (§2.3). |
| Explorer | Class and validity badges on source pages; inline assertion edit | — |
| Export (optional) | `scripts/export_ontology.py`: schema as SKOS Turtle, facts as ELI / schema.org JSON-LD | Adapter only, not needed at runtime. |

---

## 9. The `legal-de` module (Strahlenschutz pyramid)

| rank | class | broader | norm | Typical cues (title/head) | Examples |
|---|---|---|---|---|---|
| 1 | `eu-regulation`, `eu-directive` | legal-instrument | yes | `Verordnung (EU\|Euratom)`, `Richtlinie \d{4}/\d+/Euratom` | 2013/59/Euratom |
| 2 | `constitution` | legal-instrument | yes | `Grundgesetz` | GG |
| 3 | `federal-act` (+ `state-act`) | legal-instrument | yes | `Gesetz`, "Der Bundestag hat … beschlossen" | StrlSchG, AtG |
| 4 | `ordinance` | legal-instrument | yes | `verordnet`, `Verordnung` | StrlSchV |
| 5 | `admin-regulation` | legal-instrument | internal* | `Allgemeine Verwaltungsvorschrift` | AVV |
| 6 | `ministerial-guideline`, `technical-rule`, `expert-recommendation` | guidance / standard | no | `Richtlinie … (BMUV)`, `Bekanntmachung`, `DIN`, `KTA`, `SSK` | Fachkunde-Richtlinie, DIN 6812, SSK recommendations |
| 7 | `permit`, `order` | decision | individual | `Genehmigung`, `Bescheid`, `wird … erteilt` | operating licence |
| 8 | `rp-instruction`, `operational-rule` | procedure | internal | `Strahlenschutzanweisung` | internal instructions |

\* Administrative regulations bind the authorities. Norm-concretising ones (TA Luft is the classic case, relevant to the Abluftreinigung DB) have been given external effect by case law, which is one more reason `norm` is not simply a boolean.

**Relations** (ELI mapping): `based_on`/`basis_for` (eli:based_on), `transposes` (eli:transposes), `amends` (eli:amends), `repeals` (eli:repeals), `applies` (eli:applies: a permit applies § 12 StrlSchG), `cites` (eli:cites), `is_part_of` (eli:is_part_of), `incorporates` (no ELI equivalent; attributes `mode`, `version`, `effect`, `scope`).

**Deriving whether something is binding.** `binding_of("din-6812", context="permit-XY", as_of=today)` returns an **explanation path**, not a flag:

```
DIN 6812:2013-06  ◄─incorporates(static, mandatory)─  Genehmigung XY (addressee: Klinik Z)
                                                     └─applies─►  § 12 StrlSchG  ◄─based_on─ …
→ binding for Klinik Z by reference in its permit, in the 2013 edition, while the permit is valid.
   The 2021 edition is NOT binding for Klinik Z until the permit is amended (static reference).
```

With no incoming `incorporates` edge from a valid, binding instrument, the result is "interpretive / state of the art only". That is exactly the legal point in your input ("the label alone creates no obligation"), but now it can be checked and audited.

**Other DBs (sketch).**
- *Labor / STA-QS*: `procedure` with revision Expressions ("Rev. 3 gültig ab").
- *Investing*: `report`/`dataset` with an `as_of` observation date as the dominant temporal attribute.
- *Fusion*: `report` (papers) with `cites`.

The core temporal machinery (Work/Expression, `as_of`) is identical in each case, and only the cues differ.

---

## 10. Implementation plan (phased, each phase verifiable)

| Phase | Scope | Verify |
|---|---|---|
| **0 Prototype corpus** | Create `data/KI` and seed 6–8 public texts: the Directive, StrlSchG, **two Stände** of StrlSchV 2018, the repealed StrlSchV 2001, one BMUV guideline, one sample permit that references a DIN standard. Hand-label a gold file `bench/fixture_KI_ontology.json`. | Gold file reviewed by you. Baseline detection precision/recall, rules vs LLM. |
| **1 Schema + detection + ledger** | `ontology/core.yaml`, `ontology/legal-de.yaml`, `src/ontology.py` (load / validate / detect / ledger / project / stamp), stamping via `_okf_apply`, new columns in the upload table, `delete_source` retraction. | Validator rejects cycles, dangling `broader`, asymmetric inverses and bad regexes. Cue detection meets an agreed precision on gold. A `resolve_contradiction` rewrite keeps the ontology keys (F7 test). Delete retracts rows. |
| **2 Time** | Work/Expression registry, `current_expression` / `validity`, **`_is_newer` fix**, change notes aware of succession, `as_of` demotion + citation badges, `outdated` overlay. | F2 regression test. `as_of=2017-06-01` resolves StrlSchV 2001. A change between two Stände is not flagged as a contradiction. **A DB without an ontology returns byte-identical search results.** |
| **3 Relations + binding** | Formula regexes (Eingangsformel, transposition, repeal, entry into force), LLM proposals with verbatim evidence, review panel, `chain` / `binding_of`, typed directed graph edges + pyramid layout, deterministic lint. | Binding path for the DIN standard in the sample permit. Lint flags an ordinance `based_on` a VwV. A fabricated quote is rejected. |
| **4 Editing + evolution** | Maintenance → Ontology (module editor for admins, binding for maintainers, cue tester, impact preview, re-classify dry-run/apply), schema proposals from agents, SKOS / JSON-LD export. | Deprecating a class migrates assertions via `replaced_by`. User overrides survive re-classify. The exported Turtle parses. |
| **5 Optional** | Classes for concept/entity pages, §-level validity, modules for other DBs. | Per-module gold files. |

**Documentation when implementing** (per AGENTS §5.1):
- `docs/ontology.md` as the component doc, which this report then becomes the rationale for;
- a row in IMPLEMENTATION.md §3;
- these **AGENTS.md hard rules**:
  - The ontology schema lives in `ontology/*.yaml`. Agents never edit it at runtime; they file proposals.
  - Ontology keys (`class`, `work`, validity, typed relations) are code-stamped from the ledger, like OKF. Never ask the LLM to write them.
  - Valid time (legal dates of sources) is not transaction time (`created`/`updated`). Never compare across the two.
  - Relations target Works; versions are resolved at query time. Supersession closes intervals and never deletes.
  - `delete_source` also retracts the ledger rows of the deleted source.

---

## 11. Decisions I need from you

1. **Ledger + projection** (recommended) or frontmatter only. The trade-off is one more store against sticky user decisions, a proposal queue, history, and immunity to LLM rewrites.
2. **Where shared modules live and who may edit them.** Recommendation: `ontology/` in git, admins only; DB-local extensions editable by maintainers.
3. **Superseded versions:** *demote + label* (recommended) or *hide by default*.
4. **Work ids:** a slug from abbreviation + Ausfertigungsdatum (recommended), switching to ELI URIs where the publication provides them.
5. **Scope of Phase 1:** `core` genres for **all** DBs plus `legal-de` (recommended: cheap, and multi-DB chat benefits), or legal DBs only.
6. **Phase 0:** may I create and seed `data/KI` with public legal texts? It does not exist yet.

---

## References

- ELI ontology v1.4, Publications Office of the EU: <https://op.europa.eu/documents/3938058/11669184/eli.owl/> and <https://data.europa.eu/eli/ontology> (classes and properties verified 2026-09-24)
- schema.org `Legislation`: <https://schema.org/Legislation> (properties verified 2026-09-24)
- Graphiti bitemporal model (Zep): <https://blog.getzep.com/beyond-static-knowledge-graphs/> (valid_at/invalid_at + created_at/expired_at; invalidate, don't delete)
- W3C Time Ontology in OWL: <https://www.w3.org/TR/owl-time/>
- W3C SKOS Reference: <https://www.w3.org/TR/skos-reference/>
- OASIS LegalDocML (Akoma Ntoso) v1.0: lifecycle events and temporalData (in force vs efficacy)
- R. Snodgrass, *Developing Time-Oriented Database Applications in SQL* (bitemporal model); C. Welty & R. Fikes, *A Reusable Ontology for Fluents in OWL* (2006)
- Project docs: [architecture.md](architecture.md), [okf.md](okf.md), [retrieval.md](retrieval.md), [openissues.md](openissues.md) (Gap 5: source-version awareness)
