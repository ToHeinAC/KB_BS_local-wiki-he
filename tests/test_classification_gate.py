"""The access gate in db_context: no path into a shard above the caller's clearance."""

import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

import db_context


@pytest.fixture
def root(tmp_path, monkeypatch):
    monkeypatch.setattr(db_context, "DATA_ROOT", tmp_path)
    db_context.set_active_db("KI")
    db_context.set_search_scope([])
    yield tmp_path
    db_context.set_search_scope([])


def test_shards_nest_under_their_db(root):
    assert db_context.shard_path("KI") == root / "KI"
    assert db_context.shard_path("KI@strict") == root / "KI" / "_levels" / "strict"


def test_unsealed_default_grants_only_the_normal_level(root):
    assert db_context.data_root() == root / "KI"
    for shard in ("KI@confidential", "KI@strict", "Other@strict"):
        with pytest.raises(db_context.AccessDenied):
            db_context.require(shard)


@pytest.mark.parametrize(
    "enter",
    [
        lambda s: db_context.set_active_db(s),
        lambda s: db_context.using_db(s).__enter__(),
        lambda s: db_context.set_search_scope(["KI", s]),
    ],
)
def test_binding_a_shard_above_clearance_raises(root, enter):
    with db_context.clearance({"KI": 1}), pytest.raises(db_context.AccessDenied):
        enter("KI@strict")
    assert db_context.get_active_db() == "KI"


def test_malformed_shard_ids_are_denied_not_crashing(root):
    with pytest.raises(db_context.AccessDenied):
        db_context.require("KI@secret")


def test_clearance_is_hierarchical(root):
    with db_context.clearance({"KI": 2}), db_context.using_db("KI@confidential"):
        assert db_context.data_root() == root / "KI" / "_levels" / "confidential"
        assert db_context.base_db() == "KI"
        assert db_context.level() == 1


def test_sealed_clearance_also_enforces_the_db_allowlist(root):
    with db_context.clearance({"KI": 2}), pytest.raises(db_context.AccessDenied):
        db_context.require("Investing")


def test_path_getters_re_check_after_clearance_shrinks(root):
    """A shard bound earlier cannot be read once the grant is gone."""
    with db_context.clearance({"KI": 2}):
        db_context.set_active_db("KI@strict")
    with pytest.raises(db_context.AccessDenied):
        db_context.wiki_dir()
    db_context.set_active_db("KI")


def test_reachable_shards_lists_existing_levels_up_to_clearance(root):
    for lvl in ("confidential", "strict"):
        (root / "KI" / "_levels" / lvl / "raw").mkdir(parents=True)
    with db_context.clearance({"KI": 1}):
        assert db_context.reachable_shards("KI") == ("KI", "KI@confidential")
        assert db_context.reachable_shards("Investing") == ()
    with db_context.clearance({"KI": 2}):
        assert db_context.reachable_shards("KI") == ("KI", "KI@confidential", "KI@strict")


def test_write_target_is_the_high_water_mark_of_the_scope(root):
    with db_context.clearance({"KI": 2, "Inv": 2}):
        assert db_context.write_target("KI", ["KI"]) == "KI"
        assert db_context.write_target("KI", ["KI", "Inv@strict"]) == "KI@strict"
    with db_context.clearance({"KI": 0, "Inv": 2}), pytest.raises(db_context.AccessDenied):
        db_context.write_target("KI", ["Inv@strict"])


def test_ensure_shard_creates_the_store(root):
    with db_context.clearance({"KI": 1}):
        path = db_context.ensure_shard("KI@confidential")
    assert {p.name for p in path.iterdir()} == {"raw", "chunks", "index", "wiki"}


def test_ontology_binding_is_shared_by_every_level(root):
    with db_context.clearance({"KI": 2}), db_context.using_db("KI@strict"):
        assert db_context.ontology_binding_path() == root / "KI" / "ontology.yaml"


def test_an_unpropagated_thread_falls_back_to_normal(root):
    seen: list[BaseException | None] = []

    def probe() -> None:
        try:
            db_context.require("KI@strict")
            seen.append(None)
        except db_context.AccessDenied as exc:
            seen.append(exc)

    with db_context.clearance({"KI": 2}):
        t = threading.Thread(target=probe)
        t.start()
        t.join()
    assert isinstance(seen[0], db_context.AccessDenied)


def test_bind_context_carries_clearance_db_and_scope_into_workers(root):
    (root / "KI" / "_levels" / "strict" / "raw").mkdir(parents=True)

    def probe(_: int) -> tuple[str, tuple[str, ...], str]:
        return db_context.get_active_db(), db_context.search_scope(), str(db_context.data_root())

    with db_context.clearance({"KI": 2}), db_context.using_db("KI@strict"):
        db_context.set_search_scope(["KI", "KI@strict"])
        with ThreadPoolExecutor(max_workers=1) as ex:
            got = list(ex.map(db_context.bind_context(probe), [0]))
    assert got == [("KI@strict", ("KI", "KI@strict"), str(root / "KI/_levels/strict"))]
