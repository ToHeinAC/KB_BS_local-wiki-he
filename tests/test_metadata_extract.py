"""Tests for deterministic effective-date detection."""

import metadata_extract as me


def test_cue_gueltig_ab_dmy():
    assert me.extract_effective_date("Diese Verordnung ist gültig ab 01.01.2024.") == "2024-01-01"


def test_cue_in_kraft_getreten():
    assert me.extract_effective_date("... in Kraft getreten am 15.03.2022 ...") == "2022-03-15"


def test_cue_stand_month_name():
    assert me.extract_effective_date("Stand: 1. Januar 2020") == "2020-01-01"


def test_cue_fassung_vom_iso():
    assert me.extract_effective_date("Fassung vom 2019-07-08 der Richtlinie") == "2019-07-08"


def test_cue_priority_prefers_in_kraft_over_stand():
    text = "Stand: 05.05.2005. Die Regel ist in Kraft getreten am 09.09.2009."
    assert me.extract_effective_date(text) == "2009-09-09"


def test_bare_date_fallback():
    assert me.extract_effective_date("Ein Dokument vom 31.12.2021 ohne Signalwort davor.") == "2021-12-31"


def test_no_date_returns_none():
    assert me.extract_effective_date("Ein Text ganz ohne Datumsangabe.") is None


def test_empty_returns_none():
    assert me.extract_effective_date("") is None


def test_invalid_calendar_date_skipped():
    # 31.02 is not a real date -> not matched, falls through to None
    assert me.extract_effective_date("gültig ab 31.02.2024") is None


def test_date_only_in_tail_ignored():
    head = "x" * 4100
    assert me.extract_effective_date(head + " gültig ab 01.01.2024") is None
