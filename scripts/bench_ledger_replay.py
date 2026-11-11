"""Replay of the Deep chat ledger answer on recorded ledgers (research_notes/retrieval_deepchat/
02_insights_and_improvements.md §6.9).

`bench_study_deep.py` keeps each run's final evidence ledger in the gitignored `bench/local/`.
This script writes the ledger answer again from those ledgers, once per variant, so only the
answer step changes: no search, no agent turn, none of the navigation's noise. Variants:

- R0: the ledger as recorded, rendered as `chat_agent` renders it, with the levels of code's
  pre-flight for the question.
- V1: each section's quotes together; a section a quote refers to ("nach Anlage 8") right
  after that quote's section, at its level.
- V13: V1 without the quotes off the question: not of level 1 or a section the gate requires,
  and fewer than two question stems (a figure counting as one).
- V14, V134: the answers of V1 and V13 plus, added by code, the ledger quotes the answer
  never cites that carry a figure or an exception or belong to a section a cited quote refers
  to. No extra model call.
- G: only the gold sections' quotes, levels as R0 (diagnostic: the ledger without noise).

Rows quote the database, so they go to `bench/local/`:

    DATA_ROOT=<scratch> uv run python scripts/bench_ledger_replay.py \
        --rows bench/local/study_deep_E0_all3.jsonl --reps 2 --out bench/local/replay_all3.jsonl
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import bench_study

import chat_agent
import db_context
import evidence
import lang
import run_memory
import tools

Quote = tuple[str, str]
VARIANTS = ("R0", "V1", "V13", "G")  # written by the model; V14 and V134 derive from V1, V13
OMIT_MAX = 8  # quotes code adds to one answer
OMITTED_HEADING = {
    "de": "## Weitere Belege aus den Quellen",
    "en": "## Further evidence from the sources",
}
_CITE_RE = re.compile(r"\[Source:\s*([^\]\n]+?)\s*\]")
_LABEL_RE = re.compile(r"(§|Anlage)\s*(\d+[a-z]?)(?:\s+Abs\.\s*(\d+[a-z]?))?")
_FIGURE_RE = re.compile(
    r"\b\d+(?:[.,]\d+)?\s*(?:%|Prozent|Monat|Jahr|Woche|Tag|Stunde|Bq|Becquerel|mSv|Millisievert"
    r"|Sv\b|Gy\b|kg\b|Kilogramm|Meter|month|year|week|day|hour)"
    r"|\b(?:ein|zwei|drei|vier|fünf|sechs|sieben|acht|neun|zehn|zwölf|achtzehn|dreißig)\s+"
    r"(?:Monat|Jahr|Woche|Tag|Stunde)",
    re.I,
)
_EXCEPTION_RE = re.compile(
    r"\b(?:abweichend|ausgenommen|es sei denn|gilt nicht|unbeschadet|except|unless|does not apply)",
    re.I,
)


def _label_re(ref: str) -> re.Pattern[str] | None:
    """How a quote names the section `ref` ("A.md § 5 Abs. 2" → "§ 5 Absatz 2")."""
    m = _LABEL_RE.fullmatch(ref.split(" ", 1)[1]) if " " in ref else None
    if m is None:
        return None
    head = r"§\s*" if m[1] == "§" else r"Anlage\s+"
    tail = rf"\s+(?:Abs\.|Absatz)\s*{re.escape(m[3])}\b" if m[3] else ""
    return re.compile(head + re.escape(m[2]) + r"\b" + tail)


def _refers(text: str, by: str, ref: str) -> bool:
    """Whether `text`, quoted from section `by`, refers to section `ref` of the same file."""
    pattern = _label_re(ref)
    same_file = by.split(" ", 1)[0] == ref.split(" ", 1)[0]
    return by != ref and same_file and pattern is not None and pattern.search(text) is not None


def grouped(ledger: Sequence[Quote], levels: Sequence[int]) -> tuple[list[Quote], list[int]]:
    """`ledger` with each section's quotes together, sections by level then first quote, and
    a section a quote refers to right after that quote's section, at its level."""
    order = list(dict.fromkeys(ref for ref, _ in ledger))
    level = {
        ref: min((lv for (r, _), lv in zip(ledger, levels, strict=True) if r == ref))
        for ref in order
    }
    text = {ref: " ".join(s for r, s in ledger if r == ref) for ref in order}
    placed: list[str] = []

    def place(ref: str, at: int) -> None:
        placed.append(ref)
        level[ref] = at if not level[ref] or level[ref] > at else level[ref]
        for child in order:
            if child not in placed and _refers(text[ref], ref, child):
                place(child, level[ref])

    for ref in sorted(order, key=lambda r: (level[r] or len(order) + 9, order.index(r))):
        if ref not in placed:
            place(ref, level[ref])
    out = [(r, s) for ref in placed for r, s in ledger if r == ref]
    return out, [level[r] for r, _ in out]


