"""Re-split a database's text originals whose chunking has changed, then rebuild its index.

Chunks are derived from `raw/` (AGENTS.md §5.3), so a chunker change — e.g. statutes with
plain `§ N Title` headings, which used to become anonymous `part N` windows — only reaches
an existing database by re-splitting it. Only text originals (.md, .txt, .html) that
already have chunks are considered; a source whose new chunks carry the same anchors is
left alone. Changed sources are re-embedded when the database has vectors, and the
lexical index is rebuilt once. Without `--apply` it only lists what would change.

Usage:
    uv run python scripts/rechunk_db.py --db KI            # dry run
    uv run python scripts/rechunk_db.py --db KI --apply
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import chunker
import classification
import db_context
import embed_index
import wiki_engine

_TEXT_EXTS = (".md", ".txt", ".html")


def changed_sources() -> list[tuple[str, int, int]]:
    """(source, old chunk count, new chunk count) of each text original in the bound DB
    whose re-split chunks carry other anchors than the stored ones."""
    out: list[tuple[str, int, int]] = []
    for path in sorted(db_context.raw_dir().iterdir()):
        old = chunker.load_chunks(path.name) if path.suffix.lower() in _TEXT_EXTS else []
        if not old:
            continue
        new = chunker.split(path.read_text(encoding="utf-8", errors="replace"))
        if new and [c["anchor"] for c in new] != [c["anchor"] for c in old]:
            out.append((path.name, len(old), len(new)))
    return out


def rechunk(apply: bool) -> list[tuple[str, int, int]]:
    """The changed sources of the bound DB; with `apply`, rewritten, re-embedded and
    indexed."""
    changed = changed_sources()
    if not apply or not changed:
        return changed
    for name, _, _ in changed:
        data = wiki_engine.read_raw_source(name) or b""
        chunks = chunker.split(data.decode("utf-8", errors="replace"))
        chunker.write_chunks(name, chunks)
        embed_index.index_replace_source(name, chunker.load_chunks(name))
    wiki_engine.rebuild_lex_index()
    return changed


def main() -> None:
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n", 1)[0])
    ap.add_argument("--db", required=True, help="database name (every level of it)")
    ap.add_argument("--apply", action="store_true", help="write; without it, a dry run")
    args = ap.parse_args()
    if args.db not in db_context.list_dbs():
        raise SystemExit(f"no database named {args.db!r}")
    with db_context.clearance({args.db: len(classification.LEVELS) - 1}):
        for shard in db_context.reachable_shards(args.db):
            with db_context.using_db(shard):
                for name, old, new in rechunk(args.apply):
                    verb = "re-split" if args.apply else "would re-split"
                    print(f"{shard}: {verb} {name}: {old} -> {new} chunks")


if __name__ == "__main__":
    main()
