"""Characterization tests for wiki_engine.delete_source — the cascade across every store."""

import frontmatter
import pytest

import chunker
import db_context
import dedup
import ontology
import ontology_store
import wiki_engine


def _page(path, sources, related=()):
    post = frontmatter.Post(f"# {path.stem}\n\nBody.", title=path.stem, type="concept")
    post.metadata["sources"] = list(sources)
    post.metadata["related"] = list(related)
    post.metadata["updated"] = "2000-01-01"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(frontmatter.dumps(post))


def _meta(path):
    return frontmatter.load(str(path)).metadata


@pytest.fixture
def seeded(wiki_dir):
    dedup.register_file(b"gone bytes", "gone.md")
    dedup.register_file(b"kept bytes", "kept.md")
    chunks = db_context.chunks_dir() / f"{chunker.source_slug('gone.md')}.jsonl"
    chunks.write_text('{"chunk_id": "c1"}\n')
    _page(wiki_dir / "only-gone.md", ["gone.md §3"])
    _page(wiki_dir / "shared.md", ["gone.md", "kept.md"])
    _page(wiki_dir / "linker.md", ["kept.md"], related=["only-gone.md", "shared.md"])
    _page(wiki_dir / "insights" / "insight.md", ["gone.md"])
    return wiki_dir


def test_removes_raw_manifest_and_chunks(seeded):
    result = wiki_engine.delete_source("gone.md")
    assert result["raw"] is True
    assert result["manifest"] is True
    assert result["chunks"] is True
    assert not (db_context.raw_dir() / "gone.md").exists()
    assert dedup.list_sources() == ["kept.md"]


def test_deletes_pages_left_without_sources(seeded):
    result = wiki_engine.delete_source("gone.md")
    assert result["wiki_pages"] == ["insights/insight.md", "only-gone.md"]
    assert not (seeded / "only-gone.md").exists()
    assert not (seeded / "insights" / "insight.md").exists()


def test_drops_the_source_from_shared_pages(seeded):
    wiki_engine.delete_source("gone.md")
    meta = _meta(seeded / "shared.md")
    assert meta["sources"] == ["kept.md"]
    assert meta["updated"] != "2000-01-01"


def test_scrubs_related_links_to_deleted_pages(seeded):
    result = wiki_engine.delete_source("gone.md")
    assert result["related_scrubbed"] == 1
    assert _meta(seeded / "linker.md")["related"] == ["shared.md"]


def test_unknown_source_changes_nothing(seeded):
    result = wiki_engine.delete_source("never-registered.md")
    assert result == {
        "raw": False,
        "manifest": False,
        "chunks": False,
        "qa_rows": 0,
        "wiki_pages": [],
        "related_scrubbed": 0,
        "ontology_rows": 0,
    }
    assert _meta(seeded / "shared.md")["sources"] == ["gone.md", "kept.md"]


def test_deletion_is_logged(seeded):
    wiki_engine.delete_source("gone.md")
    assert "Source deleted" in (seeded / "log.md").read_text()


def test_retracts_the_sources_ontology_rows(seeded):
    ontology_store.append_rows(
        [
            ontology.assertion("src:gone.md", "class", "report", by="user"),
            ontology.assertion("src:kept.md", "class", "report", by="rule"),
        ]
    )
    result = wiki_engine.delete_source("gone.md")
    assert result["ontology_rows"] == 1
    facts = ontology.project(ontology_store.read_rows(), multi=set())
    assert set(facts) == {"src:kept.md"}
    assert "Ontology rows retracted: 1" in (seeded / "log.md").read_text()


def test_db_without_ontology_gets_no_ontology_files(seeded):
    wiki_engine.delete_source("gone.md")
    assert not ontology_store.store_dir().exists()


def test_ontology_db_records_the_retraction_as_a_revision(seeded):
    ontology_store.binding_path().write_text("modules: [core]\n")
    ontology_store.append_rows([ontology.assertion("src:gone.md", "class", "report", by="user")])
    wiki_engine.delete_source("gone.md")
    [row] = ontology_store.history()
    assert row["via"] == "delete_source"
    assert "via delete_source" in (seeded / "log.md").read_text()
