# Low-cost tweaks for a small-model (~4B) agentic RAG loop ("Deep chat")

Scope: the Deep chat loop (raw_search hybrid BM25+embedding → RRF → GGUF cross-encoder rerank; raw_read; wiki_search/wiki_read; think_tool; submit_chat_answer with a code quality gate; run memory; 400-char trimming of old tool results; wrap-up nudge at ~18/40; fallback synthesis from notes). Target: Gemma 4 E4B-class model via Ollama, fully local, at most 1.2x wall-clock time.
Research date: 2026-10-22. Note on currency: several anchor results are older (2023–2024) and are marked as such. Few sources measure exactly the <10B agentic-loop setting. Where a number comes from a larger generator or a non-agentic pipeline, that is stated.

## Q1. Retrieval-side tweaks: which give the best gain per added latency?

### Takeaway
The cheapest high-yield retrieval tweaks are the ones that cost no LLM calls at query time. These are contextual chunk headers computed at index time, hybrid search (already present), cross-encoder reranking (already present), neighbour/small-to-big expansion of top hits, and reordering of the packed context. HyDE is the only query-time LLM rewrite with a measured retrieval gain. Plain query rewriting and decomposition *lowered* retrieval nDCG in the one controlled benchmark found, and they cost 3–6x the retrieval latency.

