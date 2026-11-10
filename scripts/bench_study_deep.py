"""Deep chat arms of the study in research_notes/retrieval_deepchat/00_framework.md (FF2, FF3).

Runs `chat_agent.run_chat_agent` on the gold file's `deep` questions under each arm and logs
one JSON row per run: mandatory facts found, gold sections read, wall time, time to the first
usable answer, and the token counts of every LLM call. Arms only switch module attributes
for the run, `src/` stays as it is. `prompt_eval_count` is the whole prompt even on a cache
hit, so it gives the fill level, and `prompt_eval_duration` tells the cache hit (measured,
framework §1). A run appends to `--out` and a restart skips what is there.

Every row also says where its text went and where its facts were lost: generated tokens per
calling function of `src/`, the characters of thoughts, `think_tool` notes and submitted
drafts, the evidence ledger, and each fact found in the reads and in the ledger. Rows carry
the full answer, which quotes the database, so write them to the gitignored `bench/local/`
and commit a copy without `answer` and `ledger`. Arm O is the oracle: every sentence of the
gold sections as the ledger, then the ledger answer, no search and no agent.

The window is read at import, so an arm with another one gets it from the environment:

    DATA_ROOT=<scratch> uv run python scripts/bench_study_deep.py --arm E0 --arm E1 --arm D1 \
        --arm D2 --arm D3 --arm D4 --reps 3 --out runs.jsonl
    DATA_ROOT=<scratch> INGEST_NUM_CTX=65536 uv run python scripts/bench_study_deep.py --arm E3 \
        --reps 3 --out runs.jsonl
"""

from __future__ import annotations

import argparse
import contextlib
import json
import sys
import time
from collections import Counter
from collections.abc import Callable, Iterable, Iterator, Sequence
from pathlib import Path
from types import FrameType
from typing import Any

import ollama

sys.path.insert(0, str(Path(__file__).resolve().parent))
import bench_deep_chat
import bench_study

import chat_agent
import chunker
import db_context
import evidence
import lang
import ollama_client
import run_memory
import tools

RESERVE = 8192  # chat_agent._ANSWER_RESERVE_TOKENS
CODE_RATIO = 3  # chat_agent._CHARS_PER_TOKEN
AT_WINDOW = 0.99
CACHE_FACTOR = 3  # a prompt counts as cached when it prefills this much faster than the coldest
SRC = Path(__file__).resolve().parent.parent / "src"
LOCAL_ONLY = ("answer", "ledger")  # quote the database: kept in bench/local/, never committed
DRAFT_TOOLS = {"think_tool": "think_chars", "submit_chat_answer": "submit_chars"}

_NO_DEPTH = {"TERMS_MAX": 0, "CITING_MAX": 0, "DEEP_TERMS_MAX": 0}


def _no_footer(*_args: Any) -> str:
    return ""


def _no_levels(*_args: Any) -> list[Any]:
    return []


# Arm → attributes of `tools` set for the run (framework §2). E1–E4 add the token budget, and
# E2–E4 need their window from the environment. D4 and O skip the agent loop.
ARMS: dict[str, dict[str, Any]] = {
    "E0": {},
    "E1": {},
    "E2": {},
    "E3": {},
    "E4": {},
    "D1": {"_ref_footer": _no_footer},
    "D2": _NO_DEPTH,
    "D3": {"_ref_footer": _no_footer, "level_reads": _no_levels},
    "D4": {"_ref_footer": _no_footer},
    "O": {},
}
TOKEN_BUDGET_ARMS = {"E1", "E2", "E3", "E4"}
WINDOWS = {"E2": 16384, "E3": 65536, "E4": 131072}


def token_budget(num_ctx: int, chars: int, tokens: int) -> int:
    """The history budget in characters from the run's measured ratio (the code's estimate
    until a history and the prompt that carried it have both been measured)."""
    ratio = chars / tokens if chars and tokens else CODE_RATIO
    return int((num_ctx - RESERVE) * ratio)


