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

**Classification gate.** Each DB has one shard per classification level
(`KI`, `KI@confidential`, `KI@strict`; see `classification`). The "active DB"
and every scope entry are shard ids. `require()` checks a shard against the
clearance ContextVar and runs in `data_root()` — which every path getter goes
through — and whenever a shard is bound. Unsealed (tests, scripts) the
clearance grants level 0 of every DB; the app seals the user's grants on every
rerun, which also limits it to the user's DBs. Worker threads start unsealed,
so they only reach normal shards unless `bind_context` carries the grants in.
"""

from __future__ import annotations

import os
import re
import shutil
from collections.abc import Callable, Generator, Iterable, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from types import MappingProxyType
from typing import ParamSpec, TypeVar

from dotenv import load_dotenv

import classification

load_dotenv()

DEFAULT_DB = "Strahlenschutz"
DATA_ROOT = Path(os.getenv("DATA_ROOT", "data"))

#: Separator for DB-qualified refs. Not "/" — wiki pages already use that for
#: the `insights/` subpath — and not a character `_SAFE_NAME_RE` admits.
SCOPE_SEP = "::"

_active: ContextVar[str] = ContextVar("active_db", default=DEFAULT_DB)
_scope: ContextVar[tuple[str, ...]] = ContextVar("search_scope", default=())
#: None = unsealed (level 0 of every DB); a mapping = exactly these DBs up to these levels.
_clearance: ContextVar[Mapping[str, int] | None] = ContextVar("clearance", default=None)
_LEVELS_DIR = "_levels"
_P = ParamSpec("_P")
_R = TypeVar("_R")
_SAFE_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_\- ]{0,40}$")


class AccessDenied(PermissionError):
    """A path or shard the caller may not reach. Readers report it as "not found"."""


def _granted_level(db: str) -> int | None:
    grants = _clearance.get()
    if grants is None:
        return 0
    return grants.get(db)


def require(shard: str) -> None:
    """Raise AccessDenied unless the current clearance reaches `shard`."""
    try:
        db, level = classification.parse_shard(shard)
    except ValueError:
        raise AccessDenied(shard) from None
    granted = _granted_level(db)
    if granted is None or level > granted:
        raise AccessDenied(shard)


def seal_clearance(grants: Mapping[str, int]) -> None:
    """Fix the session's grants (DB -> highest level). The app calls this every rerun."""
    _clearance.set(MappingProxyType(dict(grants)))


@contextmanager
def clearance(grants: Mapping[str, int]) -> Generator[None]:
    """Grant `grants` for the block only (tests, scripts, maintenance jobs)."""
    token = _clearance.set(MappingProxyType(dict(grants)))
    try:
        yield
    finally:
        _clearance.reset(token)


def bind_context(fn: Callable[_P, _R]) -> Callable[_P, _R]:
    """Wrap `fn` so a ThreadPoolExecutor worker re-applies the caller's context.

    Worker threads don't inherit the caller's ContextVars, so clearance, active
    DB and search scope would reset to their defaults inside the pool. They are
    captured here and re-set at the start of each call — clearance first, since
    binding the DB and scope is checked against it. `copy_context().run` can't
    be used: one Context object can't be entered by several workers at once.
    """
    grants = _clearance.get()
    db = get_active_db()
    scope = search_scope()

    def _wrapped(*args: _P.args, **kwargs: _P.kwargs) -> _R:
        _clearance.set(grants)
        set_active_db(db)
        set_search_scope(scope)
        return fn(*args, **kwargs)

    return _wrapped


def set_active_db(name: str) -> None:
    if not name:
        return
    require(name)
    _active.set(name)


def get_active_db() -> str:
    return _active.get()


@contextmanager
def using_db(name: str):
    """Bind `name` as the active DB for the duration of the block."""
    require(name)
    token = _active.set(name)
    try:
        yield
    finally:
        _active.reset(token)


def set_search_scope(names: Iterable[str | None] | None) -> None:
    """Set the DBs that read-only retrieval fans out over. Empty = follow active."""
    scope = tuple(dict.fromkeys(n for n in (names or []) if n))
    for name in scope:
        require(name)
    _scope.set(scope)


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


def confine(base: Path, name: str) -> Path:
    """Resolve `name` inside `base`, refusing anything that lands outside it.

    Page and raw names reach the readers from LLM output, so `../` segments and
    absolute paths are hostile input, not typos.
    """
    root = base.resolve()
    path = (root / name).resolve()
    if not name or path == root or not path.is_relative_to(root):
        raise AccessDenied(name)
    return path


def shard_path(shard: str) -> Path:
    """Directory of a shard: `data/<db>/` for normal, `data/<db>/_levels/<level>/` above."""
    db, level = classification.parse_shard(shard)
    root = DATA_ROOT / db
    return root if level == 0 else root / _LEVELS_DIR / classification.LEVELS[level]


def data_root() -> Path:
    shard = get_active_db()
    require(shard)
    return shard_path(shard)


def base_db() -> str:
    """The active DB without its level — for maintainer checks, tags and prompts."""
    return classification.parse_shard(get_active_db())[0]


def level() -> int:
    return classification.parse_shard(get_active_db())[1]


def reachable_shards(db: str) -> tuple[str, ...]:
    """The shards of `db` the clearance reaches: normal, plus existing higher levels."""
    granted = _granted_level(db)
    if granted is None:
        return ()
    higher = (classification.shard_id(db, lvl) for lvl in range(1, granted + 1))
    return (db, *(s for s in higher if (shard_path(s) / "raw").exists()))


def write_target(db: str, read_shards: Iterable[str]) -> str:
    """Shard of `db` at the high-water mark of what was read; AccessDenied if unreachable."""
    shard = classification.shard_id(db, classification.high_water(read_shards))
    require(shard)
    return shard


def ensure_shard(shard: str) -> Path:
    """Create a shard's store (raw, chunks, index, wiki) and return its root."""
    require(shard)
    root = shard_path(shard)
    for sub in ("raw", "chunks", "index", "wiki"):
        (root / sub).mkdir(parents=True, exist_ok=True)
    return root


def ontology_binding_path() -> Path:
    """`ontology.yaml` is per DB, shared by every level (config, not content)."""
    require(get_active_db())
    return shard_path(base_db()) / "ontology.yaml"


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
