"""Ontology store: the only I/O for ontologies (shared modules, per-DB binding, ledger, history).

    ontology/*.yaml                           shared schema modules (git; read-only here)
    data/<DB>/ontology.yaml                   binding: bound modules + local extension
    data/<DB>/ontology/assertions.jsonl       fact ledger, append-only
    data/<DB>/ontology/changes.jsonl          one row per revision, append-only
    data/<DB>/ontology/history/<seq>-<hash>.yaml   full snapshot per revision

A DB without a binding has no ontology, and reading never creates files, so such a
DB behaves exactly as before. Content errors come back as messages, never as
exceptions (fail open). Every write of schema or facts goes through `apply()` (or,
for automatic writers, `record_change()`), which records a revision only when the
canonical content actually changed. Pure logic lives in `ontology` / `ontology_bundle`.
See docs/ontology.md.
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

import auth
import db_context
import dedup
import ontology
import ontology_bundle as bundle

MODULE_DIR = Path(__file__).resolve().parents[1] / "ontology"
HUMAN_VIA = ("create", "import", "editor", "restore", "review")
MAX_DIFF_ROWS = 200

_ROW_ID_RE = re.compile(r"^a-(\d+)$")
_BINDING_HEADER = (
    "# Ontology binding of this database. Written by Maintenance -> Ontology;\n"
    "# edit it through export/import so every change is validated and logged.\n"
)


class StaleRevisionError(RuntimeError):
    """The ontology changed after the plan was computed; re-run the preview."""


def binding_path() -> Path:
    return db_context.data_root() / "ontology.yaml"


def store_dir() -> Path:
    return db_context.data_root() / "ontology"


def ledger_path() -> Path:
    return store_dir() / "assertions.jsonl"


def changes_path() -> Path:
    return store_dir() / "changes.jsonl"


def history_dir() -> Path:
    return store_dir() / "history"


def exists() -> bool:
    """True when the active DB has an ontology (a binding file)."""
    return binding_path().is_file()


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


# --- schema ------------------------------------------------------------------------


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


def shared_modules() -> dict[str, Any]:
    """Parsed shared modules by id; unreadable ones are left out (`load` reports them)."""
    out: dict[str, Any] = {}
    for mid, path in available_modules().items():
        data, errors = _read_yaml(path)
        if not errors and isinstance(data, dict):
            out[mid] = data
    return out


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


# --- JSONL files ---------------------------------------------------------------------


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    """Every JSON object line of ``path``; [] when absent. Unreadable lines are skipped."""
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            value = json.loads(line) if line.strip() else None
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            rows.append(cast("dict[str, Any]", value))
    return rows


def _append_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    """Append rows durably (caller holds the lock)."""
    # A crash can leave a last line without its newline; never glue a row onto it.
    torn = path.is_file() and path.stat().st_size > 0 and not path.read_bytes().endswith(b"\n")
    with path.open("a", encoding="utf-8") as fh:
        if torn:
            fh.write("\n")
        fh.writelines(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in rows)
        fh.flush()
        os.fsync(fh.fileno())


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


@contextmanager
def _locked() -> Generator[None]:
    """Exclusive lock for store writes (several Streamlit sessions may write at once)."""
    store_dir().mkdir(parents=True, exist_ok=True)
    with (store_dir() / ".lock").open("w") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)


# --- fact ledger -------------------------------------------------------------------


def read_rows() -> list[dict[str, Any]]:
    """Every ledger row in order; [] without a ledger. Unreadable lines are skipped."""
    return [r for r in _read_jsonl(ledger_path()) if isinstance(r.get("id"), str)]


def _append_rows_unlocked(rows: list[dict[str, Any]]) -> list[str]:
    if not rows:
        return []
    seqs = [int(m[1]) for r in read_rows() if (m := _ROW_ID_RE.match(r["id"]))]
    start, now = max(seqs, default=0) + 1, _now()
    stamped = [
        {**row, "id": f"a-{start + i:06d}", "recorded_at": now} for i, row in enumerate(rows)
    ]
    _append_jsonl(ledger_path(), stamped)
    return [r["id"] for r in stamped]


def append_rows(rows: list[dict[str, Any]]) -> list[str]:
    """Append rows with fresh ids (`a-000001`, …) and one `recorded_at`; returns the ids."""
    if not rows:
        return []
    with _locked():
        return _append_rows_unlocked(rows)


def retract_subject(subject: str, *, by: str, reason: str, user: str | None = None) -> int:
    """Retract every live row about ``subject`` (e.g. a deleted source); returns the count."""
    live = [r for r in ontology.live_rows(read_rows()) if r.get("subject") == subject]
    append_rows([ontology.retraction(r, by=by, reason=reason, user=user) for r in live])
    return len(live)


def referenced_ids() -> set[str]:
    """Class and relation ids any ledger row ever used (retracted rows included)."""
    rows = read_rows()
    classes = {str(r.get("object")) for r in rows if r.get("predicate") == "class"}
    return classes | {str(r.get("predicate")) for r in rows}


# --- state and revisions -------------------------------------------------------------


def _binding_data() -> dict[str, Any]:
    if not exists():
        return {}
    data, _ = _read_yaml(binding_path())
    return cast("dict[str, Any]", data) if isinstance(data, dict) else {}


def _multi_valued(shared: dict[str, Any], binding: dict[str, Any]) -> set[str]:
    modules = [bundle.as_map(m) for m in (*shared.values(), binding.get("local"))]
    return {"aliases"} | {r for m in modules for r in bundle.as_map(m.get("relations"))}


def current_state() -> dict[str, Any]:
    """The editable state: the binding as written plus the ledger's projected facts."""
    binding = _binding_data()
    facts = ontology.project(read_rows(), _multi_valued(shared_modules(), binding))
    return {"schema": binding, "facts": bundle.facts_state(facts)}


