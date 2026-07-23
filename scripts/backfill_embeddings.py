"""Backfill the semantic (embedding) index for one or more DBs — Stage C.

Chunks are already persisted in data/<DB>/chunks/*.jsonl with stable content-
addressed chunk_ids, so this re-embeds an existing corpus with no re-ingest. The
vectors are a pure derived cache (embed_index.build regenerates them from chunks/
+ wiki/); re-running is safe and overwrites.

Requires a local embedding model pulled in Ollama (default `bge-m3`; override with
EMBED_MODEL). For a German legal corpus a multilingual model such as bge-m3 is the
right default — see idea.md DECISION 5; switching models later forces a full
re-embed (vectors are not cross-compatible).

Usage:
    ollama pull bge-m3
    uv run python scripts/backfill_embeddings.py KI
    uv run python scripts/backfill_embeddings.py --all
    EMBED_MODEL=snowflake-arctic-embed2 uv run python scripts/backfill_embeddings.py KI
"""

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import db_context  # noqa: E402
import embed_index  # noqa: E402
import ollama_client  # noqa: E402


def _backfill(db: str) -> dict:
    db_context.set_active_db(db)
    start = time.time()

    def _progress(done: int, total: int) -> None:
        print(f"\r  {db}: embedded {done}/{total} chunks", end="", flush=True)

    summary = embed_index.build(progress=_progress)
    print(f"\r  {db}: {summary['chunks']} chunks, model={summary['model']}, "
          f"dim={summary.get('dim', 0)}  ({time.time() - start:.1f}s)")
    return summary


def main() -> int:
    ap = argparse.ArgumentParser(description="Backfill embeddings for DB(s)")
    ap.add_argument("db", nargs="?", help="database name (omit with --all)")
    ap.add_argument("--all", action="store_true", help="every DB under data/")
    args = ap.parse_args()

    if not ollama_client.is_available():
        print("ERROR: Ollama not reachable. Start it and `ollama pull bge-m3`.",
              file=sys.stderr)
        return 2

    dbs = db_context.list_dbs() if args.all else ([args.db] if args.db else [])
    if not dbs:
        ap.error("give a DB name or --all")

    print(f"Backfilling embeddings (model={embed_index._model()}) for {len(dbs)} DB(s)")
    grand = 0
    for db in dbs:
        try:
            grand += _backfill(db)["chunks"]
        except Exception as exc:
            print(f"\n  {db}: FAILED — {exc}", file=sys.stderr)
    print(f"Total chunks embedded: {grand}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
