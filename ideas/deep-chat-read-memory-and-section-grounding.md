# Deep chat: missing § text and redundant reads — analysis and fix plan

Status: memo, nothing implemented. Date: 2026-10-16.
Trigger: Deep chat run on `StrlSch_DE` + `StrlSch_DE · Confidential`,
question *"Wie können Rückstände aus der Überwachung entlassen werden?"* (51 s, "5 cited").
Analysis is from the code and the UI trace only; the StrlSch_DE databases were not opened
(AGENTS.md §5.5).

## 1. What the run actually did

| # | Call | What really happened (from code) |
|---|---|---|
| 1 | `raw_search("Rückstand")` | 3 hits. Only one query; never `Entlassung`, never §62's heading words. |
| 2 | `wiki_search([...])` | 27 hits (counted toward the 3-search minimum). |
| 3 | `raw_read(["StrlSchG.md"])` | **The only real read**: bytes 0–16000 of 430 079, i.e. the table of contents / §§ 1–5. |
| 4 | `raw_read(..., offset=1048576)` | Hallucinated 1 MiB offset → "offset past end". Still **marked as read**. |
| 5–9 | `raw_read(..., offset=0)` ×5 | All five were **memory stubs** (`_duplicate_read_stub`): "Already read at step 3 … call `raw_read([...], offset=16000)`". The model ignored the hint five times. Each stub still cost a full LLM turn, ≈ 23 s of the 51 s. |
| 10 | prose, no tool call | `should_continue` → END → `_direct_answer` returned the prose **without any gate**. |

The model never called `think_tool` ("MANDATORY") and never called `submit_chat_answer`.

## 2. Root causes

**RC1: the prose exit skips the quality gate.** `src/chat_agent.py` `should_continue` (≈ l. 144)
ends the graph whenever the last AI message has no tool calls, and `_final_step` →
`_direct_answer` (≈ l. 351/415) hands that text to the user as a normal final answer. The checks
in `_submit_chat_impl` / `_research_gap` (≥ 500 words, ≥ 3 sources, ≥ 1 original read, from
ec60d1d) never ran. A weak model that gives up can skip every grounding rule. Neither the user
nor the trace sees that this happened.

**RC2: grounding is checked per file, not per section.** `_research_gap` (`src/tools.py` ≈ l. 581)
asks only whether *some* window of a cited file was read (`_read_bases` drops the section and the
offset). Citing `[Source: StrlSchG.md §62]` therefore passes after reading only the TOC. The §62
in the answer most likely came from a TOC line, a heading in a search hit, or a wiki page, not from
the section text. That is exactly the "requirements are not in the answer" symptom.

**RC3: a bare read of a § file serves bytes, not law.** `_raw_read_one` (≈ l. 464) returns byte
window 0 for a bare filename. For a 430 KB statute that is the TOC, which is useless content.
Section reads (`StrlSchG.md § 62`) exist and work, but only if the model passes the anchor. The
prompt prefers sections, yet its tool list still advertises `raw_read(filenames, offset=0) … paginate`
(`CHAT_AGENT_SYSTEM`), and weak models take the simplest signature.

**RC4: the duplicate guard detects the loop but cannot break it.** The visited-set works:
reads 5–9 *were* recognised. But the stub only advises, and a model stuck in a loop ignores advice.
The stub burns a turn without new information, so the loop runs until the model gives up (here
via RC1) or `MAX_ITER` is reached.

**RC5: past-end offsets pollute the memory.** `_mark_reads` records offset 1048576 as a read
window. It counts toward `RAW_READ_NUDGE_AFTER` and tells the model nothing useful about the file's
real size.

**RC6: the trace hides the loop.** `gui_trace._READ` summarises a stub with the same header as a
real read ("read StrlSchG.md (offset 0)"), so the user cannot tell five stubs from five reads, or
see that the answer bypassed the gate.

Contributing, not a root cause: retrieval was never asked the right thing. The question contains
§62's heading words almost verbatim (*Entlassung … Rückständen … Überwachung*); a query of those
stems would put §62 first. The model searched only `Rückstand`.

## 3. Decisions (grilled 2026-10-16)

