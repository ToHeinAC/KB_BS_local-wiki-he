"""Relations between documents (plan Phase 6): attributes, formula detection, binding, lint."""

from datetime import date
from pathlib import Path
from typing import Any

import pytest

import ontology
import ontology_bundle as ob
import ontology_detect as od
import ontology_graph as og
import ontology_query as oq
import ontology_store

TODAY = date(2026, 9, 26)
HEADS = Path(__file__).resolve().parents[1] / "bench" / "ontology_detect"


@pytest.fixture(scope="module")
def schema() -> ontology.Schema:
    shared = ontology_store.shared_modules()
    built, errors = ontology.build_schema([shared["core"], shared["legal-de"]])
    assert built is not None, errors
    return built


def _view(schema: ontology.Schema, extra: dict[str, Any] | None = None) -> oq.View:
    facts: dict[str, Any] = {
        "sources": {
            "strlschg.md": {"class": "federal-act", "work": "de-strlschg-2017"},
            "strlschv.md": {"class": "ordinance", "work": "de-strlschv-2018"},
            "bimschg.md": {"class": "federal-act", "work": "de-bimschg-1974"},
            "permit.md": {"class": "permit"},
        },
        "works": {
            "de-strlschg-2017": {"class": "federal-act", "aliases": ["StrlSchG"]},
            "de-strlschv-2018": {
                "class": "ordinance",
                "aliases": ["StrlSchV"],
                "based_on": ["de-strlschg-2017"],
                "transposes": ["eu-dir-2013-59-euratom"],
            },
            "de-bimschg-1974": {
                "class": "federal-act",
                "aliases": ["BImSchG", "Bundes-Immissionsschutzgesetz"],
            },
        },
    }
    for section, entries in (extra or {}).items():
        for key, value in entries.items():
            facts[section].setdefault(key, {}).update(value)
    return oq.build_view(schema, facts, {})


# --- relation attributes in facts ---------------------------------------------------------


def test_relation_attributes_survive_projection() -> None:
    row = ontology.assertion(
        "src:permit.md",
        "incorporates",
        "din-6812",
        by="user",
        attributes={"mode": "static", "edition": "2013-06"},
    )
    row["id"] = "a-000001"
    facts = ontology.project([row], multi={"incorporates"})
    assert facts["src:permit.md"]["incorporates"] == [
        {"to": "din-6812", "mode": "static", "edition": "2013-06"}
    ]


def test_relation_items_are_a_set_in_the_canonical_form() -> None:
    items = [{"to": "b", "mode": "static"}, "a", {"mode": "static", "to": "b"}]
    one = {"schema": {"modules": ["core"]}, "facts": {"works": {"w": {"cites": items}}}}
    two = {"schema": {"modules": ["core"]}, "facts": {"works": {"w": {"cites": items[::-1]}}}}
    assert ob.revision_hash(one) == ob.revision_hash(two)


def test_changing_an_attribute_replaces_the_member_without_negating_it() -> None:
    old = {"sources": {"p.md": {"incorporates": [{"to": "din-6812", "mode": "dynamic"}]}}}
    new = {"sources": {"p.md": {"incorporates": [{"to": "din-6812", "mode": "static"}]}}}
    rows = ob.fact_rows(old, new, user="u", evidence="e")
    assert [(r["object"], r["negated"], r.get("attributes")) for r in rows] == [
        ("din-6812", False, {"mode": "static"})
    ]
    gone = ob.fact_rows(old, {"sources": {"p.md": {}}}, user="u", evidence="e")
    assert [(r["object"], r["negated"]) for r in gone] == [("din-6812", True)]


def test_relation_items_are_validated(schema: ontology.Schema) -> None:
    facts = {
        "sources": {"a.md": {"incorporates": [{"mode": "static"}, {"to": "x", "mode": "odd"}]}}
    }
    errors, _ = ob.validate_facts(facts, schema, {"a.md"})
    assert any("to" in e for e in errors)
    assert any("odd" in e for e in errors)


# --- formula detection ---------------------------------------------------------------


def test_a_real_transposition_clause_is_a_rule_fact(schema: ontology.Schema) -> None:
    text = (HEADS / "strlschv_2018.md").read_text(encoding="utf-8")
    found = od.detect_relations(text, _view(schema), self_work="de-strlschv-2018", cls="ordinance")
    [transposes] = [f for f in found if f.rel == "transposes"]
    assert (transposes.target, transposes.status) == ("eu-dir-2013-59-euratom", "confirmed")
    assert "Umsetzung der Richtlinie 2013/59/Euratom des Rates vom 5. Dezember 2013" in (
        transposes.evidence
    )  # a period after a number or an abbreviation does not end the sentence


EINGANG = (
    "Auf Grund des § 4 Absatz 1 Satz 3 und des § 7 Absatz 1 des Bundes-Immissionsschutzgesetzes "
    "in der Fassung der Bekanntmachung vom 17. Mai 2013 (BGBl. I S. 1274) verordnet die "
    "Bundesregierung nach Anhörung der beteiligten Kreise:"
)


