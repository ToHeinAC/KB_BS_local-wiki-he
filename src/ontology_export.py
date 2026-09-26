"""Standard exports of an ontology (plan Phase 7; an adapter, not needed at runtime).

Pure. The schema becomes a SKOS concept scheme in Turtle (classes as `skos:Concept` with
`skos:broader`, de/en `skos:prefLabel`, `owl:deprecated` + `dct:isReplacedBy`; relations
as `owl:ObjectProperty`, mapped to ELI with `owl:equivalentProperty`). The facts become
JSON-LD with schema.org's `Legislation` terms where they exist (`legislationTransposes`,
`legislationDateVersion`, `exampleOfWork`, …) and ELI otherwise (`eli:based_on`).
Relation attributes (incorporates mode/effect/edition) are not exported.
See docs/ontology.md §Evolution.
"""

from __future__ import annotations

from datetime import date
from typing import Any
from urllib.parse import quote

import ontology
import ontology_query
import ontology_time
from ontology_query import View

BASE = "urn:localwiki:"
ELI = "http://data.europa.eu/eli/ontology#"
SCHEMA_ORG = "https://schema.org/"
_PREFIXES = """\
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix dct: <http://purl.org/dc/terms/> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
"""
_JSONLD_RELATIONS = {
    "transposes": "legislationTransposes",
    "amends": "legislationAmends",
    "repeals": "legislationRepeals",
    "consolidates": "legislationConsolidates",
    "is_part_of": "isPartOf",
    "cites": "citation",
    "based_on": f"{ELI}based_on",
    "applies": f"{ELI}applies",
}
_FORCE = {ontology_time.VALID: "InForce", ontology_time.SUPERSEDED: "NotInForce"}


def _lit(text: str) -> str:
    escaped = text.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
    return f'"{escaped.replace(chr(13), chr(92) + "r")}"'


def _iri(kind: str, ident: str) -> str:
    return f"{BASE}{kind}/{quote(ident, safe='')}"


def _class_turtle(c: ontology.ClassDef) -> str:
    lines = [
        f"<{_iri('class', c.id)}> a skos:Concept",
        f"skos:inScheme <{BASE}scheme>",
        f"skos:notation {_lit(c.id)}",
        *(f"skos:prefLabel {_lit(v)}@{lang}" for lang, v in sorted(c.labels.items())),
        f"skos:definition {_lit(c.definition)}",
    ]
    if c.broader:
        lines.append(f"skos:broader <{_iri('class', c.broader)}>")
    if c.deprecated:
        lines.append("owl:deprecated true")
        if c.replaced_by:
            lines.append(f"dct:isReplacedBy <{_iri('class', c.replaced_by)}>")
    return " ;\n    ".join(lines) + " ."


def _relation_turtle(r: ontology.RelationDef) -> str:
    lines = [f"<{_iri('relation', r.id)}> a owl:ObjectProperty", f"rdfs:label {_lit(r.id)}"]
    if r.eli:
        lines.append(f"owl:equivalentProperty <{ELI}{r.eli}>")
    if r.deprecated:
        lines.append("owl:deprecated true")
    return " ;\n    ".join(lines) + " ."


def skos_turtle(schema: ontology.Schema) -> str:
    """The schema (shared modules + local extension) as a SKOS concept scheme."""
    versions = ", ".join(f"{m} {v}" for m, v in sorted(schema.modules.items()))
    head = (
        f"<{BASE}scheme> a skos:ConceptScheme ;\n    dct:title {_lit('LocalWiki ontology')} ;\n"
        f"    owl:versionInfo {_lit(versions)} ."
    )
    classes = [_class_turtle(c) for c in sorted(schema.classes.values(), key=lambda c: c.id)]
    relations = [_relation_turtle(r) for r in sorted(schema.relations.values(), key=lambda r: r.id)]
    return _PREFIXES + "\n" + "\n\n".join([head, *classes, *relations]) + "\n"


def _type(view: View, cls: object) -> str:
    return (
        "Legislation"
        if ontology_query.in_class(view, str(cls or ""), "legal-instrument")
        else "CreativeWork"
    )


def _work_node(view: View, wid: str, work: dict[str, Any]) -> dict[str, Any]:
    node: dict[str, Any] = {"@id": _iri("work", wid), "@type": _type(view, work.get("class"))}
    if work.get("aliases"):
        node["alternateName"] = list(work["aliases"])
    if work.get("class"):
        node[f"{BASE}class"] = {"@id": _iri("class", str(work["class"]))}
    for rel, targets in work["relations"].items():
        key = _JSONLD_RELATIONS.get(rel, _iri("relation", rel))
        node[key] = [{"@id": _iri("work", t)} for t in targets]
    return node


def _source_node(view: View, name: str, facts: dict[str, Any], today: date) -> dict[str, Any]:
    node: dict[str, Any] = {"@id": _iri("source", name), "@type": _type(view, facts.get("class"))}
    if facts.get("work"):
        node["exampleOfWork"] = {"@id": _iri("work", str(facts["work"]))}
    if facts.get("version_date"):
        node["legislationDateVersion"] = str(facts["version_date"])
    force = _FORCE.get(ontology_time.validity(view, name, today))
    if force:
        node["legislationLegalForce"] = {"@id": f"{SCHEMA_ORG}{force}"}
    return node


def facts_jsonld(view: View, *, db: str, today: date | None = None) -> dict[str, Any]:
    """The DB's works and sources as JSON-LD (schema.org Legislation + ELI)."""
    when = today or date.today()
    graph = [_work_node(view, w, work) for w, work in sorted(view.works.items())]
    graph += [_source_node(view, s, f, when) for s, f in sorted(view.sources.items())]
    dataset = {"@id": _iri("database", db), "@type": "Dataset", "name": db}
    # No top-level @id: that would make @graph a *named* graph, which plain RDF readers skip.
    return {"@context": {"@vocab": SCHEMA_ORG, "eli": ELI}, "@graph": [dataset, *graph]}
