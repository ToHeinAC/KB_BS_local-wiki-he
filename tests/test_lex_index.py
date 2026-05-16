"""Unit tests for the lexical BM25 index."""

import pytest

import chunker
import lex_index


SAMPLE_LEGAL = """\
## § 62 Entlassung von Rückständen aus der Überwachung
Rückstände dürfen nur dann aus der Überwachung entlassen werden,
wenn ihre Aktivität die Freigabewerte für Co-60 von 0,1 Bq/g unterschreitet.

## § 63 In der Überwachung verbleibende Rückstände
Sonstige Rückstände verbleiben in der amtlichen Überwachung.
"""

SAMPLE_ENGLISH = """\
## Revenue
SAP SE reported 2024 revenue growth of 10%.

## Risks
The primary risk is regulatory uncertainty in cloud markets.
"""


@pytest.fixture()
def fresh_index(tmp_path, monkeypatch):
    monkeypatch.setattr(chunker, "CHUNKS_DIR", tmp_path / "chunks")
    monkeypatch.setattr(lex_index, "INDEX_DIR", tmp_path / "index")
    monkeypatch.setattr(lex_index, "POSTINGS_PATH", tmp_path / "index" / "postings.json")
    monkeypatch.setattr(lex_index, "STATS_PATH", tmp_path / "index" / "stats.json")

    chunks_de = chunker.split(SAMPLE_LEGAL)
    chunker.write_chunks("StrlSchG.md", chunks_de)
    chunks_en = chunker.split(SAMPLE_ENGLISH)
    chunker.write_chunks("SAP.md", chunks_en)
    summary = lex_index.build()
    assert summary["chunks"] > 0
    return summary


def test_variants_three_forms():
    v = lex_index.variants("Rückstände")
    assert "rückstände" in v
    assert "rueckstaende" in v  # umlaut fold
    assert any(x.startswith("rueckstand") or x.startswith("ruckstand") for x in v)  # stem


def test_stopwords_filtered():
    assert lex_index.variants("der") == []
    assert lex_index.variants("the") == []


def test_recall_with_diacritic_folded_query(fresh_index):
    # Query uses ASCII fold; index has umlaut form
    hits = lex_index.query("rueckstaende")
    assert hits, "fold should match umlaut content"
    assert any("§ 62" in h["anchor"] or "§ 63" in h["anchor"] for h in hits)


def test_recall_with_stem_query(fresh_index):
    # Query uses singular; index has plural
    hits = lex_index.query("Rückstand")
    assert hits
    assert hits[0]["source"] == "StrlSchG.md"


def test_bm25_ranks_specific_section_higher(fresh_index):
    hits = lex_index.query("Freigabewerte Co-60")
    assert hits
    # § 62 mentions Freigabewerte; § 63 does not. § 62 must rank first.
    assert "§ 62" in hits[0]["anchor"]


def test_english_query(fresh_index):
    hits = lex_index.query("revenue growth")
    assert hits
    assert hits[0]["source"] == "SAP.md"


def test_no_results_for_unknown_query(fresh_index):
    hits = lex_index.query("xyzzy quux frobnicate")
    assert hits == []
