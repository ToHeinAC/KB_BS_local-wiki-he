"""Inside a higher-level shard, DB-wide concepts still refer to the base DB."""

import json

import frontmatter
import pytest

import auth
import calibrate
import db_context
import ontology_store
import wiki_engine


@pytest.fixture
def strict_shard(tmp_path, monkeypatch):
    monkeypatch.setattr(db_context, "DATA_ROOT", tmp_path)
    monkeypatch.delenv("ABSTAIN_TAU_DEFAULT", raising=False)
    db_context.set_active_db("KI")
    with db_context.clearance({"KI": 2}):
        db_context.ensure_shard("KI")
        root = db_context.ensure_shard("KI@strict")
        with db_context.using_db("KI@strict"):
            yield root


def test_a_db_maintainer_maintains_every_level_of_it(strict_shard):
    auth.add_user("m", "pw", ["KI"], maintains=["KI"])
    assert wiki_engine.propose_page_classes("m") == 0  # no PermissionError


def test_the_ontology_binding_comes_from_the_base_db(strict_shard, tmp_path):
    assert ontology_store.binding_path() == tmp_path / "KI" / "ontology.yaml"
    assert ontology_store.store_dir() == strict_shard / "ontology"


def test_okf_tags_name_the_base_db_not_the_shard(strict_shard):
    page = "---\ntitle: T\ntype: concept\nsources: [a.md]\n---\nBody\n"
    tags = str(frontmatter.loads(wiki_engine._okf_apply(page)).metadata["tags"])
    assert "'ki'" in tags
    assert "strict" not in tags


def test_calibration_is_read_from_the_shard(strict_shard):
    (strict_shard / "index" / "calibration.json").write_text(json.dumps({"tau": 0.42}))
    assert calibrate.threshold() == pytest.approx(0.42)
    assert calibrate.threshold("KI") is None


def test_calibration_of_an_unreachable_shard_is_uncalibrated(strict_shard):
    (strict_shard / "index" / "calibration.json").write_text(json.dumps({"tau": 0.42}))
    with db_context.clearance({"KI": 0}):
        assert calibrate.threshold("KI@strict") is None
