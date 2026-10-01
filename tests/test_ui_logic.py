"""UI-agnostic logic shared by the Streamlit and NiceGUI frontends (src/ui_logic.py)."""

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest

import db_context
import ui_logic
import wiki_engine


@pytest.fixture(autouse=True)
def _restore_binding() -> Iterator[None]:
    """These tests bind DBs and scopes; conftest only resets clearance, so undo them here."""
    active = db_context._active.set(db_context._active.get())
    scope = db_context._scope.set(db_context._scope.get())
    yield
    db_context._scope.reset(scope)
    db_context._active.reset(active)


def _confidential_shard() -> None:
    with db_context.clearance({"test": 1}):
        db_context.ensure_shard("test@confidential")


def test_ontology_line_names_matches_targets_and_favoured_sources() -> None:
    frame = {"matched": ["StrlSchG"], "works": ["w1"], "classes": ["law"], "sources": ["a", "b"]}
    assert (
        ui_logic.ontology_line(frame) == "Ontology — “StrlSchG” → `w1`, `law`; 2 source(s) favoured"
    )
    assert ui_logic.ontology_line({**frame, "db": "KI"}).startswith("Ontology — KI: ")


def test_level_names_and_report_ref() -> None:
    assert ui_logic.level_name("KI") == "Normal"
    assert ui_logic.level_name("KI@confidential") == "Confidential"
    assert ui_logic.level_key_label("confidential") == "Confidential"
    assert ui_logic.report_ref("/x/data/KI/wiki/comparisons/r.md") == "comparisons/r.md"


def test_grants_shrank_only_when_a_level_or_db_drops() -> None:
    assert ui_logic.grants_shrank({"KI": 2}, {"KI": 1}) is True
    assert ui_logic.grants_shrank({"KI": 1, "B": 0}, {"KI": 1}) is True
    assert ui_logic.grants_shrank({"KI": 1}, {"KI": 2, "B": 0}) is False
    assert ui_logic.grants_shrank(None, {"KI": 0}) is False
    assert ui_logic.grants_shrank({}, {}) is False


def test_convert_progress_maps_page_progress_into_batch_fraction() -> None:
    seen: list[tuple[float, str]] = []
    cb = ui_logic.convert_progress(lambda frac, text: seen.append((frac, text)), "a.pdf", 1, 2)
    cb(1, 2, "page 1")
    cb(0, 0, "done")
    assert seen == [(0.75, "a.pdf: page 1"), (1.0, "a.pdf: done")]


def test_shard_ref_qualifies_only_higher_levels(raw_dir: Path) -> None:
    with db_context.clearance({"test": 1}):
        assert ui_logic.shard_ref("p.md") == "p.md"
        with db_context.using_db("test@confidential"):
            assert ui_logic.shard_ref("p.md") == "test@confidential::p.md"


