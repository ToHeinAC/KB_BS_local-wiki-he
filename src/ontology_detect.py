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
from dataclasses import dataclass, field
from typing import Any

import ontology
import ontology_bundle
import ontology_query
import ontology_time

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
        if c.deprecated or c.applies_to != "source":
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


def classify_options(schema: ontology.Schema, applies_to: str = "source") -> dict[str, str]:
    """Leaf classes (no narrower class) for documents (or pages), with their one-line
    definitions, for the prompt."""
    parents = {c.broader for c in schema.classes.values() if not c.deprecated}
    return {
        c.id: c.definition
        for c in sorted(schema.classes.values(), key=lambda c: c.id)
        if not c.deprecated and c.id not in parents and c.applies_to == applies_to
    }


def page_class_options(schema: ontology.Schema) -> dict[str, str]:
    """Leaf classes for wiki concept/entity pages (plan Phase 8)."""
    return classify_options(schema, applies_to="page")


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


def review_values(
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
    values, warnings = review_values(source, review, schema)
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


# --- relations between documents (plan Phase 6) ---------------------------------------

RELATION_CHARS = 20000  # where Eingangsformel and transposition clauses appear
MAX_REFERENCES = 25  # standards per document (one proposal per referenced standard)
_MONTH_NUM = ontology_time.MONTHS

_TRANSPOSE_RE = re.compile(
    r"der\s+Umsetzung\s+(?:der|von)\s+(Richtlinie[^.;:]{0,40}?\d{4}/\d{1,4}"
    r"(?:/(?:Euratom|EWG|EU|EG)\b)?)",
    re.IGNORECASE,
)
_EINGANG_RE = re.compile(r"Auf\s+Grund\s+(?:des|der|von)\b[\s\S]{0,1500}?\bverordne[nt]\b")
_REPEAL_RE = re.compile(r"außer\s+Kraft|(?:wird|werden)\s+aufgehoben", re.IGNORECASE)
_STANDARD_RE = re.compile(
    r"\b(DIN|KTA)(?:\s+(EN))?(?:\s+(ISO))?\s+(\d{2,6})(?:(?:-|\s+Teil\s+)(\d{1,3}))?"
    r"(?::(\d{4}(?:-\d{2})?))?"
)
_AUSGABE_RE = re.compile(r"^\s*,?\s*\(?\s*Ausgabe\s+([A-Za-zäöü]+)\s+(\d{4})")
_PRESUMPTION_RE = re.compile(r"gel(?:ten|t)\s+als\s+erfüllt|vermute", re.IGNORECASE)
_MANDATORY_RE = re.compile(
    r"\b(?:einzuhalten|zu\s+beachten|muss|müssen|(?:ist|sind)\s+\w+\s+anzuwenden)\b",
    re.IGNORECASE,
)
_DYNAMIC_RE = re.compile(r"jeweils\s+(?:geltenden|gültigen)\s+Fassung", re.IGNORECASE)


@dataclass(frozen=True)
class RelationFinding:
    rel: str
    target: str  # a work id (possibly not in this database yet)
    evidence: str  # the sentence or clause, verbatim
    status: str  # "confirmed" (formula matched verbatim) | "proposed" (needs review)
    attributes: dict[str, str] = field(default_factory=lambda: {})


_ABBREVIATIONS = ("Nr", "Abs", "Art", "S", "bzw", "vgl", "ggf", "z", "B", "Bek", "BGBl", "Ges")


def _is_stop(text: str, i: int) -> bool:
    """A "." at ``i`` ends a sentence unless it follows a number ("5. Dezember") or a
    common abbreviation ("Nr.", "Abs.", "BGBl. I S.")."""
    word = re.findall(r"(\w+)$", text[max(0, i - 12) : i])
    return not word or not (word[0].isdigit() or word[0] in _ABBREVIATIONS)


def _sentence(text: str, start: int, end: int) -> str:
    left = text.rfind("\n", 0, start) + 1
    for i in range(start - 1, left - 1, -1):
        if text[i] == "." and _is_stop(text, i):
            left = i + 1
            break
    right = text.find("\n", end)
    right = len(text) if right < 0 else right
    stop = next((i for i in range(end, right) if text[i] == "." and _is_stop(text, i)), right)
    return " ".join(text[left : stop + 1].split())[:MAX_QUOTE]


def _named_works(text: str, view: ontology_query.View, self_work: str | None) -> list[str]:
    frame = ontology_query.resolve(text, view)
    return [w for w in frame.works if w != self_work] if frame else []


def _allowed(view: ontology_query.View, rel: str, cls: str | None) -> bool:
    domain = (view.domains or {}).get(rel, ())
    return any(ontology_query.in_class(view, cls, d) for d in domain)


def _transposes(text: str) -> list[RelationFinding]:
    out: list[RelationFinding] = []
    for m in _TRANSPOSE_RE.finditer(text[:RELATION_CHARS]):
        target, _ = _eu_work(m[1])
        if target:
            out.append(
                RelationFinding("transposes", target, _sentence(text, *m.span()), "confirmed")
            )
    return out


def _based_on(text: str, view: ontology_query.View, self_work: str | None) -> list[RelationFinding]:
    m = _EINGANG_RE.search(text[:RELATION_CHARS])
    if m is None:
        return []
    clause = " ".join(m[0].split())
    return [
        RelationFinding("based_on", w, clause[:MAX_QUOTE], "confirmed")
        for w in _named_works(clause, view, self_work)
    ]


def _repeals(text: str, view: ontology_query.View, self_work: str | None) -> list[RelationFinding]:
    out: list[RelationFinding] = []
    for m in _REPEAL_RE.finditer(text):
        sentence = _sentence(text, *m.span())
        out += [
            RelationFinding("repeals", w, sentence, "proposed")
            for w in _named_works(sentence, view, self_work)
        ]
    return out


def _standard(m: re.Match[str], text: str) -> RelationFinding:
    org, en, iso, number, part, edition = m.groups()
    target = "-".join(p for p in (org.lower(), en and "en", iso and "iso", number, part) if p)
    if not edition and (after := _AUSGABE_RE.match(text[m.end() : m.end() + 60])):
        month = _MONTH_NUM.get(after[1].lower())
        edition = f"{after[2]}-{month:02d}" if month else after[2]
    sentence = _sentence(text, *m.span())
    attrs: dict[str, str] = {}
    if edition:
        attrs.update(mode="static", edition=edition)
    elif _DYNAMIC_RE.search(sentence):
        attrs["mode"] = "dynamic"
    if _PRESUMPTION_RE.search(sentence):
        attrs["effect"] = "presumption"
    elif _MANDATORY_RE.search(sentence):
        attrs["effect"] = "mandatory"
    return RelationFinding("incorporates", target, sentence, "proposed", attrs)


def _incorporates(text: str) -> list[RelationFinding]:
    found: dict[str, RelationFinding] = {}
    for m in _STANDARD_RE.finditer(text):
        ref = _standard(m, text)
        found.setdefault(ref.target, ref)
        if len(found) >= MAX_REFERENCES:
            break
    return list(found.values())


def detect_relations(
    text: str, view: ontology_query.View, *, self_work: str | None, cls: str | None
) -> list[RelationFinding]:
    """Relations a document states in its own words (report §7.2): transposition clause and
    Eingangsformel → confirmed; repeals (a named known work) and references to standards →
    proposed. Only relations whose domain covers the document's class, one per target."""
    found = [
        *_transposes(text),
        *_based_on(text, view, self_work),
        *_repeals(text, view, self_work),
        *_incorporates(text),
    ]
    unique: dict[tuple[str, str], RelationFinding] = {}
    for f in found:
        if _allowed(view, f.rel, cls):
            unique.setdefault((f.rel, f.target), f)
    return list(unique.values())


def relation_rows(subject: str, findings: list[RelationFinding]) -> list[dict[str, Any]]:
    """Ledger rows for relation findings (code is the actor; proposals need review)."""
    return [
        ontology.assertion(
            subject,
            f.rel,
            f.target,
            by="rule",
            status=f.status,
            evidence=f.evidence,
            attributes=f.attributes or None,
        )
        for f in findings
    ]


def standard_id(text: str) -> str | None:
    """The work id of the first standard named in ``text`` ("DIN 6812" → "din-6812")."""
    m = _STANDARD_RE.search(text)
    return _standard(m, text).target if m else None
