"""Tests for wiki_engine.py — core wiki operations."""

from unittest.mock import MagicMock

import pytest

import ollama_client
import wiki_engine


# --- init_wiki ---

def test_init_wiki_creates_wiki_dir(tmp_path, monkeypatch):
    wiki = tmp_path / "wiki"
    raw = tmp_path / "raw"
    monkeypatch.setattr(wiki_engine, "WIKI_DIR", wiki)
    monkeypatch.setattr(wiki_engine, "RAW_DIR", raw)
    monkeypatch.setattr(wiki_engine, "_INDEX", wiki / "index.md")
    monkeypatch.setattr(wiki_engine, "_LOG", wiki / "log.md")
    wiki_engine.init_wiki()
    assert wiki.exists()


def test_init_wiki_creates_raw_dir(tmp_path, monkeypatch):
    wiki = tmp_path / "wiki"
    raw = tmp_path / "raw"
    monkeypatch.setattr(wiki_engine, "WIKI_DIR", wiki)
    monkeypatch.setattr(wiki_engine, "RAW_DIR", raw)
    monkeypatch.setattr(wiki_engine, "_INDEX", wiki / "index.md")
    monkeypatch.setattr(wiki_engine, "_LOG", wiki / "log.md")
    wiki_engine.init_wiki()
    assert raw.exists()


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


def test_stats_excludes_manifest_from_raw_count(wiki_dir, monkeypatch):
    raw = wiki_dir.parent / "raw"
    monkeypatch.setattr(wiki_engine, "RAW_DIR", raw)
    raw.mkdir(exist_ok=True)
    (raw / "manifest.json").write_text("{}")
    (raw / "file.txt").write_bytes(b"x")
    s = wiki_engine.stats()
    assert s["raw_files"] == 1
