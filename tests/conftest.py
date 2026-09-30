"""Shared fixtures for LocalWiki test suite. The suite is offline: any socket connect raises."""

import socket
import sys
from pathlib import Path
from unittest.mock import MagicMock

import bcrypt
import dotenv
import pytest

# The suite must not depend on the developer's .env (CI has none): every src module
# calls load_dotenv() at import, so disable it before any of them is imported.
dotenv.load_dotenv = lambda *_a, **_k: False

# Ensure src/ is on sys.path so bare module imports work
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import auth
import db_context
import gpu_widget
import ollama_client
import ollama_server
import run_memory
import wiki_engine


@pytest.fixture(autouse=True)
def _block_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("tests must stay offline; use synthetic fixtures")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket.socket, "connect_ex", refuse)


@pytest.fixture(autouse=True)
def _fast_bcrypt(monkeypatch: pytest.MonkeyPatch) -> None:
    """Hash test passwords at bcrypt's minimum cost; the default makes every seed slow."""
    gensalt = bcrypt.gensalt
    monkeypatch.setattr(bcrypt, "gensalt", lambda *_a, **_k: gensalt(rounds=4))


@pytest.fixture(autouse=True)
def _unsealed_clearance():
    """Every test starts unsealed (level 0 of every DB), so a grant never leaks into the next."""
    token = db_context._clearance.set(None)
    principal = db_context._principal.set(None)
    yield
    db_context._principal.reset(principal)
    db_context._clearance.reset(token)


@pytest.fixture(autouse=True)
def _no_run_memory():
    """No agent run leaks its visited-set into the next test (tools would answer
    "Already read" instead of reading, and a leak probe could pass vacuously)."""
    token = run_memory._current.set(None)
    yield
    run_memory._current.reset(token)


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


GUI_USERS = {
    "reader": ("pw", [db_context.DEFAULT_DB], []),
    "nodb": ("pw", [], []),
}


@pytest.fixture
def gui_env(tmp_path, monkeypatch):
    """Isolated data root, seeded users and a stubbed daemon/GPU for the NiceGUI tests.

    Users: the seeded admin (`auth.DEFAULT_USER` / `auth.DEFAULT_PASSWORD`, maintains the
    default DB), `reader` (no maintainer rights) and `nodb` (no databases); all with password
    `pw` except the admin.
    """
    monkeypatch.setattr(db_context, "DATA_ROOT", tmp_path)
    monkeypatch.setenv("INGEST_QA", "0")
    monkeypatch.setenv("INGEST_DESCRIPTION", "0")
    status = {"host": "http://127.0.0.1:1", "pinned": True, "gpu": 1, "managed": True}
    monkeypatch.setattr(ollama_server, "status", lambda: {**status, "reason": "test"})
    idle = {"gpus": [], "elapsed": None, "is_running": False, "model": None}
    monkeypatch.setattr(gpu_widget, "gpu_payload", lambda: idle)
    auth.ensure_seeded()
    for name, (pw, dbs, maintains) in GUI_USERS.items():
        auth.add_user(name, pw, dbs, maintains=maintains)
    db_context.set_active_db(db_context.DEFAULT_DB)
    wiki_engine.init_wiki()
    return tmp_path
