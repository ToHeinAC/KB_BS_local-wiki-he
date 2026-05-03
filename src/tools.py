"""Tool definitions and functions for the ReAct research agent."""

import os
import re
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

from prompts import REPORT_WRITER_DESCRIPTION, TAVILY_SEARCH_DESCRIPTION

load_dotenv()

WIKI_DIR = Path(os.getenv("WIKI_DIR", "data/wiki"))


def tavily_search(query: str, max_results: int = 5) -> str:
    from tavily import TavilyClient

    client = TavilyClient(api_key=os.getenv("TAVILY_API_KEY"))
    results = client.search(query, max_results=max_results, include_answer=True)
    lines = []
    for i, r in enumerate(results.get("results", []), 1):
        lines.append(
            f"[Result {i}]\nTitle: {r.get('title', '')}\n"
            f"URL: {r.get('url', '')}\nContent: {r.get('content', '')}\n---"
        )
    return "\n".join(lines) or "(no results)"


def report_writer(title: str, content: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    dest_dir = WIKI_DIR / "comparisons"
    dest_dir.mkdir(parents=True, exist_ok=True)
    date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    filename = f"report-{slug}.md"
    body = f'---\ntitle: "{title}"\ntype: report\ncreated: "{date}"\n---\n\n{content}'
    (dest_dir / filename).write_text(body)
    return f"Report saved: comparisons/{filename}"


TAVILY_SEARCH_SCHEMA = {
    "type": "function",
    "function": {
        "name": "tavily_search",
        "description": TAVILY_SEARCH_DESCRIPTION,
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "The search query string"},
                "max_results": {
                    "type": "integer",
                    "description": "Number of results to return (1-10)",
                    "default": 5,
                },
            },
            "required": ["query"],
        },
    },
}

REPORT_WRITER_SCHEMA = {
    "type": "function",
    "function": {
        "name": "report_writer",
        "description": REPORT_WRITER_DESCRIPTION,
        "parameters": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Report title"},
                "content": {
                    "type": "string",
                    "description": "Full markdown content of the report, with sources cited",
                },
            },
            "required": ["title", "content"],
        },
    },
}

TOOLS = [TAVILY_SEARCH_SCHEMA, REPORT_WRITER_SCHEMA]
TOOL_FUNCTIONS = {"tavily_search": tavily_search, "report_writer": report_writer}
