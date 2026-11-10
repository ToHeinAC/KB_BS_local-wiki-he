# Insights from the RTX 4090 run, ingest timing, wiki pages, outside approaches

As of 2026-11-10. This note re-reads [01_zwischenstand.md](01_zwischenstand.md) against the raw
rows in `bench/results/study_deep_4090_2026-11-09.jsonl` (135 runs, 9 arms × 5 questions × 3) and
`study_ff1_*_4090_91bba8c.json`. It adds the code paths behind the numbers, ingest times, an audit of
the generated wiki pages, and a survey of current outside approaches (PageIndex and others).

**Data access.** Wiki pages were inspected only in `data/KI`. `StrlSch_DE` statements come from
[00_framework.md](00_framework.md) § 6, not from opening that database. Ingest times come from
`data/KI` (`manifest.json` against `wiki/log.md`) and from the ingest rows of `data/usage.jsonl`
(metadata only: database, file count, duration).

## 0. Summary

1. **Retrieval is no longer the main bottleneck. Turning what was read into the answer is.** In 65 of
   135 runs every gold section was read, yet facts were still missed. F03 read its gold in 24 of 24
   runs (all arms except D4) and scored 4 of 48 facts. F10 read § 78 in 24 of 24 runs, and "50 mSv"
   reached the answer in 3.
2. **The closing path decides more facts than any arm.** Answers from `notes-fallback` and `direct`
   reach 15–19 % of the facts; `submitted` and `draft` reach 58 %. All three D2 runs on F02 read both
   gold sections and closed via `ledger`, scoring 0 of 9. The likely cause is the ledger's
   sentence selection in `src/evidence.py`, which can drop a list, an exception clause or a table row
   before the model ever sees it.
3. **About 90 % of generated tokens never reach the answer.** A run produces about 12,000 tokens
   (1,480 per LLM call) for a 675-word answer, about 1,150 tokens. At 151 tok/s that is roughly 70 s of
   the 90 s mean.
4. **Reference-following was hardly exercised.** Only 17 of 135 runs made a single hop, and F06 made
   none at all. The FF3 statement that references help on F02 (H3.4) is not supported: D1 and D3 read
   both F02 gold sections without a hop. Their losses follow the closing path, not retrieval.
5. **Ingest time per document has not changed drastically.** Comparable 30–50 KB Markdown sources
   took 1–2 min in July and 113 s on 24 Oct. Differences between batches follow size and format. One
   new one-off cost: since `d752a47`, the first ingest into a database without vectors embeds the
   whole database.
6. **Wiki pages are coarse, have no locators, and keep growing.** Summaries are near-copies (one is
   larger than its source). Hub pages grow by appending every source. Citations name a file, never a
   § or heading. For statute research the wiki is a map without coordinates.
7. **Outside approaches agree on one point:** structure belongs in code, not in a model's reasoning.
   PageIndex's useful part (a heading/§ tree built without an LLM) fits; its LLM tree search does
   not suit a 4B model. A German statute-KG paper finds that sentence/number-level units beat
   section-level units, and that following citations only pays off when it targets the cited unit.

---

## 1. What the 4090 rows show

### 1.1 Reading ≠ using

All arms except D4, 24 runs per question:

| Question | Gold fully read | Facts | Hit rate per fact |
|---|---|---|---|
| F02 Radon workplaces | 23/24 | 45/72 | Bergwerk 18, Radonheil 15, Wasser… 12 |
| F03 Cs-137 | **24/24** | **4/48** | 1E+4 Bq: 1, 1E-1 Bq/g: 3 |
| F05 Pregnancy | 1/24 | 49/96 | 1 mSv 20, internal exposure 23, **weekly 4, documented 2** |
| F06 Radon chain | 0/24 | 90/144 | 300 Bq 12, without delay 17, **30 months 1**, registration 22, 6 months 20, 6 mSv 18 |
| F10 Eye lens | **24/24** | 35/72 | 20 mSv 19, **50 mSv 3**, 100 mSv 13 |

Two kinds of failure, which call for different fixes:

- **Extraction failure (F03, F10, partly F02).** The section was read, the fact did not arrive. In
  F10 the threshold arrives but the authority's exception does not. In F03 the table row is in the
  context but its values are not.