| Topic | Decision |
|---|---|
| Prose exit | **Gate it like a submit.** Run the same gate; on REJECTED feed the reason back and continue (bounded retries), then a *labelled* best-effort answer. |
| Duplicate read | **Auto-advance.** Code serves the next unread unit instead of a stub: the unread § that best matches the question, else the next unread byte window. |
| Bare read on a § file | **Section map + best hits.** A compact § index plus the 1–2 best-matching sections in full. Byte offsets only for files without sections. |
| § grounding | **A cited § must have been read.** Reject a `[Source: file §N]`, or a `§ N` of a cited original named in the prose, whose text was not opened this run; the rejection names the exact `raw_read` call. |
| Memory scope | **Per run** (unchanged). Earlier results are not in a follow-up's context, so cross-turn blocking would hide text. |
| Trace | **Label** memory hits, auto-advances, and gate path. |
| Proof | **Live bench on `data/KI`** (plus the unit tests the gate requires anyway, §6). |

## 4. Design

All logic is deterministic Python in `src/tools.py` / `src/chat_agent.py` / `src/run_memory.py`.
Prompt text changes only in `src/prompts.py` (AGENTS.md §5.3). The visited-set keying
(`_read_key`: `raw:<qualified base>[|sec=<canon>]:<offset>`) stays intact.

### Fix A: gate the prose exit (RC1)

- New graph node `prose_gate` between `agent` and END. When the last AI message has no tool calls
  and no ACCEPTED submit exists, `should_continue` routes to `prose_gate` instead of END.
- `prose_gate` runs `_submit_chat_impl(text)` (pure, already exists):
  - `ACCEPTED` → END; `_final_step` treats the prose as the submitted answer.
  - `REJECTED…`/nudge, with `mem.prose_rejections < CHAT_PROSE_RETRIES` (new env, default 2) →
    append a `HumanMessage` containing the rejection text plus "call the tool it names, then
    `submit_chat_answer`", and route back to `agent`.
  - Retries exhausted → END. `_final_step` prefixes `(best-effort — quality gate not met: <reason>)`,
    the existing best-effort label, now with the reason.
- `prose_rejections` lives in `RunMemory`, which bounds the loop on top of `MAX_ITER`.
- This also closes the same hole for the Quick/research agent if it has a prose exit. Check
  `src/agent.py` when building this.

### Fix B: section-level grounding (RC2)

- New pure helper `_section_read(mem, qbase, canon) -> bool`. True when
  `raw:<qbase>|sec=<canon>:*` is in `mem.reads`, **or** a byte window recorded for `qbase` overlaps
  the chunk's `[char_start, char_end)` (chunks carry offsets; `chunker.load_chunks`). An honest
  pagination read therefore counts.
- `_research_gap` gains a third check over:
  1. every cited ref with a section (`_RAW_CITE_RE` already captures `§62` / `# heading`), and
  2. every `§ N` in the prose that resolves (`_resolve_section`) to an anchor of a **cited**
     original. This limits it to the cited law, so "§ 2 AtG" in a StrlSchG answer is ignored unless
     AtG is cited.
- Rejection text (constant in `prompts.py`) lists at most 3 unread sections with the exact call:
  `REJECTED: you cite § 62 of StrlSch_DE::StrlSchG.md but never read it. Call
  raw_read(['StrlSch_DE::StrlSchG.md § 62']), take the conditions from its text, then submit again.`
- Prose-only mentions (case 2) are enforced once per run (`mem.prose_section_nudged`), the same
  pattern as `low_conf_nudged` / `validity_nudged`. Tagged citations (case 1) are always enforced.
  A weak model cannot ping-pong on an incidental "§ 63 regelt …".
- The `_RAW_CITE_RE` in `chat_agent.py` (no section suffix) differs from the one in `tools.py`.
  Unify it so the "N cited" count and the sources panel agree with the gate.

### Fix C: bare read of a § file → section map + best hits (RC3)

- Condition: there is no section, `offset == 0`, the file has legal anchors (`_section_anchors`),
  and it is longer than `RAW_READ_CAP`.
- Ranking: `lex_index.query(q, scope="raw", sources=[base])`, which already supports a per-file
  restriction. `q` is the run's question plus its distinct search queries. Store the question on
  `RunMemory` (`begin_run(question)`).
- Output, within `RAW_READ_CAP`:
  ```
  ## Raw file: StrlSch_DE::StrlSchG.md — section map (218 sections; best matches read in full)
  ## Raw file: StrlSch_DE::StrlSchG.md § 62            ← full text, marked read (sec key)
  …
  ## Raw file: StrlSch_DE::StrlSchG.md § 61            ← second best, if it fits
  Map near the matches: § 60 Anwendungsbereich… · § 61 Anfall, Verwertung und Beseitigung… ·
  § 63 … · § 64 … (+ Teil/Kapitel headings). Read another with raw_read(['…StrlSchG.md § N']).
  ```
  The map is **not** all 218 entries (≈ 10 KB). It shows ±5 anchors around each hit plus the
  `heading_path` chapter titles.
