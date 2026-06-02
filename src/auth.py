"""Local user store with bcrypt password hashes.

Schema (`data/users.json`):
    {
      "users": {
        "<username>": {"pw_hash": "...", "dbs": ["..."], "is_admin": bool,
                        "maintains": ["..."]}
      }
    }

`dbs` is the read-access allowlist; `maintains` is the subset of those DBs the
user may *change* (upload new sources / delete data). Maintainer rights are
explicit per DB — being an admin does not imply maintaining any DB.

On first import the file is seeded with the default admin
(`T. Hein` / `k-wiki`, allow-listed for the `Strahlenschutz` DB).
"""

from __future__ import annotations

import json
from pathlib import Path

import bcrypt

import db_context

DEFAULT_USER = "T. Hein"
DEFAULT_PASSWORD = "k-wiki"


def _path() -> Path:
    return db_context.users_json_path()


def _load() -> dict:
    p = _path()
    if not p.exists():
        return {"users": {}}
    try:
        return json.loads(p.read_text())
    except Exception:
        return {"users": {}}


def _save(data: dict) -> None:
    p = _path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2, ensure_ascii=False))


def _hash(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def ensure_seeded() -> None:
    """Create users.json with the default admin if it doesn't exist."""
    p = _path()
    if p.exists():
        return
    _save({
        "users": {
            DEFAULT_USER: {
                "pw_hash": _hash(DEFAULT_PASSWORD),
                "dbs": [db_context.DEFAULT_DB],
                "is_admin": True,
                "maintains": [db_context.DEFAULT_DB],
            }
        }
    })


def backfill_maintainers() -> None:
    """One-time migration: grant existing admins maintainer rights on their DBs.

    Users created before the maintainer layer have no ``maintains`` key. Admins
    get backfilled to maintain the DBs they already access so they keep upload
    rights; non-admins stay read-only until explicitly assigned. Idempotent.
    """
    data = _load()
    changed = False
    for meta in data.get("users", {}).values():
        if "maintains" not in meta:
            meta["maintains"] = list(meta.get("dbs", [])) if meta.get("is_admin") else []
            changed = True
    if changed:
        _save(data)


def list_users() -> list[dict]:
    data = _load()
    return [
        {
            "username": u,
            "dbs": list(meta.get("dbs", [])),
            "is_admin": bool(meta.get("is_admin", False)),
            "maintains": list(meta.get("maintains", [])),
        }
        for u, meta in sorted(data.get("users", {}).items())
    ]


def verify(username: str, password: str) -> bool:
    data = _load()
    user = data.get("users", {}).get(username)
    if not user:
        return False
    try:
        return bcrypt.checkpw(password.encode("utf-8"), user["pw_hash"].encode("utf-8"))
    except Exception:
        return False


def user_dbs(username: str) -> list[str]:
    data = _load()
    return list(data.get("users", {}).get(username, {}).get("dbs", []))


def is_admin(username: str) -> bool:
    data = _load()
    return bool(data.get("users", {}).get(username, {}).get("is_admin", False))


def user_maintains(username: str) -> list[str]:
    data = _load()
    return list(data.get("users", {}).get(username, {}).get("maintains", []))


def is_maintainer(username: str, db: str) -> bool:
    return db in user_maintains(username)


def add_user(
    username: str,
    password: str,
    dbs: list[str],
    is_admin: bool = False,
    maintains: list[str] | None = None,
) -> None:
    if not username or not password:
        raise ValueError("username and password required")
    data = _load()
    if username in data.get("users", {}):
        raise ValueError(f"User {username!r} already exists")
    data.setdefault("users", {})[username] = {
        "pw_hash": _hash(password),
        "dbs": list(dbs),
        "is_admin": bool(is_admin),
        "maintains": list(maintains or []),
    }
    _save(data)


def delete_user(username: str) -> bool:
    data = _load()
    if username not in data.get("users", {}):
        return False
    del data["users"][username]
    _save(data)
    return True


def set_user_dbs(username: str, dbs: list[str]) -> None:
    data = _load()
    if username not in data.get("users", {}):
        raise ValueError(f"Unknown user: {username!r}")
    data["users"][username]["dbs"] = list(dbs)
    _save(data)


def set_user_maintains(username: str, dbs: list[str]) -> None:
    data = _load()
    if username not in data.get("users", {}):
        raise ValueError(f"Unknown user: {username!r}")
    data["users"][username]["maintains"] = list(dbs)
    _save(data)


def grant_maintainer(username: str, db: str) -> None:
    """Grant access to and maintainer rights on ``db`` in one write.

    A maintainer must also be able to read the DB, so ``db`` is added to both
    ``dbs`` and ``maintains``.
    """
    data = _load()
    user = data.get("users", {}).get(username)
    if user is None:
        raise ValueError(f"Unknown user: {username!r}")
    user["dbs"] = sorted(set(user.get("dbs", [])) | {db})
    user["maintains"] = sorted(set(user.get("maintains", [])) | {db})
    _save(data)


def change_password(username: str, new_password: str) -> None:
    data = _load()
    if username not in data.get("users", {}):
        raise ValueError(f"Unknown user: {username!r}")
    data["users"][username]["pw_hash"] = _hash(new_password)
    _save(data)
