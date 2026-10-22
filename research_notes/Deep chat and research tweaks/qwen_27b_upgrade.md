# Upgrading Gemma 4 E4B to Qwen3.8-27B (dense, quantized, < 24 GB, one GPU)

Context from the repo (not web-sourced): this box runs **2x RTX 4090**, the default model is `gemma4:e4b`, every call uses `INGEST_NUM_CTX=32768`, and the pinned daemon runs `OLLAMA_NUM_PARALLEL=1` on one card (docs/gpu.md, docs/configuration.md). So "one GPU, < 24 GB" means one RTX 4090.

## 1. Exact model facts, and how they compare with Gemma 4 E4B

### Takeaway
The name the user gave is real. **`qwen3.8:27b` is an official Ollama library tag** (18 GB, 256K context, tools + thinking + vision), and `Qwen/Qwen3.8-27B` is the official Hugging Face card (released around August 2026). It is a **dense 27B hybrid-attention model**: 48 Gated DeltaNet (linear) layers and 16 gated full-attention layers, in a 3:1 ratio. Native context is 262K, and YaRN extends it to 1M. On every benchmark both vendors publish, it is far ahead of E4B (GPQA 89.2 vs 58.6, LiveCodeBench v6 90.3 vs 52.0). However, Qwen publishes **no BFCL, tau2, RULER, BrowseComp or DeepResearch Bench** numbers for it.

