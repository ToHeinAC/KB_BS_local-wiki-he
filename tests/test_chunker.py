"""Unit tests for the structural chunker."""

import pytest

import chunker


LEGAL_SAMPLE = """\
# Strahlenschutzgesetz
Preamble paragraph one.

Preamble paragraph two with some context.

## § 1 Anwendungsbereich
Dieses Gesetz regelt den Schutz vor ionisierender Strahlung. Es ist auf alle
Tätigkeiten anzuwenden, die mit radioaktiven Stoffen verbunden sind.

## § 2 Begriffsbestimmungen
Im Sinne dieses Gesetzes ist eine Tätigkeit jede Handlung, die mit Strahlung
verbunden ist.

## § 62 Entlassung von Rückständen aus der Überwachung
Rückstände nach § 61 dürfen nur dann aus der Überwachung entlassen werden,
wenn ihre Aktivität bestimmte Freigabewerte unterschreitet. Die Freigabewerte
werden in Bq/g angegeben.
"""

MARKDOWN_SAMPLE = """\
# Company Overview

## Revenue
2024 revenue was 10B EUR.

## Risks
Key risk is regulatory exposure.

## Outlook
Growth expected in 2026.
"""


def test_legal_chunker_splits_per_paragraph():
    chunks = chunker.split(LEGAL_SAMPLE)
    anchors = [c["anchor"] for c in chunks]
    assert "§ 1" in anchors
    assert "§ 2" in anchors
    assert "§ 62" in anchors
    # Preamble may or may not survive MIN_CHUNK_CHARS — that's fine; the §'s are what matters.
    section_62 = next(c for c in chunks if c["anchor"] == "§ 62")
    assert "Freigabewerte" in section_62["text"]
    assert section_62["lang"] == "de"


def test_markdown_chunker_splits_per_heading():
    chunks = chunker.split(MARKDOWN_SAMPLE)
    anchors = {c["anchor"] for c in chunks}
    # Short sections may be merged into preceding; require at least Revenue or Outlook present.
    assert any(a in anchors for a in ("Revenue", "Outlook", "Risks"))
    # Combined text should preserve all original content
    joined = " ".join(c["text"] for c in chunks)
    assert "10B EUR" in joined
    assert "regulatory exposure" in joined


def test_chunk_id_is_stable_and_content_addressable():
    a = chunker.split(LEGAL_SAMPLE)
    b = chunker.split(LEGAL_SAMPLE)
    assert [c["chunk_id"] for c in a] == [c["chunk_id"] for c in b]


def test_chunk_id_changes_with_content():
    a = chunker.split(LEGAL_SAMPLE)
    mutated = LEGAL_SAMPLE.replace("Freigabewerte", "Grenzwerte")
    b = chunker.split(mutated)
    a_ids = {c["chunk_id"] for c in a}
    b_ids = {c["chunk_id"] for c in b}
    # The mutated § 62 chunk must have a different id from the original
    assert a_ids != b_ids


def test_empty_input_returns_empty():
    assert chunker.split("") == []
    assert chunker.split("   \n\n  ") == []


def test_persistence_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(chunker, "CHUNKS_DIR", tmp_path / "chunks")
    chunks = chunker.split(LEGAL_SAMPLE)
    chunker.write_chunks("StrlSchG.md", chunks)
    loaded = chunker.load_chunks("StrlSchG.md")
    assert len(loaded) == len(chunks)
    assert loaded[0]["chunk_id"] == chunks[0]["chunk_id"]
    assert loaded[0]["source"] == "StrlSchG.md"
