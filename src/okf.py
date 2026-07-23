"""Open Knowledge Format (OKF v0.1) conformance helpers.

Deterministic, model-independent stamping + validation so each per-DB `wiki/`
folder is a conformant OKF Knowledge Bundle. No LLM is involved — every OKF
field/section here is derived in code, so a small local model (gemma 4b) can
never break conformance. See docs/okf.md for the OKF<->project mapping.

This module never imports wiki_engine (wiki_engine imports it) and holds no
prompt strings (project rule 5.3).
"""

from __future__ import annotations

import re
from collections import OrderedDict
from pathlib import Path

import frontmatter

OKF_VERSION = "0.1"

# Reserved / non-concept filenames — exempt from the `type` requirement.
_NON_CONCEPT = ("index.md", "log.md", "DESCRIPTION.md")

_CITATIONS_HEADING = "## Citations"
_KEY_FACTS_HEADING = "## Key facts"
_DESC_MAX = 160

_INLINE_CITE_RE = re.compile(r"\[[^\]]*\]")          # strip [source.md] inline cites
_SLUG_RE = re.compile(r"[^a-z0-9]+")
_URL_RE = re.compile(r"^https?://", re.IGNORECASE)
_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
# Legacy log heading: "## 2026-06-24 14:03 — Ingest: foo" (space or T before time).
_LEGACY_LOG_RE = re.compile(r"^##\s+(\d{4}-\d{2}-\d{2})[ T](\d{2}:\d{2})\s+[—-]\s+(.*)$")


def _slug(name: str) -> str:
    return _SLUG_RE.sub("-", str(name).lower()).strip("-")


def _as_list(value) -> list[str]:
    if not value:
        return []
    if not isinstance(value, list):
        value = [value]
    return [str(v).strip() for v in value if str(v).strip()]


# --- Description -------------------------------------------------------------

def _key_facts_bullets(body: str) -> list[str]:
    out, capturing = [], False
    for line in body.splitlines():
        s = line.strip()
        if s.lower().startswith(_KEY_FACTS_HEADING.lower()):
            capturing = True
            continue
        if capturing:
            if s.startswith("## "):
                break
            if s.startswith(("- ", "* ")):
                out.append(s[2:].strip())
    return out


def _first_prose_sentence(body: str) -> str:
    for line in body.splitlines():
        s = line.strip()
        if not s or s.startswith(("#", "-", "*", "|", ">")):
            continue
        return re.split(r"(?<=[.!?])\s", s, maxsplit=1)[0]
    return ""


def _derive_description(body: str) -> str:
    facts = _key_facts_bullets(body)
    cand = facts[0] if facts else _first_prose_sentence(body)
    cand = _INLINE_CITE_RE.sub("", cand)
    cand = re.sub(r"\s+", " ", cand).strip(" .;,")
    if len(cand) > _DESC_MAX:
        cand = cand[:_DESC_MAX].rsplit(" ", 1)[0].rstrip() + "…"
    return cand


# --- Frontmatter enrichment --------------------------------------------------

def _derive_tags(meta: dict, db: str, ptype: str) -> list[str]:
    """Coarse, deterministic categories (no LLM): db + page type + `part of`."""
    tags: list[str] = []
    for t in (_slug(db), ptype):
        if t and t not in tags:
            tags.append(t)
    part_of = meta.get("part of") or meta.get("part_of")
    if part_of:
        s = _slug(part_of)
        if s and s not in tags:
            tags.append(s)
    return tags


def _derive_resource(meta: dict, ptype: str) -> str | None:
    """A URI for the underlying asset — source-summary / report only."""
    if ptype not in ("source-summary", "report"):
        return None
    sources = _as_list(meta.get("sources"))
    if not sources:
        return None
    first = sources[0]
    return first if _URL_RE.match(first) else f"raw/{first}"


def _iso_timestamp(value) -> str | None:
    if not value:
        return None
    s = str(value)[:10]
    return f"{s}T00:00:00Z" if _ISO_DATE_RE.match(s) else None


def enrich_frontmatter(meta: dict, body: str, *, db: str) -> dict:
    """Add OKF-recommended fields (description/tags/resource/timestamp).

    Idempotent and additive: keeps an existing non-empty `description`; never
    touches load-bearing keys (sources/related/key_terms/confidence/...).
    """
    m = dict(meta)
    ptype = str(m.get("type") or "concept").strip().lower()
    if not str(m.get("type") or "").strip():
        m["type"] = ptype  # OKF's one hard rule: a non-empty type on every page

    if not str(m.get("description") or "").strip():
        desc = _derive_description(body)
        if desc:
            m["description"] = desc

    m["tags"] = _derive_tags(m, db, ptype)

    res = _derive_resource(m, ptype)
    if res:
        m["resource"] = res

    ts = _iso_timestamp(m.get("updated") or m.get("created"))
    if ts:
        m["timestamp"] = ts
    return m


# --- Citations ---------------------------------------------------------------

def render_citations(sources) -> str:
    """Numbered `## Citations` block from a sources list; '' when empty."""
    items = _as_list(sources)
    if not items:
        return ""
    lines = [_CITATIONS_HEADING, ""] + [f"{i}. {s}" for i, s in enumerate(items, 1)]
    return "\n".join(lines) + "\n"


def _strip_citations(body: str) -> str:
    """Remove a trailing auto-generated `## Citations` section (idempotency)."""
    out, skip = [], False
    for line in body.splitlines():
        if line.strip().lower() == _CITATIONS_HEADING.lower():
            skip = True
            continue
        if skip and line.startswith("## "):
            skip = False
        if not skip:
            out.append(line)
    return "\n".join(out).rstrip()


