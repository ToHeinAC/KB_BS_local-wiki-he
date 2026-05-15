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
RAW_TOKEN_MIN = 3
RAW_TOKEN_PREFIX = 6  # match first N chars of each token for German morphology tolerance
RAW_MAX_EXCERPTS_PER_FILE = 3

_URL_RE = re.compile(r"https?://[^\s\)\]]+")
_WIKI_CITE_RE = re.compile(r"\[Wiki:\s*([\w\-./]+\.md)\s*\]")
# Accept an optional trailing " §..." or " #..." section marker so the same file
# can be cited as multiple distinct sources, e.g. [Source: StrlSchG.md §62].
_RAW_CITE_RE = re.compile(
    r"\[Source:\s*([^\]\n]+?\.(?:md|txt|html)(?:\s*[§#][^\]\n]+?)?)\s*\]"
)
_RAW_TEXT_EXTS = {".md", ".txt", ".html"}


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


def _raw_files() -> list[Path]:
    if not RAW_DIR.exists():
        return []
    return [p for p in sorted(RAW_DIR.iterdir())
            if p.is_file() and p.suffix.lower() in _RAW_TEXT_EXTS]


def _tokenize_query(query: str) -> list[str]:
    raw = re.split(r"\s+", (query or "").strip().lower())
    seen: list[str] = []
    for tok in raw:
        tok = tok.strip("\"'.,;:!?()[]{}<>")
        if len(tok) < RAW_TOKEN_MIN:
            continue
        stem = tok[:RAW_TOKEN_PREFIX]
        if stem not in seen:
            seen.append(stem)
    return seen


def _window_excerpt(body: str, idx: int, before: int = 80, after: int = 120) -> str:
    start = max(0, idx - before)
    end = min(len(body), idx + after)
    s = body[start:end].replace("\n", " ").strip()
    if start > 0:
        s = "…" + s
    if end < len(body):
        s = s + "…"
    return s


def _raw_search_one(query: str, max_results: int) -> str:
    parts = [f"## Raw query: {query}"]
    stems = _tokenize_query(query)
    if not stems:
        parts.append("(empty or too-short query)")
        return "\n".join(parts)

    scored: list[tuple[int, str, list[str]]] = []  # (score, filename, excerpts)
    for path in _raw_files():
        try:
            body = path.read_text(errors="replace")
        except Exception:
            continue
        body_lower = body.lower()
        excerpts: list[str] = []
        score = 0
        for stem in stems:
            idx = body_lower.find(stem)
            if idx == -1:
                continue
            score += 1
            if len(excerpts) < RAW_MAX_EXCERPTS_PER_FILE:
                excerpts.append(_window_excerpt(body, idx))
        if score == 0 and not any(s in path.name.lower() for s in stems):
            continue
        if score == 0:  # filename-only match — still useful to surface
            excerpts.append(_window_excerpt(body, 0, before=0, after=160))
            score = 1
        scored.append((score, path.name, excerpts))

    if not scored:
        parts.append("(no results — try a single stem keyword, e.g. 'Rückstand', 'Freigabe')")
        return "\n".join(parts)

    scored.sort(key=lambda t: (-t[0], t[1]))
    out_idx = 1
    for score, fname, excerpts in scored[:max_results]:
        for ex in excerpts:
            parts.append(
                f"[Raw hit {out_idx}]\n"
                f"file: {fname}\n"
                f"score: {score} / {len(stems)} stems\n"
                f"excerpt: {ex}\n---"
            )
            out_idx += 1
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
