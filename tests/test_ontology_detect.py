"""Deterministic ontology detection on a document head (plan Phase 3; pure)."""

from pathlib import Path

import pytest

import ontology
import ontology_detect as od
import ontology_store


@pytest.fixture(scope="module")
def schema() -> ontology.Schema:
    shared = ontology_store.shared_modules()
    built, errors = ontology.build_schema([shared["core"], shared["legal-de"]])
    assert errors == []
    assert built is not None
    return built


HEADS = Path(__file__).resolve().parents[1] / "bench" / "ontology_detect"


def _head(name: str) -> str:
    return (HEADS / name).read_text(encoding="utf-8")


STRLSCHG, STRLSCHV, ATG, GG, TA_LUFT, EU_DIR = (
    _head(n)
    for n in (
        "strlschg.md",
        "strlschv_2018.md",
        "atg.md",
        "gg.md",
        "ta_luft.md",
        "eu_dir_2013_59.md",
    )
)
EU_REG = """\
Verordnung (EU) 2016/679 des Europäischen Parlaments und des Rates vom 27. April 2016
zum Schutz natürlicher Personen bei der Verarbeitung personenbezogener Daten
"""
AI_REPORT = """\
# Local AI Deep Dive July 2026

This report compares local inference stacks. Section 3 covers the DIN-A4 printable checklist
and the "Genehmigungsfrei" note from our legal team is out of scope.
"""


@pytest.mark.parametrize(
    ("text", "cls", "work", "aliases"),
    [
        (STRLSCHG, "federal-act", "de-strlschg-2017", ("StrlSchG", "Strahlenschutzgesetz")),
        (STRLSCHV, "ordinance", "de-strlschv-2018", ("StrlSchV", "Strahlenschutzverordnung")),
        (ATG, "federal-act", "de-atg-1959", ("AtG", "Atomgesetz")),
        (GG, "constitution", "de-gg-1949", ("GG",)),
        (TA_LUFT, "admin-regulation", None, ()),
        (EU_DIR, "eu-directive", "eu-dir-2013-59-euratom", ("Richtlinie 2013/59/Euratom",)),
        (EU_REG, "eu-regulation", "eu-reg-2016-679", ("Verordnung (EU) 2016/679",)),
    ],
)
def test_legal_heads_get_class_and_work(
    schema: ontology.Schema, text: str, cls: str, work: str | None, aliases: tuple[str, ...]
) -> None:
    found = od.detect(text, schema)
    assert found.class_id == cls
    assert found.work == work
    assert set(found.aliases) == set(aliases)
    assert found.evidence
    assert found.evidence in text


def test_a_report_gets_no_class_and_no_work(schema: ontology.Schema) -> None:
    assert od.detect(AI_REPORT, schema) == od.Detection()


def test_only_the_head_is_read(schema: ontology.Schema) -> None:
    late = "x" * od.HEAD_CHARS + "\nAllgemeine Verwaltungsvorschrift"
    assert od.detect(late, schema).class_id is None


def test_deprecated_classes_are_never_detected(schema: ontology.Schema) -> None:
    ordinance = schema.classes["ordinance"]
    classes = {
        **schema.classes,
        "ordinance": ordinance.__class__(
            **{**ordinance.__dict__, "deprecated": True, "replaced_by": "federal-act"}
        ),
    }
    patched = ontology.Schema(schema.modules, classes, schema.relations)
    assert od.detect(STRLSCHV, patched).class_id != "ordinance"


def test_work_needs_a_legal_class(schema: ontology.Schema) -> None:
    text = "Harness notes (Engineering Report - HER)\nAusfertigungsdatum: 01.01.2020\n"
    assert od.detect(text, schema).work is None


# --- verifying an LLM proposal (report §7.4) --------------------------------------------


def test_llm_answer_is_accepted_only_with_a_verbatim_quote(schema: ontology.Schema) -> None:
    head = "Leitfaden zur Fachkunde im Strahlenschutz\n\nDiese Richtlinie regelt die Fachkunde."
    ok = '```json\n{"class": "guidance", "quote": "Diese  Richtlinie regelt\\ndie Fachkunde."}\n```'
    assert od.parse_proposal(ok, head, {"guidance", "report"}) == (
        "guidance",
        "Diese  Richtlinie regelt\ndie Fachkunde.",
    )
    fabricated = '{"class": "guidance", "quote": "Dieses Gesetz tritt sofort in Kraft."}'
    assert od.parse_proposal(fabricated, head, {"guidance"}) is None
    assert (
        od.parse_proposal(
            '{"class": "permit", "quote": "Leitfaden zur Fachkunde"}', head, {"guidance"}
        )
        is None
    )
    assert od.parse_proposal('{"class": "none", "quote": ""}', head, {"guidance"}) is None
    assert od.parse_proposal("no json here", head, {"guidance"}) is None
    assert od.parse_proposal('{"class": "guidance", "quote": "Leit"}', head, {"guidance"}) is None


def test_classify_options_are_leaf_classes_with_definitions(schema: ontology.Schema) -> None:
    options = od.classify_options(schema)
    assert "report" in options
    assert "legal-instrument" not in options  # has children: pick the specific one
    assert "document" not in options
    assert all("\n" not in d for d in options.values())
