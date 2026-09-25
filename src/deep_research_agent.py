"""Deep Research (web mode) — adapter over the vendored open_deep_research graph.

Second Research mode alongside the local-first `agent.run_research_agent` ("Quick").
This one is **web-only**: a supervisor decomposes the question, fans out researcher
subgraphs over Tavily, and synthesises a cited report. It never reads the wiki or
`data/raw/` — its citations are web URLs.

The graph itself is vendored, unmodified, under `src/vendor/open_deep_research/`
(MIT; see `src/vendor/README.md`). We drive it purely through `Configuration`:
all four model roles point at local Ollama, clarification is off, and the
concurrency/iteration budgets come from `DEEP_RESEARCH_*` env vars.

Public surface mirrors `agent.run_research_agent` so the Streamlit Research page
can dispatch to either mode through the same renderer:
  {"type": "thought", "content": ...}
  {"type": "tool_call", "name": ..., "args": ...}
  {"type": "tool_result", "name": ..., "result": ..., "sources": [{url, title}]}
  {"type": "notice", "content": ...}          # mode-level status (e.g. fallback)
  {"type": "final_answer", "content": ..., "report_path": str | None}
  {"type": "error", "content": ...}

Async is deliberate here: the vendored graph is natively async (`asyncio.gather`
across researcher subgraphs). The project's general no-async rule is waived for
this feature (see docs/deep_research.md). `run_deep_research` stays a plain sync
generator — it owns a private event loop and pumps `astream` one event at a time,
so Streamlit's synchronous rerun model is unaffected.
"""

from __future__ import annotations

import asyncio
import os
import re
from collections.abc import Generator
from datetime import UTC, datetime
from typing import Any

import frontmatter  # pyright: ignore[reportMissingTypeStubs]
from dotenv import load_dotenv
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

import agent as quick_agent
import db_context
import lang
import okf
import ollama_client
from prompts import DEEP_RESEARCH_FALLBACK_NOTICE, DEEP_RESEARCH_QUESTION
from vendor.open_deep_research.configuration import SearchAPI
from vendor.open_deep_research.deep_researcher import deep_researcher

load_dotenv()

MODEL = os.getenv("DEEP_RESEARCH_MODEL") or ollama_client.QUERY_MODEL
CONCURRENCY = int(os.getenv("DEEP_RESEARCH_CONCURRENCY", "1"))
MAX_ITERATIONS = int(os.getenv("DEEP_RESEARCH_MAX_ITERATIONS", "4"))
MAX_TOOL_CALLS = int(os.getenv("DEEP_RESEARCH_MAX_TOOL_CALLS", "6"))
MAX_TOKENS = int(os.getenv("DEEP_RESEARCH_MAX_TOKENS", "8192"))
CLARIFICATION = os.getenv("DEEP_RESEARCH_CLARIFICATION", "false").lower() == "true"

# Upstream's tavily_search formats every hit as
#   --- SOURCE 3: Some Page Title ---
#   URL: https://example.org/x
# which is where the Perplexity-style citation cards come from.
_SOURCE_RE = re.compile(r"^--- SOURCE \d+: (.*?) ---\s*\nURL: (\S+)", re.MULTILINE)

# One `tavily_search` call emits exactly one of these headers, whatever the
# number of queries it batched. Counting them is the only reliable way to size
# the search effort: the researcher subgraphs never stream their tool calls, and
# `compress_research`'s prose summary of "queries made" is LLM-written guesswork.
_SEARCH_CALL_RE = re.compile(r"^(Search results:|No valid search results found)", re.MULTILINE)

# URLs cited in the finished report (upstream ends it with `### Sources`,
# `[n] Title: URL`). Trailing sentence punctuation is stripped by the caller.
_URL_RE = re.compile(r"https?://[^\s<>\])}\"']+")

# `final_report_generation` swallows its own exceptions into the report string
# rather than raising, so a failed run looks like a successful one.
_REPORT_ERROR_PREFIX = "Error generating final report"

# State keys whose values are message lists worth streaming to the UI.
_MESSAGE_KEYS = ("messages", "supervisor_messages", "researcher_messages")

# What each of the supervisor's tools actually does. Surfaced to the UI as a
# caption so the trace is readable without knowing the vendored graph.
#
# `ResearchComplete` is the one that looks broken but isn't: it is a *sentinel*
# — a pydantic model with **zero fields** (`state.py`), so `args` is correctly
# and always `{}`. `supervisor_tools` matches on its name and jumps straight to
# END without appending a ToolMessage, so it is also the one tool call that
# never gets a result. Empty args + no result is the expected shape, not a
# failure; the UI must not render it as `ResearchComplete — {}`.
TOOL_NOTES = {
    "ConductResearch": "Delegates one sub-topic to a researcher subgraph (its own search loop).",
    "think_tool": "Strategic reflection — recorded in the transcript, nothing is executed.",
    "ResearchComplete": (
        "Sentinel with no arguments and no result: the supervisor is signalling that "
        "the research phase is done, and the graph moves on to writing the report."
    ),
    "web_search": "Tavily results, summarised per URL by the local model.",
}


