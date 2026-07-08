"""Deterministic DE/EN language detection + directive selection (Layer 1).

No external NLP deps: a marker-count heuristic tuned for the project's German
(legal) + English domains, robust down to short chat queries. Detection stays in
code (small-model-safe, per project rules); the directive WORDING lives in
prompts.py. Callers pin the answer/summary language by injecting the returned
directive into their prompt (see wiki_engine, agent, chat_agent).
"""

from __future__ import annotations

import re

from prompts import INGEST_LANGUAGE_DIRECTIVE, RESPONSE_LANGUAGE_DIRECTIVE

_TOKEN_RE = re.compile(r"[a-zäöüß]+")

# High-signal function words per language, word-boundary matched (so they work
# on short queries where raw substring counting is unreliable).
_DE_WORDS = frozenset(
    "der die das und oder ist sind ein eine einen einem einer für mit von nicht "
    "auch wie was welche welcher welches wann warum wird werden muss darf kann bei "
    "zum zur dem den des auf im nach über unter gibt sich".split()
)
_EN_WORDS = frozenset(
    "the and or is are a an of to for with from not also how what which when why "
    "will would be must may can at in on after over under this that does has have".split()
)


def detect(text: str, default: str = "de") -> str:
    """Return 'de' or 'en' for ``text``.

    Any umlaut/ß decisively marks German. Otherwise the language with more
    function-word hits wins; a tie or no signal falls back to ``default``
    (German — the corpus language, and the drift direction users hit most).
    """
    sample = (text or "")[:4000].lower()
    tokens = _TOKEN_RE.findall(sample)
    de = sum(t in _DE_WORDS for t in tokens)
    en = sum(t in _EN_WORDS for t in tokens)
    if any(c in sample for c in "äöüß"):
        de += 2
    if de == en:
        return default
    return "de" if de > en else "en"


def response_directive(text: str, default: str = "de") -> str:
    """Answer-language directive matched to ``text`` (query/answer/agent paths)."""
    return RESPONSE_LANGUAGE_DIRECTIVE[detect(text, default)]


def ingest_directive(text: str, default: str = "de") -> str:
    """Page-language directive matched to the source ``text`` (ingest path)."""
    return INGEST_LANGUAGE_DIRECTIVE[detect(text, default)]
