"""Ontology store: the only I/O for ontologies (shared modules, per-DB binding, fact ledger).

    ontology/*.yaml                        shared schema modules (git; read-only here)
    data/<DB>/ontology.yaml                binding: bound modules + local extension
    data/<DB>/ontology/assertions.jsonl    fact ledger, append-only

A DB without a binding has no ontology, and reading never creates files, so such a
DB behaves exactly as before. Content errors come back as messages, never as
exceptions (fail open). Validation and projection are pure, in `ontology`.
See docs/_plan-ontology.md §3.1.
"""

from __future__ import annotations

import fcntl
import json
import os
import re
from collections.abc import Generator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import db_context
import ontology

MODULE_DIR = Path(__file__).resolve().parents[1] / "ontology"

_ROW_ID_RE = re.compile(r"^a-(\d+)$")


def binding_path() -> Path:
    return db_context.data_root() / "ontology.yaml"


def store_dir() -> Path:
    return db_context.data_root() / "ontology"


def ledger_path() -> Path:
    return store_dir() / "assertions.jsonl"


def exists() -> bool:
    """True when the active DB has an ontology (a binding file)."""
    return binding_path().is_file()


def available_modules() -> dict[str, Path]:
    """Shared modules by id (the file stem)."""
    if not MODULE_DIR.is_dir():
        return {}
    return {p.stem: p for p in sorted(MODULE_DIR.glob("*.yaml"))}


def _read_yaml(path: Path) -> tuple[Any, list[str]]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        return None, [f"{path.name}: {exc}"]
    data, errors = ontology.parse_yaml(text)
    return data, [f"{path.name}: {e}" for e in errors]


def _read_modules(ids: list[str], available: dict[str, Path]) -> tuple[list[Any], list[str]]:
    modules: list[Any] = []
    errors: list[str] = []
    for mid in ids:
        data, errs = _read_yaml(available[mid])
        declared = cast("dict[str, Any]", data).get("id") if isinstance(data, dict) else None
        if not errs and declared != mid:
            errs = [f"{mid}.yaml: declares id {declared!r}, expected {mid!r}"]
        errors += errs
        modules.append(data)
    return modules, errors


def load() -> tuple[ontology.Schema | None, list[str]]:
    """The active DB's validated schema: (None, []) without an ontology, (None, errors) when
    the binding or a module is broken."""
    if not exists():
        return None, []
    data, errors = _read_yaml(binding_path())
    if errors:
        return None, errors
    available = available_modules()
    ids, local, errors = ontology.read_binding(data, set(available))
    if errors:
        return None, errors
    modules, errors = _read_modules(ids, available)
    if errors:
        return None, errors
    return ontology.build_schema(modules + ([local] if local else []))


# --- fact ledger -------------------------------------------------------------------


def _parse_row(line: str) -> dict[str, Any] | None:
    try:
        value = json.loads(line)
    except json.JSONDecodeError:
        return None
    if not isinstance(value, dict):
        return None
    row = cast("dict[str, Any]", value)
    return row if isinstance(row.get("id"), str) else None


def read_rows() -> list[dict[str, Any]]:
    """Every ledger row in order; [] without a ledger. Unreadable lines are skipped."""
    path = ledger_path()
    if not path.is_file():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()
    return [row for line in lines if line.strip() and (row := _parse_row(line)) is not None]


def _next_seq(rows: list[dict[str, Any]]) -> int:
    seqs = [int(m[1]) for r in rows if (m := _ROW_ID_RE.match(r["id"]))]
    return max(seqs, default=0) + 1


@contextmanager
def _locked() -> Generator[None]:
    """Exclusive lock for ledger writes (several Streamlit sessions may write at once)."""
    store_dir().mkdir(parents=True, exist_ok=True)
    with (store_dir() / ".lock").open("w") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)


def append_rows(rows: list[dict[str, Any]]) -> list[str]:
    """Append rows with fresh ids (`a-000001`, …) and one `recorded_at`; returns the ids."""
    if not rows:
        return []
    with _locked():
        path = ledger_path()
        start = _next_seq(read_rows())
        now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        stamped = [
            {**row, "id": f"a-{start + i:06d}", "recorded_at": now} for i, row in enumerate(rows)
        ]
        # A crash can leave a last line without its newline; never glue a row onto it.
        torn = path.is_file() and path.stat().st_size > 0 and not path.read_bytes().endswith(b"\n")
        with path.open("a", encoding="utf-8") as fh:
            if torn:
                fh.write("\n")
            fh.writelines(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in stamped)
            fh.flush()
            os.fsync(fh.fileno())
    return [r["id"] for r in stamped]


def retract_subject(subject: str, *, by: str, reason: str, user: str | None = None) -> int:
    """Retract every live row about ``subject`` (e.g. a deleted source); returns the count."""
    live = [r for r in ontology.live_rows(read_rows()) if r.get("subject") == subject]
    append_rows([ontology.retraction(r, by=by, reason=reason, user=user) for r in live])
    return len(live)