def history() -> list[dict[str, Any]]:
    """Change rows, oldest first (one per revision)."""
    return [r for r in _read_jsonl(changes_path()) if isinstance(r.get("seq"), int)]


def last_change(human: bool) -> dict[str, Any] | None:
    """Newest change made by a person (create/import/editor/restore) or, with
    ``human=False``, by code (ingest, delete_source, …)."""
    for row in reversed(history()):
        if (row.get("via") in HUMAN_VIA) == human:
            return row
    return None


def current_revision() -> tuple[int, str]:
    """(last recorded revision number, hash of the current content)."""
    rows = history()
    return (rows[-1]["seq"] if rows else 0), bundle.revision_hash(current_state())


def _snapshot_path(pattern: str) -> Path | None:
    matches = sorted(history_dir().glob(pattern)) if history_dir().is_dir() else []
    return matches[-1] if matches else None


def snapshot_text(seq: int) -> str | None:
    """The exchange file of revision ``seq`` as it was recorded."""
    path = _snapshot_path(f"{seq:04d}-*.yaml")
    return path.read_text(encoding="utf-8") if path else None


def _snapshot_state(pattern: str) -> dict[str, Any] | None:
    path = _snapshot_path(pattern)
    if path is None:
        return None
    text = path.read_text(encoding="utf-8")
    state, _, _ = bundle.parse(text, db=db_context.get_active_db(), allow_other_db=True)
    return state


def export_text(user: str | None) -> str:
    """The current ontology as an exchange file, with the shared modules for reference."""
    state = current_state()
    seq, rev = current_revision()
    shared = shared_modules()
    modules = [str(m) for m in bundle.as_list(state["schema"].get("modules"))]
    reference = {m: shared[m] for m in modules if m in shared}
    return bundle.render(
        state,
        db=db_context.get_active_db(),
        revision=f"{seq}-{rev}",
        user=user,
        exported_at=_now(),
        reference=reference,
    )


# --- plans ---------------------------------------------------------------------------


def _plan(
    imported: object, base: object | None, resolutions: dict[str, str] | None
) -> bundle.ImportPlan:
    return bundle.plan_import(
        imported,
        base=base,
        current=current_state(),
        shared=shared_modules(),
        known_sources=set(dedup.list_sources()),
        referenced=referenced_ids(),
        resolutions=resolutions,
    )


def prepare_import(
    text: str, *, resolutions: dict[str, str] | None = None, allow_other_db: bool = False
) -> bundle.ImportPlan:
    """Parse, merge (3-way against the file's base revision) and validate an edited file."""
    state, base_label, errors = bundle.parse(
        text, db=db_context.get_active_db(), allow_other_db=allow_other_db
    )
    if state is None:
        return bundle.ImportPlan("error", errors=errors)
    base_hash = base_label.rpartition("-")[2] if base_label else ""
    base = _snapshot_state(f"*-{base_hash}.yaml") if base_hash else None
    return _plan(state, base, resolutions)


def prepare_state(state: dict[str, Any]) -> bundle.ImportPlan:
    """A plan that makes ``state`` the new content (create, restore, GUI editor)."""
    return _plan(state, current_state(), None)


def prepare_restore(seq: int) -> bundle.ImportPlan:
    state = _snapshot_state(f"{seq:04d}-*.yaml")
    if state is None:
        return bundle.ImportPlan("error", errors=[f"revision {seq} not found"])
    return prepare_state(state)


# --- writes --------------------------------------------------------------------------


