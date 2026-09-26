"""Time in the ontology (plan Phase 5): time intent of a question, validity of versions.

Pure, no LLM. Valid time is derived from facts at query time, never stored twice:
- a *work* (a law as such) may carry `in_force_from` / `in_force_until`;
- each *version* (a raw source filed under a work) holds from its `version_date` until
  the next version's `version_date` within the same work, bounded by the work's interval.
  A source's own `in_force_until` overrides the upper bound.
`validity()` answers "valid" / "superseded" / "not-yet" / "unknown" for a date; unknown
never demotes anything (fail open). `time_intent()` finds the point in time a question
asks about, in code (like `lang.py`): explicit dates, a year after a cue word
("im Jahr 2017", "Stand 2019", "vor 2018"), or words such as "damals" / "alte Fassung"
(a past without a date). Bare years are ignored, so "Richtlinie 2013/59/Euratom" is not
a date. See docs/ontology.md §Time.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ontology_query import View

VALID, SUPERSEDED, NOT_YET, UNKNOWN = "valid", "superseded", "not-yet", "unknown"
LABELS = {VALID: "in force", SUPERSEDED: "superseded", NOT_YET: "not yet in force"}

MONTHS = {
    m: i
    for i, m in enumerate(
        [
            "januar",
            "februar",
            "märz",
            "april",
            "mai",
            "juni",
            "juli",
            "august",
            "september",
            "oktober",
            "november",
            "dezember",
        ],
        1,
    )
}
_ISO_RE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
_DMY_RE = re.compile(r"\b(\d{1,2})\.(\d{1,2})\.(\d{4})\b")
_DMONTH_RE = re.compile(rf"\b(\d{{1,2}})\.\s*({'|'.join(MONTHS)})\s+(\d{{4}})\b", re.IGNORECASE)
_YEAR_CUE_RE = re.compile(
    r"\b(im\s+jahre?|jahr|in|bis|ab|seit|nach|vor|stand|as\s+of|year|until|since|after|before)"
    r"\s+((?:19|20)\d{2})\b(?![/.\d-])",
    re.IGNORECASE,
)
_PAST_RE = re.compile(
    r"\b(damals|(?:alte|früher|vorherig|ursprünglich)[a-z]*\s+fassung|vor\s+der\s+novelle|"
    r"old\s+version|previous\s+version|former\s+version|at\s+the\s+time)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class TimeIntent:
    as_of: date
    explicit: bool  # a date or year was named
    past: bool  # the question asks about the past (named date or "damals", "alte Fassung")


def _date(y: str | int, m: str | int, d: str | int) -> date | None:
    try:
        return date(int(y), int(m), int(d))
    except ValueError:
        return None


def _named_date(q: str) -> date | None:
    for rx, order in ((_ISO_RE, (1, 2, 3)), (_DMY_RE, (3, 2, 1))):
        m = rx.search(q)
        if m and (found := _date(m[order[0]], m[order[1]], m[order[2]])):
            return found
    m = _DMONTH_RE.search(q)
    if m:
        return _date(m[3], MONTHS[m[2].lower()], m[1])
    m = _YEAR_CUE_RE.search(q)
    if m:
        year = int(m[2]) - (1 if m[1].lower() in ("vor", "before") else 0)
        return date(year, 12, 31)
    return None


def time_intent(q: str, today: date) -> TimeIntent:
    """The point in time ``q`` asks about (today when it names none)."""
    named = _named_date(q)
    as_of = named or today
    return TimeIntent(as_of, named is not None, as_of < today or bool(_PAST_RE.search(q)))


def parse(value: object) -> date | None:
    if not isinstance(value, str):
        return None
    m = _ISO_RE.fullmatch(value.strip())
    return _date(m[1], m[2], m[3]) if m else None


# --- validity ------------------------------------------------------------------------


def _interval(view: View, source: str) -> tuple[date | None, date | None]:
    """[start, end) of a version; None bounds are open; (None, None) means unknown."""
    facts = view.sources.get(source, {})
    work = view.works.get(str(facts.get("work") or ""))
    if work is None:
        return None, None
    start = parse(facts.get("version_date")) or parse(work.get("in_force_from"))
    end = parse(work.get("in_force_until"))
    dated = [s for s in work["sources"] if parse(view.sources[s].get("version_date"))]
    newer = [
        d
        for s in dated
        if (d := parse(view.sources[s].get("version_date"))) and start and d > start
    ]
    if newer:
        end = min([*newer, end] if end else newer)
    end = parse(facts.get("in_force_until")) or end
    return start, end


def validity(view: View, source: str, as_of: date) -> str:
    """Whether the version ``source`` holds at ``as_of``."""
    start, end = _interval(view, source)
    if start is None and end is None:
        return UNKNOWN
    if start is not None and as_of < start:
        return NOT_YET
    if end is not None and as_of >= end:
        return SUPERSEDED
    return VALID


def current_expression(view: View, work: str, as_of: date) -> str | None:
    """The version of ``work`` in force at ``as_of`` (None when no version holds)."""
    sources: list[str] = view.works.get(work, {}).get("sources", [])
    return next((s for s in sources if validity(view, s, as_of) == VALID), None)


def work_in_force(view: View, work: str, as_of: date) -> bool:
    return current_expression(view, work, as_of) is not None


def outdated_pages(view: View, as_of: date) -> list[str]:
    """Wiki pages whose dated sources are all superseded at ``as_of``."""
    by_page: dict[str, list[str]] = {}
    for source, pages in view.pages.items():
        for page in pages:
            by_page.setdefault(page, []).append(validity(view, source, as_of))
    return sorted(
        page
        for page, states in by_page.items()
        if SUPERSEDED in states and all(s in (SUPERSEDED, UNKNOWN) for s in states)
    )


def validity_order(hits: list[dict[str, Any]], view: View, as_of: date) -> list[dict[str, Any]]:
    """Demote (never drop) hits from versions not in force at ``as_of``; stable."""
    keep = [h for h in hits if validity(view, h["source"], as_of) in (VALID, UNKNOWN)]
    later = [h for h in hits if validity(view, h["source"], as_of) not in (VALID, UNKNOWN)]
    return keep + later
