"""Tools for the deep researcher (LangGraph agent in agent.py).

Parallel-by-default I/O: tavily_search and fetch_webpage_content fan out via a
ThreadPoolExecutor. LLM calls remain sequential at the agent layer.
"""

from __future__ import annotations

import contextlib
import operator as _op
import os
import re
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, date, datetime
from functools import partial
from typing import Any, cast

import frontmatter  # pyright: ignore[reportMissingTypeStubs]
from dotenv import load_dotenv
from langchain_core.tools import tool

import calibrate
import chunker
import classification
import db_context
import evidence
import lex_index
import okf
import ontology_graph
import ontology_query
import ontology_store
import ontology_time
import refs
import retrieval
import run_memory
import wiki_engine
from prompts import (
    CHAT_OPEN_REFS_MISSING,
    CHAT_QUOTE_UNMATCHED,
    CHAT_SECTION_UNREAD,
    EVALUATE_CONDITION_DESCRIPTION,
    FETCH_WEBPAGE_DESCRIPTION,
    LOW_CONFIDENCE_NUDGE,
    ONTOLOGY_LOOKUP_DESCRIPTION,
    ONTOLOGY_SUPERSEDED_NUDGE,
    RAW_READ_DESCRIPTION,
    RAW_SEARCH_DESCRIPTION,
    SUBMIT_CHAT_DESCRIPTION,
    SUBMIT_FINAL_DESCRIPTION,
    TAVILY_SEARCH_DESCRIPTION,
    THINK_TOOL_DESCRIPTION,
    WIKI_READ_DESCRIPTION,
    WIKI_SEARCH_DESCRIPTION,
)

load_dotenv()

PARALLELISM = int(os.getenv("RESEARCH_PARALLELISM", "4"))
MIN_WORDS = int(os.getenv("RESEARCH_MIN_WORDS", "600"))
MIN_URLS = int(os.getenv("RESEARCH_MIN_URLS", "4"))
CHAT_MIN_WORDS = int(os.getenv("CHAT_MIN_WORDS", "500"))
CHAT_MIN_SOURCES = int(os.getenv("CHAT_MIN_SOURCES", "2"))
CHAT_MIN_SEARCHES = int(os.getenv("CHAT_MIN_SEARCHES", "3"))
# Deep chat's word floor per cited source, capped at CHAT_MIN_WORDS: a flat floor makes a
# small model pad thin evidence with uncited text.
CHAT_WORDS_PER_SOURCE = int(os.getenv("CHAT_WORDS_PER_SOURCE", "100"))
CONTENT_TRUNCATE = 2000
RAW_READ_CAP = 16000  # chars per raw_read call (per file, per offset window)
# After this many distinct byte-offset windows of one file have been read in a
# run, the read result appends a "submit now" nudge — stops weak models from
# paginating a whole document instead of answering.
RAW_READ_NUDGE_AFTER = int(os.getenv("CHAT_RAW_READ_NUDGE_AFTER", "3"))
# Reference chains (raw_read footers): cross-file hops a run may follow, and the extra agent
# turns it may earn by following them (+2 per followed cross-file reference).
REF_MAX_HOPS = 3
REF_BONUS_MAX = int(os.getenv("CHAT_REF_BONUS_MAX", "6"))
LEDGER_MAX = 40  # quotes a run's evidence ledger keeps (first come; ~24K chars at most)
RANK_TOP_K = 12  # sections ranked per file for the section map and auto-advance
MAP_RADIUS = 5  # section-map entries shown on each side of a served section
WIKI_LINK_EXPANSION = os.getenv("WIKI_LINK_EXPANSION", "1") != "0"
WIKI_LINK_SEEDS = int(os.getenv("WIKI_LINK_SEEDS", "3"))  # top hits whose links we follow
WIKI_LINK_MAX = int(os.getenv("WIKI_LINK_MAX", "5"))  # max neighbours appended per query
# Floor on per-DB hits when a multi-DB search splits its budget — below this a
# wide scope starves every DB into uselessness.
MIN_HITS_PER_DB = 3

_URL_RE = re.compile(r"https?://[^\s\)\]]+")
# Permissive body so a DB-qualified page ("Investing::foo.md") still parses —
# DB names may contain spaces, so this can't be a \w-class.
_WIKI_CITE_RE = re.compile(r"\[Wiki:\s*([^\]\n]+?\.md)\s*\]")
# A document's own numbered sections, as cited or mentioned: "Kapitel 3", "Kap. 3.2",
# "Abschnitt 5", "Abs. 5" (resolved to the heading that starts with the number).
_DOC_SECTION = r"(?:Kapitel\b|Kap\.|Abschnitte?\b|Abschn\.|Absatz\b|Abs\.)"
_DOC_SECTION_RE = re.compile(rf"^{_DOC_SECTION}\s*(?P<num>\d+(?:\.\d+)*)\b")
# Accept an optional trailing " §...", " #..." or " Kapitel ..." section marker so the same
# file can be cited as multiple distinct sources, e.g. [Source: StrlSchG.md §62].
_RAW_CITE_RE = re.compile(
    rf"\[Source:\s*([^\]\n]+?\.(?:md|txt|html)(?:\s*(?:[§#]|{_DOC_SECTION})[^\]\n]+?)?)\s*\]"
)


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "report"


def _format_tavily_result(idx: int, r: dict[str, Any]) -> str:
    content = (r.get("content") or "")[:CONTENT_TRUNCATE]
    url = r.get("url", "")
    return f"Result {idx}: {r.get('title', '')}\nCite as: [Source: {url}]\nContent: {content}\n---"


def _tavily_one(query: str, max_results: int) -> str:
    from tavily import TavilyClient  # pyright: ignore[reportMissingTypeStubs]

    client: Any = TavilyClient(api_key=os.getenv("TAVILY_API_KEY"))  # loosely typed SDK
    results: dict[str, Any] = client.search(query, max_results=max_results, include_answer=True)
    parts = [f"## Query: {query}"]
    answer = results.get("answer")
    if answer:
        parts.append(f"Answer: {answer}")
    for i, r in enumerate(results.get("results", []), 1):
        parts.append(_format_tavily_result(i, r))
    return "\n".join(parts) if len(parts) > 1 else f"## Query: {query}\n(no results)"


def _query_list(query: str | None, queries: list[str] | None) -> list[str]:
    """The non-empty queries of a `query=` / `queries=` tool call."""
    return [q for q in (queries or ([query] if query else [])) if q]


def _names(value: str | list[str] | None) -> list[str]:
    """The non-empty names of a tool argument that may be one string or a list."""
    return [v for v in ([value] if isinstance(value, str) else value or []) if v]


WEB_TOOL_NAMES = frozenset({"tavily_search", "fetch_webpage_content"})
_WEB_OFF = (
    "Web search is off: classified documents are in scope, so nothing may leave this machine."
)


def _web_blocked() -> bool:
    """Defence in depth for G4: the agents unbind these tools, and they refuse anyway."""
    return classification.high_water(db_context.search_scope()) > 0


def _tavily_search_impl(
    query: str | None = None, queries: list[str] | None = None, max_results: int = 5
) -> str:
    if _web_blocked():
        return _WEB_OFF
    qs = _query_list(query, queries)
    if not qs:
        return "Error: provide `query` or `queries`."
    if len(qs) == 1:
        return _tavily_one(qs[0], max_results)
    with ThreadPoolExecutor(max_workers=PARALLELISM) as ex:
        outs = list(ex.map(partial(_tavily_one, max_results=max_results), qs))
    return "\n\n".join(outs)


def _fetch_one(url: str) -> str:
    import httpx
    from markdownify import markdownify

    try:
        resp = httpx.get(url, timeout=15.0, follow_redirects=True)
        resp.raise_for_status()
    except Exception as exc:
        return f"## {url}\n(fetch failed: {exc})"
    md = markdownify(resp.text)
    if len(md) > CONTENT_TRUNCATE * 2:
        md = md[: CONTENT_TRUNCATE * 2] + "\n...[truncated]"
    return f"## {url}\n{md}"


def _fetch_webpage_impl(urls: str | list[str] | None) -> str:
    if _web_blocked():
        return _WEB_OFF
    urls = _names(urls)
    if not urls:
        return "Error: provide one or more urls."
    if len(urls) == 1:
        return _fetch_one(urls[0])
    with ThreadPoolExecutor(max_workers=PARALLELISM) as ex:
        outs = list(ex.map(_fetch_one, urls))
    return "\n\n".join(outs)


