"""Tests for tools.py — deep researcher tools."""

from unittest.mock import MagicMock, patch

import chunker
import lex_index
import run_memory
import tools

# --- tavily_search --------------------------------------------------------


def _fake_tavily_response(q):
    return {
        "answer": f"answer for {q}",
        "results": [{"title": f"T-{q}", "url": f"http://e.com/{q}", "content": "x" * 50}],
    }


def test_tavily_search_single_query(monkeypatch):
    fake_client = MagicMock()
    fake_client.search.side_effect = lambda q, **kw: _fake_tavily_response(q)
    monkeypatch.setenv("TAVILY_API_KEY", "test")
    with patch("tavily.TavilyClient", return_value=fake_client):
        out = tools._tavily_search_impl(query="rust")
    assert "rust" in out
    assert "http://e.com/rust" in out


def test_tavily_search_parallel_batch(monkeypatch):
    calls = []
    fake_client = MagicMock()

    def fake_search(q, **kw):
        calls.append(q)
        return _fake_tavily_response(q)

    fake_client.search.side_effect = fake_search
    monkeypatch.setenv("TAVILY_API_KEY", "test")
    with patch("tavily.TavilyClient", return_value=fake_client):
        out = tools._tavily_search_impl(queries=["a", "b", "c"])
    assert set(calls) == {"a", "b", "c"}
    assert "## Query: a" in out
    assert "## Query: b" in out
    assert "## Query: c" in out


def test_tavily_search_empty_input_returns_error():
    out = tools._tavily_search_impl()
    assert "Error" in out


# --- fetch_webpage_content ------------------------------------------------


def test_fetch_webpage_returns_markdown(monkeypatch):
    fake_resp = MagicMock(text="<h1>Hi</h1><p>body</p>")
    fake_resp.raise_for_status = lambda: None
    with patch("httpx.get", return_value=fake_resp):
        out = tools._fetch_webpage_impl(["http://x.com"])
    assert "Hi" in out
    assert "http://x.com" in out


def test_fetch_webpage_handles_failure(monkeypatch):
    with patch("httpx.get", side_effect=RuntimeError("boom")):
        out = tools._fetch_webpage_impl("http://x.com")
    assert "fetch failed" in out


# --- submit_final_answer --------------------------------------------------


def test_submit_rejects_short_answer(tmp_path, monkeypatch):
    monkeypatch.setattr(tools.db_context, "wiki_dir", lambda: tmp_path)
    monkeypatch.setattr(tools, "MIN_WORDS", 100)
    monkeypatch.setattr(tools, "MIN_URLS", 2)
    out = tools._submit_final_impl("T", "too short http://a.com")
    assert out.startswith("REJECTED")
    assert "words" in out


def test_submit_rejects_few_sources(tmp_path, monkeypatch):
    monkeypatch.setattr(tools.db_context, "wiki_dir", lambda: tmp_path)
    monkeypatch.setattr(tools, "MIN_WORDS", 3)
    monkeypatch.setattr(tools, "MIN_URLS", 3)
    out = tools._submit_final_impl("T", "one two three http://a.com")
    assert out.startswith("REJECTED")
    assert "sources" in out


def test_submit_accepts_and_writes_file(tmp_path, monkeypatch):
    monkeypatch.setattr(tools.db_context, "wiki_dir", lambda: tmp_path)
    monkeypatch.setattr(tools, "MIN_WORDS", 3)
    monkeypatch.setattr(tools, "MIN_URLS", 2)
    out = tools._submit_final_impl("My Report", "alpha beta gamma http://a.com http://b.com")
    assert out.startswith("ACCEPTED")
    written = (tmp_path / "comparisons" / "report-my-report.md").read_text()
    assert "My Report" in written
    assert "http://a.com" in written


def test_submit_accepts_wiki_citations_as_sources(tmp_path, monkeypatch):
    monkeypatch.setattr(tools.db_context, "wiki_dir", lambda: tmp_path)
    monkeypatch.setattr(tools, "MIN_WORDS", 3)
    monkeypatch.setattr(tools, "MIN_URLS", 2)
    out = tools._submit_final_impl(
        "Wiki Only", "alpha beta gamma [Wiki: siemens-ag.md] [Wiki: sap-se.md]"
    )
    assert out.startswith("ACCEPTED")
    written = (tmp_path / "comparisons" / "report-wiki-only.md").read_text()
    assert "wiki:siemens-ag.md" in written


def test_submit_accepts_file_source_citations(tmp_path, monkeypatch):
    monkeypatch.setattr(tools.db_context, "wiki_dir", lambda: tmp_path)
    monkeypatch.setattr(tools, "MIN_WORDS", 3)
    monkeypatch.setattr(tools, "MIN_URLS", 2)
    out = tools._submit_final_impl(
        "Legal", "alpha beta gamma [Source: StrlSchG.md § 78] [Source: StrlSchV.md § 33]"
    )
    assert out.startswith("ACCEPTED")
    assert "2 source cites" in out
    written = (tmp_path / "comparisons" / "report-legal.md").read_text()
    assert "src:StrlSchG.md § 78" in written


