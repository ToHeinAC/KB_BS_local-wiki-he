"""Tests for wiki_engine.py — core wiki operations."""

from datetime import date
from unittest.mock import MagicMock

import pytest

import ollama_client
import wiki_engine


# --- init_wiki ---

def _patch_root(monkeypatch, tmp_path):
    import db_context
    monkeypatch.setattr(db_context, "DATA_ROOT", tmp_path)
    db_context.set_active_db("t")
    return tmp_path / "t"


def test_init_wiki_creates_wiki_dir(tmp_path, monkeypatch):
    root = _patch_root(monkeypatch, tmp_path)
    wiki_engine.init_wiki()
    assert (root / "wiki").exists()


def test_init_wiki_creates_raw_dir(tmp_path, monkeypatch):
    root = _patch_root(monkeypatch, tmp_path)
    wiki_engine.init_wiki()
    assert (root / "raw").exists()


def test_init_wiki_creates_index(wiki_dir):
    assert (wiki_dir / "index.md").exists()


def test_init_wiki_creates_log(wiki_dir):
    assert (wiki_dir / "log.md").exists()


def test_init_wiki_does_not_overwrite_existing_index(wiki_dir):
    idx = wiki_dir / "index.md"
    idx.write_text("custom content")
    wiki_engine.init_wiki()
    assert idx.read_text() == "custom content"


# --- _parse_llm_pages ---

def test_parse_llm_pages_single_block():
    response = "=== concept.md ===\n---\ntitle: X\n---\nBody\n=== END ==="
    pages = wiki_engine._parse_llm_pages(response)
    assert len(pages) == 1
    assert pages[0]["filename"] == "concept.md"
    assert "Body" in pages[0]["content"]


def test_parse_llm_pages_multiple_blocks():
    response = (
        "=== a.md ===\ncontent A\n=== END ===\n"
        "=== b.md ===\ncontent B\n=== END ==="
    )
    pages = wiki_engine._parse_llm_pages(response)
    assert len(pages) == 2
    filenames = [p["filename"] for p in pages]
    assert "a.md" in filenames
    assert "b.md" in filenames


def test_parse_llm_pages_ignores_malformed():
    response = "no blocks here at all"
    pages = wiki_engine._parse_llm_pages(response)
    assert pages == []


def test_parse_llm_pages_empty_string():
    assert wiki_engine._parse_llm_pages("") == []


# --- ingest ---

_INGEST_RESPONSE = (
    "=== summary-mysrc.md ===\n"
    "---\ntitle: My Source\ntype: source-summary\n---\nSummary content\n"
    "=== END ===\n"
    "=== concept-alpha.md ===\n"
    "---\ntitle: Alpha\ntype: concept\n---\nAlpha content\n"
    "=== END ==="
)


def test_ingest_creates_wiki_files(wiki_dir, monkeypatch):
    mock = MagicMock()
    mock.generate.return_value = {"response": _INGEST_RESPONSE}
    monkeypatch.setattr(ollama_client, "_client", lambda: mock)
    wiki_engine.ingest("some text", "mysrc.txt")
    assert (wiki_dir / "summary-mysrc.md").exists()
    assert (wiki_dir / "concept-alpha.md").exists()


def test_ingest_returns_created_list(wiki_dir, monkeypatch):
    mock = MagicMock()
    mock.generate.return_value = {"response": _INGEST_RESPONSE}
    monkeypatch.setattr(ollama_client, "_client", lambda: mock)
    result = wiki_engine.ingest("text", "mysrc.txt")
    assert "summary-mysrc.md" in result["created"]
    assert "concept-alpha.md" in result["created"]


def test_ingest_detects_updated_pages(wiki_dir, monkeypatch):
    (wiki_dir / "concept-alpha.md").write_text("existing")
    mock = MagicMock()
    mock.generate.return_value = {"response": _INGEST_RESPONSE}
    monkeypatch.setattr(ollama_client, "_client", lambda: mock)
    result = wiki_engine.ingest("text", "mysrc.txt")
    assert "concept-alpha.md" in result["updated"]


