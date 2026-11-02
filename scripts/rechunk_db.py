"""Re-split a database's text originals whose chunking has changed, then rebuild its index.

Originals converted from PDF before `md_convert.clean_text` existed still carry pdfium's
line-end hyphen marker (U+FFFE: "Gru\ufffebenwässer", which search cannot find as one
word); such an original is cleaned in place first — every word kept — and re-split.

Chunks are derived from `raw/` (AGENTS.md §5.3), so a chunker change — e.g. statutes with
plain `§ N Title` headings, which used to become anonymous `part N` windows — only reaches
an existing database by re-splitting it. Only text originals (.md, .txt, .html) that
already have chunks are considered; a source whose new chunks carry the same anchors is
left alone. Changed sources are re-embedded when the database has vectors, and the
lexical index is rebuilt once. Without `--apply` it only lists what would change.

Usage:
    uv run python scripts/rechunk_db.py --db KI            # dry run
    uv run python scripts/rechunk_db.py --db KI --apply
    uv run python scripts/rechunk_db.py --all              # every database, dry run
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
import md_convert
import wiki_engine

_TEXT_EXTS = (".md", ".txt", ".html")


def _text(name: str) -> str:
    """The original as ingest chunks it (line ends kept)."""
    return (wiki_engine.read_raw_source(name) or b"").decode("utf-8", errors="replace")


def _changed(name: str, old: list[dict[str, object]]) -> int | None:
    """The new chunk count of original `name` if it needs cleaning or its re-split chunks
    carry other anchors than the stored `old` ones, else None."""
    text = _text(name)
    clean = md_convert.clean_text(text)
    new = chunker.split(clean)
    if new and (clean != text or [c["anchor"] for c in new] != [c["anchor"] for c in old]):
        return len(new)
    return None


def changed_sources() -> list[tuple[str, int, int]]:
    """(source, old chunk count, new chunk count) of each text original in the bound DB
    that needs cleaning or whose re-split chunks carry other anchors."""
    out: list[tuple[str, int, int]] = []
    for path in sorted(db_context.raw_dir().iterdir()):
        old = chunker.load_chunks(path.name) if path.suffix.lower() in _TEXT_EXTS else []
        count = _changed(path.name, old) if old else None
        if count is not None:
            out.append((path.name, len(old), count))
    return out


def rechunk(apply: bool) -> list[tuple[str, int, int]]:
    """The changed sources of the bound DB; with `apply`, cleaned, rewritten, re-embedded
    and indexed."""
    changed = changed_sources()
    if not apply or not changed:
        return changed
    for name, _, _ in changed:
        text = _text(name)
        clean = md_convert.clean_text(text)
        if clean != text:
            (db_context.raw_dir() / name).write_bytes(clean.encode("utf-8"))
        chunker.write_chunks(name, chunker.split(clean))
        embed_index.index_replace_source(name, chunker.load_chunks(name))
    wiki_engine.rebuild_lex_index()
    return changed


def databases(db: str | None, every: bool) -> list[str]:
    """The databases to re-split: `db`, or with `every` each database (not its level shards)."""
    names = db_context.list_dbs()
    if every:
        return [n for n in names if classification.LEVEL_SEP not in n]
    if db not in names:
        raise SystemExit(f"no database named {db!r}")
    return [db]


def main() -> None:
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n", 1)[0])
    target = ap.add_mutually_exclusive_group(required=True)
    target.add_argument("--db", help="database name (every level of it)")
    target.add_argument("--all", action="store_true", help="every database")
    ap.add_argument("--apply", action="store_true", help="write; without it, a dry run")
    args = ap.parse_args()
    verb = "re-split" if args.apply else "would re-split"
    for db in databases(args.db, args.all):
        with db_context.clearance({db: len(classification.LEVELS) - 1}):
            for shard in db_context.reachable_shards(db):
                with db_context.using_db(shard):
                    for name, old, new in rechunk(args.apply):
                        print(f"{shard}: {verb} {name}: {old} -> {new} chunks")


if __name__ == "__main__":
    main()
