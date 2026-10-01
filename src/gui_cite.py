"""Numbered citations for the Broadsheet answer view.

Answers carry inline `[Source: file §x]` / `[Wiki: page.md]` tags. The reading view shows a
numeral (`<sup class="cite">`) in the text and a matching note in the margin column, so the
prose stays quiet. One bracket may name several sources (`[Source: a.md; Source: b.md]`), and
Markdown escapes in names (`JEN\\_KOINNO.md`) are undone. LaTeX the model writes is turned into
MathML (`render_math`). Pure text logic: no UI imports.
"""

import re
from collections.abc import Callable
from dataclasses import dataclass

from latex2mathml.converter import convert as latex_to_mathml

import ui_logic

_TAG_RE = re.compile(r"\[(Source|Wiki):\s*([^\]]*?)\s*\]")
_SECTION_RE = re.compile(r"^(.*?)\s*([§#].*)$")
# Several sources in one bracket: split on `;`, or on `,` only before another `Source:`/`Wiki:`
# (a comma inside a file name stays).
_PART_SPLIT_RE = re.compile(r"\s*;\s*|\s*,\s*(?=(?:Source|Wiki):)")
_PREFIX_RE = re.compile(r"^(Source|Wiki):\s*")
_ESCAPE_RE = re.compile(r"\\([\\`*_{}\[\]()#+\-.!|~])")
_CODE_RE = re.compile(r"(```.*?```|`[^`\n]*`)", re.S)
_MATH_RE = re.compile(
    r"\$\$(.+?)\$\$|\\\[(.+?)\\\]|\\\((.+?)\\\)|\$(?!\s)([^$\n]+?)(?<!\s)\$", re.S
)
_LATEX_HINT_RE = re.compile(r"\\[A-Za-z]+|[\^_{}]")  # `$5 and $10` has none: it stays text


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


def _parts(word: str, body: str) -> list[tuple[str, str]]:
    """(tag word, ref) for each source one bracket names, escapes undone."""
    parts: list[tuple[str, str]] = []
    for raw in _PART_SPLIT_RE.split(body):
        found = _PREFIX_RE.match(raw.strip())
        ref = raw.strip()[found.end() :] if found else raw.strip()
        ref = _ESCAPE_RE.sub(r"\1", ref).strip()
        if ref:
            parts.append((found.group(1) if found else word, ref))
    return parts


def _number(text: str, mark: Callable[[Note], str], sep: str = "") -> tuple[str, list[Note]]:
    """Replace each citation tag with `mark(note)` per source it names, joined by `sep`; a note
    is numbered at its first appearance and the same document and section reuse it."""
    notes: dict[tuple[str, str, str], Note] = {}

    def numeral(match: re.Match[str]) -> str:
        parts = _parts(match.group(1), match.group(2))
        if not parts:
            return match.group(0)
        marks: list[str] = []
        for word, ref in parts:
            file, section = _split(ref)
            kind = "web" if not section and file.lower().startswith("http") else word.lower()
            note = notes.setdefault(
                (kind, file, section), Note(len(notes) + 1, kind, file, section)
            )
            marks.append(mark(note))
        return sep.join(dict.fromkeys(marks))

    return _TAG_RE.sub(numeral, text), list(notes.values())


def number_citations(text: str) -> tuple[str, list[Note]]:
    """Replace each citation tag with a numeral; return the new text and the notes."""
    return _number(
        text,
        lambda note: f'<sup class="cite" data-n="{note.n}">{note.n}</sup>',
        '<sup class="cite-sep">,</sup>',
    )


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


def _mathml(match: re.Match[str]) -> str:
    block = match.group(1) or match.group(2)
    latex = block or match.group(3) or match.group(4)
    if not _LATEX_HINT_RE.search(latex):
        return match.group(0)
    try:
        return latex_to_mathml(latex.strip(), display="block" if block else "inline")
    except Exception:  # any malformed formula: show what the model wrote rather than nothing
        return match.group(0)


def render_math(text: str) -> str:
    """LaTeX in `$…$`, `$$…$$`, `\\(…\\)`, `\\[…\\]` as MathML; code spans and blocks untouched."""
    pieces = _CODE_RE.split(text)
    return "".join(p if i % 2 else _MATH_RE.sub(_mathml, p) for i, p in enumerate(pieces))
