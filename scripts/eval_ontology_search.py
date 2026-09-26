"""Ontology-stage relevance evaluation (plan §4.6, requirement R14).

Builds a throwaway database *outside* data/ from public German law texts
(gesetze-im-internet.de, verwaltungsvorschriften-im-internet.de): downloads them,
converts each § into a "## § n Title" section, chunks and indexes them (no LLM), types
them with the Phase 3 detection (rule facts, shared `core` + `legal-de`), then runs the
hand-labelled questions in bench/fixture_ontology_search.json with the ontology stage off
and on. Lexical + ontology arms only (no embeddings, no reranker).

Groups: (a) the question names a document by abbreviation, (b) by a class word,
(c) it asks about a point in time, (d) controls that name nothing — their rankings may
change only by superseded versions moving down.

For (c) the database also holds `strlschv_2019.md`: a synthetic older version of the
StrlSchV (the current text with a marker per section, version date 2019-12-01; the
public site only serves the current version). It measures the validity order, not
content differences.

Usage:
    uv run python scripts/eval_ontology_search.py --root /tmp/ontology-eval
"""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import sys
import urllib.request
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import chunker
import db_context
import dedup
import lex_index
import metadata_extract
import ontology
import ontology_detect
import ontology_store
import ontology_time
import retrieval

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "bench" / "fixture_ontology_search.json"
DB = "OntologyEval"
LAWS = {
    "strlschg.md": "https://www.gesetze-im-internet.de/strlschg/BJNR196610017.html",
    "strlschv.md": "https://www.gesetze-im-internet.de/strlschv_2018/BJNR203600018.html",
    "atg.md": "https://www.gesetze-im-internet.de/atg/BJNR008140959.html",
    "gg.md": "https://www.gesetze-im-internet.de/gg/BJNR000010949.html",
    "bimschg.md": "https://www.gesetze-im-internet.de/bimschg/BJNR007210974.html",
}
TA_LUFT = (
    "ta_luft.md",
    "https://www.verwaltungsvorschriften-im-internet.de/bsvwvbund_18082021_IGI25025005.htm",
)
TOP_K = 10
OLD_STAND = ("strlschv_2019.md", "2019-12-01")
CURRENT_STAND = ("strlschv.md", "2024-10-23")