### Cited Findings
- The Ollama library lists `qwen3.8:latest` = `qwen3.8:27b` (18 GB, 256K context, text+image input, capabilities vision/tools/thinking) plus a `27b-mlx` variant. Thinking is on by default and can be turned off per request; there are `reasoning_effort` and `preserve_thinking` controls. — [Ollama library: qwen3.8](https://ollama.com/library/qwen3.8)
- The predecessor `qwen3.6:27b` also exists in the official library: arch `qwen35`, 27.3B LM params plus a 461M vision projector, Q4_K_M, about 19 GB total, capabilities vision/tools/thinking. — [Ollama: qwen3.6:27b](https://ollama.com/library/qwen3.6:27b)
- Official card for Qwen3.8-27B: Apache-2.0, BF16, 27B params ("28B" in the safetensors metadata). 64 layers, hidden size 5120. Layout is `16 x (3 x (Gated DeltaNet -> FFN) -> 1 x (Gated Attention -> FFN))`. DeltaNet has 48 V heads / 16 QK heads with head dim 128. Gated Attention has 24 Q heads / **4 KV heads**, head dim 256. FFN 17,408, vocab 248K. Trained with multi-token prediction (MTP). — [HF Qwen/Qwen3.8-27B](https://huggingface.co/Qwen/Qwen3.8-27B)
- Context: **262,144 native**, up to 1M with YaRN (factor 4). The card warns that static YaRN can hurt short-text quality, so enable it only for long inputs. — [HF card](https://huggingface.co/Qwen/Qwen3.8-27B)
- Thinking is on by default (`<think>`) and turned off with `enable_thinking: False`. `reasoning_effort` takes `xhigh` (the default), `medium` or `low`. `preserve_thinking` is on by default. Recommended sampling with thinking: temp 1.0, top_p 0.95, top_k 20. Non-thinking: temp 0.7, top_p 0.8, top_k 20, presence_penalty 1.5. Serving is OpenAI-compatible (SGLang/vLLM recipes); the card does not document the tool-call wire format. — [HF card](https://huggingface.co/Qwen/Qwen3.8-27B)
- Qwen3.8-27B benchmarks from the card (Qwen3.6-27B in brackets): Terminal-Bench 2.1 73.0 (63.4), SWE-bench Pro 61.7 (53.5), DeepSWE 1.1 42.2 (13.3), CoWorkBench 70.7 (61.0), JobBench 33.4 (21.8), Agents' Last Exam 20.4/42.9 (10.6/27.3), IFBench 79.5 (69.1), GPQA Diamond 89.2 (87.8), HLE 30.8 (24.0), LiveCodeBench v6 90.3 (83.9), OSWorld-Verified 84.3 (63.9), WebArena-Verified 64.8 (48.8), OmniDocBench 1.5 91.1. Several of these (QwenSWEBench, CoWorkBench, JobBench) are Qwen in-house benchmarks. — [HF card](https://huggingface.co/Qwen/Qwen3.8-27B)
- Artificial Analysis independent results: Intelligence Index 34 (#1 of 141 in its class, against a median of 8). It is also **very verbose**: 200M output tokens to run the index, against a median of 82M (verbosity rank 25/27). API speed is 40.3 tok/s. No sub-scores (tau2, AA-LCR) are shown on the page. — [Artificial Analysis](https://artificialanalysis.ai/models/qwen3-8-27b)
- Gemma 4 E4B (official card): 4.5B effective / 8B with per-layer embeddings, 42 layers, 512-token sliding window interleaved with global layers, **128K context**, native function calling, thinking toggled by the `<|think|>` token. Scores: MMLU-Pro 69.4, GPQA 58.6, LiveCodeBench v6 52.0, **Tau2 (avg of 3) 42.2**, BigBench Extra Hard 33.1, MMMLU 76.6, **MRCR v2 8-needle 128K 25.4** (31B dense: 66.4), OmniDocBench edit distance 0.181. Supports 35+ languages; pretrained on 140+. — [HF google/gemma-4-E4B-it](https://huggingface.co/google/gemma-4-E4B-it)
- Independent figures for E4B: tau2-bench 26.0%, Long-Context Reasoning 22.0% (Artificial Analysis evals quoted by a third party). — [computeprices.com](https://computeprices.com/models/gemma-4-e4b)

### Inferences
- The two models can be compared on GPQA (+30.6 pts) and LiveCodeBench v6 (+38.3 pts). In both cases Qwen3.8-27B is in a different class from E4B, and also above Gemma 4 31B dense (84.3 / 80.0).
- For agentic tool use there is no head-to-head tau2 or BFCL figure. The available proxies (IFBench 79.5, Terminal-Bench 73.0, WebArena 64.8, Agents' Last Exam) all point to multi-step tool-use ability far above E4B's 42.2 vendor tau2 (26.0 independent).
- The hybrid architecture matters for this system: only 16 of 64 layers keep a growing KV cache, so long context is cheap in VRAM compared with a classic dense 27B (see section 2).

### Gaps
- No published BFCL, tau2-bench, RULER, LongBench, MRCR, BrowseComp or DeepResearch Bench numbers for Qwen3.8-27B (not on the card or the Artificial Analysis page). Long-context quality beyond the 262K spec is unverified.
- The tool-call wire format (Hermes JSON vs Qwen3-Coder XML) is not documented on the card.

## 2. VRAM math for < 24 GB: quants, KV cache, context fit, quant quality loss

### Takeaway
**Q4_K_M or UD-Q4_K_XL (about 16.5–18 GB) plus 32K–64K of F16 KV cache fits one 24 GB card.** The KV cost is only about 64 KiB/token, because just 16 attention layers with 4 KV heads store K/V. Independent tests show Q4_K_M is statistically indistinguishable from BF16 on GPQA, IFBench and Terminal-Bench. Q6_K (about 22–23 GB) leaves almost no room for context on 24 GB. Q8_0 (29 GB) does not fit.

### Cited Findings
- Quant sizes, from secondary sources that disagree slightly: Unsloth UD-IQ2_XXS 7.27 GB, UD-Q2_K_XL 9.83 GB, UD-Q3_K_XL 13.15 GB, UD-IQ4_XS 14.25 GB, UD-Q4_K_M 16.46 GB, UD-Q4_K_XL 17.56 GB, UD-Q6_K 21.98 GB, Q8_0 29.05 GB, BF16 54.66 GB. Another guide lists Q4_K_M 17.1 GB, IQ4_XS 15.7 GB, and the ggml-org Q4_K_M at 19.0 GB. — [besthub.dev quant guide](https://www.besthub.dev/articles/qwen3-8-27b-quantization-selection-guide-match-your-hardware-to-the-right-gguf-version-d0090eaae45d), [techplained](https://www.techplained.com/run-qwen-3-8-27b-locally) (via search summary); a third source lists Q4_K_M 17.1 GB, UD-Q4_K_XL 17.9 GB, Q6_K 22.9 GB, NVFP4 about 16.5 GB (Blackwell only) — [Context Studios](https://www.contextstudios.ai/blog/qwen-3-8-27b-hardware-guide)
- The Ollama default `qwen3.8:27b` is 18 GB. — [Ollama](https://ollama.com/library/qwen3.8)
- Quesma benchmark of Unsloth GGUFs on llama.cpp with **F16 KV (about 2.3 GB per 32K tokens)**. Q4_K_M (17 GB) showed "no noticeable difference from BF16" on GPQA Diamond, IFBench and Terminal-Bench 2.1, and they say it fits 24 GB with about 64K context. UD-Q2_K_XL (10.7 GB) drops slightly on GPQA and clearly on Terminal-Bench, and uses about 25% more output tokens. The 1-bit IQ1_M and IQ1_S quants collapse to random-guess level. No numeric KLD was given. The authors note that users report **KV-cache quantization is more sensitive** (untested). — [Quesma](https://quesma.com/blog/qwen38-27b-quantizations-benchmarked/)
- NVIDIA NVFP4 vs BF16: GPQA 88.01 vs 88.92, Terminal-Bench 74.02 vs 75.56. — [HF nvidia/Qwen3.8-27B-NVFP4](https://huggingface.co/nvidia/Qwen3.8-27B-NVFP4) (via search summary)
- Mean KLD (secondary source): UD-IQ1_S about 0.43, UD-Q2_K_XL about 0.09. A competing quantizer claims 0.0325 vs 0.0484 for Unsloth at 13.8 GB (3-bit class). Unsloth's own KLD table was not retrieved. — [search summary of besthub/HF discussion](https://huggingface.co/Qwen/Qwen3.8-27B/discussions/65)
- Measured VRAM (Hardware Corner, Q4_K_S 16.68 GiB, llama.cpp with flash attention, MTP off): 4K 18 GB, 8K 18 GB, 16K 19 GB, **32K 20 GB, 64K 22 GB**, 128K 26 GB, 256K 34 GB. — [Hardware Corner](https://www.hardware-corner.net/qwen3-8-27b-hardware-tests/)
- Community: about 64 KB/token in BF16 across the 16 full-attention layers, and FP8/q8 KV halves it. The two 2.5 GB BF16 embedding matrices can be requantized to int8 to free 2.6 GB. Rule of thumb: 24 GB holds 64K out of the box, and 262K only with tuning. — [Context Studios](https://www.contextstudios.ai/blog/qwen-3-8-27b-hardware-guide)
- A 24 GB recipe uses `--cache-type-k q4_0 --cache-type-v q4_0`, because without KV flags context creation fails past about 90K tokens with 17 GB of weights. A 5090 guide uses q8_0 KV. — [sudoingX/qwen38-mtp](https://github.com/sudoingX/qwen38-mtp), [DataCamp](https://www.datacamp.com/tutorial/how-to-run-qwen3-8-27b-locally) (via search summary)

### Inferences
- KV math from the official card (16 attention layers x 4 KV heads x 256 dim x 2 (K,V) x 2 bytes) gives **64 KiB/token F16**: 16K ≈ 1 GiB, 32K ≈ 2 GiB, 64K ≈ 4 GiB, 128K ≈ 8 GiB. q8_0 (about 8.5 bits) is roughly 34 KiB/token, and q4_0 is roughly 18 KiB/token. This matches Hardware Corner's +2 GB from 4K to 32K and Quesma's 2.3 GB per 32K. The DeltaNet layers add a fixed recurrent state per sequence, which does not grow with context. My estimate is about 0.15 GB per sequence (48 x 48 x 128 x 128 fp32), not sourced.
- Fit table for one RTX 4090 (24 GB), with about 1.5 GB of compute and graph overhead assumed:
  - UD-Q4_K_XL / Q4_K_M (16.5–18 GB) + F16 KV: 32K comfortable (about 20 GB measured), 64K tight but works (about 22 GB measured).
  - Q4_K_M + q8_0 KV: about 128K (around 22 GB).
  - IQ4_XS (14–15.7 GB) + q8_0 KV: 128K with headroom.
  - Q5_K_M (about 19–20 GB, inferred from the bit width) + F16 KV: about 16–32K.
  - Q6_K (22–23 GB): only a few K of context. Not practical on 24 GB.
  - Q8_0: does not fit.
- The project's existing 32K `num_ctx` keeps working unchanged at Q4 with F16 KV, using about 20 GB.
- Because Quesma flags KV quantization as "more sensitive", prefer F16 KV up to 64K. Use q8_0 only when a whole-document read needs more.

### Gaps
- No verified per-quant KLD/perplexity table from Unsloth or bartowski. No measured quality impact of q8_0/q4_0 KV on this hybrid model.
- Whether Ollama's `OLLAMA_KV_CACHE_TYPE` applies cleanly to the `qwen35` hybrid arch was not verified.

## 3. Throughput on a 24 GB card vs a 4B model; the 40-iteration loop and parallel researchers

### Takeaway
On an **RTX 4090 with llama.cpp at Q4, expect about 46 tok/s generation and about 2,900 tok/s prefill at 4K, falling to about 38 / 1,900 at 64K**. MTP self-speculation adds about 1.6–1.8x on decode. That is roughly 3–5x slower decode than a 4B-class model. The model is also very verbose with thinking at xhigh, so a 40-step tool loop that takes minutes on E4B could take tens of minutes unless reasoning effort is lowered.

### Cited Findings
- RTX 4090 (llama.cpp, Q4_K_S, flash attention, MTP off), PP/TG tok/s: 4K 2963/46.2, 8K 2854/45.5, 16K 2679/44.3, 32K 2367/42.2, 64K 1918/38.4. RTX 3090: 4K 1308/40.3, 32K 977/37.0, 64K 767/34.0. The RTX 5090 numbers in the same table oddly fall below the 4090 beyond 8K (32K: 1146/29.0), which looks like a measurement anomaly. — [Hardware Corner](https://www.hardware-corner.net/qwen3-8-27b-hardware-tests/)
- MTP speculative decoding on one RTX 3090 (llama.cpp, `--spec-draft-n-max 2`): 41.55 to 66.39 tok/s (+59.8%), but output is not bit-exact with greedy decoding. — [hackmd thc1006](https://hackmd.io/@thc1006/qwen3-8-27b-speculative-decoding-rtx-3090) (via search summary). A 1.81x gain was also reported with `--spec-type draft-mtp` at depth 3, and 98 tok/s with Q6 + MTP on a 5090. — [Context Studios](https://www.contextstudios.ai/blog/qwen-3-8-27b-hardware-guide)
- Tuned vLLM on a 3090 (power-limited to 250 W): about 114 tok/s single-user at 64K, and about 1,000 tok/s aggregate across 64 parallel requests. — [Context Studios citing syv-ai/qwen38-27b-rtx3090](https://www.contextstudios.ai/blog/qwen-3-8-27b-hardware-guide)
- Verbosity: 200M output tokens to run the Artificial Analysis index, against a median of 82M. — [Artificial Analysis](https://artificialanalysis.ai/models/qwen3-8-27b). Quesma: the default xhigh effort uses about 8K reasoning tokens per GPQA question and "can overthink". — [Quesma](https://quesma.com/blog/qwen38-27b-quantizations-benchmarked/)
- Overthinking thread: one user attributes it to broken `ssm_conv1d` scales and shared an "SSMFIX" BF16 model. Others dispute this. The thread has no published benchmarks. One user reports about 50 tok/s at Q6_K with 128K context and no looping. — [HF discussion #76](https://huggingface.co/Qwen/Qwen3.8-27B/discussions/76)
- E4B reference point: about 19.6 tok/s on an M4 16 GB (not comparable to a 4090). — [omlx.ai](https://omlx.ai/benchmarks/5ptewmtx). The repo's docs/gpu.md has local E4B measurements on this box (94 tok/s single-card, 170 in a split-related comparison; see AGENTS.md §GPU).

### Inferences
- Decode budget for a 40-iteration Deep chat loop, assuming each step emits about 300 thinking + 150 tool-call tokens at medium effort: about 18K tokens ≈ 6.5 min at 46 tok/s, or about 4 min with MTP. At xhigh effort (often more than 1–2K thinking tokens per step) this becomes 15–30+ min. **Set `reasoning_effort` low/medium, or turn thinking off for tool-selection turns, and use xhigh only for the final synthesis.**
- Prefill is cheap: about 2,400 tok/s at 32K means re-reading a 32K context takes about 13 s. Ollama's prefix cache, once working, avoids most of that.
- Parallel researchers in open_deep_research: with `OLLAMA_NUM_PARALLEL=N`, Ollama allocates `num_ctx` of KV per slot. On a hybrid model that is only about 2 GiB per 32K slot (F16), so 2–3 parallel 32K slots fit next to Q4 weights (around 20 + 2x2 GiB is too tight; around 2 slots with q8_0 KV). That is much better than a classic dense 27B, but llama.cpp/Ollama batch throughput is far below vLLM's. The DeltaNet recurrent state is also per sequence.
- One option on this box: put E4B on the second 4090 as a separate pinned instance, which avoids NUM_PARALLEL entirely (the project already pins one model per card).

### Gaps
- No Ollama-specific (vs raw llama.cpp) tok/s measurements for qwen3.8:27b on a 4090. Whether Ollama exposes MTP speculative decoding for this model is not confirmed. An Ollama issue mentions `draft_num_predict` defaults, which suggests some draft support exists.
- No measured multi-slot (`NUM_PARALLEL` > 1) throughput for this model in Ollama.

## 4. What improves, and which guards could be relaxed

### Takeaway
The gains should be large in instruction following (IFBench 79.5), multi-step agentic work (Terminal-Bench, WebArena, OSWorld, Agents' Last Exam roughly doubled vs Qwen3.6) and reasoning. The 262K native context lets Deep chat read whole documents instead of 16 KB windows. Treat the guards as **telemetry first, then relax**: keep the code-enforced grounding gate (it is a correctness rule, not a small-model crutch), and loosen the crutch guards (wrap-up nudges, 400-char tool-result trimming, fallback synthesis) only after measuring. Ollama's tool-calling path for this model family has had real bugs, so structured-output reliability has to be verified on the installed Ollama version.

### Cited Findings
- IFBench 79.5 (Qwen3.6-27B 69.1; Opus 4.6 Max 62.5). WebArena-Verified 64.8. Agents' Last Exam 20.4/42.9 vs 10.6/27.3. JobBench 33.4 vs 21.8. — [HF card](https://huggingface.co/Qwen/Qwen3.8-27B)
- E4B: Tau2 42.2 (vendor) / 26.0 (independent), MRCR v2 128K 25.4%, Long-Context Reasoning 22%. — [HF Gemma 4 E4B](https://huggingface.co/google/gemma-4-E4B-it), [computeprices](https://computeprices.com/models/gemma-4-e4b)
- `preserve_thinking` (on by default) keeps prior reasoning across turns. It is aimed at agentic multi-turn use, but it grows context. — [HF card](https://huggingface.co/Qwen/Qwen3.8-27B), [Ollama qwen3.6](https://ollama.com/library/qwen3.6:27b)
- Ollama hang for qwen3.8:27b in agents (#17839 on 0.32.13): a client timeout during a long prefill broke the prefix cache, so retries looped. Fixed in v0.33.0 (one user says not fully). Ollama was at 0.40.3 as of Oct 13, 2026. Tool-call issues #18913 and #18872 are still open. Thinking toggles did not change the hang. — [Betterclaw (vendor blog; issue numbers unverified)](https://www.betterclaw.io/blog/qwen-3-8-27b-tool-calling-fails-agents-fix)
- Precedent: Ollama issue #14493. Qwen3.5-27B tool calling broke because Ollama mapped it to the Hermes JSON parser while the model was trained on the Qwen3-Coder XML format. Separate reports say qwen3.5 models emit thinking but no structured tool call through Ollama. — [ollama/ollama#14493](https://github.com/ollama/ollama/issues/14493), [zeroclaw#3079](https://github.com/zeroclaw-labs/zeroclaw/issues/3079)
- German: no German-specific or MMLU-ProX score for Qwen3.8-27B was found. An independent 80-language test found translation strong on major languages and weak on low-resource ones. — [MindStudio](https://www.mindstudio.ai/blog/qwen3-8-27b-vision-multilingual-test). E4B: MMMLU 76.6, 35+ languages. — [HF Gemma 4 E4B](https://huggingface.co/google/gemma-4-E4B-it)

### Inferences (mapped onto this repo's guards)
- **Keep:** the `[Source: ...]` original-document gate (`_submit_chat_impl`), the run_memory duplicate-search blocking (cheap, model-agnostic), and code-side language detection (`src/lang.py`). These are design rules from AGENTS.md, not small-model crutches.
- **Relax first (measure each):**
  - Tool-result trimming from 400 chars to a few thousand chars or whole sections. KV is cheap: 32K costs about 2 GiB.
  - `RAW_READ_CAP` 16 KB to 32–64 KB, or whole sections, with `num_ctx` 64K.
  - Wrap-up nudges can fire later.
  - Fallback synthesis rarely triggers but should stay as a safety net.
  - The ≥500 words / ≥3 searches thresholds can move from hard rejects to soft hints.
- **New possibilities:**
  - True multi-document comparison in one context: 64K at Q4 with F16 KV, or about 128K with q8_0 KV.
  - Self-verification passes, such as a citation check of the draft answer against quoted originals.
  - Parallel tool calls in one turn. This depends on Ollama's parser and is unverified for qwen3.8.
  - More reliable `with_structured_output` in open_deep_research (supervisor ConductResearch/ResearchComplete tool calls, clarify-with-user schema). This follows from IFBench and agentic scores but is not directly measured.
- German: likely at least as good as E4B given the scale (inference, unsourced). Keep the code-pinned language directives regardless.

### Gaps
- No direct measurement of Qwen3.8-27B structured-output or JSON-schema adherence via Ollama. No parallel-tool-call support confirmation in Ollama's qwen3.8 parser.
- No German benchmark.

## 5. Hybrid setups: 27B planner/writer + E4B workers, speculative decoding

### Takeaway
Built-in **MTP self-speculation** (llama.cpp `--spec-type draft-mtp` / `--spec-draft-n-max 2–3`) gives the speedup without a second model: +60–80% decode. That is a better first step than a separate draft model. A role split (27B for supervisor/planning/final report, E4B for researcher summarization/compression) fits this box naturally, with one model per 4090. It keeps the parallel researchers fast while the quality-critical steps get the 27B.

### Cited Findings
- MTP: +59.8% on a 3090 (`--spec-draft-n-max 2`), not bit-exact. Use `--spec-draft-n-max 1` for reproducibility. A Q4_0 MTP drafter had the best acceptance; a Q5/Q6 drafter cost about 26.6% throughput. Sources conflict on whether the MTP head ships inside the main GGUF or as a separate file. — [hackmd thc1006](https://hackmd.io/@thc1006/qwen3-8-27b-speculative-decoding-rtx-3090), [sudoingX/qwen38-mtp](https://github.com/sudoingX/qwen38-mtp), [DataCamp](https://www.datacamp.com/tutorial/how-to-run-qwen3-8-27b-locally) (via search summary)
- The model card confirms the model was trained with multi-step MTP. — [HF card](https://huggingface.co/Qwen/Qwen3.8-27B)
- 1.81x from draft-mtp at depth 3, and a 5090 speculative config at 128–148 tok/s. — [Context Studios](https://www.contextstudios.ai/blog/qwen-3-8-27b-hardware-guide)

### Inferences
- A separate small draft model (e.g. a tiny Qwen3.x) must share the tokenizer (248K vocab). E4B uses a different tokenizer (262K Gemma vocab), so **E4B cannot be a draft model for Qwen**. MTP is the practical route.
- open_deep_research already separates `research_model`, `summarization_model`, `compression_model` and `final_report_model` in `Configuration`. Setting the 27B for research/supervisor + final report and E4B for summarization/compression is a config-only change via `DEEP_RESEARCH_*` env knobs. Both are Ollama models, but on two daemons/cards, which needs two hosts in the client config.
- For Deep chat: the 27B runs the tool loop and the final synthesis; E4B can stay for ingest/QA generation, where throughput matters more.
- Cost: running both models takes both 4090s. Today the second card may serve other apps (docs/gpu.md notes the shared daemon), so check availability.

### Gaps
- No public benchmark of open_deep_research quality with a mixed 27B/4B model setup.
- Whether Ollama (vs raw llama.cpp `llama-server`) exposes MTP speculation for qwen3.8, and how it interacts with `OLLAMA_NUM_PARALLEL`, is unverified. If Ollama lacks it, getting MTP means running `llama-server`, which conflicts with the repo's "reach models via ollama_client" convention and would need a design decision.
