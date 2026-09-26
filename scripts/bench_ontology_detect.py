"""Ontology detection benchmark (plan Phase 3).

Runs `ontology_detect.detect()` with the shared `core` + `legal-de` modules on the
hand-labelled heads in bench/ontology_detect/ and reports class precision / coverage and
work-id accuracy. Every raw file of the fixture's `negatives_db` (non-legal documents)
must get **no** legal class: each one that does is a false positive.

Ground truth is hand-labelled (bench/fixture_ontology_detect.json) — never model-generated.

A gold file may name its `modules` and a `db` whose raw documents are read at run
time instead of bench/ontology_detect/ (their texts are not copied into git).

Usage:
    uv run python scripts/bench_ontology_detect.py
    uv run python scripts/bench_ontology_detect.py --no-negatives
    uv run python scripts/bench_ontology_detect.py --gold bench/fixture_ontology_detect_KI.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import db_context
import dedup
import ontology
import ontology_detect
import ontology_store

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "bench" / "fixture_ontology_detect.json"
HEADS = ROOT / "bench" / "ontology_detect"


def _schema(modules: list[str]) -> ontology.Schema:
    shared = ontology_store.shared_modules()
    schema, errors = ontology.build_schema([shared[m] for m in modules])
    if schema is None:
        raise SystemExit("schema invalid: " + "; ".join(errors))
    return schema


def _text(name: str, db: str | None) -> str:
    if db is None:
        return (HEADS / name).read_text(encoding="utf-8")
    with db_context.using_db(db):
        return (db_context.raw_dir() / name).read_text(encoding="utf-8", errors="replace")


def _positives(
    schema: ontology.Schema, files: dict[str, Any], db: str | None
) -> tuple[int, int, int, int]:
    """(detected, correct class, correct work, total); prints one line per file."""
    detected = correct = works = 0
    for name, want in files.items():
        got = ontology_detect.detect(_text(name, db), schema)
        detected += got.class_id is not None
        ok_class, ok_work = got.class_id == want["class"], got.work == want["work"]
        correct += ok_class
        works += ok_work
        mark = "ok " if ok_class and ok_work else "ERR"
        print(f"  {mark} {name[:40]:40} class={got.class_id!s:20} want={want['class']}")
    return detected, correct, works, len(files)


def _negatives(schema: ontology.Schema, db: str) -> tuple[int, int]:
    """(legal false positives, files) over every raw file of ``db``."""
    false_pos = 0
    with db_context.using_db(db):
        names = dedup.list_sources()
        for name in names:
            text = (db_context.raw_dir() / name).read_text(encoding="utf-8", errors="replace")
            got = ontology_detect.detect(text, schema)
            if got.class_id and ontology_detect.is_a(schema, got.class_id, "legal-instrument"):
                false_pos += 1
                print(f"  FP  {name[:50]:50} -> {got.class_id} ({got.evidence[:60]!r})")
    return false_pos, len(names)


def main() -> None:
    parser = argparse.ArgumentParser(description="Ontology detection benchmark")
    parser.add_argument("--no-negatives", action="store_true", help="skip the negatives DB")
    parser.add_argument("--gold", default=str(FIXTURE), help="gold labels (JSON)")
    args = parser.parse_args()
    gold = json.loads(Path(args.gold).read_text(encoding="utf-8"))
    schema = _schema(gold.get("modules", ["core", "legal-de"]))
    print(f"Positives ({gold.get('db') or 'bench/ontology_detect/'}):")
    detected, correct, works, total = _positives(schema, gold["files"], gold.get("db"))
    precision = correct / detected if detected else 0.0
    print(f"class precision {precision:.0%} ({correct}/{detected}) · coverage {detected}/{total}")
    print(f"work id accuracy {works}/{total}")
    if not args.no_negatives and gold.get("negatives_db"):
        db = gold["negatives_db"]
        print(f"Negatives ({db}, no legal class expected):")
        false_pos, n = _negatives(schema, db)
        print(f"legal false positives {false_pos}/{n}")


if __name__ == "__main__":
    main()