- **Navigation failure (F05, F06).** The gold set is almost never read in full. The facts that are
  missing almost every time come from the sections no arm found in FF1 (§ 126, § 157) or from the
  second statute (StrlSchV § 55/§ 69 for F05).

Correlation between generated tokens and fact rate: r = 0.10. Between tool calls and fact rate:
r = 0.13. More turns and more text do not buy facts.

### 1.2 The closing path decides

| Closing | Runs | Fact rate |
|---|---|---|
| `submitted` (agent answer, gate passed) | 39 | 0.58 |
| `draft` (best-effort draft) | 17 | 0.58 |
| `ledger` (answer written from the evidence ledger) | 57 | 0.50 |
| `notes-fallback` | 7 | **0.19** |
| `direct` (D4) | 15 | 0.15 |

`ledger` is the most frequent exit. The ledger is filled in code (`evidence.extract` → `_best`):

- Per read block it keeps at most `PER_BLOCK = 4` sentences.
- A sentence qualifies by sharing at least `_MIN_SHARED = 2` six-character stems with the
  **question** (a digit counts as one).
- For core sections it also keeps the lead sentence of each numbered paragraph and each list.
- Sentences longer than 900 characters are clipped at the last comma.

This explains the extraction pattern above, with one caveat: the ledger content is not logged, so
this is an inference, not a measurement.

- An enumerated annex (Anlage 8: mines, radon spas, water works) shares no stems with the question
  "an welchen Arbeitsplätzen … gemessen". The guess is that this is why D2 failed 0/9 on F02 with
  both gold sections read.
- An exception clause ("im Einzelfall … 50 mSv … 100 mSv in fünf Jahren") is a second sentence,
  not a paragraph lead. It competes for 4 slots and may sit behind a comma that `_clip` cuts.
- Table rows (F03) have no stem overlap at all. Only the digit bonus can lift them, and it needs at
  least one shared stem first.

**Diagnostic, cheap:** dump `mem.ledger` per run into the bench row, then check in code whether each
fact regex matches the ledger. "Never selected" and "selected but not used" then become separate,
countable failures.

### 1.3 Where the time goes

| | Mean per run (E0–D3) |
|---|---|
| Generated tokens | ≈ 11,000 (E0: 12,250) |
| LLM calls | 6.5–9.4 |
| Generated tokens per call | ≈ 1,480 |
| Share of generated tokens in the final answer (1.7 tok/word) | **≈ 10 %** |
| Share of run time spent generating text | 91–94 % |
| Prefill | ≈ 2 % |

The remaining 90 % is intermediate text: `think_tool` reflections, drafts the gate rejects, ledger
answers that fail the gate, tool arguments. The rows do not split it per node. That split is the
first instrumentation gap to close. The agent loop also runs at temperature 1.0 with no
`num_predict` (`src/chat_agent.py:252`). `local_summarizer` saw runaway duplicates at 1.0 and settled
on 0.2 plus a cap.

### 1.4 The depth arms measure less than they seem to

- **Hops:** 17 of 135 runs used one; F06 had 0 in all runs. On F02, E0 hopped in 2 of 3 runs, but D1
  and D3 (no references) read both gold sections in 3 of 3 runs anyway. The F02 gap between E0 (9/9)
  and D1 (5/9) therefore does not come from the reference. It runs with the closing path
  (D1 rep 1: `draft`, gold 2/2, 0 facts).
- **D2's robust loss (F02: 0/9)** also comes with gold 2/2 in two of three runs. It is a
  ledger/closing effect, not a retrieval effect. One plausible reading: the Level 2/3 reads matter
  less for finding sections than for which sentences get quoted.
- **Noise:** two identical E1 runs scored 30 and 24 facts (01_zwischenstand). The FF2 decision
  (E0 stays) and the FF3 decision (all depth steps stay) are best read as "no difference detectable
  at n = 3", not as proof that each step helps. The one robust result is that D4 is not viable as
  built.

### 1.5 Measurement caveats

- **Fact regexes** may produce false negatives on notations such as `1 · 10⁴ Bq` (superscript) or
  `10 000 Bq` with a thin space. The answer texts were deliberately not committed, so the scorer
  cannot be audited from git. Keep them locally (gitignored) and re-score.
