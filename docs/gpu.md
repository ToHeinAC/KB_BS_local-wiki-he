# GPU placement

> Modules: [`src/gpu_placement.py`](../src/gpu_placement.py) (policy),
> [`src/ollama_server.py`](../src/ollama_server.py) (the pinned Ollama daemon).
> Config table: [IMPLEMENTATION.md §6](../IMPLEMENTATION.md#6-configuration).

## The policy

**Keep each model on one GPU unless it cannot fit.**

Splitting a model's layers across cards does not make single-stream decoding
faster. The GPUs run *sequentially* — each idles while the other works — and
every token pays a cross-device hop. A split buys capacity, not speed, so it is
worth taking only when one card cannot hold the model.

Measured on this box (2× RTX 4090, `gemma4:e4b`) with the sibling
[`local-llm-testing`](https://github.com/ToHeinAC/local-llm-testing) bench harness:

| Setup | tok/s |
|---|---|
| llama.cpp, split across both cards, ctx 8192 | 94 |
| llama.cpp, pinned to one card, ctx 8192 | **170** |
| Ollama, shared system daemon (split, `NUM_PARALLEL=4`, ctx 131072) | 149 |
| Ollama, pinned daemon (`NUM_PARALLEL=1`, ctx 8192) | **164** |

The llama.cpp pair is a clean placement A/B — same context, same build. The
Ollama pair is not: placement, parallelism *and* context all differ, because the
shared daemon's settings are not ours to change. Treat 149 → 164 as "the daemon
we control beats the one we don't", not as a pure placement delta.

Here placement is also a **stability** fix, not only a speed one. A compute
graph spread across cards is what trips the `GGML_SCHED_MAX_SPLIT_INPUTS` assert
during ingest synthesis — the crash `ollama_client._CRASH_MARKERS` retries
around. `OLLAMA_NUM_PARALLEL=1` matters for the same reason: the shared daemon's
four slots each allocate `INGEST_NUM_CTX`, re-inflating the very graph that cap
exists to shrink.

## Two traps

Both cost a debugging round-trip; neither is re-derivable from the symptom.

1. **`CUDA_VISIBLE_DEVICES` alone silently fails for Ollama.** Ollama offers
   every card through CUDA *and* Vulkan. Hiding a card from CUDA makes it
   reappear as a Vulkan device and the model loads there anyway — asking for
   GPU 1 lands you on GPU 0, with no error. **`OLLAMA_VULKAN=0`** is what makes
   the CUDA filter authoritative.
2. **CUDA orders devices fastest-first, not by PCI bus.** Without
   **`CUDA_DEVICE_ORDER=PCI_BUS_ID`**, index *N* need not be nvidia-smi's GPU
   *N*. `gpu_placement.cuda_env()` always emits both variables together, and
   `rerank._preload_cuda()` sets the ordering before the CUDA runtime loads.

## Ollama: a daemon of our own

The system daemon on `:11434` runs as `User=ollama` with
`OLLAMA_NUM_PARALLEL=4` and no device pin. Its environment needs root to change,
and restarting it would drop whatever the box's other apps have loaded. So the
app does not touch it.

Instead `ollama_server` starts a **second `ollama serve`** on a spare port
(`11435`) against the **same model store** — no copy, no re-pull; the store is
world-readable — pinned to one card, and `ollama_client.host()` returns that.

```
app start
   └─ ollama_client.host() ─┬─ configured OLLAMA_HOST is remote?  → use it unchanged
                            ├─ OLLAMA_PIN_GPU=off?                → use it unchanged
                            ├─ models too big for one card?       → use it unchanged
                            ├─ :11435 already serving?            → adopt it
                            └─ spawn `ollama serve` on :11435 ──┬─ up   → use it
                                                                └─ down → use :11434
```

Every branch that is not a pin returns the configured `OLLAMA_HOST` **unchanged**
and the app behaves exactly as it did before. `ollama_server.status()` reports
which branch was taken, and the sidebar renders it (`Ollama · pinned to GPU 1`,
or `Ollama · shared daemon` with the reason on hover).

**What the child gets:** `CUDA_VISIBLE_DEVICES` + `CUDA_DEVICE_ORDER` from
`cuda_env()`, `OLLAMA_VULKAN=0`, `OLLAMA_NUM_PARALLEL=1`,
`OLLAMA_HOST=127.0.0.1:<port>`, and `OLLAMA_MODELS` from `find_models_dir()`.

**Finding the model store** is deliberately "the candidate with the most
manifests", not "the first that exists": `~/.ollama/models` is created empty by
the CLI on this box while all 51 models live in the system daemon's store, so
picking by existence starts a daemon that can see no models at all.

**The size estimate** (`required_gib`) sums the *distinct* models every role is
configured with — Ollama holds several resident at once, one per role, each until
its `keep_alive` expires, so the sum and not the max has to fit. Sizes come from
the already-running daemon's `/api/tags`; a model never pulled contributes 0, and
an unreachable daemon leaves only the compute overhead. Both under-estimate, which
is the right bias: if no daemon answers, ours is the app's only LLM.

**Lifecycle.** Started lazily on the first `host()` call, stopped via `atexit`,
so Streamlit's SIGTERM shutdown reaps it. A daemon already listening on the
pinned port is **adopted**, not duplicated, so a hard kill leaves at most one
stray daemon and the next app start reuses it. `stop()` never touches an adopted
daemon — only one we started.

The one sharp edge: **run a single LocalWiki instance per pinned port.** With two
up at once the second adopts the first's daemon, and if the owner exits first the
adopter is left pointing at a dead host (the resolution is cached, so it will not
re-resolve on its own). Give a second instance its own `OLLAMA_PIN_PORT`, or set
`OLLAMA_PIN_GPU=off` on it.

## The reranker

`src/rerank.py` runs `bge-reranker-v2-m3` in-process through `llama-cpp-python`,
and llama.cpp defaults to `split_mode = LAYER` — so before this change even that
~0.6 GiB cross-encoder was spread over both cards, paying a device hop per scored
pair for capacity it did not need. `_model_params()` now sets
`split_mode = NONE` and `main_gpu` to the emptiest card.

Because the emptiest card wins, the reranker naturally lands on the *other* GPU
once the pinned Ollama daemon owns one — the two locals end up on separate cards
with no coordination between them.

One honest caveat: ggml still creates a CUDA context on **every** visible device,
so the unpinned card gains ~390 MiB even though no weights and no per-token work
land there. Full exclusivity would need `CUDA_VISIBLE_DEVICES` on the Streamlit
process itself, which is a bigger hammer than the problem deserves.

## Verifying

```bash
# what the app resolved, without starting the UI
uv run python -c "import sys; sys.path.insert(0,'src'); import ollama_server, json; \
                  print(json.dumps(ollama_server.status(), indent=2))"

# where the weights actually landed
nvidia-smi --query-gpu=index,memory.used,utilization.gpu --format=csv
```

A correct pin shows the whole model on one card and the other card flat at its
baseline — that is the check that catches the Vulkan trap, which a status line
alone cannot.

## Turning it off

`OLLAMA_PIN_GPU=off` and `RERANK_PIN_GPU=off` restore the previous behaviour
exactly: the shared `:11434` daemon and llama.cpp's own layer split. `"0"` is
**not** an off-switch in either — it names GPU 0.
