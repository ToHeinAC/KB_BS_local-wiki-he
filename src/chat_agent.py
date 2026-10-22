"""Deep chat agent — LangGraph state machine over data/raw/ originals.

Public surface: `run_chat_agent(question)` is a generator of step dicts, emitting the
same step-dict shape as the research agent:
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
from langgraph.errors import GraphRecursionError  # pyright: ignore[reportMissingTypeStubs]
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
    CHAT_AGENT_SYSTEM,
    CHAT_BUDGET_NUDGE,
    CHAT_FALLBACK_PROMPT,
    CHAT_FALLBACK_SYSTEM,
    CHAT_PROSE_GATE_RETRY,
)

load_dotenv()

MIN_SEARCHES = int(os.getenv("CHAT_MIN_SEARCHES", "3"))
MIN_WORDS = int(os.getenv("CHAT_MIN_WORDS", "500"))
MIN_SOURCES = int(os.getenv("CHAT_MIN_SOURCES", "3"))
MAX_ITER = int(os.getenv("CHAT_MAX_ITERATIONS", "40"))
NUDGE_AT = int(os.getenv("CHAT_NUDGE_AT", str(MAX_ITER // 2 - 2)))
LLM_TIMEOUT = int(os.getenv("CHAT_LLM_TIMEOUT", "180"))
FALLBACK_NOTES_CAP = int(os.getenv("CHAT_FALLBACK_NOTES_CAP", "12000"))
# A prose answer (no submit call) runs the submit gate too; this many rejections are fed
# back before the run ends with a labelled best-effort answer.
PROSE_RETRIES = int(os.getenv("CHAT_PROSE_RETRIES", "2"))

# Ollama stops generating once prompt + answer reach num_ctx, so a long run's answer would
# be cut mid-sentence. The history sent per turn stays under the window minus a reserve for
# the tool schemas and the answer; 3 characters per token is conservative for German text.
_ANSWER_RESERVE_TOKENS = 8192
_CHARS_PER_TOKEN = 3
WINDOW_CHARS = (ollama_client.NUM_CTX - _ANSWER_RESERVE_TOKENS) * _CHARS_PER_TOKEN
_TRIM_HEAD = 400  # what a trimmed tool result keeps: its header names file and section
# A trim cuts the history down to this share of the budget, so the following turns resend
# the same prefix and Ollama's prompt cache holds until the next trim.
_TRIM_TO = 0.6
_TRIMMED = "\n[trimmed to fit the context window — the facts noted in think_tool still hold]"

_RAW_TEXT_EXTS = {".md", ".txt", ".html"}
# The gate's own pattern, so "N cited" and the sources panel count `[Source: file §N]` as it does.
_RAW_CITE_RE = tool_module._RAW_CITE_RE  # pyright: ignore[reportPrivateUsage]
# Permissive body so a DB-qualified page ("Investing::foo.md") still parses —
# DB names may contain spaces, so this can't be a \w-class.
_WIKI_CITE_RE = re.compile(r"\[Wiki:\s*([^\]\n]+?\.md)\s*\]")


def _cites(text: str, extra: list[str] | None = None) -> dict[str, Any]:
    """Split the citations in `text` into raw originals and wiki pages."""
    return {
        "sources": sorted(set(_RAW_CITE_RE.findall(text)) | set(extra or [])),
        "wiki_sources": sorted(set(_WIKI_CITE_RE.findall(text))),
    }


def _size(m: AnyMessage) -> int:
    calls = m.tool_calls if isinstance(m, AIMessage) else []
    return len(str(m.content)) + (len(str(calls)) if calls else 0)


def _trim(m: AnyMessage) -> AnyMessage:
    return m.model_copy(update={"content": str(m.content)[:_TRIM_HEAD] + _TRIMMED})


def _fit_window(
    msgs: list[AnyMessage], trimmed: frozenset[int] = frozenset(), budget_chars: int = WINDOW_CHARS
) -> tuple[list[AnyMessage], frozenset[int]]:
    """The history to send and the indexes of its trimmed tool results. Earlier trims
    (`trimmed`) are reapplied as they were; once over budget, the oldest bulky results are
    cut to their head down to `_TRIM_TO` of it. think_tool notes and the latest tool result
    stay whole; the run's state is unchanged."""
    out = [_trim(m) if i in trimmed else m for i, m in enumerate(msgs)]
    cut = set(trimmed)
    excess = sum(map(_size, out)) - budget_chars
    if excess > 0:
        excess += int(budget_chars * (1 - _TRIM_TO))
    last_tool = max((i for i, m in enumerate(out) if isinstance(m, ToolMessage)), default=-1)
    for i, m in enumerate(out):
        if excess <= 0:
            break
        if (
            i in cut
            or not isinstance(m, ToolMessage)
            or i == last_tool
            or m.name == "think_tool"
            or len(str(m.content)) <= _TRIM_HEAD + len(_TRIMMED)
        ):
            continue
        out[i] = _trim(m)
        cut.add(i)
        excess -= len(str(m.content)) - len(str(out[i].content))
    return out, frozenset(cut)


