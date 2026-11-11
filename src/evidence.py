"""Evidence ledger for Deep chat: the sentences of each read original that match the run's
query, with the citation they belong to. Pure — no I/O, no LLM.

`tools.raw_read` feeds every read into the run's ledger; `chat_agent` writes the final
answer from it, so a small model answers from quotes instead of from a long history.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

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
# A soft line wrap of hard-wrapped prose (markdown): one line break inside a sentence,
# not before a heading, list item, table row, numbered paragraph, markup or footer.
_SOFT_WRAP_RE = re.compile(
    r"(?<=[^\s.!?:;])[ \t]*\n(?!\n)(?![ \t]*(?:References:|Map near))"
    r"(?=[ \t]*[^\s#*+|>(\[`{<…\-\d])"
)
# A markdown bullet item; after a line ending in ":" the list is one quote with that line.
_ITEM_RE = re.compile(r"[-*+]\s")
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
_NOT_TEXT = ("[", "…[", "#", "References:", "Map near the matches:", "```", "{{", "<")
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


def _split(para: str) -> list[str]:
    out: list[str] = []
    start = 0
    for m in _BOUNDARY_RE.finditer(para):
        if m.group() != "." or _ends_sentence(para[start : m.start()]):
            out.append(para[start : m.end()])
            start = m.end()
    out.append(para[start:])
    return [s.strip() for s in out if s.strip()]


def _sentences(body: str) -> list[tuple[str, bool]]:
    """(sentence, is a list) of `body`: a list stays with the sentence that introduces it,
    a hard-wrapped sentence is one sentence."""
    out: list[tuple[str, bool]] = []
    in_list = False
    body = body.replace("\r\n", "\n").replace("\r", "\n")  # text copied on Windows
    for para in _SOFT_WRAP_RE.sub(" ", _LIST_BREAK_RE.sub(" ", body)).split("\n"):
        line = para.strip()
        if not line:
            continue
        if _ITEM_RE.match(line) and (in_list or (out and out[-1][0].endswith(":"))):
            out[-1] = (f"{out[-1][0]} {line}", True)
            in_list = True
            continue
        in_list = False
        out += [(s, False) for s in _split(line)]
    return out


def _clip(sentence: str) -> str:
    """`sentence` cut at its last clause before `_MAX_CHARS`, marked " …" (a verbatim
    prefix, so the quote check still finds it)."""
    if len(sentence) <= _MAX_CHARS:
        return sentence
    cut = sentence.rfind(", ", 0, _MAX_CHARS - 2)
    return sentence[: cut if cut > _MIN_CHARS else _MAX_CHARS - 2].rstrip(" ,") + " …"


def _best(body: str, query: set[str], k: int, leads: bool = False) -> list[str]:
    """Up to ``k`` sentences of ``body`` that share enough of the query, in reading order;
    with ``leads`` (a section read as the core) every such sentence, so an exception or a
    deadline does not lose to sentences repeating the rule's words, and also the first
    sentence of the block, of every numbered paragraph ("(3) Maßstab …") and every
    introduced list: a core section states its rules there, whatever words were asked."""
    units = [(_clip(p), is_list) for p, is_list in _sentences(body)]
    lists = {i for i, (_, is_list) in enumerate(units) if is_list}
    scored = [
        (_score(s, query), i, s)
        for i, (s, _) in enumerate(units)
        if len(s) >= _MIN_CHARS and not s.startswith(_NOT_TEXT) and len(_TOC_RE.findall(s)) < 2
    ]
    matching = sorted((x for x in scored if x[0] >= _MIN_SHARED), key=lambda x: (-x[0], x[1]))
    top = matching if leads else matching[:k]
    if leads and scored:
        first = scored[0][1]
        rules = [x for x in scored if x[1] == first or x[1] in lists or _PARA_RE.match(x[2])]
        top += [x for x in rules if x not in top]
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


# --- the ledger as the answer sees it (research_notes/retrieval_deepchat/02 §6.9) --------

Quote = tuple[str, str]
OMIT_MAX = 8  # ledger quotes code adds to one answer
_LABEL_RE = re.compile(r"(§|Anlage)\s*(\d+[a-z]?)(?:\s+Abs\.\s*(\d+[a-z]?))?")
# A figure with its unit, a duration in words, or an exception: what an answer must not drop.
_FIGURE_RE = re.compile(
    r"\b\d+(?:[.,]\d+)?\s*(?:%|Prozent|Monat|Jahr|Woche|Tag|Stunde|Bq|Becquerel|mSv|Millisievert"
    r"|Sv\b|Gy\b|kg\b|Kilogramm|Meter|month|year|week|day|hour)"
    r"|\b(?:ein|zwei|drei|vier|fünf|sechs|sieben|acht|neun|zehn|zwölf|achtzehn|dreißig)\s+"
    r"(?:Monat|Jahr|Woche|Tag|Stunde)",
    re.I,
)
_EXCEPTION_RE = re.compile(
    r"\b(?:abweichend|ausgenommen|es sei denn|gilt nicht|unbeschadet|except|unless|does not apply)",
    re.I,
)


def _label_re(ref: str) -> re.Pattern[str] | None:
    """How a quote names the section `ref` ("A.md § 5 Abs. 2" → "§ 5 Absatz 2")."""
    m = _LABEL_RE.fullmatch(ref.split(" ", 1)[1]) if " " in ref else None
    if m is None:
        return None
    head = r"§\s*" if m[1] == "§" else r"Anlage\s+"
    tail = rf"\s+(?:Abs\.|Absatz)\s*{re.escape(m[3])}\b" if m[3] else ""
    return re.compile(head + re.escape(m[2]) + r"\b" + tail)


def _refers(text: str, by: str, ref: str) -> bool:
    """Whether `text`, quoted from section `by`, refers to section `ref` of the same file."""
    pattern = _label_re(ref)
    same_file = by.split(" ", 1)[0] == ref.split(" ", 1)[0]
    return by != ref and same_file and pattern is not None and pattern.search(text) is not None


def grouped(ledger: Sequence[Quote], levels: Sequence[int]) -> tuple[list[Quote], list[int]]:
    """`ledger` with each section's quotes together, sections by level then first quote, and
    a section a quote refers to ("nach Anlage 8") right after that quote's section, at its
    level: E4B reads a core rule and the list it points to as one."""
    order = list(dict.fromkeys(ref for ref, _ in ledger))
    pairs = list(zip(ledger, levels, strict=True))
    level = {ref: min(lv for (r, _), lv in pairs if r == ref) for ref in order}
    text = {ref: " ".join(s for r, s in ledger if r == ref) for ref in order}
    placed: list[str] = []

    def place(ref: str, at: int) -> None:
        placed.append(ref)
        level[ref] = at if not level[ref] or level[ref] > at else level[ref]
        for child in order:
            if child not in placed and _refers(text[ref], ref, child):
                place(child, level[ref])

    for ref in sorted(order, key=lambda r: (level[r] or len(order) + 9, order.index(r))):
        if ref not in placed:
            place(ref, level[ref])
    out = [(r, s) for ref in placed for r, s in ledger if r == ref]
    return out, [level[r] for r, _ in out]


def pruned(
    ledger: Sequence[Quote], levels: Sequence[int], question: str, required: set[str]
) -> tuple[list[Quote], list[int]]:
    """`ledger` without the quotes off the question: not of level 1 or a `required` section,
    and sharing fewer than two of the question's stems (a figure counting as one). Without a
    core quote or a required section (no levels read) the ledger stays whole."""
    if 1 not in levels and not required:
        return list(ledger), list(levels)
    q = stems(question)
    kept = [
        (x, lv)
        for x, lv in zip(ledger, levels, strict=True)
        if lv == 1 or x[0] in required or _score(x[1], q) >= _MIN_SHARED
    ]
    return [x for x, _ in kept], [lv for _, lv in kept]


def omitted(cited: set[str], ledger: Sequence[Quote]) -> list[Quote]:
    """The quotes of the sections not in `cited` that carry a figure or an exception, or
    that belong to a section a cited quote refers to; at most `OMIT_MAX`."""
    by_cited = [(r, s) for r, s in ledger if r in cited]

    def wanted(ref: str, s: str) -> bool:
        if _FIGURE_RE.search(s) or _EXCEPTION_RE.search(s):
            return True
        return any(_refers(t, by, ref) for by, t in by_cited)

    return [(r, s) for r, s in ledger if r not in cited and wanted(r, s)][:OMIT_MAX]
