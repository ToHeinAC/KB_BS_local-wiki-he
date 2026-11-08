"""FF1 arm R4: the same vectors in a vector database (research_notes/retrieval_deepchat/).

Only the store of the dense arm changes: `embed_index.query` is swapped for an ANN search in
LanceDB over `vectors.npy`, and fusion and rerank stay as they are. That isolates the store's
effect. It also times the store against today's brute force on padded matrices (random unit
vectors added, so it measures latency, not quality). LanceDB is an experiment and no project
dependency (AGENTS.md §5.3): it comes in with `--with`, and all files stay under `--dir`.

Usage:
    DATA_ROOT=<scratch> uv run --with lancedb python scripts/bench_study_vectordb.py \
        --dir <scratch>/lance --out run.json
"""

from __future__ import annotations

import argparse
import functools
import json
import shutil
import sys
import time
from pathlib import Path
from typing import Any

import lancedb  # pyright: ignore[reportMissingImports]
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import bench_study

import db_context
import embed_index
import retrieval

SIZES = (533, 10_000, 100_000)
ROUNDS = 5  # each question's search is repeated this often per timing
ROWS_PER_PARTITION = 4096  # LanceDB's guidance for the IVF layer


def _matrix(n: int, real: np.ndarray) -> np.ndarray:
    """`n` unit rows as float32: the real vectors first, then random ones."""
    real = real[: min(n, len(real))]
    rng = np.random.default_rng(0)
    pad = rng.standard_normal((n - len(real), real.shape[1]), dtype=np.float32)
    pad /= np.linalg.norm(pad, axis=1, keepdims=True)
    return np.vstack([real, pad])


