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
