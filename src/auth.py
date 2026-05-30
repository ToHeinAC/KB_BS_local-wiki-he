"""Local user store with bcrypt password hashes.

Schema (`data/users.json`):
    {
      "users": {
        "<username>": {"pw_hash": "...", "dbs": ["..."], "is_admin": bool}
      }
    }

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
            }
        }
    })


def list_users() -> list[dict]:
    data = _load()
    return [
        {"username": u, "dbs": list(meta.get("dbs", [])), "is_admin": bool(meta.get("is_admin", False))}
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


def add_user(username: str, password: str, dbs: list[str], is_admin: bool = False) -> None:
    if not username or not password:
        raise ValueError("username and password required")
    data = _load()
    if username in data.get("users", {}):
        raise ValueError(f"User {username!r} already exists")
    data.setdefault("users", {})[username] = {
        "pw_hash": _hash(password),
        "dbs": list(dbs),
        "is_admin": bool(is_admin),
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


def change_password(username: str, new_password: str) -> None:
    data = _load()
    if username not in data.get("users", {}):
        raise ValueError(f"Unknown user: {username!r}")
    data["users"][username]["pw_hash"] = _hash(new_password)
    _save(data)
