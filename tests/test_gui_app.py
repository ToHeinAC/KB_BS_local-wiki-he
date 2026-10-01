"""Smoke tests for the NiceGUI (Broadsheet) entry point: harness, routing, login page."""

import asyncio
import os
import signal
from pathlib import Path

import pytest
from nicegui import app, ui
from nicegui.testing import User

import auth
import db_context
import gui_app
import gui_chrome
import gui_session


@pytest.fixture(autouse=True)
def _pages(user: User) -> None:
    """NiceGUI's `user` fixture resets the app per test; register the pages after it."""
    gui_session._SESSIONS.clear()
    gui_app.register()


async def test_unauthenticated_root_redirects_to_login(user: User) -> None:
    await user.open("/")
    await user.should_see("LocalWiki")
    await user.should_see("Sign in")


async def test_login_page_has_credential_fields(user: User) -> None:
    await user.open("/login")
    await user.should_see("Username")
    await user.should_see("Password")


def test_prefix_is_the_streamlit_base_path() -> None:
    assert gui_app.MOUNT_PATH == "/wiwi"


# --- login, chrome and routing (docs/ui.md §Broadsheet frontend) ------------------------------


async def _sign_in(user: User, name: str, password: str) -> None:
    await user.open("/login")
    user.find("Username").type(name)
    user.find("Password").type(password)
    user.find("sign-in").click()


async def test_bad_credentials_show_an_error_and_stay_on_the_login_page(
    gui_env: Path, user: User
) -> None:
    await _sign_in(user, "reader", "wrong")
    await user.should_see("Invalid username or password.")
    await user.should_not_see("2BrAIn")


async def test_an_account_without_databases_cannot_sign_in(gui_env: Path, user: User) -> None:
    await _sign_in(user, "nodb", "pw")
    await user.should_see("This account has no database access. Ask an admin.")


async def test_admin_signs_in_to_the_front_page_with_the_full_nav(
    gui_env: Path, user: User
) -> None:
    await _sign_in(user, auth.DEFAULT_USER, auth.DEFAULT_PASSWORD)
    for text in ("2BrAIn", "Explorer", "Chat", "Research", "Maintenance"):
        await user.should_see(text)
    await user.should_not_see(kind=ui.link, content="Upload")
    await user.should_see("Normal")  # the level stamp


async def test_the_browser_tab_reads_l_wiki_with_an_emoji_icon(gui_env: Path, user: User) -> None:
    await _sign_in(user, "reader", "pw")
    await user.should_see("2BrAIn")
    assert user.client is not None
    page = user.client.page
    assert (page.resolve_title(), page.favicon) == ("L-Wiki", gui_app.FAVICON)
    assert not str(gui_app.FAVICON).isascii()  # an emoji, not a file path


def test_the_quasar_primary_is_the_newspaper_green() -> None:
    assert app.config.quasar_config["brand"]["primary"] == "#234637"


async def test_only_admins_reach_the_admin_page(gui_env: Path, user: User) -> None:
    await _sign_in(user, "reader", "pw")
    await user.open("/admin")
    await user.should_not_see("This page is not built yet")


async def test_a_signed_out_visitor_is_sent_to_login_from_every_page(user: User) -> None:
    for path in ("/explorer", "/chat", "/research", "/maintenance"):
        await user.open(path)
        await user.should_see("Sign in")


async def test_signed_in_users_skip_the_login_page(gui_env: Path, user: User) -> None:
    await _sign_in(user, "reader", "pw")
    await user.open("/login")
    await user.should_see("2BrAIn")


async def test_sign_out_returns_to_login_and_drops_the_session(gui_env: Path, user: User) -> None:
    await _sign_in(user, "reader", "pw")
    await user.should_see("Explorer")
    user.find("user-menu").click()
    user.find("sign-out").click()
    await user.should_see("Sign in to continue")
    await user.open("/chat")
    await user.should_see("Sign in to continue")


async def test_the_folio_reports_model_and_index(gui_env: Path, user: User) -> None:
    await _sign_in(user, "reader", "pw")
    await user.should_see("Open Knowledge Format v0.1")
    await user.should_see("on GPU 1")
    await user.should_see("No search index")


async def test_switching_database_rebinds_the_session(gui_env: Path, user: User) -> None:
    auth.set_user_dbs("reader", [db_context.DEFAULT_DB, "Other"])
    await _sign_in(user, "reader", "pw")
    await user.should_see("2BrAIn")
    user.find(ui.select).click()
    user.find("Other").click()
    (session,) = gui_session._SESSIONS.values()
    for _ in range(40):  # the async handler runs as a background task
        if session.active_db == "Other":
            break
        await asyncio.sleep(0.05)
    assert (session.active_db, session.shard) == ("Other", "Other")


def test_the_gpu_endpoint_serves_the_widget_payload(gui_env: Path) -> None:
    assert gui_app.gpu_endpoint() == {
        "gpus": [],
        "elapsed": None,
        "is_running": False,
        "model": None,
    }


def test_every_route_of_the_nav_is_registered_and_guarded() -> None:
    assert {path for path, _, _ in gui_app._PAGES} == {href for _, href in gui_chrome.NAV} | {
        "/admin"
    }


async def test_each_page_starts_at_the_base_level_with_no_widened_scope(
    gui_env: Path, user: User
) -> None:
    auth.set_clearance("reader", db_context.DEFAULT_DB, "confidential", by="t")
    with db_context.clearance({db_context.DEFAULT_DB: 1}):
        db_context.ensure_shard(f"{db_context.DEFAULT_DB}@confidential")
    await _sign_in(user, "reader", "pw")
    await user.should_see("2BrAIn")
    (session,) = gui_session._SESSIONS.values()
    session.scope = [db_context.DEFAULT_DB, f"{db_context.DEFAULT_DB}@confidential"]  # Chat's

    def build(_s: gui_session.Session) -> None:
        ui.label(f"scope {db_context.search_scope()}")

    ui.page("/scoped")(gui_session.guard(build))
    await user.open("/scoped")
    await user.should_see(f"scope ('{db_context.DEFAULT_DB}',)")
    assert session.scope == []


async def test_admins_can_stop_the_server_by_signalling_its_own_process(
    gui_env: Path, user: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    signals: list[tuple[int, int]] = []
    monkeypatch.setattr(gui_chrome.os, "kill", lambda pid, sig: signals.append((pid, sig)))
    await _sign_in(user, auth.DEFAULT_USER, auth.DEFAULT_PASSWORD)
    await user.should_see("2BrAIn")
    user.find("user-menu").click()
    user.find("stop-server").click()
    for _ in range(40):
        if signals:
            break
        await asyncio.sleep(0.05)
    assert signals == [(os.getpid(), signal.SIGTERM)]


async def test_readers_have_no_stop_server_item(gui_env: Path, user: User) -> None:
    await _sign_in(user, "reader", "pw")
    await user.should_see("2BrAIn")
    user.find("user-menu").click()
    await user.should_not_see("stop-server")


def test_stopping_is_refused_for_non_admins(gui_env: Path) -> None:
    with pytest.raises(PermissionError):
        gui_chrome.stop_server("reader")
