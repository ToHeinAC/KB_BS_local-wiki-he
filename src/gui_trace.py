"""The timeline of an agent run ("How the research ran"), shared by Research and Chat.

Agent steps (thought, tool call, tool result, notice, error) become dated items: a time, a pin
and a line that folds open to the detail. Steps are stamped with the time they arrived. A tool
result reads as a one-line summary (hits, the file read, "no results"); folded open it lists the
hits, and the complete tool output folds open beneath them.
"""

import re
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
    full: str = ""  # a tool result's complete output


_HIT = re.compile(r"^(?:\[(?:Raw hit|Wiki hit|Wiki linked) \d+|Result \d+: )", re.M)
_OUTLINE = re.compile(r"^(?:file: (.+)|Result \d+: (.+))$", re.M)
_READ = re.compile(r"^## (?:Raw file|Wiki page): (.+)$", re.M)
# Run-memory markers of Deep chat's raw_read (src/tools.py): a repeat served something new,
# a long law was answered with a section map, or a file has nothing left to read.
_ADVANCED = re.compile(r"^## Raw file: (.+?) \[memory: (.+?) → serving", re.M)
_MAP = re.compile(r"^## Raw file: (.+?) — section map", re.M)
_EXPLORED = re.compile(r"^\[memory\] (.+?) fully explored", re.M)


def _value(value: Any) -> str:
    items: list[Any] = value if isinstance(value, list) else [value]  # pyright: ignore[reportUnknownVariableType]
    return ", ".join(map(str, items))


def _args_text(args: dict[str, Any]) -> str:
    """Call arguments as `key: value` pairs instead of a Python dict."""
    return " · ".join(f"{k}: {_value(v)}" for k, v in args.items())


def _memory_summary(result: str) -> str | None:
    """The run-memory label of a raw_read result, or None when it carries no marker."""
    advanced = _ADVANCED.findall(result)
    if advanced:
        return "; ".join(f"{why} → served {what}" for what, why in advanced)
    mapped = _MAP.search(result)
    if mapped:
        served = [r.removeprefix(mapped[1]).strip() for r in _READ.findall(result)[1:]]
        return f"section map of {mapped[1]} → read " + ", ".join(served)
    explored = _EXPLORED.search(result)
    return f"{explored[1]} fully explored" if explored else None


def summarize(result: str) -> str:
    """One line on what a tool returned: hits, the files read, no results, or its first line."""
    hits = len(_HIT.findall(result))
    if hits:
        return f"{hits} hit(s)"
    memory = _memory_summary(result)
    if memory:
        return memory
    reads = _READ.findall(result)
    if reads:
        return "read " + ", ".join(reads)
    if "(no results" in result:
        return "no results"
    return next((line.strip() for line in result.splitlines() if line.strip()), "")[:120]


def _outline(result: str) -> list[str]:
    """The file (or web title) of each hit, in order."""
    return [a or b for a, b in _OUTLINE.findall(result)]


def stamp(step: dict[str, Any]) -> dict[str, Any]:
    """The step with the wall-clock time it arrived, as the timeline shows it."""
    return {**step, "at": time.strftime("%H:%M:%S")}


def _item(step: dict[str, Any]) -> TraceItem | None:
    kind, at = step["type"], step.get("at", "")
    if kind == "thought":
        return TraceItem("thought", step.get("label") or "Thought", step["content"], at)
    if kind == "notice":
        return TraceItem("notice", "Notice", step["content"], at)
    if kind == "gate":  # Deep chat's prose answer went through the submit gate
        return TraceItem("notice", f"Quality gate — {step['content']}", "", at)
    if kind == "ontology":
        return TraceItem("thought", "Ontology frame", step["content"], at)
    if kind == "error":
        return TraceItem("error", "Error", step["content"], at)
    if kind == "tool_call":
        args: dict[str, Any] = step.get("args") or {}
        if step.get("terminal"):
            return TraceItem("done", f"{step['name']} — research phase finished", "", at)
        shown = _args_text(args)
        title = step["name"] + (f" — {shown[:100]}" if shown else "")
        detail = "\n".join(p for p in (shown, step.get("note", "")) if p)
        return TraceItem("call", title, detail, at)
    if kind == "tool_result":
        return _result_item(step, at)
    return None


def _result_item(step: dict[str, Any], at: str) -> TraceItem:
    result: str = step["result"]
    srcs: list[dict[str, str]] = step.get("sources") or []
    summary = f"{len(srcs)} source(s)" if srcs else summarize(result)
    title = f"Result: {step['name']}" + (f" — {summary}" if summary else "")
    lines = [
        step.get("note", ""),
        *(f"{s['title'] or s['url']} ({s['url']})" for s in srcs),
        *([] if srcs else _outline(result)),
    ]
    return TraceItem("result", title, "\n".join(filter(None, lines)), at, full=result)


def trace_items(steps: list[dict[str, Any]]) -> list[TraceItem]:
    return [item for item in map(_item, steps) if item is not None]


def _render_item(item: TraceItem) -> None:
    with ui.element("div").classes(f"row {'done' if item.kind == 'done' else ''}".strip()):
        ui.label(item.at).classes("time")
        ui.element("span").classes("pin")
        with ui.column().classes("what gap-0"):
            if item.full or (item.detail and item.kind in ("call", "thought")):
                with ui.expansion(item.title).classes("fold w-full"):
                    if item.detail:
                        ui.label(item.detail).classes("muted text-caption").style(
                            "white-space: pre-wrap"
                        )
                    if item.full:
                        _render_full(item.full)
            else:
                ui.label(item.title).classes("text-negative" if item.kind == "error" else "")
                if item.detail:
                    ui.label(item.detail).classes("muted text-caption")


def _render_full(text: str) -> None:
    """The complete tool output, folded, in a scrolling monospace block."""
    with ui.expansion(f"Full output ({len(text):,} characters)").classes("fold w-full"):
        ui.label(text).classes("text-caption").style(
            "white-space: pre-wrap; font-family: monospace; max-height: 24rem; overflow-y: auto"
        )


def render_timeline(title: str, steps: list[dict[str, Any]]) -> None:
    """The section label and one item per shown step; nothing when no step is shown."""
    items = trace_items(steps)
    if not items:
        return
    ui.label(title).classes("section-label")
    with ui.column().classes("wire w-full gap-0"):
        for item in items:
            _render_item(item)
