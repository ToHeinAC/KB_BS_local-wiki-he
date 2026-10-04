"""Startup heal of missing search indexes (scripts/heal_indexes.py, run by scripts/run_app.py)."""

import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

import chunker
import db_context
import wiki_engine

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "heal_indexes.py"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("heal_indexes", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["heal_indexes"] = module
    spec.loader.exec_module(module)
    return module


def _content_without_index(shard: str) -> None:
    db = shard.split("@")[0]
    with db_context.clearance({db: 2}):
        db_context.ensure_shard(shard)
        with db_context.using_db(shard):
            chunker.write_chunks("a.md", chunker.split("## A\nplutonium criticality data\n"))


@pytest.fixture
def data(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(db_context, "DATA_ROOT", tmp_path)
    return tmp_path


def test_heal_rebuilds_every_shard_with_content_but_no_index(data: Path) -> None:
    for shard in ("test", "test@confidential", "other"):
        _content_without_index(shard)
    db_context.create_db("empty")
    with db_context.clearance({"other": 0}), db_context.using_db("other"):
        wiki_engine.rebuild_lex_index()  # already healthy: left alone
    heal = _load().heal
    assert heal() == ["test", "test@confidential"]
    assert heal() == []


def test_heal_keeps_going_past_a_failing_shard(data: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    for shard in ("other", "test"):
        _content_without_index(shard)

    def _build() -> dict[str, Any]:
        if db_context.base_db() == "other":
            raise OSError("disk full")
        return {"chunks": 1}

    monkeypatch.setattr(wiki_engine, "rebuild_lex_index", _build)
    assert _load().heal() == ["test"]
