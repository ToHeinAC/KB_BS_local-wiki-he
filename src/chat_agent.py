"""Deep chat agent — LangGraph state machine over data/raw/ originals.

Public surface: `run_chat_agent(question) -> Generator[step_dict, None, None]`
emitting the same step-dict shape as the research agent:
  {"type": "thought", "content": ...}
  {"type": "tool_call", "name": ..., "args": ...}
  {"type": "tool_result", "name": ..., "result": ...}
  {"type": "final_answer", "content": ..., "sources": list[str]}
  {"type": "error", "content": ...}

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

import ollama_client
import tools as tool_module
from prompts import CHAT_AGENT_SYSTEM

load_dotenv()

MIN_SEARCHES = int(os.getenv("CHAT_MIN_SEARCHES", "3"))
MIN_WORDS = int(os.getenv("CHAT_MIN_WORDS", "300"))
MIN_SOURCES = int(os.getenv("CHAT_MIN_SOURCES", "2"))
MAX_ITER = int(os.getenv("CHAT_MAX_ITERATIONS", "25"))
LLM_TIMEOUT = int(os.getenv("CHAT_LLM_TIMEOUT", "180"))

RAW_DIR = Path(os.getenv("RAW_DIR", "data/raw"))
_RAW_TEXT_EXTS = {".md", ".txt", ".html"}
_RAW_CITE_RE = re.compile(r"\[Source:\s*([^\]]+\.(?:md|txt|html))\s*\]")


def _build_llm():
    return ChatOllama(
        model=ollama_client._MODEL,
        base_url=ollama_client._HOST,
        temperature=0.3,
        timeout=LLM_TIMEOUT,
    ).bind_tools(tool_module.CHAT_TOOLS)


def _build_graph(llm):
    def agent_node(state: MessagesState) -> dict:
        return {"messages": [llm.invoke(state["messages"])]}

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


def _build_raw_index() -> str:
    if not RAW_DIR.exists():
        return ""
    lines = []
    for p in sorted(RAW_DIR.iterdir()):
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
        lines.append(f"- {p.name}" + (f" — {hint}" if hint else ""))
    return "\n".join(lines)


def _system_prompt() -> str:
    index_text = _build_raw_index()
    raw_block = (
        f"Original files available in data/raw/:\n{index_text}\n\n"
        if index_text else ""
    )
    return CHAT_AGENT_SYSTEM.format(
        raw_block=raw_block,
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
    try:
        llm = _build_llm()
        graph = _build_graph(llm)
    except Exception as exc:
        yield {"type": "error", "content": f"Chat agent init failed: {exc}"}
        return

    init = {
        "messages": [
            SystemMessage(content=_system_prompt()),
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
        cited = sorted(set(_RAW_CITE_RE.findall(answer)) | set(sources))
        yield {"type": "final_answer", "content": answer, "sources": cited}
        return

    if isinstance(final_msg, AIMessage) and not getattr(final_msg, "tool_calls", None):
        text = final_msg.content if isinstance(final_msg.content, str) else str(final_msg.content)
        cited = sorted(set(_RAW_CITE_RE.findall(text)))
        yield {"type": "final_answer", "content": text, "sources": cited}
        return

    if recursion_hit:
        # Surface the last AIMessage text (likely a partial reflection) as a partial answer
        for m in reversed(all_messages):
            if isinstance(m, AIMessage):
                text = m.content if isinstance(m.content, str) else str(m.content or "")
                if text.strip():
                    cited = sorted(set(_RAW_CITE_RE.findall(text)))
                    yield {"type": "final_answer",
                           "content": f"(partial — recursion limit hit)\n\n{text}",
                           "sources": cited}
                    return
        yield {"type": "final_answer",
               "content": "(no answer — recursion limit hit before any reflection was emitted)",
               "sources": []}
        return

    yield {"type": "error",
           "content": f"Reached max iterations ({MAX_ITER}) without a submitted answer."}
