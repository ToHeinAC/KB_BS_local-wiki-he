"""Cross-encoder reranking — Stage D.

Reorders the RRF-fused candidate list with a real cross-encoder: query and chunk
are scored *together* in one forward pass, so the model sees the interaction that
bi-encoder cosine (arm B) and BM25 (arm A) both structurally miss.

Runtime is `llama-cpp-python` **in-process** — no second service, matching the
Stage C precedent (local, file-backed, no cloud API). The reranker GGUF lives in
`models/` as a derived, re-downloadable artifact, never a source of truth.

Two facts established by the D.0 smoke test (ideas/idea.md §5.4), both non-obvious:

1. `Llama.rank` is NOT exposed by llama-cpp-python 0.3.19, so this drives the
   ctypes layer and builds the cross-encoder input itself:
       [BOS] query [EOS] [SEP] document [EOS]
   which is what llama.cpp's server does internally for /v1/rerank. Under RANK
   pooling `llama_get_embeddings_seq()[0]` is the classification-head score, not
   an embedding vector.
2. Ollama cannot host a reranker at all — it exposes no rerank endpoint, and
   running a reranker through /api/generate returns uniform noise rather than
   erroring. Do not "simplify" this module onto ollama_client.

OPTIONAL AND GRACEFUL, exactly like the semantic arm: no GGUF, no llama-cpp
installed, or any error mid-scoring — `available()` goes False / `rerank()`
returns the input order untouched. A down reranker must degrade ranking, never
break search (idea.md §5.4: "fail open, always").
"""

from __future__ import annotations

import ctypes
import functools
import os
import threading
from pathlib import Path

# Cap the document side so a long chunk can't exceed the context window. The doc
# is truncated for SCORING only — hit text, anchors and citations are untouched.
_MAX_DOC_CHARS = 4000
_N_CTX = 4096

_lock = threading.Lock()  # llama.cpp contexts are not thread-safe; Streamlit reruns
_state: dict | None = None


def _model_path() -> Path:
    return Path(os.getenv("RERANK_MODEL", "models/bge-reranker-v2-m3-Q8_0.gguf"))


def candidates() -> int:
    """How deep into the fused list to rerank. Cost is linear in this number."""
    return int(os.getenv("RERANK_CANDIDATES", "30"))


@functools.lru_cache(maxsize=1)
def _llama_cpp():
    """The llama_cpp module, or None when it isn't installed (optional extra)."""
    try:
        import llama_cpp

        return llama_cpp
    except Exception:
        return None


def available() -> bool:
    """True when reranking is enabled, the runtime is installed and the GGUF exists."""
    if os.getenv("RERANK_ENABLED", "1").strip().lower() in ("0", "false", "no"):
        return False
    return _llama_cpp() is not None and _model_path().exists()


def _load() -> dict | None:
    """Lazily build the model + RANK-pooled context. Cached for the process."""
    global _state
    if _state is not None:
        return _state
    L = _llama_cpp()
    if L is None or not _model_path().exists():
        return None
    try:
        L.llama_backend_init()
        L.llama_log_set(ctypes.cast(None, L.llama_log_callback), None)
        model = L.llama_model_load_from_file(str(_model_path()).encode(),
                                             L.llama_model_default_params())
        if not model:
            return None
        p = L.llama_context_default_params()
        p.embeddings = True
        p.pooling_type = L.LLAMA_POOLING_TYPE_RANK  # the classification head
        p.n_ctx = p.n_batch = p.n_ubatch = _N_CTX
        threads = int(os.getenv("RERANK_THREADS", "0")) or min(16, os.cpu_count() or 4)
        p.n_threads = p.n_threads_batch = threads
        ctx = L.llama_init_from_model(model, p)
        if not ctx:
            return None
        _state = {"L": L, "model": model, "ctx": ctx,
                  "vocab": L.llama_model_get_vocab(model)}
        return _state
    except Exception:
        return None


def _tokenize(st: dict, text: str) -> list[int]:
    L, buf = st["L"], (st["L"].llama_token * _N_CTX)()
    raw = text.encode()
    n = L.llama_tokenize(st["vocab"], raw, len(raw), buf, _N_CTX, False, True)
    return list(buf[:n]) if n > 0 else []