### Cited Findings
- **Contextual retrieval (Anthropic, Sept 2024, older):** prepending a short LLM-generated context to each chunk before embedding and BM25 indexing lowered the top-20 retrieval failure rate from 5.7% to 2.9% (−49%) with contextual embeddings plus contextual BM25. Adding a reranker brought it to 1.9% (−67%). Contextual embeddings alone gave about −35%. — [Anthropic, Introducing Contextual Retrieval](https://www.anthropic.com/news/contextual-retrieval); figures as relayed by [Maginative](https://www.maginative.com/article/anthropics-contextual-retrieval-technique-enhances-rag-accuracy-by-67) and [CO/AI](https://getcoai.com/news/anthropic-introduces-contextual-retrieval-to-boost-accuracy-of-rag-systems)
- The gains vary by domain. The appendix spans from about 84% (fiction) down to about 41% (Codebases-Vague). The headline 67% is an average. — [Almond AI critique on Medium](https://medium.com/almond-ai/responding-to-anthropics-contextual-retrieval-for-rag-apps-why-context-is-not-all-you-need-af503985aa55)
- **Query transforms, controlled benchmark (Wang et al., EMNLP 2024, older; TREC DL19/DL20, LLM-Embedder base):**
  - Base: nDCG@10 70.20 / 68.76 at 2.61 s / 0.71 s per query.
  - Query rewriting: **67.89 / 65.62** (worse) at 7.80 s / 2.06 s.
  - Query decomposition: **66.10 / 64.95** (worse) at 14.98 s / 2.01 s.
  - HyDE: **75.44 / 73.94** (+5.2 points) at 7.21 s / 2.14 s.
  - Hybrid search: 72.50 / 69.80 at 3.20 s / 0.77 s.
  - HyDE + hybrid: 73.34 / 72.72 at 11.16 s / 2.95 s.
  - HyDE with 1 pseudo-doc plus the query beat 8 pseudo-docs (75.44 vs 75.12) at half the latency.
  - The rewriter was zephyr-7b. HyDE and decomposition used GPT-3.5-class models, so a 4B model's HyDE passage may be weaker. — [Searching for Best Practices in RAG](https://arxiv.org/html/2407.01219v1)
- **Hybrid weighting (same paper):** the best sparse weight was α=0.3 (BM25 weight 0.3, dense 0.7), giving 72.50 vs 70.87–70.67 at the extremes. — [arXiv 2407.01219](https://arxiv.org/html/2407.01219v1)
- **Reranking (same paper, MS MARCO dev, rerank of BM25 top-1000):**

  | Reranker | MRR@10 | Latency (s) |
  |---|---|---|
  | BM25 alone | 11.65 | – |
  | monoT5 (220M) | 31.78 | 4.5 |
  | monoBERT (340M) | 31.69 | 15.8 |
  | RankLLaMA (7B) | 32.35 | 82.4 |

  A small cross-encoder gets almost all of the 7B reranker's gain at about 1/18 of its latency. — [arXiv 2407.01219](https://arxiv.org/html/2407.01219v1)
- **Chunk size and small-to-big (same paper, older; zephyr-7b generator, GPT-3.5 judge):**
  - Faithfulness peaked at 512-token chunks (97.59) vs 2048 tokens (80.37).
  - Small2Big raised faithfulness from 95.74 to 96.67, and a sliding window raised it to 97.41.
  - These are small effects measured with an LLM judge. — [arXiv 2407.01219](https://arxiv.org/html/2407.01219v1)
- **Repacking order (same paper):** "Reverse" packing, with the most relevant chunk placed last, next to the question, was recommended. The scores were close across orders: Avg 0.483 (reverse) vs 0.474 (forward), with "sides" scoring 0.580 on the RAG score. — [arXiv 2407.01219](https://arxiv.org/html/2407.01219v1)
- **Compression (same paper):** abstractive Recomp gave avg F1 32.85 with 59 tokens, vs 31.53 with 139 tokens uncompressed. End-to-end, Recomp added about 0.7 s and raised the RAG score from 0.533 to 0.560. LongLLMLingua was worse (0.539) and slower (+5.2 s). — [arXiv 2407.01219](https://arxiv.org/html/2407.01219v1)
- **RECOMP (ICLR 2024, older):** extractive and abstractive compressors kept performance at compression rates as low as 6%, and output an empty string when the retrieved documents are useless ("selective augmentation"). — [RECOMP, arXiv 2310.04408](https://arxiv.org/pdf/2310.04408)
- **Distractors hurt:**
  - A single topically related distractor lowers accuracy, and four lower it further, across 18 models (Chroma, July 2025). — [Chroma, Context Rot](https://www.trychroma.com/research/context-rot)
  - Needle-question pairs with lower embedding similarity degrade faster as the input grows. — [Chroma, Context Rot](https://www.trychroma.com/research/context-rot)

### Inferences
These are mine, ranked by gain per added latency for this system.
1. **Contextual chunk headers at index time.** This adds zero query-time latency. A deterministic variant needs no LLM: prepend `file title › § heading path › parent section title` to each chunk for both FTS5 and embedding. For German legal text, the § anchor and law title carry most of the "implicit context" that contextual retrieval targets. An optional LLM-generated one-line context can be produced once at ingest by the 4B model, but that costs ingest time only. Expected effect: fewer misses for chunks like "Abs. 3 gilt entsprechend" that are meaningless without their header. This fits a 4B model well because the model does nothing at query time.
2. **Neighbour stitching / small-to-big on the top-k reranked hits.** Return the hit chunk plus ±1 neighbour chunks, or the enclosing § section capped at N chars, in the raw_search excerpt. The cost is a database lookup measured in milliseconds. It reduces the need for the model to choose raw_read correctly, which is a known small-model weak point.
3. **Reranker-score floor plus a relative cutoff.** Drop hits below a calibrated absolute score, or below x% of the top score, and always keep at least 1–2. This costs zero latency and directly targets the distractor effect. Calibrate the threshold on `data/KI`, because cross-encoder GGUF scores are model-specific.
4. **MMR/deduplication over the reranked list.** Before showing hits, collapse hits from the same file and § and drop near-duplicate excerpts (n-gram Jaccard). This costs milliseconds. It raises coverage for the ">=3 unique sources" gate without the model having to search more.
5. **Up-front HyDE or multi-query is optional and should be measured.** HyDE is the only LLM-side query transform with a positive measured retrieval result. It costs one short generation, roughly 1–3 s on a 4B model, once per question rather than per iteration. Multi-query plus RRF is plausible because RRF already exists, but I found no controlled number for it. Plain rewriting and decomposition degraded retrieval in the one benchmark found, so do not add them for retrieval's sake. Decomposition may still help *coverage planning* (see Q2).
6. **Reverse packing in raw_search output.** Put the best hit last, adjacent to the model's next generation, or keep it first and the second best last ("sides"). This costs nothing, but the effect is small.

### Gaps
- No controlled measurement was found for multi-query + RRF vs a single query, or for HyDE when the HyDE passage is written by a ~4B model.
- No benchmark was found specifically on German legal text for contextual chunk headers.
- No public calibration data exists for GGUF cross-encoder score thresholds; a threshold must be fitted locally.

## Q2. Agent-loop tweaks: what does the 2024–2026 evidence say about small models in ReAct loops?

### Takeaway
Small models fail mainly at tool *selection and initiation*, at argument formation, and at using tool output. They also degrade as the context grows and fills with similar-looking distractors. The evidence favours moving decisions out of the model and into code. That means scripting the first searches, keeping the tool set small, trimming and clearing old tool results, keeping structured notes, and using hard step budgets. Plan-then-execute without re-planning is *not* reliably better than ReAct.

### Cited Findings
- **Docker local tool-calling evaluation (2025):** 21 models, 3,570 test cases, 5-tool scenario, maximum 5 rounds.

  | Model | Tool-selection F1 |
  |---|---|
  | qwen3:8B (F16) | 0.933 |
  | qwen3:8B (Q4) | 0.919 |
  | llama3.1:8B | 0.835 |
  | qwen2.5:7B | 0.753 |
  | **gemma3:4B** | **0.733** |
  | llama3.2:3B | 0.727 |

  - The observed failure modes were eager over-invocation, wrong tool choice, invalid or missing arguments, and **ignoring tool responses**.
  - Quantization made no significant difference.
  - qwen3:8B averaged about 84 s latency vs about 5 s for hosted GPT-4.
  - — [Docker blog](https://www.docker.com/blog/local-llm-tool-calling-a-practical-evaluation/)
- **Community Gemma 3 function-calling benchmark:** the 4B model scored 2.0/5 and 1B scored 0.5/5. The 4B model failed at function selection and multi-step composition. This is a community result, not peer-reviewed. — [gemma3-function-calling-benchmarks](https://github.com/gamemaker1/gemma3-function-calling-benchmarks)
- **BFCL multi-turn:** Qwen3-4B-Instruct-2507 is listed at 22.1% multi-turn accuracy, with missed functions and missed parameters as the most common errors. This comes from a secondary aggregator. — [benchmarklist](https://benchmarklist.com/models/qwen3-4b-instruct-2507/)
- **Tool-call propensity failure:** Mistral-Small-3.2-24B made *no* tool calls on a long multi-criterion prompt but called tools correctly on a short single-fact query. The authors read this as a reluctance to start retrieval, not missing capability. — [IntentKV, arXiv 2606.09916](https://arxiv.org/pdf/2606.09916)
- **Failure cascades:** each tool call can fail through the wrong tool, a malformed query, or a timeout. Errors cascade when an agent treats an error message as valid output. — [SoK Agentic RAG, arXiv 2603.07379](https://arxiv.org/pdf/2603.07379)
- **Leading agentic-RAG errors:** on MuSiQue and 2Wiki, entity confusion and wrong strategy are the leading failure categories. — [A-RAG, arXiv 2602.03442](https://arxiv.org/pdf/2602.03442)
- **Practitioner failure modes:** retrieval thrash, tool storms and context bloat, attributed to missing budgets and stopping rules. — [Towards Data Science](https://towardsdatascience.com/agentic-rag-failure-modes-retrieval-thrash-tool-storms-and-context-bloat-and-how-to-spot-them-early/)
- **Peer-reviewed evidence is thin:** a TrustNLP 2026 taxonomy of 33 RAG failure modes found that all 8 agentic orchestration modes lack dedicated peer-reviewed empirical evidence. — [ACL Anthology listing](https://aclanthology.org/people/anupama-garani/unverified/)
- **Context rot (Chroma, July 2025):**
  - Performance falls with input length for all 18 models, far below the context limit.
  - Qwen3-8B began producing random, looping output at about 5,000 words in the repeated-words task.
  - Focused prompts (about 300 tokens) beat full prompts (about 113k tokens) on LongMemEval for all models.
  - Coherent haystacks hurt more than shuffled ones.
  - — [Chroma, Context Rot](https://www.trychroma.com/research/context-rot)
- **Lost in the middle (Liu et al., 2023, older):** performance is highest when relevant information is at the start or end of the context and degrades significantly in the middle. This was shown on multi-document QA and key-value retrieval. Later work finds the effect is task-, length- and model-dependent. — [Liu et al., arXiv 2307.03172](https://arxiv.org/abs/2307.03172); [Found in the Middle, arXiv 2406.16008](https://arxiv.org/pdf/2406.16008)
- **Anthropic context-engineering guidance (2025):**
  - Treat context as finite with diminishing returns.
  - Use minimal, non-overlapping tool sets ("If a human engineer can't definitively say which tool should be used…").
  - Use tool-result clearing as "one of the safest lightest touch forms of compaction".
  - Use structured note-taking outside the context window, just-in-time retrieval, and sub-agents that return distilled summaries.
  - — [Anthropic, Effective context engineering for AI agents](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents)
- **Workflows vs agents:** Anthropic recommends predefined workflows such as prompt chaining and routing when the task is predictable, and agents only when flexibility is needed. — [Anthropic, Building effective agents](https://www.anthropic.com/research/building-effective-agents)
- **Plan-then-execute vs ReAct:**
  - With GPT-4o-mini, Plan-and-Execute scored 0.4503 vs ReAct 0.6161, so ReAct was better on that benchmark. — [GoalAct, arXiv 2504.16563](https://arxiv.org/pdf/2504.16563)
  - Pre-Act, which plans before each action, improved Action Recall by 70% over ReAct averaged across five models, using fine-tuned Llama 3.1 8B/70B. — [Pre-Act, arXiv 2505.09970](https://arxiv.org/pdf/2505.09970)
  - Plan-then-execute fails when the initial plan is flawed and there is no re-planning. — [arXiv 2509.08646](https://arxiv.org/pdf/2509.08646)
- **CRAG relevance grading (2024, older):**
  - A fine-tuned T5-large evaluator scores each (question, document) pair and triggers correct, ambiguous or incorrect actions. With LLaMA2-7B on PopQA, CRAG scored 54.9 vs RAG 50.5, and Self-CRAG scored 61.8 vs Self-RAG 54.9. — [CRAG, arXiv 2401.15884](https://arxiv.org/pdf/2401.15884)
  - A 2026 reproduction with **Phi-3-mini (3.8B)** got 54.4 vs 51.4 for vanilla RAG. The evaluator relies mainly on named-entity alignment, and it is biased toward biographical questions, which hurt ARC-Challenge. — [CRAG reproduction, arXiv 2603.16169](https://arxiv.org/pdf/2603.16169)
- **RL-trained small search agents (Search-R1 line):** with Qwen2.5-7B, Search-R1 scored 0.513 / 0.586 EM on HotpotQA / 2Wiki vs 0.228 / 0.205 for standard RAG. These are Pass@8 numbers from a follow-up paper's table. 3B follow-ups (GTA-RAG at 44.5 EM / 53.6 F1 average) show multi-turn search loops help *after RL training*. This does not transfer to an off-the-shelf 4B model without fine-tuning. — [S³-R1, arXiv 2605.01248](https://arxiv.org/pdf/2605.01248); [GTA-RAG, arXiv 2608.22479](https://arxiv.org/pdf/2608.22479)

### Inferences
These are mine, and each is implementable in code.
1. **Scripted first step ("pre-flight").** Before the model's first turn, code runs raw_search on the user query, plus an optional HyDE or keyword variant, and wiki_search. It injects the deduplicated, reranked top hits as the first tool results. This removes the initiation failure (arXiv 2606.09916) and the wrong-first-tool failure (Docker, Gemma 3 4B). It also pre-satisfies part of the ">=3 distinct searches" gate. Latency: retrieval only, with no extra LLM call, so roughly 0–5% added.
2. **Auto-read of the top original.** If the top reranked raw hit's section has not been opened by iteration ~3, code calls raw_read (section-aware) on it and appends the result. This targets the "ignored tool responses / never opens the source" failure and the gate's ">=1 cited original actually opened" rule. It adds one read, with no LLM call.
3. **Deterministic evidence extraction instead of free-form notes.** After each raw_read, code extracts the sentences or § clauses that best match the query (BM25 or cross-encoder over sentences, top 3–5, with file and § anchor) into an "evidence ledger" kept in the system message or at the tail of the context. The full read result then gets the 400-char trimming sooner. This is RECOMP's extractive idea done without a model, and it puts relevant material at the end of the context, where "lost in the middle" says it is used best. It costs milliseconds.
4. **Shrink the tool menu per phase.** Expose only raw_search, raw_read, think_tool and submit until the evidence ledger has N entries, then add wiki tools; or the other way round. Remove think_tool if the code-side ledger replaces it. Fewer, non-overlapping tools is the Anthropic guidance, and small models' main error is selection. This costs no latency.
5. **Structured, compact tool output.** Return hits as numbered fixed-field lines (`[3] file | § anchor | score | 2-line excerpt`). Return errors as a single explicit `ERROR:` line plus a suggested next call, so errors are not mistaken for content (the cascade risk in arXiv 2603.07379).
6. **Earlier tool-result clearing plus a length budget.** Clear old tool results harder: keep only ledger quotes and hit headers. Keep the live context under roughly a few thousand tokens. Chroma showed 8B-class looping and degradation in the low thousands of words. This should *reduce* wall-clock time because prefill per step gets shorter.
7. **Code-side relevance grading (CRAG-lite) using the existing reranker.** Treat the reranker score as the evaluator. If the top score is below a threshold, code automatically triggers one reformulated search (for example, keywords extracted from the query, or a § number lookup) instead of letting the model decide. CRAG gains were confirmed with a 3.8B generator, but its evaluator was fine-tuned and entity-centric, so local calibration is needed.
8. **Lighter decomposition (plan-lite).** Instead of full plan-then-execute, have one short up-front call produce 2–4 sub-questions. Code then runs one search per sub-question (pre-flight) and checks coverage, meaning each sub-question has at least one ledger quote, before allowing submit. This keeps ReAct's adaptivity, and the evidence that full plan-and-execute beats ReAct is mixed. Cost: one short LLM call, roughly 2–5% of a 20-step run.
9. **Earlier nudge and early stopping.** Nudge when coverage is met (each sub-question has evidence and the gate counts are satisfied), not at a fixed iteration 18. Stop or force synthesis on k consecutive steps with no new ledger entries (thrash detection). This likely *saves* time.

### Gaps
- No peer-reviewed head-to-head of ReAct vs plan-then-execute vs scripted-first-step on a 3–5B off-the-shelf model was found.
- No public tool-calling benchmark for Gemma 4 E4B specifically was found. The only hit was a vendor fine-tune claiming about 95% multi-tool selection, which is self-reported and not neutral ([Featherless](https://featherless.ai/models/roshangrewal/gemma4-e4b-toolcall-v02)).
- No quantitative study was found of repeated-call or looping rates for small models in ReAct, beyond the Chroma looping observation and the Docker 5-round cap.

## Q3. Answer-synthesis tweaks: evidence-first, outline-first, per-claim citations, post-hoc verification, and the 500-word minimum

### Takeaway
Synthesising from a compact, quoted evidence set rather than from the raw tool history is the best-supported tweak, because it combines focused-prompt, compression and position evidence. Per-sentence citations can be checked in code by string or fuzzy matching against the opened sources. NLI-based checking (ALCE) agrees with humans only about 78–85% of the time, so cheap string matching of quoted spans is a reasonable deterministic substitute. No study was found that directly tests a hard word minimum. However, the available evidence makes padding with unsupported claims a plausible risk for small models.

### Cited Findings
- **Focused vs full context:** all 18 models scored significantly higher with focused prompts of about 300 tokens than with full prompts of about 113k tokens on LongMemEval. — [Chroma, Context Rot](https://www.trychroma.com/research/context-rot)
- **Compressed context helps:** compressed context (Recomp, 59 tokens) matched or beat the uncompressed 139 tokens on F1 (32.85 vs 31.53). — [arXiv 2407.01219](https://arxiv.org/html/2407.01219v1)
- **ALCE citation metrics (Gao et al., 2023, older):**
  - Citation recall asks whether the cited passages jointly entail the sentence. Citation precision asks whether each citation is needed.
  - The automatic NLI judgments agree with humans 85.1% of the time for recall and 77.6% for precision.
  - The NLI model cannot detect *partial* support.
  - — [ALCE, arXiv 2305.14627](https://arxiv.org/pdf/2305.14627)
- **Post-hoc citations can be decorative:** the model may answer from parametric memory and then attach a passage. Citation *correctness* (does the passage entail the claim) differs from *faithfulness* (was the passage actually used). This is a practitioner blog. Its claim that "up to 57% of citations are unfaithful" has no traceable primary source. — [tianpan.co blog](https://tianpan.co/blog/2026-04-23-rag-citations-post-hoc-rationalization)
- **Long answers are harder to verify:** long-form factuality checking requires claim extraction and annotation, whereas short answers can be matched against a gold answer. — [arXiv 2505.21072](https://arxiv.org/pdf/2505.21072)
- **Hallucination base rate:** the RAGTruth corpus reports a 43.1% response-level hallucination rate across its RAG tasks, without isolating length. — [RAGTruth, arXiv 2401.00396](https://arxiv.org/pdf/2401.00396)
- **Search-o1 (Jan 2025, design only):** it adds a "Reason-in-Documents" step that condenses retrieved documents before they enter the reasoning chain, to avoid noise injection. I did not verify its numbers in this session. — [Search-o1, arXiv 2501.05366](https://arxiv.org/abs/2501.05366)

### Inferences
These are mine.
1. **Two-pass synthesis from the evidence ledger.** When the gate conditions are met, code builds a fresh, short prompt: the question, the sub-questions, and the numbered ledger quotes with `[Source: file §]`. It does not replay the tool history. The model writes the answer from this prompt alone. This is the existing fallback-from-notes path promoted to the default. Cost: one generation that the run does anyway, with shorter prefill, so roughly neutral.
2. **Outline-first inside the same call.** Ask for headings, one per sub-question, then prose under each with a citation after every factual sentence. This works as a format constraint, which 4B models follow better than open-ended instructions, though that is unmeasured here. No extra call is needed.
3. **Quote-anchored citations, verified in code.**
   - Require citations to be of the form `[n]` referencing ledger entries, or require a short verbatim quote per key claim.
   - Code checks that every `[n]` exists, that its source was raw_read (already gated), and that any quoted span appears in the source by normalised or fuzzy substring match.
   - Code strips or flags unverifiable citations, then either accepts with a warning or requests one repair pass.
   - This is cheap, deterministic, and avoids NLI's 78–85% agreement ceiling for exact-quote claims. It does *not* verify paraphrased claims. For those, an optional sentence-level reranker-score check (claim vs cited chunk) using the existing cross-encoder is a cheap proxy. That proxy is my suggestion and has not been validated.
4. **Reconsider the hard ≥500-word minimum.**
   - No direct evidence was found either way.
   - From first principles, a fixed floor forces a small model to pad when evidence is thin, and padding is where unsupported, uncited sentences arise. Long outputs are also harder to verify.
   - Safer options:
     - Make the floor conditional on evidence, for example about 80–120 words per distinct ledger source or sub-question, with a cap.
     - Or keep the floor but count only sentences that carry a verified citation.
   - Either way, the gate rewards coverage instead of verbosity.
5. **Gate on structure, not only counts.** Replace "≥3 searches" with "every sub-question has ≥1 verified ledger quote". The searches then serve coverage rather than satisfying a counter, and the model cannot satisfy the gate with three near-duplicate queries. The run memory already blocks exact duplicates but not paraphrases.

### Gaps
- No study was found that measures the effect of a minimum-length requirement on faithfulness, for small or large models. This is the main open question and should be A/B-tested locally on `data/KI`.
- No ALCE-style citation-quality numbers were found for <10B generators.
- Search-o1's quantitative results were not retrieved in this session.

## Q4. Which tweaks have measured results on small (<10B) models specifically?

### Takeaway
Measured evidence on <10B generators exists for:
- reranking, HyDE, compression and chunking with 7B generators (Wang et al. 2024);
- CRAG with LLaMA2-7B and with Phi-3-mini 3.8B;
- tool-selection reliability for 3–8B local models (Docker; Gemma 3 4B at F1 0.733);
- RL-trained 3B/7B search agents (the Search-R1 line, which requires training).

For off-the-shelf ~4B models in multi-step ReAct RAG loops, controlled measurements are essentially absent, so local A/B testing is required.

### Cited Findings
- **7B generator (Llama2-7B-Chat, zephyr-7b):**
  - Rerankers: a 220M monoT5 reaches MRR@10 31.78 vs 32.35 for a 7B RankLLaMA, at 4.5 s vs 82.4 s.
  - HyDE gives +5 nDCG points.
  - Rewriting and decomposition give negative results.
  - Recomp compression helps slightly.
  - 512-token chunks are best for faithfulness.
  - — [arXiv 2407.01219](https://arxiv.org/html/2407.01219v1)
- **CRAG:** with LLaMA2-7B, PopQA +4.4 points (54.9 vs 50.5); with Phi-3-mini 3.8B, +3.0 points (54.4 vs 51.4). — [arXiv 2401.15884](https://arxiv.org/pdf/2401.15884); [arXiv 2603.16169](https://arxiv.org/pdf/2603.16169)
- **Tool selection F1:** gemma3:4B 0.733, llama3.2:3B 0.727, qwen3:8B 0.933. — [Docker](https://www.docker.com/blog/local-llm-tool-calling-a-practical-evaluation/)
- **Long context:** Qwen3-8B degenerates into looping output at about 5k words in a simple copy task. — [Chroma](https://www.trychroma.com/research/context-rot)
- **Search-R1 line:**
  - With Qwen2.5-7B, the RL-trained search agent roughly doubles HotpotQA/2Wiki EM over standard RAG (0.513 vs 0.228; 0.586 vs 0.205; Pass@8). — [arXiv 2605.01248](https://arxiv.org/pdf/2605.01248)
  - The 3B GTA-RAG reaches 44.5 EM / 53.6 F1 averaged across its benchmarks. — [arXiv 2608.22479](https://arxiv.org/pdf/2608.22479)

### Inferences
These are mine. Proposed shortlist within the 1.2x budget, ordered by expected value per cost for Gemma 4 E4B.

| # | Tweak | Where | Added latency (estimate) | Mostly code-decided? |
|---|---|---|---|---|
| 1 | Pre-flight scripted searches (query + optional HyDE) injected as first tool results | loop start | +0–5% (1 short gen if HyDE) | yes |
| 2 | Deterministic evidence ledger (sentence-level top-k from each read, with anchors), kept at context tail | after raw_read | ~0 | yes |
| 3 | Synthesis from ledger in a fresh short prompt (promote fallback to default), outline-first, `[n]` citations | submit | ~0 (shorter prefill) | yes |
| 4 | Code citation verification (ids exist, opened, quoted span substring-matches) plus one repair pass on failure | gate | +0–10% (repair only on failure) | yes |
| 5 | Reranker floor and relative cutoff, MMR/dedup by file+§, neighbour-chunk stitching in hits | raw_search | ms | yes |
| 6 | Contextual chunk headers (title › § path) in FTS5 and embedding text | ingest/index rebuild | 0 at query time | yes |
| 7 | Auto-read of top original if not opened by step ~3 | loop | +1 read | yes |
| 8 | Coverage-based nudge/stop and thrash detection (k steps without new evidence) | loop | likely negative (saves time) | yes |
| 9 | Phase-restricted tool menu; structured fixed-field outputs; explicit `ERROR:` lines | tools | 0 | yes |
| 10 | Evidence-proportional length gate instead of a flat 500 words | gate | 0 | yes |

- Items 1, 2, 3 and 8 together plausibly keep wall-clock time at or below today's, because they shorten contexts and runs. HyDE and the repair pass are the only added LLM calls.
- Contextual headers require an index rebuild. The derived-cache rule applies: rebuild via `wiki_engine.rebuild_lex_index()`, never change the query path to compensate.

### Gaps
- No public benchmark exists for Gemma 4 E4B as an agentic RAG driver. All expected gains above are extrapolated from 3.8–8B results and must be verified on `data/KI` with a fixed question set. Measure citation-verification pass rate, the number of unique opened sources, answer faithfulness via sampled human check, and wall-clock time.
- The Search-R1 3B baseline numbers from the original paper were not retrieved, only those from follow-up papers.
