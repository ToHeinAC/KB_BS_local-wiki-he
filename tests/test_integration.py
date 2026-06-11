"""End-to-end ingest→query round-trip with a deterministic mocked Ollama.

Regression net for the ingest-quality + retrieval changes (roadmap I-1/I-2/Q-*).
No live Ollama: `generate()` is routed by prompt content. QA + description LLM
sidecars are disabled by the `wiki_dir` fixture (INGEST_QA / INGEST_DESCRIPTION = 0).
"""

from unittest.mock import MagicMock

import frontmatter

import ollama_client
import wiki_engine

# Deterministic source-summary + concept page the ingest synthesis call emits.
_SOURCE_A_PAGES = (
    "=== summary-strlschg.md ===\n"
    "---\ntitle: StrlSchG\ntype: source-summary\nsources: [\"strlschg.md\"]\n"
    "related: []\nconfidence: high\n---\n"
    "The Strahlenschutzgesetz sets the annual effective dose limit for occupationally "
    "exposed persons at 20 millisievert.\n"
    "=== END ===\n"
    "=== dose-limit.md ===\n"
    "---\ntitle: Dose Limit\ntype: concept\nsources: [\"strlschg.md\"]\n"
    "related: []\nconfidence: high\n---\n"
    "The annual effective dose limit for occupationally exposed persons is 20 mSv "
    "per year under the Strahlenschutzgesetz.\n"
    "=== END ==="
)


def _route(system, prompt, **kwargs):
    """Return a canned response based on which prompt template is in play."""
    if prompt.startswith("You are ingesting a new source document"):
        return {"response": _SOURCE_A_PAGES}
    if prompt.startswith("Wiki index:"):  # SELECT_PROMPT
        return {"response": "dose-limit.md\n"}
    if prompt.startswith("Using only the wiki pages below"):  # ANSWER_PROMPT
        return {"response": "The annual limit is 20 mSv [Dose Limit]."}
    return {"response": ""}


def _mock(monkeypatch):
    mock = MagicMock()
    mock.generate.side_effect = lambda system, prompt, **kw: _route(system, prompt, **kw)
    monkeypatch.setattr(ollama_client, "_client", lambda: mock)
    return mock


def test_ingest_creates_valid_page_then_query_grounds_in_it(wiki_dir, monkeypatch):
    _mock(monkeypatch)

    result = wiki_engine.ingest("StrlSchG dose limit 20 mSv", "strlschg.md")
    assert "dose-limit.md" in result["created"]

    # Page exists with valid YAML frontmatter and the expected provenance.
    page = wiki_dir / "dose-limit.md"
    assert page.exists()
    post = frontmatter.load(str(page))
    assert post.metadata["type"] == "concept"
    assert "strlschg.md" in post.metadata["sources"]

    # Query selects the page and answers grounded in its content.
    out = wiki_engine.query_with_sources("Was ist der Jahresdosisgrenzwert?")
    assert "dose-limit.md" in out["sources"]
    assert "20 mSv" in out["answer"]
    assert "strlschg.md" in out["raw_sources"]


def test_second_source_merges_into_existing_page_no_duplicate(wiki_dir, monkeypatch):
    """A second source touching the same concept must MERGE (existing content
    injected for the synthesis call), not spawn a parallel page."""
    _mock(monkeypatch)

    wiki_engine.ingest("StrlSchG dose limit 20 mSv", "strlschg.md")
    pages_after_first = {p["filename"] for p in wiki_engine.list_pages()}
    assert "dose-limit.md" in pages_after_first

    # Capture the ingest prompt of the second source to confirm the existing
    # page body was pre-loaded via BM25 selection.
    seen = {}
    real_route = _route

    def _capture(system, prompt, **kw):
        if prompt.startswith("You are ingesting a new source document"):
            seen["ingest_prompt"] = prompt
        return real_route(system, prompt, **kw)

    mock = MagicMock()
    mock.generate.side_effect = lambda system, prompt, **kw: _capture(system, prompt, **kw)
    monkeypatch.setattr(ollama_client, "_client", lambda: mock)

    wiki_engine.ingest("Occupational dose limit 20 mSv per year clarification", "strlschv.md")

    assert "ingest_prompt" in seen
    # BM25 surfaced the existing concept page and its body was injected to merge.
    assert "Existing page content" in seen["ingest_prompt"]
    assert "dose-limit.md" in seen["ingest_prompt"]

    # The concept page set is unchanged (merged in place, not duplicated), and
    # the second source is now recorded in the page's provenance.
    assert {p["filename"] for p in wiki_engine.list_pages()} == pages_after_first
    post = frontmatter.load(str(wiki_dir / "dose-limit.md"))
    assert "strlschv.md" in post.metadata["sources"]
