"""Pure aggregation of usage-log events (`usage.py`) for the admin statistics.

Adapted from local_translator's `usage_stats.py`.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

Event = dict[str, Any]

#: metric -> the events it counts; `minutes` sums their `duration_s` instead.
METRIC_EVENTS: dict[str, tuple[str, ...]] = {
    "chats": ("chat",),
    "research": ("research",),
    "ingests": ("ingest",),
    "minutes": ("chat", "research", "ingest"),
    "logins": ("login_ok",),
    "downloads": ("download",),
}
OTHER = "Other"
#: Categorical slots 1-8 of the dataviz reference palette (light), in fixed order.
PALETTE = (
    "#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948",
)  # fmt: skip
_COUNTED = {"login_ok": "logins", "chat": "chats", "research": "research", "ingest": "ingests"}


@dataclass
class UserTotals:
    user: str
    logins: int = 0
    chats: int = 0
    research: int = 0
    ingests: int = 0
    minutes: float = 0.0
    downloads: int = 0
    errors: int = 0
    last_seen: str = ""


def _time(event: Event) -> datetime:
    return datetime.fromisoformat(event["ts"])


def since(events: list[Event], days: int | None, now: datetime) -> list[Event]:
    """Events of the last `days` days; all of them for None."""
    if days is None:
        return events
    cutoff = now - timedelta(days=days)
    return [e for e in events if _time(e) >= cutoff]


def _value(event: Event, metric: str) -> float:
    if event["event"] not in METRIC_EVENTS[metric]:
        return 0.0
    return float(event.get("duration_s", 0.0)) / 60 if metric == "minutes" else 1.0


def daily(events: list[Event], metric: str) -> dict[tuple[date, str], float]:
    """Sum of `metric` per (day, user); days with nothing are left out."""
    sums: dict[tuple[date, str], float] = defaultdict(float)
    for e in events:
        if value := _value(e, metric):
            sums[(_time(e).date(), e["user"])] += value
    return dict(sums)


def _add(row: UserTotals, event: Event) -> None:
    kind = event["event"]
    if kind in _COUNTED:
        setattr(row, _COUNTED[kind], getattr(row, _COUNTED[kind]) + 1)
    row.downloads += kind == "download"
    if kind in METRIC_EVENTS["minutes"]:
        row.minutes += float(event.get("duration_s", 0.0)) / 60
        row.errors += event.get("status") == "error"
    row.last_seen = max(row.last_seen, event["ts"])


def totals(events: list[Event]) -> list[UserTotals]:
    """One row per user in order of first appearance; failed-login names are not users."""
    rows: dict[str, UserTotals] = {}
    for e in events:
        if e["event"] != "login_failed":
            _add(rows.setdefault(e["user"], UserTotals(e["user"])), e)
    return list(rows.values())


def users_in_order(events: list[Event]) -> list[str]:
    """Users by first appearance; taken from the full log, colors stay fixed across filters."""
    return [row.user for row in totals(events)]


def series_names(order: list[str]) -> dict[str, str]:
    """User -> chart series; beyond eight users the rest share one `OTHER` series."""
    if len(order) <= len(PALETTE):
        return {u: u for u in order}
    keep = len(PALETTE) - 1
    return {u: u if i < keep else OTHER for i, u in enumerate(order)}


def user_colors(order: list[str]) -> dict[str, str]:
    """Series name -> color, assigned in fixed palette order."""
    names = series_names(order)
    series = list(dict.fromkeys(names.values()))
    colors = {name: PALETTE[i] for i, name in enumerate(series)}
    return {**colors, **{u: colors[s] for u, s in names.items()}}
