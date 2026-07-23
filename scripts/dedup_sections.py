"""Collapse consecutive duplicate `##` sections in wiki pages.

Fixes a small-model ingest artifact where a page emits the same level-2 heading
twice (e.g. `## Key facts` as an outline, then again as real content). The cleanup
is deterministic (okf.collapse_duplicate_sections): among a run of adjacent
same-name sections it keeps the one with the most body text and drops the rest.

Dry-run by default — prints what would change and writes nothing until `--apply`.
When it changes a DB's pages, it rebuilds that DB's lexical index so search stays
in sync.

Usage:
    uv run python scripts/dedup_sections.py KI            # dry-run one DB
    uv run python scripts/dedup_sections.py KI --apply     # apply
    uv run python scripts/dedup_sections.py --all          # dry-run every DB
    uv run python scripts/dedup_sections.py --all --apply   # apply to all
"""

import argparse
import sys
from pathlib import Path

import frontmatter

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import db_context  # noqa: E402
import lex_index  # noqa: E402
import okf  # noqa: E402

_RESERVED = ("index.md", "log.md", "DESCRIPTION.md")


def _pages(wiki: Path) -> list[Path]:
    return [p for p in sorted(wiki.rglob("*.md")) if p.name not in _RESERVED]


def dedup_db(db: str, *, apply: bool) -> dict:
    db_context.set_active_db(db)
    wiki = db_context.wiki_dir()
    changed: list[tuple[str, int]] = []
    if wiki.exists():
        for page in _pages(wiki):
            post = frontmatter.load(str(page))
            new_body, removed = okf.collapse_duplicate_sections(post.content)
            if removed:
                changed.append((page.name, removed))
                if apply:
                    post.content = new_body
                    page.write_text(frontmatter.dumps(post) + "\n")
    if apply and changed:
        lex_index.build()  # keep postings/FTS5 in sync with the edited bodies
    return {"changed": changed}


def _report(db: str, res: dict) -> None:
    changed = res["changed"]
    print(f"\n=== {db} ===")
    if not changed:
        print("  no duplicate sections")
        return
    total = sum(n for _, n in changed)
    print(f"  {len(changed)} page(s), {total} section(s) removed:")
    for name, n in changed:
        print(f"    {name}  (-{n})")


def main() -> int:
    ap = argparse.ArgumentParser(description="Collapse duplicate `##` sections")
    ap.add_argument("db", nargs="?", help="database name (omit with --all)")
    ap.add_argument("--all", action="store_true", help="every DB under data/")
    ap.add_argument("--apply", action="store_true", help="write changes (default: dry-run)")
    args = ap.parse_args()

    dbs = db_context.list_dbs() if args.all else ([args.db] if args.db else [])
    if not dbs:
        ap.error("give a DB name or --all")

    mode = "APPLY" if args.apply else "DRY-RUN"
    print(f"[{mode}] collapsing duplicate sections across {len(dbs)} DB(s)")
    grand = 0
    for db in dbs:
        res = dedup_db(db, apply=args.apply)
        _report(db, res)
        grand += sum(n for _, n in res["changed"])
    print(f"\nTotal sections {'removed' if args.apply else 'to remove'}: {grand}")
    if not args.apply and grand:
        print("Re-run with --apply to write.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
