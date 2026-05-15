"""Unit tests for the ingest-time term/acronym/fact extractor."""

import json
from unittest.mock import patch

import pytest

import chunker
import extractor
import lex_index


@pytest.fixture()
def isolated_index(tmp_path, monkeypatch):
    monkeypatch.setattr(extractor, "INDEX_DIR", tmp_path / "index")
    monkeypatch.setattr(extractor, "ALIASES_PATH", tmp_path / "index" / "aliases.json")
    monkeypatch.setattr(extractor, "ACRONYMS_PATH", tmp_path / "index" / "acronyms.json")
    monkeypatch.setattr(extractor, "TERMS_PATH", tmp_path / "index" / "terms.json")
    monkeypatch.setattr(extractor, "FACTS_PATH", tmp_path / "index" / "facts.jsonl")
    return tmp_path / "index"


@pytest.fixture()
def isolated_lex(tmp_path, monkeypatch):
    monkeypatch.setattr(chunker, "CHUNKS_DIR", tmp_path / "chunks")
    monkeypatch.setattr(lex_index, "INDEX_DIR", tmp_path / "index")
    monkeypatch.setattr(lex_index, "POSTINGS_PATH", tmp_path / "index" / "postings.json")
    monkeypatch.setattr(lex_index, "STATS_PATH", tmp_path / "index" / "stats.json")
    monkeypatch.setattr(lex_index, "TRIGRAMS_PATH", tmp_path / "index" / "trigrams.json")
    return tmp_path


SAMPLE_JSON = json.dumps({
    "aliases": [{"canonical": "Strahlenschutzgesetz",
                 "variants": ["StrlSchG", "Radiation Protection Act"]}],
    "acronyms": [{"acronym": "BfS", "expansion": "Bundesamt für Strahlenschutz"}],
    "terms":   [{"term": "Freigabewerte", "anchor": "§ 5",
                 "short_definition": "Activity thresholds for clearance."}],
    "facts":   [{"kind": "clearance_value", "subject": "Co-60",
                 "value": 0.1, "unit": "Bq/g", "anchor": "Anlage 4"}],
})


def test_extract_parses_clean_json(isolated_index):
    with patch.object(extractor.ollama_client, "generate", return_value=SAMPLE_JSON):
        out = extractor.extract("StrlSchG.md", "irrelevant text body")
    assert out["acronyms"][0]["acronym"] == "BfS"
    assert out["facts"][0]["subject"] == "Co-60"


def test_extract_strips_code_fences(isolated_index):
    fenced = "```json\n" + SAMPLE_JSON + "\n```"
    with patch.object(extractor.ollama_client, "generate", return_value=fenced):
        out = extractor.extract("x.md", "body")
    assert out["aliases"][0]["canonical"] == "Strahlenschutzgesetz"


def test_extract_empty_on_bad_json(isolated_index):
    with patch.object(extractor.ollama_client, "generate", return_value="not json at all"):
        out = extractor.extract("x.md", "body")
    assert out == {"aliases": [], "acronyms": [], "terms": [], "facts": []}


def test_extract_empty_on_ollama_failure(isolated_index):
    def boom(*a, **kw):
        raise RuntimeError("ollama down")
    with patch.object(extractor.ollama_client, "generate", side_effect=boom):
        out = extractor.extract("x.md", "body")
    assert out["aliases"] == []


def test_persist_writes_all_sidecars(isolated_index):
    data = json.loads(SAMPLE_JSON)
    extractor.persist("StrlSchG.md", data)
    assert (isolated_index / "aliases.json").exists()
    assert (isolated_index / "acronyms.json").exists()
    assert (isolated_index / "terms.json").exists()
    assert (isolated_index / "facts.jsonl").exists()
    acronyms = json.loads((isolated_index / "acronyms.json").read_text())
    assert acronyms[0]["acronym"] == "BfS"


def test_persist_merges_idempotently(isolated_index):
    data = json.loads(SAMPLE_JSON)
    extractor.persist("StrlSchG.md", data)
    extractor.persist("StrlSchG.md", data)
    acronyms = extractor.load_acronyms()
    aliases = extractor.load_aliases()
    assert len(acronyms) == 1  # not duplicated
    assert len(aliases) == 1
    # facts.jsonl is append-only — accept both entries
    facts = extractor.load_facts()
    assert len(facts) == 2 and facts[0]["subject"] == "Co-60"


def test_digest_built_for_large_sources(isolated_index):
    big = "x" * (extractor.DIGEST_THRESHOLD + 100)
    chunks = [{"anchor": "§ 1", "text": "Erster Paragraf inhalt."},
              {"anchor": "§ 2", "text": "Zweiter Paragraf inhalt."}]
    captured = {}

    def capture(system, prompt, temperature=0.1):
        captured["prompt"] = prompt
        return SAMPLE_JSON

    with patch.object(extractor.ollama_client, "generate", side_effect=capture):
        extractor.extract("Big.md", big, chunks)
    assert "[§ 1]" in captured["prompt"]
    assert "[§ 2]" in captured["prompt"]
    # full body NOT included
    assert "x" * 1000 not in captured["prompt"]


def test_acronym_expansion_lifts_chunk_rank(isolated_lex, isolated_index):
    """End-to-end: an acronym query that has zero direct hits in the body must
    still rank the right chunk after expansion."""
    body = """\
## § 1 Anwendungsbereich
Dieses Gesetz regelt den Schutz vor ionisierender Strahlung.

## § 5 Begriffsbestimmungen
Die Bundesbehörde für Strahlenschutz veröffentlicht regelmäßig Freigabewerte.
"""
    chunks = chunker.split(body)
    chunker.write_chunks("StrlSchG.md", chunks)
    lex_index.build()

    # Without expansion: "BfS" string doesn't appear in the body at all.
    no_expand = lex_index.query("BfS")
    assert no_expand == [] or all("BfS" not in h["text"] for h in no_expand)

    # Persist an acronym entry mapping BfS -> Bundesbehörde für Strahlenschutz
    extractor.persist("StrlSchG.md", {
        "aliases": [],
        "acronyms": [{"acronym": "BfS", "expansion": "Bundesbehörde für Strahlenschutz"}],
        "terms": [],
        "facts": [],
    })

    expanded = lex_index.query("BfS")
    assert expanded, "expansion should rescue the query"
    assert "Bundesbehörde" in expanded[0]["text"]


def test_facts_lookup(isolated_index):
    extractor.persist("StrlSchG.md", json.loads(SAMPLE_JSON))
    hits = lex_index.facts_lookup("clearance value Co-60")
    assert hits
    assert hits[0]["subject"] == "Co-60"
    assert hits[0]["unit"] == "Bq/g"
