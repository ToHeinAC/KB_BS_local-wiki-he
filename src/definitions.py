"""Defined terms of a law ("(32) Rückstände: Materialien, die …"), found and matched. Pure.

`register` reads every definition of a markdown law: a numbered paragraph `(N) Begriff: …`
in a section whose heading says "Begriff…", or `(N) Begriff ist/sind die …` where the
heading says "Begriff…" or starts with the term. `used_in` finds the defined terms a text
uses, in any inflection ("Rückständen", "Einzelpersonen der Bevölkerung"), so Deep chat can
read the definitions behind a core section in code (ideas/deep-chat-levels.md).
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass

from chunker import legal_heads

_HEADING_RE = re.compile(r"^#{1,4}\s", re.M)
_PARA_RE = re.compile(r"^\((\d+[a-z]?)\)[ \t]*", re.M)
# "(N) Begriff: …" — at most six words before the colon.
_COLON_RE = re.compile(r"^([A-ZÄÖÜ][^:\n.;()]{1,80}?):\s")
_COLON_MAX_WORDS = 6
# "(N) Begriff [(…)] [im Sinne dieses Gesetzes] ist/sind die …": not a duty ("Dem Antrag
# sind …") — no leading article or preposition, and an article or a list must follow.
_IS_RE = re.compile(
    r"^((?!(?:Die|Der|Das|Dem|Den|Des|Ein|Eine|Bei|Im|In|Zur|Zum|Für|Nach|Vor|Auf|Aus)\s)"
    r"[A-ZÄÖÜ][\w\-]*(?:\s+[\w\-]+){0,3}?)"
    r"(?:\s*\([^)\n]*\))?(?:\s+im Sinne (?:dieses|dieser) \w+)?\s+(?:ist|sind)\s+(\S+)"
)
_IS_FOLLOW = {"die", "der", "das", "ein", "eine", "einer", "jede", "jeder", "alle"}
# "§ 5 Abs. 32", "§5 (32)", "§ 5 Absatz 32".
_PARA_REF_RE = re.compile(r"^§\s*(\d+[a-z]?)\s*(?:Abs\.|Absatz|\()\s*(\d+[a-z]?)\)?\s*$")
_WORD_RE = re.compile(r"[^\W\d_][\w\-]*")
_FOLD = str.maketrans({"ä": "a", "ö": "o", "ü": "u", "ß": "ss"})
_INFLECTION = 3  # letters an inflected or plural form may add or change at the end


@dataclass(frozen=True)
class Definition:
    term: str  # "Rückstände"
    anchor: str  # "§ 5"
    number: str  # "32"
    text: str  # the paragraph, verbatim: "(32) Rückstände: Materialien, …"

    @property
    def section(self) -> str:
        return f"{self.anchor} Abs. {self.number}"


def _fold(word: str) -> str:
    return word.casefold().translate(_FOLD)


def _words(text: str) -> list[str]:
    return [_fold(w) for w in _WORD_RE.findall(text)]


def _term(paragraph: str, heading: str) -> str | None:
    """The term `paragraph` defines under `heading`, or None."""
    begriff = "begriff" in heading.casefold()
    m = _COLON_RE.match(paragraph)
    if begriff and m and len(m[1].split()) <= _COLON_MAX_WORDS:
        return m[1].strip()
    m = _IS_RE.match(paragraph)
    if not m or not (m[2].casefold() in _IS_FOLLOW or re.fullmatch(r"\d+\.", m[2]) or begriff):
        return None
    head, first = _words(m[1])[-1], (_words(heading) or [""])[0]
    return m[1] if begriff or head[:6] == first[:6] else None


def parse(anchor: str, heading: str, body: str) -> list[Definition]:
    """The definitions in one section's `body` (the text below its heading)."""
    parts = _PARA_RE.split(body)
    out: list[Definition] = []
    for number, paragraph in zip(parts[1::2], parts[2::2], strict=True):
        term = _term(paragraph, heading)
        if term:
            out.append(Definition(term, anchor, number, f"({number}) {paragraph.strip()}"))
    return out


def register(text: str) -> list[Definition]:
    """Every definition of a markdown law, in document order."""
    out: list[Definition] = []
    heads = legal_heads(text)  # the § headings, as the chunker splits the law
    for i, m in enumerate(heads):
        end = heads[i + 1].start() if i + 1 < len(heads) else len(text)
        nxt = _HEADING_RE.search(text, m.end(), end)
        body = text[m.end() : nxt.start() if nxt else end]
        out += parse(f"§ {m[2]}", m[3].strip(), body)
    return out


def is_paragraph_ref(ref: str) -> bool:
    """Whether `ref` names one paragraph of a section ("§ 5 Abs. 32", "§ 5 (32)")."""
    return bool(_PARA_REF_RE.match(ref.strip()))


def find(defs: Iterable[Definition], ref: str) -> Definition | None:
    """The definition a paragraph reference names ("§ 5 Abs. 32"), or None."""
    m = _PARA_REF_RE.match(ref.strip())
    if not m:
        return None
    return next((d for d in defs if d.anchor == f"§ {m[1]}" and d.number == m[2]), None)


def _same_word(term: str, word: str) -> bool:
    """`word` is `term` inflected: same stem, at most a few letters longer."""
    if len(term) <= 3:
        return word == term
    common = 0
    for a, b in zip(term, word, strict=False):
        if a != b:
            break
        common += 1
    return common >= max(4, len(term) - _INFLECTION) and len(word) <= len(term) + _INFLECTION


def _hits(term: list[str], words: list[str]) -> list[int]:
    n = len(term)
    return [
        i
        for i in range(len(words) - n + 1)
        if all(_same_word(t, w) for t, w in zip(term, words[i : i + n], strict=True))
    ]


def used_in(text: str, defs: Iterable[Definition], query: str = "") -> list[Definition]:
    """The defined terms `text` uses: those the query names first, then the most used,
    then in order of first use."""
    words, asked = _words(text), _words(query)
    ranked: list[tuple[bool, int, int, Definition]] = []
    for d in defs:
        term = _words(d.term)
        hits = _hits(term, words) if term else []
        if hits:
            named = any(_same_word(t, q) for t in term for q in asked)
            ranked.append((not named, -len(hits), hits[0], d))
    ranked.sort(key=lambda r: r[:3])
    return [d for *_, d in ranked]