- `first_usable_s` is 81 % of total time on average. The ledger answer is often ready well before
  the run ends, which is a speed lever by itself (§ 5, A3).
- FF1: hybrid scores below dense alone (16 vs 18 Recall@10); the reranker only recovers part of the
  gap. Fusion with equal RRF weights pulls dense hits down (Anlage 8: rank 5 → 21). This holds on
  both corpora.

---

## 2. Ingest time per document

### 2.1 KI: start (`manifest.added_at`, UTC) against the log entry (UTC, minute resolution, +0–60 s)

| Date | Size | Pieces of 40 KB | Duration |
|---|---|---|---|
| 2026-06-07 | 47 KB | 2 | ≈ 5–6 min (before consolidate, outlier) |
| 2026-06-19 | 31 KB | 1 | ≈ 1.5–2.5 min |
| 2026-07-08 | 41 KB | 2 | ≈ 1–2 min |
| 2026-07-10 | 230 KB | 6 | ≈ 3–4 min |
| 2026-09-23 | 51–53 KB | 2 | ≈ 1–1.5 min each |
| 2026-10-01 | 136 KB | 4 | ≈ 2–3 min |
| 2026-10-24 | 46 KB | 2 | **113 s** (exact, from the usage log) |

### 2.2 Usage log (exact, since logging started on 2026-10-12)

| Database | Files | Duration | Per file |
|---|---|---|---|
| Investing, AVE, KI (single files) | 1 | 40–125 s | 40–125 s |
| LV-SMB (2026-10-14) | 1 each | 334–426 s | 334–426 s |
| JEN-CZ (2026-10-29) | 2–4 | 119–1128 s | 30–376 s |
| FGK JEN CZ (2026-10-30) | 16 | 2248 s | 140 s |
| StrlSch_DE (2026-11-03) | 11 | 2304 s | 209 s |

**Verdict:** for comparable documents (Markdown, 30–50 KB) the time stayed at 1–2 min from July to
late October. No ingest has been logged since the chunker changes (30 Oct – 9 Nov) or the embed
change (9 Nov). The large values belong to large or non-Markdown batches. I did not open those
databases, so file sizes and formats there are unverified. The PDF→Markdown conversion and OCR
path is the likely driver for LV-SMB.

**Cost model, from the code:**

- `ceil(size / 40 KB)` synthesis calls per source, plus one retry when no page block is parsed.
- One `qa_gen` call (≤ 5 questions).
- One translation call per cross-language merge (`_align_language`).
- One description refresh at the end of a batch.
- The chunker, the lexical index and the merge are code and cost seconds.

A 500 KB statute therefore needs about 13 synthesis calls. Time grows linearly with size; the code
changes since September added no LLM step.

**Still to check:**

- `d752a47` makes a database's first ingest without vectors for `EMBED_MODEL` build the whole vector
  index (`embed_index.build()`). This is a one-off delay, scaling with chunk count, that the user
  sees as one slow ingest. Measure it once on KI (delete the vectors in a scratch copy).
- The status line should tell the user that the index is being built.

---

## 3. What the wiki pages are, and why

### 3.1 Observed in `data/KI` (58 content pages, 406 KB from ≈ 965 KB of originals)

| Finding | Evidence | Cause |
|---|---|---|
| Three page types: 21 `source-summary`, 33 `concept`, 4 `entity` | frontmatter `type` | `INGEST_PROMPT` rules 1–2 |
| Summaries are near-copies | `summary-dense-moe-…` is 54.6 KB from a 47.2 KB source, keeping the source's Parts I–VII and references | Prompt: "Preserve relevant passages … in detail", and a later piece extends the same file |
| Hub pages accrete | `concept-agent-workflow.md`: 37 KB, 18 sources, 19 H2 sections with near-duplicate headings ("Definition and Components", "Description and Components", "Components and Processes", …), the definition restated once per source | `_select_affected_pages` (BM25) offers the same generic hubs on almost every ingest (see the `Affected:` lines in `log.md`); `_merge_bodies` appends and deduplicates only identical lines |
| `## Key facts` often holds headings, not facts | `- Agent Workflow`, `- Components of a Workflow` | Prompt rule 3 plus code back-fill; the small model echoes headings |
| `key_terms` are cut stems | `stag`, `optimizatio`, `defin` | `_extract_key_terms` writes stems meant for routing into visible frontmatter |
| Citations name a file only | `## Citations` lists file names, including a duplicate spelling and a wiki page | Prompt asks for `[source_name]`; OKF stamping lists `sources:` |
| Language stays fixed per page | 49 EN, 9 DE | By design (`page_lang`) |

