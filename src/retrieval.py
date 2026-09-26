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

from contextvars import ContextVar
from datetime import date
from typing import Any

import db_context
import embed_index
import lex_index
import ontology_query
import ontology_store
import ontology_time
import rerank
import run_memory

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
# The ontology arm (docs/ontology.md §Search) is one more ranked list: lexical hits
# restricted to the sources of the works/classes a question names. RRF bounds its
# influence, so a wrong resolution can move a hit but never swamp the other arms.
W_ONTOLOGY = 1.0

Ranked = list[dict[str, Any]]
_last_frame: ContextVar[dict[str, Any] | None] = ContextVar("ontology_frame", default=None)


def _arm_contribution(rank: int) -> float:
    """One arm's RRF weight for a hit at 0-based `rank`, incl. a top-rank bonus."""
    c = 1.0 / (RRF_K + rank + 1)
    if rank == 0:
        c += 0.05
    elif rank in (1, 2):
        c += 0.02
    return c


def _rrf_fuse(
    lex_hits: Ranked,
    sem_hits: Ranked,
    top_k: int,
    extra: list[tuple[Ranked, float]] | None = None,
) -> Ranked:
    """Weighted Reciprocal Rank Fusion of two ranked lists, keyed on chunk_id.

    score(d) = Σ_arms w_arm · (1/(k + rank) + top-rank bonus) (idea.md C.2). The
    lexical hit dict wins ties (iterated first) so `matched_terms`/text survive.
    """
    score: dict[str, float] = {}
    hit: dict[str, dict[str, Any]] = {}
    for hits, w in ((lex_hits, W_LEXICAL), (sem_hits, W_SEMANTIC), *(extra or [])):
        for rank, h in enumerate(hits):
            cid = h["chunk_id"]
            score[cid] = score.get(cid, 0.0) + w * _arm_contribution(rank)
            hit.setdefault(cid, h)
    ranked = sorted(score, key=lambda c: (-score[c], c))[:top_k]
    out: list[dict[str, Any]] = []
    for cid in ranked:
        h = dict(hit[cid])
        h["score"] = round(score[cid], 4)
        out.append(h)
    return out


def _scoped(view: ontology_query.View, sources: tuple[str, ...], scope: str | None) -> list[str]:
    """Index `source` values for raw files: themselves (raw), the pages citing them (wiki)."""
    pages = list(ontology_query.pages_for(view, sources))
    if scope == "raw":
        return list(sources)
    return pages if scope == "wiki" else [*sources, *pages]


def _ontology_arm(
    q: str, frame: ontology_query.QueryFrame, view: ontology_query.View, scope: str | None
) -> Ranked:
    """Lexical hits within the named works' sources (query + their aliases), then within
    the named classes' sources. Only lexical hits: the lexical arm stays the citation truth."""
    works = _scoped(view, frame.sources, scope)
    classes = [s for s in _scoped(view, frame.class_sources, scope) if s not in works]
    hits = lex_index.query(" ".join([q, *frame.terms]), _CANDIDATES, scope, works) if works else []
    seen = {h["chunk_id"] for h in hits}
    if classes:
        hits += [
            h for h in lex_index.query(q, _CANDIDATES, scope, classes) if h["chunk_id"] not in seen
        ]
    return hits


def _note_frame(frame: ontology_query.QueryFrame | None) -> None:
    record = ontology_query.audit(frame) or None
    _last_frame.set(record)
    mem = run_memory.current()
    if mem is not None and record:
        mem.note_ontology({"db": db_context.get_active_db(), **record})


def point_in_time(q: str) -> date | None:
    """The date to judge versions at: one the query names, else the run question's, else
    today — None when the question asks about the past without a date (don't reorder)."""
    today = date.today()
    intent = ontology_time.time_intent(q, today)
    mem = run_memory.current()
    if intent.explicit:
        return intent.as_of
    if mem is not None and mem.as_of:
        return ontology_time.parse(mem.as_of)
    if intent.past or (mem is not None and mem.time_past):
        return None
    return today