def telemetry(calls: Sequence[dict[str, Any]], num_ctx: int) -> dict[str, Any]:
    """A run's LLM calls in one row: fill level, cache hits, truncation signs."""
    if not calls:
        return {"llm_calls": 0, "fill_max": 0, "fill_mean": 0}
    prompts = [c["prompt_tokens"] for c in calls]
    by_caller: Counter[str] = Counter()
    for c in calls:
        by_caller[c.get("caller", "?")] += c["answer_tokens"]
    rates = [c["prompt_tokens"] / c["prefill_s"] for c in calls if c["prefill_s"] > 0]
    coldest = min(rates, default=0)
    return {
        "llm_calls": len(calls),
        "fill_max": round(max(prompts) / num_ctx, 3),
        "fill_mean": round(sum(prompts) / len(prompts) / num_ctx, 3),
        "prompt_tokens_max": max(prompts),
        "answer_tokens": sum(c["answer_tokens"] for c in calls),
        "prefill_s": round(sum(c["prefill_s"] for c in calls), 1),
        "answer_s": round(sum(c["answer_s"] for c in calls), 1),
        "cached_calls": sum(1 for r in rates if r >= CACHE_FACTOR * coldest),
        "at_window": sum(1 for p in prompts if p >= AT_WINDOW * num_ctx),
        "cut_answers": sum(1 for c in calls if c["done_reason"] == "length"),
        "tokens_by_caller": dict(by_caller),
    }


def caller(frame: FrameType | None, root: Path) -> str:
    """`module.function` of the innermost frame whose file lies under ``root`` ("?" if none):
    the code in `src/` that made an LLM call, however deep in LangChain it was sent. The
    Ollama adapter only forwards a call, so its frames are skipped."""
    while frame is not None:
        path = Path(frame.f_code.co_filename).resolve()
        if root.resolve() in path.parents and path.stem != "ollama_client":
            return f"{path.stem}.{frame.f_code.co_name}"
        frame = frame.f_back
    return "?"


def text_by_kind(steps: Iterable[dict[str, Any]]) -> dict[str, int]:
    """Characters of the run's intermediate text: the agent's thoughts, its `think_tool`
    notes and the drafts it submitted."""
    out = {"thought_chars": 0, **dict.fromkeys(DRAFT_TOOLS.values(), 0)}
    for s in steps:
        if s["type"] == "thought":
            out["thought_chars"] += len(str(s.get("content", "")))
        elif s["type"] == "tool_call" and s.get("name") in DRAFT_TOOLS:
            args = s.get("args") or {}
            out[DRAFT_TOOLS[s["name"]]] += sum(len(str(v)) for v in args.values())
    return out


def fact_trace(
    facts: Sequence[str], reads: Sequence[str], ledger: Sequence[tuple[str, str]]
) -> dict[str, list[bool]]:
    """Each fact in the text the run read and in the ledger its answer could quote."""
    return {
        "facts_in_reads": bench_study.fact_hits("\n".join(reads), facts),
        "facts_in_ledger": bench_study.fact_hits(" ".join(s for _, s in ledger), facts),
    }


def oracle_ledger(
    gold: Sequence[dict[str, str]], load: Callable[[str], list[dict[str, Any]]]
) -> list[tuple[str, str]]:
    """Every sentence of the gold sections (a gold `part` only that part), cited as the
    ledger cites them: file and section, without the part marker."""
    out: list[tuple[str, str]] = []
    for g in gold:
        for ch in load(g["file"]):
            anchor = str(ch["anchor"])
            if (
                anchor != g["part"]
                if "part" in g
                else bench_study.section_of(anchor) != g["section"]
            ):
                continue
            ref = f"{g['file']} {bench_study.section_of(anchor)}"
            out += [(ref, s) for s, _ in evidence._sentences(str(ch["text"]))]  # pyright: ignore[reportPrivateUsage]
    return out


def first_usable_s(steps: Iterable[tuple[float, dict[str, Any]]]) -> float | None:
    """When the run first held an answer: the first acceptance, else the final answer."""
    final = None
    for at, s in steps:
        submit = s["type"] == "tool_result" and s.get("name") == "submit_chat_answer"
        if submit and str(s.get("result", "")).startswith("ACCEPTED"):
            return at
        if s["type"] == "gate" and s.get("content") == "accepted":
            return at
        if s["type"] == "final_answer" and final is None:
            final = at
    return final


@contextlib.contextmanager
def arm_switches(arm: str) -> Iterator[None]:
    """The arm's `tools` attributes for the duration of the block."""
    changes = ARMS[arm]
    before = {name: getattr(tools, name) for name in changes}
    for name, value in changes.items():
        setattr(tools, name, value)
    try:
        yield
    finally:
        for name, value in before.items():
            setattr(tools, name, value)