### 3.2 StrlSch_DE (from [00_framework.md](00_framework.md) § 6, not opened)

- 60 pages; `StrlSchG.md` backs 25 of them.
- Tables were not carried over, so the Cs-137 values are not in the wiki.
- F02 facts are in the wiki, but not in its top 5. The F05 wording on internal exposure is missing.
- 21 of 25 pieces were written by a cloud model, so the pages are better than a purely local ingest
  would produce.

### 3.3 Why this matters for research

- **Deep chat uses the wiki as a map** (`wiki_search`/`wiki_read`), but the map has no coordinates.
  A page that says "the operator must measure radon" cannot point to § 127 or Anlage 8. The agent has
  to search the originals again, spending turns and generated tokens.
- **Hubs pollute both search arms.** A 37 KB page with 19 sections matches nearly any query and
  takes wiki-arm slots from specific pages. A routing defect turns into retrieval noise.
- **Statutes do not fit the concept/entity scheme.** Their natural unit is the § / Absatz / Anlage
  tree. The chunker already builds it (`heading_path`, anchors), but the wiki does not use it.
- **Facts the benchmark needs** (numbers with units, deadlines, exceptions, enumerations, table rows)
  are exactly what the paraphrasing ingest flattens or drops.

---

## 4. Outside approaches, mapped to these findings

Collected on 2026-11-10 (web). Licences as stated by each project; items marked * were not
verified in detail.

| Approach | Mechanism | Fit here |
|---|---|---|
| **PageIndex** (VectifyAI, MIT) | PDFs: an LLM detects the ToC, builds a node tree and summarises nodes. Markdown mode: tree from `#` headings, **no LLM**. Query: the chat model reasons over the ToC (titles, node ids, summaries) and fetches page ranges, with no vectors. | **Take the Markdown-mode idea:** a tree built in code from § / Abschnitt / Anlage headings, with node ids and one-line titles. **Skip the LLM tree search:** it assumes a strong chat model (defaults are frontier models; the README says "use the best model you can afford"), and no test with ≤ 8B models was found. The 98.7 % FinanceBench figure is their own Mafin 2.5 system, self-reported. |
| **German statute KG** (Siddig et al., RAGE-KG 2026; paper CC BY 4.0, code licence unchecked) | Regex parse of gesetze-im-internet into Buch→§→Abs→Satz→Nr nodes plus `cites_*` edges | Most relevant. Satz/Nr-level units give ≈ 3× the token-efficient recall of 100-word chunks and beat §-level units. Following citations gives a small gain that disappears when its tokens are counted, **unless the hop targets the cited Satz/Nr, not the whole §** |
| **Contextual Retrieval** (Anthropic) | Prefix each chunk with 50–100 tokens of context before embedding and BM25 | Retrieval failures down 35 % (embeddings only), 49 % (with BM25), 67 % (with rerank), by Anthropic's own numbers. For statutes the prefix can be built **in code** from `heading_path`, without an LLM |
| **Docling / TableFormer** (MIT) | Recovers table structure and header cells | Row-as-record (headers repeated per row) addresses F03 directly. Evidence on Markdown vs key-value is mixed; test on our own data |
| **RAPTOR**, **GraphRAG/LazyGraphRAG**, **LightRAG**, **HippoRAG 2** (MIT) | Cluster summaries, entity graphs, PPR over OpenIE triples | Little fit. They target global sensemaking, and LightRAG names a 30B-A3B model as its local minimum. Our explicit § references are a better graph than LLM-extracted triples |
| **Chain-of-Note** | One reading note per document, then the answer | Adds generated tokens; tested on fine-tuned 7B. Not a fit at our token budget |
| **Provence / XProvence** | 430M model that prunes irrelevant sentences | Matches the "sentence selection" need closely, but **CC BY-NC**, not Apache-compatible |
| **Quote-first, verified in code** | Model quotes first, code checks the quote verbatim, then the model answers | Fits the existing quote gates |
| **Local 7B ablation** (arXiv 2606.21553*, Qwen2.5-7B, HotpotQA) | Agentic vs single pass | 2 iterations reach 95 % of the gains of 5; fixed RRF beats adaptive routing. Points to a short fixed loop |
| **ReWOO** | Plan all tool calls up front | ≈ 5× fewer tokens, planner distilled to 7B. Supports moving the search plan into code |
| **Chain of Draft** | Terse reasoning drafts | Accuracy drops sharply at ≤ 3B. **Avoid** for gemma4:e4b |

