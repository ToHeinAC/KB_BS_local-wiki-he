"""Deterministic DE/EN language detection + directive selection (Layer 1).

No external NLP deps: a marker-count heuristic tuned for the project's German
(legal) + English domains, robust down to short chat queries. Detection stays in
code (small-model-safe, per project rules); the directive WORDING lives in
prompts.py. Callers pin the answer/summary language by injecting the returned
directive into their prompt (see wiki_engine, agent, chat_agent).
"""

from __future__ import annotations

import re

from prompts import ABSTAIN_MESSAGE, INGEST_LANGUAGE_DIRECTIVE, RESPONSE_LANGUAGE_DIRECTIVE

_TOKEN_RE = re.compile(r"[a-zäöüß]+")

# High-signal function words per language, word-boundary matched (so they work
# on short queries where raw substring counting is unreliable).
_DE_WORDS = frozenset(
    ["der", "die", "das", "und", "oder", "ist", "sind", "ein", "eine", "einen", "einem", "einer", "für", "mit", "von", "nicht", "auch", "wie", "was", "welche", "welcher", "welches", "wann", "warum", "wird", "werden", "muss", "darf", "kann", "bei", "zum", "zur", "dem", "den", "des", "auf", "im", "nach", "über", "unter", "gibt", "sich"]
)
_EN_WORDS = frozenset(
    ["the", "and", "or", "is", "are", "a", "an", "of", "to", "for", "with", "from", "not", "also", "how", "what", "which", "when", "why", "will", "would", "be", "must", "may", "can", "at", "in", "on", "after", "over", "under", "this", "that", "does", "has", "have"]
)


_WINDOW = 4000


def _sample(text: str) -> str:
    """Start + middle + end windows, so an abstract in another language can't decide."""
    if len(text) <= 3 * _WINDOW:
        return text
    mid = len(text) // 2
    return " ".join(
        (text[:_WINDOW], text[mid - _WINDOW // 2 : mid + _WINDOW // 2], text[-_WINDOW:])
    )


def detect(text: str, default: str = "de") -> str:
    """Return 'de' or 'en' for ``text``.

    The language with more function-word hits wins. An umlaut/ß only breaks a
    tie (terse queries like "Rückstände Grenzwert?") — never outvotes English
    function words, so a German name in an English sentence can't flip it. No
    signal at all falls back to ``default`` (German — the corpus language).
    """
    sample = _sample(text or "").lower()
    tokens = _TOKEN_RE.findall(sample)
    de = sum(t in _DE_WORDS for t in tokens)
    en = sum(t in _EN_WORDS for t in tokens)
    if de == en:
        return "de" if any(c in sample for c in "äöüß") else default
    return "de" if de > en else "en"


def response_directive(text: str, default: str = "de") -> str:
    """Answer-language directive matched to ``text`` (query/answer/agent paths)."""
    return RESPONSE_LANGUAGE_DIRECTIVE[detect(text, default)]


def ingest_directive(text: str, default: str = "de") -> str:
    """Page-language directive matched to the source ``text`` (ingest path)."""
    return INGEST_LANGUAGE_DIRECTIVE[detect(text, default)]


def abstain_message(query: str, db: str, page: str, score: float, default: str = "de") -> str:
    """Stage E abstention text in the query's language (see prompts.ABSTAIN_MESSAGE)."""
    return ABSTAIN_MESSAGE[detect(query, default)].format(db=db, page=page, score=score)