class _Recorder:
    """Every LLM call of a run, read from the Ollama client under both LangChain and
    `ollama_client`, plus what the history trim did. The ratio pairs the history of the last
    fit with the prompt of the chat call that sent it, never with a generate call."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.reads: list[str] = []
        self.trims = 0
        self.token_budget = False
        self.reset()
        self._fit = chat_agent._fit_window  # pyright: ignore[reportPrivateUsage]

    def reset(self) -> None:
        """A new run: no history measured yet."""
        self.calls.clear()
        self.reads.clear()
        self.trims = 0
        self.measured = (0, 0)  # (history chars, prompt tokens of the call that sent them)
        self._sent_chars: int | None = None

    def note(self, resp: Any, chat: bool = False) -> None:
        if chat and self._sent_chars is not None:
            self.measured = (self._sent_chars, getattr(resp, "prompt_eval_count", 0) or 0)
            self._sent_chars = None
        self.calls.append(
            {
                "prompt_tokens": getattr(resp, "prompt_eval_count", 0) or 0,
                "prefill_s": (getattr(resp, "prompt_eval_duration", 0) or 0) / 1e9,
                "answer_tokens": getattr(resp, "eval_count", 0) or 0,
                "answer_s": (getattr(resp, "eval_duration", 0) or 0) / 1e9,
                "done_reason": getattr(resp, "done_reason", None),
                "caller": caller(sys._getframe(), SRC),  # pyright: ignore[reportPrivateUsage]
            }
        )

    def fit(self, msgs: list[Any], trimmed: frozenset[int] = frozenset()) -> Any:
        budget = (
            token_budget(ollama_client.NUM_CTX, *self.measured)
            if self.token_budget
            else chat_agent.WINDOW_CHARS
        )
        out, cut = self._fit(msgs, trimmed, budget)
        self.trims += len(cut) - len(trimmed)
        self._sent_chars = sum(map(chat_agent._size, out))  # pyright: ignore[reportPrivateUsage]
        return out, cut


def _record(rec: _Recorder) -> None:
    def wrap(orig: Callable[..., Any], chat: bool) -> Callable[..., Any]:
        def stream(chunks: Iterable[Any]) -> Iterator[Any]:
            for chunk in chunks:
                if getattr(chunk, "done", False):
                    rec.note(chunk, chat)
                yield chunk

        def call(self: Any, *args: Any, **kwargs: Any) -> Any:
            out = orig(self, *args, **kwargs)
            if isinstance(out, Iterator):
                return stream(out)
            rec.note(out, chat)
            return out

        return call

    ollama.Client.chat = wrap(ollama.Client.chat, True)  # pyright: ignore[reportAttributeAccessIssue]
    ollama.Client.generate = wrap(ollama.Client.generate, False)  # pyright: ignore[reportAttributeAccessIssue]
    chat_agent._fit_window = rec.fit  # pyright: ignore[reportPrivateUsage]
    note_evidence = tools._note_evidence  # pyright: ignore[reportPrivateUsage]

    def noted(mem: run_memory.RunMemory, outputs: list[str], leads: bool = False) -> None:
        rec.reads.extend(outputs)
        note_evidence(mem, outputs, leads)

    tools._note_evidence = noted  # pyright: ignore[reportPrivateUsage]


def run_direct(question: str, gold: Sequence[dict[str, str]] | None = None) -> list[dict[str, Any]]:
    """Arm D4: code's searches and levels, then straight to the ledger answer, no agent turn.
    With ``gold`` (arm O) the ledger is every sentence of the gold sections instead, and
    nothing is searched. A draft the gate rejects still counts, so its facts can be scored."""
    run_memory.begin_run(question)
    mem = run_memory.current()
    assert mem is not None
    if gold is None:
        chat_agent._preflight(question)  # pyright: ignore[reportPrivateUsage]
    else:
        mem.ledger = oracle_ledger(gold, chunker.load_chunks)
    directive = lang.response_directive(question)
    answer = chat_agent._write_ledger_answer(mem, question, directive)  # pyright: ignore[reportPrivateUsage]
    drafts = mem.ledger_drafts or [""]
    note = chat_agent.LEDGER_NOTE if answer is not None else ""
    closing = "direct" if gold is None else "oracle"
    return [
        {"type": "final_answer", "content": answer or drafts[-1], "note": note, "closing": closing}
    ]


def _timed_steps(item: dict[str, Any], arm: str, started: float) -> list[tuple[float, Any]]:
    """The run's steps with their time since ``started``."""
    if arm in ("D4", "O"):
        gold = item["gold"] if arm == "O" else None
        return [(time.monotonic() - started, s) for s in run_direct(item["question"], gold)]
    return [(time.monotonic() - started, s) for s in chat_agent.run_chat_agent(item["question"])]