def _format_wiki_hit(idx: int, hit: dict[str, Any]) -> str:
    return (
        f"[Wiki hit {idx}]\n"
        f"file: {db_context.qualify(hit.get('filename', ''))}\n"
        f"title: {hit.get('title', '')}\n"
        f"excerpt: {hit.get('excerpt', '')}\n---"
    )


def _format_wiki_link(idx: int, hit: dict[str, Any]) -> str:
    via = hit.get("via", "")
    why = (
        f"shares a source with {via}"
        if hit.get("kind") == "shared-source"
        else f"related via {via}"
    )
    return (
        f"[Wiki linked {idx} — {why}]\n"
        f"file: {db_context.qualify(hit.get('filename', ''))}\n"
        f"title: {hit.get('title', '')}\n"
        f"excerpt: {hit.get('excerpt', '')}\n---"
    )


def _wiki_search_db(query: str, max_results: int) -> list[str]:
    """Formatted wiki hits for the *active* DB; [] when nothing matched.

    Link expansion stays inside the DB — `related:` edges never cross databases.
    """
    hits = wiki_engine.search_wiki(query) or []
    if not hits:
        return []
    top = hits[:max_results]
    parts = [_format_wiki_hit(i, h) for i, h in enumerate(top, 1)]
    if WIKI_LINK_EXPANSION:
        seeds = [h["filename"] for h in top[:WIKI_LINK_SEEDS]]
        shown = {h["filename"] for h in top}
        linked = [
            page
            for page in wiki_engine.linked_pages(seeds, limit=WIKI_LINK_MAX)
            if page["filename"] not in shown
        ]
        parts.extend(_format_wiki_link(i, page) for i, page in enumerate(linked, 1))
    return parts


