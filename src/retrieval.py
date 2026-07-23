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

RRF_K = 60
_CANDIDATES = 40  # per-arm depth fed into fusion (idea.md: fuse deep, return shallow)


def _rrf_fuse(lex_hits: list[dict], sem_hits: list[dict], top_k: int) -> list[dict]:
    """Reciprocal Rank Fusion of two ranked lists, keyed on chunk_id.

    score(d) = Σ_arms 1/(k + rank) + a small top-rank bonus (idea.md C.2). The
    lexical hit dict wins ties (iterated first) so `matched_terms`/text survive.
    """
    score: dict[str, float] = {}
    hit: dict[str, dict] = {}
    for hits in (lex_hits, sem_hits):
        for rank, h in enumerate(hits):
            cid = h["chunk_id"]
            score[cid] = score.get(cid, 0.0) + 1.0 / (RRF_K + rank + 1)
            if rank == 0:
                score[cid] += 0.05
            elif rank in (1, 2):
                score[cid] += 0.02
            hit.setdefault(cid, h)
    ranked = sorted(score, key=lambda c: (-score[c], c))[:top_k]
    out: list[dict] = []
    for cid in ranked:
        h = dict(hit[cid])
        h["score"] = round(score[cid], 4)
        out.append(h)
    return out


def search(q: str, top_k: int = 10, scope: str | None = None) -> list[dict]:
    """Hybrid lexical+semantic retrieval. Falls back to pure lexical when the
    semantic arm is unavailable (identical to `lex_index.query`)."""
    lex_hits = lex_index.query(q, top_k=_CANDIDATES, scope=scope)
    if not embed_index.available():
        return lex_hits[:top_k]
    sem_hits = embed_index.query(q, top_k=_CANDIDATES, scope=scope)
    if not sem_hits:
        return lex_hits[:top_k]
    return _rrf_fuse(lex_hits, sem_hits, top_k)
