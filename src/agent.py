"""Deep research agent — LangGraph state machine, ChatOllama backend.

Public surface preserved: `run_research_agent(question, wiki_context)` is a generator of
step dicts, emitting the same step-dict shape the Streamlit Research page expects:
  {"type": "thought", "content": ...}
  {"type": "tool_call", "name": ..., "args": ...}
  {"type": "tool_result", "name": ..., "result": ...}
  {"type": "final_answer", "content": ..., "report_path": str | None}
  {"type": "error", "content": ...}
"""

from __future__ import annotations

import os
from collections.abc import Generator, Iterator
from dataclasses import dataclass, field
from typing import Any

from dotenv import load_dotenv
from langchain_core.language_models import LanguageModelInput
from langchain_core.messages import (
    AIMessage,
    AnyMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_core.runnables import Runnable, RunnableConfig
from langchain_ollama import ChatOllama
from langgraph.graph import (  # pyright: ignore[reportMissingTypeStubs]
    END,
    START,
    MessagesState,
    StateGraph,
)
from langgraph.graph.state import (  # pyright: ignore[reportMissingTypeStubs]
    CompiledStateGraph,
)
from langgraph.prebuilt import ToolNode

import db_context
import lang
import ollama_client
import retrieval
import run_memory
import tools as tool_module
from prompts import (
    RESEARCH_BUDGET_NUDGE,
    RESEARCH_FALLBACK_PROMPT,
    RESEARCH_FALLBACK_SYSTEM,
    RESEARCHER_INSTRUCTIONS,
)

load_dotenv()

MIN_SEARCHES = int(os.getenv("RESEARCH_MIN_SEARCHES", "6"))
MIN_WORDS = int(os.getenv("RESEARCH_MIN_WORDS", "600"))
MIN_URLS = int(os.getenv("RESEARCH_MIN_URLS", "4"))
MAX_ITER = int(os.getenv("RESEARCH_MAX_ITERATIONS", "40"))
NUDGE_AT = int(os.getenv("RESEARCH_NUDGE_AT", str(MAX_ITER // 2 - 2)))
MAX_SUBMIT_ATTEMPTS = int(os.getenv("RESEARCH_MAX_SUBMIT_ATTEMPTS", "3"))
LLM_TIMEOUT = int(os.getenv("RESEARCH_LLM_TIMEOUT", "300"))
FALLBACK_NOTES_CAP = int(os.getenv("RESEARCH_FALLBACK_NOTES_CAP", "12000"))


def _build_llm() -> Runnable[LanguageModelInput, BaseMessage]:
    return ChatOllama(
        model=ollama_client.QUERY_MODEL,
        base_url=ollama_client.host(),
        temperature=0.3,
        client_kwargs={"timeout": LLM_TIMEOUT},  # ChatOllama drops a bare timeout=
    ).bind_tools(tool_module.with_ontology(tool_module.TOOLS))  # pyright: ignore[reportUnknownMemberType]  # bare Callable


def _build_graph(
    llm: Runnable[LanguageModelInput, BaseMessage], directive: str = ""
) -> CompiledStateGraph[MessagesState]:
    nudge = RESEARCH_BUDGET_NUDGE + (f"\n\n{directive}" if directive else "")

    def agent_node(state: MessagesState) -> dict[str, Any]:
        msgs = list(state["messages"])
        ai_count = sum(1 for m in msgs if isinstance(m, AIMessage))
        if ai_count >= NUDGE_AT:
            msgs = [*msgs, HumanMessage(content=nudge)]
        return {"messages": [llm.invoke(msgs)]}

    def should_continue(state: MessagesState) -> str:
        last = state["messages"][-1]
        if not (isinstance(last, AIMessage) and last.tool_calls):
            return END
        submit_msgs = [
            m
            for m in state["messages"]
            if isinstance(m, ToolMessage)
            and m.name == "submit_final_answer"
            and isinstance(m.content, str)
        ]
        if any(str(m.content).startswith("ACCEPTED") for m in submit_msgs):
            return END
        if len(submit_msgs) >= MAX_SUBMIT_ATTEMPTS:
            return END
        return "tools"

    g: StateGraph[MessagesState] = StateGraph(MessagesState)
    # langgraph leaves CachePolicy/BaseCheckpointSaver generics unsolved in these signatures.
    g.add_node("agent", agent_node)  # pyright: ignore[reportUnknownMemberType]
    g.add_node("tools", ToolNode(tool_module.with_ontology(tool_module.TOOLS)))  # pyright: ignore[reportUnknownMemberType]
    g.add_edge(START, "agent")
    g.add_conditional_edges("agent", should_continue, {"tools": "tools", END: END})
    g.add_edge("tools", "agent")
    return g.compile()  # pyright: ignore[reportUnknownMemberType]


def _load_wiki_index() -> str:
    index = db_context.wiki_dir() / "index.md"
    if not index.exists():
        return ""
    try:
        return index.read_text()
    except Exception:
        return ""


def _system_prompt(wiki_context: str, directive: str = "") -> str:
    parts: list[str] = []
    index_text = _load_wiki_index()
    if index_text.strip():
        parts.append(
            f"Wiki index (page filenames available to wiki_search / wiki_read):\n{index_text}"
        )
    if wiki_context:
        parts.append(f"Extra wiki context (user paste):\n{wiki_context}")
    wiki_block = ("\n\n".join(parts) + "\n\n") if parts else ""
    return RESEARCHER_INSTRUCTIONS.format(
        wiki_block=wiki_block,
        language_directive=directive,
        min_searches=MIN_SEARCHES,
        min_words=MIN_WORDS,
        min_urls=MIN_URLS,
    )


def _ai_to_thought(msg: AIMessage) -> Iterator[dict[str, Any]]:
    text = msg.content if isinstance(msg.content, str) else str(msg.content or "")
    if text.strip():
        yield {"type": "thought", "content": text}
    for tc in msg.tool_calls:
        yield {
            "type": "tool_call",
            "name": tc.get("name"),
            "args": tc.get("args") or {},
        }


def _tool_to_result(msg: ToolMessage) -> Iterator[dict[str, Any]]:
    content = msg.content if isinstance(msg.content, str) else str(msg.content)
    yield {"type": "tool_result", "name": msg.name, "result": content}


def _gather_notes(all_messages: list[Any]) -> str:
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


def _synthesize_fallback(question: str, all_messages: list[Any], directive: str = "") -> str:
    """Best-effort report from gathered notes when the agent stalled without
    calling submit_final_answer. Returns '' if there are no notes or on error."""
    notes = _gather_notes(all_messages)
    if not notes.strip():
        return ""
    prompt = RESEARCH_FALLBACK_PROMPT.format(question=question, notes=notes)
    if directive:
        prompt += f"\n\n{directive}"
    try:
        return ollama_client.generate(
            RESEARCH_FALLBACK_SYSTEM,
            prompt,
            temperature=0.3,
            model_id=ollama_client.QUERY_MODEL,
        ).strip()
    except Exception:
        return ""


@dataclass
class _Run:
    """What one streamed run has produced so far (read by the final-answer cascade)."""

    messages: list[AnyMessage] = field(default_factory=list[AnyMessage])
    final_msg: AIMessage | ToolMessage | None = None
    report_path: str | None = None
    last_submit_args: dict[str, Any] | None = None
    recursion_hit: bool = False


def _observe(msg: AnyMessage, run: _Run) -> Iterator[dict[str, Any]]:
    """Live steps for one new message; records submissions and the filed report."""
    if isinstance(msg, AIMessage):
        for tc in msg.tool_calls:
            if tc.get("name") == "submit_final_answer":
                run.last_submit_args = tc.get("args") or {}
        yield from _ai_to_thought(msg)
        run.final_msg = msg
    elif isinstance(msg, ToolMessage):
        yield from _tool_to_result(msg)
        run.final_msg = msg
        if (
            msg.name == "submit_final_answer"
            and isinstance(msg.content, str)
            and msg.content.startswith("ACCEPTED")
        ):
            # parse "ACCEPTED: comparisons/<file> (...)"
            body = msg.content.split(":", 1)[1].strip()
            run.report_path = body.split(" ", 1)[0]


def _stream(graph: Any, init: MessagesState, run: _Run) -> Generator[dict[str, Any], None, bool]:
    """Run the graph, yielding live steps. Returns False when it died on a real error
    (already reported); an iteration-limit stop is recorded and returns True."""
    config: RunnableConfig = {"recursion_limit": MAX_ITER}
    seen = 0
    try:
        for chunk in graph.stream(init, config=config, stream_mode="values"):
            run.messages = chunk.get("messages", [])
            for msg in run.messages[seen:]:
                yield from _observe(msg, run)
            seen = len(run.messages)
    except Exception as exc:
        err = str(exc)
        if "recursion" not in err.lower() and "GRAPH_RECURSION_LIMIT" not in err:
            yield {"type": "error", "content": err}
            return False
        run.recursion_hit = True
        yield {
            "type": "error",
            "content": f"Iteration limit ({MAX_ITER}) reached for this run — "
            "returning best-effort answer.",
        }
    return True


def _direct_answer(final_msg: AIMessage | ToolMessage | None) -> str | None:
    """The closing assistant prose, when the run ended cleanly without a tool call."""
    if not isinstance(final_msg, AIMessage):
        return None
    text = final_msg.content if isinstance(final_msg.content, str) else str(final_msg.content)
    return text if not final_msg.tool_calls and text.strip() else None


def _best_effort_draft(run: _Run) -> tuple[str, str | None] | None:
    """(text, note) of the last rejected submission, else of the last assistant prose."""
    if run.last_submit_args and run.last_submit_args.get("answer"):
        note = "Submission did not meet quality bar; returning best-effort draft."
        return str(run.last_submit_args["answer"]), note
    for m in reversed(run.messages):
        if isinstance(m, AIMessage):
            t = m.content if isinstance(m.content, str) else str(m.content or "")
            if t.strip():
                return t, None
    return None


def _last_resort(question: str, directive: str, run: _Run) -> dict[str, Any]:
    # The agent gathered search results but never wrote prose or filed a report
    # (common with small local models). Synthesise an answer from the notes
    # instead of discarding everything.
    synth = _synthesize_fallback(question, run.messages, directive)
    if synth:
        return {
            "type": "final_answer",
            "content": "(assembled from gathered notes — the agent did not file a report)"
            f"\n\n{synth}",
            "report_path": None,
            "note": "Fallback synthesis from gathered tool results.",
        }
    if run.recursion_hit:
        return {
            "type": "final_answer",
            "content": "(no answer — iteration limit reached before any draft was produced)",
            "report_path": None,
        }
    return {
        "type": "error",
        "content": "The agent ended without producing an answer — try rephrasing or click "
        "🆕 New research.",
    }


def _final_step(question: str, directive: str, run: _Run) -> dict[str, Any]:
    """The one closing step: filed report, clean answer, best-effort draft, or fallback."""
    if run.report_path:
        return {
            "type": "final_answer",
            "content": "Report submitted.",
            "report_path": run.report_path,
        }
    direct = _direct_answer(run.final_msg)
    if direct:
        return {"type": "final_answer", "content": direct, "report_path": None}
    draft = _best_effort_draft(run)
    if draft is None:
        return _last_resort(question, directive, run)
    prefix = (
        "(partial — iteration limit hit)"
        if run.recursion_hit
        else "(best-effort — quality gate not met)"
    )
    step: dict[str, Any] = {
        "type": "final_answer",
        "content": f"{prefix}\n\n{draft[0]}",
        "report_path": None,
    }
    if draft[1]:
        step["note"] = draft[1]
    return step


def run_research_agent(
    question: str, wiki_context: str = ""
) -> Generator[dict[str, Any], None, None]:
    run_memory.begin_run()
    directive = lang.response_directive(question)
    try:
        graph = _build_graph(_build_llm(), directive)
    except Exception as exc:
        yield {"type": "error", "content": f"Agent init failed: {exc}"}
        return

    brief, frames = retrieval.ontology_briefing(question)
    for frame in frames:
        run_memory.note_ontology(frame)
    if brief:
        yield {"type": "ontology", "content": brief}
    system = _system_prompt(wiki_context, directive) + (f"\n\n{brief}" if brief else "")
    init: MessagesState = {
        "messages": [
            SystemMessage(content=system),
            HumanMessage(content=question),
        ]
    }
    run = _Run()
    if (yield from _stream(graph, init, run)):
        yield _final_step(question, directive, run)
