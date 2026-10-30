"""Evidence ledger for Deep chat: the sentences of each read original that match the run's
query, with the citation they belong to. Pure — no I/O, no LLM.

`tools.raw_read` feeds every read into the run's ledger; `chat_agent` writes the final
answer from it, so a small model answers from quotes instead of from a long history.
"""

from __future__ import annotations

import re

PER_BLOCK = 4  # sentences kept per read section or window
_MIN_CHARS, _MAX_CHARS = 40, 900
_MIN_SHARED = 2  # query stems a sentence must share (a figure counts as one)
_STEM = 6  # prefix length: "Rückstände"/"Rückständen" share "rückst"

# `## Raw file: <file>[ <section>][ (bytes a-b of n)]` opens each block of a raw_read output.
_HEADER_RE = re.compile(r"^## Raw file: (.+?)(?: \((?:bytes|offset) [^)]*\))?[ \t]*$", re.M)
_TEIL_RE = re.compile(r"\s*\(Teil \d+\)$")
_PARA_RE = re.compile(r"\(\d+[a-z]?\)\s")  # a numbered paragraph's opening "(3) "
# A line break inside one sentence: after an enumeration number ("1.", "a)") or a list
# item that goes on (",", "und", "oder"), as German legal texts lay out their lists.
_LIST_BREAK_RE = re.compile(
    r"(?:(?<=[\s(]\d\.)|(?<=[\s(]\d\d\.)|(?<=^\d\.)|(?<=\s[a-z]\))|(?<=,)"
    r"|(?<=\bund)|(?<=\boder))[ \t]*\n+[ \t]*(?!References:|Map near|\[|…\[|#)",
    re.M,
)
_BOUNDARY_RE = re.compile(r"[.;!?](?=\s)")
_LAST_WORD_RE = re.compile(r"(\S+)$")
# Words a period follows without ending the sentence ("Abs. 2", "BGBl. I S. 2833").
_ABBREV = frozenset(
    {"abs", "nr", "art", "anl", "buchst", "kap", "abschn", "bgbl", "vgl", "ggf", "bzw"}
    | {"ca", "inkl", "gem", "lit", "s", "z", "b", "u", "a", "i", "v", "m", "d", "h"}
)
# A table-of-contents line: several "· § N …" entries.
_TOC_RE = re.compile(r"·\s*(?:§|Anlage|Artikel)")
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


# Question and modal words a search query does without (the stems' stopwords as well).
_QUESTION_WORDS = frozenset(
    {"welche", "welcher", "welches", "welchem", "welchen", "wann", "warum", "wieso", "gilt"}
    | {"gelten", "gibt", "dürfen", "darf", "müssen", "muss", "sollen", "soll", "what"}
    | {"which", "when", "does", "apply", "applies", "should"}
    | {"ihre", "ihrem", "ihren", "ihrer", "ihres", "seine", "seinem", "seinen", "seiner"}
)
_TERM_RE = re.compile(r"\w[\w\-]{3,}")


def key_terms(text: str) -> str:
    """The content words of a question, in order, as a search query: no question, modal or
    function words ("Welcher Grenzwert gilt für die Bevölkerung?" → "Grenzwert
    Bevölkerung")."""
    seen: set[str] = set()
    out: list[str] = []
    for w in _TERM_RE.findall(text):
        k = w.casefold()
        if k not in _STOP and k not in _QUESTION_WORDS and k not in seen:
            seen.add(k)
            out.append(w)
    return " ".join(out)


# German inflection changes the vowel ("entlassen" → "entlässt"), so stems fold umlauts.
_FOLD = str.maketrans({"ä": "a", "ö": "o", "ü": "u", "ß": "ss"})


def stems(text: str) -> set[str]:
    """The content-word stems of ``text``, umlauts folded."""
    words = (w.casefold() for w in _WORD_RE.findall(text))
    return {w.translate(_FOLD)[:_STEM] for w in words if w not in _STOP}


def _score(sentence: str, query: set[str]) -> int:
    shared = len(stems(sentence) & query)
    return shared + (1 if shared and re.search(r"\d", sentence) else 0)