def pruned(
    ledger: Sequence[Quote], levels: Sequence[int], question: str, required: set[str]
) -> tuple[list[Quote], list[int]]:
    """`ledger` without the quotes off the question: not of level 1 or a `required` section,
    and sharing fewer than two of the question's stems (a figure in a sharing quote counts
    as one)."""
    stems = evidence.stems(question)
    kept = [
        (q, lv)
        for q, lv in zip(ledger, levels, strict=True)
        if lv == 1 or q[0] in required or evidence._score(q[1], stems) >= 2  # pyright: ignore[reportPrivateUsage]
    ]
    return [q for q, _ in kept], [lv for _, lv in kept]


def omitted(answer: str, ledger: Sequence[Quote]) -> list[Quote]:
    """The quotes of the sections `answer` never cites (outside its open points) that carry
    a figure or an exception, or that belong to a section a cited quote refers to."""
    m = tools._OPEN_POINTS_RE.search(answer)  # pyright: ignore[reportPrivateUsage]
    cited = set(_CITE_RE.findall(answer[: m.start()] if m else answer))
    by_cited = [(r, s) for r, s in ledger if r in cited]

    def wanted(ref: str, s: str) -> bool:
        if _FIGURE_RE.search(s) or _EXCEPTION_RE.search(s):
            return True
        return any(_refers(t, by, ref) for by, t in by_cited)

    return [(r, s) for r, s in ledger if r not in cited and wanted(r, s)][:OMIT_MAX]


def with_omitted(answer: str, quotes: Sequence[Quote], language: str) -> str:
    """`answer` with `quotes` verbatim under their own heading, before the open points."""
    if not quotes:
        return answer
    heading = OMITTED_HEADING.get(language, OMITTED_HEADING["en"])
    block = "\n".join([heading, *(f'- "{s}" [Source: {r}]' for r, s in quotes)])
    m = tools._OPEN_POINTS_RE.search(answer)  # pyright: ignore[reportPrivateUsage]
    if m is None:
        return f"{answer}\n\n{block}"
    return f"{answer[: m.start()]}{block}\n\n{answer[m.start() :]}"


def gold_only(ledger: Sequence[Quote], gold: Sequence[dict[str, str]]) -> list[Quote]:
    """The quotes of the gold sections."""
    refs = {f"{g['file']} {g['section']}" for g in gold}
    return [(r, s) for r, s in ledger if r in refs]


# --- I/O: pre-flight levels, the writer, the rows --------------------------------------


def preflight(question: str) -> dict[str, Any]:
    """Code's pre-flight for `question`: its levels, required sections and reads."""
    mem = run_memory.begin_run(question)
    chat_agent._preflight(question)  # pyright: ignore[reportPrivateUsage]
    return {
        "levels": dict(mem.levels),
        "core": list(mem.core_refs),
        "terms": list(mem.term_refs),
        "reads": dict(mem.reads),
        "searches": dict(mem.searches),
    }


def _read_key(ref: str) -> str:
    """The run-memory key of a section read of `ref` (every ledger quote was read)."""
    _db, base, section = tools._split_ref(ref)  # pyright: ignore[reportPrivateUsage]
    return f"raw:{base}|sec={tools._norm_anchor(section)}:0"  # pyright: ignore[reportPrivateUsage]


def write(
    question: str, ledger: Sequence[Quote], levels: Sequence[int], pre: dict[str, Any]
) -> dict[str, Any]:
    """The ledger answer for `ledger` at `levels`, written as `chat_agent` writes it."""
    mem = run_memory.begin_run(question)
    mem.core_refs, mem.term_refs = list(pre["core"]), list(pre["terms"])
    mem.reads = {**pre["reads"], **{_read_key(r): 1 for r, _ in ledger}}
    mem.searches = dict(pre["searches"])  # the gate counts the run's searches
    mem.ledger = list(ledger)
    mem.levels = {tools.ref_key(r): lv for (r, _), lv in zip(ledger, levels, strict=True) if lv}
    started = time.monotonic()
    accepted = chat_agent._write_ledger_answer(mem, question, lang.response_directive(question))  # pyright: ignore[reportPrivateUsage]
    return {
        "answer": mem.ledger_drafts[-1] if mem.ledger_drafts else "",
        "accepted": accepted is not None,
        "seconds": round(time.monotonic() - started, 1),
        "gate": mem.gate_events[-1] if mem.gate_events else "",
    }


