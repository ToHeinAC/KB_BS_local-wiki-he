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


# --- detect: robustness (umlaut is a tie-breaker, sampling spans the document) ---


def test_umlaut_name_does_not_flip_english_sentence():
    assert lang.detect("This paper by Jürgen Müller describes the model.") == "en"


def test_long_document_sampled_beyond_english_abstract():
    abstract = "Abstract: We propose a harness for the agents and the tools. " * 60
    body = (
        "Die Arbeit beschreibt, wie der Agent mit den Werkzeugen arbeitet und was er darf. " * 400
    )
    assert lang.detect(abstract + body) == "de"


# --- ingest directive protects original terms ---


def test_ingest_directives_protect_original_terms():
    de = lang.ingest_directive("Der Bericht beschreibt die Anlage.")
    en = lang.ingest_directive("The report describes the plant.")
    assert "ORIGINALBEGRIFFE" in de and "ORIGINAL TERMS" in en
    assert "fasse fremdsprachige Passagen" not in de
    assert "summarise non-English" not in en
