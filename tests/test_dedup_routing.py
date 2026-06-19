"""Tests for deterministic dedup-routing + merge (model-independent)."""

from unittest.mock import MagicMock

import frontmatter

import ollama_client
import wiki_engine
import wiki_engine as w


# --- term canonicalization (the linchpin) -----------------------------------

def test_depluralize_handles_short_plurals():
    assert w._depluralize("llms") == "llm"
    assert w._depluralize("moe") == "moe"      # too short, untouched
    assert w._depluralize("ai") == "ai"
    assert w._depluralize("class") == "class"  # -ss never stripped


def test_term_key_does_not_double_strip():
    # `densing` -> stem `dens`; must NOT be depluralized to `den`.
    assert w._term_key("densing") == w._term_key("densing")
    assert w._term_key("llms") == w._term_key("llm")
    assert w._term_key("experts") == w._term_key("expert")


def test_canonical_slug_tokens_fold_plural_and_prefix():
    assert w._canonical_slug_tokens("dense-llms") == w._canonical_slug_tokens("concept-dense-llm.md")
    assert w._canonical_slug_tokens("Dense LLMs") == w._canonical_slug_tokens("dense-llm")


def test_canonical_slug_tokens_subset_relations():
    assert w._canonical_slug_tokens("edge-ai") <= w._canonical_slug_tokens("edge-ai-inference")
    assert w._canonical_slug_tokens("mixture-of-experts-moe") <= \
        w._canonical_slug_tokens("mixture-of-experts-moe-llms")


def test_densing_law_not_confused_with_dense_llm():
    a = w._canonical_slug_tokens("densing-law")
    b = w._canonical_slug_tokens("dense-llm")
    assert a != b and not (a <= b) and not (b <= a)


# --- _route_page -------------------------------------------------------------

def _reg(entries):
    return {fn: {"type": t, "tokens": w._canonical_slug_tokens(title),
                 "terms": frozenset(terms)}
            for fn, t, title, terms in entries}


def test_route_exact_topic_match():
    reg = _reg([("concept-dense-llm.md", "concept", "Dense LLM", ["dens", "llm"])])
    target = w._route_page("concept", w._canonical_slug_tokens("Dense LLMs"),
                           frozenset(["dens", "llm"]), reg, "concept-dense-llms.md")
    assert target == "concept-dense-llm.md"


def test_route_subset_requires_term_overlap():
    reg = _reg([("concept-edge-ai.md", "concept", "Edge AI", ["edge", "ai"])])
    target = w._route_page("concept", w._canonical_slug_tokens("Edge AI Inference"),
                           frozenset(["edge", "ai"]), reg, "concept-edge-ai-inference.md")
    assert target == "concept-edge-ai.md"


def test_route_no_match_for_unrelated():
    reg = _reg([("concept-dense-llm.md", "concept", "Dense LLM", ["dens", "llm"])])
    target = w._route_page("concept", w._canonical_slug_tokens("Densing Law"),
                           frozenset(["dens", "law"]), reg, "concept-densing-law.md")
    assert target is None


def test_route_never_crosses_type():
    reg = _reg([("summary-x.md", "source-summary", "Dense LLM", ["dens", "llm"])])
    target = w._route_page("concept", w._canonical_slug_tokens("Dense LLM"),
                           frozenset(["dens", "llm"]), reg, "concept-dense-llm.md")
    assert target is None


# --- key facts index ---------------------------------------------------------

def test_parse_and_extract_key_terms_roundtrip():
    content = ('---\ntitle: "Dense LLMs"\ntype: concept\n---\n'
               '## Key facts\n- transformer scaling\n- flash attention\n\nBody.')
    facts = w._parse_index_block(content)
    assert facts == ["transformer scaling", "flash attention"]
    terms = w._extract_key_terms(content)
    assert "llm" in terms and "transform" in " ".join(terms)


def test_ensure_index_block_synthesizes_when_missing():
    content = '---\ntitle: "Edge AI"\ntype: concept\n---\nSome prose without an index.'
    out = w._ensure_index_block(content)
    assert "## Key facts" in out


