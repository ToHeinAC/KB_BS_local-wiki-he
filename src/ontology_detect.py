"""Deterministic ontology detection on a document's head, and verification of LLM proposals.

Pure. `detect()` reads only the first `HEAD_CHARS` characters:
- **Class:** every cue (regex) of every non-deprecated class is tried; the match that
  *ends* first wins, ties go to the deeper (more specific) class, then the lower rank.
  Title-line cues are anchored at `^` and greedy, so "ends first" is what separates
  "Allgemeine Verwaltungsvorschrift zum …gesetz" (admin regulation) from a statute.
- **Work** (only for legal instruments): German law from the title's "(Name - ABBR)" or
  a standalone abbreviation line plus the year of the Ausfertigungsdatum; EU acts from
  "Richtlinie/Verordnung … YYYY/N". The id is `de-<abbr>-<year>` / `eu-dir-…` / `eu-reg-…`.
An LLM may only *propose* a class, and only with a quote that occurs verbatim in the head
(`parse_proposal`); anything else is discarded. See docs/ontology.md §Detection.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

import ontology
import ontology_bundle

HEAD_CHARS = 4000
LEGAL_ROOT = "legal-instrument"
MIN_QUOTE = 12
MAX_QUOTE = 300
MAX_EVIDENCE = 200

_TITLE_ABBR_RE = re.compile(r"\(([^()\n]{3,120}?)\s+-\s+([^()\s]{2,20})\)")
_TITLE_NAME_RE = re.compile(r"\(([^()\n\s]{4,60})\)\s*$")
_ABBR_LINE_RE = re.compile(r"^\s*([A-ZÄÖÜ][A-Za-zÄÖÜäöü0-9-]{0,19})\s*$", re.MULTILINE)
_AUSF_RE = re.compile(r"Ausfertigungsdatum:\s*\d{1,2}\.\d{1,2}\.(\d{4})")
_MONTHS = "Januar|Februar|März|April|Mai|Juni|Juli|August|September|Oktober|November|Dezember"
_VOM_RE = re.compile(rf"\bvom\s+\d{{1,2}}\.\s*(?:{_MONTHS})\s+(\d{{4}})")
_EU_RE = re.compile(
    r"\b(richtlinie|verordnung|directive|regulation)\s+(?:\((eu|eg|ewg|euratom)\)\s+)?"
    r"(?:nr\.\s*)?(\d{4})/(\d{1,4})(?:/(eu|eg|ewg|euratom))?\b",
    re.IGNORECASE,
)
_ORG = {"eu": "EU", "eg": "EG", "ewg": "EWG", "euratom": "Euratom"}
_UMLAUTS = str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss"})
_JSON_RE = re.compile(r"\{.*?\}", re.DOTALL)


@dataclass(frozen=True)
class Detection:
    class_id: str | None = None
    evidence: str = ""  # the line the class cue matched
    work: str | None = None
    aliases: tuple[str, ...] = ()


def _line_at(text: str, pos: int) -> str:
    start = text.rfind("\n", 0, pos) + 1
    end = text.find("\n", pos)
    return text[start : end if end >= 0 else len(text)].strip()[:MAX_EVIDENCE]


def _depth(schema: ontology.Schema, cid: str) -> int:
    depth, cur = 0, schema.classes[cid].broader
    while cur and cur in schema.classes:
        depth, cur = depth + 1, schema.classes[cur].broader
    return depth


def is_a(schema: ontology.Schema, cid: str, ancestor: str) -> bool:
    cur: str | None = cid
    while cur and cur in schema.classes:
        if cur == ancestor:
            return True
        cur = schema.classes[cur].broader
    return False


def _best_class(head: str, schema: ontology.Schema) -> tuple[str, int] | None:
    """(class id, match start) of the winning cue, or None."""
    best: tuple[int, int, int, str, int] | None = None
    for c in schema.classes.values():
        if c.deprecated:
            continue
        for cue in c.cues:
            m = re.search(cue, head)
            if m is None:
                continue
            key = (m.end(), -_depth(schema, c.id), c.rank or 99, c.id, m.start())
            best = key if best is None or key < best else best
    return (best[3], best[4]) if best else None


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower().translate(_UMLAUTS)).strip("-")


def _german_work(head: str) -> tuple[str | None, tuple[str, ...]]:
    title = next((ln.strip() for ln in head.splitlines() if ln.strip()), "")
    names: list[str] = []
    m = _TITLE_ABBR_RE.search(title)
    if m:
        names = [m[2], m[1].strip()]
    else:
        named = _TITLE_NAME_RE.search(title)
        line = _ABBR_LINE_RE.search("\n".join(head.splitlines()[1:6]))
        names = [n for n in (line[1] if line else None, named[1] if named else None) if n]
    year = _AUSF_RE.search(head) or _VOM_RE.search(head[:600])
    if not names or not year:
        return None, ()
    return f"de-{_slug(names[0])}-{year[1]}", tuple(names)


def _eu_work(head: str) -> tuple[str | None, tuple[str, ...]]:
    m = _EU_RE.search(head[:600])
    if m is None:
        return None, ()
    kind, org_before, year, num, org_after = m.groups()
    org = (org_before or org_after or "eu").lower()
    if kind.lower() in ("richtlinie", "directive"):
        return f"eu-dir-{year}-{num}-{org}", (f"Richtlinie {year}/{num}/{_ORG[org]}",)
    return f"eu-reg-{year}-{num}", (f"Verordnung ({_ORG[org]}) {year}/{num}",)


def detect(text: str, schema: ontology.Schema) -> Detection:
    """Class (by cue) and, for legal instruments, Work id + aliases of a document."""
    head = text[:HEAD_CHARS]
    found = _best_class(head, schema)
    if found is None:
        return Detection()
    cid, pos = found
    work, aliases = None, ()
    if is_a(schema, cid, LEGAL_ROOT):
        work, aliases = _eu_work(head) if cid.startswith("eu-") else _german_work(head)
    return Detection(cid, _line_at(head, pos), work, aliases)


# --- LLM proposals -------------------------------------------------------------------


def classify_options(schema: ontology.Schema) -> dict[str, str]:
    """Leaf classes (no narrower class) with their one-line definitions, for the prompt."""
    parents = {c.broader for c in schema.classes.values() if not c.deprecated}
    return {
        c.id: c.definition
        for c in sorted(schema.classes.values(), key=lambda c: c.id)
        if not c.deprecated and c.id not in parents
    }


def _norm(text: str) -> str:
    return " ".join(text.split())


def parse_proposal(answer: str, head: str, allowed: set[str]) -> tuple[str, str] | None:
    """(class, quote) from the model's JSON when the class is allowed and the quote occurs
    verbatim (whitespace-normalised) in ``head``; None otherwise — never a guess."""
    for blob in _JSON_RE.findall(answer):
        try:
            data = json.loads(blob)
        except json.JSONDecodeError:
            continue
        if not isinstance(data, dict):
            continue
        cls, quote = data.get("class"), data.get("quote")  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
        if not (isinstance(cls, str) and isinstance(quote, str)) or cls not in allowed:
            return None
        norm = _norm(quote)
        if MIN_QUOTE <= len(norm) <= MAX_QUOTE and norm in _norm(head):
            return cls, quote
        return None
    return None


# --- upload review → ledger rows ---------------------------------------------------


def detected_dict(found: Detection, version_date: str) -> dict[str, Any]:
    """What the upload review table was prefilled with (kept in session state)."""
    return {
        "class": found.class_id or "",
        "work": found.work or "",
        "aliases": list(found.aliases),
        "evidence": found.evidence,
        "version_date": version_date,
    }


def _review_values(
    source: str, review: dict[str, str], schema: ontology.Schema
) -> tuple[dict[str, str], list[str]]:
    """The review's class / work / version_date, blanked (with a warning) when invalid."""
    values = {k: (review.get(k) or "").strip() for k in ("class", "work", "version_date")}
    warnings: list[str] = []
    cls = schema.classes.get(values["class"])
    if values["class"] and (cls is None or cls.deprecated):
        warnings.append(f"{source}: unknown class {values['class']!r} ignored")
        values["class"] = ""
    if values["work"] and not ontology_bundle.WORK_ID_RE.match(values["work"]):
        warnings.append(f"{source}: work id {values['work']!r} ignored (lowercase, no spaces)")
        values["work"] = ""
    if values["version_date"] and not ontology_bundle.is_date(values["version_date"]):
        warnings.append(f"{source}: date {values['version_date']!r} ignored (YYYY-MM-DD)")
        values["version_date"] = ""
    return values, warnings


def upload_rows(
    source: str,
    review: dict[str, str],
    detected: dict[str, Any],
    schema: ontology.Schema,
    *,
    user: str,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Ledger rows for one uploaded source: a value equal to what code detected is a
    `rule` fact (with the matched line as evidence), a corrected one a `user` fact."""
    values, warnings = _review_values(source, review, schema)
    by = {k: "rule" if v == detected.get(k) else "user" for k, v in values.items()}

    def row(subject: str, pred: str, obj: str, actor: str) -> dict[str, Any]:
        evidence = str(detected.get("evidence") or "") if actor == "rule" else "upload review"
        user_name = user if actor == "user" else None
        return ontology.assertion(subject, pred, obj, by=actor, user=user_name, evidence=evidence)

    rows = [row(f"src:{source}", k, v, by[k]) for k, v in values.items() if v]
    work = values["work"]
    if work and values["class"]:
        rows.append(row(f"work:{work}", "class", values["class"], by["class"]))
    if work and by["work"] == "rule":
        rows += [
            row(f"work:{work}", "aliases", a, "rule")
            for a in ontology_bundle.as_list(detected.get("aliases"))
        ]
    return rows, warnings
