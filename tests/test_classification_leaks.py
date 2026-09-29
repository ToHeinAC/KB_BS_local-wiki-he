"""Canary leak suite for the classification gate (PRD M7, docs/security.md).

Unique tokens are planted in every store of the confidential and strict shards.
For each read entry point a user without clearance must never see a token — in
any output and in any LLM prompt — and a cleared user must (the positive twin
proves the probe really reaches the shard, so a negative can't pass by accident).
"""

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import pytest
from langchain_core.messages import AIMessage

import agent
import chat_agent
import chunker
import db_context
import dedup
import graph_export
import graph_widget
import lex_index
import ollama_client
import tools
import wiki_engine

DB = "KI"
CONF = "zebraquartz7731"  # content token of KI@confidential
STRICT = "okapiflint4402"  # content token of KI@strict
# File names carry their own tokens: a probe that names a file echoes the name back
# ("Page not found: …"), so names are only checked where nobody supplied them.
CONF_NAME, STRICT_NAME = "marmotcobalt5510", "lynxbasalt6620"
TOKENS = {"KI": None, "KI@confidential": CONF, "KI@strict": STRICT}
NAMES = {"KI": "public", "KI@confidential": CONF_NAME, "KI@strict": STRICT_NAME}


def _raw_text(tok: str) -> str:
    return f"## Shielding plan\nShielding plan for the gamma bunker, reference {tok}.\n"


def _page_text(tok: str, raw: str) -> str:
    return (
        f"---\ntitle: Shielding {tok}\ntype: concept\nsources: [{raw}]\n---\n"
        f"# Shielding {tok}\n\nShielding plan for the gamma bunker, reference {tok}.\n"
    )


def _seed(shard: str, tok: str | None) -> None:
    raw, page = f"{NAMES[shard]}-plan.md", f"{NAMES[shard]}-page.md"
    body = tok or "public"
    db_context.ensure_shard(shard)
    with db_context.using_db(shard):
        wiki_engine.init_wiki()
        dedup.register_file(_raw_text(body).encode(), raw)
        chunker.write_chunks(raw, chunker.split(_raw_text(body)))
        (db_context.wiki_dir() / page).write_text(_page_text(body, raw))
        (db_context.wiki_dir() / "DESCRIPTION.md").write_text(f"Overview {body}\n")
        wiki_engine._append_log(f"Ingest {raw}", f"created {page} ({body})")
        wiki_engine._rebuild_index()
        lex_index.build()


@pytest.fixture
def classified_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db_context, "DATA_ROOT", tmp_path)
    monkeypatch.setenv("INGEST_QA", "0")
    monkeypatch.setenv("INGEST_DESCRIPTION", "0")
    db_context.set_active_db(DB)
    with db_context.clearance({DB: 2}):
        for shard, tok in TOKENS.items():
            _seed(shard, tok)
    yield tmp_path
    db_context.set_active_db(DB)
    db_context.set_search_scope([])


@pytest.fixture
def prompts(monkeypatch) -> list[str]:
    """Every text handed to the local LLM, however it is called."""
    seen: list[str] = []

    def spy(system: str, prompt: str, **_kw: Any) -> str:
        seen.append(f"{system}\n{prompt}")
        return "Answer from the wiki."

    monkeypatch.setattr(ollama_client, "generate", spy)
    return seen


@contextmanager
def session(level: int) -> Iterator[None]:
    """What the app does for a user with `level` clearance in DB `KI`."""
    with db_context.clearance({DB: level}):
        db_context.set_active_db(DB)
        db_context.set_search_scope(db_context.reachable_shards(DB))
        try:
            yield
        finally:
            db_context.set_search_scope([])


def _leaked(text: object, level: int, names: bool = True) -> list[str]:
    """Tokens in `text` that a user with `level` clearance must not see."""
    s = str(text)
    tokens = [(1, CONF), (2, STRICT)] + ([(1, CONF_NAME), (2, STRICT_NAME)] if names else [])
    return [tok for lvl, tok in tokens if lvl > level and tok in s]


# Names a user (or a prompt-injected model) might try, for every secret file.
def _probes() -> list[str]:
    out: list[str] = []
    for shard, tok in TOKENS.items():
        if tok is None:
            continue
        lvl = shard.split("@")[1]
        for name in (f"{NAMES[shard]}-plan.md", f"{NAMES[shard]}-page.md"):
            out += [
                name,
                f"{shard}::{name}",
                f"../_levels/{lvl}/raw/{name}",
                f"../_levels/{lvl}/wiki/{name}",
                f"../../{DB}/_levels/{lvl}/raw/{name}",
            ]
    return out


# --- engine entry points ------------------------------------------------------


def _engine_listings() -> str:
    parts: list[Any] = [
        wiki_engine.list_pages(include_insights=True),
        wiki_engine.get_wiki_tree(),
        wiki_engine.search_wiki("shielding gamma bunker"),
        wiki_engine.read_log(),
        wiki_engine.read_description(),
        wiki_engine.stats(),
        dedup.list_sources(),
        graph_export.export(),
    ]
    return "\n".join(map(str, parts))


def _engine_probes() -> str:
    parts: list[Any] = []
    for name in _probes():
        parts += [wiki_engine.read_page(name), wiki_engine.read_page_parsed(name)]
        parts.append(wiki_engine.read_raw_source(name))
    return "\n".join(map(str, parts))


@pytest.mark.parametrize("level", [0, 1])
def test_engine_reads_never_reach_a_higher_level(classified_db, level):
    with session(level):
        assert _leaked(_engine_listings(), level) == []
        assert _leaked(_engine_probes(), level, names=False) == []
        assert not dedup.is_duplicate(_raw_text(STRICT).encode())