What the outside work agrees on: **move structure and selection into code, and give the small model
less, denser and well-labelled text in fewer calls.** That matches this project's rule of keeping
format logic deterministic in code.

---

## 5. Improvements, ordered by expected value per effort

Each item gives its reason and how to verify it. Nothing here is built yet.

### A. Answer path (largest measured loss)

**A1 – Fact-preserving ledger selection.**

- Change in `evidence._best`: for core-level sections, always keep sentences with a number+unit or a
  deadline pattern (`mSv|Bq|µSv|Monat|Woche|Jahr|unverzüglich|im Einzelfall`).
- Keep a whole introduced list, whatever its stems.
- Do not `_clip` away a clause that holds a number.
- For table blocks, keep the row that matches a query identifier (`Cs-137`), together with the table
  header.

*Why:* §1.2. Facts are read and then never offered to the model. *Verify:* the ledger dump from §1.2
first (red), then F02/F03/F10 fact counts for ledger closings.

**A2 – Oracle arm.** Give `gemma4:e4b` exactly the gold sections and the question in one call, and
count the facts.

*Why:* this separates model capacity from pipeline loss.

- If the oracle reaches less than about 70 %, the ceiling is the model. A model arm
  (`qwen3.8:27b` at 64k fits on one 4090, per `local_summarizer`) becomes the largest lever.
- If the oracle is close to 100 %, the losses are in our pipeline and A1/A3 matter most.

Costs about 15 runs.

**A3 – Cut intermediate generation.** One factor per arm:

- `num_predict` caps on non-final turns.
- Temperature 0.3 in the loop.
- A length cap on `think_tool`.
- Stop the run as soon as a gate-passing ledger answer exists (`first_usable_s` is 81 % of total).

*Why:* §1.3. About 90 % of generated tokens, roughly 60 s of 90 s, never reach the answer.
*Verify:* time and facts against E0, and tag every LLM call with its node to get the per-node split.

**A4 – Closing on the fallback cliff.** `notes-fallback` scores 0.19. When the run falls back, write
the answer from the (A1-improved) ledger instead of free notes. *Verify:* E2/E3 F10 rows, where most
fallbacks sit.

### B. Navigation (F05, F06)

**B1 – Structural expansion in code.**

- Add the sibling sections of the same Abschnitt (F06: §§ 126–131 are contiguous) as a level read.
- Add an incoming-reference index: which sections cite § X (F05: StrlSchV provisions that implement
  StrlSchG § 78).
- Following the statute-KG paper, hop to the cited Absatz/Nr, not the whole §.

*Why:* FF1 shows that no search arm reaches § 126 or § 157, and the agent hardly ever hops (§1.4),
so the expansion must not depend on the model. *Verify:* `gold_read` on F05/F06.

**B2 – German decompounding for BM25.** Add an FTS5 `trigram` table (built into SQLite, no
dependency) as a third lexical arm or as a fallback, or split compounds at query time.

*Why:* BM25 drops out on F06 ("Radonwerte", "Radonkonzentration"). *Verify:* the R0/R2 rows of FF1.

**B3 – Weighted RRF or rank-aware fusion.**

*Why:* dense alone beats hybrid on Recall@10 on both corpora. *Verify:* FF1 only, no LLM, minutes.