def test_ingest_extracts_contradiction_lines(wiki_dir, monkeypatch):
    response = _INGEST_RESPONSE + "\nCONTRADICTION: Alpha conflicts with Beta"
    mock = MagicMock()
    mock.generate.return_value = {"response": response}
    monkeypatch.setattr(ollama_client, "_client", lambda: mock)
    result = wiki_engine.ingest("text", "src.txt")
    assert any("Alpha" in c for c in result["contradictions"])


def test_ingest_raises_runtime_error_when_ollama_down(wiki_dir, monkeypatch):
    mock = MagicMock()
    mock.generate.side_effect = Exception("connection refused")
    monkeypatch.setattr(ollama_client, "_client", lambda: mock)
    with pytest.raises(RuntimeError):
        wiki_engine.ingest("text", "src.txt")


def test_ingest_appends_to_log(wiki_dir, monkeypatch):
    mock = MagicMock()
    mock.generate.return_value = {"response": _INGEST_RESPONSE}
    monkeypatch.setattr(ollama_client, "_client", lambda: mock)
    wiki_engine.ingest("text", "mysrc.txt")
    log = (wiki_dir / "log.md").read_text()
    assert "Ingest" in log
    assert "mysrc.txt" in log


def test_ingest_injects_user_metadata_into_prompt(wiki_dir, monkeypatch):
    mock = MagicMock()
    mock.generate.return_value = {"response": _INGEST_RESPONSE}
    monkeypatch.setattr(ollama_client, "_client", lambda: mock)
    user_meta = {
        "name": "Alpha Spec",
        "fullname": "Alpha Specification v3",
        "description": "Reference doc for Alpha module",
        "effective as of": "2026-01-01",
        "part of": "Alpha programme",
    }
    wiki_engine.ingest("text", "mysrc.txt", user_meta)
    sent_prompt = mock.generate.call_args.kwargs["prompt"]
    assert "User-supplied metadata" in sent_prompt
    for v in user_meta.values():
        assert v in sent_prompt


def test_ingest_works_without_user_metadata(wiki_dir, monkeypatch):
    mock = MagicMock()
    mock.generate.return_value = {"response": _INGEST_RESPONSE}
    monkeypatch.setattr(ollama_client, "_client", lambda: mock)
    wiki_engine.ingest("text", "mysrc.txt", None)
    sent_prompt = mock.generate.call_args.kwargs["prompt"]
    assert "User-supplied metadata" not in sent_prompt
    # blank-only dict treated identically
    wiki_engine.ingest("text", "mysrc.txt", {"name": "", "part of": "  "})
    sent_prompt2 = mock.generate.call_args.kwargs["prompt"]
    assert "User-supplied metadata" not in sent_prompt2


# --- query ---

def test_query_returns_string(wiki_dir, monkeypatch):
    mock = MagicMock()
    mock.generate.return_value = {"response": "The answer is 42."}
    monkeypatch.setattr(ollama_client, "_client", lambda: mock)
    result = wiki_engine.query("What is the answer?")
    assert isinstance(result, str)
    assert "42" in result


def test_query_handles_empty_wiki(wiki_dir, monkeypatch):
    mock = MagicMock()
    mock.generate.return_value = {"response": "NONE"}
    monkeypatch.setattr(ollama_client, "_client", lambda: mock)
    result = wiki_engine.query("anything?")
    assert isinstance(result, str)


def test_query_raises_runtime_error_when_ollama_down(wiki_dir, monkeypatch):
    mock = MagicMock()
    mock.generate.side_effect = Exception("offline")
    monkeypatch.setattr(ollama_client, "_client", lambda: mock)
    with pytest.raises(RuntimeError):
        wiki_engine.query("question")


# --- lint ---

def test_lint_empty_wiki_returns_message(wiki_dir):
    result = wiki_engine.lint()
    assert "empty" in result.lower()


def test_lint_returns_report_string(wiki_dir, monkeypatch):
    (wiki_dir / "page.md").write_text("---\ntitle: Page\n---\nContent")
    mock = MagicMock()
    mock.generate.return_value = {"response": "Lint report: all good."}
    monkeypatch.setattr(ollama_client, "_client", lambda: mock)
    result = wiki_engine.lint()
    assert isinstance(result, str)
    assert "Lint report" in result