def _table(root: Path, name: str, matrix: np.ndarray, scopes: list[str]) -> tuple[Any, float]:
    """A table with an HNSW index over `matrix`, and the seconds it took to build."""
    started = time.perf_counter()
    table = lancedb.connect(str(root)).create_table(
        name,
        data=[{"idx": i, "scope": scopes[i], "vector": v.tolist()} for i, v in enumerate(matrix)],
        mode="overwrite",
    )
    table.create_index(
        metric="cosine",
        index_type="IVF_HNSW_SQ",
        vector_column_name="vector",
        num_partitions=max(1, len(matrix) // ROWS_PER_PARTITION),
    )
    return table, time.perf_counter() - started


def _ids(
    table: Any, query: np.ndarray, k: int, scope: str | None = None, exact: bool = False
) -> Any:
    search = table.search(query, vector_column_name="vector").distance_type("cosine")
    if scope:
        search = search.where(f"scope = '{scope}'", prefilter=True)
    if exact:
        search = search.bypass_vector_index()
    return search.limit(k).select(["idx"]).to_list()


def ann_query(
    table: Any, rows: list[dict[str, Any]], q: str, top_k: int = 10, scope: str | None = None
) -> list[dict[str, Any]]:
    """`embed_index.query` answered from the table: same hit shape, same query vector."""
    qv = embed_index._embed_query(q, embed_index.model_name()).astype(np.float32)  # pyright: ignore[reportPrivateUsage]
    cache: dict[str, dict[str, str]] = {}
    return [
        embed_index._to_hit(  # pyright: ignore[reportPrivateUsage]
            rows[r["idx"]],
            1.0 - float(r["_distance"]),
            embed_index._row_text(rows[r["idx"]], cache),  # pyright: ignore[reportPrivateUsage]
        )
        for r in _ids(table, qv, top_k, scope)
    ]


def _timed(fn: Any, queries: np.ndarray) -> dict[str, float]:
    times = []
    for _ in range(ROUNDS):
        for q in queries:
            started = time.perf_counter()
            fn(q)
            times.append(1000 * (time.perf_counter() - started))
    times.sort()
    return {
        "ms_p50": round(times[len(times) // 2], 2),
        "ms_p95": round(times[int(len(times) * 0.95)], 2),
    }


def scaling(
    root: Path, real: np.ndarray, meta: dict[str, Any], queries: np.ndarray
) -> list[dict[str, Any]]:
    """Today's search against the table on padded matrices, and the index's recall."""
    out = []
    for n in SIZES:
        matrix = _matrix(n, real)
        half = matrix.astype(np.float16)
        np.save(root / "pad.npy", half)
        (root / "pad.json").write_text(
            json.dumps({"rows": (meta["rows"] * (n // len(meta["rows"]) + 1))[:n]})
        )

        def today(q: np.ndarray) -> None:  # what embed_index.query does per call
            json.loads((root / "pad.json").read_text())
            m = np.load(root / "pad.npy")
            np.argsort(-(m.astype(np.float32) @ q))[:10]

        def cached(q: np.ndarray, m: np.ndarray = matrix) -> None:
            np.argsort(-(m @ q))[:10]

        table, build = _table(root / "scale", f"n{n}", matrix, ["raw"] * n)
        hits = [
            len(
                {r["idx"] for r in _ids(table, q, 10)}
                & {r["idx"] for r in _ids(table, q, 10, exact=True)}
            )
            for q in queries
        ]
        row = {
            "rows": n,
            "npy_mb": round(half.nbytes / 1e6, 1),
            "lance_mb": round(
                sum(
                    f.stat().st_size
                    for f in (root / "scale" / f"n{n}.lance").rglob("*")
                    if f.is_file()
                )
                / 1e6,
                1,
            ),
            "lance_build_s": round(build, 1),
            "ann_recall@10": round(sum(hits) / (10 * len(hits)), 3),
            "today": _timed(today, queries),
            "numpy_in_memory": _timed(cached, queries),
            "lance_ann": _timed(lambda q, t=table: _ids(t, q, 10), queries),
        }
        print(row, flush=True)
        out.append(row)
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n", 1)[0])
    ap.add_argument("--gold", type=Path, default=bench_study.FIXTURE)
    ap.add_argument("--dir", type=Path, required=True, help="scratch folder for the tables")
    ap.add_argument("--out", type=Path, help="write the results as JSON")
    args = ap.parse_args()
    fixture = json.loads(args.gold.read_text(encoding="utf-8"))
    db_context.set_active_db(fixture["db"])
    db_context.set_search_scope([fixture["db"]])
    shutil.rmtree(args.dir, ignore_errors=True)
    args.dir.mkdir(parents=True)

    meta = json.loads(embed_index._meta_path().read_text())  # pyright: ignore[reportPrivateUsage]
    real = np.load(embed_index._vectors_path()).astype(np.float32)  # pyright: ignore[reportPrivateUsage]
    rows = meta["rows"]
    table, build = _table(args.dir / "real", "chunks", real, [r.get("scope", "raw") for r in rows])
    embed_index.query = functools.partial(ann_query, table, rows)
    result: dict[str, Any] = {"build_s": round(build, 2)}
    for name, search in {
        "dense_lance": embed_index.query,
        "hybrid_lance": retrieval.search,
        "rerank_lance": functools.partial(retrieval.search, use_rerank=True),
    }.items():
        arm_rows = bench_study.run_arm(fixture, search)
        if name == "rerank_lance" and not bench_study.rerank_ran(arm_rows):
            raise SystemExit("the reranker failed open: this arm would only repeat `hybrid_lance`")
        result[name] = {"summary": bench_study.summary(arm_rows), "rows": arm_rows}
        print(name, result[name]["summary"], flush=True)

    queries = np.stack(
        [
            embed_index._embed_query(q["question"], embed_index.model_name()).astype(np.float32)  # pyright: ignore[reportPrivateUsage]
            for q in fixture["questions"]
        ]
    )
    result["scaling"] = scaling(args.dir, real, meta, queries)
    if args.out:
        args.out.write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )


if __name__ == "__main__":
    main()
