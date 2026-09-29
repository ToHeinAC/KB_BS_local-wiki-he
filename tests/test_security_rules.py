"""Enforces the classification gate (docs/security.md): no data path bypasses db_context.

`data_root()` and the path getters are gated; `DATA_ROOT` and `shard_path` are not,
so product code outside `db_context` must never touch them, nor the gate's private
state. Only the app seals a session's clearance; elevation is for tests and scripts.
"""

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
VENDOR = SRC / "vendor"
GATE_MODULE = "db_context.py"
UNGATED = {"DATA_ROOT", "shard_path", "_active", "_scope", "_clearance", "_granted_level"}
ONLY_IN = {"seal_clearance": {"app.py"}, "clearance": set[str]()}


def violations(source: str, module: str) -> list[str]:
    """'line: attr' for every forbidden `db_context.<attr>` use in ``source``."""
    if module == GATE_MODULE:
        return []
    found: list[tuple[int, str]] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.ImportFrom) and node.module == "db_context":
            found += [(node.lineno, f"import {a.name}") for a in node.names]
        if not (isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name)):
            continue
        if node.value.id != "db_context":
            continue
        allowed = ONLY_IN.get(node.attr)
        if node.attr in UNGATED or (allowed is not None and module not in allowed):
            found.append((node.lineno, node.attr))
    return [f"{line}: {what}" for line, what in sorted(found)]


def test_detects_ungated_data_root_use() -> None:
    src = "import db_context\np = db_context.DATA_ROOT / 'KI'\n"
    assert violations(src, "x.py") == ["2: DATA_ROOT"]


def test_detects_private_gate_state_and_ungated_shard_paths() -> None:
    src = "db_context._clearance.set(None)\ndb_context.shard_path('KI@strict')\n"
    assert violations(src, "x.py") == ["1: _clearance", "2: shard_path"]


def test_detects_from_imports_that_would_hide_the_module_name() -> None:
    assert violations("from db_context import DATA_ROOT\n", "x.py") == ["1: import DATA_ROOT"]


def test_sealing_is_reserved_for_the_app_and_elevation_for_tests() -> None:
    seal = "db_context.seal_clearance({})\n"
    assert violations(seal, "wiki_engine.py") == ["1: seal_clearance"]
    assert violations(seal, "app.py") == []
    assert violations("with db_context.clearance({}):\n    pass\n", "app.py") == ["1: clearance"]


def test_gated_accessors_are_allowed_everywhere() -> None:
    src = "db_context.data_root()\ndb_context.wiki_dir()\ndb_context.require('KI')\n"
    assert violations(src, "x.py") == []
    assert violations("db_context.DATA_ROOT\n", GATE_MODULE) == []


def test_repo_src_never_bypasses_the_gate() -> None:
    files = [p for p in SRC.rglob("*.py") if VENDOR not in p.parents]
    offenders = {
        str(p.relative_to(ROOT)): found
        for p in files
        if (found := violations(p.read_text(encoding="utf-8"), p.name))
    }
    assert offenders == {}