def test_submit_report_survives_a_quoted_title(tmp_path, monkeypatch):
    """Frontmatter is YAML-serialised, not f-string interpolated. An LLM title
    containing a quote or colon used to emit invalid YAML that okf passes
    through unchanged, leaving a report on disk that could not be read back."""
    import frontmatter as _fm

    monkeypatch.setattr(tools.db_context, "wiki_dir", lambda: tmp_path)
    monkeypatch.setattr(tools, "MIN_WORDS", 3)
    monkeypatch.setattr(tools, "MIN_URLS", 2)
    title = 'Thesis: "potential 100x baggers")'
    out = tools._submit_final_impl(title, "alpha beta gamma http://a.com http://b.com")
    assert out.startswith("ACCEPTED")
    path = tmp_path / "comparisons" / out.split("comparisons/")[1].split(" ")[0]
    post = _fm.load(str(path))  # would raise ParserError before the fix
    assert post.metadata["title"] == title
    assert "alpha beta gamma" in post.content


def test_submit_does_not_double_count_url_source_citations(tmp_path, monkeypatch):
    monkeypatch.setattr(tools.db_context, "wiki_dir", lambda: tmp_path)
    monkeypatch.setattr(tools, "MIN_WORDS", 3)
    monkeypatch.setattr(tools, "MIN_URLS", 2)
    # A single [Source: <URL>.html] must count once (as a URL), not twice.
    out = tools._submit_final_impl("Once", "alpha beta gamma [Source: https://x.com/a.html]")
    assert out.startswith("REJECTED")
    assert "1 unique source" in out


# --- wiki_search / wiki_read ---------------------------------------------


def test_wiki_search_returns_hits(monkeypatch):
    fake_hits = [
        {"filename": "siemens-ag.md", "title": "Siemens AG", "excerpt": "industrial..."},
        {"filename": "sap-se.md", "title": "SAP SE", "excerpt": "ERP..."},
    ]
    monkeypatch.setattr(tools.wiki_engine, "search_wiki", lambda q: fake_hits)
    out = tools._wiki_search_impl(query="german industrial")
    assert "siemens-ag.md" in out
    assert "Siemens AG" in out
    assert "industrial..." in out


def test_wiki_search_no_results(monkeypatch):
    monkeypatch.setattr(tools.wiki_engine, "search_wiki", lambda q: [])
    out = tools._wiki_search_impl(query="unknown")
    assert "(no results)" in out


def test_wiki_search_parallel_batch(monkeypatch):
    seen = []

    def fake(q):
        seen.append(q)
        return [{"filename": f"{q}.md", "title": q, "excerpt": ""}]

    monkeypatch.setattr(tools.wiki_engine, "search_wiki", fake)
    out = tools._wiki_search_impl(queries=["a", "b", "c"])
    assert set(seen) == {"a", "b", "c"}
    assert "a.md" in out
    assert "b.md" in out
    assert "c.md" in out


def test_wiki_search_appends_linked_pages(monkeypatch):
    monkeypatch.setattr(tools, "WIKI_LINK_EXPANSION", True)
    monkeypatch.setattr(
        tools.wiki_engine,
        "search_wiki",
        lambda q: [{"filename": "a.md", "title": "A", "excerpt": "hit"}],
    )
    captured = {}

    def fake_linked(seeds, limit):
        captured["seeds"] = seeds
        return [{"filename": "b.md", "title": "B", "excerpt": "nbr", "via": "a.md"}]

    monkeypatch.setattr(tools.wiki_engine, "linked_pages", fake_linked)
    out = tools._wiki_search_impl(query="x")
    assert captured["seeds"] == ["a.md"]
    assert "Wiki linked 1" in out
    assert "b.md" in out
    assert "related via a.md" in out


def test_wiki_search_link_expansion_skips_already_shown(monkeypatch):
    monkeypatch.setattr(tools, "WIKI_LINK_EXPANSION", True)
    monkeypatch.setattr(
        tools.wiki_engine,
        "search_wiki",
        lambda q: [{"filename": "a.md", "title": "A", "excerpt": "hit"}],
    )
    # linked_pages returns a page already present as a direct hit -> filtered out
    monkeypatch.setattr(
        tools.wiki_engine,
        "linked_pages",
        lambda seeds, limit: [{"filename": "a.md", "title": "A", "excerpt": "", "via": "a.md"}],
    )
    out = tools._wiki_search_impl(query="x")
    assert "Wiki linked" not in out


def test_wiki_search_link_expansion_disabled(monkeypatch):
    monkeypatch.setattr(tools, "WIKI_LINK_EXPANSION", False)
    monkeypatch.setattr(
        tools.wiki_engine,
        "search_wiki",
        lambda q: [{"filename": "a.md", "title": "A", "excerpt": "hit"}],
    )
    monkeypatch.setattr(
        tools.wiki_engine,
        "linked_pages",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("should not be called")),
    )
    out = tools._wiki_search_impl(query="x")
    assert "Wiki linked" not in out


