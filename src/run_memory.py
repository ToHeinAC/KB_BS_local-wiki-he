"""Per-run "visited" memory for the Chat-Deep and Researcher agents.

Tracks which (file, offset) reads and which search queries the agent has
already issued during a single graph invocation, so the tool layer can
short-circuit exact-duplicate calls with a one-line stub instead of
re-fetching the same content and re-feeding it into the message history.

Scoped via `contextvars.ContextVar` so each Streamlit submission gets a
fresh memory without callers needing to thread it through.
"""

from __future__ import annotations

import contextvars
from dataclasses import dataclass, field
from typing import Any


@dataclass
class RunMemory:
    reads: dict[str, int] = field(default_factory=dict[str, int])
    searches: dict[str, int] = field(default_factory=dict[str, int])
    step: int = 0
    # Stage E: best cross-encoder rerank_score seen this run, and whether the low-
    # confidence nudge has already fired (bounds it to one extra iteration).
    best_relevance: float | None = None
    low_conf_nudged: bool = False
    # Search-ladder audit (idea.md §6.9.1): best rerank_score seen per source, so the
    # answer surface can show a "Why these sources" record (kept vs below-τ).
    relevance_by_source: dict[str, float] = field(default_factory=dict[str, float])
    # Ontology stage (docs/ontology.md §Search): one record per distinct frame this run.
    ontology: list[dict[str, Any]] = field(default_factory=list[dict[str, Any]])
    # Point in time of the run's question (docs/ontology.md §Time): an ISO date when it
    # named one, `time_past` when it asked about an earlier state without a date.
    as_of: str | None = None
    time_past: bool = False
    validity_nudged: bool = False  # the S4 superseded-citation check fired once
    # The run's question: ranks a long legal file's sections on a bare or repeated read.
    question: str = ""
    # Prose-exit gate: answers written as prose instead of submitted, and the reason the
    # last one failed (None once one passed). `gate_events` feeds the trace.
    prose_rejections: int = 0
    gate_reason: str | None = None
    gate_events: list[str] = field(default_factory=list[str])
    prose_section_nudged: bool = False  # an unread § named in the prose was rejected once
    open_refs_nudged: bool = False  # an out-of-scope reference missing from Open points
    quote_nudged: bool = False  # a quoted span the cited originals lack was rejected once
    # The sections the last rejection cited unread ("file § N"): code reads them next turn.
    unread_due: list[str] = field(default_factory=list[str])
    # Evidence ledger (src/evidence.py): (citation ref, sentence) from every raw_read; and
    # how many turns in a row added none (chat_agent's stop rule).
    ledger: list[tuple[str, str]] = field(default_factory=list[tuple[str, str]])
    ledger_seen: int = -1  # -1: the run's first turn always counts as progress
    stale_turns: int = 0
    empty_nudged: bool = False  # an empty model turn was sent back once
    # The answer written from the ledger, its gate verdict, and the ledger size it was
    # written at (-1: none yet), so an unchanged ledger is not written up twice.
    ledger_answer: str | None = None
    ledger_verdict: str = ""
    ledger_tried: int = -1
    ledger_drafts: list[str] = field(default_factory=list[str])  # every one written, for the trace
    ledger_raw: list[str] = field(default_factory=list[str])  # the same, before code cleaned them
    # Reference chains: a section a footer offered ("<qbase>|sec=<canon>" → (depth, cross)),
    # the depth of each read section, out-of-scope work names per read section, and the
    # extra agent turns earned by following cross-file references.
    ref_offers: dict[str, tuple[int, bool]] = field(default_factory=dict[str, tuple[int, bool]])
    ref_depth: dict[str, int] = field(default_factory=dict[str, int])
    out_of_scope: dict[str, list[str]] = field(default_factory=dict[str, list[str]])
    bonus: int = 0
    work_files: dict[str, str | None] = field(default_factory=dict[str, str | None])  # name → file

    def tick(self) -> int:
        self.step += 1
        return self.step

    def note_relevance(self, score: float) -> None:
        if self.best_relevance is None or score > self.best_relevance:
            self.best_relevance = score

    def note_source_relevance(self, source: str, score: float) -> None:
        prev = self.relevance_by_source.get(source)
        if prev is None or score > prev:
            self.relevance_by_source[source] = score

    def note_ontology(self, record: dict[str, Any]) -> None:
        if record not in self.ontology:
            self.ontology.append(record)

    def seen_read(self, key: str) -> int | None:
        return self.reads.get(key)

    def mark_read(self, key: str) -> None:
        self.reads.setdefault(key, self.step)

    def seen_search(self, key: str) -> int | None:
        return self.searches.get(key)

    def mark_search(self, key: str) -> None:
        self.searches.setdefault(key, self.step)

    def search_count(self) -> int:
        """Distinct queries searched: one query in the raw and the wiki scope is one search."""
        return len({key.split(":", 1)[-1] for key in self.searches})


_current: contextvars.ContextVar[RunMemory | None] = contextvars.ContextVar(
    "run_memory_current", default=None
)


def begin_run(question: str = "") -> RunMemory:
    m = RunMemory(question=question)
    _current.set(m)
    return m


def current() -> RunMemory | None:
    return _current.get()


def note_ontology(record: dict[str, Any]) -> None:
    """Record an ontology frame on the current run (no-op outside a run)."""
    mem = current()
    if mem is not None:
        mem.note_ontology(record)


def note_time(as_of: str | None, past: bool) -> None:
    """Record the question's point in time on the current run (no-op outside a run)."""
    mem = current()
    if mem is not None:
        mem.as_of, mem.time_past = as_of, past
