"""The timeline of an agent run ("How the research ran"), shared by Research and Chat.

Agent steps (thought, tool call, tool result, notice, error) become dated items: a time, a pin
and a line that folds open to the detail. Steps are stamped with the time they arrived.
"""

import time
from dataclasses import dataclass
from typing import Any

from nicegui import ui


@dataclass(frozen=True)
class TraceItem:
    kind: str  # call, result, thought, notice, error, done
    title: str
    detail: str
    at: str


def stamp(step: dict[str, Any]) -> dict[str, Any]:
    """The step with the wall-clock time it arrived, as the timeline shows it."""
    return {**step, "at": time.strftime("%H:%M:%S")}


def _item(step: dict[str, Any]) -> TraceItem | None:
    kind, at = step["type"], step.get("at", "")
    if kind == "thought":
        return TraceItem("thought", step.get("label") or "Thought", step["content"], at)
    if kind == "notice":
        return TraceItem("notice", "Notice", step["content"], at)
    if kind == "ontology":
        return TraceItem("thought", "Ontology frame", step["content"], at)
    if kind == "error":
        return TraceItem("error", "Error", step["content"], at)
    if kind == "tool_call":
        args: dict[str, Any] = step.get("args") or {}
        if step.get("terminal"):
            return TraceItem("done", f"{step['name']} — research phase finished", "", at)
        detail = "\n".join(p for p in (str(args)[:300] if args else "", step.get("note", "")) if p)
        return TraceItem("call", step["name"], detail, at)
    if kind == "tool_result":
        srcs: list[dict[str, str]] = step.get("sources") or []
        title = f"Result: {step['name']}" + (f" — {len(srcs)} source(s)" if srcs else "")
        lines = [step.get("note", ""), *(f"{s['title'] or s['url']} ({s['url']})" for s in srcs)]
        return TraceItem(
            "result", title, "\n".join([*filter(None, lines), step["result"][:2000]]), at
        )
    return None


def trace_items(steps: list[dict[str, Any]]) -> list[TraceItem]:
    return [item for item in map(_item, steps) if item is not None]


def _render_item(item: TraceItem) -> None:
    with ui.element("div").classes(f"row {'done' if item.kind == 'done' else ''}".strip()):
        ui.label(item.at).classes("time")
        ui.element("span").classes("pin")
        with ui.column().classes("what gap-0"):
            if item.detail and item.kind in ("result", "call", "thought"):
                with ui.expansion(item.title).classes("fold w-full"):
                    ui.label(item.detail).classes("muted text-caption").style(
                        "white-space: pre-wrap"
                    )
            else:
                ui.label(item.title).classes("text-negative" if item.kind == "error" else "")
                if item.detail:
                    ui.label(item.detail).classes("muted text-caption")


def render_timeline(title: str, steps: list[dict[str, Any]]) -> None:
    """The section label and one item per shown step; nothing when no step is shown."""
    items = trace_items(steps)
    if not items:
        return
    ui.label(title).classes("section-label")
    with ui.column().classes("wire w-full gap-0"):
        for item in items:
            _render_item(item)
