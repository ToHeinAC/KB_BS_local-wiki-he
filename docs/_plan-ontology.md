# Ontology: implementation plan

**Status:** plan, nothing implemented · **Date:** 2026-09-26 · **Checked against:** commit `b35e1f1`
**Input:** [_idea-onthology.md](_idea-onthology.md) (the concept, "the report" below), checked against the current code.
**Added requirements (user, 2026-09-26):**
1. Per database, the user can **see** the ontology in the GUI (if the DB has one), **export** it, **edit it by hand**, and **import** it again. Every change is **logged**, and the GUI shows the **last actual change**: re-importing an unchanged file is not a change.
2. Every search runs a **mandatory check against the ontology**, to get the most relevant answer possible (§4).

This plan keeps the report's architecture (three layers, ledger, code-stamping, fail-open) and its phases, with three changes:
- The GUI workbench (view / export / import / history) moves **forward**, to Phase 2, right after the schema and ledger exist. It ships on its own, before any automatic detection.
- The report's single `src/ontology.py` becomes four modules plus a UI module, because AGENTS.md §5.2 requires pure core logic and I/O in adapters.
- Ontology-aware search gets its own phase (Phase 4). The report only had `as_of` demotion and citation badges; this plan makes the ontology step a **code-enforced stage of every search path**, with a dedicated agent tool as a supplement.

---

## 0. What changed since the report

| Report said | Now | Consequence |
|---|---|---|
| F9: `data/KI` does not exist | It exists: 18 AI/tech reports, **no legal texts** | Phases 1–2 can be built and tried on KI with the `core` module only. The `legal-de` gold set (Phase 0b) still needs public legal texts seeded into KI. |
| Line refs `_is_newer` :427, `_okf_apply`, `build_typed_graph` :2033, `resolve_contradiction` :2163 | `_is_newer` wiki_engine.py:473, `_okf_apply` :844, `delete_source` :1459, `build_typed_graph` :2285, `resolve_contradiction` :2351 | Findings F1–F8 still hold; only the line numbers moved. |
| Upload review table | `st.data_editor` at app.py:1183, one editable column `effective as of` | Phase 3 adds columns here. |
| Maintenance sections | Segmented control at app.py:1863 (`Search index`, `Delete source`, `Link graph health`, `Lint`, `Page language`, `Activity log`, `Admin`) | Phase 2 adds `Ontology` as one more option. |
| Roles | `auth.is_admin`, `auth.is_maintainer(user, db)`, read access via `user_dbs` | Enough for the permission matrix (§3.5); no auth change needed. |
| AGENTS.md | 190 / 200 lines | The new hard rules must fit in ≤ 8 lines; details go to `docs/ontology.md`. |
| PyYAML | Only transitive (via `python-frontmatter`) | `uv add pyyaml` (MIT) because we will import it directly. |

---

## 1. Decisions

The report's §11 questions are still open. This plan assumes the **recommended** answer for each; the GUI requirement adds D7–D10. Please confirm or change them before Phase 1 starts.

