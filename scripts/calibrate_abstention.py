"""Stage E calibration — measure rerank-score separability, derive an abstention τ.

The kill criterion (ideas/idea.md §5.5, §5.10): abstention is viable only if the
cross-encoder `rerank_score` distributions of labelled-RELEVANT vs labelled-IRRELEVANT
hits separate cleanly. Heavy overlap ⇒ a threshold that fires unpredictably ⇒ do NOT
ship. This script reports the number, then (with --write) persists the derived per-DB τ.

It reuses the bench harness: the hand-labelled fixtures (`bench/fixture_<DB>_chunk.json`,
`expected` = relevant chunk_ids) and the relevance predicate (`bench_retrieval._matches`).

Two views, because abstention is a per-QUERY decision, not a per-passage one:

  * QUERY-LEVEL (primary, when a negatives fixture exists). Abstention keys on the best
    passage — idea.md §3.5, "when the top reranked score falls below threshold". So this
    takes max(`rerank_score`) per query for should-ANSWER queries (the labelled fixture,
    each has an in-corpus answer) vs should-ABSTAIN queries (`bench/fixture_<DB>_negatives.json`,
    deliberately out-of-domain). τ must sit above the abstain top-scores and below the
    answer top-scores; the gap between them is what makes abstention viable or not.
  * PER-HIT (always). Pools every returned hit's `rerank_score` as relevant/irrelevant and
    reports ROC-AUC — the passage-level separability idea.md §5.5 names.

τ recommendations: Youden-J (max tpr−fpr) and a CONSERVATIVE variant (highest τ that still
answers `--min-recall` of should-answer queries — a regulatory corpus should rather answer
weakly than wrongly abstain when a relevant page exists).

Usage:
    uv run python scripts/calibrate_abstention.py --db KI
    uv run python scripts/calibrate_abstention.py --db KI --write   # persist calibration.json
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from bench_retrieval import _matches  # reuse, never duplicate the predicate

import db_context
import embed_index
import rerank
import retrieval

# Full reranked window per query: ~1 relevant + many irrelevant hits, all carrying a
# `rerank_score` (rerank() scores the top `candidates()`), so one query yields the most
# labelled samples possible without a second search.
_DEPTH = 30


def _percentile(values: list[float], p: float) -> float:
    """Linear-interpolated percentile (p in [0,1]); [] -> nan."""
    if not values:
        return float("nan")
    s = sorted(values)
    if len(s) == 1:
        return s[0]
    idx = p * (len(s) - 1)
    lo = int(idx)
    frac = idx - lo
    hi = min(lo + 1, len(s) - 1)
    return s[lo] + frac * (s[hi] - s[lo])


def _auc(rel: list[float], irr: list[float]) -> float:
    """ROC-AUC via the Mann-Whitney statistic. 0.5 = indistinguishable."""
    if not rel or not irr:
        return float("nan")
    wins = 0.0
    for r in rel:
        for i in irr:
            wins += 1.0 if r > i else 0.5 if r == i else 0.0
    return wins / (len(rel) * len(irr))


def _best_tau_youden(rel: list[float], irr: list[float]) -> float:
    """Threshold maximizing tpr - fpr over all observed scores (kept = score >= τ)."""
    cuts = sorted(set(rel + irr))
    best_tau, best_j = cuts[0], -1.0
    for tau in cuts:
        tpr = sum(1 for r in rel if r >= tau) / len(rel)
        fpr = sum(1 for i in irr if i >= tau) / len(irr)
        if tpr - fpr > best_j:
            best_j, best_tau = tpr - fpr, tau
    return best_tau


def _conservative_tau(rel: list[float], irr: list[float], min_recall: float) -> float:
    """Highest τ that still retains >= min_recall of relevant hits (few false abstains)."""
    cuts = sorted(set(rel + irr), reverse=True)
    chosen = min(rel)
    for tau in cuts:
        if sum(1 for r in rel if r >= tau) / len(rel) >= min_recall:
            chosen = tau
            break
    return chosen


def _search(query: str, scope: str) -> list[dict]:
    q_scope = scope
    return retrieval.search(
        query, top_k=_DEPTH, use_rerank=True, scope=(q_scope if q_scope != "both" else None)
    )


def _rerank_scores(hits: list[dict]) -> list[float]:
    return [float(h["rerank_score"]) for h in hits if "rerank_score" in h]


def _collect(cases: list[dict], scope: str) -> tuple[list[float], list[float], int, int]:
    """Run reranked search over every case; return (relevant, irrelevant) hit-score pools."""
    rel: list[float] = []
    irr: list[float] = []
    found_q = 0
    for case in cases:
        hits = _search(case["query"], case.get("scope", scope))
        expected = case["expected"]
        hit_rel = False
        for h in hits:
            if "rerank_score" not in h:  # reranker failed open — not calibratable
                continue
            s = float(h["rerank_score"])
            if any(_matches(h, t) for t in expected):
                rel.append(s)
                hit_rel = True
            else:
                irr.append(s)
        found_q += 1 if hit_rel else 0
    return rel, irr, found_q, len(cases)


def _top_scores(cases: list[dict], scope: str) -> list[float]:
    """Per-query best passage score = max(rerank_score) — what abstention thresholds on."""
    out: list[float] = []
    for case in cases:
        scores = _rerank_scores(_search(case["query"], case.get("scope", scope)))
        if scores:
            out.append(max(scores))
    return out


def _report_per_hit(rel: list[float], irr: list[float], found_q: int, n_q: int) -> float:
    """Passage-level separability (idea.md §5.5). Returns ROC-AUC."""
    auc = _auc(rel, irr)
    rel_p = {p: _percentile(rel, p) for p in (0.10, 0.25, 0.50)}
    irr_p = {p: _percentile(irr, p) for p in (0.50, 0.75, 0.90)}
    print("── PER-HIT (passage-level separability) ──")
    print(
        f"relevant hits:   n={len(rel):>4}  "
        f"p10={rel_p[0.10]:+.3f}  p25={rel_p[0.25]:+.3f}  p50={rel_p[0.50]:+.3f}"
    )
    print(
        f"irrelevant hits: n={len(irr):>4}  "
        f"p50={irr_p[0.50]:+.3f}  p75={irr_p[0.75]:+.3f}  p90={irr_p[0.90]:+.3f}"
    )
    print(f"queries with a relevant hit in top-{_DEPTH}: {found_q}/{n_q}")
    print(f"ROC-AUC:                       {auc:.3f}   (0.5 = none, 1.0 = perfect)\n")
    return auc


def _report_query_level(answer: list[float], abstain: list[float], min_recall: float) -> dict:
    """Query-level (top-hit) separation — what abstention actually thresholds on."""
    ans_p = {p: _percentile(answer, p) for p in (0.10, 0.25, 0.50)}
    abs_p = {p: _percentile(abstain, p) for p in (0.50, 0.75, 0.90)}
    tau_j = _best_tau_youden(answer, abstain)
    auc_q = _auc(answer, abstain)
    # When the answer/abstain top-scores separate, the maximum-margin τ is the midpoint
    # of the gap — the choice most robust to unseen queries. Fall back to the recall-
    # constrained conservative τ when they overlap.
    clean = ans_p[0.10] > abs_p[0.90]
    tau = (
        (ans_p[0.10] + abs_p[0.90]) / 2 if clean else _conservative_tau(answer, abstain, min_recall)
    )

    def _abstain_rate(t: float) -> tuple[float, float]:
        # (should-answer wrongly abstained, should-abstain correctly abstained)
        return (
            sum(1 for s in answer if s < t) / len(answer),
            sum(1 for s in abstain if s < t) / len(abstain),
        )

    print("── QUERY-LEVEL (top-hit; abstention decision) ──")
    print(
        f"should-ANSWER  top-score: n={len(answer):>3}  "
        f"p10={ans_p[0.10]:+.3f}  p25={ans_p[0.25]:+.3f}  p50={ans_p[0.50]:+.3f}"
    )
    print(
        f"should-ABSTAIN top-score: n={len(abstain):>3}  "
        f"p50={abs_p[0.50]:+.3f}  p75={abs_p[0.75]:+.3f}  p90={abs_p[0.90]:+.3f}"
    )
    print(f"query-level ROC-AUC:           {auc_q:.3f}")
    print(
        f"gap answer-p10 − abstain-p90:  {ans_p[0.10] - abs_p[0.90]:+.3f}   "
        f"(>0 = a τ separates them)"
    )
    fj, tj = _abstain_rate(tau_j)
    fr, tr = _abstain_rate(tau)
    print(
        f"τ (Youden):                    {tau_j:+.3f}  "
        f"→ false-abstain {fj:.0%}, correct-abstain {tj:.0%}"
    )
    print(
        f"τ ({'max-margin midpoint' if clean else 'conservative'}):        "
        f"{tau:+.3f}  → false-abstain {fr:.0%}, correct-abstain {tr:.0%}   <- recommended\n"
    )

    verdict = (
        "SHIP: answer/abstain top-scores separate — abstention is viable."
        if auc_q >= 0.90 and clean
        else "SHIP (conservative): usable τ with few false abstains; tune per-DB."
        if auc_q >= 0.80 and tr >= 0.5
        else "CAUTION: weak query-level separation — inspect before shipping."
    )
    print(f"VERDICT: {verdict}")
    return {
        "auc_query": round(auc_q, 4),
        "tau_youden": round(tau_j, 4),
        "tau": round(tau, 4),
        "answer_p10": round(ans_p[0.10], 4),
        "abstain_p90": round(abs_p[0.90], 4),
        "false_abstain": round(fr, 4),
        "correct_abstain": round(tr, 4),
        "n_answer": len(answer),
        "n_abstain": len(abstain),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Stage E abstention calibration")
    ap.add_argument("--db", required=True, help="database name (e.g. KI)")
    ap.add_argument(
        "--fixture", help="should-answer fixture (default: bench/fixture_<db>_chunk.json)"
    )
    ap.add_argument(
        "--negatives", help="should-abstain fixture (default: bench/fixture_<db>_negatives.json)"
    )
    ap.add_argument("--scope", default="both", choices=["raw", "wiki", "both"])
    ap.add_argument(
        "--min-recall",
        type=float,
        default=0.90,
        help="conservative-τ target: fraction of should-answer queries to keep",
    )
    ap.add_argument(
        "--write", action="store_true", help="persist derived τ to data/<db>/index/calibration.json"
    )
    args = ap.parse_args()

    db_context.set_active_db(args.db)
    fixture_path = Path(args.fixture or f"bench/fixture_{args.db}_chunk.json")
    if not fixture_path.exists():
        print(f"fixture not found: {fixture_path}", file=sys.stderr)
        return 2
    if not embed_index.available():
        print(
            f"ERROR: no semantic index for '{args.db}'. Run "
            f"scripts/backfill_embeddings.py {args.db}",
            file=sys.stderr,
        )
        return 2
    if not rerank.available():
        print(
            "ERROR: calibration needs the reranker (llama-cpp-python + GGUF at "
            f"{rerank._model_path()}). Without it there is no score to calibrate.",
            file=sys.stderr,
        )
        return 2

    cases = json.loads(fixture_path.read_text())["queries"]
    neg_path = Path(args.negatives or f"bench/fixture_{args.db}_negatives.json")
    print(
        f"DB={args.db}  answer-fixture={fixture_path}  cases={len(cases)}  "
        f"model={rerank._model_path().name}"
    )
    print(f"abstain-fixture={neg_path if neg_path.exists() else '(none — per-hit only)'}\n")

    rel, irr, found_q, n_q = _collect(cases, args.scope)
    if not rel or not irr:
        print("ERROR: could not collect both relevant and irrelevant scored hits.", file=sys.stderr)
        return 1
    auc_hit = _report_per_hit(rel, irr, found_q, n_q)

    summary: dict = {"auc_hit": round(auc_hit, 4)}
    if neg_path.exists():
        answer_tops = _top_scores(cases, args.scope)
        abstain_tops = _top_scores(json.loads(neg_path.read_text())["queries"], args.scope)
        if answer_tops and abstain_tops:
            summary = {
                **_report_query_level(answer_tops, abstain_tops, args.min_recall),
                "auc_hit": round(auc_hit, 4),
            }
    else:
        # No negatives: fall back to a per-hit conservative τ (weaker, toothless bias).
        summary["tau"] = round(_conservative_tau(rel, irr, args.min_recall), 4)
        print(
            "(no negatives fixture — τ from per-hit recall only; add one for a "
            "meaningful threshold)"
        )

    if args.write:
        out = db_context.index_dir() / "calibration.json"
        out.write_text(
            json.dumps(
                {
                    "model": rerank._model_path().name,
                    "computed_at": datetime.now(UTC).isoformat(timespec="seconds"),
                    "answer_fixture": fixture_path.name,
                    "abstain_fixture": neg_path.name if neg_path.exists() else None,
                    **summary,
                },
                indent=2,
            )
        )
        print(f"\nwrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
