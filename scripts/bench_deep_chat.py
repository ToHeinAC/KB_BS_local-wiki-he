"""Live Deep chat bench (ideas/deep-chat-read-memory-and-section-grounding.md §6, §9.4).

Runs `chat_agent.run_chat_agent` with the real QUERY_MODEL on each question of a gold file
and reports, per run: tool calls, repeat reads served as empty stubs (target ≤ 1), auto-
advances, exit path (ledger-accepted / submit-accepted / prose-gated-accepted / best-effort),
the run's gate events, cited sections never read (target 0), gold sections read, quote
overlap (share of the answer's sentences citing a gold § that share a ≥ 6-word n-gram with
its text; no LLM judge), chain hops and bonus turns, and wall time.

Gold sections are hand-labelled with the heading each one must carry; the bench checks it
against the ingested text and flags a mismatch instead of scoring against a wrong label.
The statutes named by the gold file must be ingested into the database first (public law
from gesetze-im-internet.de); the bench never writes `data/`.

Usage:
    uv run python scripts/bench_deep_chat.py                       # all questions, DB KI
    uv run python scripts/bench_deep_chat.py --only q1 --out run.json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import chat_agent
import chunker
import db_context
import evidence
import run_memory
import tools

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "bench" / "fixture_deep_chat_KI.json"
NGRAM = 6


def exit_path(steps: list[dict[str, Any]]) -> str:
    """How the answer left the agent loop. An answer written from the evidence ledger passed
    the gate and replaces any submission, so it wins."""
    if any(s["type"] == "final_answer" and s.get("note") == chat_agent.LEDGER_NOTE for s in steps):
        return "ledger-accepted"
    for s in steps:
        submit = s["type"] == "tool_result" and s.get("name") == "submit_chat_answer"
        if submit and str(s.get("result", "")).startswith("ACCEPTED"):
            return "submit-accepted"
    if any(s["type"] == "gate" and s.get("content") == "accepted" for s in steps):
        return "prose-gated-accepted"
    return "best-effort"


def ledger_record(mem: run_memory.RunMemory) -> dict[str, Any]:
    """The run's evidence ledger and every answer written from it (shown or not), cleaned
    and as the model wrote it."""
    return {
        "ledger": evidence.render(mem.ledger),
        "ledger_answers": list(mem.ledger_drafts),
        "ledger_raw": list(mem.ledger_raw),
    }


def closing(steps: list[dict[str, Any]]) -> str:
    """Which path wrote the final answer (ledger, submitted, prose, draft, notes-fallback)."""
    final = next((s for s in reversed(steps) if s["type"] == "final_answer"), {})
    return str(final.get("closing", "none"))


def gate_events(steps: list[dict[str, Any]]) -> list[str]:
    """The run's gate events in order: stop rule, prose-gate verdicts."""
    return [str(s.get("content", "")) for s in steps if s["type"] == "gate"]


def memory_counts(steps: list[dict[str, Any]]) -> dict[str, int]:
    """Tool calls, auto-advanced reads and reads that ended in an empty stub."""
    results = [str(s.get("result", "")) for s in steps if s["type"] == "tool_result"]
    return {
        "tool_calls": sum(1 for s in steps if s["type"] == "tool_call"),
        "advances": sum(r.count("[memory: ") for r in results),
        "empty_stubs": sum(r.count("fully explored for this question") for r in results),
    }


def cited_by_level(
    levels: dict[tuple[str, str], int], cited: list[tuple[str, str]]
) -> dict[str, int]:
    """How many of the answer's cited sources (by `tools.ref_key`) each level read in code
    supplied (ideas/deep-chat-levels.md); "other" for sources the model found itself."""
    out = {"1": 0, "2": 0, "3": 0, "other": 0}
    for key in dict.fromkeys(cited):
        level = levels.get(key)
        out[str(level) if level else "other"] += 1
    return out


def _grams(text: str) -> set[tuple[str, ...]]:
    words = re.findall(r"\w+", text.casefold())
    return {tuple(words[i : i + NGRAM]) for i in range(len(words) - NGRAM + 1)}