| # | Decision | Assumed default | Alternative |
|---|---|---|---|
| D1 | Ledger + projection, or frontmatter only | Ledger + projection | Frontmatter only (loses sticky user edits, history, 3-way import) |
| D2 | Shared modules `ontology/*.yaml` | In git, edited via git/PR only; **not** writable from the GUI | Admins may import shared modules through the GUI (writes git-tracked files at runtime) |
| D3 | Superseded versions in retrieval | Demote + label | Hide by default |
| D4 | Work ids | Slug from abbreviation + Ausfertigungsdatum; ELI URI when present | ELI URI only |
| D5 | Phase 1 scope | `core` for all DBs + `legal-de` | Legal DBs only |
| D6 | Seed public legal texts into `data/KI` (Phase 0b) | Yes, before Phase 3 | Use synthetic fixtures only |
| D7 | What one exported file contains | **One YAML file per DB**: DB binding + local schema extensions + confirmed facts; shared modules included **read-only** for reference | Two files (schema, facts) |
| D8 | "Actual change" | **Semantic**: the canonical form (§3.2) differs. Comments, key order, formatting, quoting and export metadata are not changes | Byte-level file hash |
| D9 | No-op import | Nothing written, **nothing logged**, GUI says "identical to revision N, nothing changed" | Log it as "import (no change)" in the change history, but never as the last change |
| D10 | YAML comments on round trip | Not preserved (export is regenerated from the store); every class and fact takes an optional `note:` field instead | Preserve comments with `ruamel.yaml` (only possible for the schema part, never for facts) |
| D11 | How the ontology check is made mandatory | **In code**: a fixed stage inside `retrieval.search` plus a code-injected briefing before the agent's first LLM call; the tool `ontology_lookup` is an extra, not the guarantee (§4.1) | Tool only, with a prompt rule "always call it first" (a 4B model skips or misuses it) |
| D12 | "Mandatory" on a DB without an ontology | The stage always runs and records "no ontology" in the audit; search is byte-identical to today | Refuse to answer until the DB has an ontology |
| D13 | May the ontology stage bring in chunks the lexical/semantic arms did not rank in the candidate pool? | Yes, but only through **lexical** queries (aliases, labels, the resolved Work's current version), so the lexical arm stays the citation truth | Reorder only (smaller gain: a document that the query names by abbreviation only can stay missing) |
| D14 | Class words in a query ("Verordnung", "Genehmigung") | **Boost** matching classes, never filter; a hard filter only when the user picks one in the UI | Hard filter from the query text |

---

## 2. Requirements

| # | Requirement | Acceptance (test) |
|---|---|---|
| R1 | Any user with read access sees the active DB's ontology: bound modules, effective classes (tree by `broader`), relations, facts per source/work, current revision | AppTest: KI with a fixture ontology renders the class tree and the facts table |
| R2 | A DB without an ontology says so and changes nothing else | AppTest: "No ontology for this database"; `ontology_store.exists()` is False; no file is created by viewing |
| R3 | Maintainers can create one from a template (module picker) or by importing a file | Test: create writes `ontology.yaml` + revision 1 + one change row |
| R4 | Anyone with read access can export the current revision (or any past revision) as one YAML file | Test: `export(rev)` parses back to the same canonical form; its header carries `base_revision` |
| R5 | Maintainers can import an edited file. The import is parsed, validated, diffed and **previewed** before anything is written | Tests: invalid file → errors listed, store unchanged; valid file → preview lists added/removed/changed items |
| R6 | Re-importing an identical file (also after reformatting or comments) is a no-op | Test: export → import → `status == "unchanged"`, revision and change log untouched |
| R7 | Every applied change is logged: structured change row, full snapshot, and a line in the wiki `log.md` (Activity log) with user, revision, summary | Test: one apply → one `changes.jsonl` row, one snapshot, one `log.md` entry |
| R8 | The GUI shows the **last actual change** (when, who, how, what) and, separately, the last automatic change (ingest) | Test: after a no-op import, "last change" still points at the previous real change |
| R9 | An import based on an older export does not silently undo newer changes (3-way merge, §3.3) | Test: export at rev 3, ingest makes rev 4, import of the edited rev-3 file keeps rev 4's facts and applies only the user's edits |
| R10 | Any past revision can be downloaded and restored; a restore is a new revision, never a rewrite | Test: restore rev 2 → rev 5 whose canonical form equals rev 2; history still has rev 3–4 |
| R11 | Fail open: an ontology error never breaks ingest, search, chat or the Explorer | Test: corrupt `ontology.yaml` → section shows the error; search results byte-identical |
| R12 | Every search path runs the ontology stage: Search page, Quick chat, Deep chat, Quick research (Deep research is web-only and excluded, AGENTS §5.3) | Test per path: a spy on `ontology_query.resolve` is called exactly once per search |
| R13 | The agent sees the ontology frame without having to call a tool | Test: the first message list of `run_chat_agent` / `run_research_agent` contains the briefing block when the question names a known Work |
| R14 | Relevance does not get worse, and gets better on questions that name documents, classes or dates | Benchmark (§4.6): hit@1 / hit@5 with the stage on ≥ off on every gold question set; time-intent questions return the valid version at rank 1 |
| R15 | The user can see what the ontology stage did | "Why these sources" panel shows matched Works, classes, `as_of`, expansions, boosted / demoted hits |

---

## 3. Design of the workbench

### 3.1 Modules and storage

| Module | Kind | Responsibility |
|---|---|---|
| `src/ontology.py` | pure | Schema model (dataclasses), module merge (core + domain + local), meta-validation (report §5.4), projection of ledger rows to current facts (precedence user > rule > llm). Later: `detect`, `validity`, `chain`, `binding_of`, `lint`. |
| `src/ontology_bundle.py` | pure | The export/import file: render, parse, canonicalise, revision hash, semantic diff, 3-way merge, semver bump, apply plan. No file access. |
| `src/ontology_store.py` | I/O adapter | Everything under `data/<DB>/ontology/`: read/write the binding, append ledger rows, append change rows, write snapshots, lock, atomic replace. Reads `ontology/*.yaml` (shared modules). |
| `src/ontology_query.py` | pure | The search stage (§4): resolve a query against the ontology view, expansions, rescoring, briefing text, audit record. |
| `src/ontology_ui.py` | Streamlit | The `Ontology` maintenance section. `app.py` only calls `ontology_ui.render(user, can_maintain)`, so the 2,092-line script does not grow (same pattern as `gpu_widget.py`, `graph_widget.py`). |

```
ontology/core.yaml, ontology/legal-de.yaml          shared modules (git, read-only at runtime, D2)
data/<DB>/ontology.yaml                             binding: modules + local extensions (report §4.2)
data/<DB>/ontology/assertions.jsonl                 fact ledger, append-only (report §4.3)
data/<DB>/ontology/changes.jsonl                    one row per revision (§3.4), append-only
data/<DB>/ontology/history/<seq>-<hash>.yaml        full snapshot per revision (export format)
data/<DB>/ontology/.lock                            flock for apply
```

The binding file sits at `data/<DB>/ontology.yaml` as in the report. The GUI never writes it directly: all writes go through `ontology_store.apply()`.

### 3.2 The exchange file and its canonical form

```yaml
# LocalWiki ontology export. Edit `schema.local` and `facts`; everything under
# `reference` is read-only (shared modules live in git). Comments are not kept.
format: localwiki-ontology/1
db: KI
revision: 7                      # informational
base_revision: 7-3f9c21a04be1    # used for the 3-way merge (§3.3); do not edit
exported_at: 2026-09-26T14:02:11Z
exported_by: tobias
schema:
  modules: [core]                # bound shared modules (by id; version pinned by the repo)
  local:
    version: 0.3.0               # bumped by code on apply; an edit here is ignored
    classes:
      market-report: {broader: report, labels: {en: Market report, de: Marktbericht},
                      definition: "Analyst or vendor report on a market segment",
                      cues: ['\bmarket (outlook|report)\b'], note: "added for KI"}
    relations: {}
facts:
  works:
    attention-2017: {class: report, aliases: [Transformer paper], cites: [seq2seq-2014]}
  sources:
    NIPS-2017-attention-is-all-you-need-Paper.md: {class: report, work: attention-2017,
                                                  version_date: 2017-06-12}
reference:                       # read-only: the bound shared modules, for orientation
  core: {id: core, version: 1.0.0, classes: {...}, relations: {...}}
```

**Canonical form** (the basis for "actual change", D8): parse with `yaml.safe_load`; keep only `schema.modules`, `schema.local.{classes,relations}`, `facts`; drop `format`, `db`, `revision`, `base_revision`, `exported_*`, `reference`, `schema.local.version`; strip strings; dates as ISO strings; every list of scalars is a set (sorted, de-duplicated); empty maps, empty strings, `null` and `false` removed; sorted-key compact JSON. **Revision hash** = first 12 hex chars of SHA-256 over that JSON. Two files are "the same ontology" exactly when their hashes match.

`facts` in the file is the **projection** (current confirmed values); relations are list-valued keys on their subject, like `aliases`. As built: [ontology.md](ontology.md) §Workbench. Proposals are not exported; they stay in the GUI review panel (Phase 3+).

### 3.3 Import pipeline

All steps up to *Apply* are pure (`ontology_bundle`) and write nothing.

1. **Size and parse.** Refuse files > 2 MB. `yaml.safe_load` only (no custom tags); refuse aliases/anchors beyond a small count (YAML bomb guard). Check `format` and that `db` matches the active DB (mismatch → error, with an explicit "import anyway" checkbox for copying one DB's schema into another).
2. **Validate schema.** Report §5.4 meta-rules on the merged schema (shared modules + local): unique ids, no id clash with shared modules unless it is a declared override, `broader` exists and has no cycle, relation `domain`/`range` exist, inverse pairs symmetric, labels de+en, one-line definition, cues compile, are ≤ 200 chars, and do not match the empty string.
3. **Validate facts.** Class ids exist and are not deprecated; sources exist in the DB's manifest (unknown source → error, listed); dates are ISO; `work` ids are slugs; relation names exist; `from`/`to` are known Works or kept as *dangling* (warning, not error; report §7.4).
4. **Find the base.** Look up `base_revision` in `history/`. Missing header or unknown base → base = current (2-way, with a warning).
5. **3-way merge** on flattened paths (`schema.local.classes.market-report.cues`, `facts.sources.X.class`, …):
   - *mine* = diff(base, imported), *theirs* = diff(base, current).
   - Paths only in *mine* → apply. Paths only in *theirs* → keep current. Same path, same result → fine. Same path, different result → **conflict**: listed in the preview; the user picks "mine" or "keep current" per conflict (default: keep current).
   - Result = the new canonical state. If its hash equals the current hash → **unchanged** (D9): show "identical to revision N — nothing changed" and stop.
6. **Impact checks.**
   - Removing a class/relation id that any ledger row (current or past) references → refused; the message says to mark it `deprecated: true` with `replaced_by`. Removing an id nothing ever referenced (a typo) is allowed.
   - Facts pointing at a deprecated id with a 1:1 `replaced_by` → migrated, listed in the preview.
   - Counts: sources whose class changes, pages to re-stamp (Phase 3+).
7. **Preview.** Table of added / removed / changed items (schema and facts separately), conflicts, warnings, the computed semver bump for `schema.local` (patch: labels/definitions/cues/notes; minor: added ids; major: re-parenting, changed domain/range, deprecations).
8. **Apply** (`ontology_store.apply`), under the flock:
   - Re-check that the current revision is still the one the preview was computed on; otherwise refuse and re-preview (optimistic concurrency, two maintainers).
   - Write the binding with the bumped `local.version` (tmp file + `os.replace`).
   - Turn fact changes into ledger rows with `by: user`, `user: <name>`, `evidence: "import rev <n>"`: a changed value is a new assertion; a removed value is a **user assertion of `null`** (explicit unset), not a retraction, so a later re-classify cannot bring back what the user removed (report §5.6).
   - Write the snapshot `history/<seq>-<hash>.yaml`, append the change row (§3.4), append the `log.md` line.
   - Phase 3+: rebuild `index/ontology.json` and re-stamp affected summary pages.

The **GUI editor** (Phase 7: `st.data_editor` tables) and **restore** (R10) produce a new state and go through steps 2–8 unchanged. There is one write path.

### 3.4 Change log and "last change"

One row per revision in `data/<DB>/ontology/changes.jsonl`:

```json
{"seq": 8, "hash": "a41d07c9e2f0", "parent": "7-3f9c21a04be1", "at": "2026-09-26T14:07:40Z",
 "user": "tobias", "via": "import", "file": "ontology-KI-edited.yaml", "file_sha256": "…",
 "summary": {"schema": {"added": 1, "changed": 1, "removed": 0},
             "facts": {"added": 3, "changed": 2, "removed": 1}, "conflicts_kept_current": 1},
 "local_version": "0.3.0 -> 0.4.0",
 "diff": [{"path": "schema.local.classes.market-report", "op": "add"},
          {"path": "facts.sources.JEN_KOINNO.md.class", "op": "change", "from": "report", "to": "guidance"}]}
```

- `via` ∈ `create`, `import`, `editor`, `restore`, `ingest`, `reclassify`, `delete_source`. Automatic writers (Phase 3+) write **one row per ingest batch**, not per ledger row.
- A row is written **only** when the canonical hash changes. That is what makes "last change" actual (R6, R8).
- **Last change** in the GUI = newest row with a human `via` (`create`/`import`/`editor`/`restore`); **last automatic change** = newest row with `ingest`/`reclassify`/`delete_source`. Both show time (UTC → local), user, via, file name, summary.
- The wiki `log.md` gets one line per row through a new public `wiki_engine.log_event(action, detail)` (thin wrapper of `_append_log`, which stays the only log writer): `ontology | rev 8 by tobias via import (ontology-KI-edited.yaml): schema +1 ~1, facts +3 ~2 −1`. It then shows in Maintenance → Activity log.
- Snapshots are kept forever (a few KB each). `data/` has no backup (AGENTS §5.5); `data/<DB>/ontology/` must be part of any future backup.
- `changes.jsonl` is the source of truth for history; if the file is missing or unreadable the GUI shows "history unavailable" and the ontology still works (R11).

### 3.5 Permissions

| Action | Reader (has DB) | Maintainer (DB) | Admin |
|---|---|---|---|
| View, export current or past revision | yes | yes | yes |
| Create, import, restore, edit binding / local schema / facts | — | yes | yes |
| Change shared modules `ontology/*.yaml` | — | — | via git only (D2) |

Every write function takes `user` and checks the role itself (not only the UI), so a hidden button is not the only guard.

### 3.6 The GUI section

Maintenance → **Ontology** (new segmented-control option, app.py:1863). Inside, a second segmented control (not `st.tabs`, see [ui.md](ui.md)): `Overview | Classes | Facts | History | Import`.

```
Ontology — KI                                   revision 8 · a41d07c9e2f0
Modules: core 1.0.0 · local 0.4.0
Last change:            2026-09-26 16:07 · tobias · import of ontology-KI-edited.yaml
                        schema +1 ~1 · facts +3 ~2 −1          [Show diff]
Last automatic change:  2026-09-25 09:12 · ingest (3 sources) · facts +3
[Export current (YAML)]
─────────────────────────────────────────────────────────────────────────────
Classes (tree)        document ▸ report ▸ market-report (local)   used by 4 sources
Facts (table)         Source | Class | Work | Version date | In force | By (user/rule/llm)
History (table)       Rev | When | Who | Via | Summary | [Diff] [Download] [Restore…]
Import                file_uploader → errors | "identical, nothing changed" | preview + conflicts
                      → [Apply import] (primary, maintainers only)
```

- Without an ontology: an info box, plus (maintainers) "Create from modules" (multiselect of shared modules) and "Import file".
- The preview lives in `st.session_state` keyed by (DB, uploaded file hash, current revision), so a rerun does not recompute it and a DB switch discards it.
- Export uses `st.download_button` with the file name `ontology-<DB>-rev<seq>-<YYYYMMDD>.yaml`.

---

## 4. Ontology-aware search (mandatory)

### 4.1 Why a tool alone is not enough

- The model calls a tool only when it decides to. The target model (gemma e4b) skips tools, passes wrong arguments, or loops; that is why `run_memory` and the raw-citation gate in `_submit_chat_impl` exist. A prompt rule like "always call `ontology_lookup` first" is a request, not a guarantee.
- The project's pattern for "must always hold" is **code**: OKF stamping, language pinning, the citation gate. The ontology check follows it (D11).
- So the check is mandatory **in code** (S1, S2, S4 below). The dedicated tool (S3) is kept for follow-up questions the model has during an agent run.

| Layer | Where | Runs | What it does |
|---|---|---|---|
| **S1** Retrieval stage | `retrieval.search`, `wiki_engine.search_wiki` | every search, every path | resolve the query against the ontology, add an ontology arm to fusion, order by validity, annotate hits |
| **S2** Briefing | `chat_agent.run_chat_agent`, `agent.run_research_agent`, Quick chat synthesis | every answer | code-built "ontology frame" in the system prompt, before the first LLM call |
| **S3** Tool `ontology_lookup` | `tools.py` (`TOOLS`, `CHAT_TOOLS`) | when the model calls it | versions, validity, relation chains, class members |
| **S4** Answer check | `_submit_chat_impl`, source lists in the UI | every Deep-chat submit, every rendered answer | reject once when only superseded versions are cited; badges stamped by code |

On a DB without an ontology, every layer runs, records "no ontology" in the audit and changes nothing (D12, R11).

### 4.2 S1: the retrieval stage

```
query ─► ontology_query.resolve(q, view, today)          (pure, no LLM, target < 5 ms)
           works:      "StrlSchV" → de-strlschv-2018   (alias, exact word match)
           classes:    "Verordnung" → ordinance        (class label de/en)
           as_of:      2017-06-01 from "2017"          (Phase 5; default today)
           expansions: ["Strahlenschutzverordnung"]
lexical arm:  lex_index.query(q)  +  lex_index.query(e) for each expansion (≤ 3)
semantic arm: unchanged
ontology arm: lex_index.query(q, sources=current versions of resolved Works),
              then chunks of sources whose class matched
      └──────────► RRF fusion (the ontology arm is one more ranked list, fixed weight)
                   ─► rerank (Deep paths only, unchanged)
                   ─► validity order (Phase 5: Expressions not valid at as_of go after valid ones; last step, so rerank cannot undo it)
                   ─► hits, each with hit["ontology"] = {class, work, version, validity}, plus an audit record
```

- **Resolution is deterministic.** It is a longest-match, word-boundary lookup over an alias/label table precomputed in `index/ontology.json`: Work aliases, Work labels de+en, class labels de+en. An ambiguous alias (two Works both called "StrlSchV") is resolved by `as_of` (report §6.3); if that does not decide it, both are kept.
- **Why a separate arm, not a score multiplier.** RRF bounds each list's influence, so a wrong resolution can move a hit but never swamp the other arms. It also keeps the stage one idea: "the ontology has an opinion about the ranking", with no extra tuning constants beyond one weight.
- **Only lexical queries bring in new chunks** (D13). Expansions and the ontology arm are FTS5 queries, so every hit is still a lexical hit, and the lexical arm stays the citation truth. `lex_index.query` gains an optional `sources=` filter (adapter change, tested).
- **Class words boost, never filter** (D14). A hard filter comes only from an explicit UI control (Phase 4: a class chip on the Search page).
- **Wiki scope.** `index/ontology.json` also maps pages to Works: a source-summary page to its source, and a concept page to the Works its `sources:` belong to. The ontology arm then lists those pages. `search_wiki` and `retrieval.search` share one helper for the stage, so the Search page stays on its current lexical path plus the ontology arm, and does not gain the semantic arm as a side effect.
- **Multi-DB.** Each DB has its own view. `_raw_search_db` / `_wiki_search_db` already run per active DB, so resolution happens per DB. Shared `core` class ids keep class boosts uniform across DBs.
- **Fail open.** No ontology, an unreadable view, or an empty frame → the stage returns `None`, and `search()` runs today's code path, byte-identical (test).

### 4.3 S2: the briefing

Before the agent's first LLM call, code builds the frame and places it in the **system prompt** (like the language directive, so it survives truncation):

```
Ontology frame (built by code from confirmed facts):
- "StrlSchV" = Strahlenschutzverordnung 2018 (de-strlschv-2018), class: ordinance.
  Current version: StrlSchV_Stand_B.md (in force since …). Older: StrlSchV_Stand_A.md (superseded …).
  Based on: StrlSchG (de-strlschg-2017). Transposes: Directive 2013/59/Euratom.
- Point in time of the question: today (no date given).
Prefer the current version. When you cite an older version, name it as such.
```

- The header and the closing rule are constants in `prompts.py` (`ONTOLOGY_BRIEFING_HEADER`, `ONTOLOGY_BRIEFING_RULE`). The lines are generated from confirmed ledger facts only, never from document text, so a document cannot inject instructions (report §7.4).
- The frame is capped at about 600 characters (at most 3 Works, one hop of relations). An empty frame adds nothing and costs no tokens.
- It is also yielded as a trace step `{"type": "ontology", …}`, so the Research trace and Deep-chat steps show it.
- Quick chat (`wiki_engine.query_with_sources`) adds the same frame to its synthesis prompt.

### 4.4 S3: the tool `ontology_lookup`

`ontology_lookup(term: str, as_of: str = "") -> str`, in `TOOLS` and `CHAT_TOOLS`:
- For a Work or alias: class; all versions with validity at `as_of`; one hop of `based_on`, `transposes`, `amends`, `repeals`, `incorporates` in both directions.
- For a class: its definition and up to 15 member Works.
- Unknown term: "no ontology entry for X", plus the 3 nearest aliases (`difflib`), so the model can retry once with the right name.
- Deterministic; `run_memory` short-circuits a repeated `(term, as_of)` call like any other duplicate read (AGENTS §5.3 loop guard).
- One line in `CHAT_AGENT_SYSTEM` and the research system prompt names the tool. Phase 6 adds binding paths (`binding_of`).

### 4.5 S4: the answer check (lands with Phase 5, "Time")

- **Gate.** In `_submit_chat_impl`: if every cited raw source is an Expression that is superseded at `as_of`, and the DB holds the current Expression of the same Work, the answer is **rejected once**, naming the current file. The second submit is accepted (a `run_memory` counter), so a weak model cannot loop. It never triggers for a past `as_of` (the question asked about the old law) or without an ontology.
- **Badges.** Source lists under answers and Search hits get `[ordinance · Stand B · in force]` / `[superseded since …]`, written by code, never by the LLM.

### 4.6 Measuring "most relevant"

- Gold set `bench/ontology_search_KI.jsonl` on the Phase 0b corpus, about 30 questions with their expected sources, in four groups: (a) document named by abbreviation, (b) by class word, (c) with a date or "alte Fassung", (d) control questions that name nothing.
- `scripts/eval_ontology_search.py` runs `retrieval.search` with the stage on and off (a keyword argument for the script, not an env knob) and reports hit@1, hit@5 and MRR per group.
- **Acceptance (R14):** on ≥ off in every group; group (c) hit@1 = 100 %; group (d) rankings identical.
- The pytest suite covers the logic with synthetic fixtures. The script is the manual quality check at the end of Phases 4 and 5.

---

## 5. Phases

Every phase follows AGENTS §5.6: red test first, green, gate, `/documentation-update`, `/commit-git`. Tests are offline with synthetic fixtures under `tmp_path` (`DATA_ROOT` override), never a real DB.

### Phase 0 — Decisions and fixtures (no production code)

- 0a. Confirm D1–D14. Add milestone **M6: Ontology** to [PRD.md](../PRD.md) (needs your approval) and a row to the IMPLEMENTATION.md phase table.
- 0b. (D6) Seed `data/KI` with 6–8 public legal texts (report §10 Phase 0) and hand-label `bench/fixture_KI_ontology.json`. Needed from Phase 3 on, not for 1–2.
- **Verify:** you have reviewed the decisions and the gold file.

### Phase 1 — Schema, binding, ledger (pure core + store, no UI)

- `uv add pyyaml`. Write `ontology/core.yaml` (report §4.1) and `ontology/legal-de.yaml` (report §9, classes + relations, no cues yet beyond the report's).
- `ontology.py`: `Schema`/`ClassDef`/`RelationDef` dataclasses, `merge_modules`, `validate_schema` (all §5.4 rules), `project(rows)`.
- `ontology_store.py`: `exists`, `load(db)`, `read_rows`, `append_rows`, atomic write helper, flock context manager; path helpers join `db_context` paths (no new env var).
- `wiki_engine.delete_source`: retract ledger rows of the source (behind `exists()`, so DBs without an ontology are untouched).
- **Red tests first** (`tests/test_ontology.py`, `tests/test_ontology_store.py`): cycle in `broader`; dangling `broader`; asymmetric inverse; cue that matches `""`; label missing `de`; two-line definition; projection precedence user > rule > llm; retraction hides a row; user `null` unsets; delete retracts; missing store → `exists()` False and no files created.
- **Verify:** shipped `core.yaml` and `legal-de.yaml` validate clean (a test loads them).

### Phase 2 — Ontology workbench (the user's requirement)

- `ontology_bundle.py`: `render(state, meta) -> str`, `parse(text) -> Bundle | errors`, `canonical(state) -> dict`, `revision_hash`, `flatten`, `diff`, `merge3(base, mine, theirs)`, `bump(old, diff)`, `plan_import(...)` (steps 1–7 of §3.3).
- `ontology_store.apply(plan, user, via, file)` (step 8), `create(db, modules, user)`, `history()`, `snapshot(rev)`, `last_change(human=True|False)`.
- `wiki_engine.log_event(action, detail)`.
- `ontology_ui.py` + one `elif _maint_view == "Ontology"` branch in `app.py`.
- **Red tests first** (`tests/test_ontology_bundle.py`, extend `tests/test_ontology_store.py`, `tests/test_app.py`):
  - round trip: `parse(render(s))` has the same hash as `s`;
  - reformatting, comments, key order, re-quoting, changed `exported_at` → same hash (R6);
  - a changed cue → different hash, diff lists exactly that path;
  - no-op import → `unchanged`, no row, no snapshot, no `log.md` line (R6, R8);
  - stale base: rev-3 export edited, current rev 4 → rev-4-only paths kept, user paths applied, overlapping path reported as conflict (R9);
  - removing a referenced class → refused with the deprecate hint; removing an unreferenced one → allowed;
  - `replaced_by` migrates facts;
  - wrong `db`, unknown source, bad date, unknown class, file > 2 MB, YAML with 1,000 aliases → errors, store unchanged (R5);
  - concurrent apply: preview on rev 4, store moved to rev 5 → apply refused;
  - restore rev 2 → new rev, hash equals rev 2 (R10);
  - reader cannot apply (function-level check), maintainer can;
  - AppTest: no-ontology state (R2); overview shows last human change, not the newer no-op (R8).
- **Verify:** on KI in the running app (port 8520): create from `core`, export, add a local class and two source classes by hand, import, see preview → apply, see rev 2 + last change + Activity log line; re-import the same file → "nothing changed", last change unchanged.

### Phase 3 — Detection at ingest, stamping, upload review

(Report §10 Phase 1, rest.)
- `ontology.detect(text, filename, schema)` (cues on title/head, first 4 KB only), Work-id and date formulas (report §6.3, §7.3). `ONTOLOGY_CLASSIFY_PROMPT` in `prompts.py`; the LLM call in `wiki_engine`; evidence verified verbatim in code (report §7.4).
- Upload review table (app.py:1183) gains *Class*, *Work*, *Version date*, *Supersedes*, prefilled; edits become `by: user` rows. (Built: *Class*, *Work* and a read-only *Other versions*; the existing `effective as of` column is the version date; supersession itself is Phase 5.)
- `ontology.stamp` called from `_okf_apply` (report §4.4). (`index/ontology.json` moved to Phase 4, its first consumer.)
- Each ingest batch writes **one** `via: ingest` change row (only when the hash changed).
- Proposal review panel (inside Ontology → `Proposals`).
- **Tests:** cue precision on the gold file (agreed threshold); F7: `resolve_contradiction` rewrite keeps ontology keys; fabricated quote rejected; ingest of a DB without an ontology is byte-identical to today.

### Phase 4 — Ontology-aware search (S1, S2, S3; §4)

- `ontology.build()` writes `index/ontology.json` (works, versions, classes per source) with the alias/label table and the page→Works map.
- `ontology_query.py`: `resolve(q, view, today) -> QueryFrame | None`, `arm(frame, …) -> list[hit]`, `briefing(frame) -> str`, `audit(frame, hits) -> dict`.
- `lex_index.query(…, sources=None)` filter; the ontology arm in `retrieval.search` and `search_wiki` through one shared helper.
- Briefing injected in `run_chat_agent`, `run_research_agent`, `query_with_sources`; prompt constants in `prompts.py`.
- `ontology_lookup` in `tools.py`; the "Why these sources" panel shows the frame (R15); Search page gets badges and an optional class chip.
- **Red tests first** (`tests/test_ontology_query.py`, extend `test_lex_index.py` (sources filter), `test_embed_index.py` (fusion with the ontology arm), `test_tools.py`, `test_chat_agent.py`, `test_agent.py`):
  - alias match is word-bounded ("StrlSchV" matches, "StrlSchVO-Entwurf" does not unless listed);
  - ambiguous alias with two Works → both kept without `as_of`;
  - a question naming a Work by abbreviation only ranks that Work's chunk first, where the stage-off ranking does not (synthetic fixture);
  - a class word boosts but never removes a non-matching hit;
  - no ontology / corrupt view → `search()` output byte-identical, `resolve` still called once (R12, D12);
  - the first message list of both agents contains the frame when the question names a known Work, and no frame otherwise (R13);
  - the frame contains no text from document bodies (injection test with a crafted source);
  - `ontology_lookup` repeated with the same arguments → `run_memory` stub;
  - one `resolve` call per search on every path (spy) (R12).
- **Verify:** `scripts/eval_ontology_search.py` groups (a), (b), (d) meet R14.
- **As built** ([ontology.md](ontology.md) §Search): the view is an in-memory cache per DB (keyed on file stamps) instead of `index/ontology.json`; alias expansions are part of the restricted ontology arm instead of unrestricted extra queries (they lifted *other* laws that mention the name); the briefing carries ids, file names and dates, not document-derived names; the Search-page class chip is not built. R12's spy test counts `resolve` per search in DBs that have an ontology (without one, the stage stops before resolving).

### Phase 5 — Time

Report §10 Phase 2: Work/Expression registry, `current_expression`, `validity`, the `_is_newer` fix (F2 regression test), succession-aware change notes, `outdated` overlay. In the search stage: time-intent detection in `resolve` (dates, years, "damals", "alte Fassung", "as of"), the validity-order step (§4.2), the S4 gate and badges (§4.5).
- **Tests:** `as_of=2017-06-01` resolves StrlSchV 2001; a change between two Stände is not flagged as a contradiction; S4 rejects a superseded-only answer once and accepts the second submit; S4 is silent for a past `as_of`; a DB without an ontology returns byte-identical results.
- **Verify:** eval group (c) hit@1 = 100 %.
- **As built** ([ontology.md](ontology.md) §Time): validity is derived at query time from version dates and work intervals (no interval-closing ledger rows); a year counts as a date only after a cue word; the eval's older StrlSchV version is synthetic (the public site serves only the current one).

### Phase 6 — Relations, binding, lint, graph

Report §10 Phase 3 unchanged. The Ontology section gains a lint panel; directed typed edges and the pyramid layout go into `build_typed_graph` / `graph_widget`; `ontology_lookup` gains binding paths.

### Phase 7 — Evolution

Report §10 Phase 4, adapted: an in-GUI editor (`st.data_editor` for local classes and facts) that feeds the same import pipeline; cue tester ("matches 14 of 19 sources"); re-classify dry-run/apply (writes `via: reclassify`); agent schema proposals queue; `scripts/export_ontology.py` for SKOS Turtle / JSON-LD.

### Phase 8 — Optional

Classes for concept pages, §-level validity, modules for other DBs (report §10 Phase 5).

---

## 6. Risks

| Risk | Mitigation |
|---|---|
| Stale export silently reverts newer facts | 3-way merge on `base_revision` (§3.3 step 5); conflicts default to "keep current" |
| Two maintainers import at once | flock + revision re-check at apply |
| Hand-edited regex hangs the app (ReDoS) | Cue length cap, compile check, applied only to the first 4 KB; only maintainers can import |
| YAML bombs, huge files | 2 MB cap, `safe_load`, alias-count cap |
| Data loss (no backup under `data/`) | Append-only ledger and change log, full snapshot per revision, atomic replace; restore instead of rewrite |
| A broken ontology breaks the app | Fail open everywhere (R11); errors shown only in the Ontology section |
| `app.py` grows further | UI in `ontology_ui.py`; one branch in `app.py` |
| Suite exceeds 60 s | Pure-module tests carry the logic; at most 2–3 AppTest cases |
| KI has no legal texts | Phases 1–2 use `core` + synthetic fixtures; Phase 0b seeds legal texts before Phase 3 |
| A wrong alias resolution pushes the wrong document up | Exact word-bounded matches only; the ontology arm is one RRF list with a fixed weight, so it cannot swamp the other arms; eval group (d) must stay identical |
| The briefing bloats small-model context | ≤ 600 characters, only when a Work or class matched |
| The S4 gate makes a weak model loop | Rejects at most once per run (`run_memory` counter) |
| Per-keystroke Search gets slower | Resolution is a dict lookup on a cached table (< 5 ms target, asserted in a test with a 5,000-alias fixture) |

---

## 7. Documentation when implementing

- New `docs/ontology.md` (component doc: file format, canonical form, merge rules, change log, permissions); this plan and the report become its rationale.
- IMPLEMENTATION.md: phase row for M6, module-map row (`ontology.py`, `ontology_bundle.py`, `ontology_store.py`, `ontology_query.py`, `ontology_ui.py`).
- [retrieval.md](retrieval.md): the ontology arm, its place in fusion, the validity-order step, the audit fields.
- [configuration.md](configuration.md): only if a knob is added (none planned).
- [ui.md](ui.md): the Ontology section.
- AGENTS.md §5.3, one condensed bullet (headroom is 10 lines): *Ontology schema lives in `ontology/*.yaml` (git) and `data/<DB>/ontology.yaml`; every write goes through `ontology_store.apply` (validated, versioned, logged, append-only). Ontology keys are code-stamped from the ledger, never LLM-written. Valid time ≠ transaction time. `delete_source` retracts ledger rows. Every search runs the ontology stage in code (`ontology_query`); it adds only lexical hits and fails open to today's ranking. See docs/ontology.md.*
