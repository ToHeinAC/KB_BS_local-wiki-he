# Gemma 4 E4B in Ollama: getting the best tool-calling and long-context RAG performance at low latency

Scope: `gemma4:e4b` served by a single-GPU Ollama daemon, driving a LangGraph/ChatOllama tool loop (German and English document Q&A) and the planner, researcher and report roles of open_deep_research. Research date: 2026-10-22.

## 1. Gemma 4 E4B facts: architecture, context, tool calling, thinking, multilingual, benchmarks

### Takeaway
The model exists and is well documented. Gemma 4 E4B is a dense model with 4.5B effective and 8B total parameters (the difference is per-layer embeddings). It has a 128K native context, native function calling and an optional thinking mode. In thinking mode it is far stronger than Gemma 3 27B on long context (RULER 86.6 at 128K). It is still clearly weak at agentic work: Tau2 averages 42.2% for E4B against 68–77% for the 26B and 31B models, and IFBench is only 38.0. The published numbers assume **thinking mode**.

### Cited Findings
**Architecture**
- E2B and E4B use per-layer embeddings, as in Gemma 3n, "making them 2.3B and 4.5B effective out of 5B and 8B total parameters respectively." The family also includes dense 12B and 31B models and a 26B-A4B MoE with 3.8B active parameters — [Gemma 4 Technical Report, arXiv 2607.02770](https://arxiv.org/pdf/2607.02770)
- E4B has 42 layers, a 512-token sliding window, 128K context, a 262K vocabulary, a ~150M vision encoder and a ~300M audio encoder. Local sliding-window attention is interleaved with global attention, and the last layer is always global — [Google model card](https://ai.google.dev/gemma/docs/core/model_card_4)
- The local:global attention ratio is 4:1 for E2B and 5:1 for the other models. Global layers use p-RoPE (p=0.25) with base frequency 1M; local layers use RoPE with base 10k. The KV cache is shared across layers in a ratio of 18/42 for E4B. Keys-as-values in global layers is used "except in E2B and E4B" — [Tech report](https://arxiv.org/pdf/2607.02770)
- Memory at 32K context, text only: E4B needs 9.0 GB in bf16 and 2.3 GB with mobile quantization. An int8 KV cache at 32K adds +0.14 GB for E4B, which is very small because of KV sharing and SWA — [Tech report, Table 3](https://arxiv.org/pdf/2607.02770)
- The pre-training data cutoff is January 2025 — [Tech report](https://arxiv.org/pdf/2607.02770)

**Ollama packaging**
- In Ollama, `gemma4:e4b` is the same model as `gemma4:latest`. Variants are 6.6–9.5 GB with a 128K context and text and image input; audio is supported only on E2B and E4B. Tools and thinking are listed as capabilities. The library also lists `gemma4:12b`, `26b` and `31b` with 256K context — [Ollama library](https://ollama.com/library/gemma4)
- Ollama ≥ 0.20.0 is required for Gemma 4 — [opencode issue #20995](https://github.com/anomalyco/opencode/issues/20995)

**Tool-call format**
- The native template uses `<|tool>declaration:...<tool|>` for tool declarations and `<|tool_call>call:...<tool_call|>` for calls. Thinking is enabled by `<|think|>`. IT models end each turn with `<turn|>` — [Tech report, Table 11](https://arxiv.org/pdf/2607.02770)
- Argument strings are delimited as `key:<|"|>value<|"|>`. This is not JSON, and Ollama has to parse it back into JSON — [Ollama issue #17882](https://github.com/ollama/ollama/issues/17882)

**Thinking mode**
- Thinking is enabled by putting `<|think|>` at the start of the system prompt and disabled by removing it. Thinking output appears as `<|channel>thought\n … <channel|>` followed by the answer. With thinking disabled, the larger models still emit an empty thought block; E2B and E4B do not — [Google model card](https://ai.google.dev/gemma/docs/core/model_card_4); [Ollama library](https://ollama.com/library/gemma4)
- In llama-server, thinking is turned off with `--chat-template-kwargs '{"enable_thinking":false}'` — [Unsloth Gemma 4 docs](https://unsloth.ai/docs/models/gemma-4)
- In ChatOllama, `reasoning=True` returns the thinking in `additional_kwargs["reasoning_content"]` and `reasoning=False` disables it. With `None`, the model's default behaviour applies, and thinking tags may end up in `content` — [LangChain ChatOllama reference](https://reference.langchain.com/python/langchain-ollama/langchain_ollama/chat_models/ChatOllama)
- An Ollama maintainer (drifkin) said that "small models often perform better on tool calling with reasoning enabled." With `think:false`, E4B often asked clarifying questions instead of calling the tool. The reporter measured roughly 2–4 s extra latency with thinking against about 0.3 s without — [Ollama issue #15539](https://github.com/ollama/ollama/issues/15539)

**Benchmarks, instruction-tuned, thinking mode unless stated** — [model card](https://ai.google.dev/gemma/docs/core/model_card_4); [tech report Tables 5 and 9](https://arxiv.org/pdf/2607.02770)

| Benchmark | E4B | E2B | 12B | 26B-A4B | 31B | Gemma 3 27B (non-thinking) |
|---|---|---|---|---|---|---|
| MMLU Pro | 69.4 | 60.0 | 77.2 | 82.6 | 85.2 | 67.6 |
| MMMLU (multilingual) | 76.6 | 67.4 | 83.4 | 86.3 | 88.4 | 70.7 |
| GPQA Diamond | 58.6 | 43.4 | – | 82.3 | 84.3 | – |
| Tau2 (avg of 3), model card | 42.2 | 24.5 | – | 68.2 | 76.9 | – |
| IFEval / IFBench | 96.7 / 44.0 (see note) | | | 98.5 / 72.0 | 98.9 / 76.0 | 90.4 / 32.0 |
| MRCR v2 8-needle 128K | 25.4 | 19.1 | 43.4 | 44.1 | 66.4 | 13.5 |
| RULER 32K / 128K | 95.2 / 86.6 | 83.0 / 70.4 | 96.4 / 91.2 | 97.3 / 89.8 | 96.8 / 96.4 | 91.1 / 66.0 |
| LOFT text retrieval 128K (Recall@k) | 58.5 | 50.5 | 66.4 | 66.3 | 79.5 | 8.6 |
| GraphWalks F1 (<128K) | 50.9 | 4.1 | 71.0 | 72.6 | 82.3 | 32.8 |
| BigBench Extra Hard | 33.1 | 21.9 | – | 64.8 | 74.4 | – |

- **Column-alignment caveat (uncertain).** The PDF text extraction of Table 5 lists six columns: 31B, 26B, 12B, E4B, E2B, G3-27B. The IFEval/IFBench row reads 98.9/98.5/97.2/96.7/94.6/90.4 and 76.0/72.0/74.0/44.0/38.0/32.0. Taken in that order, E4B would get IFEval 94.6 and IFBench 38.0, not the 96.7/44.0 shown in the table, and the E4B column might be shifted. The Tau2 per-domain values (airline, retail, telecom) read 75.0/76.0/75.0/52.0/31.0/39.0, 86.4/85.5/77.6/67.1/34.6/6.6 and 69.3/43.0/54.4/18.4/19.7/3.1. These reproduce the model-card averages for 31B (76.9) and 26B (68.2). They do **not** reproduce the E4B average of 42.2, which suggests the E4B and E2B columns are misaligned in the extraction. Use the model-card averages: Tau2 E4B **42.2**, E2B 24.5 — [Tech report](https://arxiv.org/pdf/2607.02770); [model card](https://ai.google.dev/gemma/docs/core/model_card_4)
- The model card publishes no BFCL score for any Gemma 4 model — [model card](https://ai.google.dev/gemma/docs/core/model_card_4)
- A third-party article *estimates* BFCL v4 as "high 80s" for Qwen3-4B-Instruct-2507 and "mid-to-high 80s" for Gemma 4 E4B. These are illustrative ranges, not a controlled test — [Ertas AI](https://www.ertas.ai/blog/on-device-tool-calling-2026-qwen3-gemma4-phi4)
- An academic RULER study found the Qwen3 family "exhibits strong effective utilization of extended context". Gemma 3 4B dropped from 90.9 to 62.3 at long lengths; that is Gemma 3, not Gemma 4 — [arXiv 2604.07035](https://arxiv.org/html/2604.07035v1) (as summarised in search results)

**Multilingual**
- Gemma 4 was pre-trained on 140+ languages and supports 35+ languages out of the box — [model card](https://ai.google.dev/gemma/docs/core/model_card_4)
- Speech translation de→en, CoVoST BLEU: E4B 42.0, E2B 39.2 — [Tech report](https://arxiv.org/pdf/2607.02770)

### Inferences
- E4B is a capable reader but a weak multi-step agent. Expect the tool loop to need code-side guard rails, such as the existing `run_memory` loop guard and the "≥1 original read" gate, rather than relying on the model's planning.
- All published agentic and long-context numbers are in thinking mode. Turning thinking off for tool turns will probably cost tool reliability (see §2 and §3).
- MMMLU at 76.6 (above Gemma 3 27B) suggests German reading comprehension is solid. Instruction following in German, with its long legal compounds, is untested.

### Gaps
- No official BFCL or tau-bench non-thinking numbers for E4B, and no direct E4B vs Qwen3-4B head-to-head under the same harness.
- No German-specific text benchmark for E4B, such as German MMLU or a German RAG eval.
- The column alignment of the E4B IFBench and Tau2 per-domain numbers could not be verified from the PDF text.

## 2. Sampling parameters, system-prompt quirks, known Ollama tool-calling bugs

### Takeaway
Google, Ollama and Unsloth all recommend temperature 1.0, top_p 0.95 and top_k 64 for every use case. None of them recommends a repeat penalty. Ollama's Gemma 4 tool-call parser has had a long series of bugs that silently drop or leak calls: early versions, 0.20.x, and still 0.34.x for edge cases. Pin a recent Ollama version and validate tool calls in code.

### Cited Findings
- "Use the same configuration for all use cases: temperature=1.0, top_p=0.95, top_k=64" — [Google model card](https://ai.google.dev/gemma/docs/core/model_card_4). Ollama repeats this — [Ollama library](https://ollama.com/library/gemma4). Unsloth repeats it and mentions no repeat penalty or min_p — [Unsloth](https://unsloth.ai/docs/models/gemma-4)
- Multi-turn: keep only the final answer in history and drop earlier thoughts, **except in tool-call turns, where thinking should be preserved** — [Google model card](https://ai.google.dev/gemma/docs/core/model_card_4)
- Thinking is controlled solely by `<|think|>` at the start of the system prompt. Ollama's template inserts it from the `think` parameter — [Unsloth](https://unsloth.ai/docs/models/gemma-4); [Ollama library](https://ollama.com/library/gemma4)

**Ollama parser bug history** (check the deployed version against these)
- #15241 and #15315: "gemma4 tool call parsing failed" (invalid character) on early 0.20.x releases. 0.20.1 did not fully fix it for E4B — [#15315](https://github.com/ollama/ollama/issues/15315), [#15241](https://github.com/ollama/ollama/issues/15241)
- #15539, 0.20.6: a system prompt combined with `think:false` and tools put the tool-call JSON in `content` with no `tool_calls`. Fixed in v0.20.7-rc1; the cause was an empty think block being sent. The workaround for `think:false` was a prescriptive system prompt: forbid any preamble before tool calls and include positive and negative examples — [#15539](https://github.com/ollama/ollama/issues/15539)
- PR #16075: the parser ended a call early when the close marker appeared inside an argument string — [PR #16075](https://github.com/ollama/ollama/pull/16075)
- #17882: the model sometimes emits `key='value'` instead of `key:<|"|>value<|"|>`; the parse fails and the response comes back empty — [#17882](https://github.com/ollama/ollama/issues/17882)
- #18354: a string-placeholder collision silently drops valid calls (many string values followed by an array) — [#18354](https://github.com/ollama/ollama/issues/18354)
- #18390: object keys containing spaces are left unquoted and the whole call is dropped as an empty response — [#18390](https://github.com/ollama/ollama/issues/18390)
- #18649, reported on 0.34.3/0.34.4: trailing junk such as `$$` after the closing brace causes a valid call to be rejected — [#18649](https://github.com/ollama/ollama/issues/18649)
- Both `/api/chat` and `/v1/chat/completions` return proper `tool_calls` for gemma4, including when streaming. Failures in that report were in the client's streaming parser — [opencode #20995](https://github.com/anomalyco/opencode/issues/20995)

### Inferences
- Keep the official sampling settings for the researcher and tool roles. Do not reduce temperature far below 1.0 without an A/B test, since the model was tuned for it. A temperature of about 0.3–0.7 for the final report is a reasonable experiment but is *not* sourced guidance.
- Keep tool schemas simple: snake_case keys without spaces, mostly string and integer arguments, and avoid arrays after many strings. This sidesteps #18354 and #18390.
- Treat "empty content and no tool_calls" as a parser failure and retry once. Do not treat it as a final answer.
- When thinking is enabled, keep the thinking of tool-call turns in the LangGraph message history and drop the thinking of final-answer turns, as Google advises.

### Gaps
- Fix status of #17882, #18354, #18390 and #18649 as of October 2026 was not checked one by one.

## 3. Effective usable context: what num_ctx makes sense for RAG on E4B

### Takeaway
On simple retrieval, E4B holds up well: RULER 95.2 at 32K and 86.6 at 128K. Multi-needle disambiguation is much weaker (MRCR 8-needle at 128K: 25.4) and so is graph or multi-hop reasoning (GraphWalks 50.9). For RAG with a tool loop, about 16K–32K tokens is the sensible operating point. Do not fill the 128K window.

### Cited Findings
- RULER: E4B scores 95.2 at 32K and 86.6 at 128K; Gemma 3 27B scores 91.1 and 66.0 — [Tech report Table 9](https://arxiv.org/pdf/2607.02770)
- MRCR v2 8-needle at 128K: E4B 25.4 against 66.4 for the 31B — [model card](https://ai.google.dev/gemma/docs/core/model_card_4)
- LOFT text retrieval at 128K, Recall@k: E4B 58.5; GraphWalks F1 below 128K: 50.9 — [Tech report](https://arxiv.org/pdf/2607.02770)
- Ollama's own guidance says agents, web search and coding tools should use "at least 64000 tokens" — [Ollama docs: context length](https://docs.ollama.com/context-length)

### Inferences
- RULER retrieval at 32K is almost lossless (95.2). The 8-needle MRCR result shows that telling apart many similar passages, such as multiple versions of a legal text, degrades badly at long context. Keep retrieved context short and ranked: top-k chunks in a 16–32K working window. Do not stuff whole documents in.
- For open_deep_research, 32K is enough for the researcher role, which compresses its notes. The report role may need more if `raw_notes` are large; compress them instead of raising num_ctx.
- Because E4B's KV cache is tiny (+0.14 GB int8 at 32K), memory is not the reason to keep context small. Quality and prefill time are.

### Gaps
- No independent context-rot or needle-in-a-haystack study of E4B specifically, and no German long-context evaluation.

## 4. Ollama serving knobs: num_ctx, flash attention, KV cache type, keep_alive, parallelism, prefix caching, structured outputs

### Takeaway
Set num_ctx explicitly; the default can be only 4K. Flash attention is enabled automatically. A q8_0 KV cache is nearly free in quality but saves little, because E4B's cache is already small. Use keep_alive=-1 or a long value, and NUM_PARALLEL of 2–4 for parallel researchers (cheap on E4B). The largest latency lever is **prefix-cache stability**: Gemma 4's 512-token sliding-window layers mean any edit to an early part of the prompt forces a full re-prefill.

### Cited Findings
- Default context depends on VRAM: under 24 GiB → 4K, 24–48 GiB → 32K, 48 GiB or more → 256K. It can be set with `OLLAMA_CONTEXT_LENGTH` or `options.num_ctx`, and `ollama ps` shows the effective CONTEXT — [Ollama docs: context length](https://docs.ollama.com/context-length). The FAQ still says 4096 — [Ollama FAQ](https://docs.ollama.com/faq)
- Flash attention is turned on automatically when the backend and devices support it. KV cache types are `f16` (default), `q8_0` (about half the memory, "very little quality loss") and `q4_0` (about a quarter, small-to-medium loss, worse at long context). The setting is global and requires flash attention — [Ollama FAQ](https://docs.ollama.com/faq)
- `OLLAMA_NUM_PARALLEL` defaults to 1. Required RAM scales with NUM_PARALLEL × context length. `keep_alive` defaults to 5 minutes; -1 keeps the model loaded and 0 unloads it. `OLLAMA_MAX_LOADED_MODELS` defaults to 3 × the number of GPUs — [Ollama FAQ](https://docs.ollama.com/faq)
- Gemma 4's template puts the system text first, then all tool declarations, then the conversation. SWA layers keep only the last 512 tokens, so llama.cpp cannot rewind to an early divergence point. One changed word at token 1,009 of a 2.9K prompt reused 0 cached tokens; `--swa-full` made it reuse 1,014 but cost +2.5 GB at 64K. An edit at the end of a ~5K system text discarded ~14K tokens of tool schemas, taking ~45 s instead of seconds. A divergence right *after* the system prompt reused all of it — [AMD GAIA issue #5289](https://github.com/amd/gaia/issues/5289)
- Dropping reasoning from an earlier reply also forces re-prefill (#5039, cited in the same issue) — [GAIA #5289](https://github.com/amd/gaia/issues/5289)
- Ollama serving Gemma 4 has been observed reusing ~19K tokens of prefix per turn with Claude Code traffic. Mechanism: a cached prompt is reusable only if the SWA layers still hold the keys and values for the final window — [scratchy issue #328](https://github.com/AI-native-Systems-Research/scratchy/issues/328), [PR #329](https://github.com/AI-native-Systems-Research/scratchy/pull/329)
- Flash-attention hangs during large prefill on CUDA were reported for the **31B** in Ollama — [#15350](https://github.com/ollama/ollama/issues/15350). In llama.cpp, an E4B plus MTP-assistant run with `-fa on` aborted in `fattn.cu` — [llama.cpp PR #24282](https://github.com/ggml-org/llama.cpp/pull/24282)
- Structured outputs: a `format` JSON schema works with Gemma 4 on Ollama 0.30.7 — [DEV Community](https://dev.to/jangwook_kim_e31e7291ad98/ollama-structured-outputs-in-practice-getting-type-safe-json-from-local-llms-with-pydantic-m38). A secondary write-up says Ollama 0.34.4 allows a thinking model to reason first and then emit schema-constrained JSON, but that some parsers block tool calls after thinking; Gemma 4's thinking-end marker is `<channel|>` — [Towards AI (paywalled; unverified)](https://pub.towardsai.net/ollama-0-34-4-lets-qwen-think-before-json-then-blocks-the-tool-call-5-of-6-parsers-tested-8313c8dfb089)
- A third-party post mentions a Triton attention fallback that dropped E4B to about 9 tok/s on an RTX 4090 in some configurations. It is unverified and probably refers to vLLM — [vantaige.io](https://vantaige.io/blog/gemma-4-rtx-4090-tokens-per-sec-vram-benchmark)

### Inferences (recommended configuration; not benchmarked here)
- Set `num_ctx` explicitly per request, for example 32768 for chat and research and possibly 16384 for short tool turns. **Keep one value for every role.** A different num_ctx forces a model reload or re-allocation in Ollama, which costs seconds.
- Use `OLLAMA_KV_CACHE_TYPE=q8_0` only if VRAM is tight. Given the +0.14 GB per 32K int8 figure, f16 is affordable and avoids any risk; avoid q4_0. The setting is global, so it affects every model on the pinned daemon.
- Set `keep_alive=-1` or `"24h"` on the pinned daemon to avoid cold loads between chat turns.
- `OLLAMA_NUM_PARALLEL=2–4` lets open_deep_research's concurrent researchers run in parallel instead of queueing. The KV cost is small on E4B, but per-stream decode speed drops under concurrency.
- Prefix stability rules for the LangGraph loop:
  1. Keep the system prompt byte-identical across turns. Put no timestamps, run IDs or per-query hints in it; move query-specific instructions to the end.
  2. Keep the set and order of bound tools fixed for the whole run, because tool declarations sit right after the system prompt.
  3. Only append messages. Do not rewrite or trim early history, or apply truncation such as the history window fix in commit b21ee3e, more often than necessary; trim in large steps so the prefix stays stable over many turns.
  4. Keep the thinking of tool-call turns in history, as Google advises. That also avoids the re-prefill caused by stripping reasoning.
- Structured outputs (`format=` schema) suit small extraction steps; use them with `think=false` unless the Ollama version is at least 0.34.4. For open_deep_research's structured roles, such as the ClarifyWithUser and ResearchQuestion schemas, keep the schemas flat and the field names simple.

### Gaps
- No measured tok/s, prefill speed or prefix-cache hit numbers for `gemma4:e4b` on the user's GPU; measure with `ollama ps` and `eval_count`/`prompt_eval_duration`.
- Ollama does not document whether its engine applies a `--swa-full`-like policy for Gemma 4.

## 5. Speculative decoding / MTP draft models

### Takeaway
Gemma 4 ships an official MTP drafter. For E4B it is weak: about 76–77M parameters, with a clustered top-k head that llama.cpp does not yet implement. In llama.cpp it works for E2B/E4B since PR #24282 (June 2026) with modest acceptance (~0.48 on E2B), and it breaks with flash attention on CUDA. No official Ollama support for it was found. Do not count on it for the 1.2× wall-time budget.

### Cited Findings
- The MTP drafter is a small autoregressive head (a 4-layer transformer, model dimension 256 for E2B/E4B) that cross-attends to the main model's KV, so it needs no separate prefill. For E2B/E4B, the full-vocabulary projection is replaced by a top-k over token clusters (d×262,000 → d×4,096) — [Tech report §2.6](https://arxiv.org/pdf/2607.02770). The drafter size table lists 76M and 77M for the two smallest models — [Tech report Table 1](https://arxiv.org/pdf/2607.02770)
- Unsloth claims MTP gives "1.4-2.2x faster inference without accuracy loss", with the largest gains on the dense 31B. In vLLM it is enabled with `--speculative-config '{"method":"mtp","num_speculative_tokens":2}'` — [Unsloth](https://unsloth.ai/docs/models/gemma-4); [Unsloth MTP guide](https://unsloth.ai/docs/models/mtp)
- llama.cpp PR #23398 (merged June 2026) added Gemma 4 MTP for 31B and 26B only: about 2× on the dense 31B, 1.74–1.97× at Q8 with 0.58–0.70 acceptance. A Q8_0 KV cache initially gave 0% acceptance (later fixed) — [PR #23398](https://github.com/ggml-org/llama.cpp/pull/23398)
- llama.cpp PR #24282 (merged June 8, 2026) added the E2B/E4B assistants by dropping the `masked_embedding` tensors and using the dense head, so there is no efficient ordered head. Acceptance was 0.479 on E2B; one E4B user on a Jetson Orin Nano went from 19.7 to 27.7 t/s. E4B with `-fa on` on CUDA aborted in `fattn.cu` — [PR #24282](https://github.com/ggml-org/llama.cpp/pull/24282)
- One user ran Ollama 0.32.15's bundled llama-server with `draft-mtp` flags and hit failures. No official Ollama MTP support was found — [llama.cpp discussion #22735](https://github.com/ggml-org/llama.cpp/discussions/22735)

### Inferences
- On a discrete GPU, E4B decoding is already fast, and with RAG the wall time is likely dominated by prefill. Prefix-cache stability (§4) is therefore a much bigger and safer speed lever than speculative decoding.
- The trade-off for the 1.2× budget: thinking mode on tool turns probably costs +2–4 s per turn (per #15539) but is what the published agentic numbers assume. Pay for it by keeping the prefix cache warm, keeping num_ctx at 32K or less with tight top-k chunks, NUM_PARALLEL for researchers, and keep_alive. A cheaper middle path is thinking on only for planning and tool-selection turns, and `think=false` with a prescriptive system prompt for the final synthesis. This is an inference to A/B test, not sourced.

### Gaps
- No E4B MTP speedup measurement on a desktop CUDA GPU, and no Ollama release note confirming MTP support.