**B4 – Heading-path prefixes.** Index and embed each chunk with its full `heading_path` (Teil →
Abschnitt → § title) and, for table chunks, the column headers. This is Contextual Retrieval built
deterministically; it extends `a4353bc`, which added only the original's title. *Verify:* FF1.

**B5 – Keep vectors in memory.** Already identified (13–15 ms against 257–417 ms at 100k rows).

### C. Wiki generation (pays off on every later search)

**C1 – Section cards for structured sources.** For a statute (detected in code), generate one card
per § / Anlage **in code**. A card holds:

- the title and heading path;
- defined terms;
- every number+unit and deadline (regex, verbatim);
- outgoing and incoming references;
- the siblings.

Optionally add one short LLM sentence saying what the section regulates. This is the
PageIndex/statute-KG tree, built without an LLM. It gives the wiki coordinates, puts F10's three
thresholds and F06's 300 Bq on a page, and makes B1 cheap.

**C2 – Claim-level locators.** After synthesis, anchor each bullet or sentence in code to its
best-matching chunk of the same source (BM25 within the source) and stamp it as
`[Source: StrlSchG.md § 127]`. The model never writes the locator. *Why:* it turns a wiki hit into a
direct `raw_read` target and saves agent turns.

**C3 – Summaries as digests, not copies.**

- Bound the size, for example to ≈ 15 % of the source with a floor.
- Organise the summary along the source's own heading tree.
- Change prompt rule 1 from "preserve passages in detail" to "list facts and figures verbatim, one
  line each". The originals hold the detail; the chunk index already serves them.

**C4 – Hub hygiene.**

- Damp generic hubs in `_select_affected_pages` (an IDF-like penalty for pages already offered on
  most ingests).
- Cap per-source additions to a page.
- Run `consolidate` with `llm_polish` on pages above a size threshold.
- Make `Key facts` facts: back-fill from `_readable_facts` only when it yields lines with content,
  never headings.
- Keep `key_terms` stems out of visible frontmatter, or store full words.

**C5 – Tables row-as-record** at conversion/chunk time (header repeated per row). This helps the
originals, the ledger (A1) and the wiki at once.

### D. Benchmark hygiene

- Keep answer texts locally (gitignored) and audit the fact regexes for false negatives.
- Log ledger contents, generated tokens per node, and the gate verdicts per run.
- Use a paired design: the same seed across arms, or at least 5 repetitions on the decisive cells.
  Report per-fact hits, not only totals.
- Run one winner per change against `bench/fixture_deep_chat_general.json` (second corpus).

### Not recommended

- An LLM tree search in the PageIndex style, and GraphRAG/LightRAG/HippoRAG. All assume strong
  models and add generated tokens, while our graph (§ references) is explicit.
- Chain of Draft on a 4B model.
- Provence, because of its licence.
- A vector database (FF1, decided).

### Suggested order

1. Instrument: ledger dump, per-node tokens, stored answers.
2. Run the oracle arm (A2).
3. Implement A1 and C5, and test on F02/F03/F10.
4. Run A3 as one-factor arms.
5. Implement B1 + C1 together, since both rest on the same § tree.
6. Implement C2–C4, and add B2–B4 as FF1-only checks.

---

## 6. Results of steps 1 and 2 (2026-11-10, RTX 4090)

Fresh scratch copy of `StrlSch_DE`, gold file `bench/fixture_study_StrlSch_DE_full.json`, the pinned
daemon shared with the idle live app. Stripped rows:

- `bench/results/study_deep_O_4090_4d7a410.jsonl` (oracle, 15 runs)
- `bench/results/study_deep_E0_4090_4d7a410.jsonl` (E0, 15 runs)
- `bench/results/study_deep_E0_callers_4090_f43440b.jsonl` (E0, 5 runs, corrected caller tags)

Rows with answers and ledgers are kept locally in `bench/local/`.

### 6.1 Oracle (arm O): the model is not the main limit

| | F02 (9) | F03 (6) | F05 (12) | F06 (18) | F10 (9) | Total | Time per run | Generated tokens |
|---|---|---|---|---|---|---|---|---|
| O, oracle ledger, 1 call | 5 | 4 | 10 | **18** | **9** | **46 (85 %)** | ≈ 16 s | ≈ 2,400 |
| E0 today | 6 | 0 | 6 | 8 | 5 | 25 (46 %) | 72 s | ≈ 9,800 |
| E0 on 2026-11-09 | 9 | 0 | 7 | 11 | 6 | 33 (61 %) | 90 s | ≈ 12,250 |

