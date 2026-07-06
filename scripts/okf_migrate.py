"""One-off OKF v0.1 backfill for existing knowledge bases.

Makes each `data/<db>/wiki/` a conformant OKF bundle: stamps OKF frontmatter
(description/tags/resource/timestamp) + a `## Citations` section on every page,
rewrites index.md (with `okf_version`) and log.md to OKF format, and rebuilds
the BM25 index so postings/stats stay in sync with the new page bodies.

Everything is deterministic (no LLM) so it is safe and repeatable. Dry-run by
default — writes nothing until `--apply`.

Usage:
    uv run python scripts/okf_migrate.py Investing          # dry-run one DB
    uv run python scripts/okf_migrate.py Investing --apply   # apply
    uv run python scripts/okf_migrate.py --all               # dry-run every DB
    uv run python scripts/okf_migrate.py --all --apply        # apply to all 8
"""

import argparse
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import db_context  # noqa: E402
import lex_index  # noqa: E402
import okf  # noqa: E402
import wiki_engine  # noqa: E402

_RESERVED = ("index.md", "log.md", "DESCRIPTION.md")


def _pages(wiki: Path) -> list[Path]:
    return [p for p in sorted(wiki.rglob("*.md")) if p.name not in _RESERVED]


def migrate_db(db: str, *, apply: bool) -> dict:
    db_context.set_active_db(db)
    wiki = db_context.wiki_dir()
    if not wiki.exists():
        return {"db": db, "pages": 0, "issues": ["no wiki/ dir"], "backup": None}

    backup = wiki.parent / f"wiki.bak_{datetime.now(timezone.utc):%Y%m%d}"
    pages = _pages(wiki)

    if apply:
        if not backup.exists():
            shutil.copytree(wiki, backup)
        for p in pages:
            p.write_text(okf.apply_to_page(p.read_text(), db=db))
        log = wiki / "log.md"
        if log.exists():
            log.write_text(okf.reformat_log(log.read_text()))
        wiki_engine._rebuild_index()       # OKF index.md + okf_version
        lex_index.build()                   # resync postings/stats to new bodies

    issues = okf.okf_validate(wiki) if apply else []
    return {"db": db, "pages": len(pages),
            "issues": issues, "backup": str(backup) if apply else None}


def main() -> None:
    ap = argparse.ArgumentParser(description="OKF v0.1 backfill migration.")
    ap.add_argument("db", nargs="?", help="database name (omit with --all)")
    ap.add_argument("--all", action="store_true", help="every DB under data/")
    ap.add_argument("--apply", action="store_true", help="write changes (default: dry-run)")
    args = ap.parse_args()

    dbs = db_context.list_dbs() if args.all else ([args.db] if args.db else [])
    if not dbs:
        ap.error("give a DB name or --all")

    mode = "APPLY" if args.apply else "DRY-RUN"
    print(f"OKF migration [{mode}] — {len(dbs)} database(s)")
    failed = False
    for db in dbs:
        res = migrate_db(db, apply=args.apply)
        status = "ok" if not res["issues"] else f"{len(res['issues'])} ISSUE(S)"
        print(f"\n=== {res['db']} ===  pages={res['pages']}  {status}")
        if res["backup"]:
            print(f"  backup: {res['backup']}")
        for i in res["issues"]:
            print(f"  ! {i}")
            failed = True
    if not args.apply:
        print("\n(dry-run — re-run with --apply to write; validation runs after apply)")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
