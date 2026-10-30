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
from collections import Counter
from collections.abc import Generator, Hashable, Iterator
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
    ToolCall,
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
from langgraph.prebuilt.tool_node import ToolInvocationError

import db_context
import evidence
import lang
import ollama_client
import retrieval
import run_memory
import tools as tool_module
from prompts import (
    CHAT_AGENT_SYSTEM,
    CHAT_BUDGET_NUDGE,
    CHAT_EMPTY_TURN,
    CHAT_FALLBACK_PROMPT,
    CHAT_FALLBACK_SYSTEM,
    CHAT_HYDE_PROMPT,
    CHAT_HYDE_SYSTEM,
    CHAT_LEDGER_LEVELS,
    CHAT_LEDGER_PROMPT,
    CHAT_LEDGER_REJECTED,
    CHAT_LEDGER_SYSTEM,
    CHAT_OPEN_REF_LINE,
    CHAT_PROSE_GATE_RETRY,
    CHAT_TOOL_ERROR,
)

load_dotenv()

MIN_SEARCHES = int(os.getenv("CHAT_MIN_SEARCHES", "3"))
MIN_SOURCES = int(os.getenv("CHAT_MIN_SOURCES", "2"))
MAX_ITER = int(os.getenv("CHAT_MAX_ITERATIONS", "40"))
NUDGE_AT = int(os.getenv("CHAT_NUDGE_AT", str(MAX_ITER // 2 - 2)))
LLM_TIMEOUT = int(os.getenv("CHAT_LLM_TIMEOUT", "180"))
FALLBACK_NOTES_CAP = int(os.getenv("CHAT_FALLBACK_NOTES_CAP", "12000"))
# A prose answer (no submit call) runs the submit gate too; this many rejections are fed
# back before the run ends with a labelled best-effort answer.
PROSE_RETRIES = int(os.getenv("CHAT_PROSE_RETRIES", "2"))
# Agent turns (the pre-flight search counts as one) after which code opens the best raw
# hit if the model has read no original yet.
AUTO_READ_AT = 3
# Turns in a row without a new quote in the evidence ledger after which a covered run
# (enough searches and quoted sources for the gate) is answered from the ledger: it stops
# if that answer passes the gate, else goes on with the verdict as feedback.
STALL_TURNS = 3
# The length the ledger answer is asked for, per quoted source: detailed, not a floor (the
# gate only sends back an answer under tools.CHAT_WORDS_PER_ITEM per source, once).
LEDGER_WORDS_PER_SOURCE = 80
# The note on a final answer written from the evidence ledger (it passed the gate).
LEDGER_NOTE = "Written from the quotes collected from the originals."
HYDE_CAP = 600  # characters of the hypothetical passage used as a query
# Sections a follow-up re-reads from the previous run's evidence ledger, most-quoted first.
CARRY_MAX = 4

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
_FILE_LINE_RE = re.compile(r"^file: (.+)$", re.MULTILINE)  # a raw_search hit's file and §
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


def _should_continue(state: MessagesState) -> str:
    last = state["messages"][-1]
    if not (isinstance(last, AIMessage) and last.tool_calls):
        if _text(last).strip():
            return "prose_gate"
        return "empty_turn" if _empty_turn_due() else END
    for m in reversed(state["messages"]):
        if (
            isinstance(m, ToolMessage)
            and m.name == "submit_chat_answer"
            and isinstance(m.content, str)
            and m.content.startswith("ACCEPTED")
        ):
            return END
    return "tools"


def _empty_turn_due() -> bool:
    """An empty model turn (no text, no tool call) of a run that lacks the gate's searches
    or sources is sent back once; otherwise it ends the run (the stop rule's empty turn
    comes only on a covered run)."""
    mem = run_memory.current()
    return mem is not None and not mem.empty_nudged and not _covered(mem)


def _empty_turn(state: MessagesState) -> dict[str, Any]:
    mem = run_memory.current()
    assert mem is not None  # routed here only inside a run
    mem.empty_nudged = True
    mem.gate_events.append("empty turn: sent back to search and read")
    refs = len({ref for ref, _ in mem.ledger})
    nudge = CHAT_EMPTY_TURN.format(
        searches=mem.search_count(),
        min_searches=MIN_SEARCHES,
        sources=refs,
        min_sources=MIN_SOURCES,
    )
    return {"messages": [HumanMessage(content=nudge)]}


def _after_gate(state: MessagesState) -> str:
    return "agent" if isinstance(state["messages"][-1], HumanMessage) else END


def _build_llm() -> Runnable[LanguageModelInput, BaseMessage]:
    return ChatOllama(
        model=ollama_client.QUERY_MODEL,
        base_url=ollama_client.host(),
        # Google's sampling for Gemma 4, for every use case (Ollama and Unsloth agree).
        temperature=1.0,
        top_p=0.95,
        top_k=64,
        # No thinking (`reasoning` unset), even for a model that can: on the KI bench it cited
        # unread sections and far overran the time budget (bench/results/deep_chat_2026-10-22.md).
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


def _auto_read(msgs: list[AnyMessage]) -> AIMessage | None:
    """A `raw_read` of the best raw hit's section, made for the model once it has taken
    `AUTO_READ_AT` turns without opening any original: small models answer from search
    excerpts, and the gate rejects an answer whose cited originals were never read."""
    calls = [c for m in msgs if isinstance(m, AIMessage) for c in m.tool_calls]
    if len([m for m in msgs if isinstance(m, AIMessage)]) < AUTO_READ_AT or any(
        c["name"] == "raw_read" for c in calls
    ):
        return None
    hits = (_text(m) for m in msgs if isinstance(m, ToolMessage) and m.name == "raw_search")
    top = next((h.group(1).strip() for h in map(_FILE_LINE_RE.search, hits) if h), None)
    if top is None:
        return None
    read: ToolCall = {
        "name": "raw_read",
        "args": {"filenames": [top]},
        "id": "auto-read",
        "type": "tool_call",
    }
    return AIMessage(content="", tool_calls=[read])


def _due_read(mem: run_memory.RunMemory | None) -> AIMessage | None:
    """A `raw_read` of the sections the last rejection cited unread: E4B tends to resubmit
    the same answer instead of reading them."""
    if mem is None or not mem.unread_due:
        return None
    refs, mem.unread_due = mem.unread_due, []
    read: ToolCall = {
        "name": "raw_read",
        "args": {"filenames": refs},
        "id": f"due-read-{mem.step}",
        "type": "tool_call",
    }
    return AIMessage(content="", tool_calls=[read])


def _covered(mem: run_memory.RunMemory) -> bool:
    """Enough searches and quoted sources for the gate to accept a ledger answer."""
    refs = {ref for ref, _ in mem.ledger}
    return mem.search_count() >= MIN_SEARCHES and len(refs) >= MIN_SOURCES


def _evidence_stalled(mem: run_memory.RunMemory | None) -> bool:
    """Count this turn as stale unless the ledger grew; True once a covered run has gone
    STALL_TURNS turns without a new quote (retrieval thrash)."""
    if mem is None:
        return False
    grew = len(mem.ledger) > mem.ledger_seen
    mem.ledger_seen = len(mem.ledger)
    mem.stale_turns = 0 if grew else mem.stale_turns + 1
    return mem.stale_turns >= STALL_TURNS and _covered(mem)


def _code_turn(
    msgs: list[AnyMessage], mem: run_memory.RunMemory | None, directive: str
) -> AIMessage | HumanMessage | None:
    """A turn code takes instead of the model: the read of sections a rejection cited
    unread, the auto-read, or a stalled run's ledger answer. If that passes the gate the
    run stops (an empty message ends the graph and the final step ships it); else the
    verdict goes to the model as feedback."""
    due = _due_read(mem)
    if due is not None:
        return due
    stalled = _evidence_stalled(mem)
    auto = _auto_read(msgs)
    if auto is not None or not stalled or mem is None:
        return auto
    mem.stale_turns = 0  # judged again only after STALL_TURNS more turns without a quote
    if _ledger_answer(mem.question, directive) is not None:
        mem.gate_events.append(f"stopped: no new evidence in {STALL_TURNS} turns")
        return AIMessage(content="")
    if not mem.ledger_verdict:
        return None
    return HumanMessage(content=CHAT_LEDGER_REJECTED.format(verdict=mem.ledger_verdict))


def _tool_error(e: Exception) -> str:
    """What a raising tool returns instead of ending the run (ToolNode re-raises anything
    but bad arguments by default); bad arguments keep their own explanation."""
    if isinstance(e, ToolInvocationError):
        return e.message
    return CHAT_TOOL_ERROR


def _tool_node() -> ToolNode:
    return ToolNode(
        tool_module.with_ontology(tool_module.CHAT_TOOLS), handle_tool_errors=_tool_error
    )


def _step_guard(config: RunnableConfig, bonus: int) -> None:
    """The graph's own limit leaves room for the reference bonus; the run's real limit is
    MAX_ITER plus two steps per earned turn (an agent step and a tool step)."""
    step = int((config.get("metadata") or {}).get("langgraph_step", 0))
    if step > MAX_ITER + 2 * bonus:
        raise GraphRecursionError(f"Recursion limit of {MAX_ITER} reached")


def _build_graph(
    llm: Runnable[LanguageModelInput, BaseMessage], directive: str = ""
) -> CompiledStateGraph[MessagesState]:
    nudge = CHAT_BUDGET_NUDGE + (f"\n\n{directive}" if directive else "")
    trimmed: frozenset[int] = frozenset()

    def agent_node(state: MessagesState, config: RunnableConfig) -> dict[str, Any]:
        nonlocal trimmed
        mem = run_memory.current()
        bonus = mem.bonus if mem is not None else 0
        _step_guard(config, bonus)
        forced = _code_turn(list(state["messages"]), mem, directive)
        if isinstance(forced, AIMessage):
            return {"messages": [forced]}
        msgs, trimmed = _fit_window(list(state["messages"]), trimmed)
        new = [*([forced] if forced is not None else []), *_new_nudge(msgs, nudge, bonus)]
        return {"messages": [*new, llm.invoke([*msgs, *new])]}

    def prose_gate(state: MessagesState) -> dict[str, Any]:
        return _gate_prose(_text(state["messages"][-1]))

    g: StateGraph[MessagesState] = StateGraph(MessagesState)
    # langgraph leaves CachePolicy/BaseCheckpointSaver generics unsolved in these signatures.
    g.add_node("agent", agent_node)  # pyright: ignore[reportUnknownMemberType]
    g.add_node("tools", _tool_node())  # pyright: ignore[reportUnknownMemberType]
    g.add_node("prose_gate", prose_gate)  # pyright: ignore[reportUnknownMemberType]
    g.add_node("empty_turn", _empty_turn)  # pyright: ignore[reportUnknownMemberType]
    g.add_edge(START, "agent")
    routes: dict[Hashable, str] = {
        "tools": "tools",
        "prose_gate": "prose_gate",
        "empty_turn": "empty_turn",
        END: END,
    }
    g.add_conditional_edges("agent", _should_continue, routes)
    g.add_edge("empty_turn", "agent")
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
        min_sources=MIN_SOURCES,
        words_per_item=tool_module.CHAT_WORDS_PER_ITEM,
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
            "closing": "notes-fallback",
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


def _ledger_answer(question: str, directive: str) -> str | None:
    """The answer written from the run's evidence ledger, if it passes the submit gate;
    None before the run is covered (the gate would reject it) or on any failure. Written
    once per ledger size."""
    mem = run_memory.current()
    if mem is None or not _covered(mem):
        return None
    if mem.ledger_tried != len(mem.ledger):
        mem.ledger_tried = len(mem.ledger)
        mem.ledger_answer = _write_ledger_answer(mem, question, directive)
    return mem.ledger_answer


def _write_ledger_answer(mem: run_memory.RunMemory, question: str, directive: str) -> str | None:
    """The ledger answer in a fresh, short prompt; its gate verdict goes to the gate events."""
    refs = len({ref for ref, _ in mem.ledger})
    levels = [mem.levels.get(tool_module.ref_key(ref), 0) for ref, _ in mem.ledger]
    rendered = evidence.render(mem.ledger, levels, CHAT_LEDGER_LEVELS)
    prompt = CHAT_LEDGER_PROMPT.format(
        question=question, evidence=rendered, words=LEDGER_WORDS_PER_SOURCE * refs
    )
    try:
        answer = ollama_client.generate(
            CHAT_LEDGER_SYSTEM,
            prompt + (f"\n\n{directive}" if directive else ""),
            temperature=0.3,
            model_id=ollama_client.QUERY_MODEL,
        ).strip()
    except Exception as exc:
        mem.ledger_verdict = ""
        mem.gate_events.append(f"ledger answer failed: {exc}")
        return None
    mem.ledger_raw.append(answer)
    answer = _clean_ledger_answer(answer, mem)
    mem.ledger_drafts.append(answer)
    verdict = tool_module.chat_verdict(answer)
    if verdict.startswith("ACCEPTED"):
        mem.ledger_verdict = ""
        mem.gate_events.append("ledger answer accepted")
        return answer
    mem.ledger_verdict = verdict
    mem.gate_events.append(f"ledger answer rejected: {_verdict_reason(verdict)}")
    return None


_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")
_TAG_RE = re.compile(r"\s*\[Source:\s*([^\]\n]+?)\s*\]")


def _clean_ledger_answer(answer: str, mem: run_memory.RunMemory) -> str:
    """The ledger answer with each `[Source: ...]` tag mapped to the quote's own tag (E4B
    writes "§ 31 (2)", or a § the quote never carried), and without the sentences no quote
    backs or that name a § the run never read. Headings stay; the laws not in scope that
    the cited sections rely on are named under `## Open points` by code."""
    tags = {tool_module.ref_key(ref): ref for ref, _ in mem.ledger}
    files = {db_context.qualify(b, d) for d, b, _ in map(tool_module._split_ref, tags.values())}  # pyright: ignore[reportPrivateUsage]
    out: list[str] = []
    body = False  # under a heading other than the open points: every claim needs a tag
    for line in answer.splitlines():
        if line.lstrip().startswith("#"):
            body = not tool_module._OPEN_POINTS_RE.match(line.strip())  # pyright: ignore[reportPrivateUsage]
        if not line.strip() or line.lstrip().startswith("#"):
            out.append(line)
            continue
        sentences = (_backed(s, tags, mem, files) for s in _SENTENCE_RE.split(line))
        kept = [k for k in sentences if k and not (body and _untagged(k))]
        if kept and not _LIST_MARKER_RE.fullmatch(" ".join(kept)):
            out.append(" ".join(kept))
    return _with_open_refs(_tidy(out), mem)


_LIST_MARKER_RE = re.compile(r"\s*(?:\d+[.)]|[-*•])\s*")


def _untagged(sentence: str) -> bool:
    """A claim without a `[Source: ...]` tag; a list marker ("1.") or a line that
    introduces a list is none."""
    s = sentence.rstrip()
    return not (_TAG_RE.search(s) or s.endswith(":") or _LIST_MARKER_RE.fullmatch(s))


def _tidy(lines: list[str]) -> str:
    """`lines` without the headings left empty and the blank runs dropped sentences leave."""
    out: list[str] = []
    for line in reversed(lines):  # backwards: a heading sees what follows it
        nxt = next((x for x in out[::-1] if x.strip()), None)
        if line.lstrip().startswith("#") and (nxt is None or nxt.lstrip().startswith("#")):
            continue
        out.append(line)
    text = "\n".join(reversed(out)).strip()
    return re.sub(r"\n{3,}", "\n\n", text)


def _with_open_refs(answer: str, mem: run_memory.RunMemory) -> str:
    """`answer` with a code-written `## Open points` entry for each law not in scope that
    its cited sections rely on and it does not name yet."""
    cited = set(tool_module._RAW_CITE_RE.findall(answer))  # pyright: ignore[reportPrivateUsage]
    works = tool_module.open_refs_unnamed(answer, cited)
    if not works:
        return answer
    lines = [CHAT_OPEN_REF_LINE[lang.detect(mem.question)].format(work=w) for w in works]
    if tool_module._OPEN_POINTS_RE.search(answer):  # pyright: ignore[reportPrivateUsage]
        gap = [] if answer.splitlines()[-1].lstrip().startswith(("- ", "* ", "• ")) else [""]
        return "\n".join([answer, *gap, *lines])
    return "\n".join([answer, "", "## Open points", *lines])


def _backed(
    sentence: str, tags: dict[tuple[str, str], str], mem: run_memory.RunMemory, files: set[str]
) -> str | None:
    """`sentence` with its tags mapped to ledger tags; None when it has tags but no ledger
    quote backs any of them, or when it names a § of a cited file that was never read."""
    found = _TAG_RE.findall(sentence)
    mapped = {t: tags.get(tool_module.ref_key(t)) for t in found}
    if found and not any(mapped.values()):
        return None
    if tool_module._prose_unread(mem, _TAG_RE.sub("", sentence), files):  # pyright: ignore[reportPrivateUsage]
        return None

    def retag(m: re.Match[str]) -> str:
        ref = mapped.get(m.group(1))
        return f" [Source: {ref}]" if ref else ""

    return _TAG_RE.sub(retag, sentence)


def _final_step(question: str, directive: str, run: _Run) -> dict[str, Any]:
    """The one closing step: the ledger answer, accepted submission, clean answer, draft,
    or fallback."""
    ledgered = _ledger_answer(question, directive)
    if ledgered is not None:
        return {
            "type": "final_answer",
            "content": _with_iter_hint(ledgered, run.recursion_hit),
            **_cites(ledgered),
            "note": LEDGER_NOTE,
            "closing": "ledger",
        }
    submitted = _extract_submitted_answer(run.messages)
    if submitted is not None:
        answer, sources = submitted
        return {
            "type": "final_answer",
            "content": _with_iter_hint(answer, run.recursion_hit),
            **_cites(answer, sources),
            "closing": "submitted",
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
            "closing": "prose",
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
        "closing": "draft",
    }


def _preflight(question: str) -> list[AnyMessage]:
    """The run's first searches, run by code: a raw and a wiki search on the question, and a
    raw search on its key terms (a small model's weakest step is starting retrieval at all,
    and E4B rarely makes the gate's searches itself). They count as two of the gate's
    searches; on any failure the model starts the search itself."""
    tools = {"raw_search": tool_module.raw_search, "wiki_search": tool_module.wiki_search}
    queries = [("raw_search", question), ("wiki_search", question)]
    terms = evidence.key_terms(question)
    if terms and terms.casefold() != question.strip().casefold():
        queries.append(("raw_search", terms))
    calls: list[ToolCall] = [
        {"name": name, "args": {"query": q}, "id": f"preflight-{i}", "type": "tool_call"}
        for i, (name, q) in enumerate(queries)
    ]
    try:
        results: list[AnyMessage] = [
            ToolMessage(
                content=str(tools[c["name"]].invoke(c["args"])),
                name=c["name"],
                tool_call_id=c["id"],
            )
            for c in calls
        ]
    except Exception:
        return []
    hyde = _hyde_search(question)
    searched = [
        str(m.content)
        for m in [*results, *hyde]
        if isinstance(m, ToolMessage) and m.name == "raw_search"
    ]
    return [AIMessage(content="", tool_calls=calls), *results, *hyde, *_levels(question, searched)]


def _levels(question: str, searched: list[str]) -> list[AnyMessage]:
    """Code's reads of the core sections and the terms and provisions around them, one
    `raw_read` turn per level (tools.level_reads); [] on any failure."""
    try:
        done = tool_module.level_reads(question, searched)
    except Exception:
        return []
    out: list[AnyMessage] = []
    for n, (reads, text) in enumerate(done, 1):
        call: ToolCall = {
            "name": "raw_read",
            "args": {"filenames": reads},
            "id": f"level-{n}",
            "type": "tool_call",
        }
        out += [
            AIMessage(content="", tool_calls=[call]),
            ToolMessage(content=text, name="raw_read", tool_call_id=call["id"]),
        ]
    return out


def _hyde_search(question: str) -> list[AnyMessage]:
    """HyDE: one raw search with a short passage the model writes as if it were the answer
    (it matches the originals' wording better than a question). Not counted toward the
    gate's searches; [] on any failure."""
    try:
        passage = ollama_client.generate(
            CHAT_HYDE_SYSTEM,
            CHAT_HYDE_PROMPT.format(
                question=question, language_directive=lang.response_directive(question)
            ),
            temperature=0.3,
            model_id=ollama_client.QUERY_MODEL,
        ).strip()[:HYDE_CAP]
        hits = tool_module._raw_search_impl(queries=[passage])  # pyright: ignore[reportPrivateUsage]
    except Exception:
        return []
    if not passage:
        return []
    call: ToolCall = {
        "name": "raw_search",
        "args": {"query": passage},
        "id": "preflight-hyde",
        "type": "tool_call",
    }
    return [
        AIMessage(content="", tool_calls=[call]),
        ToolMessage(content=str(hits), name="raw_search", tool_call_id=call["id"]),
    ]


def _carry_refs(mem: run_memory.RunMemory) -> list[str]:
    """The ledger's sections, most-quoted first: what a follow-up re-reads. Names only, so
    no document text outlives the run."""
    return [ref for ref, _ in Counter(ref for ref, _ in mem.ledger).most_common(CARRY_MAX)]


def _carried_read(refs: list[str]) -> list[AnyMessage]:
    """A follow-up's code-made `raw_read` of the previous answer's sections: their quotes are
    taken again against the new question, and the gate sees them read in this run. [] on
    any failure."""
    if not refs:
        return []
    call: ToolCall = {
        "name": "raw_read",
        "args": {"filenames": refs[:CARRY_MAX]},
        "id": "carried-read",
        "type": "tool_call",
    }
    try:
        text = str(tool_module.raw_read.invoke(call["args"]))
    except Exception:
        return []
    return [
        AIMessage(content="", tool_calls=[call]),
        ToolMessage(content=text, name="raw_read", tool_call_id=call["id"]),
    ]


def run_chat_agent(
    question: str, carry: list[str] | None = None
) -> Generator[dict[str, Any], None, None]:
    """Answer `question`; `carry` names the sections a follow-up's previous answer rested on
    (its final step's `evidence_refs`), which code re-reads before the model's first turn."""
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
            *_preflight(question),
            *_carried_read(carry or []),
        ]
    }
    run = _Run()
    if (yield from _stream(graph, init, run)):
        mem = run_memory.current()
        logged = len(mem.gate_events) if mem is not None else 0
        final = _final_step(question, directive, run)
        events = mem.gate_events[logged:] if mem is not None else []
        yield from ({"type": "gate", "content": e} for e in events)
        yield {**final, "evidence_refs": _carry_refs(mem)} if mem is not None else final
