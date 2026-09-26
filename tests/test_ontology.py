"""Pure ontology core: module validation, schema merge, ledger projection (no I/O)."""

import copy
from typing import Any

import pytest

import ontology


def _labels(en: str, de: str) -> dict[str, str]:
    return {"en": en, "de": de}


def _core() -> dict[str, Any]:
    return {
        "id": "core",
        "version": "1.2.0",
        "classes": {
            "document": {"labels": _labels("Document", "Dokument"), "definition": "Any source"},
            "report": {
                "broader": "document",
                "labels": _labels("Report", "Bericht"),
                "definition": "A report or study",
                "cues": [r"\bBericht\b"],
            },
        },
        "relations": {
            "cites": {
                "domain": "document",
                "range": "document",
                "inverse": "cited_by",
                "target": "work",
            }
        },
    }


def _legal() -> dict[str, Any]:
    return {
        "id": "legal-de",
        "version": "0.1.0",
        "requires": ["core@^1"],
        "classes": {
            "ordinance": {
                "broader": "document",
                "rank": 4,
                "norm": True,
                "labels": _labels("Ordinance", "Verordnung"),
                "definition": "Rechtsverordnung",
            }
        },
        "relations": {
            "based_on": {
                "domain": ["ordinance"],
                "range": "document",
                "inverse": "basis_for",
                "target": "work",
                "eli": "based_on",
            }
        },
    }


def _errors(*modules: dict[str, Any]) -> list[str]:
    schema, errors = ontology.build_schema(list(modules))
    assert (schema is None) == bool(errors)
    return errors


def _has(errors: list[str], *needles: str) -> bool:
    return any(all(n in e for n in needles) for e in errors)


# --- schema: valid input ---------------------------------------------------------


def test_valid_modules_build_a_merged_schema() -> None:
    schema, errors = ontology.build_schema([_core(), _legal()])
    assert errors == []
    assert schema is not None
    assert schema.modules == {"core": "1.2.0", "legal-de": "0.1.0"}
    assert schema.classes["ordinance"].broader == "document"
    assert schema.classes["ordinance"].module == "legal-de"
    assert schema.relations["based_on"].domain == ("ordinance",)
    assert schema.relations["cites"].range == ("document",)
    assert schema.multi_valued() == {"aliases", "cites", "based_on"}


# --- schema: meta-rules (report §5.4) -------------------------------------------


def test_cycle_in_broader_is_rejected() -> None:
    core = _core()
    core["classes"]["document"]["broader"] = "report"
    assert _has(_errors(core), "cycle", "document")


def test_dangling_broader_is_rejected() -> None:
    core = _core()
    core["classes"]["report"]["broader"] = "nowhere"
    assert _has(_errors(core), "report", "nowhere")


def test_asymmetric_inverse_is_rejected() -> None:
    core = _core()
    core["relations"]["cited_by"] = {
        "domain": "document",
        "range": "document",
        "inverse": "mentions",
        "target": "work",
    }
    assert _has(_errors(core), "inverse", "cited_by")


@pytest.mark.parametrize(("cue", "needle"), [("x*", "empty"), ("(", "regex"), ("a" * 201, "long")])
def test_bad_cues_are_rejected(cue: str, needle: str) -> None:
    core = _core()
    core["classes"]["report"]["cues"] = [cue]
    assert _has(_errors(core), "report", needle)


def test_missing_label_language_is_rejected() -> None:
    core = _core()
    del core["classes"]["report"]["labels"]["de"]
    assert _has(_errors(core), "report", "de")


def test_multi_line_definition_is_rejected() -> None:
    core = _core()
    core["classes"]["report"]["definition"] = "line one\nline two"
    assert _has(_errors(core), "report", "one line")


def test_unknown_key_is_rejected() -> None:
    core = _core()
    core["classes"]["report"]["brodaer"] = "document"
    assert _has(_errors(core), "report", "brodaer")


def test_bad_ids_and_version_are_rejected() -> None:
    core = _core()
    core["version"] = "1.2"
    core["classes"]["Bad Id"] = copy.deepcopy(core["classes"]["document"])
    errors = _errors(core)
    assert _has(errors, "version")
    assert _has(errors, "Bad Id")


def test_duplicate_id_across_modules_is_rejected() -> None:
    legal = _legal()
    legal["classes"]["report"] = copy.deepcopy(_core()["classes"]["report"])
    assert _has(_errors(_core(), legal), "report", "core", "legal-de")


def test_unsatisfied_requires_is_rejected() -> None:
    legal = _legal()
    legal["requires"] = ["core@^2"]
    assert _has(_errors(_core(), legal), "core@^2")
    assert _has(_errors(_legal()), "core@^1")  # required module not bound at all