# --- list_pages ---

def test_list_pages_empty_wiki(wiki_dir):
    assert wiki_engine.list_pages() == []


def test_list_pages_returns_metadata(wiki_dir):
    (wiki_dir / "concept.md").write_text(
        "---\ntitle: My Concept\ntype: concept\nconfidence: high\n---\nContent"
    )
    pages = wiki_engine.list_pages()
    assert len(pages) == 1
    assert pages[0]["title"] == "My Concept"


def test_list_pages_excludes_system_files(wiki_dir):
    filenames = [p["filename"] for p in wiki_engine.list_pages()]
    assert "index.md" not in filenames
    assert "log.md" not in filenames


def test_list_pages_handles_no_frontmatter(wiki_dir):
    (wiki_dir / "bare.md").write_text("No frontmatter here")
    pages = wiki_engine.list_pages()
    assert any(p["filename"] == "bare.md" for p in pages)


# --- read_page / read_log / stats ---

def test_read_page_returns_content(wiki_dir):
    (wiki_dir / "p.md").write_text("page body")
    assert wiki_engine.read_page("p.md") == "page body"


def test_read_page_missing_returns_error_message(wiki_dir):
    result = wiki_engine.read_page("nonexistent.md")
    assert "not found" in result.lower()


def test_stats_correct_page_count(wiki_dir):
    (wiki_dir / "a.md").write_text("a")
    (wiki_dir / "b.md").write_text("b")
    s = wiki_engine.stats()
    assert s["pages"] == 2


def test_search_wiki_matches_title(wiki_dir):
    import lex_index
    (wiki_dir / "transformer.md").write_text(
        "---\ntitle: Transformer Architecture\ntype: concept\n---\nbody"
    )
    lex_index.build()  # wiki bodies + title/filename are indexed (R-1)
    hits = wiki_engine.search_wiki("transform")
    assert any(h["filename"] == "transformer.md" for h in hits)


def test_search_wiki_matches_body(wiki_dir):
    import lex_index
    (wiki_dir / "x.md").write_text(
        "---\ntitle: X\n---\nThe attention mechanism scales context windows."
    )
    lex_index.build()
    hits = wiki_engine.search_wiki("attention")
    assert len(hits) == 1
    assert "attention" in hits[0]["excerpt"].lower()


def test_search_wiki_empty_query_returns_empty(wiki_dir):
    (wiki_dir / "p.md").write_text("any content")
    assert wiki_engine.search_wiki("") == []
    assert wiki_engine.search_wiki("   ") == []


# --- Q-1: hybrid page selection ---

def test_candidate_pages_finds_body_match_absent_from_blurb(wiki_dir):
    """A term that lives in the page BODY (not its index blurb) still surfaces."""
    import lex_index
    (wiki_dir / "dose.md").write_text(
        '---\ntitle: Overview\ntype: concept\nsources: ["s.md"]\n---\n'
        "The annual effective limit is 20 millisievert for occupationally exposed workers."
    )
    lex_index.build()
    cands = wiki_engine._candidate_pages_for_query("millisievert limit workers")
    assert "dose.md" in cands


def test_candidate_pages_maps_raw_hit_to_page(wiki_dir):
    """A raw-chunk match maps back to its derived wiki page via `sources:`."""
    import chunker
    import lex_index
    (wiki_dir / "page.md").write_text(
        '---\ntitle: P\ntype: concept\nsources: ["src.md"]\n---\ngeneric overview body'
    )
    chunker.write_chunks("src.md", [{
        "chunk_id": "r1", "text": "plutonium isotope criticality safety threshold",
        "anchor": "", "heading_path": [], "char_start": 0, "char_end": 46, "lang": "en",
    }])
    lex_index.build()
    cands = wiki_engine._candidate_pages_for_query("plutonium criticality")
    assert "page.md" in cands


# --- Q-3: section-level synthesis ---