def test_the_eingangsformel_yields_based_on_to_a_known_work(schema: ontology.Schema) -> None:
    text = "Verordnung über Anlagen (Anlagenverordnung - AnlV)\n\n" + EINGANG
    found = od.detect_relations(text, _view(schema), self_work="de-anlv-2013", cls="ordinance")
    assert [(f.rel, f.target, f.status) for f in found] == [
        ("based_on", "de-bimschg-1974", "confirmed")
    ]


def test_repeal_needs_a_named_known_work_and_is_only_proposed(schema: ontology.Schema) -> None:
    text = (
        "Artikel 3\nDie StrlSchV tritt am Tag nach der Verkündung außer Kraft.\n"
        "Eilverordnungen treten spätestens sechs Monate nach ihrem Inkrafttreten außer Kraft."
    )
    found = od.detect_relations(text, _view(schema), self_work="de-x-2020", cls="federal-act")
    assert [(f.rel, f.target, f.status) for f in found] == [
        ("repeals", "de-strlschv-2018", "proposed")
    ]


@pytest.mark.parametrize(
    ("sentence", "target", "attrs"),
    [
        (
            "Die Anforderungen der DIN 6812:2013-06 sind einzuhalten.",
            "din-6812",
            {"mode": "static", "edition": "2013-06", "effect": "mandatory"},
        ),
        (
            # TA Luft, verbatim
            "Anzahl der Geruchseinheiten nach DIN EN 13725 "
            "(Ausgabe Juli 2003, Berichtigung April 2006)",
            "din-en-13725",
            {"mode": "static", "edition": "2003-07"},
        ),
        (
            "Die Anforderungen gelten als erfüllt, wenn DIN 6844-1 in der jeweils geltenden "
            "Fassung angewendet wird.",
            "din-6844-1",
            {"mode": "dynamic", "effect": "presumption"},
        ),
        ("Die Prüfung erfolgt nach KTA 3601.", "kta-3601", {}),
    ],
)
def test_references_to_standards_are_proposed_with_attributes(
    schema: ontology.Schema, sentence: str, target: str, attrs: dict[str, str]
) -> None:
    found = od.detect_relations(sentence, _view(schema), self_work=None, cls="permit")
    [ref] = found
    assert (ref.rel, ref.target, ref.status, ref.attributes) == (
        "incorporates",
        target,
        "proposed",
        attrs,
    )


def test_references_only_for_classes_in_the_relation_domain(schema: ontology.Schema) -> None:
    text = "Die Anforderungen der DIN 6812:2013-06 sind einzuhalten."
    assert od.detect_relations(text, _view(schema), self_work=None, cls="report") == []
    assert od.detect_relations(text, _view(schema), self_work=None, cls=None) == []


# --- chains, binding paths (report §9) ---------------------------------------------------


def _permit_view(schema: ontology.Schema, mode: str = "static") -> oq.View:
    attrs = {"to": "din-6812", "mode": mode, "effect": "mandatory"}
    if mode == "static":
        attrs["edition"] = "2013-06"
    return _view(schema, {"sources": {"permit.md": {"incorporates": [attrs]}}})


def test_chain_walks_a_relation_transitively(schema: ontology.Schema) -> None:
    extra = {"works": {"de-strlschg-2017": {"transposes": ["eu-dir-2013-59-euratom"]}}}
    view = _view(schema, extra)
    assert og.chain(view, "de-strlschv-2018", "based_on") == [
        "de-strlschv-2018",
        "de-strlschg-2017",
    ]


def test_a_static_mandatory_reference_in_a_permit_makes_a_standard_binding(
    schema: ontology.Schema,
) -> None:
    [path] = og.binding_of(_permit_view(schema), "din-6812", TODAY)
    assert "permit.md" in path
    assert "static" in path
    assert "2013-06" in path
    assert "mandatory" in path
    assert "newer editions are not binding" in path


def test_without_a_binding_reference_a_standard_is_not_binding(schema: ontology.Schema) -> None:
    [line] = og.binding_of(_view(schema), "din-6812", TODAY)
    assert line.startswith("Not binding by any reference in this database")


# --- lint (report §8) -------------------------------------------------------------------


def test_lint_flags_rank_violations_cycles_and_dates(schema: ontology.Schema) -> None:
    extra = {
        "sources": {"vwv.md": {"class": "admin-regulation", "work": "de-vwv-2020"}},
        "works": {
            "de-vwv-2020": {"class": "admin-regulation"},
            "de-strlschv-2018": {"based_on": ["de-strlschg-2017", "de-vwv-2020"]},
            "de-strlschg-2017": {
                "based_on": ["de-strlschv-2018"],
                "in_force_from": "2020-01-01",
                "in_force_until": "2019-01-01",
            },
        },
    }
    messages = [f["message"] for f in og.lint(_view(schema, extra))]
    assert any("de-strlschv-2018" in m and "de-vwv-2020" in m and "rank" in m for m in messages)
    assert any("cycle" in m and "based_on" in m for m in messages)
    assert any("de-strlschg-2017" in m and "in_force_until" in m for m in messages)


def test_lint_reports_missing_editions_and_missing_documents(schema: ontology.Schema) -> None:
    findings = og.lint(_permit_view(schema))
    messages = [f["message"] for f in findings]
    assert any("din-6812" in m and "2013-06" in m for m in messages)
    assert any("eu-dir-2013-59-euratom" in m and "1 document" in m for m in messages)
    assert {f["level"] for f in findings} <= {"warning", "info"}
