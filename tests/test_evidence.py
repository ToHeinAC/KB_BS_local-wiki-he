"""Tests for evidence.py — the Deep chat evidence ledger (pure: no I/O)."""

import evidence

READ = (
    "## Raw file: StrlSchG.md § 62 (Teil 2)\n"
    "Rückstände dürfen nur verwertet werden, wenn die zuständige Behörde die Entlassung "
    "aus der Überwachung genehmigt hat. Die Entlassung setzt voraus, dass 1 mSv im "
    "Kalenderjahr nicht überschritten wird. Im Übrigen gilt diese Vorschrift entsprechend.\n"
    "\n\nReferences: § 61 (same file) · read with raw_read(['StrlSchG.md § 61'])"
)


def test_the_sentences_that_match_the_question_are_kept_with_their_citation():
    got = evidence.extract(READ, "Entlassung von Rückständen aus der Überwachung genehmigt")
    assert [ref for ref, _ in got] == ["StrlSchG.md § 62", "StrlSchG.md § 62"]
    assert got[0][1].startswith("Rückstände dürfen nur verwertet werden")
    assert "1 mSv" in got[1][1]
    assert all("References" not in s for _, s in got)


def test_a_sentence_matching_only_one_query_word_is_not_evidence():
    assert evidence.extract(READ, "Vorschrift") == []


def test_window_reads_cite_the_file_and_section_maps_contribute_only_their_sections():
    window = (
        "## Raw file: a.md (bytes 0-16000 of 90000)\n"
        "Der Grenzwert für Radon beträgt 300 Bq je Kubikmeter Luft.\n"
    )
    mapped = (
        "## Raw file: b.md — section map (40 sections; best matches read in full)\n\n"
        "## Raw file: b.md § 5\nDer Radon Grenzwert gilt in Aufenthaltsräumen.\n\n"
        "Map near the matches: § 4 Radon Grenzwert · § 5 Radon Grenzwert."
    )
    q = "Radon Grenzwert"
    assert evidence.extract(window, q) == [
        ("a.md", "Der Grenzwert für Radon beträgt 300 Bq je Kubikmeter Luft.")
    ]
    assert evidence.extract(mapped, q) == [
        ("b.md § 5", "Der Radon Grenzwert gilt in Aufenthaltsräumen.")
    ]


def test_memory_stubs_and_errors_yield_no_evidence():
    stub = "## Raw file: a.md § 2\n[memory] Already read this section at step 3 — Radon Grenzwert."
    assert evidence.extract(stub, "Radon Grenzwert") == []


def test_the_ledger_renders_numbered_quotes_with_their_citation_tags():
    text = evidence.render([("a.md § 5", "Satz eins."), ("b.md", "Satz zwei.")])
    assert text == '[1] [Source: a.md § 5] "Satz eins."\n[2] [Source: b.md] "Satz zwei."'
