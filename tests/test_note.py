"""Typed notes (src/note.py): cleanup for the second brain, verbatim text kept."""

from datetime import date
from typing import Any

import pytest

import note
import ollama_client
import prompts

DAY = date(2026, 11, 1)


def test_the_file_name_comes_from_the_title_in_ascii() -> None:
    name = note.file_name("Treffen mit Müller: Budget 2025!", "# Other\n\ntext", DAY)
    assert name == "note-2026-11-01-treffen-mit-mueller-budget-2025.md"


def test_without_a_title_the_cleaned_heading_names_the_file() -> None:
    assert note.file_name("", "# Grüße aus Köln\n\ntext", DAY) == (
        "note-2026-11-01-gruesse-aus-koeln.md"
    )
    assert note.file_name("  ", "no heading at all", DAY) == "note-2026-11-01-no-heading-at-all.md"
    assert note.file_name("", "", DAY) == "note-2026-11-01.md"


def test_a_long_title_is_cut_at_a_word() -> None:
    name = note.file_name("word " * 30, "", DAY)
    stem = name.removeprefix("note-2026-11-01-").removesuffix(".md")
    assert len(stem) <= 50
    assert not stem.endswith("-")
    assert set(stem.split("-")) == {"word"}


def test_only_keywords_found_in_the_note_are_kept() -> None:
    original = "Met Anna about the Rust migration of the billing service."
    cleaned = "# Billing\n\nText.\n\nKeywords: Rust migration, Anna, Kubernetes, billing service"
    assert note.keep_known_keywords(cleaned, original).endswith(
        "Keywords: Rust migration, Anna, billing service"
    )


def test_a_keyword_line_without_known_terms_is_dropped() -> None:
    cleaned = "# Billing\n\nText.\n\n**Keywords:** Kubernetes, Helm"
    assert note.keep_known_keywords(cleaned, "billing text") == "# Billing\n\nText."


def test_numbers_the_model_added_are_reported() -> None:
    original = "Budget 1.200 EUR, deadline 15.3., 3 people"
    cleaned = "Budget 1.200 EUR by 2025-03-15 for 3 people, 4 rooms"
    assert note.new_numbers(cleaned, original) == ["2025-03-15", "4"]
    assert note.new_numbers(original, original) == []


def test_the_stored_note_keeps_the_typed_text_verbatim_as_a_quote() -> None:
    stored = note.compose("# Topic\n\nClean text.\n", "line one\n# not a heading\n\nline three")
    assert stored == (
        "# Topic\n\nClean text.\n\n"
        f"{note.ORIGINAL_HEADING}\n\n"
        "> line one\n> # not a heading\n>\n> line three\n"
    )


def _stub_generate(monkeypatch: pytest.MonkeyPatch, reply: str) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []

    def generate(system: str, prompt: str, temperature: float = 0.3) -> str:
        calls.append({"system": system, "prompt": prompt, "temperature": temperature})
        return reply

    monkeypatch.setattr(ollama_client, "generate", generate)
    return calls


def test_cleanup_pins_the_notes_language_and_passes_the_title(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _stub_generate(monkeypatch, "```markdown\n# Termin\n\nText.\n\nKeywords: Termin\n```")
    text = "Der Termin mit dem Kunden ist am Montag und wir müssen das Angebot schicken."
    cleaned = note.clean(text, "Termin")
    assert cleaned == "# Termin\n\nText.\n\nKeywords: Termin"
    (call,) = calls
    assert prompts.NOTE_LANGUAGE_DIRECTIVE["de"] in call["system"]
    assert text in call["prompt"]
    assert '"Termin"' in call["prompt"]


def test_cleanup_of_an_english_note_without_a_title(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _stub_generate(monkeypatch, "# Call\n\nText.")
    note.clean("The call with the client is on Monday and we have to send the offer.", "")
    (call,) = calls
    assert prompts.NOTE_LANGUAGE_DIRECTIVE["en"] in call["system"]
    assert "exactly this title" not in call["prompt"]
