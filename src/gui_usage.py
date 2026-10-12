"""Usage statistics on the Admin page, for the seeded owner account (`auth.DEFAULT_USER`) only.

Reads `data/usage.jsonl` (`usage.py`), aggregates it with `usage_stats` and draws daily bars
with plotly (`usage_chart`): a slider picks the period, a select the metric, a switch the
split by user; KPI tiles and a per-user table follow. Adapted from local_translator.
"""

from datetime import datetime
from typing import Any

from nicegui import ui

import usage
import usage_stats
from usage_chart import daily_figure

#: slider position -> (label, days back; None is the whole log)
PERIODS: tuple[tuple[str, int | None], ...] = (("All time", None), ("1 month", 30), ("1 week", 7))
METRICS = {
    "chats": "Chats",
    "research": "Research runs",
    "ingests": "Ingests",
    "minutes": "Minutes in runs",
    "logins": "Sign-ins",
    "downloads": "Downloads",
}
_COLUMNS = ("user", "logins", "chats", "research", "ingests", "minutes", "downloads", "errors")


class UsagePanel:
    def __init__(self) -> None:
        self.period, self.metric, self.by_user = 0, "chats", True
        self.events: list[dict[str, Any]] = []

    def build(self) -> None:
        ui.label("Usage statistics").classes("headline s q-mt-lg")
        self.events = usage.read_events()
        if not self.events:
            ui.label("No usage recorded yet.").classes("muted")
            return
        self._controls()
        self.body = ui.column().classes("w-full")
        self.render()

    def _controls(self) -> None:
        labels = ", ".join(f"'{label}'" for label, _ in PERIODS)
        with ui.row().classes("items-end w-full gap-8"):
            slider = ui.slider(min=0, max=len(PERIODS) - 1, step=1, value=self.period)
            slider.props(f'markers snap :marker-labels="[{labels}]"').classes("w-64 q-px-md")
            slider.on_value_change(lambda e: self._set("period", int(e.value or 0)))
            slider.mark("usage-period")
            metric = ui.select(METRICS, value=self.metric, label="Metric").classes("w-56")
            metric.props("outlined dense").mark("usage-metric")
            metric.on_value_change(lambda e: self._set("metric", str(e.value)))
            split = ui.switch("Split by user", value=self.by_user).mark("usage-by-user")
            split.on_value_change(lambda e: self._set("by_user", bool(e.value)))

    def _set(self, name: str, value: Any) -> None:
        setattr(self, name, value)
        self.render()

    def render(self) -> None:
        shown = usage_stats.since(self.events, PERIODS[self.period][1], datetime.now().astimezone())
        order = usage_stats.users_in_order(self.events) if self.by_user else None
        fig = daily_figure(shown, self.metric, order=order, total_label="Total")
        rows = usage_stats.totals(shown)
        self.body.clear()
        with self.body:
            _tiles(rows, shown)
            ui.plotly(fig).classes("w-full").mark("usage-chart")
            _table(rows)


def _tiles(rows: list[usage_stats.UserTotals], events: list[dict[str, Any]]) -> None:
    failed = sum(e["event"] == "login_failed" for e in events)
    tiles = [
        ("Active users", len(rows)),
        *((METRICS[m], _total(rows, m)) for m in METRICS),
        ("Failed sign-ins", failed),
    ]
    with ui.row().classes("figs w-full gap-8"):
        for label, value in tiles:
            with ui.column().classes("gap-0"):
                ui.label(label).classes("label")
                ui.label(str(value)).classes("num")


def _total(rows: list[usage_stats.UserTotals], metric: str) -> int | float:
    total = sum(getattr(r, metric) for r in rows)
    return round(total, 1) if metric == "minutes" else total


def _table(rows: list[usage_stats.UserTotals]) -> None:
    columns = [{"name": c, "label": c.capitalize(), "field": c, "align": "left"} for c in _COLUMNS]
    columns.append({"name": "last_seen", "label": "Last active", "field": "last_seen"})
    data = [
        {**{c: getattr(r, c) for c in _COLUMNS}, "minutes": round(r.minutes, 1),
         "last_seen": r.last_seen[:16].replace("T", " ")}
        for r in rows
    ]  # fmt: skip
    ui.table(columns=columns, rows=data, row_key="user").classes("w-full").mark("usage-table")
