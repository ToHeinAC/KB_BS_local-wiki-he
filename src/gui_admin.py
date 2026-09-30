"""Admin page of the Broadsheet frontend: databases, users and the security audit log.

Every action re-checks that the acting user is an admin (`require_admin`), on top of the
route guard: a page that is merely hidden is not access control. Clearance changes are
recorded in the audit log by `auth.set_clearance`.
"""

from typing import Any

from nicegui import ui

import audit
import auth
import classification
import db_context
import gui_session

_AUDIT_COLUMNS = ("at", "user", "action", "target", "shard")
_AUDIT_ROWS = 100


def require_admin(actor: str) -> None:
    if not auth.is_admin(actor):
        raise PermissionError("Admins only.")


def create_database(actor: str, name: str, maintainers: list[str]) -> str:
    """Create a database and make `actor` and `maintainers` its maintainers."""
    require_admin(actor)
    name = name.strip()
    db_context.create_db(name)
    for user in {actor, *maintainers}:
        auth.grant_maintainer(user, name)
    return f"Created `{name}` and assigned maintainers."


def save_user(
    actor: str,
    username: str,
    dbs: list[str],
    maintains: list[str],
    clearances: dict[str, str],
    password: str,
) -> None:
    """Apply the edited access of `username`; a blank password keeps the old one."""
    require_admin(actor)
    auth.set_user_dbs(username, dbs)
    auth.set_user_maintains(username, [d for d in maintains if d in dbs])
    for db, label in clearances.items():
        current = classification.level_index(auth.clearance(username, db))
        if db in dbs and classification.level_index(label) != current:
            auth.set_clearance(username, db, label, by=actor)
    if password:
        auth.change_password(username, password)


def remove_user(actor: str, username: str) -> None:
    require_admin(actor)
    if username == actor:
        raise ValueError("You cannot delete yourself.")
    auth.delete_user(username)


def add_user(
    actor: str,
    username: str,
    password: str,
    dbs: list[str],
    maintains: list[str],
    clearance: str,
    is_admin: bool,
) -> None:
    require_admin(actor)
    name = username.strip()
    maintained = [d for d in maintains if d in dbs]
    auth.add_user(name, password, dbs, is_admin=is_admin, maintains=maintained)
    if classification.level_index(clearance):
        for db in dbs:
            auth.set_clearance(name, db, clearance, by=actor)


