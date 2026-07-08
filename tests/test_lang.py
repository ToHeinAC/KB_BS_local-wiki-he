"""Tests for lang.py — deterministic DE/EN detection + directive selection."""

import lang


# --- detect: long text ---

def test_detect_german_prose():
    assert lang.detect("Der Grenzwert für die effektive Dosis beträgt 20 mSv im Jahr.") == "de"


def test_detect_english_prose():
    assert lang.detect("The effective dose limit is 20 mSv per year for workers.") == "en"


# --- detect: short queries (the weak spot Layer 1 hardens) ---

def test_detect_short_german_question():
    assert lang.detect("Was ist ein Kernbrennstoff?") == "de"


def test_detect_short_english_question():
    assert lang.detect("What is a nuclear fuel?") == "en"


def test_umlaut_forces_german_even_when_terse():
    # No function words, but ß/umlaut is decisive.
    assert lang.detect("Rückstände Grenzwert?") == "de"


# --- detect: fallbacks ---

def test_no_signal_falls_back_to_default():
    assert lang.detect("Radon 222") == "de"
    assert lang.detect("Radon 222", default="en") == "en"


def test_empty_text_uses_default():
    assert lang.detect("") == "de"
    assert lang.detect(None) == "de"


# --- directive selection maps to the right prompt constant ---

def test_response_directive_language_matches():
    assert "ANTWORTSPRACHE" in lang.response_directive("Was gilt für Radon?")
    assert "ANSWER LANGUAGE" in lang.response_directive("What applies to radon?")


def test_ingest_directive_language_matches():
    assert "SPRACHE" in lang.ingest_directive("Der Bericht beschreibt die Anlage.")
    assert "LANGUAGE (strict)" in lang.ingest_directive("The report describes the plant.")


def test_directives_exempt_key_facts_heading():
    # The pipeline keys on the literal English `## Key facts`; the directive must
    # tell the model to keep it unchanged in both languages.
    assert "## Key facts" in lang.ingest_directive("Deutscher Text mit ä ö ü.")
    assert "## Key facts" in lang.ingest_directive("English text here.")
