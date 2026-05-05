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

from prompts import (
    FETCH_WEBPAGE_DESCRIPTION,
    SUBMIT_FINAL_DESCRIPTION,
    TAVILY_SEARCH_DESCRIPTION,
    THINK_TOOL_DESCRIPTION,
)

load_dotenv()

WIKI_DIR = Path(os.getenv("WIKI_DIR", "data/wiki"))
PARALLELISM = int(os.getenv("RESEARCH_PARALLELISM", "4"))
MIN_WORDS = int(os.getenv("RESEARCH_MIN_WORDS", "600"))
MIN_URLS = int(os.getenv("RESEARCH_MIN_URLS", "4"))
CONTENT_TRUNCATE = 2000

_URL_RE = re.compile(r"https?://[^\s\)\]]+")


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


def _submit_final_impl(title: str, answer: str) -> str:
    words = len(re.findall(r"\w+", answer or ""))
    urls = set(_URL_RE.findall(answer or ""))
    if words < MIN_WORDS:
        return (
            f"REJECTED: report has {words} words, minimum is {MIN_WORDS}. "
            "Continue researching and expand the answer."
        )
    if len(urls) < MIN_URLS:
        return (
            f"REJECTED: report cites {len(urls)} unique URLs, minimum is {MIN_URLS}. "
            "Run more searches and cite additional sources."
        )
    dest_dir = WIKI_DIR / "comparisons"
    dest_dir.mkdir(parents=True, exist_ok=True)
    date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    filename = f"report-{_slug(title)}.md"
    body = (
        f'---\ntitle: "{title}"\ntype: report\ncreated: "{date}"\n'
        f"sources: {sorted(urls)}\n---\n\n{answer}"
    )
    (dest_dir / filename).write_text(body)
    return f"ACCEPTED: comparisons/{filename} ({words} words, {len(urls)} urls)"


# --- LangChain tool wrappers (used by ChatOllama.bind_tools) --------------

@tool(description=TAVILY_SEARCH_DESCRIPTION)
def tavily_search(query: str = "", queries: list[str] | None = None, max_results: int = 5) -> str:
    return _tavily_search_impl(query=query, queries=queries, max_results=max_results)


@tool(description=FETCH_WEBPAGE_DESCRIPTION)
def fetch_webpage_content(urls: list[str]) -> str:
    return _fetch_webpage_impl(urls)


@tool(description=THINK_TOOL_DESCRIPTION)
def think_tool(reflection: str) -> str:
    return reflection


@tool(description=SUBMIT_FINAL_DESCRIPTION)
def submit_final_answer(title: str, answer: str) -> str:
    return _submit_final_impl(title, answer)


TOOLS = [tavily_search, fetch_webpage_content, think_tool, submit_final_answer]

# Plain-callable map (used by tests and the LangGraph ToolNode fallback path).
TOOL_FUNCTIONS = {
    "tavily_search": _tavily_search_impl,
    "fetch_webpage_content": _fetch_webpage_impl,
    "think_tool": lambda reflection: reflection,
    "submit_final_answer": _submit_final_impl,
}