# --- deterministic merge -----------------------------------------------------

def test_merge_pages_unions_sections_without_dropping_facts():
    existing = ('---\ntitle: "X"\ntype: concept\nsources: ["a.md"]\ncreated: "2026-01-01"\n---\n'
                '## Overview\n- fact one\n')
    new = ('---\ntitle: "X"\ntype: concept\nsources: ["b.md"]\ncreated: "2026-02-01"\n---\n'
           '## Overview\n- fact two\n## Details\n- detail A\n')
    merged = w._merge_pages(existing, new, "b.md")
    assert "fact one" in merged and "fact two" in merged and "detail A" in merged
    meta = frontmatter.loads(merged).metadata
    assert set(meta["sources"]) == {"a.md", "b.md"}
    assert meta["created"] == "2026-01-01"  # earliest kept


def test_merge_pages_dedupes_identical_lines():
    page = ('---\ntitle: "X"\ntype: concept\n---\n## Overview\n- same fact\n')
    merged = w._merge_pages(page, page, "x.md")
    assert merged.count("- same fact") == 1


def test_merge_flags_numeric_contradiction_when_unresolved():
    existing = ('---\ntitle: "Dose"\ntype: concept\n---\n## Limits\n- annual limit is 20 mSv\n')
    new = ('---\ntitle: "Dose"\ntype: concept\n---\n## Limits\n- annual limit is 50 mSv\n')
    merged = w._merge_pages(existing, new, "n.md")
    assert "20 mSv" in merged and "50 mSv" in merged
    assert "## Contradictions" in merged


def test_merge_resolves_contradiction_with_date_signal():
    existing = ('---\ntitle: "Dose"\ntype: concept\nupdated: "2020-01-01"\n---\n'
                '## Limits\n- annual limit is 20 mSv\n')
    new = ('---\ntitle: "Dose"\ntype: concept\nupdated: "2026-01-01"\n---\n'
           '## Limits\n- annual limit is 50 mSv\n')
    merged = w._merge_pages(existing, new, "n.md")
    assert "newer source" in merged and "previously" in merged


# --- ingest-level: stable slug + in-ingest registry --------------------------

_PIECE1 = (
    "=== summary-doc.md ===\n---\ntitle: Doc\ntype: source-summary\n---\n## Key facts\n- s1\nP1\n=== END ===\n"
    "=== concept-dense-llm.md ===\n---\ntitle: Dense LLM\ntype: concept\n---\n## Key facts\n- dense\nC1\n=== END ==="
)
_PIECE2 = (
    "=== summary-doc-part2.md ===\n---\ntitle: Doc\ntype: source-summary\n---\n## Key facts\n- s2\nP2\n=== END ===\n"
    "=== concept-dense-llms.md ===\n---\ntitle: Dense LLMs\ntype: concept\n---\n## Key facts\n- dense2\nC2\n=== END ==="
)


def test_multipiece_collapses_to_one_summary_and_one_concept(wiki_dir, monkeypatch):
    mock = MagicMock()
    mock.generate.side_effect = [{"response": _PIECE1}, {"response": _PIECE2}]
    monkeypatch.setattr(ollama_client, "_client", lambda: mock)
    ctx = wiki_engine_ingest_two_pieces(monkeypatch)
    # exactly one summary file, named from the source ("mydoc.txt")
    summaries = sorted(p.name for p in wiki_dir.glob("summary-*.md"))
    assert summaries == ["summary-mydoc.md"]
    # the two concept variants collapsed into one page
    concepts = sorted(p.name for p in wiki_dir.glob("concept-*.md"))
    assert concepts == ["concept-dense-llm.md"]
    body = (wiki_dir / "concept-dense-llm.md").read_text()
    assert "C1" in body and "C2" in body  # nothing dropped


def wiki_engine_ingest_two_pieces(monkeypatch):
    ctx = wiki_engine.ingest_begin("full body", "mydoc.txt")
    wiki_engine.ingest_piece(ctx, "piece one", 0, 2)
    wiki_engine.ingest_piece(ctx, "piece two", 1, 2)
    return wiki_engine.ingest_end(ctx)
