"""ReAct research agent: max 8 iterations, yields step dicts for live UI display."""

import json
from typing import Generator

import ollama_client
import tools as tool_module
from prompts import AGENT_SYSTEM

MAX_ITER = 8


def run_research_agent(question: str, wiki_context: str = "") -> Generator[dict, None, None]:
    """Runs the ReAct research agent.

    Yields step dicts:
      {"type": "thought", "content": "..."}
      {"type": "tool_call", "name": "...", "args": {...}}
      {"type": "tool_result", "name": "...", "result": "..."}
      {"type": "final_answer", "content": "...", "report_path": str | None}
      {"type": "error", "content": "..."}
    """
    wiki_block = f"Wiki context:\n{wiki_context}\n\n" if wiki_context else ""
    system = AGENT_SYSTEM.format(wiki_block=wiki_block)
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": question},
    ]

    for _ in range(MAX_ITER):
        try:
            resp = ollama_client._client().chat(
                model=ollama_client._MODEL,
                messages=messages,
                tools=tool_module.TOOLS,
                options={"temperature": 0.3},
            )
        except Exception as exc:
            yield {"type": "error", "content": str(exc)}
            return

        msg = resp["message"]
        text_content = msg.get("content", "") or ""
        tool_calls = msg.get("tool_calls") or []

        if text_content:
            yield {"type": "thought", "content": text_content}

        if not tool_calls:
            yield {"type": "final_answer", "content": text_content, "report_path": None}
            return

        messages.append({"role": "assistant", "content": text_content, "tool_calls": tool_calls})

        for tc in tool_calls:
            fn_name = tc["function"]["name"]
            fn_args = tc["function"].get("arguments", {})
            if isinstance(fn_args, str):
                try:
                    fn_args = json.loads(fn_args)
                except Exception:
                    fn_args = {}

            yield {"type": "tool_call", "name": fn_name, "args": fn_args}

            func = tool_module.TOOL_FUNCTIONS.get(fn_name)
            if func is None:
                result = f"Unknown tool: {fn_name}"
            else:
                try:
                    result = func(**fn_args)
                except Exception as exc:
                    result = f"Tool error: {exc}"

            yield {"type": "tool_result", "name": fn_name, "result": result}
            messages.append({"role": "tool", "content": result})

            if fn_name == "report_writer":
                yield {"type": "final_answer", "content": result, "report_path": result}
                return

    yield {"type": "error", "content": f"Reached max iterations ({MAX_ITER}) without a final answer."}
