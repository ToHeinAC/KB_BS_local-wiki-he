"""Guard: no Broadsheet element carries one of Quasar's breakpoint classes by accident.

Quasar shows an element with class `xs`, `sm`, `md`, `lg` or `xl` only at that screen size (and
`lt-*`/`gt-*` below or above one), so a size modifier named like them hides the element on
every other screen. A `btn sm` once hid every small button on desktop widths.
"""

import re
from pathlib import Path

QUASAR_BREAKPOINTS = {
    "xs", "sm", "md", "lg", "xl",
    "lt-sm", "lt-md", "lt-lg", "lt-xl", "gt-xs", "gt-sm", "gt-md", "gt-lg",
}  # fmt: skip
# Every double-quoted literal: class lists are also built in conditionals and helpers, and a
# whole token `sm`/`md`/… practically never occurs in user-facing text.
_LITERAL_RE = re.compile(r'"([^"\n]*)"')
SRC = Path(__file__).parents[1] / "src"


def breakpoint_classes(source: str) -> list[str]:
    """Tokens of string literals that Quasar reads as a breakpoint class (hidden elsewhere)."""
    return [
        token
        for match in _LITERAL_RE.finditer(source)
        for token in match.group(1).split()
        if token in QUASAR_BREAKPOINTS
    ]


def test_the_detector_finds_breakpoint_classes_also_across_lines() -> None:
    source = 'ui.button("x").classes("btn sm")\nui.label().classes(\n    "headline xl"\n)'
    assert breakpoint_classes(source) == ["sm", "xl"]
    assert breakpoint_classes('b.classes("btn primary" if p else "btn sm")') == ["sm"]
    assert breakpoint_classes('ui.label().classes("q-mt-md small headline m")') == []


def test_no_gui_module_uses_a_quasar_breakpoint_class() -> None:
    hits = {p.name: breakpoint_classes(p.read_text()) for p in sorted(SRC.glob("gui_*.py"))}
    assert {name: found for name, found in hits.items() if found} == {}
