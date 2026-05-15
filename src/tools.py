"""Tools for the deep researcher (LangGraph agent in agent.py).

Parallel-by-default I/O: tavily_search and fetch_webpage_content fan out via a
ThreadPoolExecutor. LLM calls remain sequential at the agent layer.
"""

from __future__ import annotations

import os
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from langchain_core.tools import tool

import lex_index
import wiki_engine
from prompts import (
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

WIKI_DIR = Path(os.getenv("WIKI_DIR", "data/wiki"))
RAW_DIR = Path(os.getenv("RAW_DIR", "data/raw"))
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
    return (
        f"[Result {idx}]\n"
        f"Title: {r.get('title', '')}\n"
        f"URL: {r.get('url', '')}\n"
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
    facts = lex_index.facts_lookup(query)
    if facts:
        parts.append("### Direct facts")
        for i, f in enumerate(facts, 1):
            parts.append(
                f"[Fact {i}] {f.get('subject', '')} {f.get('kind', '')} = "
                f"{f.get('value', '')} {f.get('unit', '')} "
                f"(source: {f.get('source', '')} {f.get('anchor', '')})"
            )
    hits = lex_index.query(query, top_k=max_results)
    if not hits:
        if not facts:
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


def _raw_read_one(filename: str, offset: int = 0) -> str:
    # Strip optional " §..." / " #..." section suffix used in citations.
    base = re.sub(r"\s*[§#].*$", "", filename).strip()
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
    dest_dir = WIKI_DIR / "comparisons"
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


@tool(description=WIKI_SEARCH_DESCRIPTION)
def wiki_search(query: str = "", queries: list[str] | None = None, max_results: int = 8) -> str:
    return _wiki_search_impl(query=query, queries=queries, max_results=max_results)


@tool(description=WIKI_READ_DESCRIPTION)
def wiki_read(filenames: list[str]) -> str:
    return _wiki_read_impl(filenames)


@tool(description=THINK_TOOL_DESCRIPTION)
def think_tool(reflection: str) -> str:
    return reflection


@tool(description=SUBMIT_FINAL_DESCRIPTION)
def submit_final_answer(title: str, answer: str) -> str:
    return _submit_final_impl(title, answer)


@tool(description=RAW_SEARCH_DESCRIPTION)
def raw_search(query: str = "", queries: list[str] | None = None, max_results: int = 6) -> str:
    return _raw_search_impl(query=query, queries=queries, max_results=max_results)


@tool(description=RAW_READ_DESCRIPTION)
def raw_read(filenames: list[str], offset: int = 0) -> str:
    return _raw_read_impl(filenames, offset=offset)


@tool(description=SUBMIT_CHAT_DESCRIPTION)
def submit_chat_answer(answer: str, sources: list[str] | None = None) -> str:
    return _submit_chat_impl(answer, sources)


TOOLS = [
    wiki_search,
    wiki_read,
    tavily_search,
    fetch_webpage_content,
    think_tool,
    submit_final_answer,
]

CHAT_TOOLS = [
    raw_search,
    raw_read,
    think_tool,
    submit_chat_answer,
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
}
