"""The all-levels graph: one map over every shard the clearance reaches (docs/security.md)."""

from pathlib import Path

import pytest

import db_context
import graph_export
import graph_widget
import wiki_engine

DB = "KI"
STRICT = f"{DB}@strict"
CONF = f"{DB}@confidential"
CANARY = "okapiflint4402"


def _page(name: str, title: str, related: list[str], sources: list[str]) -> None:
    rel = ", ".join(related)
    src = ", ".join(sources)
    (db_context.wiki_dir() / name).write_text(
        f"---\ntitle: {title}\ntype: concept\nrelated: [{rel}]\nsources: [{src}]\n---\n# {title}\n"
    )


@pytest.fixture
def shards(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(db_context, "DATA_ROOT", tmp_path)
    db_context.set_active_db(DB)
    with db_context.clearance({DB: 2}):
        for shard in (DB, CONF, STRICT):
            db_context.ensure_shard(shard)
        with db_context.using_db(DB):
            wiki_engine.init_wiki()
            _page("shield.md", "Shielding", ["dose.md"], ["plan.pdf"])
            _page("dose.md", "Dose", ["shield.md"], [])
        with db_context.using_db(STRICT):
            wiki_engine.init_wiki()
            _page("shield.md", f"Shielding {CANARY}", ["bunker.md"], ["plan.pdf"])
            _page("bunker.md", "Bunker", ["shield.md"], [])
    yield
    db_context.set_active_db(DB)


def _by_id(payload: dict) -> dict:
    return {n["id"]: n for n in payload["nodes"]}


def test_every_reachable_level_is_in_one_payload_with_its_level(shards) -> None:
    with db_context.clearance({DB: 2}):
        payload = graph_export.export_levels((DB, STRICT))
    nodes = _by_id(payload)
    assert nodes[f"{DB}::dose.md"]["level"] == 0
    assert nodes[f"{STRICT}::bunker.md"]["level"] == 2
    assert nodes[f"{STRICT}::bunker.md"]["name"] == "bunker.md"
    assert payload["levels"] == {"0": "Normal", "2": "Strictly confidential"}


def test_connections_are_kept_inside_each_level(shards) -> None:
    with db_context.clearance({DB: 2}):
        payload = graph_export.export_levels((DB, STRICT))
    related = {(e["s"], e["t"]) for e in payload["edges"] if e["type"] == "related-to"}
    assert (f"{DB}::dose.md", f"{DB}::shield.md") in related
    assert (f"{STRICT}::bunker.md", f"{STRICT}::shield.md") in related


def test_the_same_page_or_source_at_two_levels_is_linked(shards) -> None:
    with db_context.clearance({DB: 2}):
        payload = graph_export.export_levels((DB, STRICT))
    same = {(e["s"], e["t"]) for e in payload["edges"] if e["type"] == "same-topic"}
    assert (f"{DB}::shield.md", f"{STRICT}::shield.md") in same
    assert (f"{DB}::source::plan.pdf", f"{STRICT}::source::plan.pdf") in same


def test_a_level_above_the_clearance_cannot_be_merged(shards) -> None:
    with db_context.clearance({DB: 0}), pytest.raises(db_context.AccessDenied):
        graph_export.export_levels((DB, STRICT))


def test_render_args_merges_only_reachable_levels(shards) -> None:
    graph_widget._payload_levels.clear()
    with db_context.clearance({DB: 1}):
        args = graph_widget.render_args(overlays=[], accent="#000", selected=None, all_levels=True)
    assert CANARY not in str(args)
    with db_context.clearance({DB: 2}):
        args = graph_widget.render_args(overlays=[], accent="#000", selected=None, all_levels=True)
    assert CANARY in str(args)
    with db_context.clearance({DB: 1}):
        again = graph_widget.render_args(overlays=[], accent="#000", selected=None, all_levels=True)
    assert CANARY not in str(again)
