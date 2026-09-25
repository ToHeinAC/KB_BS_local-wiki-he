"""Tests for auth.py — local user store and the per-DB maintainer layer."""

import json

import pytest

import auth
import db_context


@pytest.fixture
def users_root(tmp_path, monkeypatch):
    """Point the user store at an isolated data root."""
    monkeypatch.setattr(db_context, "DATA_ROOT", tmp_path)
    return tmp_path


def _read(users_root):
    return json.loads((users_root / "users.json").read_text())


# --- maintainer rights ---


def test_seeded_admin_maintains_default_db(users_root):
    auth.ensure_seeded()
    assert auth.is_maintainer(auth.DEFAULT_USER, db_context.DEFAULT_DB) is True


def test_non_maintainer_with_access_is_not_maintainer(users_root):
    auth.add_user("reader", "pw", ["DB1"])
    assert "DB1" in auth.user_dbs("reader")
    assert auth.is_maintainer("reader", "DB1") is False


def test_admin_is_not_implicit_maintainer(users_root):
    auth.add_user("adm", "pw", ["DB1"], is_admin=True)
    # Admin without explicit maintains assignment cannot maintain.
    assert auth.is_maintainer("adm", "DB1") is False


def test_add_user_with_maintains(users_root):
    auth.add_user("m", "pw", ["DB1", "DB2"], maintains=["DB1"])
    assert auth.is_maintainer("m", "DB1") is True
    assert auth.is_maintainer("m", "DB2") is False


def test_set_user_maintains_persists(users_root):
    auth.add_user("m", "pw", ["DB1"])
    auth.set_user_maintains("m", ["DB1"])
    assert auth.user_maintains("m") == ["DB1"]


def test_set_user_maintains_unknown_user_raises(users_root):
    with pytest.raises(ValueError, match="Unknown user"):
        auth.set_user_maintains("ghost", ["DB1"])


# --- grant_maintainer ---


def test_grant_maintainer_adds_to_both_lists(users_root):
    auth.add_user("u", "pw", [])
    auth.grant_maintainer("u", "DB1")
    assert "DB1" in auth.user_dbs("u")
    assert "DB1" in auth.user_maintains("u")


def test_grant_maintainer_is_idempotent(users_root):
    auth.add_user("u", "pw", ["DB1"], maintains=["DB1"])
    auth.grant_maintainer("u", "DB1")
    assert auth.user_dbs("u") == ["DB1"]
    assert auth.user_maintains("u") == ["DB1"]


def test_grant_maintainer_unknown_user_raises(users_root):
    with pytest.raises(ValueError, match="Unknown user"):
        auth.grant_maintainer("ghost", "DB1")


# --- backfill_maintainers ---


def test_backfill_grants_admins_their_dbs(users_root):
    # Simulate a pre-maintainer install: no `maintains` key.
    (users_root / "users.json").write_text(
        json.dumps(
            {
                "users": {
                    "adm": {"pw_hash": "x", "dbs": ["DB1", "DB2"], "is_admin": True},
                    "reader": {"pw_hash": "x", "dbs": ["DB1"], "is_admin": False},
                }
            }
        )
    )
    auth.backfill_maintainers()
    data = _read(users_root)
    assert data["users"]["adm"]["maintains"] == ["DB1", "DB2"]
    assert data["users"]["reader"]["maintains"] == []


def test_backfill_is_idempotent_and_skips_existing(users_root):
    auth.add_user("m", "pw", ["DB1"], maintains=["DB1"])
    auth.backfill_maintainers()
    # An explicit maintains list must not be overwritten.
    assert auth.user_maintains("m") == ["DB1"]


def test_list_users_includes_maintains(users_root):
    auth.add_user("m", "pw", ["DB1"], maintains=["DB1"])
    entry = next(u for u in auth.list_users() if u["username"] == "m")
    assert entry["maintains"] == ["DB1"]


def test_corrupt_user_store_reads_as_empty(users_root):
    auth._path().write_text("{not json")
    assert auth.list_users() == []


def test_verify_rejects_unknown_user_and_broken_hash(users_root):
    auth.add_user("u", "pw", ["DB1"])
    assert auth.verify("u", "pw") is True
    assert auth.verify("ghost", "pw") is False
    data = auth._load()
    data["users"]["u"]["pw_hash"] = "not-a-bcrypt-hash"
    auth._save(data)
    assert auth.verify("u", "pw") is False


@pytest.mark.parametrize(("user", "pw", "match"), [("", "pw", "required"), ("u", "", "required")])
def test_add_user_requires_credentials(users_root, user, pw, match):
    with pytest.raises(ValueError, match=match):
        auth.add_user(user, pw, [])


def test_add_user_rejects_duplicates(users_root):
    auth.add_user("u", "pw", [])
    with pytest.raises(ValueError, match="already exists"):
        auth.add_user("u", "pw2", [])


def test_delete_user(users_root):
    auth.add_user("u", "pw", [])
    assert auth.delete_user("u") is True
    assert auth.delete_user("u") is False


def test_change_password(users_root):
    auth.add_user("u", "old", [])
    auth.change_password("u", "new")
    assert auth.verify("u", "new") is True
    with pytest.raises(ValueError, match="Unknown user"):
        auth.change_password("ghost", "x")


def test_set_user_dbs_unknown_user(users_root):
    with pytest.raises(ValueError, match="Unknown user"):
        auth.set_user_dbs("ghost", ["DB1"])