def apply_to_page(content: str, *, db: str) -> str:
    """Stamp OKF frontmatter + regenerate the `## Citations` section. Idempotent."""
    try:
        post = frontmatter.loads(content)
    except Exception:
        return content
    post.metadata = enrich_frontmatter(post.metadata, post.content, db=db)
    body = _strip_citations(post.content)
    cites = render_citations(post.metadata.get("sources"))
    if cites:
        body = body.rstrip() + "\n\n" + cites
    post.content = body if body.endswith("\n") else body + "\n"
    return frontmatter.dumps(post) + "\n"


# --- Duplicate-section cleanup ----------------------------------------------

_H2_RE = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)


def collapse_duplicate_sections(body: str) -> tuple[str, int]:
    """Collapse consecutive level-2 sections sharing a heading, keeping the
    content-bearing one. Returns (new_body, sections_removed).

    Targets a small-model ingest artifact where a page emits e.g. `## Key facts`
    twice — once as an outline, once as real content. Deterministic: among a run of
    adjacent same-name `##` sections it keeps the one with the most body text (ties
    keep the first) and drops the rest. Non-consecutive repeats, subsection levels,
    and all other content are left untouched.
    """
    heads = list(_H2_RE.finditer(body))
    if len(heads) < 2:
        return body, 0
    preamble = body[: heads[0].start()]
    sections: list[tuple[str, str, int]] = []  # (name, full_text, body_len)
    for i, m in enumerate(heads):
        end = heads[i + 1].start() if i + 1 < len(heads) else len(body)
        text = body[m.start():end]
        body_len = len(text[m.end() - m.start():].strip())
        sections.append((m.group(1).strip().lower(), text, body_len))

    kept: list[str] = []
    removed = 0
    i = 0
    while i < len(sections):
        j = i
        while j + 1 < len(sections) and sections[j + 1][0] == sections[i][0]:
            j += 1
        run = sections[i:j + 1]
        best = max(range(len(run)), key=lambda k: run[k][2])
        kept.append(run[best][1])
        removed += len(run) - 1
        i = j + 1
    return preamble + "".join(kept), removed


# --- Reserved files: log -----------------------------------------------------

def add_log_entry(text: str, action: str, detail: str, *, day: str, time: str) -> str:
    """Insert a log entry newest-first under a `## YYYY-MM-DD` date section."""
    post = frontmatter.loads(text) if text.lstrip().startswith("---") \
        else frontmatter.Post(text or "# Log\n")
    post.metadata.setdefault("title", "Activity Log")

    bullet = f"- {time} — {action}"
    if detail:
        bullet += ": " + " ".join(detail.split())

    lines = (post.content.rstrip("\n") or "# Log").split("\n")
    heading = f"## {day}"
    if heading in lines:
        lines.insert(lines.index(heading) + 1, bullet)
    else:
        insert_at = next((i for i, ln in enumerate(lines) if ln.startswith("## ")),
                         len(lines))
        block = [heading, bullet, ""]
        if insert_at and lines[insert_at - 1].strip():
            block = [""] + block
        lines[insert_at:insert_at] = block

    post.content = "\n".join(lines).rstrip("\n") + "\n"
    return frontmatter.dumps(post) + "\n"


def _parse_legacy_log(body: str) -> list[tuple[str, str, str, str]]:
    """Extract (day, time, action, detail) tuples from the old flat log format."""
    events, cur, detail = [], None, []
    for line in body.splitlines():
        m = _LEGACY_LOG_RE.match(line.strip())
        if m:
            if cur:
                events.append((*cur, " ".join(detail).strip()))
            cur, detail = (m.group(1), m.group(2), m.group(3)), []
        elif cur and line.strip():
            detail.append(line.strip())
    if cur:
        events.append((*cur, " ".join(detail).strip()))
    return events


def reformat_log(text: str) -> str:
    """Best-effort convert a legacy flat log into OKF date-grouped form."""
    post = frontmatter.loads(text) if text.lstrip().startswith("---") \
        else frontmatter.Post(text)
    events = _parse_legacy_log(post.content)
    if not events:
        post.metadata.setdefault("title", "Activity Log")
        if not post.content.strip():
            post.content = "# Log\n"
        return frontmatter.dumps(post) + "\n"
    out = "# Log\n"
    for day, time, action, detail in events:  # file order (oldest first)
        out = add_log_entry(out, action, detail, day=day, time=time)
    return out


# --- Validation --------------------------------------------------------------

def okf_validate(wiki_dir) -> list[str]:
    """Return OKF conformance issues for a bundle directory; empty == conformant."""
    wiki_dir = Path(wiki_dir)
    issues: list[str] = []

    index = wiki_dir / "index.md"
    if not index.exists():
        issues.append("index.md: missing")
    else:
        try:
            meta = frontmatter.loads(index.read_text()).metadata
            if str(meta.get("okf_version") or "").strip() != OKF_VERSION:
                issues.append('index.md: missing okf_version: "0.1"')
        except Exception:
            issues.append("index.md: unparseable frontmatter")

    for md in sorted(wiki_dir.rglob("*.md")):
        if md.name in _NON_CONCEPT:
            continue
        try:
            meta = frontmatter.loads(md.read_text()).metadata
        except Exception:
            issues.append(f"{md.name}: unparseable frontmatter")
            continue
        if not str(meta.get("type") or "").strip():
            issues.append(f"{md.name}: empty/missing required `type`")
    return issues
