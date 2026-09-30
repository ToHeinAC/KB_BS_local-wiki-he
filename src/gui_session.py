"""Per-browser session of the NiceGUI frontend: identity, sealing, worker threads.

The classification gate keeps its state in ContextVars, and NiceGUI runs every page build,
event handler and timer tick in its own task, so **every entry point re-seals** the session's
clearance before it reads a path (`Session.seal`, applied by `guard` and `guarded`). Blocking
backend calls go through `in_worker`, which carries that binding into the worker thread.

Only `user`, `active_db` and an opaque `sid` are ever written to NiceGUI's persistent storage
(`PERSISTED_KEYS`); everything document-derived lives in the in-memory `Session.state`.
This is the only GUI module that seals clearance or touches `storage.user`
(`tests/test_security_rules.py`, `tests/test_gui_session.py`).
"""

import asyncio
import functools
import inspect
import queue
import secrets
import threading
from collections.abc import AsyncIterator, Callable, Iterator
from dataclasses import dataclass, field
from typing import Any, TypeVar, cast

from nicegui import app, run, ui

import auth
import db_context
import ui_logic
import wiki_engine

_T = TypeVar("_T")
PERSISTED_KEYS = frozenset({"user", "active_db", "sid"})
_POLL_SECONDS = 0.05


@dataclass
class Session:
    """What one signed-in browser is bound to. `shard` is the classification level the
    current page reads (the base DB unless a level picker chose a higher one)."""

    user: str
    active_db: str
    shard: str
    scope: list[str] = field(default_factory=lambda: [])
    grants: dict[str, int] = field(default_factory=lambda: {})
    state: dict[str, Any] = field(default_factory=lambda: {})

    @property
    def can_maintain(self) -> bool:
        return auth.is_maintainer(self.user, self.active_db)

    def seal(self) -> None:
        """Re-read the user's grants and bind clearance, DB and scope to this context.

        Run at the start of every page build, handler and timer tick: an admin's revocation
        then takes effect at the user's next interaction, and a shrunk grant drops whatever
        content was read under the old one.
        """
        grants = auth.clearance_map(self.user)
        if ui_logic.grants_shrank(self.grants, grants):
            self.state.clear()
            self.shard, self.scope = self.active_db, []
        self.grants = grants
        db_context.seal_clearance(grants, user=self.user)
        allowed = auth.user_dbs(self.user)
        if allowed and self.active_db not in allowed:
            self.switch_db(allowed[0])
        self._bind()

    def _bind(self) -> None:
        try:
            db_context.set_active_db(self.shard)
            db_context.set_search_scope(self.scope)
        except db_context.AccessDenied:  # the bound level was revoked
            self.shard, self.scope = self.active_db, []
            db_context.set_active_db(self.shard)
            db_context.set_search_scope([])

    def bind_shard(self, shard: str) -> None:
        """Read one classification level: it becomes the active DB and the only scope."""
        self.shard, self.scope = shard, [shard]
        ui_logic.bind_level(shard)

    def switch_db(self, db: str) -> None:
        """Move to another database: content of the old one must not follow."""
        self.active_db, self.shard, self.scope = db, db, []
        self.state.clear()


def check_persistable(key: str) -> None:
    if key not in PERSISTED_KEYS:
        raise ValueError(f"{key!r} must not be persisted (allowed: {sorted(PERSISTED_KEYS)})")


def _persist(key: str, value: str | None) -> None:
    check_persistable(key)
    storage = cast(dict[str, Any], app.storage.user)  # pyright: ignore[reportUnknownMemberType]
    if value is None:
        storage.pop(key, None)
    else:
        storage[key] = value


def _stored(key: str) -> str | None:
    storage = cast(dict[str, Any], app.storage.user)  # pyright: ignore[reportUnknownMemberType]
    value = storage.get(key)
    return value if isinstance(value, str) else None


_SESSIONS: dict[str, Session] = {}


def current() -> Session | None:
    """The signed-in session of this browser, or None. Rebuilt from storage after a restart."""
    user, sid = _stored("user"), _stored("sid")
    if not user or not sid:
        return None
    found = _SESSIONS.get(sid)
    if found is not None and found.user == user:
        return found
    allowed = auth.user_dbs(user)
    if not allowed:
        return None
    db = _stored("active_db")
    db = db if db in allowed else allowed[0]
    return _SESSIONS.setdefault(sid, Session(user, db, db))