class AdminView:
    """Databases, users and the audit log, each as a section."""

    def __init__(self, session: gui_session.Session) -> None:
        self.session = session
        self._guard = gui_session.guarded(session)
        self.flash = ""

    def build(self) -> None:
        self.body = ui.column().classes("admin-col")
        self.render()

    def render(self) -> None:
        self.body.clear()
        with self.body:
            self._render_databases()
            self._render_users()
            self._render_audit()

    def _act(self, action: Any, *args: Any, done: str = "") -> str:
        """Run an admin action; the message to show, or its error."""
        try:
            action(self.session.user, *args)
        except (ValueError, PermissionError) as e:
            return str(e)
        return done

    # --- databases -----------------------------------------------------------------------

    def _render_databases(self) -> None:
        ui.label("Databases").classes("headline s")
        if self.flash:
            ui.label(self.flash).classes("text-positive")
        ui.label("Existing: " + (", ".join(db_context.list_dbs()) or "(none)")).classes("file")
        users = [u["username"] for u in auth.list_users()]
        name = ui.input("New database name (letters, digits, _ - space)").classes("w-96")
        name.mark("new-db-name")
        maint = ui.select(users, value=[self.session.user], multiple=True, label="Maintainers")
        maint.props("use-chips outlined dense").classes("w-96")
        note = ui.label("").classes("muted")

        def create() -> None:
            try:
                self.flash = create_database(self.session.user, name.value or "", list(maint.value))
            except (ValueError, PermissionError) as e:
                note.set_text(str(e))
                return
            self.render()

        ui.button("Create database", on_click=self._guard(create)).props("flat").classes(
            "btn"
        ).mark("create-db")

    # --- users ----------------------------------------------------------------------------

    def _render_users(self) -> None:
        ui.label("Users").classes("headline s q-mt-lg")
        for info in auth.list_users():
            self._render_user(info)
        self._render_add_user()

    def _render_user(self, info: dict[str, Any]) -> None:
        name = info["username"]
        all_dbs = db_context.list_dbs()
        title = f"{name} · dbs: {', '.join(info['dbs']) or 'none'} · admin: {info['is_admin']}"
        with ui.expansion(title).classes("fold w-full"):
            dbs = ui.select(all_dbs, value=[d for d in info["dbs"] if d in all_dbs], multiple=True)
            dbs.props("use-chips outlined dense label='Allowed databases'").classes("w-96")
            dbs.mark(f"user-dbs-{name}")
            kept = [d for d in info["maintains"] if d in all_dbs]
            maint = ui.select(all_dbs, value=kept, multiple=True)
            maint.props("use-chips outlined dense label='Maintained databases'").classes("w-96")
            clearance = self._render_clearances(name, all_dbs, dbs)
            password = ui.input("New password (blank keeps it)", password=True).classes("w-96")
            password.mark(f"user-password-{name}")
            note = ui.label("").classes("muted")
            with ui.row():
                self._user_buttons(name, dbs, maint, clearance, password, note)

    def _render_clearances(
        self, name: str, all_dbs: list[str], dbs: ui.select
    ) -> dict[str, ui.select]:
        selects: dict[str, ui.select] = {}
        for db in all_dbs:
            level = classification.level_index(auth.clearance(name, db))
            select = ui.select(
                list(classification.LEVEL_LABELS),
                value=classification.LEVEL_LABELS[level],
                label=f"Clearance · {db}",
            )
            select.props("outlined dense").classes("w-96")
            select.bind_visibility_from(dbs, "value", backward=lambda v, d=db: d in (v or []))
            select.mark(f"clearance-{name}-{db}")
            selects[db] = select
        return selects

    def _user_buttons(
        self,
        name: str,
        dbs: ui.select,
        maint: ui.select,
        clearance: dict[str, ui.select],
        password: ui.input,
        note: ui.label,
    ) -> None:
        def save() -> None:
            levels = {db: str(s.value) for db, s in clearance.items()}
            message = self._act(
                save_user, name, list(dbs.value), list(maint.value), levels, password.value or "",
                done="Updated.",
            )  # fmt: skip
            note.set_text(message)
            if message == "Updated.":
                self.flash = f"Updated {name}."
                self.render()

        def delete() -> None:
            message = self._act(remove_user, name, done=f"Deleted {name}.")
            note.set_text(message)
            if message.startswith("Deleted"):
                self.flash = message
                self.render()

        ui.button("Save", on_click=self._guard(save)).props("flat").classes("btn sm").mark(
            f"user-save-{name}"
        )
        gone = ui.button("Delete", on_click=self._guard(delete)).props("flat")
        gone.classes("btn text sm").set_enabled(name != self.session.user)
        gone.mark(f"user-delete-{name}")

    def _render_add_user(self) -> None:
        ui.label("Add user").classes("label q-mt-md")
        all_dbs = db_context.list_dbs()
        name = ui.input("Username").classes("w-96").mark("new-user-name")
        password = ui.input("Password", password=True).classes("w-96").mark("new-user-password")
        dbs = ui.select(all_dbs, multiple=True, label="Allowed databases")
        dbs.props("use-chips outlined dense").classes("w-96").mark("new-user-dbs")
        maint = ui.select(all_dbs, multiple=True, label="Maintained databases")
        maint.props("use-chips outlined dense").classes("w-96")
        level = ui.select(list(classification.LEVEL_LABELS), value="Normal", label="Clearance")
        level.props("outlined dense").classes("w-96")
        admin = ui.checkbox("Admin")
        note = ui.label("").classes("muted")

        def add() -> None:
            message = self._act(
                add_user, name.value or "", password.value or "", list(dbs.value or []),
                list(maint.value or []), str(level.value), bool(admin.value),
                done=f"Added user `{(name.value or '').strip()}`.",
            )  # fmt: skip
            note.set_text(message)
            if message.startswith("Added"):
                self.flash = message
                self.render()

        ui.button("Add user", on_click=self._guard(add)).props("flat").classes("btn").mark(
            "add-user"
        )

    # --- audit ------------------------------------------------------------------------------

    def _render_audit(self) -> None:
        ui.label("Security audit log").classes("headline s q-mt-lg")
        rows = audit.recent()
        if not rows:
            ui.label("No security events recorded yet.").classes("muted")
            return
        cols = len(_AUDIT_COLUMNS)
        with (
            ui.element("div")
            .classes("audit")
            .style(f"display: grid; grid-template-columns: repeat({cols}, auto); gap: 4px 20px")
        ):
            for column in _AUDIT_COLUMNS:
                ui.label(column).classes("label")
            for row in rows[:_AUDIT_ROWS]:
                for column in _AUDIT_COLUMNS:
                    ui.label(str(row.get(column, ""))).classes("file")


def build(session: gui_session.Session) -> None:
    """Page body of `/admin`."""
    AdminView(session).build()
