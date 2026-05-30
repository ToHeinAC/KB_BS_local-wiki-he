"""Active-database context + per-call path resolution.

All data-path modules call the getters here instead of capturing
`Path(os.getenv(...))` at import time. The active database name is held
in a ContextVar so each Streamlit session / agent run resolves paths
against its own DB without threading an extra argument through every
function. Each DB owns an isolated `data/<db>/{raw,chunks,index,wiki}`
subtree.
"""

from __future__ import annotations

import os
import re
import shutil
from contextvars import ContextVar
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

DEFAULT_DB = "Strahlenschutz"
DATA_ROOT = Path(os.getenv("DATA_ROOT", "data"))

_active: ContextVar[str] = ContextVar("active_db", default=DEFAULT_DB)
_SAFE_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_\- ]{0,40}$")


def set_active_db(name: str) -> None:
    if not name:
        return
    _active.set(name)


def get_active_db() -> str:
    return _active.get()


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
