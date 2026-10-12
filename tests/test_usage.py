"""Usage log: one JSON line per event in data/usage.jsonl, never content."""

import json
from datetime import UTC, datetime

import pytest

import db_context
import usage

NOW = datetime(2026, 10, 12, 9, 30, 5, tzinfo=UTC)


@pytest.fixture
def root(tmp_path, monkeypatch):
    monkeypatch.setattr(db_context, "DATA_ROOT", tmp_path)
    return tmp_path


def test_events_are_appended_as_one_json_line_each(root):
    usage.log_event("login_ok", "Jürgen", now=lambda: NOW, session="s1")
    usage.log_event("chat", "Jürgen", now=lambda: NOW, mode="Fast", duration_s=1.5)
    lines = (root / "usage.jsonl").read_text(encoding="utf-8").splitlines()
    assert json.loads(lines[0]) == {
        "ts": "2026-10-12T09:30:05+00:00",
        "event": "login_ok",
        "user": "Jürgen",
        "session": "s1",
    }
    assert "Jürgen" in lines[1]  # readable, not \u-escaped
    assert [e["event"] for e in usage.read_events()] == ["login_ok", "chat"]


def test_a_missing_or_broken_log_is_read_without_failing(root):
    assert usage.read_events() == []
    usage.log_event("login_ok", "a")
    with (root / "usage.jsonl").open("a") as f:
        f.write('{"ts": "kaputt\n')
    usage.log_event("logout", "a")
    assert [e["event"] for e in usage.read_events()] == ["login_ok", "logout"]


def test_a_write_error_never_reaches_the_caller(root):
    (root / "usage.jsonl").mkdir()  # a directory where the file should be
    usage.log_event("login_ok", "x")  # must not raise