def _text(m: AnyMessage) -> str:
    return m.content if isinstance(m.content, str) else str(m.content or "")


def _verdict_reason(verdict: str) -> str:
    """The first line of a gate verdict, short enough for a label."""
    return verdict.strip().splitlines()[0][:300] if verdict.strip() else verdict


def _gate_prose(text: str) -> dict[str, Any]:
    """Run the submit gate on a prose answer. A rejection with retries left goes back to
    the agent as a user turn; otherwise the run ends (labelled best-effort if rejected)."""
    verdict = tool_module._submit_chat_impl(text)  # pyright: ignore[reportPrivateUsage]
    mem = run_memory.current()
    if mem is None or verdict.startswith("ACCEPTED"):
        if mem is not None:
            mem.gate_reason = None
            mem.gate_events.append("accepted")
        return {"messages": []}
    mem.gate_reason = _verdict_reason(verdict)
    if mem.prose_rejections >= PROSE_RETRIES:
        mem.gate_events.append(f"rejected, retries used up: {mem.gate_reason}")
        return {"messages": []}
    mem.prose_rejections += 1
    mem.gate_events.append(
        f"rejected (retry {mem.prose_rejections}/{PROSE_RETRIES}): {mem.gate_reason}"
    )
    return {"messages": [HumanMessage(content=CHAT_PROSE_GATE_RETRY.format(verdict=verdict))]}


def _after_gate(state: MessagesState) -> str:
    return "agent" if isinstance(state["messages"][-1], HumanMessage) else END


def _build_llm() -> Runnable[LanguageModelInput, BaseMessage]:
    return ChatOllama(
        model=ollama_client.QUERY_MODEL,
        base_url=ollama_client.host(),
        temperature=0.3,
        num_ctx=ollama_client.NUM_CTX,  # the app-wide window: no truncation, no model reload
        client_kwargs={"timeout": LLM_TIMEOUT},  # ChatOllama drops a bare timeout=
    ).bind_tools(tool_module.with_ontology(tool_module.CHAT_TOOLS))  # pyright: ignore[reportUnknownMemberType]  # bare Callable


def _new_nudge(msgs: list[AnyMessage], nudge: str, bonus: int) -> list[AnyMessage]:
    """The wrap-up nudge to store, once it is due and only once: re-added at the tail every
    turn, it would change the prompt behind the last answer and defeat Ollama's cache."""
    due = sum(1 for m in msgs if isinstance(m, AIMessage)) >= NUDGE_AT + bonus
    if due and not any(isinstance(m, HumanMessage) and m.content == nudge for m in msgs):
        return [HumanMessage(content=nudge)]
    return []


def _build_graph(
    llm: Runnable[LanguageModelInput, BaseMessage], directive: str = ""
) -> CompiledStateGraph[MessagesState]:
    nudge = CHAT_BUDGET_NUDGE.format(min_words=MIN_WORDS) + (
        f"\n\n{directive}" if directive else ""
    )
    trimmed: frozenset[int] = frozenset()

    def agent_node(state: MessagesState, config: RunnableConfig) -> dict[str, Any]:
        nonlocal trimmed
        mem = run_memory.current()
        bonus = mem.bonus if mem is not None else 0
        # The graph's own limit leaves room for the reference bonus; the run's real limit
        # is MAX_ITER plus two steps per earned turn (an agent step and a tool step).
        step = int((config.get("metadata") or {}).get("langgraph_step", 0))
        if step > MAX_ITER + 2 * bonus:
            raise GraphRecursionError(f"Recursion limit of {MAX_ITER} reached")
        msgs, trimmed = _fit_window(list(state["messages"]), trimmed)
        new = _new_nudge(msgs, nudge, bonus)
        return {"messages": [*new, llm.invoke([*msgs, *new])]}

    def should_continue(state: MessagesState) -> str:
        last = state["messages"][-1]
        if not (isinstance(last, AIMessage) and last.tool_calls):
            return "prose_gate" if _text(last).strip() else END
        for m in reversed(state["messages"]):
            if (
                isinstance(m, ToolMessage)
                and m.name == "submit_chat_answer"
                and isinstance(m.content, str)
                and m.content.startswith("ACCEPTED")
            ):
                return END
        return "tools"

    def prose_gate(state: MessagesState) -> dict[str, Any]:
        return _gate_prose(_text(state["messages"][-1]))

    g: StateGraph[MessagesState] = StateGraph(MessagesState)
    # langgraph leaves CachePolicy/BaseCheckpointSaver generics unsolved in these signatures.
    g.add_node("agent", agent_node)  # pyright: ignore[reportUnknownMemberType]
    g.add_node("tools", ToolNode(tool_module.with_ontology(tool_module.CHAT_TOOLS)))  # pyright: ignore[reportUnknownMemberType]
    g.add_node("prose_gate", prose_gate)  # pyright: ignore[reportUnknownMemberType]
    g.add_edge(START, "agent")
    g.add_conditional_edges(
        "agent", should_continue, {"tools": "tools", "prose_gate": "prose_gate", END: END}
    )
    g.add_conditional_edges("prose_gate", _after_gate, {"agent": "agent", END: END})
    g.add_edge("tools", "agent")
    return g.compile()  # pyright: ignore[reportUnknownMemberType]