def login(username: str, password: str) -> str | None:
    """Sign in. Returns the error to show, or None on success."""
    if not auth.verify(username, password):
        return "Invalid username or password."
    dbs = auth.user_dbs(username)
    if not dbs:
        return "This account has no database access. Ask an admin."
    logout()
    sid = secrets.token_hex(16)
    _persist("sid", sid)
    _persist("user", username)
    _persist("active_db", dbs[0])
    _SESSIONS[sid] = Session(username, dbs[0], dbs[0])
    return None


def logout() -> None:
    """Drop this browser's session and everything it held."""
    sid = _stored("sid")
    if sid:
        _SESSIONS.pop(sid, None)
    for key in PERSISTED_KEYS:
        _persist(key, None)


def select_db(session: Session, db: str) -> None:
    """Switch the session's database and remember the choice across reloads."""
    session.switch_db(db)
    _persist("active_db", db)


def guard(build: Callable[[Session], None], *, maintainer: bool = False, admin: bool = False):
    """Wrap a page builder: sign-in required, sealed, database initialised.

    Signed-out visitors go to `/login`; a page that needs more (`maintainer`, `admin`)
    sends the rest home. Fails closed: the clearance is emptied before anything is known.
    """

    def page() -> None:
        db_context.seal_clearance({})
        session = current()
        if session is None:
            ui.navigate.to("/login")
            return
        session.shard, session.scope = session.active_db, []  # a page never inherits another's
        session.seal()
        if (maintainer and not session.can_maintain) or (admin and not auth.is_admin(session.user)):
            ui.navigate.to("/")
            return
        wiki_engine.init_wiki()
        build(session)

    return page


def guarded(session: Session):
    """Decorator for event handlers and timer callbacks: seal, then run (sync or async)."""

    def decorate(fn: Callable[..., Any]) -> Callable[..., Any]:
        @functools.wraps(fn)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            session.seal()
            result = fn(*args, **kwargs)
            return await result if inspect.isawaitable(result) else result

        return wrapper

    return decorate


async def in_worker(fn: Callable[..., _T], *args: Any, **kwargs: Any) -> _T:
    """Run a blocking backend call in a thread that carries this context's binding."""
    bound = db_context.bind_context(functools.partial(fn, *args, **kwargs))
    return cast(_T, await run.io_bound(bound))


class _Done:
    def __init__(self, after: Any = None, error: BaseException | None = None) -> None:
        self.after, self.error = after, error


class StepStream:
    """Async iterator over the steps a sync generator produces in a worker thread.

    The generator is consumed in one worker thread, and `after` (e.g. reading the run's
    audit) runs there too, because that state lives in the worker's ContextVars; its result
    is `after_result` once the stream ends. A worker error is re-raised to the consumer.
    """

    def __init__(
        self, fn: Callable[..., Iterator[Any]], args: tuple[Any, ...], after: Callable[[], Any]
    ) -> None:
        self.after_result: Any = None
        self._queue: queue.Queue[Any] = queue.Queue()
        self._stop = threading.Event()
        self._task = asyncio.ensure_future(in_worker(self._work, fn, args, after))

    def _work(
        self, fn: Callable[..., Iterator[Any]], args: tuple[Any, ...], after: Callable[[], Any]
    ) -> None:
        try:
            for step in fn(*args):
                if self._stop.is_set():
                    return
                self._queue.put(step)
            self._queue.put(_Done(after=after()))
        except BaseException as e:  # handed to the consumer
            self._queue.put(_Done(error=e))

    def __aiter__(self) -> AsyncIterator[Any]:
        return self._steps()

    async def _steps(self) -> AsyncIterator[Any]:
        try:
            while True:
                try:
                    item = self._queue.get_nowait()
                except queue.Empty:
                    await asyncio.sleep(_POLL_SECONDS)
                    continue
                if isinstance(item, _Done):
                    if item.error is not None:
                        raise item.error
                    self.after_result = item.after
                    return
                yield item
        finally:
            self._stop.set()


def stream_steps(
    fn: Callable[..., Iterator[Any]], *args: Any, after: Callable[[], Any] = lambda: None
) -> StepStream:
    """Consume the sync step generator `fn(*args)` in a worker; iterate with `async for`."""
    return StepStream(fn, args, after)
