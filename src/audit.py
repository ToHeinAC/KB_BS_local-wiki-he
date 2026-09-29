"""Security audit log: an append-only JSONL of who did what to which shard.

Rows name users, actions, files and shards — never document content. Written
for clearance changes, classifications, moves, silent duplicates and every
access denial in a signed-in session (via `db_context.set_denial_listener`).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import db_context


def record(action: str, user: str, **fields: str | int | None) -> None:
    row: dict[str, Any] = {"at": datetime.now(UTC).isoformat(timespec="seconds")}
    row.update(action=action, user=user, **fields)
    path = db_context.audit_log_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def recent(limit: int = 200) -> list[dict[str, Any]]:
    """The newest `limit` rows, newest first. Unparseable lines are skipped."""
    path = db_context.audit_log_path()
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in reversed(path.read_text(encoding="utf-8").splitlines()):
        try:
            rows.append(json.loads(line))
        except ValueError:
            continue
        if len(rows) >= limit:
            break
    return rows


def _on_denied(user: str, target: str) -> None:
    record("access_denied", user, target=target, shard=db_context.get_active_db())


db_context.set_denial_listener(_on_denied)