def test_wiki_read_returns_body(monkeypatch):
    monkeypatch.setattr(tools.wiki_engine, "read_page", lambda f: f"BODY OF {f}")
    out = tools._wiki_read_impl(["siemens-ag.md"])
    assert "siemens-ag.md" in out
    assert "BODY OF siemens-ag.md" in out


def test_wiki_read_empty_input():
    assert "Error" in tools._wiki_read_impl([])


def test_research_tools_include_raw_search_and_read():
    names = {getattr(t, "name", None) for t in tools.TOOLS}
    assert {"wiki_search", "raw_search", "raw_read"} <= names  # research can drill into raw docs


# --- raw_read section resolution ------------------------------------------


def _ingest_source(name: str, text: str):
    """Write a raw source + its chunks so section-aware raw_read can resolve."""
    (tools.db_context.raw_dir() / name).write_text(text, encoding="utf-8")
    chunker.write_chunks(name, chunker.split(text))


_LEGAL_DOC = (
    "# StrlSchG\n\n"
    "## § 61 Anfall und Lagerung\n"
    + "Regelungen zum Anfall ueberwachungsbeduerftiger Rueckstaende. "
    * 5
    + "\n\n"
    "## § 62 Entlassung aus der Ueberwachung\n"
    + "Entlassung von Rueckstaenden aus der Ueberwachung erfolgt auf Antrag. "
    * 5
    + "\n\n"
    "## § 63 Verbleibende Rueckstaende\n"
    + "In der Ueberwachung verbleibende Rueckstaende unterliegen Auflagen. " * 5
    + "\n"
)

_MD_DOC = (
    "# Guide\n\n"
    "## Overview\n"
    + "This guide gives a broad overview of the monitoring process and scope. "
    * 4
    + "\n\n"
    "## Release Procedure\n"
    + "The release procedure describes how items leave monitoring on request. "
    * 4
    + "\n\n"
    "## Limits\n"
    + "Limits define the numeric thresholds applied during the assessment phase. " * 4
    + "\n"
)


def test_raw_read_resolves_legal_section(wiki_dir):
    _ingest_source("StrlSchG.md", _LEGAL_DOC)
    out62 = tools._raw_read_one("StrlSchG.md § 62")
    out63 = tools._raw_read_one("StrlSchG.md § 63")
    assert "§ 62" in out62
    assert "Entlassung" in out62
    assert "§ 63" in out63
    assert "verbleibende" in out63
    assert out62 != out63  # distinct sections, not the same offset-0 window


def test_raw_read_resolves_markdown_heading(wiki_dir):
    _ingest_source("guide.md", _MD_DOC)
    out = tools._raw_read_one("guide.md ## Release Procedure")
    assert "Release Procedure" in out
    assert "release procedure" in out
    assert "Overview" not in out.split("\n", 1)[1]  # not the wrong section body


def test_raw_read_section_memory_keys_distinct(wiki_dir):
    _ingest_source("StrlSchG.md", _LEGAL_DOC)
    run_memory.begin_run()
    a = tools.raw_read.invoke({"filenames": ["StrlSchG.md § 61"]})
    b = tools.raw_read.invoke({"filenames": ["StrlSchG.md § 62"]})
    assert "[memory" not in a
    assert "[memory" not in b  # different section is a fresh read
    again = tools.raw_read.invoke(
        {"filenames": ["StrlSchG.md §61"]}
    )  # same section, other spelling
    assert "[memory: repeat of step 1 → serving the next unread" in again
    assert "Regelungen zum Anfall" not in again.split("\n", 1)[0]  # not § 61 served twice


def test_a_repeated_read_serves_the_next_unread_window(wiki_dir):
    cap = tools.RAW_READ_CAP
    (tools.db_context.raw_dir() / "big.md").write_text("x" * (cap * 3), encoding="utf-8")
    run_memory.begin_run()
    first = tools.raw_read.invoke({"filenames": ["big.md"], "offset": 0})
    assert "[memory] Already read" not in first
    dup = tools.raw_read.invoke({"filenames": ["big.md"], "offset": 0})
    assert f"(bytes {cap}-{2 * cap} of {3 * cap}) [memory: repeat of step 1" in dup  # served


