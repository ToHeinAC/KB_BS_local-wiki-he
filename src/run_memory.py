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


@dataclass
class RunMemory:
    reads: dict[str, int] = field(default_factory=dict)
    searches: dict[str, int] = field(default_factory=dict)
    step: int = 0
    # Stage E: best cross-encoder rerank_score seen this run, and whether the low-
    # confidence nudge has already fired (bounds it to one extra iteration).
    best_relevance: float | None = None
    low_conf_nudged: bool = False
    # Search-ladder audit (idea.md §6.9.1): best rerank_score seen per source, so the
    # answer surface can show a "Why these sources" record (kept vs below-τ).
    relevance_by_source: dict[str, float] = field(default_factory=dict)

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

    def seen_read(self, key: str) -> int | None:
        return self.reads.get(key)

    def mark_read(self, key: str) -> None:
        self.reads.setdefault(key, self.step)

    def seen_search(self, key: str) -> int | None:
        return self.searches.get(key)

    def mark_search(self, key: str) -> None:
        self.searches.setdefault(key, self.step)


_current: contextvars.ContextVar[RunMemory | None] = contextvars.ContextVar(
    "run_memory_current", default=None
)


def begin_run() -> RunMemory:
    m = RunMemory()
    _current.set(m)
    return m


def current() -> RunMemory | None:
    return _current.get()
