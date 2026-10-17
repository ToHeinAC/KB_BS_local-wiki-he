"""References inside an original ("nach § 12 der VerordnungB"), resolved to files. Pure.

`find_refs` finds `§ N` / `§§ N bis M` / `Anlage N` / `Artikel N` mentions, reads the work
named right after them ("des Atomgesetzes", "der StrlSchV", "AtG") and resolves it with the
caller's `resolve` (work name → file in scope). A mention without a work name points into
the same file. A work that resolves to nothing but looks like a law is `out_of_scope`; any
other trailing noun ("der Behörde") is ignored. Anchors are checked with `has_anchor`, so a
missing § is flagged, never guessed. See ideas/deep-chat-read-memory-and-section-grounding.md
§9 and docs/retrieval.md §Reference footers.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass

SAME, CROSS, OUT = "same", "cross", "out_of_scope"
MAX_REFS = 8  # per text, in order of first mention
MAX_RANGE = 5  # sections expanded from one "§§ N bis M"

_REF_RE = re.compile(
    r"(?P<kind>§§?|Anlagen?\b|Artikel\b|Art\.)\s*(?P<a>\d+[a-z]?)\b"
    r"(?:\s*(?P<sep>bis|und|,|-|–)\s*(?P<b>\d+[a-z]?)\b)?"
    r"(?:\s+(?:Abs(?:atz|\.)|Satz|S\.|Nr\.|Nummer|Buchst(?:abe|\.))\s*\d+[a-z]?\b)*"
)
_WORK_RE = re.compile(
    r"\s*,?\s*(?:(?:des|der|dem|den|nach|im|gemäß)\s+(?P<w>[A-ZÄÖÜ][\w\-]*)"
    r"|(?P<abbr>[A-ZÄÖÜ][a-zäöüß]*[A-ZÄÖÜ][\w\-]*))"
)
_LAWLIKE_RE = re.compile(
    r"(?:gesetz|verordnung|ordnung|richtlinie|abkommen|übereinkommen|vertrag|satzung)"
    r"(?:es|s|en)?$",
    re.IGNORECASE,
)
_ABBR_RE = re.compile(r"^[A-ZÄÖÜ][A-Za-zäöüß]{0,8}[A-ZÄÖÜ][A-Za-zäöüß]{0,4}$")


def _kind(word: str) -> str:
    """The anchor prefix of a matched mention: "§§" → "§", "Anlagen" → "Anlage",
    "Art." → "Artikel" (every spelling `_REF_RE` accepts)."""
    return "§" if word.startswith("§") else "Anlage" if word.startswith("Anl") else "Artikel"


@dataclass(frozen=True)
class Ref:
    anchor: str  # "§ 12", "Anlage 3", "Artikel 5"
    work: str  # the work name as written; "" for a reference into the same file
    target: str | None  # the file it points to; None when out of scope
    kind: str  # SAME | CROSS | OUT
    found: bool = True  # the anchor exists in `target`


def _numbers(a: str, sep: str | None, b: str | None) -> list[str]:
    """The section numbers of one mention: a range expanded (capped), a pair, or one."""
    if not b:
        return [a]
    if sep in ("und", ","):
        return [a, b]
    if a.isdigit() and b.isdigit() and int(a) < int(b):
        return [str(n) for n in range(int(a), min(int(b), int(a) + MAX_RANGE - 1) + 1)]
    return [a, b]


def is_lawlike(name: str) -> bool:
    """A name that reads as a law or regulation ("Atomgesetzes", "StrlSchV", "AtG")."""
    return bool(_LAWLIKE_RE.search(name) or _ABBR_RE.match(name))


def _work_after(text: str, end: int) -> str:
    m = _WORK_RE.match(text, end)
    return (m["w"] or m["abbr"]) if m else ""


def _target(
    name: str, self_file: str, resolve: Callable[[str], str | None]
) -> tuple[str, str | None, str]:
    """(work as written, target file, kind). A name that resolves to nothing and does not
    read as a law is plain prose, so the mention points into the same file."""
    file = resolve(name) if name else None
    if file is not None:
        return name, file, SAME if file == self_file else CROSS
    if name and is_lawlike(name):
        return name, None, OUT
    return "", self_file, SAME


def find_refs(
    text: str,
    self_file: str,
    self_anchor: str | None,
    resolve: Callable[[str], str | None],
    has_anchor: Callable[[str, str], bool],
) -> list[Ref]:
    """References in ``text`` (read from ``self_file``, section ``self_anchor``), deduplicated,
    in order of first mention, at most MAX_REFS."""
    out: dict[tuple[str, str], Ref] = {}
    for m in _REF_RE.finditer(text):
        work, target, kind = _target(_work_after(text, m.end()), self_file, resolve)
        for num in _numbers(m["a"], m["sep"], m["b"]):
            anchor = f"{_kind(m['kind'])} {num}"
            if kind == SAME and anchor == self_anchor:
                continue
            found = target is None or has_anchor(target, anchor)
            out.setdefault((target or work, anchor), Ref(anchor, work, target, kind, found))
            if len(out) >= MAX_REFS:
                return list(out.values())
    return list(out.values())
