"""Tools for the deep researcher (LangGraph agent in agent.py).

Parallel-by-default I/O: tavily_search and fetch_webpage_content fan out via a
ThreadPoolExecutor. LLM calls remain sequential at the agent layer.
"""

from __future__ import annotations

import operator as _op
import os
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from langchain_core.tools import tool

import chunker
import db_context
import lex_index
import run_memory
import wiki_engine
from prompts import (
    EVALUATE_CONDITION_DESCRIPTION,
    FETCH_WEBPAGE_DESCRIPTION,
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
CHAT_MIN_WORDS = int(os.getenv("CHAT_MIN_WORDS", "300"))
CHAT_MIN_SOURCES = int(os.getenv("CHAT_MIN_SOURCES", "2"))
CONTENT_TRUNCATE = 2000
RAW_READ_CAP = 8000  # chars per raw_read call (per file, per offset window)

_URL_RE = re.compile(r"https?://[^\s\)\]]+")
_WIKI_CITE_RE = re.compile(r"\[Wiki:\s*([\w\-./]+\.md)\s*\]")
# Accept an optional trailing " §..." or " #..." section marker so the same file
# can be cited as multiple distinct sources, e.g. [Source: StrlSchG.md §62].
_RAW_CITE_RE = re.compile(
    r"\[Source:\s*([^\]\n]+?\.(?:md|txt|html)(?:\s*[§#][^\]\n]+?)?)\s*\]"
)


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "report"


def _format_tavily_result(idx: int, r: dict) -> str:
    content = (r.get("content") or "")[:CONTENT_TRUNCATE]
    url = r.get("url", "")
    return (
        f"Result {idx}: {r.get('title', '')}\n"
        f"Cite as: [Source: {url}]\n"
        f"Content: {content}\n---"
    )


def _tavily_one(query: str, max_results: int) -> str:
    from tavily import TavilyClient

    client = TavilyClient(api_key=os.getenv("TAVILY_API_KEY"))
    results = client.search(query, max_results=max_results, include_answer=True)
    parts = [f"## Query: {query}"]
    answer = results.get("answer")
    if answer:
        parts.append(f"Answer: {answer}")
    for i, r in enumerate(results.get("results", []), 1):
        parts.append(_format_tavily_result(i, r))
    return "\n".join(parts) if len(parts) > 1 else f"## Query: {query}\n(no results)"


def _tavily_search_impl(query=None, queries=None, max_results: int = 5) -> str:
    qs = queries if queries else ([query] if query else [])
    qs = [q for q in qs if q]
    if not qs:
        return "Error: provide `query` or `queries`."
    if len(qs) == 1:
        return _tavily_one(qs[0], max_results)
    with ThreadPoolExecutor(max_workers=PARALLELISM) as ex:
        outs = list(ex.map(lambda q: _tavily_one(q, max_results), qs))
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


def _fetch_webpage_impl(urls) -> str:
    if isinstance(urls, str):
        urls = [urls]
    urls = [u for u in (urls or []) if u]
    if not urls:
        return "Error: provide one or more urls."
    if len(urls) == 1:
        return _fetch_one(urls[0])
    with ThreadPoolExecutor(max_workers=PARALLELISM) as ex:
        outs = list(ex.map(_fetch_one, urls))
    return "\n\n".join(outs)


def _format_wiki_hit(idx: int, hit: dict) -> str:
    return (
        f"[Wiki hit {idx}]\n"
        f"file: {hit.get('filename', '')}\n"
        f"title: {hit.get('title', '')}\n"
        f"excerpt: {hit.get('excerpt', '')}\n---"
    )


def _wiki_search_one(query: str, max_results: int) -> str:
    hits = wiki_engine.search_wiki(query) or []
    parts = [f"## Wiki query: {query}"]
    if not hits:
        parts.append("(no results)")
        return "\n".join(parts)
    for i, h in enumerate(hits[:max_results], 1):
        parts.append(_format_wiki_hit(i, h))
    return "\n".join(parts)


def _wiki_search_impl(query=None, queries=None, max_results: int = 8) -> str:
    qs = queries if queries else ([query] if query else [])
    qs = [q for q in qs if q]
    if not qs:
        return "Error: provide `query` or `queries`."
    if len(qs) == 1:
        return _wiki_search_one(qs[0], max_results)
    with ThreadPoolExecutor(max_workers=PARALLELISM) as ex:
        outs = list(ex.map(lambda q: _wiki_search_one(q, max_results), qs))
    return "\n\n".join(outs)


def _wiki_read_one(filename: str) -> str:
    body = wiki_engine.read_page(filename)
    if len(body) > CONTENT_TRUNCATE * 2:
        body = body[: CONTENT_TRUNCATE * 2] + "\n...[truncated]"
    return f"## Wiki page: {filename}\n{body}"


def _wiki_read_impl(filenames) -> str:
    if isinstance(filenames, str):
        filenames = [filenames]
    filenames = [f for f in (filenames or []) if f]
    if not filenames:
        return "Error: provide one or more wiki filenames."
    if len(filenames) == 1:
        return _wiki_read_one(filenames[0])
    with ThreadPoolExecutor(max_workers=PARALLELISM) as ex:
        outs = list(ex.map(_wiki_read_one, filenames))
    return "\n\n".join(outs)


def _raw_search_one(query: str, max_results: int) -> str:
    parts = [f"## Raw query: {query}"]
    hits = lex_index.query(query, top_k=max_results)
    if not hits:
        parts.append("(no results — try a different keyword or a question phrasing)")
        return "\n".join(parts)
    for i, h in enumerate(hits, 1):
        anchor = h.get("anchor") or ""
        cite_suffix = f" {anchor}" if anchor else ""
        parts.append(
            f"[Raw hit {i}]\n"
            f"file: {h['source']}{cite_suffix}\n"
            f"chunk_id: {h['chunk_id']}\n"
            f"score: {h['score']}  matched: {', '.join(h['matched_terms'])}\n"
            f"excerpt: {h['preview']}\n---"
        )
    return "\n".join(parts)


def _raw_search_impl(query=None, queries=None, max_results: int = 6) -> str:
    qs = queries if queries else ([query] if query else [])
    qs = [q for q in qs if q]
    if not qs:
        return "Error: provide `query` or `queries`."
    if len(qs) == 1:
        return _raw_search_one(qs[0], max_results)
    with ThreadPoolExecutor(max_workers=PARALLELISM) as ex:
        outs = list(ex.map(lambda q: _raw_search_one(q, max_results), qs))
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
        return f[: m.start()].strip(), f[m.start():].strip()
    if wiki_engine.read_raw_source(f) is not None:  # bare file (may contain spaces)
        return f, ""
    m = re.match(r"^(\S+\.\w{1,5})\s+(.+)$", f)  # peel a trailing heading title
    if m and wiki_engine.read_raw_source(m.group(1)) is not None:
        return m.group(1), m.group(2).strip()
    return f, ""


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


def _resolve_section(base: str, section: str) -> dict | None:
    """Find the chunk in `base` whose anchor matches `section`, or None."""
    want = _norm_anchor(section)
    if not want:
        return None
    chunks = chunker.load_chunks(base)
    for ch in chunks:  # exact
        if _norm_anchor(ch.get("anchor", "")) == want:
            return ch
    for ch in chunks:  # prefix either direction (tolerate '(Teil n)' / title variants)
        a = _norm_anchor(ch.get("anchor", ""))
        if a and (a.startswith(want) or want.startswith(a)):
            return ch
    return None


def _format_section(base: str, ch: dict) -> str:
    anchor = ch.get("anchor", "")
    text = ch.get("text", "")
    if len(text) > RAW_READ_CAP:
        text = text[:RAW_READ_CAP] + "\n…[section truncated]"
    anchors = _section_anchors(base)
    nxt = None
    if anchor in anchors:
        i = anchors.index(anchor)
        nxt = anchors[i + 1] if i + 1 < len(anchors) else None
    footer = f"\n\n…[next section: read '{base} {nxt}']" if nxt else ""
    return f"## Raw file: {base} {anchor}\n{text}{footer}"


def _read_key(base: str, canon: str, offset: int) -> str:
    """Visited-memory key. Distinct sections (canon) get distinct keys so the
    guard no longer collapses every section read to the base file at offset 0."""
    if canon:
        return f"raw:{base}|sec={canon}:{int(offset or 0)}"
    return f"raw:{base}:{int(offset or 0)}"


def _read_canons(mem, base: str) -> set[str]:
    """Normalized section anchors of `base` already read this run."""
    prefix = f"raw:{base}|sec="
    return {k[len(prefix):].rsplit(":", 1)[0] for k in mem.reads if k.startswith(prefix)}


def _raw_read_one(filename: str, offset: int = 0) -> str:
    base, section = _split_filename(filename)
    if section:
        ch = _resolve_section(base, section)
        if ch is not None:
            return _format_section(base, ch)
    data = wiki_engine.read_raw_source(base)
    if data is None:
        return f"## Raw file: {filename}\n(not found)"
    body = data.decode("utf-8", errors="replace")
    total = len(body)
    start = max(0, int(offset or 0))
    if start >= total:
        return f"## Raw file: {base} (offset {start}/{total})\n(offset past end)"
    end = min(total, start + RAW_READ_CAP)
    window = body[start:end]
    header = f"## Raw file: {base} (bytes {start}-{end} of {total})"
    footer = ""
    if end < total:
        footer = f"\n\n…[truncated; pass offset={end} to continue]"
    elif start > 0:
        footer = "\n\n…[end of file]"
    return f"{header}\n{window}{footer}"


def _raw_read_impl(filenames, offset: int = 0) -> str:
    if isinstance(filenames, str):
        filenames = [filenames]
    filenames = [f for f in (filenames or []) if f]
    if not filenames:
        return "Error: provide one or more raw filenames."
    if len(filenames) == 1:
        return _raw_read_one(filenames[0], offset=offset)
    with ThreadPoolExecutor(max_workers=PARALLELISM) as ex:
        outs = list(ex.map(lambda f: _raw_read_one(f, offset=offset), filenames))
    return "\n\n".join(outs)


def _submit_chat_impl(answer: str, sources: list[str] | None = None) -> str:
    words = len(re.findall(r"\w+", answer or ""))
    cited = set(_RAW_CITE_RE.findall(answer or ""))
    extra = set(sources or [])
    unique = cited | extra
    if words < CHAT_MIN_WORDS:
        return (
            f"REJECTED: answer has {words} words, minimum is {CHAT_MIN_WORDS}. "
            "Continue researching and expand the answer."
        )
    if len(unique) < CHAT_MIN_SOURCES:
        return (
            f"REJECTED: answer cites {len(unique)} unique sources, minimum is "
            f"{CHAT_MIN_SOURCES}. Run more raw_search/raw_read and cite additional files."
        )
    return f"ACCEPTED: {words} words, {len(unique)} sources cited."


def _submit_final_impl(title: str, answer: str) -> str:
    words = len(re.findall(r"\w+", answer or ""))
    urls = set(_URL_RE.findall(answer or ""))
    wiki_cites = set(_WIKI_CITE_RE.findall(answer or ""))
    sources = urls | {f"wiki:{w}" for w in wiki_cites}
    if words < MIN_WORDS:
        return (
            f"REJECTED: report has {words} words, minimum is {MIN_WORDS}. "
            "Continue researching and expand the answer."
        )
    if len(sources) < MIN_URLS:
        return (
            f"REJECTED: report cites {len(sources)} unique sources "
            f"(URLs + [Wiki: ...] citations), minimum is {MIN_URLS}. "
            "Run more searches and cite additional sources."
        )
    dest_dir = db_context.wiki_dir() / "comparisons"
    dest_dir.mkdir(parents=True, exist_ok=True)
    date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    filename = f"report-{_slug(title)}.md"
    all_sources = sorted(urls) + sorted(f"wiki:{w}" for w in wiki_cites)
    body = (
        f'---\ntitle: "{title}"\ntype: report\ncreated: "{date}"\n'
        f"sources: {all_sources}\n---\n\n{answer}"
    )
    (dest_dir / filename).write_text(body)
    return (
        f"ACCEPTED: comparisons/{filename} ({words} words, "
        f"{len(urls)} urls, {len(wiki_cites)} wiki cites)"
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
    return "\n\n".join(stubs + [body]) if stubs else body


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


@tool(description=THINK_TOOL_DESCRIPTION)
def think_tool(reflection: str) -> str:
    return reflection


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
    return "\n\n".join(stubs + [body]) if stubs else body


@tool(description=RAW_READ_DESCRIPTION)
def raw_read(filenames: list[str], offset: int = 0) -> str:
    mem = run_memory.current()
    if mem is None:
        return _raw_read_impl(filenames, offset=offset)
    mem.tick()
    if isinstance(filenames, str):
        filenames = [filenames]
    filenames = [f for f in (filenames or []) if f]
    if not filenames:
        return _raw_read_impl(filenames, offset=offset)
    out: list[str] = []
    fresh: list[str] = []
    for f in filenames:
        base, section = _split_filename(f)
        canon = _norm_anchor(section) if section else ""
        key = _read_key(base, canon, offset)
        prior = mem.seen_read(key)
        if prior is None:
            fresh.append(f)
        elif canon:
            unread = [a for a in _section_anchors(base)
                      if _norm_anchor(a) not in _read_canons(mem, base)]
            menu = ", ".join(unread[:6]) if unread else "none left — pick a different file"
            out.append(
                f"## Raw file: {base} {section}\n"
                f"[memory] Already read this section at step {prior}. "
                f"Unread sections in {base}: {menu}. "
                "Read one of those, pick a different file, or call think_tool."
            )
        else:
            out.append(
                f"## Raw file: {base} (offset {int(offset or 0)})\n"
                f"[memory] Already read at step {prior} — do not re-fetch. "
                "Paginate with a new offset, pick a different file, or use think_tool."
            )
    if fresh:
        out.append(_raw_read_impl(fresh, offset=offset))
        for f in fresh:
            base, section = _split_filename(f)
            canon = _norm_anchor(section) if section else ""
            mem.mark_read(_read_key(base, canon, offset))
    return "\n\n".join(out)


@tool(description=SUBMIT_CHAT_DESCRIPTION)
def submit_chat_answer(answer: str, sources: list[str] | None = None) -> str:
    return _submit_chat_impl(answer, sources)


# --- evaluate_condition -------------------------------------------------------
#
# Deterministic logical-condition evaluator. The LLM extracts `facts` from
# natural-language source text and assembles a nested-dict `condition` tree;
# Python evaluates the tree without any further LLM judgement, eliminating
# hallucinations on threshold comparisons.

_CMP_OPS = {
    ">": _op.gt, ">=": _op.ge, "<": _op.lt, "<=": _op.le,
    "==": _op.eq, "!=": _op.ne,
}


def _fmt_val(v) -> str:
    if isinstance(v, str):
        return repr(v)
    return str(v)


def _eval_node(node, facts: dict, trace: list) -> bool:
    if not isinstance(node, dict):
        trace.append((False, f"Error: condition node not a dict: {node!r}"))
        return False
    o = node.get("op")
    try:
        if o in _CMP_OPS:
            name = node["fact"]
            v = facts[name]
            t = node["value"]
            r = bool(_CMP_OPS[o](v, t))
            trace.append((r, f"{name} {o} {_fmt_val(t)}  (= {_fmt_val(v)})"))
            return r
        if o == "in":
            name = node["fact"]
            v = facts[name]
            t = list(node["value"])
            r = v in t
            trace.append((r, f"{name} in {t}  (= {_fmt_val(v)})"))
            return r
        if o == "contains":
            name = node["fact"]
            v = facts[name]
            t = node["value"]
            r = str(t) in str(v)
            trace.append((r, f"{name} contains {_fmt_val(t)}  (= {_fmt_val(v)})"))
            return r
        if o == "between":
            name = node["fact"]
            v = facts[name]
            low, high = node["low"], node["high"]
            r = low <= v <= high
            trace.append((r, f"{name} between {_fmt_val(low)} and {_fmt_val(high)}  (= {_fmt_val(v)})"))
            return r
        if o == "not":
            inner = _eval_node(node["arg"], facts, trace)
            r = not inner
            trace.append((r, f"NOT  → {r}"))
            return r
        if o in ("and", "or"):
            results = [_eval_node(a, facts, trace) for a in node["args"]]
            r = all(results) if o == "and" else any(results)
            trace.append((r, f"{o.upper()}  → {r}"))
            return r
    except KeyError as exc:
        trace.append((False, f"Error: missing fact {exc}"))
        return False
    except TypeError as exc:
        trace.append((False, f"Error: type mismatch in op {o!r}: {exc}"))
        return False
    trace.append((False, f"Error: unknown op {o!r}"))
    return False


def _evaluate_condition_impl(facts: dict, condition: dict) -> str:
    if not isinstance(facts, dict) or not facts:
        return "Error: `facts` must be a non-empty dict."
    if not isinstance(condition, dict) or not condition:
        return "Error: `condition` must be a non-empty dict."
    lines = ["## Facts", ""]
    for k, v in facts.items():
        lines.append(f"  {k} = {_fmt_val(v)}")
    trace: list[tuple[bool, str]] = []
    result = _eval_node(condition, facts, trace)
    lines += ["", "## Condition trace", ""]
    for ok, text in trace:
        tag = "TRUE " if ok else "FALSE"
        lines.append(f"  [{tag}] {text}")
    lines += ["", f"## Result: {'PASS' if result else 'FAIL'}"]
    return "\n".join(lines)


@tool(description=EVALUATE_CONDITION_DESCRIPTION)
def evaluate_condition(facts: dict, condition: dict) -> str:
    return _evaluate_condition_impl(facts, condition)


TOOLS = [
    wiki_search,
    wiki_read,
    tavily_search,
    fetch_webpage_content,
    think_tool,
    submit_final_answer,
    evaluate_condition,
]

CHAT_TOOLS = [
    raw_search,
    raw_read,
    think_tool,
    submit_chat_answer,
    evaluate_condition,
]

# Plain-callable map (used by tests and the LangGraph ToolNode fallback path).
TOOL_FUNCTIONS = {
    "wiki_search": _wiki_search_impl,
    "wiki_read": _wiki_read_impl,
    "tavily_search": _tavily_search_impl,
    "fetch_webpage_content": _fetch_webpage_impl,
    "think_tool": lambda reflection: reflection,
    "submit_final_answer": _submit_final_impl,
    "raw_search": _raw_search_impl,
    "raw_read": _raw_read_impl,
    "submit_chat_answer": _submit_chat_impl,
    "evaluate_condition": _evaluate_condition_impl,
}