def test_query_synthesis_injects_chunks_not_full_page(wiki_dir, monkeypatch):
    import lex_index
    body = (
        "## Dose limits\nThe annual effective dose limit is 20 millisievert per year.\n\n"
        "## Banana farming\nUnrelated ZZZFILLER orchard gardening notes about bananas. " * 1
        + "## Weather\nZZZFILLER cloudy skies and rainfall patterns over the region described. "
        + "## Cooking\nZZZFILLER recipes for soup and bread baking at home in detail here. "
    )
    (wiki_dir / "dose.md").write_text(
        f'---\ntitle: Dose\ntype: concept\nsources: ["s.md"]\n---\n{body}'
    )
    lex_index.build()

    captured = {}

    def _route(system, prompt, **kw):
        if prompt.startswith("Wiki index:"):
            return {"response": "dose.md\n"}
        if prompt.startswith("Using only the wiki pages below"):
            captured["answer_prompt"] = prompt
            return {"response": "ok"}
        return {"response": ""}

    mock = MagicMock()
    mock.generate.side_effect = lambda system, prompt, **kw: _route(system, prompt, **kw)
    monkeypatch.setattr(ollama_client, "_client", lambda: mock)

    out = wiki_engine.query_with_sources("dose limit millisievert per year")
    assert out["sources"] == ["dose.md"]
    ap = captured["answer_prompt"]
    assert "20 millisievert" in ap          # the matching section is present
    assert "ZZZFILLER" not in ap            # unrelated sections are NOT injected (chunk-level, not full page)


# --- E-1: staleness ---

def test_is_page_stale_default_ttl():
    today = date(2026, 6, 11)
    old = {"updated": "2024-01-01"}          # >365 days before today
    fresh = {"updated": "2026-06-01"}
    assert wiki_engine.is_page_stale(old, today) is True
    assert wiki_engine.is_page_stale(fresh, today) is False


def test_is_page_stale_respects_expires_after_days_override():
    today = date(2026, 6, 11)
    # 100 days old: stale under a 30-day TTL, fresh under the 365-day default.
    page = {"updated": "2026-03-03", "expires_after_days": 30}
    assert wiki_engine.is_page_stale(page, today) is True
    assert wiki_engine.is_page_stale({"updated": "2026-03-03"}, today) is False


def test_is_page_stale_handles_missing_or_disabled():
    today = date(2026, 6, 11)
    assert wiki_engine.is_page_stale({}, today) is False                       # no updated
    assert wiki_engine.is_page_stale({"updated": "nonsense"}, today) is False  # unparseable
    assert wiki_engine.is_page_stale(                                          # TTL<=0 = never
        {"updated": "2000-01-01", "expires_after_days": 0}, today) is False


def test_stale_pages_lists_overdue_page(wiki_dir):
    (wiki_dir / "old.md").write_text(
        '---\ntitle: Old\ntype: concept\nupdated: "2020-01-01"\n---\nbody'
    )
    (wiki_dir / "new.md").write_text(
        f'---\ntitle: New\ntype: concept\nupdated: "{wiki_engine._date()}"\n---\nbody'
    )
    stale = wiki_engine.stale_pages()
    assert "old.md" in stale
    assert "new.md" not in stale


def test_lint_prepends_stale_pages(wiki_dir, monkeypatch):
    (wiki_dir / "old.md").write_text(
        '---\ntitle: Old\ntype: concept\nupdated: "2020-01-01"\n---\nbody'
    )
    mock = MagicMock()
    mock.generate.return_value = {"response": "LLM lint body"}
    monkeypatch.setattr(ollama_client, "_client", lambda: mock)
    report = wiki_engine.lint()
    assert "Possibly stale" in report
    assert "old.md" in report


# --- E-2: insights in wiki health ---

def test_list_pages_includes_insights_when_requested(wiki_dir):
    wiki_engine.file_answer("What is the dose limit?", "20 mSv per year.", ["dose.md"])
    without = {p["filename"] for p in wiki_engine.list_pages()}
    with_ins = {p["filename"] for p in wiki_engine.list_pages(include_insights=True)}
    assert not any(f.startswith("insights/") for f in without)   # default unchanged
    insight = next(f for f in with_ins if f.startswith("insights/"))
    page = next(p for p in wiki_engine.list_pages(include_insights=True)
                if p["filename"] == insight)
    assert page["type"] == "insight"


