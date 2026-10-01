"""Numbered citations for the Broadsheet answer view.

Answers carry inline `[Source: file §x]` / `[Wiki: page.md]` tags. The reading view shows a
numeral (`<sup class="cite">`) in the text and a matching note in the margin column, so the
prose stays quiet. Pure text logic: no UI imports.
"""

import re
from collections.abc import Callable
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


def _number(text: str, mark: Callable[[Note], str]) -> tuple[str, list[Note]]:
    """Replace each citation tag with `mark(note)`; a note is numbered at its first appearance
    and the same document and section reuse it."""
    notes: dict[tuple[str, str, str], Note] = {}

    def numeral(match: re.Match[str]) -> str:
        ref = match.group(2)
        if not ref:
            return match.group(0)
        file, section = _split(ref)
        kind = "web" if not section and file.lower().startswith("http") else match.group(1).lower()
        note = notes.setdefault((kind, file, section), Note(len(notes) + 1, kind, file, section))
        return mark(note)

    return _TAG_RE.sub(numeral, text), list(notes.values())


def number_citations(text: str) -> tuple[str, list[Note]]:
    """Replace each citation tag with a numeral; return the new text and the notes."""
    return _number(text, lambda note: f'<sup class="cite" data-n="{note.n}">{note.n}</sup>')


def answer_markdown(question: str, text: str, meta: str) -> str:
    """A standalone Markdown file of an answer: citations become footnotes listed under Sources."""
    body, notes = _number(text, lambda note: f"[^{note.n}]")
    body = re.sub(r"\s+(\[\^\d+\])", r"\1", body)
    out = f"# {question}\n\n_{meta}_\n\n{body.strip()}\n"
    if notes:
        lines = [f"[^{n.n}]: {n.label}{' (wiki page)' if n.kind == 'wiki' else ''}" for n in notes]
        out += "\n## Sources\n\n" + "\n".join(lines) + "\n"
    return out


def export_name(question: str) -> str:
    """A file name for the export: the question, lower-cased and hyphenated."""
    slug = re.sub(r"[^\w]+", "-", question.lower()).strip("-_")[:60].strip("-_")
    return f"{slug or 'answer'}.md"


def uncited(notes: list[Note], refs: list[str]) -> list[str]:
    """The sources an answer used (`refs`) that no inline tag points at."""
    cited = {n.file for n in notes}
    return [r for r in refs if ui_logic.CHUNK_SUFFIX_RE.sub("", r).strip() not in cited]
