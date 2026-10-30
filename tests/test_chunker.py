"""Unit tests for the structural chunker."""

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
    import db_context

    monkeypatch.setattr(db_context, "DATA_ROOT", tmp_path)
    db_context.set_active_db("d")
    chunks = chunker.split(LEGAL_SAMPLE)
    chunker.write_chunks("StrlSchG.md", chunks)
    loaded = chunker.load_chunks("StrlSchG.md")
    assert len(loaded) == len(chunks)
    assert loaded[0]["chunk_id"] == chunks[0]["chunk_id"]
    assert loaded[0]["source"] == "StrlSchG.md"


def test_oversize_section_is_windowed_with_overlap():
    paras = [f"Absatz {i} " + "x" * 900 for i in range(10)]
    text = "## § 7 Lang\n\n" + "\n\n".join(paras) + "\n\n## § 8 Kurz\nText.\n\n## § 9 Ende\nText."
    chunks = [c for c in chunker.split(text) if c["anchor"].startswith("§ 7")]
    assert len(chunks) >= 3
    assert all(len(c["text"]) <= chunker.MAX_CHUNK_CHARS + 1000 for c in chunks)
    assert chunks[0]["anchor"] == "§ 7 (Teil 1)"
    assert chunks[1]["anchor"] == "§ 7 (Teil 2)"
    # overlap: the second window starts with the tail of the first
    tail = chunks[0]["text"].split("\n\n")[-1]
    assert chunks[1]["text"].startswith(tail)


def test_all_chunks_reads_every_source(tmp_path, monkeypatch):
    monkeypatch.setattr(chunker, "_chunks_dir", lambda: tmp_path)
    assert chunker.all_chunks() == []  # directory exists but is empty
    chunker.write_chunks("a.md", chunker.split("## A\n" + "a " * 60))
    chunker.write_chunks("b.md", chunker.split("## B\n" + "b " * 60))
    sources = sorted({c["source"] for c in chunker.all_chunks()})
    assert sources == ["a.md", "b.md"]
    assert chunker.load_chunks("missing.md") == []
    monkeypatch.setattr(chunker, "_chunks_dir", lambda: tmp_path / "absent")
    assert chunker.all_chunks() == []


# A statute copied as text from gesetze-im-internet.de: each heading a plain line without
# "#", CRLF line ends, and running text whose line may start with a § reference.
PLAIN_LEGAL = (
    "Gesetz zum Schutz vor der schädlichen Wirkung ionisierender Strahlung\r\n"
    "Nichtamtliches Inhaltsverzeichnis\r\n"
    "§ 61 Anfall und Lagerung überwachungsbedürftiger Rückstände\r\n"
    "(1) Wer Rückstände anfallen lässt, hat sie zu lagern und der Behörde anzuzeigen.\r\n"
    "Nichtamtliches Inhaltsverzeichnis\r\n"
    "§ 62 Entlassung von Rückständen aus der Überwachung; Verordnungsermächtigung\r\n"
    "(1) Der nach § 61 Absatz 1 Satz 1 Verpflichtete hat die Verwertung anzumelden.\r\n"
    "§ 61 Absatz 2 gilt entsprechend für die Beseitigung der Rückstände im Inland.\r\n"
    "§ 53 des Atomgesetzes bleibt unberührt.\r\n"
    "Nichtamtliches Inhaltsverzeichnis\r\n"
    "§ 63 Anzeige\r\n"
    "(1) Rückstände sind der zuständigen Behörde vor ihrer Verwertung anzuzeigen.\r\n"
)


def test_plain_section_headings_without_hash_split_a_statute_per_section():
    chunks = chunker.split(PLAIN_LEGAL)
    anchors = [c["anchor"] for c in chunks if c["anchor"] != "Präambel"]
    assert anchors == ["§ 61", "§ 62", "§ 63"]  # "§ 61 Absatz 2 …", "§ 53 des …": running text
    s62 = next(c for c in chunks if c["anchor"] == "§ 62")
    assert s62["heading_path"] == [
        "§ 62 Entlassung von Rückständen aus der Überwachung; Verordnungsermächtigung"
    ]
    assert "§ 61 Absatz 2 gilt entsprechend" in s62["text"]


def test_a_text_naming_a_few_sections_at_line_start_is_not_a_statute():
    text = "Notes\n\n§ 5 Absatz 1 applies here.\n\nSee also the appendix.\n" * 2
    assert all(not c["anchor"].startswith("§") for c in chunker.split(text))


def test_a_table_of_contents_of_plain_section_lines_is_not_split_into_sections():
    toc = (
        "Inhaltsübersicht\r\n§  61\tAnfall und Lagerung\r\nAbschnitt 2\r\nEntlassung aus\r\n"
        "der Überwachung\r\n§  62\tEntlassung von Rückständen\r\n"
        "§  63\tAnzeige\r\nAnlage 1\tRückstände nach § 5 Absatz 32\r\n"
    )
    chunks = chunker.split(toc + PLAIN_LEGAL)
    assert [c["anchor"] for c in chunks if c["anchor"] != "Präambel"] == ["§ 61", "§ 62", "§ 63"]
    s62 = next(c for c in chunks if c["anchor"] == "§ 62")
    assert s62["text"].startswith("§ 62 Entlassung von Rückständen aus der Überwachung")