def _write_binding(schema: dict[str, Any]) -> None:
    _atomic_write(binding_path(), _BINDING_HEADER + bundle.dump_yaml(schema))


def _record(
    via: str,
    user: str | None,
    before: dict[str, Any],
    file_name: str | None = None,
    file_sha: str | None = None,
) -> dict[str, Any] | None:
    """Snapshot + change row when the content hash moved; None otherwise (lock held)."""
    after = current_state()
    new_hash, old_hash = bundle.revision_hash(after), bundle.revision_hash(before)
    if new_hash == old_hash:
        return None
    rows = history()
    seq, now = (rows[-1]["seq"] if rows else 0) + 1, _now()
    db = db_context.get_active_db()
    snapshot = bundle.render(after, db=db, revision=f"{seq}-{new_hash}", user=user, exported_at=now)
    _atomic_write(history_dir() / f"{seq:04d}-{new_hash}.yaml", snapshot)
    row: dict[str, Any] = {
        "seq": seq,
        "hash": new_hash,
        "parent": f"{rows[-1]['seq']}-{old_hash}" if rows else None,
        "at": now,
        "user": user,
        "via": via,
        "file": file_name,
        "file_sha256": file_sha,
        "summary": bundle.summarize(before, after),
        "local_version": bundle.local_version(after),
        "diff": bundle.diff(before, after)[:MAX_DIFF_ROWS],
    }
    _append_jsonl(changes_path(), [row])
    return row


def apply(
    plan: bundle.ImportPlan,
    *,
    user: str,
    via: str,
    file_name: str | None = None,
    file_sha: str | None = None,
) -> dict[str, Any] | None:
    """Write a ready plan: binding (if the schema changed), user fact rows, snapshot and
    change row. Raises PermissionError for non-maintainers and StaleRevisionError when the
    ontology changed since the plan was computed."""
    if plan.status != "ready":
        raise ValueError(f"cannot apply a plan with status {plan.status!r}")
    if not auth.is_maintainer(user, db_context.get_active_db()):
        raise PermissionError(f"{user!r} does not maintain this database")
    with _locked():
        before = current_state()
        if bundle.revision_hash(before) != plan.current_hash:
            raise StaleRevisionError("the ontology changed since the preview; review it again")
        if bundle.canonical(before).get("schema") != bundle.canonical(plan.state).get("schema"):
            _write_binding(bundle.as_map(plan.state.get("schema")))
        seq = (history()[-1]["seq"] if history() else 0) + 1
        facts = bundle.fact_rows(
            before["facts"], plan.state.get("facts"), user=user, evidence=f"{via} rev {seq}"
        )
        _append_rows_unlocked(facts)
        return _record(via, user, before, file_name, file_sha)


def record_change(via: str, user: str | None = None) -> dict[str, Any] | None:
    """Record a revision for changes code made directly (ingest, delete_source, …);
    None without an ontology or when nothing changed since the last revision."""
    if not exists():
        return None
    with _locked():
        rows = history()
        before = _snapshot_state(f"{rows[-1]['seq']:04d}-*.yaml") if rows else None
        return _record(via, user, before or {"schema": {}, "facts": {}})


# --- per-source facts and proposals (plan Phase 3) --------------------------------------


def source_facts(source: str) -> dict[str, Any]:
    """Current confirmed facts about one raw source ({} without an ontology)."""
    if not exists():
        return {}
    multi = _multi_valued(shared_modules(), _binding_data())
    return ontology.project(read_rows(), multi).get(f"src:{source}", {})


def proposals() -> list[dict[str, Any]]:
    """Live `proposed` rows (e.g. an LLM class with its verified quote), oldest first."""
    return [r for r in ontology.live_rows(read_rows()) if r.get("status") == "proposed"]


def decide_proposal(row_id: str, *, accept: bool, user: str) -> dict[str, Any] | None:
    """Confirm (as a `user` fact) or reject a proposal; either way it is withdrawn.
    Returns the revision a confirmation records (None for a rejection)."""
    if not auth.is_maintainer(user, db_context.get_active_db()):
        raise PermissionError(f"{user!r} does not maintain this database")
    with _locked():
        row = next((r for r in proposals() if r["id"] == row_id), None)
        if row is None:
            raise KeyError(row_id)
        before = current_state()
        reason = "confirmed" if accept else "rejected"
        rows = [ontology.retraction(row, by="user", reason=reason, user=user)]
        if accept:
            rows.insert(
                0,
                ontology.assertion(
                    row["subject"],
                    row["predicate"],
                    row["object"],
                    by="user",
                    user=user,
                    evidence=str(row.get("evidence") or ""),
                    negated=bool(row.get("negated")),
                ),
            )
        _append_rows_unlocked(rows)
        return _record("review", user, before)
