"""Acronyms and the user's own glosses in a query — pure, no I/O.

`acronyms()` finds capitalised words ("NORM", "DE") in a mixed-case query: the lexical
arm matches them only where a text writes them in capitals too, so "NORM" no longer hits
every "Norm" (standard). `find()` pairs an acronym with the explanation the user wrote
next to it — "NORM (natürliche Radioaktivität)" or "natürliche Radioaktivität (NORM)" —
so search and briefing can use the user's meaning instead of guessing it.
See docs/retrieval.md §Query vocabulary.
"""

from __future__ import annotations

import re

MIN_ACRONYM = 2
MAX_GLOSS_WORDS = 6
MAX_BEFORE_WORDS = 4

_WORD_RE = re.compile(r"\w+")
_AFTER_RE = re.compile(r"(?<!\w)(\w+)\s*\(([^()\n]{3,80})\)")
_BEFORE_RE = re.compile(r"((?:[^\W\d_][\w-]*\s+){0,8}[^\W\d_][\w-]*)\s*\((\w+)\)")
# Function words never start or extend an explanation taken from before the brackets.
_FUNCTION_WORDS = {
    "der", "die", "das", "des", "dem", "den", "ein", "eine", "einer", "eines", "von", "und",
    "oder", "in", "im", "für", "mit", "bei", "zur", "zum", "wie", "was", "the", "of", "and",
    "or", "for", "with", "a", "an", "to", "how", "what",
}  # fmt: skip


def is_acronym(word: str) -> bool:
    """A word written in capitals only (letters, at least MIN_ACRONYM of them)."""
    return len(word) >= MIN_ACRONYM and word.isalpha() and word.isupper()


def acronyms(text: str) -> list[str]:
    """Capitalised words of ``text``, in order and unique; [] for an all-caps text, where
    capitals carry no meaning."""
    if not any(c.islower() for c in text):
        return []
    return list(dict.fromkeys(w for w in _WORD_RE.findall(text) if is_acronym(w)))


def _explanation(text: str) -> bool:
    """Words that can explain an acronym: lowercase letters, no digits or § marks."""
    words = _WORD_RE.findall(text)
    return (
        0 < len(words) <= MAX_GLOSS_WORDS
        and any(c.islower() for c in text)
        and not any(c.isdigit() or c == "§" for c in text)
    )


def _initials(words: list[str], acronym: str) -> list[str] | None:
    """The trailing words whose initials spell the acronym ("Naturally Occurring …")."""
    tail = words[-len(acronym) :]
    if len(tail) == len(acronym) and "".join(w[0] for w in tail).upper() == acronym:
        return tail
    return None


def _noun_phrase(words: list[str]) -> list[str]:
    """The last word and the lowercase adjectives right before it ("natürliche …")."""
    out = [words[-1]]
    for w in reversed(words[:-1]):
        if len(out) >= MAX_BEFORE_WORDS or not w[0].islower() or w.lower() in _FUNCTION_WORDS:
            break
        out.insert(0, w)
    return out


def _before(phrase: str, acronym: str) -> str | None:
    words = phrase.split()
    picked = _initials(words, acronym) or _noun_phrase(words)
    text = " ".join(picked)
    return text if _explanation(text) and picked[-1].lower() not in _FUNCTION_WORDS else None


def find(text: str) -> list[tuple[str, str]]:
    """(acronym, explanation) pairs the text states, in order and unique."""
    pairs: list[tuple[str, str]] = []
    for m in _AFTER_RE.finditer(text):
        if is_acronym(m[1]) and _explanation(m[2]):
            pairs.append((m[1], m[2].strip()))
    for m in _BEFORE_RE.finditer(text):
        explained = _before(m[1], m[2]) if is_acronym(m[2]) else None
        if explained:
            pairs.append((m[2], explained))
    return list(dict.fromkeys(pairs))


def mentions(text: str, acronym: str) -> bool:
    """``text`` contains ``acronym`` as a word, in capitals."""
    return re.search(rf"(?<!\w){re.escape(acronym)}(?!\w)", text) is not None