- **Given complete evidence, `gemma4:e4b` extracts most facts in one call**, in a fifth of the time.
  The gap of 13–21 facts against E0 is pipeline loss. **A model change is not the next lever.**
- **F02** is the exception: the oracle is worse than E0 there. In rep 0 the Anlage 8 list was in the
  ledger, but the answer stayed with § 127. Putting the referenced annex next to its referring
  section, or flagging the enumeration, is a prompt- or order-side question.
- **F03:** the headerless table makes the model misread the columns ("activity", "half-life"). In
  one answer it also wrote `$1 \text{ E}+4$` in LaTeX, which the fact regex cannot match. Both
  support C5 (row-as-record with headers) and a scorer audit.
- E0 fell from 33 to 25 facts between two days with the same code. This confirms the noise from §1.4.

### 6.2 Where E0 loses its facts (15 runs, 31 missed facts)

Attribution in code (`facts_in_reads`, `facts_in_ledger`), corrected by hand for F10. The 50 mSv
"ledger hit" there was the skin-dose sentence; the eye-lens exception sentence was read in all
three runs but never entered the ledger.

| Where the fact was lost | Missed facts | Share |
|---|---|---|
| Read, not taken into the ledger | 17 | 55 % |
| Never read | 8 | 26 % |
| In the ledger, not used in the answer (upper bound; regexes over-match) | 4 | 13 % |
| Answered from outside the ledger, so not a loss | (2) | — |

**Ledger selection is the largest single loss.** That makes A1 the first change to build. The fact
regexes are too coarse for attribution: several values (50 mSv, 100 mSv, 1 mSv) occur in many
sections. A per-fact anchor (section + regex) would make the attribution exact.

### 6.3 Where the generated tokens go (5 runs, corrected caller tags)

| Caller | Tokens per run | Share |
|---|---|---|
| `chat_agent.agent_node` (agent turns: thoughts, `think_tool`, drafts submitted; ≈ 7,500 submit characters against a 4,200-character answer) | 6,933 | 54 % |
| `chat_agent._write_ledger_answer` (a full answer each time the ledger grows) | 5,292 | 41 % |
| `chat_agent._hyde_search` | 613 | 5 % |

The ledger answer is written several times per run, about 2,000 tokens each. Writing it once, when
the run stops, would save about a third of all generated tokens with no change to the agent. That
is the cheapest form of A3.

### 6.4 Consequences for the order in §5

1. **A1 first.** Make ledger selection keep the number-bearing sentences, the exception clauses and
   the lists of the core sections. Target: "read, not in ledger" towards 0, with E0 facts approaching
   the oracle.
2. **A3 in its cheapest form:** write the ledger answer once, not on every growth. Then cap the
   agent's submitted drafts.
3. Give each gold fact an anchor (section + regex) so loss attribution needs no hand correction.
4. Then B1 + C1 for the 26 % that is never read (F05, F06).

### 6.5 A1, first step: ledger fix (CRLF lists, no cap on core reads)

Rows: `bench/results/study_deep_E0_ledgerfix_4090.jsonl` (E0, 15 runs).

| E0, 15 runs | Before | After |
|---|---|---|
| Facts answered | 25/54 | 19/54 |
| Lost: read, not in ledger | 14 | **7** |
| Lost: in ledger, not used | 7 | 12 |
| Lost: never read | 8 | 16 |
| F10 exception sentence in the ledger | 0/3 | **3/3** |
| In-ledger facts, runs closed by the agent's own answer | 15/21 | **12/12** (8 answered) |

**What it shows:**

- The ledger now holds the facts it was losing.
- The agent's own submitted answer does not use them, while answers written from a complete ledger
  do (oracle, §6.1).
- The rise in "never read" is navigation, which this change does not touch. It is most likely
  noise, but at n = 3 that is not proven.

**Next:** when a run is covered, the final answer comes from the ledger, written once.

### 6.6 The ledger fix reverted: it ends runs too early

