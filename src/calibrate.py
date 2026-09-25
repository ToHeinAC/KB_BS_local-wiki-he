"""Stage E — calibrated abstention.

Turns the Stage D cross-encoder `rerank_score` into an abstention decision: when a
query's best passage scores below a per-DB threshold τ, the honest output is "no page
confidently answers this" — not a synthesis from weakly-matched context (idea.md §3.5/§5.5).
For a regulatory corpus a confident answer from 0.2-relevance context is worse than none.

τ is a per-DB **derived artifact**, calibrated offline by `scripts/calibrate_abstention.py`
from the score separability of should-answer vs should-abstain fixtures (DECISION 8: per-DB,
maintainer-visible, conservative default). It lives in `data/<db>/index/calibration.json` —
a pure cache, never a source of truth; delete it and abstention simply turns off.

FAIL-SAFE, like the rest of the retrieval stack: abstention fires ONLY when a real
calibrated signal exists. No `calibration.json` (DB never calibrated), no `rerank_score`
on the hits (reranker unavailable / failed open), or the master switch off ⇒ `assess()`
reports `confident=True` and the caller answers normally. It never abstains on an
uncalibrated BM25/fused score — search reliability beats an unpredictable gate.
"""

from __future__ import annotations

import json
import math
import os

import db_context

# Logit → (0,1) display spread. ~half the answer/abstain median gap measured on the KI
# fixture, so a below-τ hit renders as a small-but-nonzero confidence rather than ~0.
_TEMP = 4.0


def _enabled() -> bool:
    return os.getenv("ABSTAIN_ENABLED", "1").strip().lower() not in ("0", "false", "no")


def relevance(rerank_score: float) -> float:
    """Monotonic map of the raw cross-encoder logit to (0,1), for display/comparison.

    Temperature-scaled logistic — model-agnostic and bounded; it is presentation only,
    never the abstention decision (that thresholds the raw logit against τ directly).
    """
    return 1.0 / (1.0 + math.exp(-rerank_score / _TEMP))


def threshold(db: str | None = None) -> float | None:
    """Per-DB abstention τ. Reads `data/<db>/index/calibration.json` (the offline
    calibration artifact); falls back to env `ABSTAIN_TAU_DEFAULT`; else None.

    None means *uncalibrated* — the caller must then NOT abstain (fail-safe).
    """
    db = db or db_context.get_active_db()
    path = db_context.DATA_ROOT / db / "index" / "calibration.json"
    try:
        if path.exists():
            tau = json.loads(path.read_text()).get("tau")
            if tau is not None:
                return float(tau)
    except Exception:
        pass
    env = os.getenv("ABSTAIN_TAU_DEFAULT")
    return float(env) if env not in (None, "") else None


def _best(hits: list[dict]) -> tuple[float | None, dict | None]:
    """The highest-`rerank_score` hit — the best passage the query found."""
    scored = [(float(h["rerank_score"]), h) for h in hits if "rerank_score" in h]
    return max(scored, key=lambda t: t[0]) if scored else (None, None)


def justify(
    scored: list[tuple[str, float | None]], tau: float | None, cap: int | None = None
) -> dict:
    """Split (name, best_score) pairs into an audit record for the search ladder.

    Rung 4 of the ladder (idea.md §6.9.1): open the *justified set* — every candidate
    whose evidence clears τ — and log which were kept, dropped below τ, or cut by the cap.
    Fail-open, like the rest of Stage E: a None τ (uncalibrated / no reranker) or a None
    score (candidate the reranker never scored) is KEPT — the gate only ever drops a
    candidate on a genuine below-τ signal. Highest score first, unscored last.

    Returns {tau, kept, below_tau, over_cap}, each list a list of (name, score) pairs.
    """
    ordered = sorted(scored, key=lambda p: (p[1] is None, -(p[1] or 0.0)))
    kept: list[tuple[str, float | None]] = []
    below: list[tuple[str, float | None]] = []
    for name, s in ordered:
        (below if (tau is not None and s is not None and s < tau) else kept).append((name, s))
    over_cap: list[tuple[str, float | None]] = []
    if cap is not None and len(kept) > cap:
        kept, over_cap = kept[:cap], kept[cap:]
    return {"tau": tau, "kept": kept, "below_tau": below, "over_cap": over_cap}


def assess(hits: list[dict], db: str | None = None) -> tuple[bool, float, dict | None]:
    """Decide whether retrieval is confident enough to answer.

    Returns (confident, relevance∈(0,1], closest_hit). Abstain (confident=False) only when
    a calibrated τ exists AND the best passage's raw logit is below it; otherwise confident
    (fail-safe — uncalibrated DB, no reranker, or master switch off never abstains).
    """
    best, hit = _best(hits)
    tau = threshold(db)
    if not _enabled() or best is None or tau is None:
        return True, (relevance(best) if best is not None else 1.0), hit
    return best >= tau, relevance(best), hit