def test_rebuild_index_has_insights_section(wiki_dir):
    (wiki_dir / "concept-a.md").write_text("---\ntitle: A\ntype: concept\n---\nbody")
    wiki_engine.file_answer("Q?", "A.", [])
    wiki_engine._rebuild_index()
    index = (wiki_dir / "index.md").read_text()
    assert 'okf_version: "0.1"' in index  # OKF bundle-root declaration
    assert "# Insights" in index
    assert "insights/insight-q.md" in index


def test_file_answer_is_okf_enriched(wiki_dir):
    import frontmatter
    import okf
    rel = wiki_engine.file_answer("What is copper used for?",
                                  "Copper conducts electricity in wiring.", [])
    post = frontmatter.loads((wiki_dir / rel).read_text())
    assert post.metadata["tags"]              # OKF field code-stamped
    assert post.metadata["description"]
    assert "## Citations" in post.content     # regenerated from sources
    assert okf.okf_validate(wiki_dir) == []   # whole bundle stays conformant


def test_get_wiki_tree_groups_insights_and_flags_stale(wiki_dir):
    (wiki_dir / "old.md").write_text(
        '---\ntitle: Old\ntype: concept\nupdated: "2020-01-01"\n---\nbody'
    )
    wiki_engine.file_answer("Q?", "A.", [])
    tree = wiki_engine.get_wiki_tree()
    assert "insight" in tree and tree["insight"]
    old = next(p for p in tree["concept"] if p["filename"] == "old.md")
    assert old["stale"] is True


def test_get_wiki_tree_groups_by_type(wiki_dir):
    (wiki_dir / "a.md").write_text("---\ntitle: A\ntype: concept\n---\n")
    (wiki_dir / "b.md").write_text("---\ntitle: B\ntype: entity\n---\n")
    (wiki_dir / "c.md").write_text("---\ntitle: C\n---\n")
    tree = wiki_engine.get_wiki_tree()
    assert [p["filename"] for p in tree["concept"]] == ["a.md"]
    assert [p["filename"] for p in tree["entity"]] == ["b.md"]
    assert [p["filename"] for p in tree["other"]] == ["c.md"]
    assert "comparison" not in tree


# --- file_answer ---

def test_file_answer_creates_insight_page(wiki_dir):
    rel = wiki_engine.file_answer("What is X?", "X is the answer.", related=["a.md"])
    path = wiki_dir / rel
    assert path.exists()
    body = path.read_text()
    assert "type: comparison" in body
    assert "X is the answer." in body
    assert "a.md" in body


# --- build_link_graph / find_orphans ---

def test_find_orphans_returns_pages_with_no_inedges(wiki_dir):
    (wiki_dir / "a.md").write_text('---\ntitle: A\nrelated: ["b.md"]\n---\nA')
    (wiki_dir / "b.md").write_text("---\ntitle: B\nrelated: []\n---\nB")
    (wiki_dir / "c.md").write_text("---\ntitle: C\nrelated: []\n---\nC")
    orphans = wiki_engine.find_orphans()
    assert "b.md" not in orphans
    assert "a.md" in orphans
    assert "c.md" in orphans


# --- linked_pages (link-aware retrieval expansion) ---

def test_linked_pages_returns_one_hop_neighbours(wiki_dir):
    (wiki_dir / "a.md").write_text('---\ntitle: A\nrelated: ["b.md", "c.md"]\n---\nBody A')
    (wiki_dir / "b.md").write_text("---\ntitle: B\nrelated: []\n---\nBody B")
    (wiki_dir / "c.md").write_text("---\ntitle: C\nrelated: []\n---\nBody C")
    out = wiki_engine.linked_pages(["a.md"])
    names = {p["filename"] for p in out}
    assert names == {"b.md", "c.md"}
    assert all(p["via"] == "a.md" for p in out)
    assert next(p for p in out if p["filename"] == "b.md")["title"] == "B"