def _configurable() -> dict[str, Any]:
    """Our overrides for the vendored `Configuration` (all four roles → Ollama).

    NOTE: `Configuration.from_runnable_config` reads `os.environ[FIELD.upper()]`
    *before* this dict, so a stray `RESEARCH_MODEL` / `SEARCH_API` in the
    environment would win. That is why our knobs are namespaced `DEEP_RESEARCH_*`.
    """
    model = f"ollama:{MODEL}"
    return {
        "research_model": model,
        "final_report_model": model,
        "compression_model": model,
        "summarization_model": model,
        "research_model_max_tokens": MAX_TOKENS,
        "final_report_model_max_tokens": MAX_TOKENS,
        "compression_model_max_tokens": MAX_TOKENS,
        "summarization_model_max_tokens": MAX_TOKENS,
        "search_api": SearchAPI.TAVILY.value,
        "allow_clarification": CLARIFICATION,
        "max_concurrent_research_units": CONCURRENCY,
        "max_researcher_iterations": MAX_ITERATIONS,
        "max_react_tool_calls": MAX_TOOL_CALLS,
    }


def _extract_sources(text: str) -> list[dict[str, Any]]:
    """Pull {url, title} citation cards out of a web_search tool result."""
    return [{"title": t.strip(), "url": u} for t, u in _SOURCE_RE.findall(text or "")]


def _report_urls(report: str) -> set[str]:
    """Unique URLs the finished report actually cites (its `### Sources` list
    plus any inline links). Trailing sentence punctuation is stripped so
    `…example.org/x.` and `…example.org/x` count once."""
    return {u.rstrip(".,;:") for u in _URL_RE.findall(report or "")}


def _slug(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (text or "report").lower()).strip("-")
    return (s or "report")[:60]


def _save_report(question: str, report: str, sources: list[dict[str, Any]]) -> str | None:
    """Persist the report to `comparisons/` in the same shape as the Quick path
    (`tools._submit_final_impl`), so the Research page reads it back unchanged.

    The frontmatter is **serialised by the YAML writer, never f-string
    interpolated**. A question like `... the thesis "potential 100x baggers"`
    embeds a double quote; hand-built `title: "{question}"` then emits invalid
    YAML, `okf.apply_to_page` fails open and writes it through unchanged, and
    the page becomes unreadable — which the Research page used to render as a
    blank result.
    """
    try:
        dest_dir = db_context.wiki_dir() / "comparisons"
        dest_dir.mkdir(parents=True, exist_ok=True)
        filename = f"report-{_slug(question)}.md"
        post = frontmatter.Post(
            report,
            title=question[:120],
            type="report",
            created=datetime.now(UTC).strftime("%Y-%m-%d"),
            sources=sorted({s["url"] for s in sources}),
        )
        (dest_dir / filename).write_text(
            okf.apply_to_page(frontmatter.dumps(post), db=db_context.get_active_db())
        )
        return f"comparisons/{filename}"
    except Exception:
        return None


def _message_steps(msg) -> Generator[dict[str, Any], None, None]:
    """Map one LangChain message to step-dicts (mirrors agent._ai_to_thought)."""
    if isinstance(msg, AIMessage):
        text = msg.content if isinstance(msg.content, str) else str(msg.content or "")
        if text.strip():
            yield {"type": "thought", "label": "Supervisor reasoning", "content": text}
        for tc in getattr(msg, "tool_calls", None) or []:
            name = tc.get("name")
            yield {
                "type": "tool_call",
                "name": name,
                "args": tc.get("args") or {},
                "note": TOOL_NOTES.get(name, ""),
                "terminal": name == "ResearchComplete",
            }
    elif isinstance(msg, ToolMessage):
        content = msg.content if isinstance(msg.content, str) else str(msg.content)
        yield {
            "type": "tool_result",
            "name": msg.name,
            "result": content,
            "note": TOOL_NOTES.get(msg.name, ""),
            "sources": _extract_sources(content),
            "searches": len(_SEARCH_CALL_RE.findall(content)),
        }


def _update_steps(update: dict[str, Any]) -> Generator[dict[str, Any], None, None]:
    """Map one node's state delta to step-dicts.

    `raw_notes` is where the web citations actually live. The researcher
    subgraphs are driven with `researcher_subgraph.ainvoke(...)` inside
    `supervisor_tools`, not wired as graph nodes, so their `web_search` tool
    messages never reach the parent stream even with `subgraphs=True`. What does
    come back is `raw_notes` — the concatenated researcher tool output, still
    carrying upstream's `--- SOURCE n: … ---/URL:` blocks.
    """
    brief = update.get("research_brief")
    if brief:
        yield {"type": "thought", "label": "Research brief", "content": brief}
    compressed = update.get("compressed_research")
    if compressed:
        yield {"type": "thought", "label": "Sub-topic findings", "content": compressed}
    for notes in update.get("raw_notes") or []:
        sources = _extract_sources(notes)
        if sources:
            yield {
                "type": "tool_result",
                "name": "web_search",
                "result": notes,
                "note": TOOL_NOTES["web_search"],
                "sources": sources,
                "searches": len(_SEARCH_CALL_RE.findall(notes)),
            }
    for key in _MESSAGE_KEYS:
        for msg in update.get(key) or []:
            yield from _message_steps(msg)