def _build_raw_index_one() -> str:
    """One line per raw file in the *active* DB, names DB-qualified when needed."""
    raw = db_context.raw_dir()
    if not raw.exists():
        return ""
    lines: list[str] = []
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
    blocks: list[str] = []
    for db in scope:
        with db_context.using_db(db):
            text = _build_raw_index_one()
        if text:
            blocks.append(f"Database {db}:\n{text}")
    return "\n\n".join(blocks)


def _system_prompt(directive: str = "") -> str:
    index_text = _build_raw_index()
    raw_block = f"Original files available in data/raw/:\n{index_text}\n\n" if index_text else ""
    return CHAT_AGENT_SYSTEM.format(
        raw_block=raw_block,
        language_directive=directive,
        min_searches=MIN_SEARCHES,
        min_words=MIN_WORDS,
        min_sources=MIN_SOURCES,
    )


def _ai_to_thought(msg: AIMessage) -> Iterator[dict[str, Any]]:
    text = msg.content if isinstance(msg.content, str) else str(msg.content or "")
    if text.strip():
        yield {"type": "thought", "content": text}
    for tc in msg.tool_calls:
        yield {"type": "tool_call", "name": tc.get("name"), "args": tc.get("args") or {}}


def _tool_to_result(msg: ToolMessage) -> Iterator[dict[str, Any]]:
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


def _gather_notes(all_messages: list[AnyMessage]) -> str:
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


def _synthesize_fallback(question: str, all_messages: list[AnyMessage], directive: str = "") -> str:
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
            CHAT_FALLBACK_SYSTEM,
            prompt,
            temperature=0.3,
            model_id=ollama_client.QUERY_MODEL,
        ).strip()
    except Exception:
        return ""


def _extract_submitted_answer(messages: list[AnyMessage]) -> tuple[str, list[str]] | None:
    """Find the most recent submit_chat_answer call whose tool result was ACCEPTED.

    Returns (answer_text, sources) or None.
    """
    accepted_tool_idx = None
    for i in range(len(messages) - 1, -1, -1):
        m = messages[i]
        if (
            isinstance(m, ToolMessage)
            and m.name == "submit_chat_answer"
            and isinstance(m.content, str)
            and m.content.startswith("ACCEPTED")
        ):
            accepted_tool_idx = i
            break
    if accepted_tool_idx is None:
        return None
    # The matching AIMessage with the tool_call is just before the ToolMessage.
    for j in range(accepted_tool_idx - 1, -1, -1):
        m = messages[j]
        if isinstance(m, AIMessage):
            for tc in m.tool_calls:
                if tc.get("name") == "submit_chat_answer":
                    args = tc.get("args") or {}
                    return args.get("answer", ""), list(args.get("sources") or [])
            break
    return None


@dataclass
class _Run:
    """What one streamed run has produced so far (read by the final-answer cascade)."""

    messages: list[AnyMessage] = field(default_factory=list[AnyMessage])
    final_msg: AIMessage | ToolMessage | None = None
    recursion_hit: bool = False


def _stream(graph: Any, init: MessagesState, run: _Run) -> Generator[dict[str, Any], None, bool]:
    """Run the graph, yielding live steps. Returns False when it died on a real error
    (already reported); a recursion-limit stop is recorded and returns True."""
    config: RunnableConfig = {"recursion_limit": MAX_ITER + 2 * tool_module.REF_BONUS_MAX}
    seen = gates = 0
    mem = run_memory.current()
    try:
        for chunk in graph.stream(init, config=config, stream_mode="values"):
            run.messages = chunk.get("messages", [])
            for msg in run.messages[seen:]:
                if isinstance(msg, AIMessage):
                    yield from _ai_to_thought(msg)
                    run.final_msg = msg
                elif isinstance(msg, ToolMessage):
                    yield from _tool_to_result(msg)
                    run.final_msg = msg
            seen = len(run.messages)
            events = mem.gate_events if mem is not None else []
            yield from ({"type": "gate", "content": e} for e in events[gates:])
            gates = len(events)
    except Exception as exc:
        err = str(exc)
        if "recursion" not in err.lower() and "GRAPH_RECURSION_LIMIT" not in err:
            yield {"type": "error", "content": err}
            return False
        run.recursion_hit = True
        yield {
            "type": "error",
            "content": f"Recursion limit ({MAX_ITER}) reached. "
            "Returning best-effort partial answer.",
        }
    return True


