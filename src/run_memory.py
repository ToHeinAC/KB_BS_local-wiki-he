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

    def tick(self) -> int:
        self.step += 1
        return self.step

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
