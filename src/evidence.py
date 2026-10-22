"""Evidence ledger for Deep chat: the sentences of each read original that match the run's
query, with the citation they belong to. Pure — no I/O, no LLM.

`tools.raw_read` feeds every read into the run's ledger; `chat_agent` writes the final
answer from it, so a small model answers from quotes instead of from a long history.
"""

from __future__ import annotations

import re

PER_BLOCK = 4  # sentences kept per read section or window
_MIN_CHARS, _MAX_CHARS = 40, 600
_MIN_SHARED = 2  # query stems a sentence must share (a figure counts as one)
_STEM = 6  # prefix length: "Rückstände"/"Rückständen" share "rückst"

# `## Raw file: <file>[ <section>][ (bytes a-b of n)]` opens each block of a raw_read output.
_HEADER_RE = re.compile(r"^## Raw file: (.+?)(?: \((?:bytes|offset) [^)]*\))?[ \t]*$", re.M)
_TEIL_RE = re.compile(r"\s*\(Teil \d+\)$")
_SENTENCE_RE = re.compile(r"(?<=[.;!?])\s+|\n+")
_WORD_RE = re.compile(r"\w{4,}")
# Lines raw_read adds around the text: memory stubs, hints, reference footers, section maps.
_NOT_TEXT = ("[", "…[", "#", "References:", "Map near the matches:")
_STOP = frozenset(
    {
        "auch",
        "beim",
        "dass",
        "diese",
        "dieser",
        "dieses",
        "durch",
        "eine",
        "einem",
        "einen",
        "einer",
        "eines",
        "kann",
        "können",
        "nach",
        "nicht",
        "oder",
        "sich",
        "sind",
        "sowie",
        "unter",
        "wenn",
        "werden",
        "wird",
        "wurde",
        "über",
        "with",
        "that",
        "this",
        "from",
        "have",
        "which",
        "their",
        "there",
        "were",
        "been",
        "will",
        "shall",
        "must",
        "also",
        "into",
        "than",
    }
)


def stems(text: str) -> set[str]:
    """The content-word stems of ``text``."""
    words = (w.casefold() for w in _WORD_RE.findall(text))
    return {w[:_STEM] for w in words if w not in _STOP}


def _score(sentence: str, query: set[str]) -> int:
    shared = len(stems(sentence) & query)
    return shared + (1 if shared and re.search(r"\d", sentence) else 0)


def _best(body: str, query: set[str], k: int) -> list[str]:
    """Up to ``k`` sentences of ``body`` that share enough of the query, in reading order."""
    scored = [
        (_score(s, query), i, s)
        for i, s in enumerate(p.strip() for p in _SENTENCE_RE.split(body))
        if _MIN_CHARS <= len(s) <= _MAX_CHARS and not s.startswith(_NOT_TEXT)
    ]
    top = sorted((x for x in scored if x[0] >= _MIN_SHARED), key=lambda x: (-x[0], x[1]))[:k]
    return [s for _, _, s in sorted(top, key=lambda x: x[1])]


def extract(read_output: str, query: str, k: int = PER_BLOCK) -> list[tuple[str, str]]:
    """(citation ref, sentence) pairs from one raw_read output: per `## Raw file:` block, the
    sentences sharing the most query stems. A section map's own header block is skipped."""
    q = stems(query)
    heads = list(_HEADER_RE.finditer(read_output))
    out: list[tuple[str, str]] = []
    for i, h in enumerate(heads):
        label = h.group(1).strip()
        if "section map" in label:
            continue
        end = heads[i + 1].start() if i + 1 < len(heads) else len(read_output)
        ref = _TEIL_RE.sub("", label)
        out += [(ref, s) for s in _best(read_output[h.end() : end], q, k)]
    return out


def render(ledger: list[tuple[str, str]]) -> str:
    """The ledger as numbered quotes, each with the citation tag to copy."""
    return "\n".join(f'[{i}] [Source: {ref}] "{s}"' for i, (ref, s) in enumerate(ledger, 1))