def test_visible_duplicate_ignores_levels_the_user_cannot_reach(
    raw_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _confidential_shard()
    hits: list[str] = []

    def is_dup(_data: bytes) -> bool:
        hits.append(db_context.get_active_db())
        return db_context.get_active_db() == "test@confidential"

    monkeypatch.setattr(ui_logic.dedup, "is_duplicate", is_dup)
    with db_context.clearance({"test": 0}):
        assert ui_logic.visible_duplicate(b"x", "test") is False
    assert hits == ["test"]
    hits.clear()
    with db_context.clearance({"test": 1}):
        assert ui_logic.visible_duplicate(b"x", "test") is True


def test_resolve_by_shard_reconciles_inside_each_pages_shard(
    raw_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _confidential_shard()
    calls: list[tuple[str, list[str]]] = []

    def resolve(_desc: str, names: list[str], _guidance: str) -> dict[str, list[str]]:
        calls.append((db_context.get_active_db(), names))
        return {"updated": names, "skipped": []}

    monkeypatch.setattr(wiki_engine, "resolve_contradiction", resolve)
    with db_context.clearance({"test": 1}):
        out = ui_logic.resolve_by_shard("d", ["a.md", "test@confidential::b.md"], "g", "test")
    assert calls == [("test", ["a.md"]), ("test@confidential", ["b.md"])]
    assert out == {"updated": ["a.md", "test@confidential::b.md"], "skipped": []}


def test_resolve_by_shard_without_refs_still_calls_the_active_shard(
    raw_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        wiki_engine, "resolve_contradiction", lambda *_a: {"updated": [], "skipped": []}
    )
    with db_context.clearance({"test": 0}):
        assert ui_logic.resolve_by_shard("d", [], "g", "test") == {"updated": [], "skipped": []}


def test_ingest_level_reports_each_file_and_collects_failures(
    raw_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    labels: list[str] = []
    ticks: list[int] = []

    @contextmanager
    def on_file(label: str):
        labels.append(label)
        yield

    def fake_ingest(f: dict[str, Any], *_a: Any) -> None:
        if f["save_name"] == "bad.md":
            raise ValueError("boom")

    monkeypatch.setattr(ui_logic, "ingest_file", fake_ingest)
    monkeypatch.setattr(wiki_engine, "init_wiki", lambda: None)
    monkeypatch.setattr(wiki_engine, "rebuild_lex_index", lambda: {})
    agg: dict[str, list[str]] = {"created": [], "updated": [], "failed": [], "ontology": []}
    group = [{"save_name": "ok.md"}, {"save_name": "bad.md"}]
    with db_context.clearance({"test": 0}):
        ui_logic.ingest_level(
            "test", group, {"ontology": None}, agg, "u", on_file, lambda: ticks.append(1)
        )
    assert labels == ["Ingesting ok.md (Normal)…", "Ingesting bad.md (Normal)…"]
    assert agg["failed"] == ["bad.md: boom"]
    assert len(ticks) == 2


def test_resolve_raw_source_previews_text_and_strips_chunk_and_section_suffixes(
    raw_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[str] = []
    monkeypatch.setattr(wiki_engine, "read_raw_source", lambda n: seen.append(n) or b"body")
    with db_context.clearance({"test": 0}):
        assert ui_logic.resolve_raw_source("law.md [Teil 2/3]") == (True, b"body")
        assert ui_logic.resolve_raw_source("law.md §62") == (True, b"body")
        assert ui_logic.resolve_raw_source("scan.pdf") == (False, None)
    assert seen == ["law.md", "law.md"]


def test_resolve_raw_source_reports_a_missing_text_file(
    raw_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(wiki_engine, "read_raw_source", lambda _n: None)
    with db_context.clearance({"test": 0}):
        assert ui_logic.resolve_raw_source("gone.md") == (True, None)


def test_answer_fast_returns_the_message_fields_or_an_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    res = {"answer": "A", "sources": ["s.md"], "raw_sources": ["r.md"], "audit": {"k": 1}}
    monkeypatch.setattr(wiki_engine, "query_with_sources", lambda q: res)
    assert ui_logic.answer_fast("q") == {
        "content": "A", "sources": ["s.md"], "raw_sources": ["r.md"], "audit": {"k": 1},
    }  # fmt: skip

    def boom(_q: str) -> dict[str, Any]:
        raise RuntimeError("ollama down")

    monkeypatch.setattr(wiki_engine, "query_with_sources", boom)
    err = ui_logic.answer_fast("q")
    assert err["content"] == "Error: ollama down"
    assert (err["sources"], err["raw_sources"], err["audit"]) == ([], [], None)


def test_fast_answer_page_tags_become_wiki_citations() -> None:
    aliases = ui_logic.wiki_aliases(["hub.md", "KI::orbit.md"], {"hub.md": "Hub Page"})
    text = (
        "See [Hub Page] and [hub.md], [orbit] [Source: x.pdf] [Wiki: a.md] "
        "[link](http://a) [unknown]."
    )
    assert ui_logic.tag_wiki_citations(text, aliases) == (
        "See [Wiki: hub.md] and [Wiki: hub.md], [Wiki: KI::orbit.md] [Source: x.pdf] "
        "[Wiki: a.md] [link](http://a) [unknown]."
    )


def test_fast_answer_tags_in_the_forms_small_models_write() -> None:
    aliases = ui_logic.wiki_aliases(["hub.md", "why.md"], {"why.md": "Why Agents"})
    text = (
        "A [hub.md Key facts (Teil 4)]. B [hub.md, why.md Key facts]. C [Why Agents.md]. "
        "D [hub.md, x]."
    )
    assert ui_logic.tag_wiki_citations(text, aliases) == (
        "A [Wiki: hub.md]. B [Wiki: hub.md] [Wiki: why.md]. C [Wiki: why.md]. D [hub.md, x]."
    )


def test_fast_answer_other_pages_and_originals_are_tagged_too() -> None:
    aliases = ui_logic.wiki_aliases(
        ["hub.md"], {"hub.md": "Hub", "other.md": "Other Page"}, ["KI::JEN.md"]
    )
    text = "A [other.md] B [JEN.md] C [Other Page] D [JEN]"
    assert ui_logic.tag_wiki_citations(text, aliases) == (
        "A [Wiki: other.md] B [Source: KI::JEN.md] C [Wiki: other.md] D [Source: KI::JEN.md]"
    )


def test_answer_fast_tags_the_pages_it_cites(monkeypatch: pytest.MonkeyPatch) -> None:
    res = {"answer": "Orbits [Hub].", "sources": ["hub.md"], "raw_sources": [], "audit": None}
    monkeypatch.setattr(wiki_engine, "query_with_sources", lambda q: res)
    monkeypatch.setattr(wiki_engine, "list_pages", lambda: [{"filename": "hub.md", "title": "Hub"}])
    assert ui_logic.answer_fast("q")["content"] == "Orbits [Wiki: hub.md]."


def test_save_answer_files_into_the_target_with_only_its_own_related_pages(
    raw_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    got: dict[str, Any] = {}

    def file_answer(q: str, a: str, related: list[str], derived_from: list[str]) -> str:
        got.update(db=db_context.get_active_db(), q=q, a=a, related=related, derived=derived_from)
        return "insights/x.md"

    monkeypatch.setattr(wiki_engine, "file_answer", file_answer)
    _confidential_shard()
    sources = ["p.md", "test@confidential::q.md"]
    with db_context.clearance({"test": 1}):
        db_context.set_search_scope(["test", "test@confidential"])
        rel = ui_logic.save_answer("Q", "A", sources, ["r.md"], "test")
    assert rel == "insights/x.md"
    assert (got["db"], got["related"]) == ("test", ["p.md"])
    assert got["derived"] == [*sources, "r.md"]


def test_read_report_reads_from_the_high_water_shard(
    raw_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _confidential_shard()
    seen: list[tuple[str, str]] = []

    def read(ref: str) -> dict[str, str]:
        seen.append((db_context.get_active_db(), ref))
        return {"content": "# report"}

    monkeypatch.setattr(wiki_engine, "read_page_parsed", read)
    with db_context.clearance({"test": 1}):
        db_context.set_search_scope(["test", "test@confidential"])
        assert ui_logic.read_report("/d/wiki/comparisons/r.md", "test") == "# report"
    assert seen == [("test@confidential", "comparisons/r.md")]


@pytest.mark.parametrize(
    ("as_source", "result", "note", "called"),
    [
        (True, {"duplicate": True, "source_name": "s"}, "Already registered as a source.", "src"),
        (True, {"duplicate": False, "source_name": "s.md"}, "Saved as source `s.md`.", "src"),
        (False, None, "Saved to wiki.", "ingest"),
    ],
)
def test_save_research_notes_what_was_written(
    raw_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    as_source: bool,
    result: dict[str, Any] | None,
    note: str,
    called: str,
) -> None:
    calls: list[str] = []
    monkeypatch.setattr(wiki_engine, "ingest_as_source", lambda *_a: calls.append("src") or result)
    monkeypatch.setattr(wiki_engine, "ingest", lambda *_a: calls.append("ingest"))
    with db_context.clearance({"test": 0}):
        assert ui_logic.save_research("ans", "T", as_source, "test") == note
    assert calls == [called]


def test_bind_level_sets_active_db_and_search_scope(raw_dir: Path) -> None:
    with db_context.clearance({"test": 1}):
        ui_logic.bind_level("test@confidential")
        assert db_context.get_active_db() == "test@confidential"
        assert db_context.search_scope() == ("test@confidential",)


def test_unload_model_posts_keep_alive_zero_to_the_pinned_host(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    posts: list[tuple[str, dict[str, Any]]] = []
    monkeypatch.setattr(ui_logic.ollama_client, "host", lambda: "http://h:1")
    monkeypatch.setattr(
        ui_logic.requests, "post", lambda url, json, timeout: posts.append((url, json))
    )
    monkeypatch.setenv("OLLAMA_MODEL", "m")
    ui_logic.unload_model()
    assert posts == [("http://h:1/api/generate", {"model": "m", "keep_alive": 0})]
    monkeypatch.setattr(
        ui_logic.requests, "post", lambda *a, **k: (_ for _ in ()).throw(OSError("down"))
    )
    ui_logic.unload_model()  # never raises