- Marking: served sections get their `|sec=` keys, so Fix B and Fix D see them as read.
- Fallback: with no index or no hit (`index_health` says no index), keep today's byte window 0.
  Plain and markdown files keep byte and section behaviour unchanged.
- Prompt: in `CHAT_AGENT_SYSTEM`, change the tool line to `raw_read(filenames)`, say a bare name on a
  law returns the best-matching §§, and say `offset` is only for files without sections.
  `RAW_READ_DESCRIPTION` changes to match.

### Fix D: auto-advance on duplicates (RC4, RC5)

`_duplicate_read_stub` becomes `_advance_read`:

1. **Legal file:** the best-ranked unread section by the same ranker as Fix C, provided its score is
   above 0. Serve it in full, mark its `|sec=` key, and use the header
   `## Raw file: X § 62 [memory: repeat of step 3 → serving the next unread best match]`.
2. **Otherwise:** the next unread byte window from `_next_unread_offset` (exists), served in full and
   marked.
3. **Nothing relevant left:** a short stub, `[memory] StrlSchG.md fully explored for this question —
   submit_chat_answer or search another file.` Only this case still costs an "empty" turn.

Also:
- A past-end offset (RC5) is clamped instead of marked. Serve the next unread window with
  `(requested offset 1048576 is past the end; file has 430 079 chars)`.
- An explicit `offset > 0` on a legal file is honoured (deliberate pagination). Only offset-0/bare
  repeats are advanced.
- `RAW_READ_NUDGE_AFTER` stays. Auto-advanced windows count toward it, so pagination still ends in
  a "submit now" nudge.
- AGENTS.md rule: *"keep the visited-set keying intact"*. It is kept. Every served unit is marked
  under its own existing key form, and nothing is served twice.

### Fix E: trace labels (RC6)

- Tool results carry stable markers: `[memory: repeat of step N → …]`, `[memory] … fully explored`,
  `section map`. The prose gate emits a step `{"type": "gate", "content": "REJECTED: …"}`.
- `gui_trace.summarize` shows them as e.g. *"raw_read — repeat of step 3 → served § 62"* and
  *"Quality gate — rejected: § 62 cited but not read (retry 1/2)"*. The answer header shows a
  marker when the answer is best-effort.
- Check whether the Streamlit trace (`src/app.py`) has its own summariser; if so, update it too.

## 5. Expected effect on this run

Step 3 (bare read) returns § 62 (best match for *Entlassung/Rückstand/Überwachung*) plus § 61 and
the map, so the TOC is never served. Steps 4–9 cannot loop: each repeat serves new, relevant
sections, or the run is told the file is exhausted. If the model still writes prose with "§ 62" and
no read, the prose gate rejects it with the exact call to make. The answer that reaches the user
either quotes §62's conditions from its text or is visibly labelled best-effort.

## 6. Verification

**Live bench (decided):** new `scripts/bench_deep_chat.py`, run against `data/KI` with the real
`QUERY_MODEL`.
- Corpus: ingest a public statute into KI (e.g. StrlSchG from gesetze-im-internet.de; it is public
  law, not user content) plus one unstructured long file. **`data/KI` does not exist on this Mac**,
  so run on the GPU box or create KI there first.
- 5–8 questions whose deciding § is known (gold file `bench/fixture_deep_chat_KI.json`, like
  `fixture_ontology_detect_KI.json`): the §62 question, a definitional one (§ 5), a threshold one, and
  one where the answer spans two §§.
- Per run, report: tool calls; **repeat reads served as empty stubs** (target ≤ 1);
  auto-advances; **exit path** (submit-accepted / prose-gated-accepted / best-effort); **cited §§
  not read** (target 0); gold § read (yes/no); **quote overlap**, the share of the answer's sentences
  citing the gold § that share ≥ 6-word n-grams with that chunk's text (deterministic, no LLM judge);
  wall time.
