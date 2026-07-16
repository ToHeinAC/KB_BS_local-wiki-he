"""Active-database context + per-call path resolution.

All data-path modules call the getters here instead of capturing
`Path(os.getenv(...))` at import time. The active database name is held
in a ContextVar so each Streamlit session / agent run resolves paths
against its own DB without threading an extra argument through every
function. Each DB owns an isolated `data/<db>/{raw,chunks,index,wiki}`
subtree.

**Active DB vs search scope.** The active DB is the single *write* target
(upload, ingest, filing an answer) and stays single-valued. The search scope
is a separate list of DBs that read-only retrieval fans out over (Wiki Chat's
"Search in" multiselect). It defaults to the active DB alone, so every
single-DB caller behaves exactly as before.

Fan-out pattern — bind one DB at a time, never merge path state:

    for db in search_scope():
        with using_db(db):
            ...                     # every path getter now resolves to `db`

Cross-DB result identity goes through `qualify()` / `split_ref()`. Names are
only prefixed (`Investing::foo.md`) when the scope holds more than one DB, so
single-DB citations, prompts, and run-memory keys stay byte-identical.
"""

from __future__ import annotations

import os
import re
import shutil
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

DEFAULT_DB = "Strahlenschutz"
DATA_ROOT = Path(os.getenv("DATA_ROOT", "data"))

#: Separator for DB-qualified refs. Not "/" — wiki pages already use that for
#: the `insights/` subpath — and not a character `_SAFE_NAME_RE` admits.
SCOPE_SEP = "::"

_active: ContextVar[str] = ContextVar("active_db", default=DEFAULT_DB)
_scope: ContextVar[tuple[str, ...]] = ContextVar("search_scope", default=())
_SAFE_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_\- ]{0,40}$")


def set_active_db(name: str) -> None:
    if not name:
        return
    _active.set(name)


def get_active_db() -> str:
    return _active.get()


@contextmanager
def using_db(name: str):
    """Bind `name` as the active DB for the duration of the block."""
    token = _active.set(name)
    try:
        yield
    finally:
        _active.reset(token)


def set_search_scope(names) -> None:
    """Set the DBs that read-only retrieval fans out over. Empty = follow active."""
    _scope.set(tuple(dict.fromkeys(n for n in (names or []) if n)))


def search_scope() -> tuple[str, ...]:
    """DBs to search, always non-empty. Falls back to the active DB alone."""
    return _scope.get() or (get_active_db(),)


def is_multi_scope() -> bool:
    return len(search_scope()) > 1


def qualify(name: str, db: str | None = None) -> str:
    """DB-qualify a filename when the scope spans several DBs, else return it as-is.

    Page names collide across DBs (every DB has an `index.md`), so a cross-DB
    result set has to carry its origin. Single-DB scope stays unprefixed.
    """
    if not name or not is_multi_scope():
        return name
    return f"{db or get_active_db()}{SCOPE_SEP}{name}"


def split_ref(ref: str) -> tuple[str, str]:
    """Split a possibly DB-qualified ref into (db, name).

    Unknown or absent prefixes resolve to the active DB, so a model that drops
    or invents a prefix still reads from a real DB instead of erroring.
    """
    ref = (ref or "").strip()
    if SCOPE_SEP in ref:
        head, _, tail = ref.partition(SCOPE_SEP)
        head, tail = head.strip(), tail.strip()
        if tail and head in search_scope():
            return head, tail
    return get_active_db(), ref


def data_root() -> Path:
    return DATA_ROOT / get_active_db()


def wiki_dir() -> Path:
    return data_root() / "wiki"


def raw_dir() -> Path:
    return data_root() / "raw"


def chunks_dir() -> Path:
    return data_root() / "chunks"


def index_dir() -> Path:
    return data_root() / "index"


def users_json_path() -> Path:
    return DATA_ROOT / "users.json"


def is_valid_db_name(name: str) -> bool:
    return bool(_SAFE_NAME_RE.match(name or ""))


def list_dbs() -> list[str]:
    if not DATA_ROOT.exists():
        return []
    out: list[str] = []
    for p in sorted(DATA_ROOT.iterdir()):
        if p.is_dir() and (p / "raw").exists():
            out.append(p.name)
    return out


def create_db(name: str) -> Path:
    if not is_valid_db_name(name):
        raise ValueError(f"Invalid database name: {name!r}")
    root = DATA_ROOT / name
    for sub in ("raw", "chunks", "index", "wiki"):
        (root / sub).mkdir(parents=True, exist_ok=True)
    return root


def migrate_legacy_layout() -> bool:
    """Move pre-multi-DB data into `data/<DEFAULT_DB>/`. Idempotent.

    Triggered when any of `data/{raw,chunks,index,wiki}` exists at the top
    level and the default DB does not yet contain that subdir.
    """
    legacy_subs = ("raw", "chunks", "index", "wiki")
    target = DATA_ROOT / DEFAULT_DB
    moved = False
    for sub in legacy_subs:
        legacy = DATA_ROOT / sub
        dest = target / sub
        if legacy.exists() and not dest.exists():
            target.mkdir(parents=True, exist_ok=True)
            shutil.move(str(legacy), str(dest))
            moved = True
    return moved
