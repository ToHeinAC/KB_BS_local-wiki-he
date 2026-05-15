"""Unit tests for the hypothetical-question generator (Tier 1.4)."""

import json
from unittest.mock import patch

import pytest

import chunker
import lex_index
import qa_gen


@pytest.fixture()
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(chunker, "CHUNKS_DIR", tmp_path / "chunks")
    monkeypatch.setattr(lex_index, "INDEX_DIR", tmp_path / "index")
    monkeypatch.setattr(lex_index, "POSTINGS_PATH", tmp_path / "index" / "postings.json")
    monkeypatch.setattr(lex_index, "STATS_PATH", tmp_path / "index" / "stats.json")
    monkeypatch.setattr(lex_index, "TRIGRAMS_PATH", tmp_path / "index" / "trigrams.json")
    monkeypatch.setattr(qa_gen, "INDEX_DIR", tmp_path / "index")
    monkeypatch.setattr(qa_gen, "QA_PATH", tmp_path / "index" / "qa.jsonl")
    return tmp_path


def test_generate_parses_json_array(isolated):
    chunks = [{"chunk_id": "c1", "anchor": "§ 1", "text": "abc"},
              {"chunk_id": "c2", "anchor": "§ 2", "text": "def"}]
    response = json.dumps([
        {"chunk_id": "c1", "questions": ["Q1a?", "Q1b?"]},
        {"chunk_id": "c2", "questions": ["Q2?"]},
    ])
    with patch.object(qa_gen.ollama_client, "generate", return_value=response):
        out = qa_gen.generate(chunks)
    assert out == [("c1", "Q1a?"), ("c1", "Q1b?"), ("c2", "Q2?")]


def test_generate_strips_code_fences(isolated):
    chunks = [{"chunk_id": "c1", "anchor": "x", "text": "x"}]
    fenced = "```json\n" + json.dumps([{"chunk_id": "c1", "questions": ["Q?"]}]) + "\n```"
    with patch.object(qa_gen.ollama_client, "generate", return_value=fenced):
        out = qa_gen.generate(chunks)
    assert out == [("c1", "Q?")]


def test_generate_drops_unknown_chunk_ids(isolated):
    chunks = [{"chunk_id": "real", "anchor": "x", "text": "x"}]
    response = json.dumps([{"chunk_id": "ghost", "questions": ["Q?"]}])
    with patch.object(qa_gen.ollama_client, "generate", return_value=response):
        assert qa_gen.generate(chunks) == []


def test_generate_empty_on_ollama_failure(isolated):
    chunks = [{"chunk_id": "c1", "anchor": "x", "text": "x"}]
    def boom(*a, **kw):
        raise RuntimeError("ollama down")
    with patch.object(qa_gen.ollama_client, "generate", side_effect=boom):
        assert qa_gen.generate(chunks) == []


def test_persist_and_load_roundtrip(isolated):
    qa_gen.persist([("c1", "Q1?"), ("c1", "Q2?"), ("c2", "Q3?")], "src.md")
    loaded = qa_gen.load()
    assert loaded == {"c1": ["Q1?", "Q2?"], "c2": ["Q3?"]}


def test_batching_chunks_runs_multiple_calls(isolated, monkeypatch):
    monkeypatch.setattr(qa_gen, "BATCH_SIZE", 2)
    chunks = [{"chunk_id": f"c{i}", "anchor": "", "text": "x"} for i in range(5)]
    call_count = {"n": 0}
    def stub(system, prompt, temperature=0.2):
        call_count["n"] += 1
        # Echo back each chunk id seen in the prompt with one question
        ids = []
        for line in prompt.splitlines():
            if line.startswith("--- chunk_id: "):
                ids.append(line.split("--- chunk_id: ")[1].split(" ")[0])
        return json.dumps([{"chunk_id": cid, "questions": [f"Q for {cid}?"]} for cid in ids])
    with patch.object(qa_gen.ollama_client, "generate", side_effect=stub):
        out = qa_gen.generate(chunks)
    assert call_count["n"] == 3  # ceil(5/2)
    assert len(out) == 5


def test_generate_caps_pairs_per_source(isolated, monkeypatch):
    """Tier A: qa_gen must emit at most MAX_PAIRS_PER_SOURCE pairs per source."""
    monkeypatch.setattr(qa_gen, "MAX_PAIRS_PER_SOURCE", 3)
    monkeypatch.setattr(qa_gen, "BATCH_SIZE", 12)
    chunks = [
        {"chunk_id": f"c{i}", "anchor": f"§ {i}", "heading_path": [f"§ {i}"],
         "text": f"Some German technical paragraph number {i} with various tokens.",
         "char_start": i * 100}
        for i in range(10)
    ]
    # LLM returns 2 questions per chunk seen → would be 20 if uncapped.
    def stub(system, prompt, temperature=0.2):
        ids = [ln.split("--- chunk_id: ")[1].split(" ")[0]
               for ln in prompt.splitlines() if ln.startswith("--- chunk_id: ")]
        return json.dumps([{"chunk_id": cid, "questions": [f"Q1 {cid}?", f"Q2 {cid}?"]}
                           for cid in ids])
    with patch.object(qa_gen.ollama_client, "generate", side_effect=stub):
        out = qa_gen.generate(chunks)
    assert len(out) == 3
    # Only the selected (anchored) chunks may appear.
    seen_ids = {cid for cid, _ in out}
    assert seen_ids.issubset({ch["chunk_id"] for ch in chunks})


def test_select_target_chunks_prefers_anchored(isolated):
    """Anchored chunks must outrank a denser-but-unanchored chunk."""
    dense_unanchored = {
        "chunk_id": "dense", "anchor": "", "heading_path": [],
        "text": " ".join(f"word{i}" for i in range(200)), "char_start": 0,
    }
    anchored = {
        "chunk_id": "anc", "anchor": "§ 5", "heading_path": ["§ 5"],
        "text": "kurz", "char_start": 10,
    }
    out = qa_gen._select_target_chunks([dense_unanchored, anchored], k=1)
    assert out[0]["chunk_id"] == "anc"


def test_questions_lift_chunk_rank(isolated):
    body = """\
## § 1 Anwendungsbereich
Dieses Gesetz regelt den Schutz.

## § 62 Entlassung von Rückständen aus der Überwachung
Rückstände dürfen aus der amtlichen Überwachung entlassen werden, wenn
ihre Aktivität bestimmte Werte unterschreitet.
"""
    chunks = chunker.split(body)
    chunker.write_chunks("StrlSchG.md", chunks)

    # Baseline index, no questions
    lex_index.build()
    baseline = lex_index.query("clearance threshold for radioactive residues")
    # Body is German; "clearance threshold" won't match well
    baseline_top = baseline[0]["anchor"] if baseline else None

    # Persist hypothetical English questions for § 62 (Teil 2 or main)
    target = next(c for c in chunks if c["anchor"].startswith("§ 62"))
    qa_gen.persist([
        (target["chunk_id"], "What is the clearance threshold for radioactive residues?"),
        (target["chunk_id"], "When may residues be released from supervision?"),
    ], "StrlSchG.md")

    lex_index.build()
    after = lex_index.query("clearance threshold for radioactive residues")
    assert after, "questions should make the chunk findable in English"
    assert after[0]["anchor"].startswith("§ 62")
    # Should be a strict improvement
    assert baseline_top != after[0]["anchor"] or (
        baseline and baseline[0]["score"] < after[0]["score"]
    )
