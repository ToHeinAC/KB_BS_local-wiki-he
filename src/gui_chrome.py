"""Broadsheet chrome: the running head, the folio and the classification stamp.

Follows `ideas/gui-redesign/` (docs/ui.md §Broadsheet frontend): one running head with the
nameplate, the primary nav, the edition (database) picker, the level stamp and the user menu;
machine status lives in the one-line folio at the page foot, not in a sidebar.
"""

import os
import signal
from collections.abc import Callable
from typing import Any

from nicegui import ui

import auth
import classification
import gpu_widget
import gui_session
import gui_upload
import lex_index
import ollama_client
import ollama_server
import ui_logic

NAV: tuple[tuple[str, str], ...] = (
    ("2BrAIn", "/"),
    ("Explorer", "/explorer"),
    ("Chat", "/chat"),
    ("Research", "/research"),
    ("Maintenance", "/maintenance"),
)
_STAMP_CLASS = ("", "conf", "strict")
_FOLIO_SECONDS = 5.0
INGEST_BUSY = "An ingest is running. Stop the server after it has finished."


def stamp(shard: str) -> tuple[str, str]:
    """`(label, css class)` of the level stamp: plain, violet or reversed ink."""
    level = classification.parse_shard(shard)[1]
    return classification.level_label(level), _STAMP_CLASS[level]


def stop_server(actor: str) -> None:
    """End this server gracefully: SIGTERM to its own process, never a kill by port.
    Admins only; the check is here, not just in the menu."""
    if not auth.is_admin(actor):
        raise PermissionError("Admins only.")
    if gui_upload.ingest_running():
        raise RuntimeError(INGEST_BUSY)
    os.kill(os.getpid(), signal.SIGTERM)


def release_model() -> bool:
    """Unload the model unless an ingest still needs it. Blocking: run in a worker."""
    if gui_upload.ingest_running():
        return False
    ui_logic.unload_model()
    return True


def folio_data() -> dict[str, Any]:
    """Machine status for the folio. Blocking (it may start the pinned daemon): run in a worker."""
    pin = ollama_server.status()
    return {
        "model": ollama_client.MODEL,
        "pinned_gpu": pin["gpu"] if pin["pinned"] else None,
        "gpus": gpu_widget.gpu_payload()["gpus"],
        "index": lex_index.index_health(),
    }


def _load(card: dict[str, Any]) -> int:
    util = str(card["util"])
    return int(util) if util.isdigit() else -1


def working_card(gpus: list[dict[str, Any]], pinned: int | None) -> int | None:
    """Index of the card the model works on: the pinned one, else the busiest.
    `gpus` is in nvidia-smi order, which the pin's PCI_BUS_ID numbering matches."""
    if not gpus:
        return None
    if pinned is not None and 0 <= pinned < len(gpus):
        return pinned
    return max(range(len(gpus)), key=lambda i: _load(gpus[i]))


def folio_text(data: dict[str, Any]) -> list[str]:
    """The folio's status segments, left to right."""
    gpu = data["pinned_gpu"]
    where = "the shared daemon" if gpu is None else f"GPU {gpu}"
    parts = [f"{data['model']} on {where}"]
    index = working_card(data["gpus"], gpu)
    if index is not None:
        card = data["gpus"][index]
        name = str(card["name"]).replace("NVIDIA GeForce ", "")
        label = "" if index == gpu else f"GPU {index}: "
        parts.append(f"{label}{name} at {card['temp']} °C, load {card['util']} %")
    passages = sum(data["index"].values())
    parts.append(f"Search index: {passages} passages" if passages else "No search index")
    return parts


def running_head(session: gui_session.Session, path: str) -> None:
    """Nameplate, nav, edition picker, level stamp and user menu."""
    with ui.header().classes("runhead"):
        ui.link("LocalWiki", "/").classes("plate")
        with ui.row().classes("nav no-wrap"):
            for label, href in NAV:
                ui.link(label, href).classes("on" if href == path else "")
        ui.space()
        _edition_picker(session)
        label, css = stamp(session.shard)
        ui.label(label).classes(f"stamp {css}".strip())
        _user_menu(session)


def _edition_picker(session: gui_session.Session) -> None:
    dbs = auth.user_dbs(session.user)

    @gui_session.guarded(session)
    def _switch(event: Any) -> None:
        if event.value != session.active_db:
            gui_session.select_db(session, event.value)
            ui.navigate.reload()

    with ui.row().classes("edition items-baseline no-wrap"):
        ui.select(dbs, value=session.active_db, on_change=_switch).props(
            "dense borderless options-dense"
        ).classes("edition-select")
        ui.label("edition").classes("muted text-caption")


def _user_menu(session: gui_session.Session) -> None:
    async def _reset() -> None:
        if not await gui_session.in_worker(release_model):
            ui.notify("An ingest is running: the model stays loaded.", type="warning")
        _sign_out()

    def _stop() -> None:
        if gui_upload.ingest_running():
            ui.notify(INGEST_BUSY, type="warning")
            return
        ui.notify("Stopping the server…")
        ui.timer(0.5, lambda: stop_server(session.user), once=True)  # let the notice reach the page

    def _sign_out() -> None:
        gui_session.logout()
        ui.navigate.to("/login")

    button = ui.button(session.user).props("flat no-caps dense").classes("user").mark("user-menu")
    with button, ui.menu():
        if auth.is_admin(session.user):
            ui.menu_item("Admin", on_click=lambda: ui.navigate.to("/admin"))
            ui.menu_item("Stop server", on_click=gui_session.guarded(session)(_stop)).mark(
                "stop-server"
            )
        ui.menu_item("Reset", on_click=gui_session.guarded(session)(_reset))
        ui.menu_item("Sign out", on_click=_sign_out).mark("sign-out")


def folio(session: gui_session.Session) -> None:
    """One-line page foot; refreshed in a worker so a slow daemon never blocks the page."""
    with ui.footer().classes("folio"):
        box = ui.row().classes("items-center no-wrap w-full")

    async def refresh() -> None:
        data = await gui_session.in_worker(folio_data)
        box.clear()
        with box:
            for text in folio_text(data):
                ui.label(text)
            ui.label("Open Knowledge Format v0.1").classes("push")

    run: Callable[..., Any] = gui_session.guarded(session)(refresh)
    ui.timer(0.1, run, once=True)
    ui.timer(_FOLIO_SECONDS, run)