def _validity_step(
    q: str, hits: Ranked, view: ontology_query.View | None, scope: str | None
) -> Ranked:
    """Demote (never drop) hits from versions not in force, and wiki pages built only on
    superseded versions (D3). No-op without an ontology or dated versions."""
    as_of = point_in_time(q) if view is not None else None
    if view is None or as_of is None:
        return hits
    hits = ontology_time.validity_order(hits, view, as_of) if scope != "wiki" else hits
    if scope == "raw":
        return hits
    outdated = set(ontology_time.outdated_pages(view, as_of))
    return [h for h in hits if h["source"] not in outdated] + [
        h for h in hits if h["source"] in outdated
    ]


def _ontology_lists(
    q: str, scope: str | None, view: ontology_query.View | None
) -> list[tuple[Ranked, float]]:
    """The ontology stage (S1): [(arm, weight)] or [] — [] without an ontology or when the
    question names no work or class, so such searches are byte-identical to before."""
    frame = ontology_query.resolve(q, view, point_in_time(q)) if view is not None else None
    _note_frame(frame)
    if view is None or frame is None:
        return []
    arm = _ontology_arm(q, frame, view, scope)
    return [(arm, W_ONTOLOGY)] if arm else []


def last_frame() -> dict[str, Any] | None:
    """Audit record of the last search's ontology stage in this context (None: no match)."""
    return _last_frame.get()


def ontology_rerank(q: str, hits: Ranked, scope: str | None, top_k: int) -> Ranked:
    """Run the ontology stage on an already-ranked lexical list (the Explorer's wiki search)."""
    view = ontology_store.view()
    extra = _ontology_lists(q, scope, view)
    return _validity_step(q, _rrf_fuse(hits, [], top_k, extra) if extra else hits, view, scope)


def ontology_briefing(question: str) -> tuple[str, list[dict[str, Any]]]:
    """S2: system-prompt block for a question over the search scope, plus audit records."""
    scope = db_context.search_scope()
    intent = ontology_time.time_intent(question, date.today())
    run_memory.note_time(intent.as_of.isoformat() if intent.explicit else None, intent.past)
    blocks: list[str] = []
    records: list[dict[str, Any]] = []
    for db in scope:
        with db_context.using_db(db):
            view = ontology_store.view()
            frame = ontology_query.resolve(question, view) if view is not None else None
        text = ontology_query.briefing(frame, view) if view is not None else ""
        if text:
            blocks.append(text if len(scope) == 1 else f"Database {db}:\n{text}")
            records.append({"db": db, **ontology_query.audit(frame)})
    return "\n\n".join(blocks), records


def search(
    q: str,
    top_k: int = 10,
    scope: str | None = None,
    use_rerank: bool = False,
    use_ontology: bool = True,
) -> list[dict[str, Any]]:
    """Hybrid lexical+semantic retrieval. Falls back to pure lexical when the
    semantic arm is unavailable (identical to `lex_index.query`).

    `use_rerank` adds the Stage D cross-encoder pass. It splits the two consumers
    per idea.md §6.9.2: the Fast path (browsing, per-keystroke) stays fusion-only,
    while the Deep answer paths — which commit to a citation — pay for precision.
    Unavailable reranker ⇒ plain fused order, so this can never break search.
    `use_ontology=False` skips the ontology stage (benchmark comparison only).
    """
    reranking = use_rerank and rerank.available()
    depth = max(top_k, rerank.candidates()) if reranking else top_k
    lex_hits = lex_index.query(q, top_k=_CANDIDATES, scope=scope)
    view = ontology_store.view() if use_ontology else None
    extra = _ontology_lists(q, scope, view)
    sem_hits = (
        embed_index.query(q, top_k=_CANDIDATES, scope=scope) if embed_index.available() else []
    )
    fused = _rrf_fuse(lex_hits, sem_hits, depth, extra) if sem_hits or extra else lex_hits[:depth]
    ranked = rerank.rerank(q, fused, top_k) if reranking else fused[:top_k]
    return _validity_step(q, ranked, view, scope)
