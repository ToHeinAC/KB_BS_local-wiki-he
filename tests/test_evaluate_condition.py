"""Characterization tests for tools._evaluate_condition_impl (deterministic evaluator)."""

import pytest

import tools

FACTS = {"dose": 1.5, "unit": "mSv", "area": "Kontrollbereich", "tags": "a,b"}


def _result(condition, facts=FACTS):
    return tools._evaluate_condition_impl(facts, condition)


@pytest.mark.parametrize(
    ("condition", "verdict", "trace"),
    [
        ({"op": ">", "fact": "dose", "value": 1}, "PASS", "[TRUE ] dose > 1  (= 1.5)"),
        ({"op": "<=", "fact": "dose", "value": 1}, "FAIL", "[FALSE] dose <= 1  (= 1.5)"),
        ({"op": "==", "fact": "unit", "value": "mSv"}, "PASS", "unit == 'mSv'  (= 'mSv')"),
        ({"op": "in", "fact": "unit", "value": ["mSv", "Sv"]}, "PASS", "unit in ['mSv', 'Sv']"),
        ({"op": "contains", "fact": "area", "value": "Kontroll"}, "PASS", "area contains"),
        (
            {"op": "between", "fact": "dose", "low": 1, "high": 2},
            "PASS",
            "dose between 1 and 2  (= 1.5)",
        ),
    ],
)
def test_leaf_operators(condition, verdict, trace):
    out = _result(condition)
    assert out.endswith(f"## Result: {verdict}")
    assert trace in out


def test_boolean_combinators_trace_children_then_parent():
    cond = {
        "op": "and",
        "args": [
            {"op": ">", "fact": "dose", "value": 1},
            {"op": "not", "arg": {"op": "==", "fact": "unit", "value": "Sv"}},
        ],
    }
    out = _result(cond)
    assert out.endswith("## Result: PASS")
    lines = [ln.strip() for ln in out.splitlines() if ln.strip().startswith("[")]
    assert lines == [
        "[TRUE ] dose > 1  (= 1.5)",
        "[FALSE] unit == 'Sv'  (= 'mSv')",
        "[TRUE ] NOT  → True",
        "[TRUE ] AND  → True",
    ]


def test_or_is_true_when_any_child_is():
    cond = {
        "op": "or",
        "args": [
            {"op": "<", "fact": "dose", "value": 1},
            {"op": "!=", "fact": "unit", "value": "Sv"},
        ],
    }
    assert _result(cond).endswith("## Result: PASS")


@pytest.mark.parametrize(
    ("condition", "message"),
    [
        ({"op": ">", "fact": "missing", "value": 1}, "Error: missing fact 'missing'"),
        ({"op": ">", "fact": "unit", "value": 1}, "Error: type mismatch in op '>'"),
        ({"op": "in", "fact": "dose", "value": 3}, "Error: type mismatch in op 'in'"),
        ({"op": "xor", "fact": "dose"}, "Error: unknown op 'xor'"),
        ({"op": "and", "args": ["not-a-node"]}, "Error: condition node not a dict: 'not-a-node'"),
    ],
)
def test_errors_fail_closed(condition, message):
    out = _result(condition)
    assert out.endswith("## Result: FAIL")
    assert message in out


@pytest.mark.parametrize(
    ("facts", "condition", "message"),
    [
        ({}, {"op": ">"}, "Error: `facts` must be a non-empty dict."),
        ("x", {"op": ">"}, "Error: `facts` must be a non-empty dict."),
        (FACTS, {}, "Error: `condition` must be a non-empty dict."),
        (FACTS, [1], "Error: `condition` must be a non-empty dict."),
    ],
)
def test_invalid_inputs(facts, condition, message):
    assert tools._evaluate_condition_impl(facts, condition) == message


def test_facts_are_listed():
    out = _result({"op": ">", "fact": "dose", "value": 1})
    assert out.startswith("## Facts\n\n  dose = 1.5\n  unit = 'mSv'")
