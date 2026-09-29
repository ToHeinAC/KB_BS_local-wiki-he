"""Moving a source between levels; moving it up purges every trace below (PRD M7)."""

from pathlib import Path
from typing import Any

import frontmatter
import pytest

import auth
import chunker
import db_context
import dedup
import lex_index
import ollama_client
import ontology
import ontology_store
import wiki_engine

DB = "KI"
STRICT = f"{DB}@strict"
CANARY = "okapiflint4402"
SECRET_RAW = f"# Bunker plan\n\nThe bunker reference is {CANARY}.\n"
OTHER_RAW = "# Shielding\n\nLead shielding attenuates gamma radiation.\n"


def _page(rel: str, sources: list[str], body: str, **meta: Any) -> None:
    post = frontmatter.Post(body, title=Path(rel).stem, type=meta.pop("type", "concept"))
    post.metadata.update(sources=sources, **meta)
    path = db_context.wiki_dir() / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(frontmatter.dumps(post) + "\n")


@pytest.fixture
def normal_db(tmp_path, monkeypatch):
    """A normal level where `secret.md` was merged with `other.md` into shared pages."""
    monkeypatch.setattr(db_context, "DATA_ROOT", tmp_path)
    monkeypatch.setenv("INGEST_QA", "0")
    monkeypatch.setenv("INGEST_DESCRIPTION", "0")
    monkeypatch.setattr(ollama_client, "generate", lambda *_a, **_k: "Overview.")
    db_context.set_active_db(DB)
    db_context.ensure_shard(DB)
    wiki_engine.init_wiki()
    auth.add_user("m", "pw", [DB], maintains=[DB], clearance={DB: "strict"})
    for name, text in (("secret.md", SECRET_RAW), ("other.md", OTHER_RAW)):
        dedup.register_file(text.encode(), name)
        chunker.write_chunks(name, chunker.split(text))
    _page("summary-secret.md", ["secret.md"], SECRET_RAW, type="source-summary")
    _page("summary-other.md", ["other.md"], OTHER_RAW, type="source-summary")
    _page("shared.md", ["secret.md §1", "other.md"], f"Lead shielding.\nBunker {CANARY}.")
    _page("linker.md", ["other.md"], "See shared.", related=["shared.md"])
    _page(
        "insights/insight-a.md",
        ["chat"],
        f"About {CANARY}.",
        type="comparison",
        derived_from=["shared.md"],
    )
    _page(
        "comparisons/report-x.md", ["src:secret.md", "https://ex.org"], f"R {CANARY}", type="report"
    )
    ontology_store.binding_path().write_text("modules: [core]\n")
    ontology_store.append_rows(
        [ontology.assertion("src:secret.md", "work", f"Plan {CANARY}", by="user", user="m")]
    )
    ontology_store.record_change("ingest")
    wiki_engine._append_log("Ingest", f"Source: secret.md — {CANARY}")
    (db_context.wiki_dir() / "DESCRIPTION.md").write_text(f"Overview {CANARY}\n")
    wiki_engine._rebuild_index()
    lex_index.build()
    yield tmp_path
    db_context.set_active_db(DB)


@pytest.fixture
def reingested(monkeypatch) -> list[tuple[str, str]]:
    """Stand-in for the LLM ingest: records (shard, source) and writes a plain summary."""
    calls: list[tuple[str, str]] = []

    def fake(name: str, _meta: dict[str, str]) -> dict[str, Any]:
        calls.append((db_context.get_active_db(), name))
        text = (wiki_engine.read_raw_source(name) or b"").decode()
        _page(f"summary-{Path(name).stem}.md", [name], text, type="source-summary")
        return {"created": [], "updated": []}

    monkeypatch.setattr(wiki_engine, "_ingest_raw", fake)
    return calls


def _traces(root: Path, *needles: str) -> list[str]:
    """Files of the normal level (not the nested higher levels) containing a needle."""
    hits: list[str] = []
    for path in (root / DB).rglob("*"):
        if "_levels" in path.parts or not path.is_file():
            continue
        data = path.read_bytes()
        hits += [f"{path.relative_to(root)}: {n}" for n in needles if n.encode() in data]
    return hits


def _move(target: str = STRICT) -> dict[str, Any]:
    with db_context.clearance({DB: 2}):
        return wiki_engine.move_source("secret.md", target, "m")


def test_the_fixture_really_holds_the_traces(normal_db):
    assert len(_traces(normal_db, CANARY)) >= 6


def test_moving_up_leaves_no_trace_in_the_lower_level(normal_db, reingested):
    _move()
    assert _traces(normal_db, CANARY, "secret.md") == []


def test_the_moved_source_is_ingested_into_its_new_level(normal_db, reingested):
    _move()
    assert (STRICT, "secret.md") in reingested
    with db_context.clearance({DB: 2}), db_context.using_db(STRICT):
        assert dedup.list_sources() == ["secret.md"]
        assert dedup.is_duplicate(SECRET_RAW.encode())
        assert ontology_store.source_facts("secret.md")["work"] == f"Plan {CANARY}"


def test_pages_it_shared_are_rebuilt_from_their_other_sources(normal_db, reingested):
    report = _move()
    assert (DB, "other.md") in reingested
    assert "shared.md" in report["rebuilt"]
    assert "other.md" in dedup.list_sources()


def test_insights_without_provenance_are_listed_for_review(normal_db, reingested):
    _page("insights/insight-old.md", ["chat"], "An older filed answer.", created="2999-01-01")
    report = _move()
    assert report["review"] == ["insights/insight-old.md"]


def test_moving_down_is_a_plain_declassification(normal_db, reingested, monkeypatch):
    purged: list[str] = []
    monkeypatch.setattr(wiki_engine, "purge_upgraded", lambda name: purged.append(name))
    with db_context.clearance({DB: 2}):
        db_context.ensure_shard(STRICT)
        with db_context.using_db(STRICT):
            wiki_engine.init_wiki()
            dedup.register_file(b"# Down", "down.md")
            wiki_engine.move_source("down.md", DB, "m")
    assert (DB, "down.md") in reingested
    assert purged == []


def test_moving_needs_maintainer_rights(normal_db, reingested):
    auth.add_user("r", "pw", [DB], clearance={DB: "strict"})
    with db_context.clearance({DB: 2}), pytest.raises(PermissionError):
        wiki_engine.move_source("secret.md", STRICT, "r")


def test_moving_needs_clearance_for_the_target(normal_db, reingested):
    with db_context.clearance({DB: 1}), pytest.raises(db_context.AccessDenied):
        wiki_engine.move_source("secret.md", STRICT, "m")
    assert "secret.md" in dedup.list_sources()


def test_the_shared_ontology_schema_is_only_changed_from_the_normal_level(normal_db):
    with db_context.clearance({DB: 2}):
        db_context.ensure_shard(STRICT)
        with db_context.using_db(STRICT), pytest.raises(PermissionError, match="normal level"):
            ontology_store._write_binding({"modules": ["core"]})