def _score_one(st: dict, q_toks: list[int], doc: str) -> float:
    """One cross-encoder forward pass over [BOS] q [EOS] [SEP] doc [EOS]."""
    L, vocab = st["L"], st["vocab"]
    toks = ([L.llama_vocab_bos(vocab)] + q_toks
            + [L.llama_vocab_eos(vocab), L.llama_vocab_sep(vocab)]
            + _tokenize(st, doc[:_MAX_DOC_CHARS]) + [L.llama_vocab_eos(vocab)])
    toks = toks[:_N_CTX]
    batch = L.llama_batch_init(len(toks), 0, 1)
    try:
        batch.n_tokens = len(toks)
        for i, t in enumerate(toks):
            batch.token[i], batch.pos[i] = t, i
            batch.n_seq_id[i], batch.seq_id[i][0] = 1, 0
            batch.logits[i] = True
        L.llama_memory_clear(L.llama_get_memory(st["ctx"]), True)
        if L.llama_decode(st["ctx"], batch) != 0:
            raise RuntimeError("llama_decode failed")
        return float(L.llama_get_embeddings_seq(st["ctx"], 0)[0])
    finally:
        L.llama_batch_free(batch)


def score_pairs(query: str, docs: list[str]) -> list[float]:
    """Relevance logits for each (query, doc). Returns [] on any failure."""
    if not query.strip() or not docs or not available():
        return []
    with _lock:
        st = _load()
        if st is None:
            return []
        try:
            q_toks = _tokenize(st, query)
            return [_score_one(st, q_toks, d) for d in docs]
        except Exception:
            return []


def _blend_weight(rank: int) -> float:
    """Reranker's share at 0-based fused `rank` (idea.md D.1, position-aware).

    Trust retrieval at the top, the reranker further down: expansion must not be
    allowed to dilute an exact match, and `exact` is the slice a statute corpus
    cannot afford to lose.

    TUNED, and deliberately gentler at the tail than qmd's published .25/.50/.75.
    Measured on both KI fixtures (page + chunk): qmd's weights buy precision@5
    (0.260 -> 0.360) by letting the reranker dominate rank 11+, which evicted a
    relevant `topical` hit from the top 10 (recall@10 1.000 -> 0.500) and cost
    chunk-level MRR (0.833 -> 0.813). Capping the tail at 0.50 keeps most of the
    gain (P@5 0.320, MRR 0.566 -> 0.603) while *improving* recall@10 (0.850 ->
    0.950) and chunk MRR (-> 0.848): the only profile that regresses nothing.
    A missed relevant document costs more here than a slightly lower P@5.
    """
    if rank < 3:
        return 0.25
    if rank < 10:
        return 0.40
    return 0.50


def _normalize(values: list[float]) -> list[float]:
    """Min-max to [0,1]; flat input degrades to a constant rather than dividing by 0."""
    lo, hi = min(values), max(values)
    if hi - lo < 1e-9:
        return [0.5] * len(values)
    return [(v - lo) / (hi - lo) for v in values]


def rerank(query: str, hits: list[dict], top_k: int) -> list[dict]:
    """Reorder fused `hits` with the cross-encoder. Fails open to `hits[:top_k]`.

    Blends normalized fused and reranker scores position-awarely (D.1) rather than
    replacing one with the other. Each returned hit carries `rerank_score` (the raw
    logit) so Stage E can calibrate an abstention threshold on it.
    """
    window = hits[:candidates()]
    if len(window) < 2:
        return hits[:top_k]
    logits = score_pairs(query, [h.get("text", "") for h in window])
    if len(logits) != len(window):
        return hits[:top_k]  # fail open — a down reranker never breaks search
    fused_n = _normalize([h.get("score", 0.0) for h in window])
    rerank_n = _normalize(logits)
    scored = []
    for rank, (h, f, r, raw) in enumerate(zip(window, fused_n, rerank_n, logits)):
        w = _blend_weight(rank)
        out = dict(h)
        out["rerank_score"] = round(raw, 4)
        out["score"] = round((1 - w) * f + w * r, 4)
        scored.append((out["score"], rank, out))
    scored.sort(key=lambda t: (-t[0], t[1]))
    reordered = [h for _, _, h in scored]
    return (reordered + hits[candidates():])[:top_k]
