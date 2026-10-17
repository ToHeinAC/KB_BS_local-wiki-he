# Deep chat: NORM question answered from DIN lab standards — analysis and solution

Status: S1, S2b, S2c implemented 2026-10-17 (see [docs/retrieval.md](../docs/retrieval.md) §Query vocabulary); S2a, S3–S5 open. Date: 2026-10-17.
Trigger: [test_deepchat.md](test_deepchat.md) — Deep chat on `StrlSch_DE` + `StrlSch_DE · Confidential`,
question *"Wie kann NORM (natürliche Radioaktivität) sicher entsorgt werden? Was ist in DE zu beachten?"*
(188 s, "3 cited"). Model: `gemma4:e4b`.
Predecessor: [deep-chat-read-memory-and-section-grounding.md](deep-chat-read-memory-and-section-grounding.md)
(Fixes A–G, implemented). Analysis is from the code and the UI trace only; the StrlSch_DE databases
were not opened (AGENTS.md §5.5). Claims about which §§ hold the answer must be checked against
StrlSchG/StrlSchV once they are ingested into `KI` (see §7).

## 1. Expected vs. actual

**Expected** (reference answer from the user): the topic is the **Rückstände** regime of StrlSchG /
StrlSchV — the Anlage 1 list of residue-producing activities, Überwachungsgrenzen (~1 Bq/g, U-238 +
Th-232 series), the Vermischungsverbot, the two routes (below the limits → Kreislaufwirtschaftsrecht;
above → notification, *Entlassung aus der Überwachung* with the 1 mSv/a dose criterion), plus
worker protection, transport, Altlasten, and competent authorities.

**Actual**: the answer is about laboratory construction (DIN 25425-1: walls, doors, stainless steel
surfaces) and storage rooms (DIN 25422), with a definition of surface contamination from StrlSchV § 1.
None of the Rückstände sections was read. The word *Rückstand* never appears in a query.

| Time | Step | What happened (from code) |
|---|---|---|
| 12:20:32 | `raw_search("NORM Entsorgung", "natürliche Radioaktivität")` | Tokens expand to `norm, entsorg…, naturlich…, radioaktivitat…` (`lex_index._expand_query`). The tokenizer lowercases, so **`NORM` matches `Norm`/`Normen` in every DIN standard**. `radioaktiv…` and `natürlich` occur in nearly every file of this DB and discriminate nothing. The only distinctive token is the colliding one → DIN hits. |
| 12:20:40 | `raw_read(DIN 25425-1, DIN 25422)` | Bytes 0–16000 of two DIN standards — off topic, now "read". |
| 12:20:48 | `raw_read(StrlSchV.md)` | Section map (Fix C) ranks sections by the question + searches (`_ranked_unread`). The best BM25 match for *natürlich / Radioaktivität / Norm* in a long statute is **§ 1 Begriffsbestimmungen** (two `Teil` chunks) — long, term-dense, irrelevant here. |
| 12:20:53–12:21:04 | `raw_search` ×2 (`StrlSchV Abfall`, `StrlSchG Entsorgung`, …) | *Abfall* / *Entsorgung* are the wrong vocabulary too: the statute speaks of *Verwertung*, *Beseitigung*, *Entlassung*. The hits were never read. |
| 12:21:23 | `submit` → REJECTED, 390 < 500 words | The answer was grounded only in DIN text. The word gate asks for **more text**, not **better text**. |
| 12:21:29–35 | `raw_read(DIN 25425-1)` ×3 | Repeats → auto-advance (Fix D) serves more DIN sections (*Abschirmungen*, *Keramische Anforderungen*, *Türen und Fenster*) — the padding that ends up in the answer. |
| 12:22:03–12:23:07 | `submit` ×6 → REJECTED, § 100 cited but not read | The model cited StrlSchV § 100 (presumably seen in a search hit). The gate names the exact call; e4b ignores it **six times** (≈ 65 s). |
| 12:23:10–25 | `raw_read(StrlSchV § 100)` → `submit` ACCEPTED | 616 words, padded with lab-construction requirements. |

## 2. Root causes

**RC1 — vocabulary gap (the main one).** The user's term (*NORM*, *Entsorgung*) is not the law's
term (*Rückstände*, *natürlich vorkommende Radionuklide*, *Verwertung/Beseitigung*,
*Entlassung aus der Überwachung*, *Überwachungsgrenzen*). Lexical search cannot bridge it, and a
4B model does not know the bridge either: it has to *already know* that German law calls NORM
residues "Rückstände" to search for it. No amount of prompting or planning makes e4b produce a
term it does not know. The bridge must come from code + data.

