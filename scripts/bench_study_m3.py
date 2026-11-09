"""FF1 arm R5: bge-m3's sparse and multi-vector output (research_notes/retrieval_deepchat/).

Ollama's `/api/embed` gives bge-m3's dense vector only, so this runs the model through
FlagEmbedding. It is an experiment and no project dependency (AGENTS.md §5.3): it comes in
with `--with`. Scored both alone and in place of the dense arm in the app's own fusion and
rerank, which shows what a richer representation could gain whatever store holds it.

Usage:
    DATA_ROOT=<scratch> uv run --with FlagEmbedding python scripts/bench_study_m3.py --out run.json
"""

from __future__ import annotations

import argparse
import functools
import json
import sys
from pathlib import Path
from typing import Any

import numpy as np
from FlagEmbedding import BGEM3FlagModel  # pyright: ignore[reportMissingImports]

sys.path.insert(0, str(Path(__file__).resolve().parent))
import bench_study

import db_context
import embed_index
import retrieval

MAX_LENGTH = 1024  # a chunk holds at most 4000 characters
BATCH = 8
WEIGHTS = (0.4, 0.2, 0.4)  # dense, sparse, multi-vector: the model card's example


def _encode(model: Any, texts: list[str]) -> dict[str, Any]:
    return model.encode(
        texts,
        batch_size=BATCH,
        max_length=MAX_LENGTH,
        return_dense=True,
        return_sparse=True,
        return_colbert_vecs=True,
    )


def _scores(model: Any, q: str, docs: dict[str, Any]) -> dict[str, np.ndarray]:
    """Each document's score for `q`, per output of the model and combined."""
    qv = model.encode(
        [q], max_length=MAX_LENGTH, return_dense=True, return_sparse=True, return_colbert_vecs=True
    )
    dense = docs["dense_vecs"] @ qv["dense_vecs"][0]
    sparse = np.array(
        [
            model.compute_lexical_matching_score(qv["lexical_weights"][0], d)
            for d in docs["lexical_weights"]
        ]
    )
    multi = np.array(
        [float(model.colbert_score(qv["colbert_vecs"][0], d)) for d in docs["colbert_vecs"]]
    )
    combined = WEIGHTS[0] * dense + WEIGHTS[1] * sparse + WEIGHTS[2] * multi
    return {"m3_dense": dense, "m3_sparse": sparse, "m3_multi": multi, "m3_combined": combined}


def _search(
    model: Any,
    docs: dict[str, Any],
    chunks: list[dict[str, Any]],
    output: str,
    q: str,
    top_k: int = 10,
    scope: str | None = None,
) -> list[dict[str, Any]]:
    """`embed_index.query` answered from one output of the model (originals only)."""
    if scope == "wiki":
        return []
    scores = _scores(model, q, docs)[output]
    return [
        embed_index._to_hit(chunks[int(i)], float(scores[int(i)]), chunks[int(i)]["text"])  # pyright: ignore[reportPrivateUsage]
        for i in np.argsort(-scores)[:top_k]
    ]


def main() -> None:
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n", 1)[0])
    ap.add_argument("--gold", type=Path, default=bench_study.FIXTURE)
    ap.add_argument("--out", type=Path)
    args = ap.parse_args()
    fixture = json.loads(args.gold.read_text(encoding="utf-8"))
    db_context.set_active_db(fixture["db"])
    db_context.set_search_scope([fixture["db"]])
    chunks = bench_study.corpus(fixture)
    model = BGEM3FlagModel("BAAI/bge-m3", use_fp16=False)
    docs = _encode(model, [c["text"] for c in chunks])
    print("encoded", len(chunks), flush=True)
    result: dict[str, Any] = {}
    for output in ("m3_dense", "m3_sparse", "m3_multi", "m3_combined"):
        search = functools.partial(_search, model, docs, chunks, output)
        rows = bench_study.run_arm(fixture, search)
        result[output] = {"summary": bench_study.summary(rows), "rows": rows}
        print(output, result[output]["summary"], flush=True)
    embed_index.query = functools.partial(_search, model, docs, chunks, "m3_combined")
    embed_index.available = lambda: True
    rows = bench_study.run_arm(fixture, functools.partial(retrieval.search, use_rerank=True))
    if not bench_study.rerank_ran(rows):
        raise SystemExit("the reranker failed open: this arm would only repeat the fusion")
    result["rerank_m3"] = {"summary": bench_study.summary(rows), "rows": rows}
    print("rerank_m3", result["rerank_m3"]["summary"], flush=True)
    if args.out:
        args.out.write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )


if __name__ == "__main__":
    main()