def test_linked_pages_excludes_seeds_and_missing_targets(wiki_dir):
    (wiki_dir / "a.md").write_text('---\ntitle: A\nrelated: ["b.md", "gone.md", "a.md"]\n---\nA')
    (wiki_dir / "b.md").write_text("---\ntitle: B\nrelated: []\n---\nB")
    out = wiki_engine.linked_pages(["a.md"])
    assert {p["filename"] for p in out} == {"b.md"}  # seed + nonexistent dropped


def test_linked_pages_ranks_by_link_count_and_caps(wiki_dir):
    (wiki_dir / "a.md").write_text('---\ntitle: A\nrelated: ["shared.md", "x.md"]\n---\nA')
    (wiki_dir / "b.md").write_text('---\ntitle: B\nrelated: ["shared.md"]\n---\nB')
    for n in ("shared.md", "x.md"):
        (wiki_dir / n).write_text(f"---\ntitle: {n}\nrelated: []\n---\n{n}")
    out = wiki_engine.linked_pages(["a.md", "b.md"], limit=1)
    assert [p["filename"] for p in out] == ["shared.md"]  # 2 links > 1 link, capped at 1


def test_linked_pages_includes_insight_neighbours(wiki_dir):
    (wiki_dir / "insights").mkdir(exist_ok=True)
    (wiki_dir / "insights" / "note.md").write_text("---\ntitle: Note\n---\nInsight body")
    (wiki_dir / "a.md").write_text('---\ntitle: A\nrelated: ["insights/note.md"]\n---\nA')
    out = wiki_engine.linked_pages(["a.md"])
    assert {p["filename"] for p in out} == {"insights/note.md"}
    assert out[0]["title"] == "Note"


# --- ingest with existing content + retry ---

def test_ingest_loads_existing_content_for_affected_pages(wiki_dir, monkeypatch):
    """BM25 selection: a page derived from a prior source whose chunks match the
    new text is surfaced, and its body is injected for merge."""
    import chunker
    import lex_index
    # Existing page derived from a prior source, present in the BM25 index.
    (wiki_dir / "alpha.md").write_text(
        '---\ntitle: Alpha\ntype: concept\nsources: ["prior.md"]\n---\n'
        '## Key facts\n- alpha radiation dose limit\n\nEXISTING_ALPHA_BODY'
    )
    chunker.write_chunks("prior.md", [{
        "chunk_id": "c-prior-1",
        "text": "Alpha radiation protection dose limits and shielding fundamentals.",
        "anchor": "", "heading_path": [], "char_start": 0, "char_end": 60, "lang": "en",
    }])
    lex_index.build()
    mock = MagicMock()
    mock.generate.return_value = {"response": _INGEST_RESPONSE}
    monkeypatch.setattr(ollama_client, "_client", lambda: mock)
    wiki_engine.ingest("source text about alpha radiation protection dose", "src.txt")
    # Only one generate call now (synthesis) — selection is BM25, not an LLM call.
    ingest_prompt = mock.generate.call_args.kwargs["prompt"]
    # The affected page is surfaced as a cheap REUSE candidate (key facts only),
    # not as a full-body injection — code-side merge is the real safety net.
    assert "alpha.md" in ingest_prompt
    assert "REUSE the exact filename" in ingest_prompt
    assert "alpha radiation dose limit" in ingest_prompt
    assert "EXISTING_ALPHA_BODY" not in ingest_prompt


def test_ingest_retries_when_no_pages_parsed(wiki_dir, monkeypatch):
    mock = MagicMock()
    mock.generate.side_effect = [
        {"response": "garbage no delimiters"},  # first INGEST attempt
        {"response": _INGEST_RESPONSE},         # retry attempt
    ]
    monkeypatch.setattr(ollama_client, "_client", lambda: mock)
    result = wiki_engine.ingest("text", "src.txt")
    assert "concept-alpha.md" in result["created"]
    # 2 calls: ingest + retry (selection is BM25, not an LLM call).
    assert mock.generate.call_count == 2


