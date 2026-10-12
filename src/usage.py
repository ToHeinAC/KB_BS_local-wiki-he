"""Usage log: an append-only JSONL of who used the app when, for later analysis.

One row per event in `data/usage.jsonl` (gitignored): `ts` (local time with UTC offset),
`event`, `user`, plus event fields — sign-ins, chat and research runs, ingests, downloads,
with mode, database, duration and status. Never passwords, questions, file names or
document text. A write error is swallowed: logging must never break the app. Read it with
`read_events()` or `pandas.read_json(path, lines=True)`. Adapted from local_translator.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Callable
from datetime import datetime
from typing import Any

import db_context

_lock = threading.Lock()


def _local_now() -> datetime:
    return datetime.now().astimezone()


def log_event(
    event: str, user: str, *, now: Callable[[], datetime] = _local_now, **fields: Any
) -> None:
    row = {"ts": now().isoformat(timespec="seconds"), "event": event, "user": user, **fields}
    line = json.dumps(row, ensure_ascii=False) + "\n"
    path = db_context.usage_log_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with _lock, path.open("a", encoding="utf-8") as f:
            f.write(line)
    except OSError:
        pass


def read_events() -> list[dict[str, Any]]:
    """All events in order; empty without a log. Unparseable lines are skipped."""
    path = db_context.usage_log_path()
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            rows.append(json.loads(line))
        except ValueError:
            continue
    return rows
