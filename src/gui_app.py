"""Broadsheet frontend (NiceGUI) entry point, selected by `FRONTEND=broadsheet`.

The Streamlit app (`src/app.py`) stays the default skin's home; this module serves the same
backend through a second GUI. Pages register through `register()` so tests can rebuild them
per NiceGUI app instance. Start it through `scripts/run_app.py`. Design: docs/ui.md.
"""

import argparse
import os
import secrets
from pathlib import Path
from typing import Any, cast

from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI
from nicegui import app, ui

import audit  # noqa: F401  # pyright: ignore[reportUnusedImport] (registers the denial listener)
import auth
import db_context

MOUNT_PATH = "/wiwi"
DEFAULT_PORT = 8520
_CSS = Path(__file__).parent / "assets" / "broadsheet" / "broadsheet.css"


def _bootstrap() -> None:
    """Same one-time setup the Streamlit app does at import."""
    db_context.migrate_legacy_layout()
    auth.ensure_seeded()
    auth.backfill_maintainers()


def _signed_in() -> bool:
    storage = cast(dict[str, Any], app.storage.user)  # pyright: ignore[reportUnknownMemberType]
    return bool(storage.get("user"))


def _login_page() -> None:
    with ui.column().classes("items-center w-full").style("margin-top: 12vh"):
        ui.label("LocalWiki").classes("plate")
        ui.input("Username").props("outlined dense").classes("w-72")
        ui.input("Password", password=True).props("outlined dense").classes("w-72")
        ui.button("Sign in").props("flat")


def _home_page() -> None:
    if not _signed_in():
        ui.navigate.to("/login")
        return
    ui.label("LocalWiki").classes("plate")


def register() -> None:
    """Register every page route on the current NiceGUI app."""
    if _CSS.exists():
        ui.add_css(_CSS.read_text(encoding="utf-8"), shared=True)
    ui.page("/login")(_login_page)
    ui.page("/")(_home_page)


def _serve(port: int) -> None:
    import uvicorn

    _bootstrap()
    api = FastAPI()
    register()
    secret = os.getenv("GUI_STORAGE_SECRET") or secrets.token_urlsafe(32)
    ui.run_with(api, mount_path=MOUNT_PATH, storage_secret=secret)  # pyright: ignore[reportUnknownMemberType]
    uvicorn.run(api, host="0.0.0.0", port=port, log_level="warning")


def main() -> None:
    parser = argparse.ArgumentParser(description="LocalWiki Broadsheet GUI")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    _serve(parser.parse_args().port)


if __name__ == "__main__":
    main()
