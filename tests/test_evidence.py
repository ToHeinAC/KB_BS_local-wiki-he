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


def test_a_numbered_list_stays_with_the_sentence_that_introduces_it():
    # § 78 (2) StrlSchG: cut after "1.", the quote lost every limit the question asks for.
    read = (
        "## Raw file: StrlSchG.md § 78\n"
        "(2) Der Grenzwert der Organ-Äquivalentdosis beträgt für beruflich exponierte "
        "Personen 1.\nfür die Augenlinse 20 Millisievert im Kalenderjahr,\n\n2.\n"
        "für die Haut 500 Millisievert im Kalenderjahr und\n\n3.\n"
        "für die Hände 500 Millisievert im Kalenderjahr.\n"
    )
    ((_, quote),) = evidence.extract(read, "Grenzwert beruflich exponierte Personen")
    assert "Augenlinse 20 Millisievert" in quote
    assert quote.endswith("für die Hände 500 Millisievert im Kalenderjahr.")


def test_dates_and_legal_abbreviations_do_not_end_a_sentence():
    read = (
        "## Raw file: V.md § 37\n"
        "Satz 1 gilt auch für die Freigabe zum Einsatz nach der Versatzverordnung vom "
        "24. Juli 2002 (BGBl. I S. 2833) und nach § 78 Abs. 2 Nr. 1 im Grenzwert. "
        "Der zweite Satz zur Freigabe nennt keinen Grenzwert der Versatzverordnung."
    )
    got = [q for _, q in evidence.extract(read, "Freigabe Versatzverordnung Grenzwert")]
    assert len(got) == 2
    assert got[0].endswith("nach § 78 Abs. 2 Nr. 1 im Grenzwert.")


def test_a_table_of_contents_line_is_not_evidence():
    read = (
        "## Raw file: G.md § 78\n"
        "· § 80 Grenzwerte für die Exposition der Bevölkerung · § 212 Grenzwerte für "
        "beruflich exponierte Personen;\n"
        "Der Grenzwert beträgt für beruflich exponierte Personen 20 Millisievert."
    )
    got = [q for _, q in evidence.extract(read, "Grenzwerte beruflich exponierte Personen")]
    assert got == ["Der Grenzwert beträgt für beruflich exponierte Personen 20 Millisievert."]


def test_an_overlong_sentence_is_clipped_at_a_clause_not_dropped():
    clauses = ", ".join(f"Grenzwert für Personen der Gruppe {i} gilt" for i in range(30))
    read = "## Raw file: G.md § 9\n" + clauses + "."
    ((_, quote),) = evidence.extract(read, "Grenzwert Personen Gruppe")
    assert 610 < len(quote) <= 910  # a list item is not left as a stub ("dem Aufsuchen …")
    assert quote.endswith(" …")
    assert quote[:-2] in read


def test_a_questions_key_terms_drop_question_and_function_words():
    q = "Welcher Grenzwert der effektiven Dosis gilt für Einzelpersonen der Bevölkerung?"
    assert evidence.key_terms(q) == "Grenzwert effektiven Dosis Einzelpersonen Bevölkerung"
    assert evidence.key_terms("Which limit applies to the public?") == "limit public"
    assert evidence.key_terms("Was gilt?") == ""
