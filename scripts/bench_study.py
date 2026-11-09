"""Retrieval arms of the study in research_notes/retrieval_deepchat/00_framework.md (FF1).

Scores each arm over the originals (`scope="raw"`) at section level: the parts of a long §
count as one rank, and gold labels are checked against the ingested text first. No LLM, and
it never writes `data/`; point `DATA_ROOT` at a scratch copy.

Usage:
    DATA_ROOT=<scratch> uv run python scripts/bench_study.py --out run.json
    DATA_ROOT=<scratch> uv run python scripts/bench_study.py --arm hybrid --arm rerank
"""

from __future__ import annotations

import argparse
import functools
import json
import math
import re
import sys
import time
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import chunker
import db_context
import embed_index
import lex_index
import retrieval

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "bench" / "fixture_study_StrlSch_DE.json"
FETCH = 60  # chunks per search; ranks are counted over the distinct sections among them
CUTOFFS = (5, 10)
_PART_RE = re.compile(r" \(Teil \d+\)$")

Hit = dict[str, Any]
Search = Callable[..., list[Hit]]

ARMS: dict[str, Search] = {
    "lexical": lex_index.query,
    "dense": embed_index.query,
    "hybrid": retrieval.search,
    "rerank": functools.partial(retrieval.search, use_rerank=True),
}


def section_of(anchor: str) -> str:
    """The section a chunk belongs to: `§ 1 (Teil 2)` is `§ 1`."""
    return _PART_RE.sub("", anchor)


def rank_of(gold: dict[str, str], hits: Sequence[Hit]) -> int | None:
    """1-based rank of the gold section among the distinct sections of `hits`, or None. A
    gold `part` counts only that part of a long annex, which still ranks as its section."""
    seen: list[tuple[str, str]] = []
    for hit in hits:
        anchor, source = str(hit.get("anchor") or ""), str(hit.get("source") or "")
        key = (source, section_of(anchor))
        if key not in seen:
            seen.append(key)
        if source != gold["file"]:
            continue
        if anchor == gold["part"] if "part" in gold else key[1] == gold["section"]:
            return seen.index(key) + 1
    return None


def recall_at(ranks: Sequence[int | None], k: int) -> int:
    """Gold sections found within the first `k` sections."""
    return sum(1 for r in ranks if r is not None and r <= k)


def mrr(ranks: Sequence[int | None]) -> float:
    """Reciprocal rank of the question's best gold section."""
    found = [r for r in ranks if r is not None]
    return 1 / min(found) if found else 0.0


def ndcg_at(ranks: Sequence[int | None], k: int) -> float:
    """Binary nDCG over the question's gold sections."""
    gains = sum(1 / math.log2(r + 1) for r in ranks if r is not None and r <= k)
    ideal = sum(1 / math.log2(i + 2) for i in range(min(len(ranks), k)))
    return gains / ideal if ideal else 0.0


def fact_hits(answer: str, facts: Sequence[str]) -> list[bool]:
    """Which mandatory facts (regexes) the answer states, ignoring case and line breaks."""
    text = re.sub(r"\s+", " ", answer)
    return [re.search(f, text, re.IGNORECASE) is not None for f in facts]


def rerank_ran(rows: Sequence[dict[str, Any]]) -> bool:
    """Whether every search carried reranker scores. The reranker fails open by design, so
    without this check a broken model scores as `hybrid` and looks like a result."""
    return all(r["top_score"] is not None for r in rows)


def gold_problems(fixture: dict[str, Any]) -> list[str]:
    """Gold labels that do not match the ingested text, so no arm is scored against them."""
    problems: list[str] = []
    for q in fixture["questions"]:
        for g in q["gold"]:
            want = g.get("part", g["section"])
            parts = [
                c
                for c in chunker.load_chunks(g["file"])
                if c["anchor"] == want or section_of(c["anchor"]) == want
            ]
            title = " ".join(parts[0].get("heading_path") or []) if parts else ""
            if g["heading"].casefold() not in title.casefold():
                problems.append(f"{q['id']} {g['file']} {want}: heading is '{title}'")
    return problems


def corpus(fixture: dict[str, Any]) -> list[dict[str, Any]]:
    """The chunks an experiment encodes itself: the gold file's `files`, or without them every
    source of the database, as the app's own arms search it."""
    if "files" not in fixture:
        return chunker.all_chunks()
    return [{**c, "source": f} for f in fixture["files"] for c in chunker.load_chunks(f)]


def run_arm(fixture: dict[str, Any], search: Search) -> list[dict[str, Any]]:
    """One arm over every question: gold ranks and the search's wall time."""
    rows: list[dict[str, Any]] = []
    for q in fixture["questions"]:
        started = time.perf_counter()
        hits = search(q["question"], FETCH, scope="raw")
        rows.append(
            {
                "id": q["id"],
                "ms": round(1000 * (time.perf_counter() - started), 1),
                "ranks": [rank_of(g, hits) for g in q["gold"]],
                "top": [str(h.get("anchor")) for h in hits[:3]],
                "top_score": hits[0].get("rerank_score") if hits else None,
            }
        )
    return rows


def summary(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """An arm's totals over the questions that have gold."""
    scored = [r for r in rows if r["ranks"]]
    ranks = [x for r in scored for x in r["ranks"]]
    times = sorted(r["ms"] for r in rows)
    return {
        "gold": len(ranks),
        **{f"recall@{k}": recall_at(ranks, k) for k in CUTOFFS},
        "mrr": round(sum(mrr(r["ranks"]) for r in scored) / len(scored), 3),
        "ndcg@10": round(sum(ndcg_at(r["ranks"], 10) for r in scored) / len(scored), 3),
        "ms_p50": times[len(times) // 2],
        "ms_max": times[-1],
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n", 1)[0])
    ap.add_argument("--gold", type=Path, default=FIXTURE)
    ap.add_argument("--arm", action="append", choices=list(ARMS), help="repeatable; default all")
    ap.add_argument("--out", type=Path, help="write the rows as JSON")
    args = ap.parse_args()
    fixture = json.loads(args.gold.read_text(encoding="utf-8"))
    db_context.set_active_db(fixture["db"])
    db_context.set_search_scope([fixture["db"]])
    if problems := gold_problems(fixture):
        raise SystemExit("gold labels wrong:\n" + "\n".join(problems))
    result = {}
    for arm in args.arm or list(ARMS):
        rows = run_arm(fixture, ARMS[arm])
        if arm == "rerank" and not rerank_ran(rows):
            raise SystemExit("the reranker failed open: this arm would only repeat `hybrid`")
        result[arm] = {"summary": summary(rows), "rows": rows}
        print(arm, result[arm]["summary"])
    if args.out:
        args.out.write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )


if __name__ == "__main__":
    main()