def test_a_cleared_user_reads_the_level_through_its_shard(classified_db):
    with session(2), db_context.using_db("KI@strict"):
        assert STRICT_NAME in _engine_listings()
        assert STRICT in _engine_probes()


@pytest.mark.parametrize("level", [0, 1])
def test_binding_a_higher_shard_is_refused(classified_db, level):
    with session(level), pytest.raises(db_context.AccessDenied):
        db_context.using_db("KI@strict").__enter__()


# --- agent tools ----------------------------------------------------------------


def _tool_searches() -> str:
    q = "shielding plan gamma bunker reference"
    parts = [
        tools.raw_search.invoke({"query": q}),
        tools.raw_search.invoke({"queries": [q, "reference bunker"]}),  # thread-pool path
        tools.wiki_search.invoke({"query": q}),
        tools.wiki_search.invoke({"queries": [q, "reference bunker"]}),
    ]
    return "\n".join(parts)


def _tool_reads() -> str:
    return "\n".join(
        [
            tools.raw_read.invoke({"filenames": _probes()}),
            tools.wiki_read.invoke({"filenames": _probes()}),
        ]
    )


@pytest.mark.parametrize("level", [0, 1])
def test_tools_never_reach_a_higher_level(classified_db, level):
    with session(level):
        assert _leaked(_tool_searches(), level) == []
        assert _leaked(_tool_reads(), level, names=False) == []


def test_tools_reach_every_level_of_a_cleared_user(classified_db):
    with session(2):
        searches, reads = _tool_searches(), _tool_reads()
    assert STRICT_NAME in searches
    assert CONF in reads
    assert STRICT in reads


def test_the_gate_is_what_blocks_the_tools(classified_db, monkeypatch):
    """Bypass meta-test: with `require` disabled the same probes do leak."""
    monkeypatch.setattr(db_context, "require", lambda _shard: None)
    db_context.set_search_scope(["KI", "KI@strict"])
    try:
        assert STRICT in _tool_reads()
    finally:
        db_context.set_search_scope([])


# --- fast chat (query_with_sources) --------------------------------------------


@pytest.mark.parametrize("level", [0, 1])
def test_fast_chat_prompts_and_answer_stay_below_clearance(classified_db, prompts, level):
    with session(level):
        result = wiki_engine.query_with_sources("What is the shielding plan for the bunker?")
    assert _leaked(result, level) == []
    assert _leaked(prompts, level) == []


def test_fast_chat_uses_every_level_of_a_cleared_user(classified_db, prompts):
    with session(2):
        wiki_engine.query_with_sources("What is the shielding plan for the bunker?")
    assert STRICT in "\n".join(prompts)


# --- agents (deep chat, quick research) ------------------------------------------


class ScriptedLLM:
    """Stands in for ChatOllama.bind_tools(...): replays tool calls, records prompts."""

    def __init__(self, calls: list[tuple[str, dict[str, Any]]]):
        self._calls = list(calls)
        self.seen: list[str] = []

    def invoke(self, messages: list[Any]) -> AIMessage:
        self.seen += [str(getattr(m, "content", m)) for m in messages]
        if not self._calls:
            return AIMessage(content="Final answer. [Source: plan.md]")
        name, args = self._calls.pop(0)
        call = {"name": name, "args": args, "id": f"c{len(self._calls)}", "type": "tool_call"}
        return AIMessage(content="", tool_calls=[call])


def _script() -> list[tuple[str, dict[str, Any]]]:
    return [
        ("raw_search", {"query": "shielding plan reference"}),
        ("raw_read", {"filenames": _probes()}),
        ("wiki_search", {"query": "shielding gamma bunker"}),
        ("wiki_read", {"filenames": _probes()}),
    ]


def _run(module: Any, run: Any, monkeypatch, prompts: list[str]) -> str:
    llm = ScriptedLLM(_script())
    monkeypatch.setattr(module, "_build_llm", lambda: llm)
    steps = list(run("What is the shielding plan for the bunker?"))
    return "\n".join([str(steps), *llm.seen, *prompts])


@pytest.mark.parametrize(
    ("module", "entry"),
    [(chat_agent, "run_chat_agent"), (agent, "run_research_agent")],
)
@pytest.mark.parametrize("level", [0, 1])
def test_agents_never_see_a_higher_level(classified_db, prompts, monkeypatch, module, entry, level):
    with session(level):
        out = _run(module, getattr(module, entry), monkeypatch, prompts)
    assert _leaked(out, level, names=False) == []


@pytest.mark.parametrize(
    ("module", "entry"),
    [(chat_agent, "run_chat_agent"), (agent, "run_research_agent")],
)
def test_agents_see_every_level_of_a_cleared_user(
    classified_db, prompts, monkeypatch, module, entry
):
    with session(2):
        out = _run(module, getattr(module, entry), monkeypatch, prompts)
    assert STRICT in out


def test_research_system_prompt_indexes_every_reachable_level(classified_db):
    with session(2):
        prompt = agent._system_prompt("")
    assert f"KI@strict::{STRICT_NAME}-page.md" in prompt


# --- graph cache ------------------------------------------------------------------


def test_the_graph_cache_never_serves_a_higher_level(classified_db):
    """Process-wide st.cache_data: a cleared render first must not leak into a later one."""
    graph_widget._payload.clear()
    with session(2), db_context.using_db("KI@strict"):
        assert STRICT in str(graph_widget._payload(graph_widget._bundle_signature()))
    with session(0):
        assert _leaked(graph_widget._payload(graph_widget._bundle_signature()), 0) == []


@pytest.mark.parametrize("level", [0, 1])
def test_agent_system_prompts_list_no_higher_level_files(classified_db, level):
    with session(level):
        prompts = [chat_agent._system_prompt(), agent._system_prompt("")]
    assert _leaked(prompts, level) == []