def _direct_answer(final_msg: AIMessage | ToolMessage | None) -> str | None:
    """Clean exit: the final assistant message carries non-empty answer text."""
    if not isinstance(final_msg, AIMessage) or final_msg.tool_calls:
        return None
    text = final_msg.content if isinstance(final_msg.content, str) else str(final_msg.content)
    return text if text.strip() else None


def _best_effort_draft(messages: list[AnyMessage]) -> tuple[str, list[str]] | None:
    """(text, sources) of the latest submit_chat_answer draft that did not clear the
    quality gate, else of the last non-empty assistant message (usually a reflection)."""
    for m in reversed(messages):
        if isinstance(m, AIMessage):
            for tc in m.tool_calls:
                if tc.get("name") == "submit_chat_answer":
                    args = tc.get("args") or {}
                    draft = (args.get("answer") or "").strip()
                    if draft:
                        return draft, list(args.get("sources") or [])
    for m in reversed(messages):
        if isinstance(m, AIMessage):
            text = m.content if isinstance(m.content, str) else str(m.content or "")
            if text.strip():
                return text, []
    return None


def _last_rejection(messages: list[AnyMessage]) -> str | None:
    """The reason the latest submit_chat_answer was turned down, if one was."""
    for m in reversed(messages):
        if isinstance(m, ToolMessage) and m.name == "submit_chat_answer":
            return _verdict_reason(_text(m))
    return None


def _last_resort(question: str, directive: str, run: _Run) -> dict[str, Any]:
    # The agent gathered search results but never submitted or wrote prose
    # (common with small local models). Synthesise an answer from the notes
    # instead of discarding everything.
    synth = _synthesize_fallback(question, run.messages, directive)
    if synth:
        return {
            "type": "final_answer",
            "content": _with_iter_hint(
                f"(assembled from gathered notes — the agent did not submit an answer)\n\n{synth}",
                run.recursion_hit,
            ),
            **_cites(synth),
            "note": "Fallback synthesis from gathered tool results.",
        }
    if run.recursion_hit:
        return {
            "type": "final_answer",
            "content": "(no answer — recursion limit hit before any reflection was emitted)",
            "sources": [],
            "wiki_sources": [],
        }
    return {
        "type": "error",
        "content": f"Reached max iterations ({MAX_ITER}) without a submitted answer.",
    }


def _final_step(question: str, directive: str, run: _Run) -> dict[str, Any]:
    """The one closing step: accepted submission, clean answer, draft, or fallback."""
    submitted = _extract_submitted_answer(run.messages)
    if submitted is not None:
        answer, sources = submitted
        return {
            "type": "final_answer",
            "content": _with_iter_hint(answer, run.recursion_hit),
            **_cites(answer, sources),
        }
    direct = _direct_answer(run.final_msg)
    mem = run_memory.current()
    if direct:
        reason = mem.gate_reason if mem is not None else None
        label = f"(best-effort — quality gate not met: {reason})\n\n" if reason else ""
        return {
            "type": "final_answer",
            "content": _with_iter_hint(label + direct, run.recursion_hit),
            **_cites(direct),
        }
    draft = _best_effort_draft(run.messages)
    if draft is None:
        return _last_resort(question, directive, run)
    reason = _last_rejection(run.messages)
    prefix = (
        "(partial — recursion limit hit)"
        if run.recursion_hit
        else f"(best-effort — quality gate not met{f': {reason}' if reason else ''})"
    )
    return {
        "type": "final_answer",
        "content": _with_iter_hint(f"{prefix}\n\n{draft[0]}", run.recursion_hit),
        **_cites(draft[0], draft[1]),
    }


def run_chat_agent(question: str) -> Generator[dict[str, Any], None, None]:
    run_memory.begin_run(question)
    directive = lang.response_directive(question)
    try:
        graph = _build_graph(_build_llm(), directive)
    except Exception as exc:
        yield {"type": "error", "content": f"Chat agent init failed: {exc}"}
        return

    brief, frames = retrieval.ontology_briefing(question)
    for frame in frames:
        run_memory.note_ontology(frame)
    if brief:
        yield {"type": "ontology", "content": brief}
    system = _system_prompt(directive) + (f"\n\n{brief}" if brief else "")
    init: MessagesState = {
        "messages": [
            SystemMessage(content=system),
            HumanMessage(content=question),
        ]
    }
    run = _Run()
    if (yield from _stream(graph, init, run)):
        yield _final_step(question, directive, run)
