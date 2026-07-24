"""Multi-database Wiki Chat: retrieval fan-out across a search scope.

Two real indexed DBs ("Alpha", "Beta") that deliberately share a filename
(`shared.md`) so DB-qualification and read-routing are actually exercised.
"""

from concurrent.futures import ThreadPoolExecutor

import pytest

import chat_agent
import chunker
import db_context
import lex_index
import run_memory
import tools
import wiki_engine


ALPHA_RAW = """\
## Reactor shielding
Alpha lead shielding attenuates gamma radiation by a factor of ten.

## Alpha disposal
Alpha waste goes to the interim storage facility.
"""

BETA_RAW = """\
## Portfolio shielding
Beta hedging shields a portfolio from gamma exposure in options markets.

## Beta disposal
Beta disposes of expiring contracts each quarter.
"""

ALPHA_PAGE = """\
---
title: Shielding Basics
sources: [alpha.md]
---
Alpha lead shielding attenuates gamma radiation in reactor containment.
"""

BETA_PAGE = """\
---
title: Shielding Basics
sources: [beta.md]
---
Beta hedging shields a portfolio from gamma exposure in derivatives.
"""


def _seed_db(name: str, raw_name: str, raw_text: str, page_text: str) -> None:
    """Build one DB: a raw source + a wiki page, both indexed."""
    with db_context.using_db(name):
        for sub in ("raw", "chunks", "index", "wiki"):
            (db_context.data_root() / sub).mkdir(parents=True, exist_ok=True)
        (db_context.raw_dir() / raw_name).write_text(raw_text)
        (db_context.raw_dir() / "shared.md").write_text(raw_text)
        chunker.write_chunks(raw_name, chunker.split(raw_text))
        chunker.write_chunks("shared.md", chunker.split(raw_text))
        (db_context.wiki_dir() / "shielding.md").write_text(page_text)
        lex_index.build()


@pytest.fixture()
def two_dbs(tmp_path, monkeypatch):
    monkeypatch.setattr(db_context, "DATA_ROOT", tmp_path)
    db_context.set_active_db("Alpha")
    db_context.set_search_scope([])
    _seed_db("Alpha", "alpha.md", ALPHA_RAW, ALPHA_PAGE)
    _seed_db("Beta", "beta.md", BETA_RAW, BETA_PAGE)
    db_context.set_active_db("Alpha")
    yield
    db_context.set_search_scope([])


# --- raw_search fan-out ---------------------------------------------------

def test_raw_search_single_db_scope_is_unqualified(two_dbs):
    """Default (one DB) behaviour must be byte-identical to the pre-scope path."""
    out = tools._raw_search_one("shielding", 6)
    assert "alpha.md" in out
    assert "Alpha::" not in out
    assert "beta.md" not in out
    assert "Database:" not in out


def test_raw_search_spans_scope_and_qualifies(two_dbs):
    db_context.set_search_scope(["Alpha", "Beta"])
    out = tools._raw_search_one("shielding", 6)
    assert "Alpha::alpha.md" in out
    assert "Beta::beta.md" in out
    assert "### Database: Alpha" in out and "### Database: Beta" in out


def test_raw_search_reports_per_db_misses(two_dbs):
    """A DB with no hits is named, so the model sees it was searched."""
    db_context.set_search_scope(["Alpha", "Beta"])
    out = tools._raw_search_one("interim storage facility", 6)
    assert "Alpha::alpha.md" in out
    assert "### Database: Beta\n(no results)" in out


def test_raw_search_splits_budget_across_dbs(two_dbs, monkeypatch):
    seen = []

    def fake_search(q, top_k, scope=None, use_rerank=False):
        seen.append(top_k)
        return []

    # _raw_search_db now goes through the hybrid entry point (retrieval.search).
    monkeypatch.setattr(tools.retrieval, "search", fake_search)
    db_context.set_search_scope(["Alpha", "Beta"])
    tools._raw_search_one("x", 6)
    assert seen == [3, 3]  # 6 split two ways, not 6 each


