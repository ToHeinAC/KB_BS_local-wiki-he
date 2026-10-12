"""Plotly bar chart of the usage log per day (admin statistics). Adapted from local_translator."""

from typing import Any

import plotly.graph_objects as go  # pyright: ignore[reportMissingTypeStubs]

from usage_stats import PALETTE, Event, daily, series_names, user_colors

_SURFACE = "#f7f5ef"  # broadsheet --paper
_GRID = "#d9d3c4"  # --hair
_MUTED = "#736e60"  # --muted


def _series(
    events: list[Event], metric: str, names: dict[str, str] | None, total: str
) -> dict[str, dict[Any, float]]:
    """Series name -> {day: value}; per user in ``names`` order, or one total series."""
    out: dict[str, dict[Any, float]] = {n: {} for n in (names or {}).values()}
    for (day, user), value in sorted(daily(events, metric).items()):
        name = names.get(user, user) if names is not None else total
        series = out.setdefault(name, {})
        series[day] = series.get(day, 0.0) + value
    return {name: values for name, values in out.items() if values}


def daily_figure(
    events: list[Event], metric: str, *, order: list[str] | None, total_label: str
) -> Any:
    """Stacked bars per day: one series per user of ``order`` (the full log, so colors stay
    fixed when the period changes), or a single total series if ``order`` is None."""
    names = series_names(order) if order is not None else None
    colors = user_colors(order) if order is not None else {}
    fig: Any = go.Figure()
    for name, values in _series(events, metric, names, total_label).items():
        fig.add_trace(
            go.Bar(
                name=name,
                x=list(values),
                y=list(values.values()),
                marker={
                    "color": colors.get(name, PALETTE[0]),
                    "line": {"color": _SURFACE, "width": 2},
                },
                hovertemplate=f"<b>{name}</b><br>%{{x|%d.%m.%Y}}: %{{y:.4~g}}<extra></extra>",
            )
        )
    fig.update_layout(
        barmode="stack",
        barcornerradius=4,
        bargap=0.25,
        showlegend=len(fig.data) > 1,
        legend={"orientation": "h", "y": 1.08, "x": 0},
        plot_bgcolor=_SURFACE,
        paper_bgcolor=_SURFACE,
        font={
            "family": "Libre Franklin, Helvetica Neue, Arial, sans-serif",
            "color": _MUTED,
            "size": 13,
        },
        margin={"l": 40, "r": 16, "t": 40, "b": 40},
        hovermode="closest",
        xaxis={"type": "date", "showgrid": False, "tickformat": "%d.%m."},
        yaxis={"gridcolor": _GRID, "zeroline": False, "rangemode": "tozero"},
    )
    return fig