def test_deprecation_needs_an_existing_replacement() -> None:
    core = _core()
    core["classes"]["report"]["deprecated"] = True
    assert _has(_errors(core), "report", "replaced_by")
    core["classes"]["report"]["replaced_by"] = "gone"
    assert _has(_errors(core), "report", "gone")


def test_relation_domain_must_exist() -> None:
    legal = _legal()
    legal["relations"]["based_on"]["domain"] = ["statute"]
    assert _has(_errors(_core(), legal), "based_on", "statute")


# --- YAML parsing and the per-DB binding ---------------------------------------


def test_parse_yaml_reports_duplicate_keys_and_syntax_errors() -> None:
    _, errors = ontology.parse_yaml("classes:\n  a: 1\n  a: 2\n")
    assert _has(errors, "duplicate", "a")
    _, errors = ontology.parse_yaml("key: [unclosed\n")
    assert errors
    data, errors = ontology.parse_yaml("id: core\n")
    assert (data, errors) == ({"id": "core"}, [])


def test_binding_selects_modules_and_adds_a_local_extension() -> None:
    binding = {
        "modules": ["core"],
        "local": {
            "classes": {
                "market-report": {
                    "broader": "report",
                    "labels": _labels("Market report", "Marktbericht"),
                    "definition": "Analyst report on a market",
                }
            }
        },
    }
    ids, local, errors = ontology.read_binding(binding, available={"core", "legal-de"})
    assert (ids, errors) == (["core"], [])
    assert local is not None
    schema, errors = ontology.build_schema([_core(), local])
    assert errors == []
    assert schema is not None
    assert schema.classes["market-report"].module == "local"


def test_binding_rejects_unknown_modules_and_keys() -> None:
    _, _, errors = ontology.read_binding({"modules": ["nope"], "extra": 1}, available={"core"})
    assert _has(errors, "nope")
    assert _has(errors, "extra")
    _, _, errors = ontology.read_binding(["core"], available={"core"})
    assert errors


# --- ledger rows and projection (report §4.3) ----------------------------------


def _row(n: int, pred: str, obj: Any, by: str = "rule", **kw: Any) -> dict[str, Any]:
    row = ontology.assertion("src:a.md", pred, obj, by=by, **kw)
    row["id"] = f"a-{n:06d}"
    return row


def _retract(n: int, target: dict[str, Any]) -> dict[str, Any]:
    row = ontology.retraction(target, by="user", reason="wrong")
    row["id"] = f"a-{n:06d}"
    return row


def _project(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return ontology.project(rows, multi={"based_on"}).get("src:a.md", {})


def test_projection_precedence_is_user_then_rule_then_llm() -> None:
    assert _project([_row(1, "class", "report"), _row(2, "class", "guidance", by="llm")]) == {
        "class": "report"
    }
    rows = [_row(1, "class", "report", by="user"), _row(2, "class", "guidance")]
    assert _project(rows) == {"class": "report"}
    assert _project([_row(1, "class", "report"), _row(2, "class", "guidance")]) == {
        "class": "guidance"
    }


def test_retraction_hides_a_row() -> None:
    llm = _row(1, "class", "report", by="llm")
    rule = _row(2, "class", "guidance")
    assert _project([llm, rule, _retract(3, rule)]) == {"class": "report"}


def test_user_null_unsets_and_blocks_lower_actors() -> None:
    rows = [_row(1, "class", "report"), _row(2, "class", None, by="user")]
    rows.append(_row(3, "class", "guidance"))
    assert _project(rows) == {}


def test_proposed_rows_are_not_projected() -> None:
    assert _project([_row(1, "class", "report", by="llm", status="proposed")]) == {}


def test_multi_valued_predicates_accumulate_and_user_negation_sticks() -> None:
    rows = [_row(1, "based_on", "work-b"), _row(2, "based_on", "work-a")]
    assert _project(rows) == {"based_on": ["work-a", "work-b"]}
    rows.append(_row(3, "based_on", "work-b", by="user", negated=True))
    rows.append(_row(4, "based_on", "work-b"))  # a later re-classify cannot bring it back
    assert _project(rows) == {"based_on": ["work-a"]}


def test_assertion_rejects_bad_input() -> None:
    with pytest.raises(ValueError, match="actor"):
        ontology.assertion("src:a.md", "class", "report", by="robot")
    with pytest.raises(ValueError, match="subject"):
        ontology.assertion("a.md", "class", "report", by="rule")
    with pytest.raises(ValueError, match="status"):
        ontology.assertion("src:a.md", "class", "report", by="rule", status="maybe")