def test_per_db_budget_has_a_floor(two_dbs):
    db_context.set_search_scope(["Alpha", "Beta"])
    assert tools._per_db_budget(2) == tools.MIN_HITS_PER_DB


# --- wiki_search fan-out --------------------------------------------------

def test_wiki_search_spans_scope_and_qualifies(two_dbs):
    db_context.set_search_scope(["Alpha", "Beta"])
    out = tools._wiki_search_one("shielding", 8)
    assert "file: Alpha::shielding.md" in out
    assert "file: Beta::shielding.md" in out


def test_wiki_search_single_scope_unqualified(two_dbs):
    out = tools._wiki_search_one("shielding", 8)
    assert "file: shielding.md" in out
    assert "::" not in out


# --- read routing ---------------------------------------------------------

def test_wiki_read_routes_qualified_ref_to_its_db(two_dbs):
    db_context.set_search_scope(["Alpha", "Beta"])
    out = tools._wiki_read_one("Beta::shielding.md")
    assert "portfolio" in out.lower()
    assert "reactor" not in out.lower()


def test_raw_read_routes_qualified_ref_to_its_db(two_dbs):
    db_context.set_search_scope(["Alpha", "Beta"])
    out = tools._raw_read_one("Beta::beta.md")
    assert "Beta hedging" in out
    assert "Alpha lead" not in out


def test_raw_read_disambiguates_same_named_file_across_dbs(two_dbs):
    """`shared.md` exists in both DBs — the prefix decides which one is read."""
    db_context.set_search_scope(["Alpha", "Beta"])
    a = tools._raw_read_one("Alpha::shared.md")
    b = tools._raw_read_one("Beta::shared.md")
    assert "Alpha lead" in a and "Beta hedging" not in a
    assert "Beta hedging" in b and "Alpha lead" not in b


def test_raw_read_unqualified_falls_back_to_active_db(two_dbs):
    """A model that forgets the prefix still gets a real file, not an error."""
    db_context.set_search_scope(["Alpha", "Beta"])
    out = tools._raw_read_one("shared.md")
    assert "Alpha lead" in out


def test_raw_read_section_of_qualified_ref(two_dbs):
    db_context.set_search_scope(["Alpha", "Beta"])
    out = tools._raw_read_one("Beta::beta.md Beta disposal")
    assert "expiring contracts" in out
    assert "Beta::beta.md" in out  # echoes a re-usable qualified name


def test_raw_read_missing_qualified_ref_reports_not_found(two_dbs):
    db_context.set_search_scope(["Alpha", "Beta"])
    assert "(not found)" in tools._raw_read_one("Beta::nope.md")


# --- read guard keying ----------------------------------------------------

def test_read_guard_keys_are_db_distinct(two_dbs):
    """Same filename in two DBs must not collapse into one visited entry."""
    run_memory.begin_run()
    db_context.set_search_scope(["Alpha", "Beta"])
    first = tools.raw_read.func(["Alpha::shared.md"])
    second = tools.raw_read.func(["Beta::shared.md"])
    assert "[memory]" not in second, "Beta read was wrongly suppressed as a duplicate"
    assert "Alpha lead" in first and "Beta hedging" in second


def test_read_guard_still_catches_true_duplicates(two_dbs):
    run_memory.begin_run()
    db_context.set_search_scope(["Alpha", "Beta"])
    tools.raw_read.func(["Beta::shared.md"])
    again = tools.raw_read.func(["Beta::shared.md"])
    assert "[memory]" in again


# --- thread-pool context propagation --------------------------------------

def test_with_active_db_restores_scope_in_worker(two_dbs):
    """Workers don't inherit ContextVars — a lost scope silently narrows search."""
    db_context.set_search_scope(["Alpha", "Beta"])

    def _probe(_):
        return db_context.search_scope()

    with ThreadPoolExecutor(max_workers=1) as ex:
        got = list(ex.map(tools._with_active_db(_probe), [1]))
    assert got == [("Alpha", "Beta")]


def test_parallel_raw_search_keeps_scope(two_dbs):
    db_context.set_search_scope(["Alpha", "Beta"])
    out = tools._raw_search_impl(queries=["shielding", "disposal"])
    assert "Alpha::" in out and "Beta::" in out


