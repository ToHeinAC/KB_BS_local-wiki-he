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

# A document's own sections: "Kapitel 3", "Abschnitt 5", "Abs. 5" (numbered headings).
DOC_KINDS = ("Kapitel", "Abschnitt", "Absatz")
_REF_RE = re.compile(
    r"(?P<kind>§§?|Anlagen?\b|Artikel\b|Art\.|Kapitel\b|Kap\.|Abschnitte?\b|Abschn\."
    r"|Absatz\b|Abs\.)\s*(?P<a>\d+(?:\.\d+)*[a-z]?)\b"
    r"(?:\s*(?P<sep>bis|und|,|-|–)\s*(?P<b>\d+(?:\.\d+)*[a-z]?)\b)?"
    r"(?:\s+(?:Abs(?:atz|\.)|Satz|S\.|Nr\.|Nummer|Buchst(?:abe|\.))\s*\d+[a-z]?\b)*"
)
# A work after a mention: "der StrlSchV", "des Berichts ABC", "AtG", or a document type
# followed by its name ("Bericht ABC", "Dokument CDE").
_WORK_RE = re.compile(
    r"\s*,?\s*(?:(?:des|der|dem|den|nach|im|gemäß)\s+"
    r"(?P<w>[A-ZÄÖÜ][\w\-]*(?:\s+[A-ZÄÖÜ0-9][A-ZÄÖÜ0-9\-]*\b)?)"
    r"|(?P<abbr>[A-ZÄÖÜ][a-zäöüß]*[A-ZÄÖÜ][\w\-]*)"
    r"|(?P<doc>[A-ZÄÖÜ][a-zäöüß]+\s+[A-ZÄÖÜ0-9][A-ZÄÖÜ0-9\-]*\b))"
)
_LAWLIKE_RE = re.compile(
    r"(?:gesetz|verordnung|ordnung|richtlinie|abkommen|übereinkommen|vertrag|satzung)"
    r"(?:es|s|en)?$",
    re.IGNORECASE,
)
_GENITIVE_RE = re.compile(r"(gesetz|abkommen|vertrag)(?:es|s)$", re.IGNORECASE)
_ABBR_RE = re.compile(r"^[A-ZÄÖÜ][A-Za-zäöüß]{0,8}[A-ZÄÖÜ][A-Za-zäöüß]{0,4}$")


def _kind(word: str) -> str:
    """The anchor prefix of a matched mention: "§§" → "§", "Anlagen" → "Anlage",
    "Art." → "Artikel", "Kap." → "Kapitel", "Abschn." → "Abschnitt", "Abs." → "Absatz"
    (every spelling `_REF_RE` accepts)."""
    for prefix, kind in (("§", "§"), ("Anl", "Anlage"), ("Art", "Artikel"), ("Kap", "Kapitel")):
        if word.startswith(prefix):
            return kind
    return "Abschnitt" if word.startswith("Abschn") else "Absatz"


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
    return (m["w"] or m["abbr"] or m["doc"]) if m else ""


def _target(
    name: str, self_file: str, resolve: Callable[[str], str | None]
) -> tuple[str, str | None, str]:
    """(work as written, target file, kind). A two-word name ("Bericht ABC") resolves as a
    whole or by its identifier ("ABC"). A name that resolves to nothing and does not read as
    a law is plain prose, so the mention points into the same file."""
    last = name.split()[-1] if " " in name else ""
    tries = (
        [name, last]
        if last and (_ABBR_RE.match(last) or any(c.isdigit() for c in last))
        else [name]
    )
    file = next((f for f in map(resolve, tries) if f), None) if name else None
    if file is not None:
        return name, file, SAME if file == self_file else CROSS
    if name and any(is_lawlike(n) for n in tries):
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
        prefix = _kind(m["kind"])
        if prefix == "Absatz" and kind == SAME:
            continue  # "Absatz 2" in a law is part of the § it stands in
        for num in _numbers(m["a"], m["sep"], m["b"]):
            anchor = f"{prefix} {num}"
            if kind == SAME and anchor == self_anchor:
                continue
            found = target is None or has_anchor(target, anchor)
            out.setdefault((target or work, anchor), Ref(anchor, work, target, kind, found))
            if len(out) >= MAX_REFS:
                return list(out.values())
    return list(out.values())


def nominative(work: str) -> str:
    """A law's name as a heading gives it: the genitive of the text dropped
    ("Atomgesetzes" → "Atomgesetz")."""
    return _GENITIVE_RE.sub(r"\1", work)
