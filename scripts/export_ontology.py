"""Export a database's ontology: the schema as SKOS Turtle, the facts as JSON-LD.

Writes `<out>/ontology-<DB>.ttl` and `<out>/ontology-<DB>.jsonld` (the same files as the
download buttons in Maintenance → Ontology → Overview). Reads only; see
docs/ontology.md §Evolution.

Usage:
    uv run python scripts/export_ontology.py --db KI --out exports/
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import db_context
import ontology_export
import ontology_store


def main() -> None:
    parser = argparse.ArgumentParser(description="Export a database's ontology")
    parser.add_argument("--db", required=True, help="database name under data/")
    parser.add_argument("--out", required=True, help="output directory")
    args = parser.parse_args()
    db_context.set_active_db(args.db)
    schema, errors = ontology_store.load()
    view = ontology_store.view()
    if schema is None or view is None:
        raise SystemExit("no valid ontology: " + ("; ".join(errors) or "none configured"))
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    ttl, jsonld = out / f"ontology-{args.db}.ttl", out / f"ontology-{args.db}.jsonld"
    ttl.write_text(ontology_export.skos_turtle(schema), encoding="utf-8")
    doc = ontology_export.facts_jsonld(view, db=args.db)
    jsonld.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {ttl} and {jsonld}")


if __name__ == "__main__":
    main()