- Run it before the change for a baseline (documents today's failure rate) and after.

**Unit tests (required by AGENTS.md §5.4 red-green, offline, synthetic statute fixture):**
prose exit gated + retry bound; section-level grounding (cited § unread → reject; byte window
overlapping the chunk → accept; prose § of an uncited law ignored); bare read on a § file → map +
best hit marked read; repeat offset 0 → next best unread §; past-end offset clamped, not marked;
trace summary labels.

## 7. Order of work

1. Fix A (prose gate). It is the largest hole, and without it B is bypassable.
2. Fix B (section grounding).
3. Fix C + D together, since they share the per-file ranker and need `question` on `RunMemory`.
4. Fix E (trace labels) + prompt/description edits.
5. Bench baseline → implement → bench after. Docs: `docs/retrieval.md` (read path),
   `docs/architecture.md` (agent loop), `docs/configuration.md` (`CHAT_PROSE_RETRIES`).

## 8. Open points / not decided

- **Question-seeded first search.** Code could run one `raw_search` on the question's stems before
  the model's first turn. Here it would have surfaced § 62 immediately. Not decided. Fix C largely
  covers it once the model opens the file.
- `think_tool` is "MANDATORY" but was never called. There is no code enforcement and none is
  proposed; the gates above do not depend on it.
- Fix B's prose regex needs care with ranges ("§§ 61 bis 64") and "Abs."/"Satz" suffixes. Resolve
  only the § number.
- Retry budget: each prose rejection is one more LLM turn (≈ 5–10 s). The 2-retry default is a
  guess; tune it with the bench.

## 9. Reference chains across files (added 2026-10-16)

Question: when original A cites B and B cites C, and all three are needed, does Deep chat follow
the chain?

### 9.1 Findings

Probe: a synthetic three-file chain in a scratch data root, run through the real tools (scratchpad
`probe/chain.py`). `GesetzA § 7` says "nach § 12 der VerordnungB", and `VerordnungB § 12` says
"nach Anlage 3 der RichtlinieC" (the answer). The wiki pages are linked A→B→C via `related:`.

| Layer | Observed | Verdict |
|---|---|---|
| `wiki_search` | A hit, B appended as `[Wiki linked 1]`, **C never** | Works as designed, one hop only (`linked_pages`, 3 seeds, ≤ 5 neighbours) |
| `wiki_read` | Raw YAML `related:` only, no `[Wiki linked]`, no in-links | **Prompt/code mismatch**: `CHAT_AGENT_SYSTEM` promises `[Wiki linked N]` |
| `raw_read` | "nach § 12 der VerordnungB": nothing resolves it | **No raw→raw reference following at all**; the model must guess `VerordnungB.md § 12` |
| `linked_pages(C)` | Returns B via the in-link | Undirected traversal is correct |
| Ontology | `based_on` / `repeals` / `transposes` / `incorporates` (standards) are detected at upload. `cites` exists in `core.yaml` but is **never detected** | No law→law citation graph |
| Budget | ≈ 4 turns per hop (search, think, read, think); 3 hops plus overhead ≈ 18 turns = `NUDGE_AT` | A three-file chain barely fits; one loop (§1) breaks it |

Building block already present: `ontology_query.resolve()` maps work names and aliases, word-bounded
and genitive-aware ("der Strahlenschutzverordnung" → StrlSchV), to their sources in force. It is
just never applied to text the agent reads.

### 9.2 Decisions (grilled 2026-10-16)

| Topic | Decision |
|---|---|
| Raw references | **Footer pointers**, resolved in code. The model decides whether to follow; unread refs also feed Fix D. |
| Layers in scope | **Raw → raw** (§ / Anlage refs, cross- and same-file) and **ontology `cites` detected at upload**. Not in scope: link expansion in `wiki_read`, and listing a wiki page's sources as refs. |
| Prompt mismatch | **Correct the prompt.** Drop the `wiki_read` `[Wiki linked N]` claim; say that linked pages come from `wiki_search` and that references inside originals come as `raw_read` footers. |
| Depth | **3 cross-file hops**, budgeted. A read that follows a resolved ref grants +2 iterations (capped). |
| Same-file refs | **Free**: listed and followable, no hop consumed (they still cost normal iterations). |
| Ref outside scope | Footer says `(not in scope)`. If the answer relies on it, the gate requires it under `## Open points`. |

### 9.3 Design

**Fix F: reference resolver (pure).** New `src/refs.py` with no I/O.
`find_refs(text, self_file, works, files, anchors_of) -> list[Ref]`, where
`Ref = {target_file, anchor | None, label, kind: same|cross|out_of_scope, quote}`.
- Patterns: `§ N` / `§§ N bis M` (expanded, capped) / `§ N Abs. x Satz y` (resolves to `§ N` only) /
  `Anlage N` / `Artikel N`, each followed within one clause by `des/der/nach <work name>`. A § with no
  work name means the same file.
- Work name → file, in this order:
  1. the ontology alias via `ontology_query.resolve` (version in force via `ontology_time`), when the
     DB has an ontology;
  2. else a match against raw filename stems and the first heading (the same data as
     `_build_raw_index`).

  A name that matches nothing in scope but looks like a law reference (§ plus a capitalised name or
  a known abbreviation shape) becomes `out_of_scope`.
- Anchor check: `_resolve_section(target, "§ N")`. A missing § → `(§ N not found in file)`, never a
  guessed anchor.
- Caps: ≤ 8 refs per section result, deduplicated, ordered by first occurrence.
- Classification: resolution only looks inside `db_context.search_scope()`, so it never names a
  file from a level outside scope (AGENTS.md classification rule; a denied name is treated like a
  missing one).

**Footer in `raw_read`** (`_format_section` / byte windows), status from run memory:
```
References: StrlSch_DE::StrlSchV.md § 12 (unread) · StrlSchG.md § 61 (same file, read) ·
AtG § 2 (not in scope)  — follow with raw_read(['StrlSch_DE::StrlSchV.md § 12'])
```

**Hop accounting (`RunMemory`):**
- `ref_depth: dict[str, int]` keyed like the visited-set (qualified base + canon).
- A read that is not reached through a listed ref has depth 0.
- A read of a ref listed by a depth-d section gets d + 1 if cross-file, or d if same-file.
- Footers of depth-3 sections list cross-file refs as `(hop limit reached)` with no call hint.
- Iteration grant: following a listed unread ref adds `mem.bonus += 2`, capped by
  `CHAT_REF_BONUS_MAX` (new env, default 6).
- `recursion_limit` is fixed when the stream starts. So set it once to
  `MAX_ITER + 2 * CHAT_REF_BONUS_MAX`, and enforce the soft limit in `agent_node`:
  `NUDGE_AT + mem.bonus` for the submit nudge, and a forced final step at `MAX_ITER + mem.bonus`.
- Runs that follow no refs behave exactly as today.

**Interplay with §4:**
- Fix D (auto-advance) ranks unread listed refs **before** lexical best matches, so a looping model
  is pushed along the chain.
- Fix B (section grounding) is unchanged: a referenced section must be read only if it is cited.
- Out of scope: the gate (`_research_gap`) checks every `out_of_scope` ref recorded from a section
  the answer **cites**. Its work name must appear under `## Open points`, or the answer is rejected
  once per run (`mem.open_refs_nudged`, the same bounded-nudge pattern).

**Fix G: ontology `cites` at upload.** In `ontology_detect.detect_relations`, add `_cites(text,
view, self_work)`. Sentences with a § reference plus `_named_works(sentence, view, self_work)`
become `RelationFinding("cites", w, sentence, "proposed")`, deduplicated per target and capped by
`MAX_REFERENCES`, filtered by `_allowed`.
- Proposed status means a maintainer reviews it (ledger rows + `record_change`, AGENTS.md ontology
  rule).
- `ontology_graph.describe` / `lookup` then list `cites` / `cited_by`, so `ontology_lookup` and the
  graph view show the citation network.
- Existing sources gain the edges only on re-detection. Check whether Maintenance → Ontology
  re-classify covers relations; if not, add a "re-detect relations" action.
- Fix G does not drive the footer; Fix F works without an ontology. Fix G adds the persistent,
  reviewable graph.

**Prompt (`src/prompts.py`):** fix the `wiki_read` line in `CHAT_AGENT_SYSTEM` as decided. Add one
line: "When a raw_read footer lists `References:` that the question depends on, follow the unread
ones (raw_read with the given ref); list `(not in scope)` ones under ## Open points."
`RAW_READ_DESCRIPTION` mentions the footer.

### 9.4 Verification

- **Red test:** turn the scratch probe into `tests/test_refs.py` / `tests/test_tools.py` cases:
  - footer lists `VerordnungB.md § 12 (unread)`, flipping to `read` after the read;
  - same-file ref takes no hop;
  - the 4th cross-file hop is shown as `(hop limit reached)`;
  - an out-of-scope ref with no Open points is rejected once;
  - an alias via a stub ontology view resolves to the version in force;
  - a classified file outside scope is never named;
  - `_cites` yields a proposed row for "nach § 12 der StrlSchV".
- **Live bench (§6):** add 2–3 chain questions to `bench/fixture_deep_chat_KI.json`. Each needs a
  gold chain of 2–3 originals in KI, e.g. a StrlSchG § that defers to a StrlSchV §. Add the metrics
  **chain completion** (gold sections read / gold sections), **hops followed**, and **bonus used**.

### 9.5 Order

After §7 steps 1–3 (they make reads trustworthy): **F** (resolver + footer + hop/bonus accounting)
→ prompt fix → **G** (`cites` at upload). The prompt correction is a one-line change and can go in
right away with §7 step 4.
