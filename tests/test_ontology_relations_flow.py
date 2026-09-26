"""Relations end to end (plan Phase 6): upload → facts/proposals → lookup, graph, lint."""

from pathlib import Path
from typing import Any

import pytest

import auth
import dedup
import graph_export
import ollama_client
import ontology
import ontology_detect
import ontology_store
import tools
import wiki_engine

HEADS = Path(__file__).resolve().parents[1] / "bench" / "ontology_detect"
PERMIT = (
    "Genehmigung nach § 12 StrlSchG\n\n"
    "Der Klinik Z wird die Genehmigung zum Betrieb der Anlage erteilt.\n"
    "Die Anforderungen der DIN 6812:2013-06 sind einzuhalten.\n"
)


@pytest.fixture
def legal(wiki_dir: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(ollama_client, "generate", lambda *a, **k: "{}")  # no proposals
    ontology_store.binding_path().write_text("modules: [core, legal-de]\n")
    auth.add_user("maint", "pw", ["test"], maintains=["test"])
    return wiki_dir


def _upload(text: str, name: str) -> None:
    dedup.register_file(text.encode(), name)
    schema, _ = ontology_store.load()
    assert schema is not None
    detected = ontology_detect.detected_dict(ontology_detect.detect(text, schema), "")
    review = {"class": detected["class"], "work": detected["work"]}
    wiki_engine.record_source_ontology(text, name, review, detected, user="maint")


def _facts() -> dict[str, Any]:
    return ontology_store.current_state()["facts"]


def test_a_transposition_clause_becomes_a_fact_of_the_work(legal: Path) -> None:
    _upload((HEADS / "strlschv_2018.md").read_text(encoding="utf-8"), "strlschv.md")
    work = _facts()["works"]["de-strlschv-2018"]
    assert work["transposes"] == ["eu-dir-2013-59-euratom"]


def test_a_confirmed_reference_keeps_its_attributes_and_makes_the_standard_binding(
    legal: Path,
) -> None:
    _upload(PERMIT, "permit.md")
    [proposal] = [r for r in ontology_store.proposals() if r["predicate"] == "incorporates"]
    assert proposal["subject"] == "src:permit.md"
    wiki_engine.decide_proposal(proposal["id"], accept=True, user="maint")
    assert _facts()["sources"]["permit.md"]["incorporates"] == [
        {"to": "din-6812", "mode": "static", "edition": "2013-06", "effect": "mandatory"}
    ]
    answer = tools.TOOL_FUNCTIONS["ontology_lookup"](term="DIN 6812")
    assert "din-6812 ◄ incorporates (static, mandatory) ─ permit.md (permit)" in answer


def test_lookup_shows_the_based_on_chain(legal: Path) -> None:
    ontology_store.append_rows(
        [
            ontology.assertion("work:de-strlschv-2018", "aliases", "StrlSchV", by="rule"),
            ontology.assertion("work:de-strlschv-2018", "based_on", "de-strlschg-2017", by="rule"),
            ontology.assertion("work:de-strlschg-2017", "based_on", "eu-x", by="rule"),
        ]
    )
    answer = tools.TOOL_FUNCTIONS["ontology_lookup"](term="StrlSchV")
    assert "based_on chain: de-strlschv-2018 → de-strlschg-2017 → eu-x" in answer


def _two_laws() -> None:
    for name, work, cls in (
        ("strlschv.md", "de-strlschv-2018", "ordinance"),
        ("strlschg.md", "de-strlschg-2017", "federal-act"),
    ):
        dedup.register_file(name.encode(), name)
        ontology_store.append_rows(
            [
                ontology.assertion(f"src:{name}", "class", cls, by="rule"),
                ontology.assertion(f"src:{name}", "work", work, by="rule"),
            ]
        )
    ontology_store.append_rows(
        [ontology.assertion("work:de-strlschv-2018", "based_on", "de-strlschg-2017", by="rule")]
    )


def test_the_graph_draws_directed_relation_edges_and_ranks(legal: Path) -> None:
    _two_laws()
    graph = wiki_engine.build_typed_graph()
    assert {
        "from": "source::strlschv.md",
        "to": "source::strlschg.md",
        "type": "based_on",
    } in graph["edges"]
    nodes = {n["id"]: n for n in graph_export.export()["nodes"]}
    assert (nodes["source::strlschv.md"]["rank"], nodes["source::strlschg.md"]["rank"]) == (4, 3)


def test_lint_includes_the_ontology_findings(legal: Path) -> None:
    _two_laws()
    ontology_store.append_rows(
        [ontology.assertion("work:de-strlschg-2017", "based_on", "de-strlschv-2018", by="rule")]
    )
    assert any("cycle in based_on" in f["message"] for f in wiki_engine.ontology_lint())
    (legal / "page.md").write_text("---\ntitle: Page\ntype: concept\n---\nContent")
    report = wiki_engine.lint()
    assert "Ontology consistency" in report
    assert "cycle in based_on" in report