The fix was measured twice against the old code, with the same instrumentation (`gate_events`).

| E0, 15 runs each | Facts | Never read | Runs with ≤ 8 tool calls |
|---|---|---|---|
| Old code (two runs) | 25, 24 | 8, 10 | 2, 1 |
| Ledger fix (two runs) | 19, 16 | 16, 16 | 4, 6 |
| Ledger fix + code-added definitions | 21 | 17 | 5 |

Rows: `bench/results/study_deep_E0_prefix_4090_f0d11c8.jsonl`,
`study_deep_E0_ledgerfix2_4090_f0d11c8.jsonl`, `study_deep_E0_ledgerfix_terms_4090.jsonl`.

**Mechanism (inferred, not measured directly):**

1. A run is "covered" with 3 searches and quotes from 2 or more sections.
2. With CRLF lists now quotable, list-only sections such as annexes contribute quotes, so runs are
   covered sooner.
3. On a covered run, an empty agent turn ends the run instead of being sent back.
4. If the ledger answer is then rejected, the run closes from its notes.

**Decision:** the fix is reverted. It should return together with a stricter end rule, for
example that a run may only end on an empty turn once its core sections are quoted.

The code-added definitions are kept on their own: they removed the "explain the defined terms"
rejection, the most frequent one (6 of 9 ledger rejections on the old code).

### 6.7 The definitions reverted too: the three steps only work together

Measured on the old ledger (`bench/results/study_deep_E0_terms_only_4090_93e21f1.jsonl`):

| E0, 15 runs | Facts | F02 | Read, not in ledger | Never read | Closed via ledger |
|---|---|---|---|---|---|
| Old code (two runs) | 25, 24 | 6, 3 | 14, 14 | 8, 10 | 5, 7 |
| Old code + definitions | 19 | **0** | 18 | 8 | 9 |
| Ledger fix + definitions | 21 | 3 | 7 | 17 | 9 |

**What happened:**

- Navigation is unchanged by the definitions change.
- More ledger answers now pass the gate. But the old ledger still misses lists in CRLF text, so
  F02's Anlage 8 list is never in it and all three F02 ledger answers scored 0.
- Before, those runs were rejected and closed with the agent's own draft, which held the list.

**The three steps depend on each other:**

1. The ledger fix makes the ledger complete, but on its own it ends runs early.
2. The code-added definitions let the ledger answer through. That only pays off with a complete
   ledger.
3. A stricter end rule is needed so a run ends only once its core sections are quoted.

**Decision:** revert the definitions as well, and build the three steps together on a branch,
measured before merging.

---

## Sources

- PageIndex: <https://github.com/VectifyAI/PageIndex> (`page_index_classic.py`, `page_index_md.py`,
  `agent_tools.py`, `config.yaml`); Mafin 2.5: <https://github.com/VectifyAI/Mafin2.5-FinanceBench>
- German statute KG: <https://ceur-ws.org/Vol-4312/paper26.pdf>,
  <https://github.com/ibrahimssd/structure-driven-legal-kg-rag>
- Contextual Retrieval: <https://www.anthropic.com/engineering/contextual-retrieval>
- Late chunking: <https://arxiv.org/abs/2409.04701> (needs token-level embeddings, which Ollama
  `/api/embed` does not return)
- Docling: <https://arxiv.org/abs/2408.09869>; tables in RAG: <https://arxiv.org/html/2402.12869v2>
- RAPTOR: <https://huggingface.co/papers/2401.18059>; LazyGraphRAG:
  <https://www.microsoft.com/en-us/research/blog/lazygraphrag/>; LightRAG:
  <https://github.com/HKUDS/LightRAG>; HippoRAG 2: <https://arxiv.org/abs/2502.14802>
- LegalBench-RAG: <https://arxiv.org/abs/2408.10343>
- Chain-of-Note: <https://arxiv.org/abs/2311.09210>; Provence: <https://arxiv.org/abs/2501.16214>
- Local 7B agent ablation: <https://arxiv.org/abs/2606.21553>*; ReWOO:
  <https://arxiv.org/abs/2305.18323>; Agentless: <https://arxiv.org/abs/2407.01489>; Chain of
  Draft: <https://arxiv.org/html/2502.18600v2>
