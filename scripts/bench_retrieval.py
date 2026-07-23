"""Retrieval benchmark harness (Stage A.1).

Scores `lex_index.query()` against a hand-labelled fixture and reports
precision@5 / recall@10 / MRR **sliced by query type**. The slice is the point:
an aggregate hides that lexical search wins `exact` and loses `semantic`, which is
the only claim the retrieval rework is testing.

Ground truth is hand-labelled (see bench/fixture_<DB>.json) — never model-generated.

Usage:
    uv run python scripts/bench_retrieval.py --db KI
    uv run python scripts/bench_retrieval.py --db KI --fixture bench/fixture_KI.json
    uv run python scripts/bench_retrieval.py --db KI --scope raw
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import db_context  # noqa: E402
import lex_index  # noqa: E402

PRECISION_K = 5
RECALL_K = 10


def _matches(hit: dict, token: str) -> bool:
    """True if a hit satisfies one expected token.

    A token is a chunk_id, a source filename, or `source#fragment` where the
    fragment must appear (case-insensitively) in the hit's anchor/heading path.
    """
    if token == hit.get("chunk_id") or token == hit.get("source"):
        return True
    if "#" in token:
        src, frag = token.split("#", 1)
        if src == hit.get("source"):
            hay = (hit.get("anchor", "") + " "
                   + " ".join(hit.get("heading_path", []))).lower()
            return frag.strip().lower() in hay
    return False


def _score_query(case: dict, scope: str | None) -> dict:
    """Run one fixture case and return its per-query metrics."""
    q_scope = case.get("scope", scope)
    hits = lex_index.query(case["query"], top_k=RECALL_K,
                           scope=(q_scope if q_scope != "both" else None))
    expected = case["expected"]
    ranks = [i for i, h in enumerate(hits) if any(_matches(h, t) for t in expected)]
    found = {t for t in expected for h in hits[:RECALL_K] if _matches(h, t)}
    rel_in_5 = sum(1 for r in ranks if r < PRECISION_K)
    return {
        "hits": len(hits),
        "precision@5": rel_in_5 / PRECISION_K,
        "recall@10": (len(found) / len(expected)) if expected else 0.0,
        "mrr": (1.0 / (ranks[0] + 1)) if ranks else 0.0,
    }


def _mean(rows: list[dict], key: str) -> float:
    return sum(r[key] for r in rows) / len(rows) if rows else 0.0


def _report(results: list[tuple[dict, dict]]) -> None:
    by_type: dict[str, list[dict]] = defaultdict(list)
    for case, m in results:
        by_type[case.get("type", "untyped")].append(m)
    hdr = f"{'slice':<14}{'n':>4}{'P@5':>8}{'R@10':>8}{'MRR':>8}"
    print(hdr)
    print("-" * len(hdr))
    for t in sorted(by_type):
        rows = by_type[t]
        print(f"{t:<14}{len(rows):>4}{_mean(rows,'precision@5'):>8.3f}"
              f"{_mean(rows,'recall@10'):>8.3f}{_mean(rows,'mrr'):>8.3f}")
    allm = [m for _, m in results]
    print("-" * len(hdr))
    print(f"{'ALL':<14}{len(allm):>4}{_mean(allm,'precision@5'):>8.3f}"
          f"{_mean(allm,'recall@10'):>8.3f}{_mean(allm,'mrr'):>8.3f}")


def main() -> int:
    ap = argparse.ArgumentParser(description="LocalWiki retrieval benchmark")
    ap.add_argument("--db", required=True, help="database name (e.g. KI)")
    ap.add_argument("--fixture", help="path to fixture JSON (default: bench/fixture_<db>.json)")
    ap.add_argument("--scope", default="both", choices=["raw", "wiki", "both"],
                    help="default retrieval scope; a case may override with its own 'scope'")
    args = ap.parse_args()

    db_context.set_active_db(args.db)
    fixture_path = Path(args.fixture or f"bench/fixture_{args.db}.json")
    if not fixture_path.exists():
        print(f"fixture not found: {fixture_path}", file=sys.stderr)
        return 2
    cases = json.loads(fixture_path.read_text())["queries"]

    results = [(c, _score_query(c, args.scope)) for c in cases]
    # Fail loud on an unindexed corpus rather than reporting silent zeros.
    if sum(m["hits"] for _, m in results) == 0:
        print(f"ERROR: 0 hits for every query — is the '{args.db}' index built?\n"
              f"Rebuild it (ingest, or a rebuild run) before benchmarking.",
              file=sys.stderr)
        return 1

    print(f"DB={args.db}  fixture={fixture_path}  cases={len(cases)}  scope={args.scope}\n")
    _report(results)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
