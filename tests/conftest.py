"""Shared fixtures for LocalWiki test suite."""

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# Ensure src/ is on sys.path so bare module imports work
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import db_context
import ollama_client
import wiki_engine


def _patch_data_root(monkeypatch, tmp_path: Path, db_name: str = "test") -> Path:
    """Point db_context at an isolated data root + active DB. Returns the DB root."""
    monkeypatch.setattr(db_context, "DATA_ROOT", tmp_path)
    db_context.set_active_db(db_name)
    root = tmp_path / db_name
    for sub in ("raw", "chunks", "index", "wiki"):
        (root / sub).mkdir(parents=True, exist_ok=True)
    return root


@pytest.fixture()
def raw_dir(tmp_path, monkeypatch):
    """Isolated raw directory."""
    root = _patch_data_root(monkeypatch, tmp_path)
    return root / "raw"


@pytest.fixture()
def wiki_dir(tmp_path, monkeypatch):
    """Isolated wiki + raw + chunks + index dirs; inits wiki state."""
    root = _patch_data_root(monkeypatch, tmp_path)
    monkeypatch.setenv("INGEST_QA", "0")
    monkeypatch.setenv("INGEST_DESCRIPTION", "0")  # no LLM overview pass during ingest tests
    wiki_engine.init_wiki()
    return root / "wiki"


@pytest.fixture()
def mock_ollama(monkeypatch):
    """Patches ollama_client._client; returns the mock instance."""
    mock_instance = MagicMock()
    monkeypatch.setattr(ollama_client, "_client", lambda: mock_instance)
    return mock_instance
