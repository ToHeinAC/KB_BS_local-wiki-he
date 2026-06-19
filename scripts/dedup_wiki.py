"""One-off wiki consolidation CLI.

Collapses legacy chunk-derived duplicate pages (per-Teil summaries and
near-duplicate concept pages) into one page per topic. Dry-run by default —
prints the merge plan and writes nothing until `--apply` is passed.

Usage:
    uv run python scripts/dedup_wiki.py KI            # dry-run on one DB
    uv run python scripts/dedup_wiki.py KI --apply    # apply
    uv run python scripts/dedup_wiki.py --all         # dry-run on every DB
    uv run python scripts/dedup_wiki.py --all --apply --llm-polish
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import db_context  # noqa: E402
import wiki_engine  # noqa: E402


def _report(db: str, res: dict) -> None:
    print(f"\n=== {db} ===")
    print(f"pages {res['before']} -> {res['after']}  (merging {len(res['rename'])})")
    for canonical, members in res["groups"]:
        dropped = [m for m in members if m != canonical]
        if dropped:
            print(f"  {canonical}  <-  {', '.join(dropped)}")
        else:
            print(f"  {canonical}  (cleanup only)")


def main() -> None:
    ap = argparse.ArgumentParser(description="Consolidate duplicate wiki pages.")
    ap.add_argument("db", nargs="?", help="DB name (omit when using --all)")
    ap.add_argument("--all", action="store_true", help="run on every DB")
    ap.add_argument("--apply", action="store_true",
                    help="write changes (default: dry-run)")
    ap.add_argument("--llm-polish", action="store_true",
                    help="smooth merged prose with the local model (slower)")
    args = ap.parse_args()

    if not args.all and not args.db:
        ap.error("provide a DB name or --all")
    dbs = db_context.list_dbs() if args.all else [args.db]

    for db in dbs:
        res = wiki_engine.consolidate(db, dry_run=not args.apply,
                                      llm_polish=args.llm_polish)
        _report(db, res)

    if not args.apply:
        print("\n(dry-run — re-run with --apply to write changes)")


if __name__ == "__main__":
    main()