**RC2 — acronym collision.** FTS5 `unicode61` lowercases. An all-caps acronym (`NORM`, `ADR`, `BfS`,
`TENORM`) collides with the ordinary word (`Norm`). In a DB that holds many DIN standards, `NORM`
is the worst possible query token: it matches *every* standard's boilerplate ("Diese Norm …").

**RC3 — section ranking without the right vocabulary.** `_ranked_unread` and `_section_map_read` rank
a statute's sections by BM25 of question + searches. With RC1 the query has no distinctive token, so
the longest, most term-dense section wins: § 1 Begriffsbestimmungen. The reranker is not used for
this in-file ranking.

**RC4 — the word gate rewards padding.** `CHAT_MIN_WORDS=500` and `CHAT_MIN_SOURCES=3` are
proxies for "complete". When the evidence is wrong, they push the model to read *more of the wrong
file* and to cite more unrelated files. The gate checks quantity, never relevance or coverage.

**RC5 — the unread-§ rejection is not self-healing.** The gate already knows the exact call
(`raw_read(['StrlSch_DE::StrlSchV.md § 100'])`) but makes the model issue it. A small model in a
"submit → rejected → submit" rut repeats the same submit. Six rejections × ~11 s = wasted minute.

**RC6 — no relevance check on what is cited.** The answer cites DIN 25425-1 (lab construction) for
a disposal question and passes. `_low_confidence_nudge` looks at the run's *best* passage only, and
the reranker likely scored the DIN hits acceptably on *Norm*. Nothing asks "does each cited
section answer the question?".

**RC7 — the agent loop asks e4b for executive function it does not have.** One free-form ReAct loop
with 8 tools must decide what to search, which hit to open, when the gaps are closed, and how to
satisfy five gate conditions. The trace shows the typical failure pattern of small models:
early commitment to the first hits, repeated identical calls, ignoring corrective feedback.
Fixes A–G made the loop *safer*; they cannot make e4b *plan* better.

## 3. Would a to-do list help?

**Partly — and only if the to-do list lives in code state, not in the prompt.**

