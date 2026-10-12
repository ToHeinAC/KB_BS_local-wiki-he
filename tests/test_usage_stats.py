"""Pure aggregation of the usage log for the admin statistics (src/usage_stats.py)."""

from datetime import UTC, date, datetime
from typing import Any

from usage_stats import OTHER, daily, since, totals, user_colors, users_in_order

NOW = datetime(2026, 10, 12, 12, 0, tzinfo=UTC)


def ev(ts: str, event: str, user: str, **fields: Any) -> dict[str, Any]:
    return {"ts": ts, "event": event, "user": user, **fields}


EVENTS = [
    ev("2026-08-01T10:00:00+00:00", "login_ok", "Gast"),
    ev("2026-10-10T09:00:00+00:00", "login_ok", "T. Hein"),
    ev("2026-10-10T09:01:00+00:00", "chat", "T. Hein", status="ok", duration_s=120.0),
    ev("2026-10-10T09:04:00+00:00", "download", "T. Hein", kind="page"),
    ev("2026-10-11T15:00:00+00:00", "research", "Brenk", status="error", duration_s=30.0),
    ev("2026-10-11T15:01:00+00:00", "ingest", "Brenk", status="ok", duration_s=90.0, files=2),
    ev("2026-10-11T15:02:00+00:00", "login_failed", "Tippfehler"),
]


def test_since_keeps_only_the_period():
    assert since(EVENTS, None, NOW) == EVENTS
    assert len(since(EVENTS, 7, NOW)) == 6
    assert since(EVENTS, 7, NOW)[0]["user"] == "T. Hein"


def test_daily_sums_each_metric_per_day_and_user():
    assert daily(EVENTS, "chats") == {(date(2026, 10, 10), "T. Hein"): 1.0}
    assert daily(EVENTS, "research") == {(date(2026, 10, 11), "Brenk"): 1.0}
    assert daily(EVENTS, "ingests") == {(date(2026, 10, 11), "Brenk"): 1.0}
    assert daily(EVENTS, "minutes") == {
        (date(2026, 10, 10), "T. Hein"): 2.0,
        (date(2026, 10, 11), "Brenk"): 2.0,
    }
    assert daily(EVENTS, "logins") == {
        (date(2026, 8, 1), "Gast"): 1.0,
        (date(2026, 10, 10), "T. Hein"): 1.0,
    }
    assert daily(EVENTS, "downloads") == {(date(2026, 10, 10), "T. Hein"): 1.0}


def test_totals_per_user_skip_failed_login_names():
    rows = totals(EVENTS)
    assert [r.user for r in rows] == ["Gast", "T. Hein", "Brenk"]
    hein, brenk = rows[1], rows[2]
    assert (hein.logins, hein.chats, hein.minutes, hein.downloads) == (1, 1, 2.0, 1)
    assert hein.last_seen == "2026-10-10T09:04:00+00:00"
    assert (brenk.research, brenk.ingests, brenk.errors) == (1, 1, 1)


def test_users_keep_their_color_when_the_period_changes():
    order = users_in_order(EVENTS)
    assert order == ["Gast", "T. Hein", "Brenk"]
    colors = user_colors(order)
    assert len(set(colors.values())) == 3
    assert user_colors(users_in_order(EVENTS))["Brenk"] == colors["Brenk"]


def test_more_than_eight_users_fold_into_other():
    colors = user_colors([f"u{i}" for i in range(10)])
    assert colors["u6"] != colors["u7"]
    assert colors["u7"] == colors["u9"] == colors[OTHER]
