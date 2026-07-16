"""Deep chat agent — LangGraph state machine over data/raw/ originals.

Public surface: `run_chat_agent(question) -> Generator[step_dict, None, None]`
emitting the same step-dict shape as the research agent:
  {"type": "thought", "content": ...}
  {"type": "tool_call", "name": ..., "args": ...}
  {"type": "tool_result", "name": ..., "result": ...}
  {"type": "final_answer", "content": ..., "sources": list[str], "wiki_sources": list[str]}
  {"type": "error", "content": ...}

`sources` are cited data/raw/ originals; `wiki_sources` are cited wiki pages.
Gates are halved vs the research agent for ~2x speed.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Generator

from dotenv import load_dotenv
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_ollama import ChatOllama
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.prebuilt import ToolNode

import db_context
import lang
import ollama_client
import run_memory
import tools as tool_module
from prompts import (
    CHAT_AGENT_SYSTEM,
    CHAT_BUDGET_NUDGE,
    CHAT_FALLBACK_PROMPT,
    CHAT_FALLBACK_SYSTEM,
)

load_dotenv()

MIN_SEARCHES = int(os.getenv("CHAT_MIN_SEARCHES", "3"))
MIN_WORDS = int(os.getenv("CHAT_MIN_WORDS", "300"))
MIN_SOURCES = int(os.getenv("CHAT_MIN_SOURCES", "2"))
MAX_ITER = int(os.getenv("CHAT_MAX_ITERATIONS", "25"))
NUDGE_AT = int(os.getenv("CHAT_NUDGE_AT", str(MAX_ITER // 2 - 2)))
LLM_TIMEOUT = int(os.getenv("CHAT_LLM_TIMEOUT", "180"))
FALLBACK_NOTES_CAP = int(os.getenv("CHAT_FALLBACK_NOTES_CAP", "12000"))

_RAW_TEXT_EXTS = {".md", ".txt", ".html"}
_RAW_CITE_RE = re.compile(r"\[Source:\s*([^\]]+\.(?:md|txt|html))\s*\]")
# Permissive body so a DB-qualified page ("Investing::foo.md") still parses —
# DB names may contain spaces, so this can't be a \w-class.
_WIKI_CITE_RE = re.compile(r"\[Wiki:\s*([^\]\n]+?\.md)\s*\]")


def _cites(text: str, extra: list[str] | None = None) -> dict:
    """Split the citations in `text` into raw originals and wiki pages."""
    return {
        "sources": sorted(set(_RAW_CITE_RE.findall(text)) | set(extra or [])),
        "wiki_sources": sorted(set(_WIKI_CITE_RE.findall(text))),
    }


def _build_llm():
    return ChatOllama(
        model=ollama_client._QUERY_MODEL,
        base_url=ollama_client._HOST,
        temperature=0.3,
        timeout=LLM_TIMEOUT,
    ).bind_tools(tool_module.CHAT_TOOLS)


def _build_graph(llm, directive: str = ""):
    nudge = CHAT_BUDGET_NUDGE + (f"\n\n{directive}" if directive else "")

    def agent_node(state: MessagesState) -> dict:
        msgs = list(state["messages"])
        ai_count = sum(1 for m in msgs if isinstance(m, AIMessage))
        if ai_count >= NUDGE_AT:
            msgs = msgs + [HumanMessage(content=nudge)]
        return {"messages": [llm.invoke(msgs)]}

    def should_continue(state: MessagesState) -> str:
        last = state["messages"][-1]
        tool_calls = getattr(last, "tool_calls", None) or []
        if not tool_calls:
            return END
        for m in reversed(state["messages"]):
            if isinstance(m, ToolMessage) and m.name == "submit_chat_answer" \
                    and isinstance(m.content, str) and m.content.startswith("ACCEPTED"):
                return END
        return "tools"

    g = StateGraph(MessagesState)
    g.add_node("agent", agent_node)
    g.add_node("tools", ToolNode(tool_module.CHAT_TOOLS))
    g.add_edge(START, "agent")
    g.add_conditional_edges("agent", should_continue, {"tools": "tools", END: END})
    g.add_edge("tools", "agent")
    return g.compile()


def _build_raw_index_one() -> str:
    """One line per raw file in the *active* DB, names DB-qualified when needed."""
    raw = db_context.raw_dir()
    if not raw.exists():
        return ""
    lines = []
    for p in sorted(raw.iterdir()):
        if not (p.is_file() and p.suffix.lower() in _RAW_TEXT_EXTS):
            continue
        hint = ""
        try:
            with p.open("r", errors="replace") as fh:
                for ln in fh:
                    s = ln.strip()
                    if not s or s.startswith("<"):
                        continue
                    if s.startswith("#"):
                        hint = s.lstrip("# ").strip()[:100]
                        break
                    if not hint:
                        hint = s[:100]  # fallback to first prose line
        except Exception:
            pass
        lines.append(f"- {db_context.qualify(p.name)}" + (f" — {hint}" if hint else ""))
    return "\n".join(lines)


def _build_raw_index() -> str:
    """Raw-file index across the whole search scope, grouped by DB.

    Under a multi-DB scope every filename is DB-qualified, which is exactly the
    form raw_read/raw_search expect back — so the model can copy names verbatim.
    """
    scope = db_context.search_scope()
    if len(scope) == 1:
        return _build_raw_index_one()
    blocks = []
    for db in scope:
        with db_context.using_db(db):
            text = _build_raw_index_one()
        if text:
            blocks.append(f"Database {db}:\n{text}")
    return "\n\n".join(blocks)


def _system_prompt(directive: str = "") -> str:
    index_text = _build_raw_index()
    raw_block = (
        f"Original files available in data/raw/:\n{index_text}\n\n"
        if index_text else ""
    )
    return CHAT_AGENT_SYSTEM.format(
        raw_block=raw_block,
        language_directive=directive,
        min_searches=MIN_SEARCHES,
        min_words=MIN_WORDS,
        min_sources=MIN_SOURCES,
    )


def _ai_to_thought(msg: AIMessage):
    text = msg.content if isinstance(msg.content, str) else str(msg.content or "")
    if text.strip():
        yield {"type": "thought", "content": text}
    for tc in getattr(msg, "tool_calls", None) or []:
        yield {"type": "tool_call", "name": tc.get("name"), "args": tc.get("args") or {}}


def _tool_to_result(msg: ToolMessage):
    content = msg.content if isinstance(msg.content, str) else str(msg.content)
    yield {"type": "tool_result", "name": msg.name, "result": content}


def _with_iter_hint(content: str, recursion_hit: bool) -> str:
    """Append an end-of-answer hint when the run stopped on the iteration limit."""
    if not recursion_hit:
        return content
    return (
        f"{content}\n\n---\n"
        f"*Hint: the agent reached its iteration limit ({MAX_ITER}) before submitting "
        "a complete answer, so this response may be partial.*"
    )


def _gather_notes(all_messages) -> str:
    """Concatenate search/read tool results so a fallback pass can synthesise
    from what the agent gathered. Keeps the most recent notes within the cap."""
    blocks: list[str] = []
    for m in all_messages:
        if isinstance(m, ToolMessage):
            c = m.content if isinstance(m.content, str) else str(m.content)
            if c.strip():
                blocks.append(f"### {m.name}\n{c.strip()}")
    notes = "\n\n".join(blocks)
    return notes[-FALLBACK_NOTES_CAP:] if len(notes) > FALLBACK_NOTES_CAP else notes


def _synthesize_fallback(question: str, all_messages, directive: str = "") -> str:
    """Best-effort answer from gathered notes when the agent stalled without
    calling submit_chat_answer. Returns '' if there are no notes or on error."""
    notes = _gather_notes(all_messages)
    if not notes.strip():
        return ""
    prompt = CHAT_FALLBACK_PROMPT.format(question=question, notes=notes)
    if directive:
        prompt += f"\n\n{directive}"
    try:
        return ollama_client.generate(
            CHAT_FALLBACK_SYSTEM, prompt,
            temperature=0.3, model_id=ollama_client._QUERY_MODEL,
        ).strip()
    except Exception:
        return ""


def _extract_submitted_answer(messages) -> tuple[str, list[str]] | None:
    """Find the most recent submit_chat_answer call whose tool result was ACCEPTED.

    Returns (answer_text, sources) or None.
    """
    accepted_tool_idx = None
    for i in range(len(messages) - 1, -1, -1):
        m = messages[i]
        if isinstance(m, ToolMessage) and m.name == "submit_chat_answer" \
                and isinstance(m.content, str) and m.content.startswith("ACCEPTED"):
            accepted_tool_idx = i
            break
    if accepted_tool_idx is None:
        return None
    # The matching AIMessage with the tool_call is just before the ToolMessage.
    for j in range(accepted_tool_idx - 1, -1, -1):
        m = messages[j]
        if isinstance(m, AIMessage):
            for tc in getattr(m, "tool_calls", None) or []:
                if tc.get("name") == "submit_chat_answer":
                    args = tc.get("args") or {}
                    return args.get("answer", ""), list(args.get("sources") or [])
            break
    return None


def run_chat_agent(question: str) -> Generator[dict, None, None]:
    run_memory.begin_run()
    directive = lang.response_directive(question)
    try:
        llm = _build_llm()
        graph = _build_graph(llm, directive)
    except Exception as exc:
        yield {"type": "error", "content": f"Chat agent init failed: {exc}"}
        return

    init = {
        "messages": [
            SystemMessage(content=_system_prompt(directive)),
            HumanMessage(content=question),
        ]
    }
    config = {"recursion_limit": MAX_ITER}

    seen = 0
    final_msg: ToolMessage | AIMessage | None = None
    all_messages: list = []
    recursion_hit = False

    try:
        for chunk in graph.stream(init, config=config, stream_mode="values"):
            messages = chunk.get("messages", [])
            all_messages = messages
            for msg in messages[seen:]:
                if isinstance(msg, AIMessage):
                    yield from _ai_to_thought(msg)
                    final_msg = msg
                elif isinstance(msg, ToolMessage):
                    yield from _tool_to_result(msg)
                    final_msg = msg
            seen = len(messages)
    except Exception as exc:
        msg = str(exc)
        if "recursion" in msg.lower() or "GRAPH_RECURSION_LIMIT" in msg:
            recursion_hit = True
            yield {"type": "error",
                   "content": f"Recursion limit ({MAX_ITER}) reached. Returning best-effort partial answer."}
        else:
            yield {"type": "error", "content": msg}
            return

    submitted = _extract_submitted_answer(all_messages)
    if submitted is not None:
        answer, sources = submitted
        yield {"type": "final_answer",
               "content": _with_iter_hint(answer, recursion_hit), **_cites(answer, sources)}
        return

    # Clean exit: the final assistant message carries non-empty answer text.
    if isinstance(final_msg, AIMessage) and not getattr(final_msg, "tool_calls", None):
        text = final_msg.content if isinstance(final_msg.content, str) else str(final_msg.content)
        if text.strip():
            yield {"type": "final_answer",
                   "content": _with_iter_hint(text, recursion_hit), **_cites(text)}
            return

    _prefix = "(partial — recursion limit hit)" if recursion_hit else "(best-effort — quality gate not met)"

    # Best-effort: a submit_chat_answer draft that did not clear the quality gate.
    for m in reversed(all_messages):
        if isinstance(m, AIMessage):
            for tc in getattr(m, "tool_calls", None) or []:
                if tc.get("name") == "submit_chat_answer":
                    draft = ((tc.get("args") or {}).get("answer") or "").strip()
                    if draft:
                        yield {"type": "final_answer",
                               "content": _with_iter_hint(f"{_prefix}\n\n{draft}", recursion_hit),
                               **_cites(draft, (tc.get("args") or {}).get("sources") or [])}
                        return

    # Best-effort: the last non-empty assistant message (usually a reflection).
    for m in reversed(all_messages):
        if isinstance(m, AIMessage):
            text = m.content if isinstance(m.content, str) else str(m.content or "")
            if text.strip():
                yield {"type": "final_answer",
                       "content": _with_iter_hint(f"{_prefix}\n\n{text}", recursion_hit),
                       **_cites(text)}
                return

    # The agent gathered search results but never submitted or wrote prose
    # (common with small local models). Synthesise an answer from the notes
    # instead of discarding everything.
    synth = _synthesize_fallback(question, all_messages, directive)
    if synth:
        yield {
            "type": "final_answer",
            "content": _with_iter_hint(
                f"(assembled from gathered notes — the agent did not submit an answer)\n\n{synth}",
                recursion_hit,
            ),
            **_cites(synth),
            "note": "Fallback synthesis from gathered tool results.",
        }
        return

    if recursion_hit:
        yield {"type": "final_answer",
               "content": "(no answer — recursion limit hit before any reflection was emitted)",
               "sources": [], "wiki_sources": []}
        return

    yield {"type": "error",
           "content": f"Reached max iterations ({MAX_ITER}) without a submitted answer."}
