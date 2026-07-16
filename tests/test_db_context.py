"""Tests for db_context.py — search scope + DB-qualified refs."""

import pytest

import db_context


@pytest.fixture(autouse=True)
def _reset_scope():
    """Keep ContextVar state from leaking between tests."""
    db_context.set_active_db("Alpha")
    db_context.set_search_scope([])
    yield
    db_context.set_search_scope([])


# --- using_db -------------------------------------------------------------

def test_using_db_binds_and_restores():
    with db_context.using_db("Beta"):
        assert db_context.get_active_db() == "Beta"
    assert db_context.get_active_db() == "Alpha"


def test_using_db_restores_on_exception():
    with pytest.raises(ValueError):
        with db_context.using_db("Beta"):
            raise ValueError("boom")
    assert db_context.get_active_db() == "Alpha"


def test_using_db_nests():
    with db_context.using_db("Beta"):
        with db_context.using_db("Gamma"):
            assert db_context.get_active_db() == "Gamma"
        assert db_context.get_active_db() == "Beta"


def test_using_db_switches_paths(tmp_path, monkeypatch):
    monkeypatch.setattr(db_context, "DATA_ROOT", tmp_path)
    with db_context.using_db("Beta"):
        assert db_context.wiki_dir() == tmp_path / "Beta" / "wiki"
    assert db_context.raw_dir() == tmp_path / "Alpha" / "raw"


# --- search_scope ---------------------------------------------------------

def test_scope_defaults_to_active_db():
    assert db_context.search_scope() == ("Alpha",)
    assert not db_context.is_multi_scope()


def test_scope_follows_active_db_when_unset():
    db_context.set_active_db("Beta")
    assert db_context.search_scope() == ("Beta",)


def test_set_scope_dedups_and_drops_empties():
    db_context.set_search_scope(["Alpha", "Beta", "Alpha", "", None])
    assert db_context.search_scope() == ("Alpha", "Beta")


def test_multi_scope_detection():
    db_context.set_search_scope(["Alpha", "Beta"])
    assert db_context.is_multi_scope()


def test_empty_scope_resets_to_active():
    db_context.set_search_scope(["Alpha", "Beta"])
    db_context.set_search_scope([])
    assert db_context.search_scope() == ("Alpha",)
    assert not db_context.is_multi_scope()


# --- qualify --------------------------------------------------------------

def test_qualify_noop_for_single_db_scope():
    assert db_context.qualify("index.md") == "index.md"


def test_qualify_prefixes_under_multi_scope():
    db_context.set_search_scope(["Alpha", "Beta"])
    assert db_context.qualify("index.md", "Beta") == "Beta::index.md"


def test_qualify_defaults_to_active_db():
    db_context.set_search_scope(["Alpha", "Beta"])
    with db_context.using_db("Beta"):
        assert db_context.qualify("index.md") == "Beta::index.md"


def test_qualify_passes_empty_through():
    db_context.set_search_scope(["Alpha", "Beta"])
    assert db_context.qualify("") == ""


# --- split_ref ------------------------------------------------------------

def test_split_ref_unqualified_resolves_to_active():
    assert db_context.split_ref("index.md") == ("Alpha", "index.md")


def test_split_ref_splits_known_db():
    db_context.set_search_scope(["Alpha", "Beta"])
    assert db_context.split_ref("Beta::index.md") == ("Beta", "index.md")


def test_split_ref_ignores_db_outside_scope():
    """An invented/stale prefix must not escape the scope."""
    db_context.set_search_scope(["Alpha", "Beta"])
    assert db_context.split_ref("Gamma::index.md") == ("Alpha", "Gamma::index.md")


def test_split_ref_roundtrips_qualify():
    db_context.set_search_scope(["Alpha", "Beta"])
    ref = db_context.qualify("insights/foo.md", "Beta")
    assert db_context.split_ref(ref) == ("Beta", "insights/foo.md")


def test_split_ref_preserves_section_suffix():
    db_context.set_search_scope(["Alpha", "Beta"])
    assert db_context.split_ref("Beta::StrlSchG.md §62") == ("Beta", "StrlSchG.md §62")


def test_split_ref_tolerates_whitespace():
    db_context.set_search_scope(["Alpha", "Beta"])
    assert db_context.split_ref("  Beta :: index.md ") == ("Beta", "index.md")


def test_split_ref_handles_empty_tail():
    db_context.set_search_scope(["Alpha", "Beta"])
    assert db_context.split_ref("Beta::") == ("Alpha", "Beta::")
