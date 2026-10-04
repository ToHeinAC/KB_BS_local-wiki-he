"""Rebuild every search index that is missing while its database has content.

A missing or unreadable `index/chunks.sqlite` makes `lex_index.query()` silently empty, which
empties search, both chat modes and the research agent (AGENTS.md §5.3); the index is a
derived cache, so the fix is always a rebuild. `scripts/run_app.py` runs this before
it starts the server. Each database is checked under a clearance for that database alone,
one level (shard) at a time; a failing shard is reported and skipped.

Usage:
    uv run python scripts/heal_indexes.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import classification
import db_context
import lex_index
import wiki_engine

_TOP_LEVEL = len(classification.LEVELS) - 1


def _heal_shard(shard: str) -> bool:
    """Rebuild `shard`'s index if it has content but no index; whether it was rebuilt."""
    try:
        with db_context.using_db(shard):
            if not lex_index.needs_rebuild():
                return False
            print(f"heal_indexes: search index of {shard} is missing, rebuilding", file=sys.stderr)
            wiki_engine.rebuild_lex_index()
    except Exception as exc:
        print(f"heal_indexes: rebuilding {shard} failed: {exc}", file=sys.stderr)
        return False
    return True


def heal() -> list[str]:
    """The shards whose index was rebuilt."""
    healed: list[str] = []
    for db in db_context.list_dbs():
        with db_context.clearance({db: _TOP_LEVEL}):
            healed += [s for s in db_context.reachable_shards(db) if _heal_shard(s)]
    return healed


if __name__ == "__main__":
    heal()