# --- resolve_contradiction ---

def test_resolve_contradiction_rewrites_pages(wiki_dir, monkeypatch):
    (wiki_dir / "a.md").write_text("OLD_A")
    response = "=== a.md ===\n---\ntitle: A\n---\nNEW_A_RESOLVED\n=== END ==="
    mock = MagicMock()
    mock.generate.return_value = {"response": response}
    monkeypatch.setattr(ollama_client, "_client", lambda: mock)
    res = wiki_engine.resolve_contradiction("A says X but B says Y", ["a.md"], "Trust source 1")
    assert "a.md" in res["updated"]
    assert "NEW_A_RESOLVED" in (wiki_dir / "a.md").read_text()


# --- Tier A: begin / piece / end split ---

def test_ingest_begin_piece_end_creates_pages(wiki_dir, monkeypatch):
    mock = MagicMock()
    mock.generate.return_value = {"response": _INGEST_RESPONSE}
    monkeypatch.setattr(ollama_client, "_client", lambda: mock)
    ctx = wiki_engine.ingest_begin("source body", "src.txt")
    wiki_engine.ingest_piece(ctx, "source body", 0, 1)
    result = wiki_engine.ingest_end(ctx)
    # Summary filename is derived from the SOURCE (src.txt), not the LLM's emitted
    # name, so every part of a document collapses to one summary page.
    assert "summary-src.md" in result["created"]
    assert "concept-alpha.md" in result["created"]
    assert (wiki_dir / "summary-src.md").exists()


def test_build_existing_block_rank_weighted_budget(wiki_dir):
    """Top-ranked page gets the largest merge window; tail pages get truncated."""
    (wiki_dir / "top.md").write_text("T" * 6000)
    (wiki_dir / "tail.md").write_text("L" * 6000)
    block = wiki_engine._build_existing_block(["top.md", "tail.md"])
    # rank 0 budget 4000, rank 1 budget 2000 (see _EXISTING_BUDGET_BY_RANK).
    assert block.count("T") == 4000
    assert block.count("L") == 2000
    assert "…[truncated]" in block


def test_source_to_pages_maps_frontmatter_sources(wiki_dir):
    (wiki_dir / "a.md").write_text('---\ntitle: A\nsources: ["s1.md", "s2.md"]\n---\nbody')
    (wiki_dir / "b.md").write_text('---\ntitle: B\nsources: ["s1.md"]\n---\nbody')
    mapping = wiki_engine._source_to_pages()
    assert set(mapping["s1.md"]) == {"a.md", "b.md"}
    assert mapping["s2.md"] == ["a.md"]


def test_ingest_affected_selection_adds_no_llm_calls_per_piece(wiki_dir, monkeypatch):
    """Affected-page selection is BM25 (no LLM), so generate runs once per piece only."""
    mock = MagicMock()
    mock.generate.return_value = {"response": _INGEST_RESPONSE}
    monkeypatch.setattr(ollama_client, "_client", lambda: mock)
    ctx = wiki_engine.ingest_begin("full text", "src.txt")
    for i in range(3):
        wiki_engine.ingest_piece(ctx, "piece text", i, 3)
    wiki_engine.ingest_end(ctx)
    # 3 synthesis calls, nothing extra for selection.
    assert mock.generate.call_count == 3


def test_ingest_back_compat_wrapper_still_works(wiki_dir, monkeypatch):
    mock = MagicMock()
    mock.generate.return_value = {"response": _INGEST_RESPONSE}
    monkeypatch.setattr(ollama_client, "_client", lambda: mock)
    result = wiki_engine.ingest("text", "mysrc.txt")
    assert "summary-mysrc.md" in result["created"]


def test_stats_excludes_manifest_from_raw_count(wiki_dir):
    import db_context
    raw = db_context.raw_dir()
    raw.mkdir(parents=True, exist_ok=True)
    (raw / "manifest.json").write_text("{}")
    (raw / "file.txt").write_bytes(b"x")
    s = wiki_engine.stats()
    assert s["raw_files"] == 1
