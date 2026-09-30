"""Numbered citations for the Broadsheet answer view.

Answers carry inline `[Source: file §x]` / `[Wiki: page.md]` tags. The reading view shows a
numeral (`<sup class="cite">`) in the text and a matching note in the margin column, so the
prose stays quiet. Pure text logic: no UI imports.
"""

import re
from dataclasses import dataclass

import ui_logic

_TAG_RE = re.compile(r"\[(Source|Wiki):\s*([^\]]*?)\s*\]")
_SECTION_RE = re.compile(r"^(.*?)\s*([§#].*)$")


@dataclass(frozen=True)
class Note:
    """One margin note. `ref` is what opens the document; `section` is `§6.1` / `#intro`."""

    n: int
    kind: str  # "source" (original document), "wiki" (wiki page) or "web" (URL)
    file: str
    section: str

    @property
    def ref(self) -> str:
        return self.file

    @property
    def label(self) -> str:
        return f"{self.file} {self.section}".strip()


def _split(ref: str) -> tuple[str, str]:
    """`file`, `section` of a cited ref; URLs keep their `#fragment`."""
    if ref.lower().startswith(("http://", "https://")):
        return ref, ""
    found = _SECTION_RE.match(ref)
    return (found.group(1), found.group(2)) if found else (ref, "")


def number_citations(text: str) -> tuple[str, list[Note]]:
    """Replace each citation tag with a numeral; return the new text and the notes.

    A note is numbered at its first appearance; the same document and section reuse it.
    """
    notes: dict[tuple[str, str, str], Note] = {}

    def numeral(match: re.Match[str]) -> str:
        ref = match.group(2)
        if not ref:
            return match.group(0)
        file, section = _split(ref)
        kind = "web" if not section and file.lower().startswith("http") else match.group(1).lower()
        note = notes.setdefault((kind, file, section), Note(len(notes) + 1, kind, file, section))
        return f'<sup class="cite" data-n="{note.n}">{note.n}</sup>'

    return _TAG_RE.sub(numeral, text), list(notes.values())


def uncited(notes: list[Note], refs: list[str]) -> list[str]:
    """The sources an answer used (`refs`) that no inline tag points at."""
    cited = {n.file for n in notes}
    return [r for r in refs if ui_logic.CHUNK_SUFFIX_RE.sub("", r).strip() not in cited]
