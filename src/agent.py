"""Deep research agent — LangGraph state machine, ChatOllama backend.

Public surface preserved: `run_research_agent(question, wiki_context) -> Generator[step_dict, None, None]`
emitting the same step-dict shape the Streamlit Research page expects:
  {"type": "thought", "content": ...}
  {"type": "tool_call", "name": ..., "args": ...}
  {"type": "tool_result", "name": ..., "result": ...}
  {"type": "final_answer", "content": ..., "report_path": str | None}
  {"type": "error", "content": ...}
"""

from __future__ import annotations

import os
from typing import Generator

from dotenv import load_dotenv
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_ollama import ChatOllama
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.prebuilt import ToolNode

import ollama_client
import tools as tool_module
from prompts import RESEARCHER_INSTRUCTIONS

load_dotenv()

MIN_SEARCHES = int(os.getenv("RESEARCH_MIN_SEARCHES", "6"))
MIN_WORDS = int(os.getenv("RESEARCH_MIN_WORDS", "600"))
MIN_URLS = int(os.getenv("RESEARCH_MIN_URLS", "4"))
MAX_ITER = int(os.getenv("RESEARCH_MAX_ITERATIONS", "40"))
LLM_TIMEOUT = int(os.getenv("RESEARCH_LLM_TIMEOUT", "300"))


def _build_llm():
    return ChatOllama(
        model=ollama_client._MODEL,
        base_url=ollama_client._HOST,
        temperature=0.3,
        timeout=LLM_TIMEOUT,
    ).bind_tools(tool_module.TOOLS)


def _build_graph(llm):
    def agent_node(state: MessagesState) -> dict:
        return {"messages": [llm.invoke(state["messages"])]}

    def should_continue(state: MessagesState) -> str:
        last = state["messages"][-1]
        tool_calls = getattr(last, "tool_calls", None) or []
        if not tool_calls:
            return END
        # End immediately once submit_final_answer was just accepted.
        for m in reversed(state["messages"]):
            if isinstance(m, ToolMessage) and m.name == "submit_final_answer" \
                    and isinstance(m.content, str) and m.content.startswith("ACCEPTED"):
                return END
        return "tools"

    g = StateGraph(MessagesState)
    g.add_node("agent", agent_node)
    g.add_node("tools", ToolNode(tool_module.TOOLS))
    g.add_edge(START, "agent")
    g.add_conditional_edges("agent", should_continue, {"tools": "tools", END: END})
    g.add_edge("tools", "agent")
    return g.compile()


def _system_prompt(wiki_context: str) -> str:
    wiki_block = f"Wiki context:\n{wiki_context}\n\n" if wiki_context else ""
    return RESEARCHER_INSTRUCTIONS.format(
        wiki_block=wiki_block,
        min_searches=MIN_SEARCHES,
        min_words=MIN_WORDS,
        min_urls=MIN_URLS,
    )


def _ai_to_thought(msg: AIMessage):
    text = msg.content if isinstance(msg.content, str) else str(msg.content or "")
    if text.strip():
        yield {"type": "thought", "content": text}
    for tc in getattr(msg, "tool_calls", None) or []:
        yield {
            "type": "tool_call",
            "name": tc.get("name"),
            "args": tc.get("args") or {},
        }


def _tool_to_result(msg: ToolMessage):
    content = msg.content if isinstance(msg.content, str) else str(msg.content)
    yield {"type": "tool_result", "name": msg.name, "result": content}


def run_research_agent(question: str, wiki_context: str = "") -> Generator[dict, None, None]:
    try:
        llm = _build_llm()
        graph = _build_graph(llm)
    except Exception as exc:
        yield {"type": "error", "content": f"Agent init failed: {exc}"}
        return

    init = {
        "messages": [
            SystemMessage(content=_system_prompt(wiki_context)),
            HumanMessage(content=question),
        ]
    }
    config = {"recursion_limit": MAX_ITER}

    seen = 0
    final_msg: ToolMessage | AIMessage | None = None
    report_path: str | None = None

    try:
        for chunk in graph.stream(init, config=config, stream_mode="values"):
            messages = chunk.get("messages", [])
            for msg in messages[seen:]:
                if isinstance(msg, AIMessage):
                    yield from _ai_to_thought(msg)
                    final_msg = msg
                elif isinstance(msg, ToolMessage):
                    yield from _tool_to_result(msg)
                    final_msg = msg
                    if msg.name == "submit_final_answer" and isinstance(msg.content, str) \
                            and msg.content.startswith("ACCEPTED"):
                        # parse "ACCEPTED: comparisons/<file> (...)"
                        body = msg.content.split(":", 1)[1].strip()
                        report_path = body.split(" ", 1)[0]
            seen = len(messages)
    except Exception as exc:
        yield {"type": "error", "content": str(exc)}
        return

    if report_path:
        yield {"type": "final_answer", "content": "Report submitted.", "report_path": report_path}
        return

    if isinstance(final_msg, AIMessage):
        text = final_msg.content if isinstance(final_msg.content, str) else str(final_msg.content)
        if not getattr(final_msg, "tool_calls", None):
            yield {"type": "final_answer", "content": text, "report_path": None}
            return

    yield {"type": "error", "content": f"Reached max iterations ({MAX_ITER}) without submitting a final report."}
