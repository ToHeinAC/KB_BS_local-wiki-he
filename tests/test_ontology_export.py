"""Standard exports (plan Phase 7): schema as SKOS Turtle, facts as schema.org/ELI JSON-LD."""

import json
from typing import Any

import pytest
from rdflib import Graph, Literal, Namespace, URIRef
from rdflib.namespace import OWL, SKOS

import ontology
import ontology_export as ox
import ontology_query as oq
import ontology_store

LW = Namespace(ox.BASE)
SDO = Namespace("https://schema.org/")


@pytest.fixture(scope="module")
def schema() -> ontology.Schema:
    shared = ontology_store.shared_modules()
    local = {
        "id": "local",
        "version": "0.1.0",
        "classes": {
            "memo": {
                "broader": "report",
                "labels": {"de": 'Notiz "intern"', "en": "Memo"},
                "definition": r"Internal memo with a back\slash",
                "deprecated": True,
                "replaced_by": "report",
            }
        },
    }
    built, errors = ontology.build_schema([shared["core"], shared["legal-de"], local])
    assert built is not None, errors
    return built


def test_the_skos_export_parses_and_carries_the_hierarchy(schema: ontology.Schema) -> None:
    g = Graph().parse(data=ox.skos_turtle(schema), format="turtle")
    ordinance, instrument = LW["class/ordinance"], LW["class/legal-instrument"]
    assert (ordinance, SKOS.broader, instrument) in g
    assert (ordinance, SKOS.prefLabel, Literal("Rechtsverordnung", lang="de")) in g
    assert (ordinance, SKOS.prefLabel, Literal("Ordinance", lang="en")) in g
    memo = LW["class/memo"]
    assert (memo, OWL.deprecated, Literal(True)) in g
    assert (memo, URIRef("http://purl.org/dc/terms/isReplacedBy"), LW["class/report"]) in g
    assert (memo, SKOS.prefLabel, Literal('Notiz "intern"', lang="de")) in g
    assert (LW["relation/transposes"], OWL.equivalentProperty, URIRef(ox.ELI + "transposes")) in g


def test_the_json_ld_export_parses_with_schema_org_terms(schema: ontology.Schema) -> None:
    facts: dict[str, Any] = {
        "sources": {
            "StrlSchV Stand B.md": {
                "class": "ordinance",
                "work": "de-strlschv-2018",
                "version_date": "2024-10-23",
            }
        },
        "works": {
            "de-strlschv-2018": {
                "class": "ordinance",
                "aliases": ["StrlSchV"],
                "transposes": ["eu-dir-2013-59-euratom"],
                "based_on": ["de-strlschg-2017"],
            }
        },
    }
    doc = ox.facts_jsonld(oq.build_view(schema, facts, {}), db="KI")
    g = Graph().parse(data=json.dumps(doc), format="json-ld")
    work, source = LW["work/de-strlschv-2018"], LW["source/StrlSchV%20Stand%20B.md"]
    assert (work, SDO.legislationTransposes, LW["work/eu-dir-2013-59-euratom"]) in g
    assert (work, URIRef(ox.ELI + "based_on"), LW["work/de-strlschg-2017"]) in g
    assert (work, SDO.alternateName, Literal("StrlSchV")) in g
    assert (source, SDO.exampleOfWork, work) in g
    assert (source, SDO.legislationDateVersion, Literal("2024-10-23")) in g