def _step_key(step: dict[str, Any]):
    """Identity used to drop replayed steps.

    A parent node's update echoes the whole accumulated sub-state (the
    `research_supervisor` node re-emits every supervisor message the subgraph
    already streamed), so the same step arrives more than once per run.

    Text-bearing steps are keyed on their body alone, ignoring type and name:
    `supervisor_tools` wraps each researcher's `compressed_research` in a
    `ConductResearch` ToolMessage, so the identical text would otherwise show up
    twice — once as the "Sub-topic findings" thought, once as a tool result.
    """
    if step["type"] == "tool_call":
        return ("tool_call", step["name"], str(step["args"]))
    return ("body", (step.get("content") or step.get("result", ""))[:400])


def _astream_sync(question: str, directive: str):
    """Pump the async graph from a private event loop, yielding `(node, update)`.

    Streamlit reruns are synchronous, so the loop is created and closed inside
    this generator's lifetime — no background thread, no queue.
    """
    payload = DEEP_RESEARCH_QUESTION.format(question=question, language_directive=directive)
    stream_args = dict(
        input={"messages": [HumanMessage(content=payload)]},
        config={"configurable": _configurable(), "recursion_limit": 100},
        stream_mode="updates",
        subgraphs=True,
    )
    loop = asyncio.new_event_loop()
    agen = None
    try:
        asyncio.set_event_loop(loop)
        agen = deep_researcher.astream(**stream_args)
        while True:
            try:
                _ns, update = loop.run_until_complete(agen.__anext__())
            except StopAsyncIteration:
                break
            for node, delta in (update or {}).items():
                if isinstance(delta, dict):
                    yield node, delta
    finally:
        try:
            if agen is not None:
                loop.run_until_complete(agen.aclose())
            loop.run_until_complete(loop.shutdown_asyncgens())
        except Exception:
            pass
        asyncio.set_event_loop(None)
        loop.close()


def _run_graph(question: str, directive: str) -> Generator[dict[str, Any], None, None]:
    """Stream the vendored graph. Ends with a `final_answer`, or a `notice`
    carrying the reason Deep mode could not produce one."""
    report, sources, failure = "", [], ""
    emitted: set[Any] = set()
    tasks = searches = 0
    try:
        for node, delta in _astream_sync(question, directive):
            if node == "final_report_generation":
                # Its `messages` delta is the finished report echoed as an
                # AIMessage; emitting it would print the whole report twice.
                report = delta.get("final_report") or ""
                continue
            for step in _update_steps(delta):
                key = _step_key(step)
                if key in emitted:
                    continue
                emitted.add(key)
                if step["type"] == "tool_result":
                    sources.extend(step["sources"])
                    searches += step.get("searches", 0)
                elif step["type"] == "tool_call" and step["name"] == "ConductResearch":
                    tasks += 1
                yield step
    except Exception as exc:
        failure = f"{type(exc).__name__}: {exc}"

    if failure:
        yield {"type": "notice", "content": DEEP_RESEARCH_FALLBACK_NOTICE.format(reason=failure)}
        return
    if not report.strip() or report.startswith(_REPORT_ERROR_PREFIX):
        reason = report.strip() or "the graph finished without writing a report"
        yield {"type": "notice", "content": DEEP_RESEARCH_FALLBACK_NOTICE.format(reason=reason)}
        return

    # De-duplicate citation cards by URL, preserving first-seen order.
    seen, uniq = set(), []
    for s in sources:
        if s["url"] not in seen:
            seen.add(s["url"])
            uniq.append(s)
    yield {
        "type": "final_answer",
        "content": report,
        "report_path": _save_report(question, report, uniq),
        "sources": uniq,
        "metrics": {
            "tasks": tasks,
            "searches": searches,
            "sources_checked": len(uniq),
            "sources_cited": len(_report_urls(report)),
        },
    }


def run_deep_research(
    question: str, wiki_context: str = ""
) -> Generator[dict[str, Any], None, None]:
    """Web-only Deep Research over the vendored open_deep_research graph.

    `wiki_context` is ignored by Deep mode itself (it is web-only) and is passed
    through only to the Quick-mode fallback, so the Research page can dispatch to
    either mode with one call signature.
    """
    if not os.getenv("TAVILY_API_KEY"):
        yield {"type": "error", "content": "TAVILY_API_KEY not set — Deep Research is web-only."}
        return

    # `init_chat_model("ollama:<tag>")` builds a ChatOllama with base_url=None,
    # and the ollama SDK then falls back to $OLLAMA_HOST. That env var is the
    # only seam for the host, since Configuration makes only model/max_tokens/
    # api_key configurable.
    os.environ["OLLAMA_HOST"] = ollama_client.host()

    directive = lang.response_directive(question)
    fell_back = False
    for step in _run_graph(question, directive):
        if step["type"] == "notice":
            fell_back = True
        yield step

    if fell_back:
        yield from quick_agent.run_research_agent(question, wiki_context)
