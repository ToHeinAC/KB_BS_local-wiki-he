"""Plotly bar chart of the usage log (src/usage_chart.py)."""

from datetime import date

from test_usage_stats import EVENTS, ev

from usage_chart import daily_figure
from usage_stats import OTHER, PALETTE, user_colors, users_in_order


def _bars(fig):
    return [(t.name, list(t.x), list(t.y), t.marker.color) for t in fig.data]


def test_split_by_user_gives_one_stacked_series_per_user_with_fixed_colors():
    colors = user_colors(users_in_order(EVENTS))
    fig = daily_figure(EVENTS, "minutes", order=users_in_order(EVENTS), total_label="Total")
    bars = _bars(fig)
    assert [b[0] for b in bars] == ["T. Hein", "Brenk"]  # Gast has no minutes
    assert bars[0][1:] == ([date(2026, 10, 10)], [2.0], colors["T. Hein"])
    assert fig.layout.barmode == "stack"
    assert fig.layout.showlegend is True


def test_total_is_one_series_without_legend():
    fig = daily_figure(EVENTS, "minutes", order=None, total_label="Total")
    ((name, x, y, color),) = _bars(fig)
    assert (name, color) == ("Total", PALETTE[0])
    assert x == [date(2026, 10, 10), date(2026, 10, 11)]
    assert y == [2.0, 2.0]
    assert fig.layout.showlegend is False


def test_no_events_give_an_empty_figure():
    assert not daily_figure([], "chats", order=[], total_label="Total").data


def test_users_beyond_eight_share_one_other_series():
    events = [ev("2026-10-10T09:00:00+00:00", "chat", f"u{i}") for i in range(10)]
    bars = _bars(daily_figure(events, "chats", order=users_in_order(events), total_label="T"))
    assert [b[0] for b in bars] == [*(f"u{i}" for i in range(7)), OTHER]
    assert bars[-1][2] == [3.0]