- The prompt already demands a plan (`Required workflow` step 1: "think_tool once at the start.
  Identify 2-4 sub-questions"). The trace's `think_tool` notes show it does plan — the plan is just
  built on the wrong terms and is not enforced. A prompt-level to-do list adds nothing.
- A plan made by e4b would look like *"1. search NORM Entsorgung 2. search Grenzwerte NORM …"*.
  It structures the answer but **does not fix RC1/RC2**: every item would still be searched with the
  colliding, non-legal vocabulary.
- What does help small models (plan-and-execute pattern): the model does **narrow, one-shot tasks**
  (decompose, judge relevance of one section, extract facts from one section, write one answer
  section), and **code** owns the loop, the state, the search queries, the reads, and the "done"
  decision. Each LLM call then has one job, short context, and a checkable output.

So: a to-do list is worth it as **structured state driving a code pipeline** (§4, S3), combined
with a **deterministic vocabulary bridge** (S1/S2). The vocabulary bridge alone would already have
fixed this run; the pipeline fixes the class of failures (RC4, RC5, RC7).

## 4. Proposed solution

Ordered by value per effort. S1 + S2 + S4 are small, independent, and fix this run. S3 is the
structural change.

### S1 — Terminology layer in the ontology (fixes RC1)

Add term concepts (SKOS-style `prefLabel` / `altLabel` / `scopeNote`) to the ontology, with the same
governance as everything else there (AGENTS.md §5.3 "Ontology writes"):

```yaml
# ontology/legal-de.yaml (shared, via git) or the DB binding (via prepare_* → apply)
terms:
  rueckstaende:
    pref: Rückstände
    alt: [NORM, TENORM, natürlich vorkommende radioaktive Stoffe, natürliche Radioaktivität,
          NORM-Rückstände, Scales]
    expand: [Rückstand, Überwachungsgrenze, Entlassung aus der Überwachung, Verwertung, Beseitigung]
    works: [StrlSchG, StrlSchV]           # optional: where the concept is regulated
  entsorgung:
    pref: Entsorgung
    alt: [Disposal]
    expand: [Verwertung, Beseitigung, Entlassung]
```

- **Matching in code**: `ontology_query.resolve()` already finds Work aliases word-bounded and
  longest-first; extend it to term labels. Acronym labels (all caps in the YAML) match only
  all-caps in the question (see S2b).
- **Use 1 — query expansion**: `retrieval.search()` adds the `pref` + `expand` stems as an extra
  lexical list (exactly like the existing ontology arm: it adds hits, never removes, and without
  terms the results stay byte-identical). `raw_search("NORM Entsorgung")` then also searches
  `Rückstand Überwachungsgrenze Entlassung Verwertung Beseitigung`.
- **Use 2 — briefing**: `ontology_briefing` adds one line, built by code:
  *"NORM" is called "Rückstände" in StrlSchG/StrlSchV. Search with: Rückstand, Überwachungsgrenze,
  Entlassung.* — the model gets the bridge it cannot produce itself. No document-derived text, so
  the existing briefing rule holds.
- **Use 3 — section ranking**: `_run_query` includes the expansion, so the section map ranks the
  Rückstände sections, not § 1.
- **Population**: a maintainer adds terms in the ontology workbench; an LLM may *propose* terms
  (e.g. from wiki pages that use both words in one sentence — verified by co-occurrence in code),
  a maintainer accepts. Same pattern as class suggestions. A starter set for radiation protection
  (NORM/Rückstände, Freigabe/clearance, Radon, Altlasten, Bauprodukte, Exposition …) is ~30 entries.

Why this over alternatives: it is deterministic, small-model-safe, auditable, exportable (SKOS
`altLabel` fits `ontology_export.py` directly), and it encodes exactly the domain knowledge a 4B
model lacks.

### S2 — Vocabulary from the corpus when no term exists (fixes RC1 without curation) + acronym guard (RC2)

**S2a — pseudo-relevance feedback (PRF) from headings.** When a raw_search's top hits are weak or
scattered (low rerank score, or hits spread over many unrelated files), code runs one extra pass:

1. Take the top-k hits of the **semantic arm** and of **wiki search** (embeddings and wiki pages
   bridge paraphrases far better than BM25; a wiki page about NORM likely says *Rückstände* too).
2. Collect their **section headings** (`heading_path`, e.g. *"§ 61 Anfall und Verwertung von
   Rückständen"*) and the wiki pages' `sources:`.
3. Add the 2–3 heading terms with the highest IDF that are not in the question as a second query
   (RM3-style), and report them in the tool output: `Also searched (from related headings): Rückstand, Entlassung`.

Pure code; reuses `embed_index`, `lex_index`, chunk metadata. Degrades to today's behaviour when
the semantic arm is off.

**S2b — acronym guard.** In `lex_index.query`, a query token that is all-caps and ≥ 3 letters
(`NORM`) keeps a hit only if the chunk text contains it in all-caps (post-filter on the hit text, or
a boost when it does and a strong penalty when it does not). `Norm` in "Diese Norm gilt …" then no
longer matches `NORM`. Applies equally to ADR, BfS, IAEA.

**S2c — use the user's gloss.** The question said *"NORM (natürliche Radioaktivität)"*, but the
gloss was lost: the tokenizer drops the parentheses, the query is an OR of tokens, the agent split
`NORM` and `natürliche Radioaktivität` into separate queries (the prompt asks for 1–2-word queries),
and the DIN standards in this DB are about radioactive substances, so the gloss *raised* their score
instead of excluding them. Fix in code: detect `ACRONYM (expansion)` (and `expansion (ACRONYM)`) in
the question, store it in run memory, and (a) always search the expansion as a phrase / stem query,
(b) keep an `ACRONYM` hit only if it is in capitals (S2b) or the chunk also matches the expansion,
(c) state the pair in the briefing ("NORM here means natürliche Radioaktivität, not 'Norm' =
standard").

### S3 — Guided Deep mode: plan-and-execute with a code-owned to-do list (fixes RC4, RC6, RC7)

Replace the free ReAct loop for Deep chat with a pipeline graph (LangGraph, `src/chat_agent.py`;
logic pure in a new module, e.g. `src/chat_plan.py`). The model never chooses tools; it fills slots.

```
question
  │  code: language, ontology frame, term expansion (S1), point in time
  ▼
[1 Decompose]   LLM, one call, JSON: 3–5 sub-questions          → state.todos
  │             (template per question type, see below; validated in code, fallback = template)
  ▼
for each todo (code loop):
  [2 Retrieve]  code: queries = todo stems + expansions + PRF (S2); retrieval.search(rerank=True);
                pick ≤ 3 sections (best rerank, distinct §), resolve refs (refs.py), read in full
  [3 Judge]     LLM per section, tiny prompt: "Does this text answer: <todo>? yes/no + 1-3 facts,
                each with a verbatim quote"   → code verifies each quote is in the section text
  [4 Close]     code: todo done if ≥ 1 verified fact; else one retry with the next sections /
                PRF terms; then "open"
  ▼
[5 Write]       LLM per done todo: one `##` section from ITS verified facts only
                (short context = high quality from a 4B model)
  ▼
[6 Assemble]    code: direct-answer intro (LLM, 2–3 sentences from the section texts),
                sections, `## Open points` = todos still open (code-written), citations stamped
                in code from the facts' (file, §) — the model never types a citation
```

- **The to-do list is state**, so "done" is a code decision (verified quote present), not a
  `think_tool` claim. Open items are reported honestly instead of padded.
- **Templates make decomposition small-model-safe.** e4b only has to pick a type and fill names:
  - *procedure/obligation* ("Wie … entsorgt / Was ist zu beachten"): scope & applicability →
    limits / thresholds → procedure & authority → obligations & exceptions → related regimes;
  - *definition* ("Ist X ein Y"): definition § → thresholds → exceptions (reuses the existing
    § 1/§ 2 rule);
  - *threshold check*: facts → rule → `evaluate_condition`.
  For the NORM question the template alone yields almost exactly the structure of the reference
  answer.
- **Citations are correct by construction**: every cited (file, §) was read and contributed a
  verified quote, so the unread-§ gate (RC5) and the "cite only what you read" rule cannot fail,
  and irrelevant sections (DIN lab walls) produce no verified facts and are never cited (RC6).
- **Cost**: 1 decompose + ≤ 3 × todos judge calls (short) + todos write calls + 1 intro ≈ 15–20
  short calls, no repeated full-history turns. The current run made ~25 calls, each carrying the
  whole growing history. Expect equal or lower latency; judge calls can run in parallel
  (`gui_session.in_worker` / `ThreadPoolExecutor` with `db_context.bind_context`).
- **Keep the agent loop** as `CHAT_MODE=agent` for strong models and for comparison in the bench;
  make `guided` the default for small models (`QUERY_MODEL` size, or an explicit env).

### S4 — Gate fixes for the existing agent loop (cheap, also useful without S3)

1. **Self-healing unread-§ rejection (RC5).** When `_unread_sections` fires, the submit tool runs
   the named `raw_read` itself and returns the section text with the rejection ("Here is § 100;
   revise the claims that use it, then submit"). On the second identical rejection for the same §,
   drop the claim's citation instead of rejecting again. Saves the six-submit loop.
2. **Coverage instead of word count (RC4).** Lower `CHAT_MIN_WORDS` to ~200 (or 0) and replace it
   with: every sub-question from the plan has a section or is listed under `## Open points`.
   Without S3 the sub-questions come from the first `think_tool`'s PLAN; with S3 from `state.todos`.
3. **Relevance gate on cited sources (RC6).** For each cited (file, §): rerank score of that section
   against the question (the reranker is already loaded on Deep paths). Below the calibrated τ
   (`calibrate.threshold()`), reject once: "*DIN 25425-1 §8.1 does not address the question;
   remove it or explain its relevance*". Fail-open without reranker, like everything in Stage D/E.
4. **Identical-rejection breaker.** If the same rejection reason repeats twice, stop asking:
   end with the labelled best-effort answer (as the prose gate already does after
   `CHAT_PROSE_RETRIES`).

### S5 — In-file section ranking (RC3)

`_ranked_unread` ranks with BM25 only. Rerank the top `RANK_TOP_K` candidates with the cross-encoder
(question + expansion as query), and down-weight `§ 1`/`§ 2` (Begriffsbestimmungen) unless the
question is definitional (the classifier already exists implicitly in the prompt's "Definitional
questions" rule — move the detection into code). Cheap, local to `tools.py`.

## 5. Expected run for the NORM question after S1–S4

1. Briefing (code): *"NORM" = "Rückstände" in StrlSchG/StrlSchV; search Rückstand,
   Überwachungsgrenze, Entlassung.*
2. Template *procedure/obligation* → todos: Anwendungsbereich (Anlage 1), Überwachungsgrenzen,
   Entlassung / Verwertung / Beseitigung, Pflichten & Behörde, angrenzende Regime.
3. Retrieval per todo (expanded + acronym-guarded) lands on the Rückstände sections of StrlSchG and
   the matching StrlSchV sections and Anlagen; DIN standards no longer match `NORM`.
4. Judge/extract verifies quotes; DIN 25425-1 produces no facts and is not cited.
5. Items not covered by the DB (e.g. ADR transport, if no ADR text is ingested) go to
   `## Open points` instead of being filled from memory.

## 6. Alternatives considered

| Option | Verdict |
|---|---|
| Prompt-only to-do list / stronger PLAN instructions | No. The plan already exists; e4b executes it with the wrong terms and does not follow corrections. |
| Let e4b generate synonyms / HyDE ("write a hypothetical answer, search with it") | Weak. HyDE works when the model knows the domain; e4b does not reliably know *Rückstände* ↔ NORM, and hallucinated terms cost searches. Fine as an *optional* extra arm behind the semantic index, not as the bridge. |
| Bigger model for Deep chat | Helps the loop, not the vocabulary gap of BM25; violates the "must work with e4b" constraint. Worth a bench row for comparison only. |
| Lower the gates only (S4) | Necessary but not sufficient: without S1/S2 the run still reads DIN standards, just with a shorter answer. |
| Embedding-only retrieval for raw search | The semantic arm already exists and is fused; it bridges paraphrases but not reliably legal terms of art, and the lexical arm stays the citation source of truth (AGENTS.md §5.3). S2a uses it as a *vocabulary* source instead. |
| Fine-tuning / LoRA on the domain | Out of scope (low-admin, local); the ontology terms carry the same knowledge auditable and editable. |
| Web Deep Research | Web-only by design; local grounding is the point of Deep chat. |

## 7. Implementation plan and verification

Red-green per AGENTS.md §5.6. Offline unit tests on synthetic fixtures; the live check is the bench.

| Step | Change | Red test (must fail first) |
|---|---|---|
| 1 | S2b acronym guard in `lex_index` | Fixture with "Diese Norm gilt …" and "NORM-Rückstände …": query `NORM` ranks only the second. |
| 2 | S1 `terms:` schema in `ontology.py` / bundle validation; `resolve()` matches labels; expansion list in `retrieval.search`; briefing line | Synthetic ontology with term `Rückstände`/alt `NORM`: `search("NORM Entsorgung")` returns the Rückstand chunk; no terms ⇒ byte-identical results (existing invariant test extended). |
| 3 | S4.1 self-healing unread-§; S4.4 breaker | Run memory with a cited unread §: rejection contains the section text; second identical rejection drops the citation / ends best-effort. |
| 4 | S4.3 relevance gate | Stub reranker: cited off-topic section below τ is rejected once; no reranker ⇒ accepted (fail-open). |
| 5 | S5 rerank + § 1 down-weight in `_ranked_unread` | Synthetic statute where § 1 wins BM25 but § 61 wins rerank: section map serves § 61. |
| 6 | S2a heading PRF | Stubbed semantic arm returns a "§ 61 … Rückständen" chunk: second query contains `Rückstand`. |
| 7 | S3 guided pipeline (`chat_plan.py` pure core + graph in `chat_agent.py`), `CHAT_MODE` | Stubbed LLM: todos from template; facts with non-verbatim quotes dropped; open todo appears under `## Open points`; citations only of read sections. |

**Bench**: add the NORM question to `bench/fixture_deep_chat_KI.json` with gold = the Rückstände
sections (labels drafted from the TOC, verified on first run like q6/q7). Ingest StrlSchG.md and
StrlSchV.md (public law) into `KI` — plus one DIN standard if the acronym collision should be part of
the benchmark — then compare `CHAT_MODE=agent` vs `guided`, with and without terms.

Prompts for decompose / judge / write go into `src/prompts.py` as named constants
(`CHAT_PLAN_DECOMPOSE`, `CHAT_PLAN_JUDGE`, `CHAT_PLAN_WRITE`). Docs: `docs/retrieval.md` (terms,
acronym guard, PRF), `docs/ontology.md` (terms schema), `docs/architecture.md` (guided mode).

## 8. Open decisions for the user

1. **S1 location**: general legal terms in shared `ontology/legal-de.yaml` (git), domain terms
   (NORM, Freigabe, …) in the DB binding — or everything per DB?
2. **S3 scope**: replace the agent loop as default, or ship `guided` behind `CHAT_MODE` first and
   decide after the bench?
3. **Word gate**: drop `CHAT_MIN_WORDS` entirely once coverage is checked, or keep a low floor?
4. **Order**: suggested S2b → S1 → S4 → S5 → S2a → S3 (quick wins first, each measurable on the bench).
