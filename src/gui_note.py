"""Note box of the 2BrAIn upload panel: a typed note is cleaned up by the local model
(`note.clean`), reviewed and edited, then added to the upload batch like a dropped Markdown file.
Nothing is ingested here; the batch's review and Ingest button decide that."""

from collections.abc import Awaitable, Callable
from datetime import date

from nicegui import ui

import gui_session
import note


class NoteBox:
    """Write → Clean up → review/edit → Add to batch (or Back to the typed note)."""

    def __init__(
        self, session: gui_session.Session, on_add: Callable[[str, bytes], Awaitable[None]]
    ) -> None:
        self._guard = gui_session.guarded(session)
        self.on_add = on_add
        self.original = ""

    def build(self) -> None:
        ui.label("Or write a note").classes("label")
        with ui.column().classes("w-full gap-2") as self.writing:
            self.title = ui.input("Title (optional)").props("dense outlined").classes("w-full")
            self.text = ui.textarea(placeholder="Type a note…").props("outlined rows=4")
            self.text.classes("w-full").mark("note-text")
            self.text.on_value_change(lambda _e: self._sync())
            with ui.row().classes("items-center gap-2"):
                self.clean_button = ui.button("Clean up", on_click=self._guard(self._clean))
                self.clean_button.props("flat").classes("btn primary").mark("note-clean")
                self.spinner = ui.spinner(size="1.4em")
        self.review = ui.column().classes("w-full gap-2")
        self.spinner.set_visibility(False)
        self._sync()

    def _sync(self) -> None:
        self.clean_button.set_enabled(bool((self.text.value or "").strip()))

    async def _clean(self) -> None:
        self.original = self.text.value or ""
        self.clean_button.set_enabled(False)
        self.spinner.set_visibility(True)
        try:
            cleaned = await gui_session.in_worker(note.clean, self.original, self.title.value or "")
            problem = ""
        except RuntimeError as exc:
            cleaned, problem = (
                self.original,
                f"Cleanup failed: {exc}. You can add the note as typed.",
            )
        self.spinner.set_visibility(False)
        self._sync()
        self._show_review(cleaned, problem)

    def _show_review(self, cleaned: str, problem: str) -> None:
        self.writing.set_visibility(False)
        self.review.clear()
        with self.review:
            ui.label("Cleaned note: review and edit before adding it.").classes("label")
            if problem:
                ui.label(problem).classes("text-warning")
            added = note.new_numbers(cleaned, self.original)
            if added:
                numbers = ", ".join(added)
                ui.label(f"Check these numbers, they are not in your note: {numbers}").classes(
                    "text-warning"
                )
            self.editor = ui.textarea(value=cleaned).props("outlined rows=8").classes("w-full")
            self.editor.mark("note-cleaned")
            ui.label(
                f"Your typed note is kept verbatim below it under “{note.ORIGINAL_HEADING}”."
            ).classes("hint")
            with ui.row().classes("items-center gap-4"):
                ui.button("Add to batch", on_click=self._guard(self._add)).props("flat").classes(
                    "btn primary"
                ).mark("note-add")
                ui.button("Back", on_click=self._guard(self._back)).props("flat").classes(
                    "btn text small"
                ).mark("note-back")

    async def _add(self) -> None:
        cleaned = self.editor.value or ""
        name = note.file_name(self.title.value or "", cleaned, date.today())
        data = note.compose(cleaned, self.original).encode()
        self.title.set_value("")
        self.text.set_value("")
        self._back()
        await self.on_add(name, data)

    def _back(self) -> None:
        self.review.clear()
        self.writing.set_visibility(True)
