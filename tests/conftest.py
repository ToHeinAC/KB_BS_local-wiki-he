"""Shared fixtures for LocalWiki test suite. The suite is offline: any socket connect raises."""

import socket
import sys
from pathlib import Path
from unittest.mock import MagicMock

import dotenv
import pytest

# The suite must not depend on the developer's .env (CI has none): every src module
# calls load_dotenv() at import, so disable it before any of them is imported.
dotenv.load_dotenv = lambda *_a, **_k: False

# Ensure src/ is on sys.path so bare module imports work
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import db_context
import ollama_client
import wiki_engine


@pytest.fixture(autouse=True)
def _block_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("tests must stay offline; use synthetic fixtures")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket.socket, "connect_ex", refuse)


def _patch_data_root(monkeypatch, tmp_path: Path, db_name: str = "test") -> Path:
    """Point db_context at an isolated data root + active DB. Returns the DB root."""
    monkeypatch.setattr(db_context, "DATA_ROOT", tmp_path)
    db_context.set_active_db(db_name)
    root = tmp_path / db_name
    for sub in ("raw", "chunks", "index", "wiki"):
        (root / sub).mkdir(parents=True, exist_ok=True)
    return root


@pytest.fixture
def raw_dir(tmp_path, monkeypatch):
    """Isolated raw directory."""
    root = _patch_data_root(monkeypatch, tmp_path)
    return root / "raw"


@pytest.fixture
def wiki_dir(tmp_path, monkeypatch):
    """Isolated wiki + raw + chunks + index dirs; inits wiki state."""
    root = _patch_data_root(monkeypatch, tmp_path)
    monkeypatch.setenv("INGEST_QA", "0")
    monkeypatch.setenv("INGEST_DESCRIPTION", "0")  # no LLM overview pass during ingest tests
    wiki_engine.init_wiki()
    return root / "wiki"


@pytest.fixture
def mock_ollama(monkeypatch):
    """Patches ollama_client._client; returns the mock instance."""
    mock_instance = MagicMock()
    monkeypatch.setattr(ollama_client, "_client", lambda: mock_instance)
    return mock_instance
