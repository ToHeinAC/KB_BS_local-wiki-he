"""Admin page of the Broadsheet frontend (src/gui_admin.py)."""

import asyncio
from pathlib import Path
from typing import Any

import pytest
from nicegui import ui
from nicegui.testing import User

import audit
import auth
import db_context
import gui_admin
import gui_app
import gui_session

DB = db_context.DEFAULT_DB
ADMIN = auth.DEFAULT_USER


# --- logic ----------------------------------------


@pytest.mark.parametrize(
    "call",
    [
        lambda: gui_admin.create_database("reader", "New", []),
        lambda: gui_admin.save_user("reader", "nodb", [DB], [], {}, ""),
        lambda: gui_admin.remove_user("reader", "nodb"),
        lambda: gui_admin.add_user("reader", "x", "pw", [], [], "Normal", False),
    ],
)
def test_every_admin_action_refuses_a_non_admin(gui_env: Path, call: Any) -> None:
    with pytest.raises(PermissionError):
        call()


def test_a_new_database_is_created_and_its_maintainers_assigned(gui_env: Path) -> None:
    msg = gui_admin.create_database(ADMIN, "Fresh DB", ["reader"])
    assert msg == "Created `Fresh DB` and assigned maintainers."
    assert "Fresh DB" in db_context.list_dbs()
    assert auth.is_maintainer(ADMIN, "Fresh DB")
    assert auth.is_maintainer("reader", "Fresh DB")


def test_an_invalid_database_name_is_rejected(gui_env: Path) -> None:
    with pytest.raises(ValueError, match="Invalid database name"):
        gui_admin.create_database(ADMIN, "../evil", [])


def test_saving_a_user_sets_access_maintainers_clearance_and_password(gui_env: Path) -> None:
    db_context.create_db("Other")
    gui_admin.save_user(
        ADMIN,
        "reader",
        [DB, "Other"],
        [DB, "Gone"],  # a maintained DB outside the allow-list is dropped
        {DB: "Confidential", "Other": "Normal"},
        "newpw",
    )
    assert auth.user_dbs("reader") == [DB, "Other"]
    assert auth.user_maintains("reader") == [DB]
    assert auth.clearance("reader", DB) == "confidential"
    assert auth.verify("reader", "newpw")
    events = [r for r in audit.recent() if r.get("action") == "clearance_set"]
    assert [(e["target"], e["level"]) for e in events] == [("reader", "confidential")]


def test_a_blank_password_keeps_the_old_one(gui_env: Path) -> None:
    gui_admin.save_user(ADMIN, "reader", [DB], [], {DB: "Normal"}, "")
    assert auth.verify("reader", "pw")


def test_an_admin_cannot_delete_themselves_but_can_delete_others(gui_env: Path) -> None:
    with pytest.raises(ValueError, match="yourself"):
        gui_admin.remove_user(ADMIN, ADMIN)
    gui_admin.remove_user(ADMIN, "nodb")
    assert "nodb" not in [u["username"] for u in auth.list_users()]


def test_adding_a_user_applies_clearance_to_each_allowed_database(gui_env: Path) -> None:
    gui_admin.add_user(ADMIN, " newbie ", "pw1", [DB], [DB, "Nope"], "Confidential", False)
    assert auth.user_dbs("newbie") == [DB]
    assert auth.user_maintains("newbie") == [DB]
    assert auth.clearance("newbie", DB) == "confidential"


def test_adding_a_user_without_a_password_is_an_error(gui_env: Path) -> None:
    with pytest.raises(ValueError, match="password"):
        gui_admin.add_user(ADMIN, "x", "", [DB], [], "Normal", False)


# --- page ----------------------------------------


@pytest.fixture(autouse=True)
def _pages(user: User, gui_env: Path) -> None:
    gui_session._SESSIONS.clear()
    gui_app.register()


async def _see(user: User, text: str) -> None:
    await user.should_see(text, retries=100)


async def _until(check: Any, tries: int = 100) -> None:
    for _ in range(tries):
        if check():
            return
        await asyncio.sleep(0.05)


async def _open_admin(user: User) -> None:
    await user.open("/login")
    user.find("Username").type(ADMIN)
    user.find("Password").type(auth.DEFAULT_PASSWORD)
    user.find("sign-in").click()
    await user.should_see("Front page")
    await user.open("/admin")


async def test_the_admin_page_lists_databases_users_and_the_audit_log(user: User) -> None:
    audit.record("classified", ADMIN, target="x.md", shard=DB, sha256="abc")
    await _open_admin(user)
    await _see(user, "Databases")
    await _see(user, f"Existing: {DB}")
    await _see(user, "Users")
    await _see(user, "reader")
    await _see(user, "Security audit log")
    await _see(user, "classified")


async def test_creating_a_database_from_the_form(user: User) -> None:
    await _open_admin(user)
    await _see(user, "Databases")
    user.find("new-db-name").type("Brand New")
    user.find("create-db").click()
    await _see(user, "Created `Brand New` and assigned maintainers.")
    assert "Brand New" in db_context.list_dbs()


async def test_an_invalid_database_name_shows_the_error(user: User) -> None:
    await _open_admin(user)
    await _see(user, "Databases")
    user.find("new-db-name").type("no/slash")
    user.find("create-db").click()
    await _see(user, "Invalid database name")


async def test_adding_a_user_from_the_form(user: User) -> None:
    await _open_admin(user)
    await _see(user, "Users")
    user.find("new-user-name").type("fresh")
    user.find("new-user-password").type("pw9")
    (dbs,) = user.find("new-user-dbs").elements
    assert isinstance(dbs, ui.select)
    dbs.set_value([DB])
    user.find("add-user").click()
    await _until(lambda: "fresh" in [u["username"] for u in auth.list_users()])
    assert auth.user_dbs("fresh") == [DB]


async def test_own_account_cannot_be_deleted_from_the_page(user: User) -> None:
    await _open_admin(user)
    await _see(user, "Users")
    (mine,) = user.find(f"user-delete-{ADMIN}").elements
    (other,) = user.find("user-delete-reader").elements
    assert isinstance(mine, ui.button)
    assert isinstance(other, ui.button)
    assert not mine.enabled
    assert other.enabled


async def test_saving_a_user_from_the_page_changes_their_databases(user: User) -> None:
    db_context.create_db("Other")
    await _open_admin(user)
    await _see(user, "Users")
    (dbs,) = user.find("user-dbs-reader").elements
    assert isinstance(dbs, ui.select)
    dbs.set_value([DB, "Other"])
    user.find("user-save-reader").click()
    await _until(lambda: auth.user_dbs("reader") == [DB, "Other"])
    assert auth.user_dbs("reader") == [DB, "Other"]
