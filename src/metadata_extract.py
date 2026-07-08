"""Deterministic effective-date detection from document text (no LLM).

Recovers the one metadata field with algorithmic weight (`effective as of`,
consumed by `wiki_engine._is_newer`) so multi-file ingest needs no per-file form.
Regex-only, German/legal vintage cues; returns the `YYYY-MM-DD` shape that
`wiki_engine._parse_date` accepts, or ``None`` when nothing matches (the upload
review table lets the user fill or correct it).
"""

import re
from datetime import date

_HEAD_CHARS = 4000  # vintage signals live in the document head

_MONTHS = {
    "januar": 1, "februar": 2, "märz": 3, "maerz": 3, "april": 4, "mai": 5,
    "juni": 6, "juli": 7, "august": 8, "september": 9, "oktober": 10,
    "november": 11, "dezember": 12,
}

# High → low priority. A cue must be followed (within ~40 chars) by a date.
_CUES = [
    r"in\s+kraft\s+getreten",
    r"in\s+kraft\s+(?:am|ab|treten)",
    r"g[üu]ltig\s+ab",
    r"g[üu]ltig\s+seit",
    r"fassung\s+vom",
    r"\bstand\b",
    r"ausfertigungsdatum",
    r"\bvom\b",
]

_DMY = re.compile(r"(\d{1,2})\.\s*(\d{1,2})\.\s*(\d{4})")           # 01.01.2024
_DMONTHY = re.compile(r"(\d{1,2})\.\s*([A-Za-zÄÖÜäöü]+)\s+(\d{4})")  # 1. Januar 2024
_ISO = re.compile(r"(\d{4})-(\d{2})-(\d{2})")                        # 2024-01-01


def _norm(day: int, month: int, year: int) -> str | None:
    try:
        return date(year, month, day).isoformat()
    except ValueError:
        return None


def _match_date(segment: str) -> str | None:
    """First date in `segment` as ISO `YYYY-MM-DD`, tried DMY → DMonthY → ISO."""
    m = _DMY.search(segment)
    if m:
        return _norm(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    m = _DMONTHY.search(segment)
    if m:
        month = _MONTHS.get(m.group(2).lower())
        if month:
            return _norm(int(m.group(1)), month, int(m.group(3)))
    m = _ISO.search(segment)
    if m:
        return _norm(int(m.group(3)), int(m.group(2)), int(m.group(1)))
    return None


def extract_effective_date(text: str) -> str | None:
    """Best-effort `effective as of` (ISO date) from a document's own text."""
    if not text:
        return None
    head = text[:_HEAD_CHARS]
    low = head.lower()
    for cue in _CUES:
        for m in re.finditer(cue, low):
            found = _match_date(head[m.end():m.end() + 40])
            if found:
                return found
    return _match_date(head)  # bare-date fallback anywhere in the head
