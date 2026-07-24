"""Hybrid retrieval — fuse the lexical (FTS5) and semantic (embedding) arms.

`search()` is the single retrieval entry point. It runs the lexical arm (always)
and the semantic arm (when a DB has vectors for the active model) and combines
them with Reciprocal Rank Fusion (RRF, k=60) — parameter-free and degrading
gracefully to a single arm.

GRACEFUL BY DESIGN: when the semantic arm is unavailable (no vectors / model not
pulled / unreachable) `search()` returns exactly `lex_index.query(...)[:top_k]`,
so enabling embeddings can never regress the lexical baseline. The lexical arm
stays the grounding/citation source of truth; fusion only re-ranks.

Hit-dict shape is identical to `lex_index.query`; the lexical hit is preferred
when a chunk is found by both arms (it carries `matched_terms` and inline text).
"""

from __future__ import annotations

import embed_index
import lex_index
import rerank

RRF_K = 60
_CANDIDATES = 40  # per-arm depth fed into fusion (idea.md: fuse deep, return shallow)

# Per-arm weights. The dense arm is weighted higher: when the lexical arm misses a
# paraphrase/synonym match entirely (it structurally can't reach it), a strong
# semantic-only hit must still outrank the topically-related decoys the lexical arm
# *does* return. Tuned on the discriminating chunk-level fixtures (bench/
# fixture_{KI,Strahlenschutz}_chunk.json): semantic-slice MRR 0.65 -> 1.00 on both
# English and German, with zero regression to the exact/topical controls.
W_LEXICAL = 1.0
W_SEMANTIC = 2.0


def _arm_contribution(rank: int) -> float:
    """One arm's RRF weight for a hit at 0-based `rank`, incl. a top-rank bonus."""
    c = 1.0 / (RRF_K + rank + 1)
    if rank == 0:
        c += 0.05
    elif rank in (1, 2):
        c += 0.02
    return c


def _rrf_fuse(lex_hits: list[dict], sem_hits: list[dict], top_k: int) -> list[dict]:
    """Weighted Reciprocal Rank Fusion of two ranked lists, keyed on chunk_id.

    score(d) = Σ_arms w_arm · (1/(k + rank) + top-rank bonus) (idea.md C.2). The
    lexical hit dict wins ties (iterated first) so `matched_terms`/text survive.
    """
    score: dict[str, float] = {}
    hit: dict[str, dict] = {}
    for hits, w in ((lex_hits, W_LEXICAL), (sem_hits, W_SEMANTIC)):
        for rank, h in enumerate(hits):
            cid = h["chunk_id"]
            score[cid] = score.get(cid, 0.0) + w * _arm_contribution(rank)
            hit.setdefault(cid, h)
    ranked = sorted(score, key=lambda c: (-score[c], c))[:top_k]
    out: list[dict] = []
    for cid in ranked:
        h = dict(hit[cid])
        h["score"] = round(score[cid], 4)
        out.append(h)
    return out


def search(q: str, top_k: int = 10, scope: str | None = None,
           use_rerank: bool = False) -> list[dict]:
    """Hybrid lexical+semantic retrieval. Falls back to pure lexical when the
    semantic arm is unavailable (identical to `lex_index.query`).

    `use_rerank` adds the Stage D cross-encoder pass. It splits the two consumers
    per idea.md §6.9.2: the Fast path (browsing, per-keystroke) stays fusion-only,
    while the Deep answer paths — which commit to a citation — pay for precision.
    Unavailable reranker ⇒ plain fused order, so this can never break search.
    """
    reranking = use_rerank and rerank.available()
    depth = max(top_k, rerank.candidates()) if reranking else top_k
    lex_hits = lex_index.query(q, top_k=_CANDIDATES, scope=scope)
    if not embed_index.available():
        fused = lex_hits[:depth]
    else:
        sem_hits = embed_index.query(q, top_k=_CANDIDATES, scope=scope)
        fused = lex_hits[:depth] if not sem_hits else _rrf_fuse(lex_hits, sem_hits, depth)
    return rerank.rerank(q, fused, top_k) if reranking else fused[:top_k]