def _fetch(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    raw = urllib.request.urlopen(req, timeout=120).read()
    return (
        raw.decode("utf-8") if b'charset="utf-8"' in raw[:3000].lower() else raw.decode("latin-1")
    )


def _text(fragment: str) -> str:
    fragment = re.sub(r"(?s)<(script|style)\b.*?</\1>", "", fragment)
    fragment = re.sub(r"<br\s*/?>|</(p|div|h\d|tr|li|td|dd|dt)>", "\n", fragment, flags=re.I)
    text = html.unescape(re.sub(r"<[^>]+>", "", fragment)).replace("\xa0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    return re.sub(r"\n\s*\n+", "\n\n", text).strip()


def _law_markdown(page: str) -> str:
    """Header (title, Ausfertigungsdatum, …) + one "## § n Title" section per norm."""
    norms = re.split(r'<div class="jnnorm"[^>]*>', page)[1:]  # [0] is the site menu
    parts = [_text(norms[0]).replace("Nichtamtliches Inhaltsverzeichnis", "")]  # title block
    for norm in norms[1:]:
        m = re.search(r'jnenbez">(.*?)</span>.*?jnentitel">(.*?)</span>', norm, re.S)
        title = html.unescape(f"{m[1]} {m[2]}" if m else "").strip()
        if title.startswith("Inhalts"):
            continue
        body = _text(norm.split("</h3>", 1)[-1])
        parts.append(f"## {title}\n{body}")
    return "\n\n".join(parts)


def _register(name: str, text: str) -> None:
    dedup.register_file(text.encode("utf-8"), name)
    chunker.write_chunks(name, chunker.split(text))
    schema, _ = ontology_store.load()
    assert schema is not None
    found = ontology_detect.detect(text, schema)
    date = metadata_extract.extract_effective_date(text) or ""
    detected = ontology_detect.detected_dict(found, date)
    review = {"class": detected["class"], "work": detected["work"], "version_date": date}
    rows, _ = ontology_detect.upload_rows(name, review, detected, schema, user="eval")
    ontology_store.append_rows(rows)
    print(f"  {name:14} class={found.class_id!s:18} work={found.work}")


def build() -> None:
    db_context.create_db(DB)
    ontology_store.binding_path().write_text("modules: [core, legal-de]\n")
    print("Building the evaluation database:")
    for name, url in LAWS.items():
        _register(name, _law_markdown(_fetch(url)))
    name, url = TA_LUFT
    page = _text(_fetch(url))
    _register(name, page[page.find("Allgemeinen Verwaltungsvorschrift") :])
    _add_old_stand()
    print(f"  indexed {lex_index.build()['chunks']} chunks")


def _add_old_stand() -> None:
    """A synthetic older version of the StrlSchV for group (c) (see module docstring)."""
    current = (db_context.raw_dir() / CURRENT_STAND[0]).read_text(encoding="utf-8")
    old = re.sub(r"(## [^\n]+\n)", r"\1[Fassung vom 01.12.2019] ", current)
    _register(OLD_STAND[0], old)
    ontology_store.append_rows(
        [
            ontology.assertion(f"src:{name}", "version_date", when, by="user", user="eval")
            for name, when in (OLD_STAND, CURRENT_STAND)
        ]
    )


def _rank(hits: list[dict[str, Any]], expected: set[str]) -> int | None:
    return next((i for i, h in enumerate(hits) if h["source"] in expected), None)


def _current(hits: list[dict[str, Any]]) -> list[str]:
    """Chunk ids of hits that are not superseded today (controls may only demote those)."""
    view = ontology_store.view()
    assert view is not None
    today = ontology_time.date.today()
    return [
        h["chunk_id"]
        for h in hits
        if ontology_time.validity(view, h["source"], today) != ontology_time.SUPERSEDED
    ]


def evaluate() -> dict[str, dict[str, float]]:
    questions = json.loads(FIXTURE.read_text(encoding="utf-8"))["questions"]
    stats: dict[str, dict[str, float]] = {}
    for q in questions:
        runs = {
            mode: retrieval.search(q["question"], TOP_K, "raw", use_ontology=mode == "on")
            for mode in ("off", "on")
        }
        for mode, hits in runs.items():
            s = stats.setdefault(f"{q['group']}/{mode}", {"n": 0, "hit1": 0, "hit5": 0, "mrr": 0})
            rank = _rank(hits, set(q["expected"]))
            s["n"] += 1
            s["hit1"] += rank == 0
            s["hit5"] += rank is not None and rank < 5
            s["mrr"] += 0 if rank is None else 1 / (rank + 1)
        if q["group"] == "d" and _current(runs["on"]) != _current(runs["off"]):
            print(f"  CONTROL CHANGED beyond superseded versions: {q['question']}")
        off, on = (_rank(runs[m], set(q["expected"])) for m in ("off", "on"))
        print(f"  ({q['group']}) off={off!s:4} on={on!s:4} {q['question']}")
    return stats


def main() -> None:
    parser = argparse.ArgumentParser(description="Ontology-stage relevance evaluation")
    parser.add_argument("--root", required=True, help="scratch data root (never data/)")
    args = parser.parse_args()
    root = Path(args.root).resolve()
    if root == (ROOT / "data").resolve():
        raise SystemExit("refusing to write into data/: pass a scratch directory")
    os.environ["RERANK_ENABLED"] = "0"
    db_context.DATA_ROOT = root
    db_context.set_active_db(DB)
    if not ontology_store.exists():
        build()
    print("Questions (rank of the first expected source; None = not in top 10):")
    for key, s in sorted(evaluate().items()):
        n = s["n"]
        print(
            f"{key:6} hit@1 {s['hit1'] / n:.0%}  hit@5 {s['hit5'] / n:.0%}  MRR {s['mrr'] / n:.2f}"
        )


if __name__ == "__main__":
    main()