# --- chat_agent raw index -------------------------------------------------

def test_raw_index_single_db_is_ungrouped(two_dbs):
    text = chat_agent._build_raw_index()
    assert "- alpha.md" in text
    assert "Database" not in text


def test_raw_index_groups_and_qualifies_across_scope(two_dbs):
    db_context.set_search_scope(["Alpha", "Beta"])
    text = chat_agent._build_raw_index()
    assert "Database Alpha:" in text and "Database Beta:" in text
    assert "- Alpha::alpha.md" in text and "- Beta::beta.md" in text


# --- citation parsing -----------------------------------------------------

def test_wiki_cite_regex_accepts_qualified_page():
    assert chat_agent._WIKI_CITE_RE.findall("see [Wiki: Beta::shielding.md] ok") == [
        "Beta::shielding.md"
    ]


def test_raw_cite_regex_accepts_qualified_source():
    got = chat_agent._RAW_CITE_RE.findall("per [Source: Alpha::alpha.md] and more")
    assert got == ["Alpha::alpha.md"]


def test_submit_gate_counts_qualified_sources_from_distinct_dbs():
    answer = "word " * 400 + "[Source: Alpha::alpha.md] [Source: Beta::beta.md]"
    assert tools._submit_chat_impl(answer).startswith("ACCEPTED")


# --- Fast-mode fan-out ----------------------------------------------------

def test_query_with_sources_fans_out_one_synthesis_call(two_dbs, monkeypatch):
    calls = []

    def fake_generate(system, prompt, **kw):
        calls.append(prompt)
        return "shielding.md" if "Select" in prompt or kw.get("model_id") else "answer"

    monkeypatch.setattr(wiki_engine.ollama_client, "generate", fake_generate)
    monkeypatch.setattr(wiki_engine.schema_loader, "get_system_prompt", lambda mode: "sys")
    monkeypatch.setattr(wiki_engine, "_select_pages", lambda q, s, i: ["shielding.md"])
    db_context.set_search_scope(["Alpha", "Beta"])

    res = wiki_engine.query_with_sources("shielding")

    assert len(calls) == 1, "synthesis must stay a single LLM call regardless of scope"
    assert res["sources"] == ["Alpha::shielding.md", "Beta::shielding.md"]
    assert res["raw_sources"] == ["Alpha::alpha.md", "Beta::beta.md"]
    assert "===== Database: Alpha =====" in calls[0]
    assert "===== Database: Beta =====" in calls[0]


def test_query_with_sources_single_db_unqualified(two_dbs, monkeypatch):
    calls = []
    monkeypatch.setattr(wiki_engine.ollama_client, "generate",
                        lambda s, p, **kw: calls.append(p) or "answer")
    monkeypatch.setattr(wiki_engine.schema_loader, "get_system_prompt", lambda mode: "sys")
    monkeypatch.setattr(wiki_engine, "_select_pages", lambda q, s, i: ["shielding.md"])

    res = wiki_engine.query_with_sources("shielding")

    assert res["sources"] == ["shielding.md"]
    assert res["raw_sources"] == ["alpha.md"]
    assert "Database:" not in calls[0]


def test_query_with_sources_splits_synthesis_budget(two_dbs, monkeypatch):
    """N DBs must not multiply the synthesis context by N."""
    monkeypatch.setattr(wiki_engine, "_QUERY_SYNTH_MAX_CHARS", 6000)
    monkeypatch.setattr(wiki_engine, "_QUERY_MIN_DB_SYNTH_CHARS", 100)
    budgets = []
    monkeypatch.setattr(wiki_engine, "_gather_pages",
                        lambda q, s, b: budgets.append(b) or ("", [], set()))
    monkeypatch.setattr(wiki_engine.ollama_client, "generate", lambda s, p, **kw: "a")
    monkeypatch.setattr(wiki_engine.schema_loader, "get_system_prompt", lambda mode: "sys")
    db_context.set_search_scope(["Alpha", "Beta"])

    wiki_engine.query_with_sources("shielding")
    assert budgets == [3000, 3000]
