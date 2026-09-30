"""Session, sealing and worker plumbing of the NiceGUI frontend (src/gui_session.py)."""

import ast
import asyncio
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from nicegui import ui
from nicegui.testing import User

import auth
import db_context
import gui_session

DB = db_context.DEFAULT_DB
SRC = Path(__file__).resolve().parents[1] / "src"


@pytest.fixture(autouse=True)
def _restore_binding() -> Iterator[None]:
    active = db_context._active.set(db_context._active.get())
    scope = db_context._scope.set(db_context._scope.get())
    yield
    db_context._scope.reset(scope)
    db_context._active.reset(active)


# --- what may be persisted -------------------------------------------------------------


def test_only_identity_keys_may_be_persisted() -> None:
    for key in ("user", "active_db", "sid"):
        gui_session.check_persistable(key)
    for key in ("messages", "last_research_answer", "pending_batch"):
        with pytest.raises(ValueError, match=key):
            gui_session.check_persistable(key)


def storage_users(source: str) -> list[int]:
    """Lines that touch NiceGUI's persistent `storage.user` (only gui_session may)."""
    return [
        n.lineno
        for n in ast.walk(ast.parse(source))
        if isinstance(n, ast.Attribute) and n.attr == "user" and _is_storage(n.value)
    ]


def _is_storage(node: ast.expr) -> bool:
    return isinstance(node, ast.Attribute) and node.attr == "storage"


def test_storage_detector_flags_a_violating_module() -> None:
    assert storage_users("from nicegui import app\napp.storage.user['x'] = 1\n") == [2]
    assert storage_users("app.storage.client['x'] = 1\n") == []


def test_only_gui_session_touches_persistent_storage() -> None:
    offenders = {
        p.name: lines
        for p in SRC.glob("gui_*.py")
        if p.name != "gui_session.py" and (lines := storage_users(p.read_text(encoding="utf-8")))
    }
    assert offenders == {}


# --- sealing -----------------------------------------------------------------------------


def test_seal_binds_clearance_db_and_scope(gui_env: Path) -> None:
    s = gui_session.Session("reader", DB, DB)
    s.seal()
    assert db_context.get_active_db() == DB
    assert db_context.search_scope() == (DB,)
    assert s.grants == {DB: 0}
    assert s.can_maintain is False


def test_seal_purges_content_when_a_grant_shrinks(gui_env: Path) -> None:
    auth.set_clearance("reader", DB, "confidential", by="t")
    s = gui_session.Session("reader", DB, DB)
    s.seal()
    s.state["messages"] = ["secret"]
    auth.set_clearance("reader", DB, "normal", by="t")
    s.seal()
    assert s.state == {}


def test_seal_keeps_content_when_grants_do_not_shrink(gui_env: Path) -> None:
    s = gui_session.Session("reader", DB, DB)
    s.seal()
    s.state["messages"] = ["kept"]
    s.seal()
    assert s.state == {"messages": ["kept"]}


def test_seal_falls_back_to_the_normal_level_when_the_bound_shard_is_revoked(
    gui_env: Path,
) -> None:
    auth.set_clearance("reader", DB, "confidential", by="t")
    s = gui_session.Session("reader", DB, DB)
    s.seal()
    db_context.ensure_shard(f"{DB}@confidential")
    s.shard, s.scope = f"{DB}@confidential", [f"{DB}@confidential"]
    s.seal()
    assert db_context.get_active_db() == f"{DB}@confidential"
    auth.set_clearance("reader", DB, "normal", by="t")
    s.seal()
    assert (s.shard, s.scope) == (DB, [])
    assert db_context.get_active_db() == DB


def test_seal_clamps_the_active_db_to_the_allowlist(gui_env: Path) -> None:
    db_context.ensure_shard("Other")
    auth.set_user_dbs("reader", ["Other"])
    s = gui_session.Session("reader", DB, DB)
    s.seal()
    assert (s.active_db, s.shard) == ("Other", "Other")


def test_switch_db_resets_shard_scope_and_content(gui_env: Path) -> None:
    s = gui_session.Session("reader", DB, f"{DB}@confidential", scope=["x"], state={"a": 1})
    s.switch_db("Other")
    assert (s.active_db, s.shard, s.scope, s.state) == ("Other", "Other", [], {})


# --- worker threads and streaming ----------------------------------------------------------


def _probe() -> dict[str, Any]:
    return {"grants": dict(db_context._clearance.get() or {}), "db": db_context.get_active_db()}


async def test_workers_carry_the_sessions_clearance(gui_env: Path, user: User) -> None:
    auth.set_clearance("reader", DB, "confidential", by="t")

    @ui.page("/probe")
    async def probe() -> None:
        s = gui_session.Session("reader", DB, DB)
        s.seal()
        seen = await gui_session.in_worker(_probe)
        ui.label(f"worker sees {seen['grants']} on {seen['db']}")

    await user.open("/probe")
    await user.should_see(f"worker sees {{'{DB}': 1}} on {DB}")


async def test_stream_steps_yields_in_order_and_returns_the_after_result(
    gui_env: Path, user: User
) -> None:
    def steps(n: int) -> Iterator[dict[str, int]]:
        for i in range(n):
            yield {"i": i}

    @ui.page("/stream")
    async def stream() -> None:
        s = gui_session.Session("reader", DB, DB)
        s.seal()
        run = gui_session.stream_steps(steps, 3, after=lambda: db_context.get_active_db())
        got = [step["i"] async for step in run]
        ui.label(f"got {got} after {run.after_result}")

    await user.open("/stream")
    await user.should_see(f"got [0, 1, 2] after {DB}")


async def test_stream_steps_reraises_worker_errors(gui_env: Path, user: User) -> None:
    def broken() -> Iterator[dict[str, int]]:
        yield {"i": 0}
        raise RuntimeError("model gone")

    @ui.page("/broken")
    async def page() -> None:
        try:
            _ = [step async for step in gui_session.stream_steps(broken)]
        except RuntimeError as e:
            ui.label(f"failed: {e}")

    await user.open("/broken")
    await user.should_see("failed: model gone")


# --- two browsers never share a binding ------------------------------------------------------


async def test_interleaved_clients_keep_their_own_clearance(
    gui_env: Path, create_user: Any
) -> None:
    auth.add_user("strict", "pw", [DB], clearance={DB: "confidential"})
    with db_context.clearance({DB: 1}):
        db_context.ensure_shard(f"{DB}@confidential")
    gate = asyncio.Event()

    def page_for(name: str, wait: bool) -> Any:
        async def page() -> None:
            s = gui_session.Session(name, DB, DB)
            s.seal()
            if wait:
                await gate.wait()
            else:
                await asyncio.sleep(0)
                gate.set()
            ui.label(f"{name} reaches {list(db_context.reachable_shards(DB))}")

        return page

    ui.page("/strict")(page_for("strict", wait=True))
    ui.page("/reader")(page_for("reader", wait=False))
    a, b = create_user(), create_user()
    await asyncio.gather(a.open("/strict"), b.open("/reader"))
    await a.should_see(f"strict reaches ['{DB}', '{DB}@confidential']")
    await b.should_see(f"reader reaches ['{DB}']")
    await b.should_not_see("confidential")