def _ends_sentence(before: str) -> bool:
    """Whether a period after `before` ends a sentence: not after a day or list number
    ("24. Juli", "1.") or a legal abbreviation ("Abs.", "BGBl.")."""
    m = _LAST_WORD_RE.search(before)
    word = m.group(1).lstrip("(").casefold() if m else ""
    return not (re.fullmatch(r"\d{1,2}", word) or word in _ABBREV)


def _sentences(body: str) -> list[str]:
    """The sentences of `body`; a list stays with the sentence that introduces it."""
    out: list[str] = []
    for para in _LIST_BREAK_RE.sub(" ", body).split("\n"):
        start = 0
        for m in _BOUNDARY_RE.finditer(para):
            if m.group() != "." or _ends_sentence(para[start : m.start()]):
                out.append(para[start : m.end()])
                start = m.end()
        out.append(para[start:])
    return [s.strip() for s in out if s.strip()]


def _clip(sentence: str) -> str:
    """`sentence` cut at its last clause before `_MAX_CHARS`, marked " …" (a verbatim
    prefix, so the quote check still finds it)."""
    if len(sentence) <= _MAX_CHARS:
        return sentence
    cut = sentence.rfind(", ", 0, _MAX_CHARS - 2)
    return sentence[: cut if cut > _MIN_CHARS else _MAX_CHARS - 2].rstrip(" ,") + " …"


def _best(body: str, query: set[str], k: int, leads: bool = False) -> list[str]:
    """Up to ``k`` sentences of ``body`` that share enough of the query, in reading order;
    with ``leads``, also the first sentence of the block and of every numbered paragraph
    ("(3) Maßstab …"): a section read as the core states its rules there, whatever words
    the question used."""
    scored = [
        (_score(s, query), i, s)
        for i, s in enumerate(_clip(p) for p in _sentences(body))
        if len(s) >= _MIN_CHARS and not s.startswith(_NOT_TEXT) and len(_TOC_RE.findall(s)) < 2
    ]
    top = sorted((x for x in scored if x[0] >= _MIN_SHARED), key=lambda x: (-x[0], x[1]))[:k]
    if leads and scored:
        first = scored[0][1]
        top += [x for x in scored if (x[1] == first or _PARA_RE.match(x[2])) and x not in top]
    return [s for _, _, s in sorted(top, key=lambda x: x[1])]


def extract(
    read_output: str, query: str, k: int = PER_BLOCK, leads: bool = False
) -> list[tuple[str, str]]:
    """(citation ref, sentence) pairs from one raw_read output: per `## Raw file:` block, the
    sentences sharing the most query stems (and with ``leads`` each paragraph's first
    sentence). A section map's own header block is skipped."""
    q = stems(query)
    heads = list(_HEADER_RE.finditer(read_output))
    out: list[tuple[str, str]] = []
    for i, h in enumerate(heads):
        label = h.group(1).strip()
        if "section map" in label:
            continue
        end = heads[i + 1].start() if i + 1 < len(heads) else len(read_output)
        ref = _TEIL_RE.sub("", label)
        out += [(ref, s) for s in _best(read_output[h.end() : end], q, k, leads)]
    return out


def render(
    ledger: list[tuple[str, str]],
    levels: list[int] | None = None,
    headers: dict[int, str] | None = None,
) -> str:
    """The ledger as numbered quotes, each with the citation tag to copy; with ``levels``
    (one per quote, 0 = not read as a level) grouped under ``headers``, level 1 first."""
    if not levels or not headers:
        return "\n".join(f'[{i}] [Source: {ref}] "{s}"' for i, (ref, s) in enumerate(ledger, 1))
    order = sorted(range(len(ledger)), key=lambda i: (levels[i] or len(headers) + 1, i))
    lines: list[str] = []
    for n, i in enumerate(order, 1):
        header = headers.get(levels[i], headers.get(0, ""))
        if header and header not in lines:
            lines += ["", header] if lines else [header]
        ref, s = ledger[i]
        lines.append(f'[{n}] [Source: {ref}] "{s}"')
    return "\n".join(lines)