def _per_db_budget(max_results: int) -> int:
    """Split a hit budget across the searched DBs so N DBs cost ~one DB's context."""
    return max(max_results // len(db_context.search_scope()), MIN_HITS_PER_DB)


def _wiki_search_one(query: str, max_results: int) -> str:
    scope = db_context.search_scope()
    per_db = _per_db_budget(max_results)
    parts = [f"## Wiki query: {query}"]
    found = False
    for db in scope:
        with db_context.using_db(db):
            blocks = _wiki_search_db(query, per_db)
        if len(scope) > 1:
            parts.append(f"### Database: {db}" + ("" if blocks else "\n(no results)"))
        parts.extend(blocks)
        found = found or bool(blocks)
    if not found and len(scope) == 1:
        parts.append("(no results)")
    return "\n".join(parts)


def _wiki_search_impl(
    query: str | None = None, queries: list[str] | None = None, max_results: int = 8
) -> str:
    qs = _query_list(query, queries)
    if not qs:
        return "Error: provide `query` or `queries`."
    if len(qs) == 1:
        return _wiki_search_one(qs[0], max_results)
    with ThreadPoolExecutor(max_workers=PARALLELISM) as ex:
        outs = list(
            ex.map(db_context.bind_context(partial(_wiki_search_one, max_results=max_results)), qs)
        )
    return "\n\n".join(outs)


def _wiki_read_one(filename: str) -> str:
    db, name = db_context.split_ref(filename)
    with db_context.using_db(db):
        body = wiki_engine.read_page(name)
    if len(body) > CONTENT_TRUNCATE * 2:
        body = body[: CONTENT_TRUNCATE * 2] + "\n...[truncated]"
    return f"## Wiki page: {filename}\n{body}"


def _wiki_read_impl(filenames: str | list[str] | None) -> str:
    filenames = _names(filenames)
    if not filenames:
        return "Error: provide one or more wiki filenames."
    if len(filenames) == 1:
        return _wiki_read_one(filenames[0])
    with ThreadPoolExecutor(max_workers=PARALLELISM) as ex:
        outs = list(ex.map(db_context.bind_context(_wiki_read_one), filenames))
    return "\n\n".join(outs)


def _clean_hits(hits: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The hits worth a small model's context: one chunk per file and section, and with a
    calibrated τ none below it but the best (the low-confidence nudge covers that case)."""
    tau = calibrate.threshold()
    seen: set[tuple[str, str]] = set()
    out: list[dict[str, Any]] = []
    for h in hits:
        key = (h["source"], h.get("anchor") or h["chunk_id"])
        below = tau is not None and "rerank_score" in h and float(h["rerank_score"]) < tau
        if key in seen or (out and below):
            continue
        seen.add(key)
        out.append(h)
    return out


def _raw_search_db(query: str, max_results: int) -> list[str]:
    """Formatted raw-chunk hits for the *active* DB; [] when nothing matched.

    Hybrid retrieval (lexical + semantic RRF); degrades to pure lexical when the DB
    has no embedding index (see src/retrieval.py)."""
    hits = retrieval.search(query, top_k=max_results, scope="raw", use_rerank=True)
    mem = run_memory.current()
    view = ontology_store.view()
    as_of = retrieval.point_in_time(query)
    for h in hits:
        if mem is not None and "rerank_score" in h:  # Stage E: track best passage seen
            mem.note_relevance(float(h["rerank_score"]))
            mem.note_source_relevance(db_context.qualify(h["source"]), float(h["rerank_score"]))
    parts: list[str] = []
    for i, h in enumerate(_clean_hits(hits), 1):
        anchor = h.get("anchor") or ""
        cite_suffix = f" {anchor}" if anchor else ""
        badge = ontology_query.badge(view, h["source"], as_of) if view is not None else ""
        parts.append(
            f"[Raw hit {i}]\n"
            f"file: {db_context.qualify(h['source'])}{cite_suffix}\n"
            f"chunk_id: {h['chunk_id']}\n"
            + (f"{badge}\n" if badge else "")
            + f"score: {h['score']}  matched: {', '.join(h['matched_terms'])}\n"
            f"excerpt: {h['preview']}\n---"
        )
    return parts


def _raw_search_one(query: str, max_results: int) -> str:
    scope = db_context.search_scope()
    per_db = _per_db_budget(max_results)
    parts = [f"## Raw query: {query}"]
    found = False
    for db in scope:
        with db_context.using_db(db):
            blocks = _raw_search_db(query, per_db)
        if len(scope) > 1:
            parts.append(f"### Database: {db}" + ("" if blocks else "\n(no results)"))
        parts.extend(blocks)
        found = found or bool(blocks)
    if not found and len(scope) == 1:
        parts.append("(no results — try a different keyword or a question phrasing)")
    return "\n".join(parts)


def _raw_search_impl(
    query: str | None = None, queries: list[str] | None = None, max_results: int = 6
) -> str:
    qs = _query_list(query, queries)
    if not qs:
        return "Error: provide `query` or `queries`."
    if len(qs) == 1:
        return _raw_search_one(qs[0], max_results)
    with ThreadPoolExecutor(max_workers=PARALLELISM) as ex:
        outs = list(
            ex.map(db_context.bind_context(partial(_raw_search_one, max_results=max_results)), qs)
        )
    return "\n\n".join(outs)


def _split_filename(filename: str) -> tuple[str, str]:
    """Split a possibly section-qualified filename into (base_file, section).

    Handles legal '§' citations, markdown '#' headings, and bare markdown
    heading titles with no prefix (the form raw_search emits, since markdown
    chunk anchors store the heading title without '#').
    """
    f = filename.strip()
    m = re.search(r"\s*[§#]", f)
    if m:  # explicit section marker
        return f[: m.start()].strip(), f[m.start() :].strip()
    if wiki_engine.read_raw_source(f) is not None:  # bare file (may contain spaces)
        return f, ""
    m = re.match(r"^(\S+\.\w{1,5})\s+(.+)$", f)  # peel a trailing heading title
    if m and wiki_engine.read_raw_source(m.group(1)) is not None:
        return m.group(1), m.group(2).strip()
    return f, ""


def _split_ref(filename: str) -> tuple[str, str, str]:
    """Split a raw-file ref into (db, base_file, section).

    `filename` may carry a DB prefix, a section suffix, or both
    ("Investing::StrlSchG.md §62"). `base_file` comes back unqualified — it names
    a file *inside* `db` — so callers must bind `db` before touching chunk/raw
    stores with it. Under a single-DB scope `db` is just the active DB.
    """
    db, rest = db_context.split_ref(filename)
    with db_context.using_db(db):
        base, section = _split_filename(rest)
        other = _other_work(base, section)
    if other is None:
        return db, base, section
    db, other_base = db_context.split_ref(other[0])
    return db, other_base, other[1]


def _other_work(base: str, section: str) -> tuple[str, str] | None:
    """(qualified file, anchor) when `section` names another work's § or chapter ("§ 34
    StrlSchG", "§ 34 des Strahlenschutzgesetzes" in a StrlSchV tag, "Kapitel 3 Bericht
    ABC"), else None."""
    if not (section.startswith("§") or _DOC_SECTION_RE.match(section)):
        return None
    try:
        found = refs.find_refs(section, base, None, _resolve_work, lambda _f, _a: True)
    except Exception:  # a broken reference parse must never cost the read or the gate
        return None
    first = found[0] if found else None
    if first is None or first.kind != refs.CROSS or first.target is None:
        return None
    return first.target, first.anchor


def _norm_anchor(s: str) -> str:
    """Normalize an anchor/section for matching: drop leading #/§, fold case."""
    s = re.sub(r"^[#§\s]+", "", s)
    return re.sub(r"\s+", " ", s).strip().casefold()


def _section_anchors(base: str) -> list[str]:
    """Distinct section anchors of a source, in document order."""
    seen: set[str] = set()
    out: list[str] = []
    for ch in chunker.load_chunks(base):
        a = ch.get("anchor", "")
        if a and a not in seen:
            seen.add(a)
            out.append(a)
    return out


def _resolve_section(base: str, section: str) -> dict[str, Any] | None:
    """Find the chunk in `base` whose anchor matches `section`, or None."""
    want = _norm_anchor(section)
    if not want:
        return None
    chunks = chunker.load_chunks(base)
    numbered = _DOC_SECTION_RE.match(section)
    if numbered:
        return _numbered_heading(chunks, numbered["num"])
    for ch in chunks:  # exact
        if _norm_anchor(ch.get("anchor", "")) == want:
            return ch
    for ch in chunks:  # prefix either direction (tolerate '(Teil n)', "(2)", title variants)
        a = _norm_anchor(_TEIL_RE.sub("", ch.get("anchor", "")))  # "§ 62 (2)" is in "§ 62 (Teil 1)"
        if a and (_prefix_of(want, a) or _prefix_of(a, want)):
            return ch
    return None


_LEGAL_ANCHOR_RE = re.compile(r"^(?:§|Anlage|Artikel|Art\.|Präambel)")
_HEADING_NUM_RE = re.compile(
    rf"^(?:{_DOC_SECTION}\s*|chapter\s+|section\s+)?(\d+(?:\.\d+)*)\.?(?:\s|$)", re.I
)


def _numbered_heading(chunks: list[dict[str, Any]], num: str) -> dict[str, Any] | None:
    """The first chunk whose heading starts with the number `num` ("3 Ergebnisse",
    "3. Ergebnisse", "Kapitel 3 …"); a law's § anchors never count, so "Abschnitt 3" is
    not § 3."""
    for ch in chunks:
        anchor = ch.get("anchor", "")
        m = _HEADING_NUM_RE.match(anchor)
        if m and m.group(1) == num and not _LEGAL_ANCHOR_RE.match(anchor):
            return ch
    return None


def _prefix_of(short: str, long: str) -> bool:
    """`short` starts `long` and ends at a word boundary: "31" starts "31 (2)", but "3"
    does not start "31 (2)"."""
    return long.startswith(short) and (len(long) == len(short) or not long[len(short)].isalnum())


def ref_key(ref: str) -> tuple[str, str]:
    """(qualified file, section) a citation points to, for comparing two spellings of one
    source: "StrlSchV.md § 31 (2)" and "StrlSchV.md § 31" are one key; a § of another work
    ("StrlSchV.md § 34 StrlSchG") is keyed to that work's file."""
    db, base, section = _split_ref(ref)
    with db_context.using_db(db):
        ch = _resolve_section(base, section) if section else None
    anchor = _TEIL_RE.sub("", ch["anchor"]) if ch is not None else _norm_anchor(section)
    return db_context.qualify(base, db), anchor


def _format_section(base: str, ch: dict[str, Any], label: str | None = None) -> str:
    """Render a section. `label` is the name echoed back to the model (DB-qualified
    under a multi-DB scope) — `base` still addresses the chunk store."""
    label = label or base
    anchor = ch.get("anchor", "")
    text = ch.get("text", "")
    if len(text) > RAW_READ_CAP:
        text = text[:RAW_READ_CAP] + "\n…[section truncated]"
    anchors = _section_anchors(base)
    nxt = None
    if anchor in anchors:
        i = anchors.index(anchor)
        nxt = anchors[i + 1] if i + 1 < len(anchors) else None
    footer = f"\n\n…[next section: read '{label} {nxt}']" if nxt else ""
    return f"## Raw file: {label} {anchor}\n{text}{footer}"


def _read_key(base: str, canon: str, offset: int) -> str:
    """Visited-memory key. Distinct sections (canon) get distinct keys so the
    guard no longer collapses every section read to the base file at offset 0."""
    if canon:
        return f"raw:{base}|sec={canon}:{int(offset or 0)}"
    return f"raw:{base}:{int(offset or 0)}"


def _canon(base: str, section: str) -> str:
    """A section's visited-memory form: the anchor it resolves to, so "§62" and "§ 62" share
    one entry; the normalized request when it resolves to nothing. Caller binds the DB."""
    ch = _resolve_section(base, section) if section else None
    return _norm_anchor(ch["anchor"]) if ch else _norm_anchor(section)


def _read_canons(mem: run_memory.RunMemory, base: str) -> set[str]:
    """Normalized section anchors of `base` already read this run."""
    prefix = f"raw:{base}|sec="
    return {k[len(prefix) :].rsplit(":", 1)[0] for k in mem.reads if k.startswith(prefix)}


def _read_offsets(mem: run_memory.RunMemory, base: str) -> set[int]:
    """Section-less byte offsets of `base` already read this run."""
    prefix = f"raw:{base}:"  # excludes section keys (those have '|sec=' before ':')
    out: set[int] = set()
    for k in mem.reads:
        if k.startswith(prefix):
            with contextlib.suppress(ValueError):
                out.add(int(k[len(prefix) :]))
    return out


def _next_unread_offset(
    mem: run_memory.RunMemory, base: str, key_base: str | None = None
) -> int | None:
    """Smallest RAW_READ_CAP-aligned offset of `base` not yet read this run.

    `base` addresses the raw store (caller binds its DB); `key_base` is the name
    the visited-memory is keyed under (DB-qualified under a multi-DB scope).
    None if the whole file is read (or it can't be sized). Lets the duplicate-read
    stub name the exact next call instead of generic 'paginate' advice, so a weak
    model breaks the offset-0 loop in one step."""
    data = wiki_engine.read_raw_source(base)
    if data is None:
        return None
    total = len(data.decode("utf-8", errors="replace"))
    read = _read_offsets(mem, key_base or base)
    g = 0
    while g < total:
        if g not in read:
            return g
        g += RAW_READ_CAP
    return None


def _raw_read_one(filename: str, offset: int = 0) -> str:
    db, base, section = _split_ref(filename)
    with db_context.using_db(db):
        label = db_context.qualify(base, db)
        if section:
            ch = _resolve_section(base, section)
            if ch is not None:
                return _format_section(base, ch, label)
        data = wiki_engine.read_raw_source(base)
    if data is None:
        return f"## Raw file: {filename}\n(not found)"
    body = data.decode("utf-8", errors="replace")
    total = len(body)
    start = max(0, int(offset or 0))
    if start >= total:
        return f"## Raw file: {label} (offset {start}/{total})\n(offset past end)"
    end = min(total, start + RAW_READ_CAP)
    window = body[start:end]
    header = f"## Raw file: {label} (bytes {start}-{end} of {total})"
    footer = ""
    if end < total:
        footer = f"\n\n…[truncated; pass offset={end} to continue]"
    elif start > 0:
        footer = "\n\n…[end of file]"
    return f"{header}\n{window}{footer}"


def _raw_read_impl(filenames: str | list[str] | None, offset: int = 0) -> str:
    filenames = _names(filenames)
    if not filenames:
        return "Error: provide one or more raw filenames."
    if len(filenames) == 1:
        return _raw_read_one(filenames[0], offset=offset)
    with ThreadPoolExecutor(max_workers=PARALLELISM) as ex:
        outs = list(
            ex.map(db_context.bind_context(partial(_raw_read_one, offset=offset)), filenames)
        )
    return "\n\n".join(outs)


def _low_confidence_nudge() -> str | None:
    """Stage E soft gate shared by both submit paths (idea.md §6.9.1 rung 5).

    Returns the one-shot abstain nudge when this run's best passage fell below the
    calibrated τ, else None. Bounded to a single fire (`low_conf_nudged`) so it can never
    stall the loop; fail-safe — an uncalibrated DB / no reranker (tau or best_relevance
    None) never nudges.
    """
    mem = run_memory.current()
    tau = calibrate.threshold()
    if (
        mem is not None
        and tau is not None
        and mem.best_relevance is not None
        and mem.best_relevance < tau
        and not mem.low_conf_nudged
    ):
        mem.low_conf_nudged = True
        return LOW_CONFIDENCE_NUDGE
    return None


def current_run_audit(db: str | None = None) -> dict[str, Any] | None:
    """Search-ladder audit for the just-finished agentic run (Deep chat / research).

    Reads the per-source best rerank_scores accumulated in run memory and splits them by
    the DB's τ into a render-ready record (see `calibrate.justify`). Returns None when the
    run scored no source (e.g. wiki/web-only), so the caller can skip the audit panel.
    """
    mem = run_memory.current()
    if mem is None or not (mem.relevance_by_source or mem.ontology):
        return None
    record = calibrate.justify(list(mem.relevance_by_source.items()), calibrate.threshold(db))
    return {**record, "ontology": list(mem.ontology)} if mem.ontology else record


_CITE_SECTION_RE = re.compile(r"\s*[§#].*$")


def _supersession(ref: str, as_of: date) -> tuple[str, str | None]:
    """(validity of a cited raw source, the version in force of its work) at ``as_of``."""
    db, name = db_context.split_ref(_CITE_SECTION_RE.sub("", ref))
    with db_context.using_db(db):
        view = ontology_store.view()
        if view is None:
            return ontology_time.UNKNOWN, None
        state = ontology_time.validity(view, name, as_of)
        work = str(view.sources.get(name, {}).get("work") or "")
        current = ontology_time.current_expression(view, work, as_of) if work else None
    return state, db_context.qualify(current, db) if current else None


def _superseded_nudge(cited: set[str]) -> str | None:
    """S4 (docs/ontology.md §Time): reject once when every dated cited source is a
    superseded version and the version in force is in the DB. Silent for questions about
    the past, without an ontology, and after it fired once (a weak model cannot loop)."""
    mem = run_memory.current()
    if mem is None or mem.validity_nudged or mem.time_past or not cited:
        return None
    as_of = ontology_time.parse(mem.as_of) if mem.as_of else date.today()
    found = [_supersession(ref, as_of or date.today()) for ref in sorted(cited)]
    states = [s for s, _ in found if s != ontology_time.UNKNOWN]
    current = sorted({c for s, c in found if s == ontology_time.SUPERSEDED and c})
    if not states or any(s != ontology_time.SUPERSEDED for s in states) or not current:
        return None
    mem.validity_nudged = True
    return ONTOLOGY_SUPERSEDED_NUDGE.format(
        cited=", ".join(sorted(cited)), current=", ".join(current)
    )


def _read_bases(mem: run_memory.RunMemory) -> set[str]:
    """The (qualified) originals this run opened with raw_read, by any section or window."""
    keys = (k[len("raw:") :] for k in mem.reads if k.startswith("raw:"))
    return {k.split("|sec=", 1)[0] if "|sec=" in k else k.rsplit(":", 1)[0] for k in keys}


def _section_read(mem: run_memory.RunMemory, qbase: str, ch: dict[str, Any]) -> bool:
    """Whether this run read the chunk `ch` of `qbase`: by its section, or by a byte window
    that overlaps it (an honest pagination read counts)."""
    if _norm_anchor(ch.get("anchor", "")) in {_norm_anchor(c) for c in _read_canons(mem, qbase)}:
        return True
    start, end = int(ch.get("char_start", 0)), int(ch.get("char_end", 0))
    return any(o < end and o + RAW_READ_CAP > start for o in _read_offsets(mem, qbase))


def _legal_chunk(base: str, anchor: str) -> dict[str, Any] | None:
    """The chunk of `base` whose anchor is exactly `anchor` (or its first part), else None:
    stricter than `_resolve_section`, so a "§ 6" in prose never resolves to § 60."""
    want = _norm_anchor(anchor)
    for ch in chunker.load_chunks(base):
        a = _norm_anchor(ch.get("anchor", ""))
        if a == want or a.startswith(f"{want} (teil"):
            return ch
    return None


def _named_raw_file(name: str) -> str | None:
    """A raw file in the active DB whose stem or first heading names `name` (genitive-
    tolerant: "Atomgesetzes" → "Atomgesetz")."""
    raw = db_context.raw_dir()
    if not raw.exists():
        return None
    n = name.casefold()
    forms = {n, n[:-1], n[:-2]} if len(n) > 5 else {n}
    for p in sorted(raw.iterdir()):
        if p.suffix.lower() not in (".md", ".txt", ".html"):
            continue
        if p.stem.casefold() in forms:
            return p.name
        head = _first_heading(p).casefold()
        if any(re.search(rf"\b{re.escape(f)}\b", head) for f in forms):
            return p.name
    return None


def _first_heading(p: Any) -> str:
    """The first heading, plus the first line when it is plain text (a gesetze-im-internet
    text opens with its title line, not a markdown heading)."""
    first = ""
    with contextlib.suppress(OSError), p.open("r", errors="replace") as fh:
        for _, line in zip(range(40), fh, strict=False):
            if line.startswith("#"):
                return f"{first} {line.lstrip('# ').strip()}".strip()
            first = first or line.strip()
    return first


def _ontology_work_file(name: str) -> str | None:
    """The version in force of the work `name` names, by the active DB's ontology."""
    view = ontology_store.view()
    frame = ontology_query.resolve(name, view) if view is not None else None
    if view is None or frame is None or not frame.works:
        return None
    return ontology_time.current_expression(view, frame.works[0], date.today())


def _resolve_work(name: str) -> str | None:
    """The (qualified) raw file a work name points to, searched only inside the search
    scope (a file of a level out of scope is never named); cached per run."""
    mem = run_memory.current()
    if mem is not None and name in mem.work_files:
        return mem.work_files[name]
    found = None
    for db in db_context.search_scope():
        with db_context.using_db(db):
            hit = _ontology_work_file(name) or _named_raw_file(name)
        if hit:
            found = db_context.qualify(hit, db)
            break
    if mem is not None:
        mem.work_files[name] = found
    return found


def _tagged_unread(mem: run_memory.RunMemory, raw_cited: set[str]) -> list[tuple[str, str]]:
    """(qualified file, anchor) of each `[Source: file §N]` whose section was not read."""
    out: list[tuple[str, str]] = []
    for ref in sorted(raw_cited):
        db, base, section = _split_ref(ref)
        with db_context.using_db(db):
            ch = _resolve_section(base, section) if section else None
        qbase = db_context.qualify(base, db)
        if ch is not None and not _section_read(mem, qbase, ch):
            out.append((qbase, ch["anchor"]))
    return out


def _prose_unread(mem: run_memory.RunMemory, answer: str, cited: set[str]) -> list[tuple[str, str]]:
    """(file, anchor) of each § the prose names in a cited original but that was not read.
    A § naming another work counts only when that work's file is cited."""
    out: list[tuple[str, str]] = []
    for r in refs.find_refs(answer, "", None, _resolve_work, lambda _f, _a: True):
        files = sorted(cited) if r.kind == refs.SAME else [r.target] if r.target in cited else []
        held: list[tuple[str, dict[str, Any]]] = []
        for qbase in files:
            db, base = db_context.split_ref(qbase)
            with db_context.using_db(db):
                ch = _legal_chunk(base, r.anchor)
            if ch is not None:
                held.append((qbase, ch))
        if held and not any(_section_read(mem, q, ch) for q, ch in held):
            out.append((held[0][0], r.anchor))
    return out


def _unread_sections(answer: str, raw_cited: set[str]) -> str | None:
    """Fix B: a rejection naming the exact read for each cited § whose text this run never
    opened. Tagged citations always count; a § named only in the prose is checked once."""
    mem = run_memory.current()
    if mem is None:
        return None
    unread = _tagged_unread(mem, raw_cited)
    if not unread and not mem.prose_section_nudged:
        cited = {db_context.qualify(b, d) for d, b, _ in map(_split_ref, raw_cited)}
        unread = _prose_unread(mem, answer, cited)
        mem.prose_section_nudged = bool(unread)
    if not unread:
        return None
    unread = list(dict.fromkeys(unread))[:3]
    return CHAT_SECTION_UNREAD.format(
        cited=", ".join(f"{a} of {f}" for f, a in unread),
        pronoun="it" if len(unread) == 1 else "them",
        calls="[" + ", ".join(f"'{f} {a}'" for f, a in unread) + "]",
    )


# A quoted span in an answer: „…“ (German), “…” or "…" on one line.
_QUOTE_RE = re.compile(r'[„“"]([^„“”"\n]+)[“”"]')
QUOTE_MIN_WORDS = 6  # shorter quoted spans are terms, not quotations
_ELLIPSIS_RE = re.compile(r"…|\.\.\.|\[…\]|\[\.\.\.\]")


def _plain(text: str) -> str:
    """`text` for a word-for-word comparison: no markdown emphasis, one space, casefolded."""
    return re.sub(r"\s+", " ", re.sub(r"[*_`]", "", text)).casefold().strip()


def _raw_text(ref: str) -> str:
    db, base, _ = _split_ref(ref)
    with db_context.using_db(db):
        data = wiki_engine.read_raw_source(base)
    return data.decode("utf-8", errors="replace") if data else ""


def _unmatched_quotes(answer: str, raw_cited: set[str]) -> str | None:
    """Once per run: reject quotes that are not word for word in any cited original. An
    ellipsis splits a quote into parts that must each be found."""
    mem = run_memory.current()
    quotes = [q for q in _QUOTE_RE.findall(answer) if len(q.split()) >= QUOTE_MIN_WORDS]
    if mem is None or mem.quote_nudged or not quotes:
        return None
    corpus = " ".join(_plain(_raw_text(ref)) for ref in sorted(raw_cited))
    missing = [
        q
        for q in quotes
        if any(
            _plain(part).strip(" .,;:") not in corpus
            for part in _ELLIPSIS_RE.split(q)
            if len(part.split()) >= 3
        )
    ]
    if not missing:
        return None
    mem.quote_nudged = True
    return CHAT_QUOTE_UNMATCHED.format(quotes="; ".join(f'"{q}"' for q in missing[:3]))


_OPEN_POINTS_RE = re.compile(r"^#{2,3}\s*(?:Open points|Offene Punkte)\b", re.I | re.M)


def _open_refs_missing(answer: str, raw_cited: set[str]) -> str | None:
    """Once per run: reject when a cited section relies on a law not in scope that the
    answer does not name under `## Open points`."""
    mem = run_memory.current()
    if mem is None or mem.open_refs_nudged:
        return None
    missing = open_refs_unnamed(answer, raw_cited)
    if not missing:
        return None
    mem.open_refs_nudged = True
    return CHAT_OPEN_REFS_MISSING.format(works=", ".join(missing[:5]))


def open_refs_unnamed(answer: str, raw_cited: set[str]) -> list[str]:
    """The laws not in scope that a cited section relies on and the answer does not name
    under `## Open points` (the gate's open-references check, without its nudge)."""
    mem = run_memory.current()
    if mem is None or not mem.out_of_scope:
        return []
    m = _OPEN_POINTS_RE.search(answer)
    open_points = answer[m.end() :].casefold() if m else ""
    missing: list[str] = []
    for ref in sorted(raw_cited):
        t = _target(ref)
        for work in mem.out_of_scope.get(f"{t.qbase}|sec={t.canon}", []) if t.section else []:
            name = refs.nominative(work)
            if name.casefold() not in open_points and name not in missing:
                missing.append(name)
    return missing


def _research_gap(raw_cited: set[str]) -> str | None:
    """A rejection when the run searched too little or opened none of the originals it
    cites: a deep answer rests on read text, not on search excerpts. None outside a run."""
    mem = run_memory.current()
    if mem is None:
        return None
    if mem.search_count() < CHAT_MIN_SEARCHES:
        return (
            f"REJECTED: {mem.search_count()} distinct searches so far, minimum is "
            f"{CHAT_MIN_SEARCHES}. raw_search the open sub-questions with other stems first."
        )
    read = _read_bases(mem)
    cited = {db_context.qualify(base, db) for db, base, _ in map(_split_ref, raw_cited)}
    if not cited & read:
        return (
            "REJECTED: none of the cited originals was opened with raw_read. raw_read the "
            "section that holds the answer, check the figures, then submit again."
        )
    return None


def _submit_chat_impl(answer: str, sources: list[str] | None = None) -> str:
    words = len(re.findall(r"\w+", answer or ""))
    cited = set(_RAW_CITE_RE.findall(answer or ""))
    extra = set(sources or [])
    # Wiki pages count toward the gate, but never alone: the wiki orients the
    # agent, raw documents ground it.
    wiki_cited = {f"wiki:{w}" for w in _WIKI_CITE_RE.findall(answer or "")}
    raw_unique = cited | extra
    unique = raw_unique | wiki_cited
    floor = min(CHAT_MIN_WORDS, CHAT_WORDS_PER_SOURCE * len(unique))
    if words < floor:
        return (
            f"REJECTED: answer has {words} words; with {len(unique)} cited sources the minimum "
            f"is {floor}. Continue researching and expand the answer."
        )
    if len(unique) < CHAT_MIN_SOURCES or not raw_unique:
        return (
            f"REJECTED: answer cites {len(unique)} unique sources ({len(raw_unique)} from "
            f"data/raw/), minimum is {CHAT_MIN_SOURCES} including at least one "
            "[Source: ...] document. Run more raw_search/raw_read and cite additional files."
        )
    nudge = (
        _research_gap(raw_unique)
        or _unread_sections(answer or "", raw_unique)
        or _unmatched_quotes(answer or "", raw_unique)
        or _open_refs_missing(answer or "", raw_unique)
        or _low_confidence_nudge()
        or _superseded_nudge(raw_unique)
    )
    if nudge:
        return nudge
    return f"ACCEPTED: {words} words, {len(unique)} sources cited."


# The gate's one-time nudges: each rejects once per run, then lets the answer pass.
_ONCE_FLAGS = (
    "prose_section_nudged",
    "quote_nudged",
    "open_refs_nudged",
    "low_conf_nudged",
    "validity_nudged",
)


def chat_verdict(answer: str) -> str:
    """The gate's verdict on an answer code wrote (the ledger answer), without using up the
    one-time nudges the agent's own answers are owed."""
    mem = run_memory.current()
    saved = {f: getattr(mem, f) for f in _ONCE_FLAGS} if mem is not None else {}
    try:
        return _submit_chat_impl(answer)
    finally:
        for flag, value in saved.items():
            setattr(mem, flag, value)


def _submit_final_impl(title: str, answer: str) -> str:
    words = len(re.findall(r"\w+", answer or ""))
    urls = set(_URL_RE.findall(answer or ""))
    wiki_cites = set(_WIKI_CITE_RE.findall(answer or ""))
    # File-style [Source: file.md] cites also count; drop URL-bearing ones so a
    # [Source: https://…html] isn't tallied twice (already caught by _URL_RE).
    raw_cites = {r for r in _RAW_CITE_RE.findall(answer or "") if "://" not in r}
    sources = urls | {f"wiki:{w}" for w in wiki_cites} | {f"src:{r}" for r in raw_cites}
    if words < MIN_WORDS:
        return (
            f"REJECTED: report has {words} words, minimum is {MIN_WORDS}. "
            "Continue researching and expand the answer."
        )
    if len(sources) < MIN_URLS:
        return (
            f"REJECTED: report cites {len(sources)} unique sources "
            f"(URLs + [Wiki: ...] + [Source: ...] citations), minimum is {MIN_URLS}. "
            "Run more searches and cite additional sources."
        )
    nudge = _low_confidence_nudge()
    if nudge:
        return nudge
    # High-water mark: the report lands at the highest level this run could read.
    target = db_context.write_target(db_context.base_db(), db_context.search_scope())
    with db_context.using_db(target):
        dest_dir = db_context.wiki_dir() / "comparisons"
    dest_dir.mkdir(parents=True, exist_ok=True)
    date = datetime.now(UTC).strftime("%Y-%m-%d")
    filename = f"report-{_slug(title)}.md"
    all_sources = (
        sorted(urls)
        + sorted(f"wiki:{w}" for w in wiki_cites)
        + sorted(f"src:{r}" for r in raw_cites)
    )
    # Serialised by the YAML writer, not f-string interpolated: an LLM-supplied
    # title containing a quote or colon would otherwise emit invalid YAML, which
    # okf.apply_to_page passes through unchanged and read_page_parsed then
    # cannot load — the report is written but unreadable.
    post = frontmatter.Post(answer, title=title, type="report", created=date, sources=all_sources)
    (dest_dir / filename).write_text(
        okf.apply_to_page(frontmatter.dumps(post), db=db_context.base_db())
    )
    return (
        f"ACCEPTED: comparisons/{filename} ({words} words, "
        f"{len(urls)} urls, {len(wiki_cites)} wiki cites, {len(raw_cites)} source cites)"
    )


# --- LangChain tool wrappers (used by ChatOllama.bind_tools) --------------


@tool(description=TAVILY_SEARCH_DESCRIPTION)
def tavily_search(query: str = "", queries: list[str] | None = None, max_results: int = 5) -> str:
    return _tavily_search_impl(query=query, queries=queries, max_results=max_results)


@tool(description=FETCH_WEBPAGE_DESCRIPTION)
def fetch_webpage_content(urls: list[str]) -> str:
    return _fetch_webpage_impl(urls)


def _dedup_search(prefix: str, qs: list[str]) -> tuple[list[str], list[str]]:
    """Split queries into (fresh, stub_lines) using current RunMemory."""
    mem = run_memory.current()
    if mem is None:
        return qs, []
    mem.tick()
    fresh: list[str] = []
    stubs: list[str] = []
    for q in qs:
        key = f"{prefix}:{(q or '').strip().lower()}"
        prior = mem.seen_search(key)
        if prior is not None:
            stubs.append(
                f"## {prefix} query: {q}\n[memory] Already searched at step {prior} — "
                "do not repeat. Try a different phrasing, or move on to reading a hit."
            )
        else:
            fresh.append(q)
            mem.mark_search(key)
    return fresh, stubs


@tool(description=WIKI_SEARCH_DESCRIPTION)
def wiki_search(query: str = "", queries: list[str] | None = None, max_results: int = 8) -> str:
    qs = queries if queries else ([query] if query else [])
    qs = [q for q in qs if q]
    if not qs:
        return _wiki_search_impl(query=query, queries=queries, max_results=max_results)
    fresh, stubs = _dedup_search("wiki_search", qs)
    if not fresh:
        return "\n\n".join(stubs)
    body = _wiki_search_impl(queries=fresh, max_results=max_results)
    return "\n\n".join([*stubs, body]) if stubs else body


@tool(description=WIKI_READ_DESCRIPTION)
def wiki_read(filenames: list[str]) -> str:
    mem = run_memory.current()
    if mem is None:
        return _wiki_read_impl(filenames)
    mem.tick()
    if isinstance(filenames, str):
        filenames = [filenames]
    filenames = [f for f in (filenames or []) if f]
    if not filenames:
        return _wiki_read_impl(filenames)
    out: list[str] = []
    fresh: list[str] = []
    for f in filenames:
        key = f"wiki:{f.strip()}"
        prior = mem.seen_read(key)
        if prior is not None:
            out.append(
                f"## Wiki page: {f}\n[memory] Already read at step {prior} — "
                "do not re-fetch. Use think_tool, pick a different page, or move on."
            )
        else:
            fresh.append(f)
    if fresh:
        out.append(_wiki_read_impl(fresh))
        for f in fresh:
            mem.mark_read(f"wiki:{f.strip()}")
    return "\n\n".join(out)


def _ontology_lookup_impl(term: str | None = None, as_of: str = "") -> str:
    term = (term or "").strip()
    if not term:
        return "Error: provide `term`."
    when = ontology_time.time_intent(f"as of {as_of}", date.today()).as_of if as_of else None
    scope = db_context.search_scope()
    parts = [f"## Ontology lookup: {term}"]
    for db in scope:
        with db_context.using_db(db):
            view = ontology_store.view()
            text = "(no ontology in this database)"
            if view is not None:
                extra = ontology_graph.describe(view, term, when or date.today())
                text = "\n".join(p for p in (ontology_query.lookup(term, view, when), extra) if p)
        parts.append(f"### Database: {db}\n{text}" if len(scope) > 1 else text)
    return "\n".join(parts)


@tool(description=ONTOLOGY_LOOKUP_DESCRIPTION)
def ontology_lookup(term: str, as_of: str = "") -> str:
    fresh, stubs = _dedup_search("ontology_lookup", [f"{term.strip()}|{as_of.strip()}"])
    return _ontology_lookup_impl(term, as_of) if fresh else stubs[0]


def with_ontology(base: list[Any]) -> list[Any]:
    """``base`` plus `ontology_lookup` when a DB in the search scope has an ontology, so
    agents over DBs without one see exactly the tools they saw before."""
    for db in db_context.search_scope():
        with db_context.using_db(db):
            if ontology_store.exists():
                return [*base, ontology_lookup]
    return base


def _think_impl(reflection: str) -> str:
    return reflection


@tool(description=THINK_TOOL_DESCRIPTION)
def think_tool(reflection: str) -> str:
    return _think_impl(reflection)


@tool(description=SUBMIT_FINAL_DESCRIPTION)
def submit_final_answer(title: str, answer: str) -> str:
    return _submit_final_impl(title, answer)


@tool(description=RAW_SEARCH_DESCRIPTION)
def raw_search(query: str = "", queries: list[str] | None = None, max_results: int = 6) -> str:
    qs = queries if queries else ([query] if query else [])
    qs = [q for q in qs if q]
    if not qs:
        return _raw_search_impl(query=query, queries=queries, max_results=max_results)
    fresh, stubs = _dedup_search("raw_search", qs)
    if not fresh:
        return "\n\n".join(stubs)
    body = _raw_search_impl(queries=fresh, max_results=max_results)
    return "\n\n".join([*stubs, body]) if stubs else body


@dataclass(frozen=True)
class _Target:
    """One raw_read request, resolved: `base` addresses the stores inside `db`, `qbase` is
    the (qualified) name the run memory and the model use, `canon` the section's key form."""

    ref: str
    db: str
    base: str
    section: str
    qbase: str
    canon: str


def _target(ref: str) -> _Target:
    db, base, section = _split_ref(ref)
    with db_context.using_db(db):
        canon = _canon(base, section)
    return _Target(ref, db, base, section, db_context.qualify(base, db), canon)


def _raw_len(t: _Target) -> int | None:
    with db_context.using_db(t.db):
        data = wiki_engine.read_raw_source(t.base)
    return None if data is None else len(data.decode("utf-8", errors="replace"))


def _chunks(t: _Target) -> list[dict[str, Any]]:
    with db_context.using_db(t.db):
        return chunker.load_chunks(t.base)


def _run_query(mem: run_memory.RunMemory) -> str:
    """The run's question, the sources' words for it (ontology terms, the user's glosses)
    and its distinct searches: what a file's sections are ranked by."""
    asked = [k.split(":", 1)[1] for k in mem.searches if k.startswith(("raw_search:", "wiki_"))]
    words = retrieval.vocabulary(" ".join([mem.question, *asked]))
    return " ".join([mem.question, words, *asked]).strip()[:2000]


def _ranked_unread(mem: run_memory.RunMemory, t: _Target) -> list[dict[str, Any]]:
    """Unread sections of `t`, best match for the run first ([] without an index or a hit)."""
    with db_context.using_db(t.db):
        q = _run_query(mem)
        hits = lex_index.query(q, top_k=RANK_TOP_K, scope="raw", sources=[t.base]) if q else []
    if not hits:
        return []
    by_id = {c["chunk_id"]: c for c in _chunks(t)}
    out: list[dict[str, Any]] = []
    for h in hits:
        ch = by_id.get(h["chunk_id"])
        if ch and float(h["score"]) > 0 and ch not in out and not _section_read(mem, t.qbase, ch):
            out.append(ch)
    return out


def _offered_unread(mem: run_memory.RunMemory, t: _Target) -> list[dict[str, Any]]:
    """Unread sections of `t` that a reference footer listed this run, in offer order."""
    prefix = f"{t.qbase}|sec="
    out: list[dict[str, Any]] = []
    for key in mem.ref_offers:
        if key.startswith(prefix):
            with db_context.using_db(t.db):
                ch = _resolve_section(t.base, key[len(prefix) :])
            if ch is not None and not _section_read(mem, t.qbase, ch):
                out.append(ch)
    return out


def _note_follow(mem: run_memory.RunMemory, qbase: str, canon: str) -> int:
    """Record a section read's chain depth; following a listed cross-file reference earns
    extra turns. Returns the depth (0 when no footer led here)."""
    key = f"{qbase}|sec={canon}"
    if key not in mem.ref_depth:
        depth, cross = mem.ref_offers.get(key, (0, False))
        mem.ref_depth[key] = depth
        if cross:
            mem.bonus = min(mem.bonus + 2, REF_BONUS_MAX)
    return mem.ref_depth[key]


def _find_anchor(file: str, anchor: str) -> dict[str, Any] | None:
    db, base = db_context.split_ref(file)
    with db_context.using_db(db):
        if anchor.startswith("§"):
            return _legal_chunk(base, anchor)
        return _resolve_section(base, anchor)


def _ref_entry(mem: run_memory.RunMemory, r: refs.Ref, depth: int) -> tuple[str, str | None]:
    """(footer entry, raw_read argument to follow it or None) for one reference."""
    if r.kind == refs.OUT or r.target is None:
        return f"{r.work} {r.anchor} (not in scope)", None
    label = f"{r.target} {r.anchor}"
    ch = _find_anchor(r.target, r.anchor) if r.found else None
    if ch is None:
        return f"{label} ({r.anchor} not found in file)", None
    same = r.kind == refs.SAME
    if not same and depth >= REF_MAX_HOPS:
        return f"{label} (hop limit reached)", None
    read = _section_read(mem, r.target, ch)
    status = ("same file, " if same else "") + ("read" if read else "unread")
    key = f"{r.target}|sec={_norm_anchor(ch['anchor'])}"
    mem.ref_offers.setdefault(key, (depth if same else depth + 1, not same))
    return f"{label} ({status})", None if read else label


def _no_own_chapter(r: refs.Ref) -> bool:
    return (
        r.kind == refs.SAME
        and r.anchor.split()[0] in refs.DOC_KINDS
        and r.target is not None
        and _find_anchor(r.target, r.anchor) is None
    )


def _ref_footer(mem: run_memory.RunMemory, t: _Target, anchor: str | None, text: str) -> str:
    """Fix F: the references a read text makes, resolved in code, with their status."""
    key = f"{t.qbase}|sec={_norm_anchor(anchor)}" if anchor else ""
    depth = mem.ref_depth.get(key, 0)
    try:
        found = refs.find_refs(text, t.qbase, anchor, _resolve_work, lambda f, a: True)
    except Exception:  # the footer is a hint: an odd text shape must never cost the read
        return ""
    # A law names its own structure ("Kapitel 2") all the time: a chapter of this file
    # with no heading for it is no reference, and listing it would crowd out the §§.
    found = [r for r in found if not _no_own_chapter(r)]
    if not found:
        return ""
    entries: list[str] = []
    follow: str | None = None
    for r in found:
        entry, call = _ref_entry(mem, r, depth)
        entries.append(entry)
        follow = follow or call
        if r.kind == refs.OUT and key and r.work not in mem.out_of_scope.get(key, []):
            mem.out_of_scope.setdefault(key, []).append(r.work)
    hint = f"  — follow with raw_read(['{follow}'])" if follow else ""
    return "\n\nReferences: " + " · ".join(entries) + hint


def _with_marker(text: str, marker: str) -> str:
    """`text` with a run-memory marker appended to its header line."""
    if not marker:
        return text
    head, _, rest = text.partition("\n")
    return f"{head} {marker}\n{rest}"


def _serve_section(
    mem: run_memory.RunMemory, t: _Target, ch: dict[str, Any], marker: str = ""
) -> str:
    """One section in full, marked read under its own key, with its reference footer."""
    canon = _norm_anchor(ch["anchor"])
    _note_follow(mem, t.qbase, canon)
    mem.mark_read(_read_key(t.qbase, canon, 0))
    with db_context.using_db(t.db):
        text = _format_section(t.base, ch, t.qbase)
    return _with_marker(text, marker) + _ref_footer(mem, t, ch["anchor"], ch["text"])


def _serve_window(mem: run_memory.RunMemory, t: _Target, offset: int, marker: str = "") -> str:
    """One byte window, marked read, with the references it makes."""
    text = _raw_read_one(t.qbase, offset=offset)
    mem.mark_read(_read_key(t.qbase, "", offset))
    body = text.partition("\n")[2]
    return _with_marker(text, marker) + _ref_footer(mem, t, None, body)


_TEIL_RE = re.compile(r"\s*\(Teil \d+\)$")


def _map_line(t: _Target, served: list[dict[str, Any]]) -> str:
    """The sections around the served ones (±MAP_RADIUS), with their titles."""
    entries: list[tuple[str, str]] = []
    for ch in _chunks(t):
        a = _TEIL_RE.sub("", ch.get("anchor", ""))
        if a and all(a != e[0] for e in entries):
            entries.append((a, ((ch.get("heading_path") or [a])[0])[:60]))
    index = {a: i for i, (a, _) in enumerate(entries)}
    keep: set[int] = set()
    for ch in served:
        i = index.get(_TEIL_RE.sub("", ch["anchor"]), 0)
        keep |= set(range(max(0, i - MAP_RADIUS), min(len(entries), i + MAP_RADIUS + 1)))
    shown = " · ".join(entries[i][1] for i in sorted(keep))
    return f"Map near the matches: {shown}. Read another with raw_read(['{t.qbase} § N'])."


def _section_map_read(mem: run_memory.RunMemory, t: _Target) -> str | None:
    """Fix C: a bare read of a long legal file serves its best-matching sections in full
    plus a map around them, instead of byte window 0 (the table of contents)."""
    best = _offered_unread(mem, t) + _ranked_unread(mem, t)
    if not best:
        return None
    served: list[dict[str, Any]] = []
    bodies: list[str] = []
    for ch in best[:2]:
        if bodies and sum(map(len, bodies)) + len(ch.get("text", "")) > RAW_READ_CAP:
            break
        served.append(ch)
        bodies.append(_serve_section(mem, t, ch))
    n = len({_TEIL_RE.sub("", c.get("anchor", "")) for c in _chunks(t)})
    head = f"## Raw file: {t.qbase} — section map ({n} sections; best matches read in full)"
    return "\n\n".join([head, *bodies, _map_line(t, served)])


def _is_law(t: _Target) -> bool:
    return any(c.get("anchor", "").startswith("§") for c in _chunks(t))


def _advance(mem: run_memory.RunMemory, t: _Target, why: str) -> str:
    """Fix D: instead of a stub, serve the next unread unit — a listed reference or the best
    unread section, else the next unread byte window; a stub only when nothing is left."""
    best = _offered_unread(mem, t) + _ranked_unread(mem, t)
    if best:
        marker = f"[memory: {why} → serving the next unread best match]"
        return _serve_section(mem, t, best[0], marker)
    with db_context.using_db(t.db):
        nxt = _next_unread_offset(mem, t.base, t.qbase)
    if nxt is not None:
        return _serve_window(mem, t, nxt, f"[memory: {why} → serving the next unread window]")
    return (
        f"## Raw file: {t.qbase}\n[memory] {t.qbase} fully explored for this question — "
        "submit_chat_answer or search another file."
    )


def _fresh_read(mem: run_memory.RunMemory, t: _Target, offset: int) -> str:
    if not t.section:
        return _serve_window(mem, t, offset)
    text = _raw_read_one(t.ref, offset=offset)
    mem.mark_read(_read_key(t.qbase, t.canon, offset))
    with db_context.using_db(t.db):
        ch = _resolve_section(t.base, t.section)
    if ch is None:
        return text
    _note_follow(mem, t.qbase, t.canon)
    return text + _ref_footer(mem, t, ch["anchor"], ch["text"])


def _memory_read(mem: run_memory.RunMemory, ref: str, offset: int) -> tuple[str, str]:
    """(output, qualified file) of one raw_read request under the run memory."""
    t = _target(ref)
    total = _raw_len(t)
    if total is None:
        return _raw_read_one(ref, offset=offset), t.qbase
    if not t.section and offset >= total > 0:
        why = f"requested offset {offset} is past the end; file has {total} chars"
        return _advance(mem, t, why), t.qbase
    prior = mem.seen_read(_read_key(t.qbase, t.canon, offset))
    if prior is not None:
        return _advance(mem, t, f"repeat of step {prior}"), t.qbase
    if not t.section and offset == 0 and total > RAW_READ_CAP and _is_law(t):
        mapped = _section_map_read(mem, t)
        if mapped is not None:
            return mapped, t.qbase
    return _fresh_read(mem, t, offset), t.qbase


def _pagination_nudge(mem: run_memory.RunMemory, files: list[str]) -> str | None:
    """The stop-paginating nudge once a file has RAW_READ_NUDGE_AFTER windows read."""
    over = sorted({f for f in files if len(_read_offsets(mem, f)) >= RAW_READ_NUDGE_AFTER})
    if not over:
        return None
    return (
        f"[memory] You have now read {RAW_READ_NUDGE_AFTER}+ windows of {', '.join(over)}. "
        "Stop paginating — if you have enough to answer, call submit_chat_answer "
        "now; otherwise raw_search a different file or call think_tool."
    )


@tool(description=RAW_READ_DESCRIPTION)
def raw_read(filenames: list[str], offset: int = 0) -> str:
    mem = run_memory.current()
    if mem is None:
        return _raw_read_impl(filenames, offset=offset)
    mem.tick()
    filenames = _names(filenames)
    if not filenames:
        return _raw_read_impl(filenames, offset=offset)
    results = [_memory_read(mem, f, int(offset or 0)) for f in filenames]
    out = [text for text, _ in results]
    _note_evidence(mem, out)
    nudge = _pagination_nudge(mem, [qbase for _, qbase in results])
    return "\n\n".join([*out, nudge] if nudge else out)


def _note_evidence(mem: run_memory.RunMemory, outputs: list[str]) -> None:
    """Add each read's sentences that match the run's query to its evidence ledger."""
    query = _run_query(mem)
    have = {s for _, s in mem.ledger}
    for text in outputs:
        for ref, sentence in evidence.extract(text, query):
            if sentence not in have and len(mem.ledger) < LEDGER_MAX:
                mem.ledger.append((ref, sentence))
                have.add(sentence)


@tool(description=SUBMIT_CHAT_DESCRIPTION)
def submit_chat_answer(answer: str, sources: list[str] | None = None) -> str:
    verdict = _submit_chat_impl(answer, sources)
    mem = run_memory.current()
    if mem is not None:  # the trace and bench rows show why a submission failed
        ok = verdict.startswith("ACCEPTED")
        head = verdict.strip().splitlines()[0][:300] if verdict.strip() else verdict
        mem.gate_events.append("submit accepted" if ok else f"submit rejected: {head}")
    return verdict


# --- evaluate_condition -------------------------------------------------------
#
# Deterministic logical-condition evaluator. The LLM extracts `facts` from
# natural-language source text and assembles a nested-dict `condition` tree;
# Python evaluates the tree without any further LLM judgement, eliminating
# hallucinations on threshold comparisons.

_CMP_OPS = {
    ">": _op.gt,
    ">=": _op.ge,
    "<": _op.lt,
    "<=": _op.le,
    "==": _op.eq,
    "!=": _op.ne,
}


def _fmt_val(v: object) -> str:
    if isinstance(v, str):
        return repr(v)
    return str(v)


_FACT_OPS = {*_CMP_OPS, "in", "contains", "between"}


def _eval_fact_op(o: str, node: dict[str, Any], facts: dict[str, Any]) -> tuple[bool, str]:
    """(result, trace line) of one leaf comparison against a named fact."""
    name = node["fact"]
    v = facts[name]
    if o in _CMP_OPS:
        t = node["value"]
        return bool(_CMP_OPS[o](v, t)), f"{name} {o} {_fmt_val(t)}  (= {_fmt_val(v)})"
    if o == "in":
        t = list(node["value"])
        return v in t, f"{name} in {t}  (= {_fmt_val(v)})"
    if o == "contains":
        t = node["value"]
        return str(t) in str(v), f"{name} contains {_fmt_val(t)}  (= {_fmt_val(v)})"
    low, high = node["low"], node["high"]  # "between"
    return low <= v <= high, (
        f"{name} between {_fmt_val(low)} and {_fmt_val(high)}  (= {_fmt_val(v)})"
    )


def _eval_node(node: object, facts: dict[str, Any], trace: list[tuple[bool, str]]) -> bool:
    if not isinstance(node, dict):
        trace.append((False, f"Error: condition node not a dict: {node!r}"))
        return False
    n = cast(dict[str, Any], node)
    o = n.get("op")
    try:
        if o in _FACT_OPS:
            r, line = _eval_fact_op(o, n, facts)
        elif o == "not":
            r = not _eval_node(n["arg"], facts, trace)
            line = f"NOT  → {r}"
        elif o in ("and", "or"):
            results = [_eval_node(a, facts, trace) for a in n["args"]]
            r = all(results) if o == "and" else any(results)
            line = f"{o.upper()}  → {r}"
        else:
            trace.append((False, f"Error: unknown op {o!r}"))
            return False
    except KeyError as exc:
        trace.append((False, f"Error: missing fact {exc}"))
        return False
    except TypeError as exc:
        trace.append((False, f"Error: type mismatch in op {o!r}: {exc}"))
        return False
    trace.append((r, line))
    return r


def _evaluate_condition_impl(facts: object, condition: object) -> str:
    if not isinstance(facts, dict) or not facts:
        return "Error: `facts` must be a non-empty dict."
    if not isinstance(condition, dict) or not condition:
        return "Error: `condition` must be a non-empty dict."
    fact_map = cast(dict[str, Any], facts)
    lines = ["## Facts", ""]
    for k, v in fact_map.items():
        lines.append(f"  {k} = {_fmt_val(v)}")
    trace: list[tuple[bool, str]] = []
    result = _eval_node(cast(dict[str, Any], condition), fact_map, trace)
    lines += ["", "## Condition trace", ""]
    for ok, text in trace:
        tag = "TRUE " if ok else "FALSE"
        lines.append(f"  [{tag}] {text}")
    lines += ["", f"## Result: {'PASS' if result else 'FAIL'}"]
    return "\n".join(lines)


@tool(description=EVALUATE_CONDITION_DESCRIPTION)
def evaluate_condition(facts: dict[str, Any], condition: dict[str, Any]) -> str:
    return _evaluate_condition_impl(facts, condition)


TOOLS = [
    wiki_search,
    wiki_read,
    raw_search,
    raw_read,
    tavily_search,
    fetch_webpage_content,
    think_tool,
    submit_final_answer,
    evaluate_condition,
]

# Deep chat stays raw-grounded, but can navigate the wiki (and thus follow
# `related:` links) to find which originals matter.
CHAT_TOOLS = [
    raw_search,
    raw_read,
    wiki_search,
    wiki_read,
    think_tool,
    submit_chat_answer,
    evaluate_condition,
]

# Plain-callable map (used by tests and the LangGraph ToolNode fallback path).
TOOL_FUNCTIONS: dict[str, Callable[..., str]] = {
    "wiki_search": _wiki_search_impl,
    "wiki_read": _wiki_read_impl,
    "tavily_search": _tavily_search_impl,
    "fetch_webpage_content": _fetch_webpage_impl,
    "think_tool": _think_impl,
    "submit_final_answer": _submit_final_impl,
    "raw_search": _raw_search_impl,
    "raw_read": _raw_read_impl,
    "submit_chat_answer": _submit_chat_impl,
    "evaluate_condition": _evaluate_condition_impl,
    "ontology_lookup": _ontology_lookup_impl,
}