def quote_overlap(answer: str, anchor: str, section_text: str) -> float | None:
    """Share of the answer's sentences naming `anchor` that quote the section's text
    (a shared ≥ NGRAM-word n-gram); None when no sentence names it."""
    num = anchor.split()[-1]
    naming = re.compile(rf"§\s*{re.escape(num)}\b")
    sentences = [s for s in re.split(r"(?<=[.!?])\s+", answer) if naming.search(s)]
    if not sentences:
        return None
    source = _grams(section_text)
    return sum(1 for s in sentences if _grams(s) & source) / len(sentences)


def _gold_chunk(file: str, section: str, heading: str) -> tuple[dict[str, Any] | None, str]:
    """The gold section's chunk, and why it cannot be scored ("" when it can)."""
    ch = tools._legal_chunk(file, section)  # pyright: ignore[reportPrivateUsage]
    if ch is None:
        return None, f"{file} {section} not found — ingest the statute first"
    title = " ".join(ch.get("heading_path") or [])
    if heading.casefold() not in title.casefold():
        return None, f"gold label wrong: {file} {section} is '{title}', not '{heading}'"
    return ch, ""


def _score_gold(
    mem: run_memory.RunMemory, answer: str, gold: list[dict[str, str]]
) -> dict[str, Any]:
    read, overlaps, problems = 0, [], []
    for g in gold:
        ch, why = _gold_chunk(g["file"], g["section"], g["heading"])
        if ch is None:
            problems.append(why)
            continue
        read += tools._section_read(mem, g["file"], ch)  # pyright: ignore[reportPrivateUsage]
        overlap = quote_overlap(answer, g["section"], ch["text"])
        overlaps.append(overlap)
    return {
        "gold_read": f"{read}/{len(gold)}",
        "quote_overlap": overlaps,
        "problems": problems,
    }


def _run(item: dict[str, Any]) -> dict[str, Any]:
    started = time.monotonic()
    steps = list(chat_agent.run_chat_agent(item["question"]))
    final = next((s for s in reversed(steps) if s["type"] == "final_answer"), {})
    answer = str(final.get("content", ""))
    mem = run_memory.current()
    assert mem is not None
    cited = set(tools._RAW_CITE_RE.findall(answer))  # pyright: ignore[reportPrivateUsage]
    return {
        "id": item["id"],
        **memory_counts(steps),
        "exit": exit_path(steps),
        "closing": closing(steps),
        "gates": gate_events(steps),
        **ledger_record(mem),
        "cited_unread": [f"{f} {a}" for f, a in tools._tagged_unread(mem, cited)],  # pyright: ignore[reportPrivateUsage]
        **_score_gold(mem, answer, item["gold"]),
        "core": mem.core_refs,
        "terms": mem.term_refs,
        "cited_by_level": cited_by_level(mem.levels, [tools.ref_key(r) for r in cited]),
        "words": len(answer.split()),
        "hops": max(mem.ref_depth.values(), default=0),
        "bonus": mem.bonus,
        "seconds": round(time.monotonic() - started, 1),
    }


def _print(row: dict[str, Any]) -> None:
    print(
        f"{row['id']:<4} {row['exit']:<21} closing={row['closing']:<14} "
        f"calls={row['tool_calls']:<3} "
        f"adv={row['advances']:<2} stubs={row['empty_stubs']:<2} "
        f"unread={len(row['cited_unread']):<2} gold={row['gold_read']:<5} "
        f"overlap={row['quote_overlap']} hops={row['hops']} bonus={row['bonus']} "
        f"levels={row['cited_by_level']} words={row['words']} {row['seconds']}s"
    )
    for g in row.get("gates", []):
        print(f"     · {g}")
    for p in row["problems"]:
        print(f"     ! {p}")


def main() -> None:
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n", 1)[0])
    ap.add_argument("--gold", type=Path, default=FIXTURE)
    ap.add_argument("--only", action="append", help="question id (repeatable)")
    ap.add_argument("--out", type=Path, help="write the rows as JSON")
    args = ap.parse_args()
    fixture = json.loads(args.gold.read_text(encoding="utf-8"))
    db_context.set_active_db(fixture["db"])
    db_context.set_search_scope([fixture["db"]])
    missing = [f for f in fixture["files"] if not chunker.load_chunks(f)]
    if missing:
        raise SystemExit(f"not ingested into {fixture['db']}: {', '.join(missing)}")
    rows = []
    for item in fixture["questions"]:
        if args.only and item["id"] not in args.only:
            continue
        rows.append(_run(item))
        _print(rows[-1])
    if args.out:
        args.out.write_text(json.dumps(rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
