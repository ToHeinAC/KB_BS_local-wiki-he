"""Broadsheet frontend (NiceGUI) entry point, selected by `FRONTEND=broadsheet`.

The Streamlit app (`src/app.py`) stays the default skin's home; this module serves the same
backend through a second GUI. Pages register through `register()` so tests can rebuild them
per NiceGUI app instance. Start it through `scripts/run_app.py`. Design: docs/ui.md.
"""

import argparse
import os
import secrets
from collections.abc import Callable
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI
from nicegui import ui

import audit  # noqa: F401  # pyright: ignore[reportUnusedImport] (registers the denial listener)
import auth
import db_context
import gpu_widget
import gui_chat
import gui_chrome
import gui_explorer
import gui_graph
import gui_research
import gui_session

# Hovering a citation numeral lights its margin note and the other way round (docs/ui.md).
CITE_JS = """<script>
document.addEventListener('mouseover', (e) => {
  const hit = e.target.closest('sup.cite, .note[data-n]');
  document.querySelectorAll('.hl').forEach((x) => x.classList.remove('hl'));
  if (!hit) return;
  const n = hit.dataset.n;
  document.querySelectorAll(`sup.cite[data-n="${n}"], .note[data-n="${n}"]`)
    .forEach((x) => x.classList.add('hl'));
});
</script>"""
MOUNT_PATH = "/wiwi"
DEFAULT_PORT = 8520
_CSS = Path(__file__).parent / "assets" / "broadsheet" / "broadsheet.css"
_PAGES: tuple[tuple[str, str, str], ...] = (
    ("/", "Front page", "user"),
    ("/explorer", "Explorer", "user"),
    ("/chat", "Chat", "user"),
    ("/research", "Research", "user"),
    ("/upload", "Upload", "maintainer"),
    ("/maintenance", "Maintenance", "user"),
    ("/admin", "Admin", "admin"),
)


_BODIES: dict[str, Callable[[gui_session.Session], None]] = {
    "/chat": gui_chat.build,
    "/explorer": gui_explorer.build,
    "/research": gui_research.build,
}


def _bootstrap() -> None:
    """Same one-time setup the Streamlit app does at import."""
    db_context.migrate_legacy_layout()
    auth.ensure_seeded()
    auth.backfill_maintainers()


def _login_page() -> None:
    if gui_session.current() is not None:
        ui.navigate.to("/")
        return

    def submit() -> None:
        message = gui_session.login(username.value or "", password.value or "")
        if message:
            error.set_text(message)
        else:
            ui.navigate.to("/")

    with ui.column().classes("items-center w-full").style("margin-top: 12vh"):
        ui.label("LocalWiki").classes("plate")
        ui.label("Sign in to continue").classes("muted")
        username = ui.input("Username").props("outlined dense").classes("w-72")
        password = ui.input("Password", password=True).props("outlined dense").classes("w-72")
        password.on("keydown.enter", submit)
        error = ui.label().classes("text-negative")
        ui.button("Sign in", on_click=submit).props("flat").classes("btn primary").mark("sign-in")


def _stub(title: str) -> Callable[[gui_session.Session], None]:
    """A placeholder body for a page the plan builds in a later phase."""

    def build(_session: gui_session.Session) -> None:
        with ui.column().classes("q-pa-xl"):
            ui.label(title).classes("headline m")
            ui.label("This page is not built yet in the Broadsheet frontend.").classes("muted")

    return build


def _shell(path: str, body: Callable[[gui_session.Session], None]):
    """Wrap a page body in the running head and the folio."""

    def build(session: gui_session.Session) -> None:
        gui_chrome.running_head(session, path)
        body(session)
        gui_chrome.folio(session)

    return build


def register() -> None:
    """Register every page route on the current NiceGUI app."""
    if _CSS.exists():
        ui.add_css(_CSS.read_text(encoding="utf-8"), shared=True)
    ui.add_body_html(CITE_JS, shared=True)
    ui.add_body_html(gui_graph.GRAPH_JS, shared=True)
    gui_graph.register_assets()
    ui.page("/login")(_login_page)
    for path, title, who in _PAGES:
        body = _BODIES.get(path, _stub(title))
        page = gui_session.guard(
            _shell(path, body), maintainer=who == "maintainer", admin=who == "admin"
        )
        ui.page(path)(page)


def gpu_endpoint() -> dict[str, Any]:
    """Same JSON the Streamlit app serves at `/_api/gpu`, for scripts that poll it."""
    return gpu_widget.gpu_payload()


def _serve(port: int) -> None:
    import uvicorn

    _bootstrap()
    api = FastAPI()
    api.add_api_route(f"{MOUNT_PATH}/_api/gpu", gpu_endpoint)
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