def inputs(item: dict[str, Any], ledger: list[Quote], pre: dict[str, Any]) -> dict[str, Any]:
    """Each written variant's ledger and levels."""
    base = [pre["levels"].get(tools.ref_key(r), 0) for r, _ in ledger]
    g_ledger, g_levels = grouped(ledger, base)
    gold = gold_only(ledger, item["gold"])
    return {
        "R0": (ledger, base),
        "V1": (g_ledger, g_levels),
        "V13": pruned(g_ledger, g_levels, item["question"], {*pre["core"], *pre["terms"]}),
        "G": (gold, [pre["levels"].get(tools.ref_key(r), 0) for r, _ in gold]),
    }


def _row(
    item: dict[str, Any], variant: str, ledger: Sequence[Quote], out: dict[str, Any]
) -> dict[str, Any]:
    facts = bench_study.fact_hits(out["answer"], item["facts"])
    in_ledger = bench_study.fact_hits(" ".join(s for _, s in ledger), item["facts"])
    return {
        "id": item["id"],
        "variant": variant,
        "quotes": len(ledger),
        "facts": facts,
        "facts_found": sum(facts),
        "facts_in_ledger": sum(in_ledger),
        "accepted": out["accepted"],
        "seconds": out["seconds"],
        "words": len(out["answer"].split()),
        "added": out.get("added", 0),
        "gate": out["gate"][:300],
        "answer": out["answer"],
    }


def replay(item: dict[str, Any], ledger: list[Quote], pre: dict[str, Any]) -> list[dict[str, Any]]:
    """One recorded ledger under every variant."""
    rows: list[dict[str, Any]] = []
    language = lang.detect(item["question"])
    for variant, (led, lv) in inputs(item, ledger, pre).items():
        out = write(item["question"], led, lv, pre)
        rows.append(_row(item, variant, led, out))
        if variant in ("V1", "V13"):
            extra = omitted(out["answer"], led)
            plus = {
                **out,
                "answer": with_omitted(out["answer"], extra, language),
                "added": len(extra),
            }
            rows.append(_row(item, {"V1": "V14", "V13": "V134"}[variant], led, plus))
    return rows


def summary(rows: Sequence[dict[str, Any]]) -> list[str]:
    """Facts answered, facts in the ledger given, gate passes and time per variant."""
    lines = ["variant  runs  facts  in-ledger  accepted  s/answer  quotes"]
    for v in ("R0", "V1", "V14", "V13", "V134", "G"):
        rs = [r for r in rows if r["variant"] == v]
        if rs:
            lines.append(
                f"{v:<8} {len(rs):>4}  {sum(r['facts_found'] for r in rs):>5}  "
                f"{sum(r['facts_in_ledger'] for r in rs):>9}  {sum(r['accepted'] for r in rs):>8}  "
                f"{sum(r['seconds'] for r in rs) / len(rs):>8.1f}  "
                f"{sum(r['quotes'] for r in rs) / len(rs):>6.1f}"
            )
    return lines


def main() -> None:
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n", 1)[0])
    ap.add_argument("--rows", type=Path, action="append", required=True)
    ap.add_argument("--gold", type=Path, default=bench_study.FIXTURE)
    ap.add_argument("--reps", type=int, default=1)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    fixture = json.loads(args.gold.read_text(encoding="utf-8"))
    db_context.set_active_db(fixture["db"])
    db_context.set_search_scope([fixture["db"]])
    items = {q["id"]: q for q in fixture["questions"]}
    recorded = [
        (path.stem, json.loads(line))
        for path in args.rows
        for line in path.read_text(encoding="utf-8").splitlines()
        if line
    ]
    pre = {
        qid: preflight(items[qid]["question"])
        for qid in dict.fromkeys(r["id"] for _, r in recorded)
    }
    done = (
        [json.loads(x) for x in args.out.read_text(encoding="utf-8").splitlines()]
        if args.out.exists()
        else []
    )
    seen = {(r["source"], r["src_rep"], r["id"], r["rep"]) for r in done}
    for rep in range(args.reps):
        for source, rec in recorded:
            if (source, rec["rep"], rec["id"], rep) in seen:
                continue
            ledger = [(str(r), str(s)) for r, s in rec["ledger"]]
            for row in replay(items[rec["id"]], ledger, pre[rec["id"]]):
                row = {"source": source, "src_rep": rec["rep"], "rep": rep, **row}
                print({k: v for k, v in row.items() if k != "answer"}, flush=True)
                with args.out.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(row, ensure_ascii=False) + "\n")
                done.append(row)
    print("\n".join(summary(done)))


if __name__ == "__main__":
    main()
