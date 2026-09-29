"""Security audit log: who did what to which shard, append-only, never content."""

import pytest

import audit
import db_context


@pytest.fixture
def root(tmp_path, monkeypatch):
    monkeypatch.setattr(db_context, "DATA_ROOT", tmp_path)
    db_context.set_active_db("KI")
    return tmp_path


def test_records_are_appended_and_read_newest_first(root):
    audit.record("classified", "m", target="a.pdf", shard="KI@strict")
    audit.record("classified", "m", target="b.pdf", shard="KI")
    rows = audit.recent()
    assert [r["target"] for r in rows] == ["b.pdf", "a.pdf"]
    assert {"at", "action", "user"} <= rows[0].keys()
    assert (root / "security_audit.jsonl").read_text().count("\n") == 2


def test_recent_limits_and_tolerates_a_missing_or_broken_log(root):
    assert audit.recent() == []
    (root / "security_audit.jsonl").write_text('{"action": "x"}\nnot json\n')
    audit.record("y", "u")
    assert [r["action"] for r in audit.recent(limit=1)] == ["y"]


def test_a_denied_shard_in_a_user_session_is_audited(root):
    db_context.seal_clearance({"KI": 0}, user="bob")
    with pytest.raises(db_context.AccessDenied):
        db_context.require("KI@strict")
    [row] = audit.recent()
    assert (row["action"], row["user"], row["target"]) == ("access_denied", "bob", "KI@strict")


def test_a_denied_traversal_in_a_user_session_is_audited(root):
    db_context.seal_clearance({"KI": 0}, user="bob")
    with pytest.raises(db_context.AccessDenied):
        db_context.confine(root / "KI" / "wiki", "../../Other/wiki/x.md")
    assert audit.recent()[0]["target"] == "../../Other/wiki/x.md"


def test_denials_outside_a_user_session_are_not_audited(root):
    with pytest.raises(db_context.AccessDenied):
        db_context.require("KI@strict")
    assert audit.recent() == []
    assert not (root / "security_audit.jsonl").exists()