def _trace(
    item: dict[str, Any], mem: run_memory.RunMemory, rec: _Recorder, steps: list[Any]
) -> dict[str, Any]:
    """Where the run's text went and where its facts were lost."""
    return {
        **text_by_kind(steps),
        **fact_trace(item["facts"], rec.reads, mem.ledger),
        "ledger": [list(q) for q in mem.ledger],
        "gate_events": list(mem.gate_events),
    }


def run_once(item: dict[str, Any], arm: str, rep: int, rec: _Recorder) -> dict[str, Any]:
    """One question under one arm."""
    rec.reset()
    rec.token_budget = arm in TOKEN_BUDGET_ARMS
    started = time.monotonic()
    with arm_switches(arm):
        timed = _timed_steps(item, arm, started)
    steps = [s for _, s in timed]
    final = next((s for s in reversed(steps) if s["type"] == "final_answer"), {})
    answer = str(final.get("content", ""))
    mem = run_memory.current()
    assert mem is not None
    facts = bench_study.fact_hits(answer, item["facts"])
    cited = set(tools._RAW_CITE_RE.findall(answer))  # pyright: ignore[reportPrivateUsage]
    return {
        "id": item["id"],
        "arm": arm,
        "rep": rep,
        "num_ctx": ollama_client.NUM_CTX,
        "seconds": round(time.monotonic() - started, 1),
        "first_usable_s": first_usable_s(timed),
        "facts": facts,
        "facts_found": sum(facts),
        "exit": bench_deep_chat.exit_path(steps),
        "closing": bench_deep_chat.closing(steps),
        **bench_deep_chat.memory_counts(steps),
        "cited_unread": [f"{f} {a}" for f, a in tools._tagged_unread(mem, cited)],  # pyright: ignore[reportPrivateUsage]
        "gold_read": bench_deep_chat._score_gold(mem, answer, item["gold"])["gold_read"],  # pyright: ignore[reportPrivateUsage]
        "hops": max(mem.ref_depth.values(), default=0),
        "bonus": mem.bonus,
        "trims": rec.trims,
        **telemetry(rec.calls, ollama_client.NUM_CTX),
        "words": len(answer.split()),
        **_trace(item, mem, rec, steps),
        "answer": answer,
    }


def _done(path: Path | None) -> set[tuple[str, str, int]]:
    if path is None or not path.exists():
        return set()
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
    return {(r["id"], r["arm"], r["rep"]) for r in rows}


def main() -> None:
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n", 1)[0])
    ap.add_argument("--gold", type=Path, default=bench_study.FIXTURE)
    ap.add_argument("--arm", action="append", choices=list(ARMS), required=True)
    ap.add_argument("--only", action="append", help="question id; default the `deep` questions")
    ap.add_argument("--reps", type=int, default=1)
    ap.add_argument("--out", type=Path)
    args = ap.parse_args()
    for arm in args.arm:
        if WINDOWS.get(arm, 32768) != ollama_client.NUM_CTX:
            raise SystemExit(f"{arm} needs INGEST_NUM_CTX={WINDOWS.get(arm, 32768)}")
    fixture = json.loads(args.gold.read_text(encoding="utf-8"))
    db_context.set_active_db(fixture["db"])
    db_context.set_search_scope([fixture["db"]])
    if problems := bench_study.gold_problems(fixture):
        raise SystemExit("gold labels wrong:\n" + "\n".join(problems))
    items = [q for q in fixture["questions"] if (q["id"] in args.only if args.only else q["deep"])]
    done, rec = _done(args.out), _Recorder()
    _record(rec)
    # Arms alternate within a question, so warm-up and caches favour none of them.
    for rep in range(args.reps):
        for item in items:
            for arm in args.arm:
                if (item["id"], arm, rep) in done:
                    continue
                row = run_once(item, arm, rep, rec)
                print({k: v for k, v in row.items() if k not in LOCAL_ONLY}, flush=True)
                if args.out:
                    with args.out.open("a", encoding="utf-8") as f:
                        f.write(json.dumps(row, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
