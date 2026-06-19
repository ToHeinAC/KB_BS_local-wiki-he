"""Tests for the one-off wiki consolidation (legacy duplicate cleanup)."""

import frontmatter

import wiki_engine


def _write(wiki_dir, name, title, ptype, body, sources=None, related=None):
    meta = {"title": title, "type": ptype, "sources": sources or [], "related": related or []}
    (wiki_dir / name).write_text(frontmatter.dumps(frontmatter.Post(body, **meta)) + "\n")


def test_dry_run_writes_nothing(wiki_dir):
    _write(wiki_dir, "summary-doc-md-teil-1-2.md", "Doc [Teil 1/2]", "source-summary", "Part one")
    _write(wiki_dir, "summary-doc-md-teil-2-2.md", "Doc [Teil 2/2]", "source-summary", "Part two")
    before = sorted(p.name for p in wiki_dir.glob("*.md"))
    res = wiki_engine.consolidate(dry_run=True)
    after = sorted(p.name for p in wiki_dir.glob("*.md"))
    assert before == after                      # nothing written
    assert res["after"] < res["before"]         # but a reduction is planned


def test_collapses_teil_summaries(wiki_dir):
    _write(wiki_dir, "summary-doc-md-teil-1-2.md", "Doc [Teil 1/2]", "source-summary",
           "## Key facts\n- a\nPart one body")
    _write(wiki_dir, "summary-doc-md-teil-2-2.md", "Doc [Teil 2/2]", "source-summary",
           "## Key facts\n- b\nPart two body")
    wiki_engine.consolidate(dry_run=False)
    summaries = sorted(p.name for p in wiki_dir.glob("summary-*.md"))
    assert summaries == ["summary-doc.md"]
    body = (wiki_dir / "summary-doc.md").read_text()
    assert "Part one body" in body and "Part two body" in body


def test_collapses_near_duplicate_concepts(wiki_dir):
    _write(wiki_dir, "concept-dense-llm.md", "Dense LLM", "concept", "## Key facts\n- x\nFrom one")
    _write(wiki_dir, "concept-dense-llms.md", "Dense LLMs", "concept", "## Key facts\n- y\nFrom two")
    wiki_engine.consolidate(dry_run=False)
    concepts = sorted(p.name for p in wiki_dir.glob("concept-*.md"))
    assert concepts == ["concept-dense-llm.md"]   # shorter/more-general kept
    body = (wiki_dir / "concept-dense-llm.md").read_text()
    assert "From one" in body and "From two" in body


def test_remaps_related_and_cleans_citations(wiki_dir):
    _write(wiki_dir, "concept-dense-llm.md", "Dense LLM", "concept",
           "Cite [doc.md [Teil 1/2].md] here.")
    _write(wiki_dir, "concept-dense-llms.md", "Dense LLMs", "concept", "Body two")
    _write(wiki_dir, "concept-other.md", "Other", "concept", "Body",
           related=["concept-dense-llms.md"])
    wiki_engine.consolidate(dry_run=False)
    other = frontmatter.load(str(wiki_dir / "concept-other.md"))
    assert other.metadata["related"] == ["concept-dense-llm.md"]  # repointed
    kept = (wiki_dir / "concept-dense-llm.md").read_text()
    assert "[Teil 1/2]" not in kept and ".md.md" not in kept     # citation cleaned


def test_clean_teil_text_collapses_repeated_md():
    assert wiki_engine._clean_teil_text("[x.md.md]") == "[x.md]"
    assert wiki_engine._clean_teil_text("[x.md.md.md]") == "[x.md]"   # triple
    assert wiki_engine._clean_teil_text("[x [Teil 3/5].md]") == "[x.md]"
    assert wiki_engine._clean_teil_text("plain.md ref") == "plain.md ref"


def test_summary_base_normalizes_variants():
    b = wiki_engine._summary_base
    assert b("summary-jc-8-atomenergie_bf.md") == b("summary-jc-8-atomenergie-bf.md")
    assert b("summary-source-summary-jc-8-atomenergie-bf.md") == b("summary-jc-8-atomenergie-bf.md")
    assert b("summary-doc-md-teil-1-2.md") == b("summary-doc-md-teil-2-2.md")


def test_idempotent_on_clean_wiki(wiki_dir):
    _write(wiki_dir, "concept-alpha.md", "Alpha", "concept", "## Key facts\n- a\nBody")
    res1 = wiki_engine.consolidate(dry_run=False)
    files1 = sorted(p.name for p in wiki_dir.glob("*.md"))
    res2 = wiki_engine.consolidate(dry_run=False)
    files2 = sorted(p.name for p in wiki_dir.glob("*.md"))
    assert files1 == files2
    assert res2["rename"] == {}
