"""Deep chat arms of the study in research_notes/retrieval_deepchat/00_framework.md (FF2, FF3).

Runs `chat_agent.run_chat_agent` on the gold file's `deep` questions under each arm and logs
one JSON row per run: mandatory facts found, gold sections read, wall time, time to the first
usable answer, and the token counts of every LLM call. Arms only switch module attributes
for the run, `src/` stays as it is. `prompt_eval_count` is the whole prompt even on a cache
hit, so it gives the fill level, and `prompt_eval_duration` tells the cache hit (measured,
framework §1). A run appends to `--out` and a restart skips what is there.

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
from collections.abc import Callable, Iterable, Iterator, Sequence
from pathlib import Path
from typing import Any

import ollama

sys.path.insert(0, str(Path(__file__).resolve().parent))
import bench_deep_chat
import bench_study

import chat_agent
import db_context
import lang
import ollama_client
import run_memory
import tools

RESERVE = 8192  # chat_agent._ANSWER_RESERVE_TOKENS
CODE_RATIO = 3  # chat_agent._CHARS_PER_TOKEN
AT_WINDOW = 0.99
CACHE_FACTOR = 3  # a prompt counts as cached when it prefills this much faster than the coldest

_NO_DEPTH = {"TERMS_MAX": 0, "CITING_MAX": 0, "DEEP_TERMS_MAX": 0}


def _no_footer(*_args: Any) -> str:
    return ""


def _no_levels(*_args: Any) -> list[Any]:
    return []


# Arm → attributes of `tools` set for the run (framework §2). E1–E4 add the token budget, and
# E2–E4 need their window from the environment. D4 skips the agent loop (`run_direct`).
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
}
TOKEN_BUDGET_ARMS = {"E1", "E2", "E3", "E4"}
WINDOWS = {"E2": 16384, "E3": 65536, "E4": 131072}


def token_budget(num_ctx: int, chars: int, tokens: int) -> int:
    """The history budget in characters from the run's measured ratio (the code's estimate
    until the first call has been measured)."""
    ratio = chars / tokens if tokens else CODE_RATIO
    return int((num_ctx - RESERVE) * ratio)


def telemetry(calls: Sequence[dict[str, Any]], num_ctx: int) -> dict[str, Any]:
    """A run's LLM calls in one row: fill level, cache hits, truncation signs."""
    if not calls:
        return {"llm_calls": 0, "fill_max": 0, "fill_mean": 0}
    prompts = [c["prompt_tokens"] for c in calls]
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
    }


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
    `ollama_client`, plus what the history trim did."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.trims = 0
        self.history_chars = 0
        self.token_budget = False
        self._fit = chat_agent._fit_window  # pyright: ignore[reportPrivateUsage]

    def note(self, resp: Any) -> None:
        self.calls.append(
            {
                "prompt_tokens": getattr(resp, "prompt_eval_count", 0) or 0,
                "prefill_s": (getattr(resp, "prompt_eval_duration", 0) or 0) / 1e9,
                "answer_tokens": getattr(resp, "eval_count", 0) or 0,
                "answer_s": (getattr(resp, "eval_duration", 0) or 0) / 1e9,
                "done_reason": getattr(resp, "done_reason", None),
            }
        )

    def fit(self, msgs: list[Any], trimmed: frozenset[int] = frozenset()) -> Any:
        tokens = self.calls[-1]["prompt_tokens"] if self.calls else 0
        budget = (
            token_budget(ollama_client.NUM_CTX, self.history_chars, tokens)
            if self.token_budget
            else chat_agent.WINDOW_CHARS
        )
        out, cut = self._fit(msgs, trimmed, budget)
        self.trims += len(cut) - len(trimmed)
        self.history_chars = sum(map(chat_agent._size, out))  # pyright: ignore[reportPrivateUsage]
        return out, cut


def _record(rec: _Recorder) -> None:
    def wrap(orig: Callable[..., Any]) -> Callable[..., Any]:
        def stream(chunks: Iterable[Any]) -> Iterator[Any]:
            for chunk in chunks:
                if getattr(chunk, "done", False):
                    rec.note(chunk)
                yield chunk

        def call(self: Any, *args: Any, **kwargs: Any) -> Any:
            out = orig(self, *args, **kwargs)
            if isinstance(out, Iterator):
                return stream(out)
            rec.note(out)
            return out

        return call

    ollama.Client.chat = wrap(ollama.Client.chat)  # pyright: ignore[reportAttributeAccessIssue]
    ollama.Client.generate = wrap(ollama.Client.generate)  # pyright: ignore[reportAttributeAccessIssue]
    chat_agent._fit_window = rec.fit  # pyright: ignore[reportPrivateUsage]


def run_direct(question: str) -> list[dict[str, Any]]:
    """Arm D4: code's searches and levels, then straight to the ledger answer, no agent turn.
    A draft the gate rejects still counts, so its facts can be scored."""
    run_memory.begin_run(question)
    chat_agent._preflight(question)  # pyright: ignore[reportPrivateUsage]
    mem = run_memory.current()
    assert mem is not None
    directive = lang.response_directive(question)
    answer = chat_agent._write_ledger_answer(mem, question, directive)  # pyright: ignore[reportPrivateUsage]
    drafts = mem.ledger_drafts or [""]
    note = chat_agent.LEDGER_NOTE if answer is not None else ""
    return [
        {"type": "final_answer", "content": answer or drafts[-1], "note": note, "closing": "direct"}
    ]


def run_once(item: dict[str, Any], arm: str, rep: int, rec: _Recorder) -> dict[str, Any]:
    """One question under one arm."""
    rec.calls.clear()
    rec.trims, rec.history_chars, rec.token_budget = 0, 0, arm in TOKEN_BUDGET_ARMS
    started = time.monotonic()
    timed: list[tuple[float, dict[str, Any]]] = []
    with arm_switches(arm):
        if arm == "D4":
            timed = [(time.monotonic() - started, s) for s in run_direct(item["question"])]
        else:
            for step in chat_agent.run_chat_agent(item["question"]):
                timed.append((time.monotonic() - started, step))
    steps = [s for _, s in timed]
    final = next((s for s in reversed(steps) if s["type"] == "final_answer"), {})
    answer = str(final.get("content", ""))
    mem = run_memory.current()
    assert mem is not None
    facts = bench_study.fact_hits(answer, item["facts"])
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
        "cited_unread": [
            f"{f} {a}"
            for f, a in tools._tagged_unread(mem, set(tools._RAW_CITE_RE.findall(answer)))
        ],  # pyright: ignore[reportPrivateUsage]
        "gold_read": bench_deep_chat._score_gold(mem, answer, item["gold"])["gold_read"],  # pyright: ignore[reportPrivateUsage]
        "hops": max(mem.ref_depth.values(), default=0),
        "bonus": mem.bonus,
        "trims": rec.trims,
        **telemetry(rec.calls, ollama_client.NUM_CTX),
        "words": len(answer.split()),
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
                print({k: v for k, v in row.items() if k != "answer"}, flush=True)
                if args.out:
                    with args.out.open("a", encoding="utf-8") as f:
                        f.write(json.dumps(row, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
