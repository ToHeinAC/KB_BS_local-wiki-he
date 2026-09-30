"""Smoke tests for the NiceGUI (Broadsheet) entry point: harness, routing, login page."""

import pytest
from nicegui.testing import User

import gui_app


@pytest.fixture(autouse=True)
def _pages(user: User) -> None:
    """NiceGUI's `user` fixture resets the app per test; register the pages after it."""
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