def test_a_repeated_read_of_a_fully_read_file_says_so(wiki_dir):
    cap = tools.RAW_READ_CAP
    (tools.db_context.raw_dir() / "small.md").write_text("y" * (cap // 2), encoding="utf-8")
    run_memory.begin_run()
    tools.raw_read.invoke({"filenames": ["small.md"], "offset": 0})  # whole file in one window
    dup = tools.raw_read.invoke({"filenames": ["small.md"], "offset": 0})
    assert "[memory] small.md fully explored for this question" in dup
    assert "offset=" not in dup


def test_raw_read_nudges_submit_after_paginating(wiki_dir):
    cap = tools.RAW_READ_CAP
    (tools.db_context.raw_dir() / "big.md").write_text("z" * (cap * 4), encoding="utf-8")
    run_memory.begin_run()
    first = tools.raw_read.invoke({"filenames": ["big.md"], "offset": 0})
    assert "Stop paginating" not in first  # one window read, no nudge yet
    second = tools.raw_read.invoke({"filenames": ["big.md"], "offset": cap})
    assert "Stop paginating" not in second  # a deep answer may read a few windows
    third = tools.raw_read.invoke({"filenames": ["big.md"], "offset": 2 * cap})
    assert "Stop paginating" in third  # RAW_READ_NUDGE_AFTER=3 windows reached
    assert "submit_chat_answer" in third


# --- think_tool -----------------------------------------------------------


def test_think_tool_passthrough():
    assert tools.TOOL_FUNCTIONS["think_tool"]("just thinking") == "just thinking"


# --- Deep chat: wiki access ------------------------------------------------


def test_chat_tools_expose_wiki_search_and_read():
    """Deep chat can navigate the wiki (and thus follow `related:` links)."""
    names = {t.name for t in tools.CHAT_TOOLS}
    assert {"wiki_search", "wiki_read"} <= names
    assert {"raw_search", "raw_read"} <= names  # still raw-grounded


def test_a_deep_chat_answer_needs_3_sources() -> None:
    assert tools._submit_chat_impl("word " * 520 + "[Source: a.md] [Source: b.md]").startswith(
        "REJECTED"
    )


def test_the_word_floor_grows_with_the_cited_sources() -> None:
    # A flat floor makes a small model pad thin evidence with uncited text; the floor is
    # ~100 words per cited source, never above CHAT_MIN_WORDS.
    three = "[Source: a.md] [Source: b.md] [Wiki: c.md]"
    short = tools._submit_chat_impl("word " * 280 + three)
    assert short.startswith("REJECTED")
    assert "300" in short
    assert tools._submit_chat_impl("word " * 320 + three).startswith("ACCEPTED")
    six = three + " [Source: d.md] [Source: e.md] [Source: f.md]"
    capped = tools._submit_chat_impl("word " * 450 + six)
    assert capped.startswith("REJECTED")
    assert "500" in capped


def _gate_ready(monkeypatch) -> run_memory.RunMemory:
    monkeypatch.setattr(tools, "CHAT_MIN_WORDS", 5)
    monkeypatch.setattr(tools, "CHAT_MIN_SOURCES", 2)
    return run_memory.begin_run()


def test_a_deep_chat_answer_needs_the_minimum_number_of_searches(monkeypatch):
    mem = _gate_ready(monkeypatch)
    mem.mark_search("rsearch:grenzwert")
    mem.mark_read("raw:a.md:0")
    out = tools._submit_chat_impl("one two three four five six [Source: a.md] [Source: b.md]")
    assert out.startswith("REJECTED")
    assert "search" in out


def test_one_query_in_both_scopes_is_one_search(monkeypatch):
    # The pre-flight runs the question as a raw and a wiki search: one query, so the model
    # still has two searches of its own to make before the gate (minimum 3) accepts.
    mem = _gate_ready(monkeypatch)
    for key in ("raw_search:frage", "wiki_search:frage", "raw_search:b"):
        mem.mark_search(key)
    mem.mark_read("raw:a.md:0")
    answer = "one two three four five six [Source: a.md] [Source: b.md]"
    out = tools._submit_chat_impl(answer)
    assert out.startswith("REJECTED: 2 distinct searches")
    mem.mark_search("raw_search:c")
    assert tools._submit_chat_impl(answer).startswith("ACCEPTED")


def test_a_deep_chat_answer_must_have_read_an_original_it_cites(monkeypatch):
    mem = _gate_ready(monkeypatch)
    for q in ("a", "b", "c"):
        mem.mark_search(f"rsearch:{q}")
    answer = "one two three four five six [Source: a.md §2] [Source: b.md]"
    out = tools._submit_chat_impl(answer)
    assert out.startswith("REJECTED")
    assert "raw_read" in out
    mem.mark_read("raw:a.md|sec=§ 2:0")
    assert tools._submit_chat_impl(answer).startswith("ACCEPTED")


def test_submit_chat_counts_wiki_citations(monkeypatch):
    monkeypatch.setattr(tools, "CHAT_MIN_WORDS", 5)
    monkeypatch.setattr(tools, "CHAT_MIN_SOURCES", 2)
    answer = "one two three four five [Source: raw.md] and [Wiki: page.md]"
    assert tools._submit_chat_impl(answer).startswith("ACCEPTED")


def test_submit_chat_wiki_cite_alone_does_not_meet_source_gate(monkeypatch):
    """Wiki pages orient the agent; grounding still needs a second source."""
    monkeypatch.setattr(tools, "CHAT_MIN_WORDS", 5)
    monkeypatch.setattr(tools, "CHAT_MIN_SOURCES", 2)
    answer = "one two three four five [Wiki: page.md]"
    assert tools._submit_chat_impl(answer).startswith("REJECTED")


def test_submit_chat_low_confidence_nudges_once(monkeypatch, tmp_path):
    """Stage E soft gate: when no passage cleared τ, nudge to abstain — exactly once,
    so it can never stall the loop."""
    import json

    import db_context
    import run_memory

    monkeypatch.setattr(db_context, "DATA_ROOT", tmp_path)
    db_context.set_active_db("KI")
    idx = tmp_path / "KI" / "index"
    idx.mkdir(parents=True)
    (idx / "calibration.json").write_text(json.dumps({"tau": -4.14}))
    monkeypatch.setattr(tools, "CHAT_MIN_WORDS", 5)
    monkeypatch.setattr(tools, "CHAT_MIN_SOURCES", 2)
    monkeypatch.setattr(tools, "CHAT_MIN_SEARCHES", 0)
    answer = "one two three four five [Source: raw.md] and [Wiki: page.md]"
    try:
        mem = run_memory.begin_run()
        mem.mark_read("raw:raw.md:0")
        mem.note_relevance(-6.0)  # best passage below τ
        assert tools._submit_chat_impl(answer).startswith("LOW CONFIDENCE")
        assert tools._submit_chat_impl(answer).startswith("ACCEPTED")  # bounded to one fire
    finally:
        run_memory.begin_run()  # clear the run scratchpad so it can't leak to later tests


def test_submit_final_low_confidence_nudges_once(monkeypatch, tmp_path):
    """Stage E soft gate on the research path — mirrors the chat gate: nudge to abstain
    exactly once when no passage cleared τ, then accept (never stalls the loop)."""
    import json

    import db_context

    monkeypatch.setattr(db_context, "DATA_ROOT", tmp_path)
    db_context.set_active_db("KI")
    idx = tmp_path / "KI" / "index"
    idx.mkdir(parents=True)
    (idx / "calibration.json").write_text(json.dumps({"tau": -4.14}))
    monkeypatch.setattr(tools.db_context, "wiki_dir", lambda: tmp_path)
    monkeypatch.setattr(tools, "MIN_WORDS", 3)
    monkeypatch.setattr(tools, "MIN_URLS", 1)
    answer = "one two three [Source: raw.md]"
    try:
        mem = run_memory.begin_run()
        mem.note_relevance(-6.0)  # best passage below τ
        assert tools._submit_final_impl("T", answer).startswith("LOW CONFIDENCE")
        assert tools._submit_final_impl("T", answer).startswith("ACCEPTED")  # bounded to one fire
    finally:
        run_memory.begin_run()


def test_current_run_audit_splits_sources_by_tau(monkeypatch, tmp_path):
    """current_run_audit builds the ladder record from per-source scores in run memory."""
    import json

    import db_context

    monkeypatch.setattr(db_context, "DATA_ROOT", tmp_path)
    db_context.set_active_db("KI")
    idx = tmp_path / "KI" / "index"
    idx.mkdir(parents=True)
    (idx / "calibration.json").write_text(json.dumps({"tau": -4.0}))
    try:
        mem = run_memory.begin_run()
        mem.note_source_relevance("good.md", -1.0)
        mem.note_source_relevance("good.md", -8.0)  # keeps the max
        mem.note_source_relevance("weak.md", -6.0)
        audit = tools.current_run_audit()
        assert audit is not None
        assert audit["kept"] == [("good.md", -1.0)]
        assert audit["below_tau"] == [("weak.md", -6.0)]
    finally:
        run_memory.begin_run()


def test_current_run_audit_none_when_no_scored_source():
    """Wiki/web-only run scored no source ⇒ no audit panel."""
    try:
        run_memory.begin_run()
        assert tools.current_run_audit() is None
    finally:
        run_memory.begin_run()


def test_wiki_search_labels_shared_source_neighbours(monkeypatch):
    monkeypatch.setattr(tools, "WIKI_LINK_EXPANSION", True)
    monkeypatch.setattr(
        tools.wiki_engine,
        "search_wiki",
        lambda q: [{"filename": "a.md", "title": "A", "excerpt": "hit"}],
    )
    monkeypatch.setattr(
        tools.wiki_engine,
        "linked_pages",
        lambda seeds, limit: [
            {
                "filename": "b.md",
                "title": "B",
                "excerpt": "nbr",
                "via": "a.md",
                "kind": "shared-source",
            }
        ],
    )
    out = tools._wiki_search_impl(query="x")
    assert "shares a source with a.md" in out


# --- section-level grounding (ideas/deep-chat-read-memory-… Fix B) ---------

_LONG_LAW = (
    "# StrlSchG\n\n## § 1 Anwendungsbereich\n"
    + "Dieses Gesetz regelt den Schutz vor ionisierender Strahlung.\n\n" * 320
    + _LEGAL_DOC.split("\n\n", 1)[1]
)


def _grounding_run(monkeypatch) -> run_memory.RunMemory:
    _ingest_source("StrlSchG.md", _LONG_LAW)
    mem = _gate_ready(monkeypatch)
    for q in ("a", "b", "c"):
        mem.mark_search(f"raw_search:{q}")
    return mem


_TAGGED = "one two three four five six [Source: StrlSchG.md §62] [Source: StrlSchG.md §1]"


def test_a_cited_section_that_was_never_read_is_rejected_with_the_exact_call(wiki_dir, monkeypatch):
    _grounding_run(monkeypatch)
    tools.raw_read.invoke({"filenames": ["StrlSchG.md § 1"]})  # the file, not § 62
    out = tools._submit_chat_impl(_TAGGED)
    assert out.startswith("REJECTED: you cite § 62 of StrlSchG.md")
    assert "raw_read(['StrlSchG.md § 62'])" in out
    tools.raw_read.invoke({"filenames": ["StrlSchG.md §62"]})
    assert tools._submit_chat_impl(_TAGGED).startswith("ACCEPTED")


def test_a_byte_window_that_covers_the_cited_section_counts_as_reading_it(wiki_dir, monkeypatch):
    mem = _grounding_run(monkeypatch)
    start = _LONG_LAW.index("## § 62")
    tools.raw_read.invoke({"filenames": ["StrlSchG.md § 1"]})
    mem.mark_read(f"raw:StrlSchG.md:{start - 100}")
    assert tools._submit_chat_impl(_TAGGED).startswith("ACCEPTED")


def test_an_unread_section_named_only_in_the_prose_is_rejected_once(wiki_dir, monkeypatch):
    _grounding_run(monkeypatch)
    tools.raw_read.invoke({"filenames": ["StrlSchG.md § 1"]})
    answer = "Nach § 63 bleiben sie in der Ueberwachung [Source: StrlSchG.md §1] [Source: b.md]"
    out = tools._submit_chat_impl(answer)
    assert out.startswith("REJECTED: you cite § 63 of StrlSchG.md")
    assert tools._submit_chat_impl(answer).startswith("ACCEPTED")  # bounded: once per run


def test_a_section_of_a_law_that_is_not_cited_is_ignored(wiki_dir, monkeypatch):
    _grounding_run(monkeypatch)
    tools.raw_read.invoke({"filenames": ["StrlSchG.md § 1"]})
    answer = "Kernbrennstoff ist in § 2 AtG definiert [Source: StrlSchG.md §1] [Source: b.md]"
    assert tools._submit_chat_impl(answer).startswith("ACCEPTED")


# --- section map, auto-advance (Fix C, D) ----------------------------------


def _indexed_law(monkeypatch, question: str) -> run_memory.RunMemory:
    _ingest_source("StrlSchG.md", _LONG_LAW)
    lex_index.build()
    return run_memory.begin_run(question)


def test_a_bare_read_of_a_long_law_serves_the_best_sections_and_a_map(wiki_dir, monkeypatch):
    mem = _indexed_law(monkeypatch, "Entlassung von Rueckstaenden aus der Ueberwachung")
    out = tools.raw_read.invoke({"filenames": ["StrlSchG.md"]})
    assert out.startswith("## Raw file: StrlSchG.md — section map (")
    assert "## Raw file: StrlSchG.md § 62\nEntlassung" in out.replace("## § 62 ", "")
    assert "Map near the matches:" in out
    assert "Dieses Gesetz regelt" not in out  # not window 0
    assert "raw:StrlSchG.md|sec=62:0" in mem.reads  # served sections count as read


def test_a_bare_read_without_an_index_keeps_byte_window_zero(wiki_dir, monkeypatch):
    _ingest_source("StrlSchG.md", _LONG_LAW)
    run_memory.begin_run("Entlassung von Rueckstaenden")
    out = tools.raw_read.invoke({"filenames": ["StrlSchG.md"]})
    assert out.startswith("## Raw file: StrlSchG.md (bytes 0-")


def test_a_repeated_section_read_serves_the_next_best_unread_section(wiki_dir, monkeypatch):
    _indexed_law(monkeypatch, "Rueckstaende Ueberwachung Entlassung")
    tools.raw_read.invoke({"filenames": ["StrlSchG.md § 62"]})
    again = tools.raw_read.invoke({"filenames": ["StrlSchG.md § 62"]})
    head = again.split("\n", 1)[0]
    assert head.endswith("[memory: repeat of step 1 → serving the next unread best match]")
    assert "§ 61" in head or "§ 63" in head


def test_a_past_end_offset_is_clamped_and_not_remembered(wiki_dir):
    cap = tools.RAW_READ_CAP
    (tools.db_context.raw_dir() / "big.md").write_text("x" * (cap * 2), encoding="utf-8")
    mem = run_memory.begin_run()
    out = tools.raw_read.invoke({"filenames": ["big.md"], "offset": 1048576})
    assert "requested offset 1048576 is past the end; file has 32000 chars" in out
    assert "(bytes 0-16000 of 32000)" in out
    assert "raw:big.md:1048576" not in mem.reads


# --- reference footers and hop budget (Fix F) ------------------------------


def _chain(n: int) -> None:
    """Files L0…L{n-1}: § 1 of Lk says "nach § 1 der L{k+1}"; L0 § 1 also names § 2 (same
    file) and § 9 AtG (a law not in the database)."""
    for k in range(n):
        nxt = f" Die Pflichten folgen aus § 1 der L{k + 1}." if k + 1 < n else ""
        extra = " Abweichend gilt § 2. Kernbrennstoffe regelt § 9 AtG." if k == 0 else ""
        body = "".join(
            f"## § {i} Pflichten {i}\n" + "Text der Vorschrift ohne Bezug. " * 4 + "\n\n"
            for i in (1, 2, 3)
        )
        body = body.replace("Text der Vorschrift ohne Bezug. \n", f"Text.{nxt}{extra}\n", 1)
        _ingest_source(f"L{k}.md", f"# L{k}\n\n{body}")


def test_a_footer_lists_resolved_references_and_their_status(wiki_dir):
    _chain(2)
    run_memory.begin_run()
    out = tools.raw_read.invoke({"filenames": ["L0.md § 1"]})
    footer = out.rsplit("References: ", 1)[1]
    assert "L1.md § 1 (unread)" in footer
    assert "L0.md § 2 (same file, unread)" in footer
    assert "AtG § 9 (not in scope)" in footer
    assert "follow with raw_read(['L1.md § 1'])" in footer
    tools.raw_read.invoke({"filenames": ["L1.md § 1"]})
    again = tools.raw_read.invoke({"filenames": ["L0.md § 3"]})  # unrelated section: no refs
    assert "References:" not in again


def test_a_same_file_reference_takes_no_hop_and_earns_no_turns(wiki_dir):
    _chain(2)
    mem = run_memory.begin_run()
    tools.raw_read.invoke({"filenames": ["L0.md § 1"]})
    tools.raw_read.invoke({"filenames": ["L0.md § 2"]})
    assert mem.ref_depth["L0.md|sec=2"] == 0
    assert mem.bonus == 0
    tools.raw_read.invoke({"filenames": ["L1.md § 1"]})
    assert mem.ref_depth["L1.md|sec=1"] == 1
    assert mem.bonus == 2


def test_the_fourth_cross_file_hop_is_shown_as_the_hop_limit(wiki_dir):
    _chain(5)
    mem = run_memory.begin_run()
    outs = [tools.raw_read.invoke({"filenames": [f"L{k}.md § 1"]}) for k in range(4)]
    assert "L4.md § 1 (hop limit reached)" in outs[3]
    assert "follow with" not in outs[3].rsplit("References: ", 1)[1]
    assert mem.bonus == tools.REF_BONUS_MAX  # 3 followed hops, capped


def test_an_out_of_scope_reference_must_be_named_under_open_points_once(wiki_dir, monkeypatch):
    _chain(1)
    mem = _gate_ready(monkeypatch)
    for q in ("a", "b", "c"):
        mem.mark_search(f"raw_search:{q}")
    tools.raw_read.invoke({"filenames": ["L0.md § 1"]})
    tools.raw_read.invoke({"filenames": ["L0.md § 2"]})
    answer = "one two three four five six [Source: L0.md §1] [Source: L0.md §2]"
    out = tools._submit_chat_impl(answer)
    assert out.startswith("REJECTED")
    assert "AtG" in out
    assert "## Open points" in out
    assert tools._submit_chat_impl(answer).startswith("ACCEPTED")  # bounded: once per run
    mem.open_refs_nudged = False
    named = answer + "\n\n## Offene Punkte\n- § 9 AtG liegt nicht vor."
    assert tools._submit_chat_impl(named).startswith("ACCEPTED")


def test_a_work_name_resolves_through_the_ontology_to_the_version_in_force(wiki_dir, monkeypatch):
    _chain(1)
    _ingest_source("StrlSchV_2018.md", "# StrlSchV\n\n## § 12 Pflichten\n" + "Text. " * 30)
    view, frame = object(), type("F", (), {"works": ("strlschv",)})()
    monkeypatch.setattr(tools.ontology_store, "view", lambda: view)
    monkeypatch.setattr(
        tools.ontology_query, "resolve", lambda q, v: frame if "StrlSchV" in q else None
    )
    monkeypatch.setattr(
        tools.ontology_time, "current_expression", lambda v, w, d: "StrlSchV_2018.md"
    )
    run_memory.begin_run()
    assert tools._resolve_work("StrlSchV") == "StrlSchV_2018.md"
    assert tools._resolve_work("Strahlenschutzgesetzes") is None


def test_a_broken_reference_footer_never_costs_the_read(wiki_dir, monkeypatch):
    _chain(2)
    run_memory.begin_run()

    def boom(*_a, **_k):
        raise KeyError("Art.")

    monkeypatch.setattr(tools.refs, "find_refs", boom)
    out = tools.raw_read.invoke({"filenames": ["L0.md § 1"]})
    assert out.startswith("## Raw file: L0.md § 1")
    assert "References:" not in out


# --- quote check in the Deep chat gate (report tweak 5) ---------------------------------


def test_a_quote_the_cited_originals_do_not_contain_is_rejected_once(monkeypatch, raw_dir):
    # A small model "quotes" from memory; a quoted span is checkable in code, word for word,
    # against the originals it cites (line breaks and markdown emphasis aside).
    mem = _gate_ready(monkeypatch)
    for q in ("a", "b", "c"):
        mem.mark_search(f"rsearch:{q}")
    mem.mark_read("raw:a.md:0")
    (raw_dir / "a.md").write_text(
        "§ 62\nRückstände dürfen nur mit **Genehmigung** der\nzuständigen Behörde verwertet werden."
    )
    cite = " [Source: a.md] [Source: b.md]"
    good = "one two three „Rückstände dürfen nur mit Genehmigung der zuständigen Behörde“" + cite
    assert tools._submit_chat_impl(good).startswith("ACCEPTED")
    bad = 'one two three "Rückstände dürfen ohne jede Genehmigung verwertet werden"' + cite
    out = tools._submit_chat_impl(bad)
    assert out.startswith("REJECTED")
    assert "Rückstände dürfen ohne jede Genehmigung" in out
    assert tools._submit_chat_impl(bad).startswith("ACCEPTED")  # once: a weak model can't loop


def test_short_quoted_terms_are_not_checked(monkeypatch, raw_dir):
    mem = _gate_ready(monkeypatch)
    for q in ("a", "b", "c"):
        mem.mark_search(f"rsearch:{q}")
    mem.mark_read("raw:a.md:0")
    (raw_dir / "a.md").write_text("Text ohne den Begriff.")
    answer = (
        'one two three the term "überwachungsbedürftige Rückstände" [Source: a.md] [Source: b.md]'
    )
    assert tools._submit_chat_impl(answer).startswith("ACCEPTED")


# --- raw_search hit hygiene (report tweak 6) --------------------------------------------


def _hit(source: str, anchor: str, cid: str, rerank: float) -> dict:
    return {
        "source": source,
        "anchor": anchor,
        "chunk_id": cid,
        "rerank_score": rerank,
        "score": 1.0,
        "matched_terms": ["x"],
        "preview": f"text of {cid}",
    }


def test_raw_hits_keep_one_chunk_per_section_and_drop_those_below_tau(monkeypatch):
    # Near-duplicate and off-topic passages are distractors a small model cannot ignore;
    # the calibrated tau already marks "not relevant", so only the best hit may sit below it.
    hits = [
        _hit("a.md", "§ 62", "c1", 0.9),
        _hit("a.md", "§ 62", "c2", 0.8),  # second part of the same section
        _hit("b.md", "§ 3", "c3", 0.7),
        _hit("c.md", "§ 9", "c4", 0.1),  # below tau
    ]
    monkeypatch.setattr(tools.retrieval, "search", lambda *a, **k: hits)
    monkeypatch.setattr(tools.calibrate, "threshold", lambda db=None: 0.5)
    parts = tools._raw_search_db("q", 6)
    assert [p.split("chunk_id: ")[1].split("\n")[0] for p in parts] == ["c1", "c3"]
    assert parts[1].startswith("[Raw hit 2]")


def test_the_best_raw_hit_survives_even_below_tau(monkeypatch):
    monkeypatch.setattr(tools.retrieval, "search", lambda *a, **k: [_hit("a.md", "", "c1", 0.1)])
    monkeypatch.setattr(tools.calibrate, "threshold", lambda db=None: 0.5)
    assert len(tools._raw_search_db("q", 6)) == 1


# --- evidence ledger (answer tweak 1) ---------------------------------------------------


def test_every_raw_read_adds_its_matching_sentences_to_the_run_ledger(monkeypatch):
    mem = run_memory.begin_run("Grenzwert für Radon in Aufenthaltsräumen")
    text = "## Raw file: a.md § 5\nDer Grenzwert für Radon in Aufenthaltsräumen beträgt 300 Bq."
    monkeypatch.setattr(tools, "_memory_read", lambda m, f, offset: (text, f))
    monkeypatch.setattr(tools, "_pagination_nudge", lambda m, q: None)
    tools.raw_read.invoke({"filenames": ["a.md § 5"]})
    tools.raw_read.invoke({"filenames": ["a.md § 5"]})  # the same sentence is noted once
    assert mem.ledger == [
        ("a.md § 5", "Der Grenzwert für Radon in Aufenthaltsräumen beträgt 300 Bq.")
    ]
