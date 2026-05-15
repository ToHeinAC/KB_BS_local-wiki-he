"""Shared fixtures for LocalWiki test suite."""

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# Ensure src/ is on sys.path so bare module imports work
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import chunker
import dedup
import extractor
import lex_index
import qa_gen
import wiki_engine
import ollama_client


@pytest.fixture()
def raw_dir(tmp_path, monkeypatch):
    """Isolated raw directory; patches dedup module attrs."""
    raw = tmp_path / "raw"
    raw.mkdir()
    monkeypatch.setattr(dedup, "RAW_DIR", raw)
    monkeypatch.setattr(dedup, "MANIFEST", raw / "manifest.json")
    return raw


@pytest.fixture()
def wiki_dir(tmp_path, monkeypatch):
    """Isolated wiki + raw directories; inits wiki state."""
    wiki = tmp_path / "wiki"
    raw = tmp_path / "raw"
    wiki.mkdir()
    raw.mkdir()
    monkeypatch.setattr(wiki_engine, "WIKI_DIR", wiki)
    monkeypatch.setattr(wiki_engine, "RAW_DIR", raw)
    monkeypatch.setattr(wiki_engine, "_INDEX", wiki / "index.md")
    monkeypatch.setattr(wiki_engine, "_LOG", wiki / "log.md")
    # Isolate chunker + lexical index writes from real data/ dirs.
    monkeypatch.setattr(chunker, "CHUNKS_DIR", tmp_path / "chunks")
    monkeypatch.setattr(lex_index, "INDEX_DIR", tmp_path / "index")
    monkeypatch.setattr(lex_index, "POSTINGS_PATH", tmp_path / "index" / "postings.json")
    monkeypatch.setattr(lex_index, "STATS_PATH", tmp_path / "index" / "stats.json")
    monkeypatch.setattr(lex_index, "TRIGRAMS_PATH", tmp_path / "index" / "trigrams.json")
    monkeypatch.setattr(extractor, "INDEX_DIR", tmp_path / "index")
    monkeypatch.setattr(extractor, "ALIASES_PATH", tmp_path / "index" / "aliases.json")
    monkeypatch.setattr(extractor, "ACRONYMS_PATH", tmp_path / "index" / "acronyms.json")
    monkeypatch.setattr(extractor, "TERMS_PATH", tmp_path / "index" / "terms.json")
    monkeypatch.setattr(extractor, "FACTS_PATH", tmp_path / "index" / "facts.jsonl")
    monkeypatch.setattr(qa_gen, "INDEX_DIR", tmp_path / "index")
    monkeypatch.setattr(qa_gen, "QA_PATH", tmp_path / "index" / "qa.jsonl")
    # Extractor + qa-gen are gated; disable both in the shared wiki fixture so
    # existing tests' Ollama mocks aren't affected.
    monkeypatch.setenv("INGEST_EXTRACT", "0")
    monkeypatch.setenv("INGEST_QA", "0")
    wiki_engine.init_wiki()
    return wiki


@pytest.fixture()
def mock_ollama(monkeypatch):
    """Patches ollama_client._client; returns the mock instance."""
    mock_instance = MagicMock()
    monkeypatch.setattr(ollama_client, "_client", lambda: mock_instance)
    return mock_instance
