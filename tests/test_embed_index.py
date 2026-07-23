"""Semantic arm + hybrid fusion tests (Stage C).

Embeddings are mocked with a deterministic toy vectorizer so cosine ranking, scope
filtering, storage roundtrip, OKF prefixing and RRF fusion are validated without a
live model. The mock maps each text to a small bag-of-words vector over a fixed
vocabulary, so texts sharing vocabulary have high cosine similarity.
"""

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import chunker
import db_context
import embed_index
import lex_index
import retrieval


_VOCAB = ["radon", "dose", "revenue", "cloud", "attention", "reactor",
          "photosynthesis", "neutron", "growth", "risk"]


def _toy_vec(text: str) -> list[float]:
    t = text.lower()
    v = np.array([1.0 if w in t else 0.0 for w in _VOCAB], dtype=np.float32)
    if not v.any():
        v[0] = 1e-3  # avoid a zero vector
    return v.tolist()


@pytest.fixture()
def semantic_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db_context, "DATA_ROOT", tmp_path)
    db_context.set_active_db("d")
    monkeypatch.setenv("EMBED_MODEL", "toy")
    monkeypatch.setattr(embed_index.ollama_client, "embed",
                        lambda texts, model_id: [_toy_vec(t) for t in texts])

    chunker.write_chunks("radon.md", chunker.split(
        "## Radon\nRadon in the reactor building raises the neutron dose."))
    chunker.write_chunks("sap.md", chunker.split(
        "## Revenue\nCloud revenue growth was strong; the main risk is regulatory."))
    lex_index.build()
    embed_index.build()
    return tmp_path


def test_build_writes_aligned_vectors_and_meta(semantic_db):
    import json
    matrix = np.load(embed_index._vectors_path())
    meta = json.loads(embed_index._meta_path().read_text())
    assert matrix.shape[0] == len(meta["rows"]) > 0
    assert meta["model"] == "toy"
    assert matrix.dtype == np.float16
    # rows are L2-normalized
    norms = np.linalg.norm(matrix.astype(np.float32), axis=1)
    assert np.allclose(norms, 1.0, atol=1e-2)


def test_available_reflects_model_match(semantic_db, monkeypatch):
    assert embed_index.available()
    monkeypatch.setenv("EMBED_MODEL", "other")   # vectors were built with 'toy'
    assert not embed_index.available()


def test_query_ranks_by_cosine(semantic_db):
    hits = embed_index.query("neutron dose in a reactor", top_k=5)
    assert hits and hits[0]["source"] == "radon.md"
    assert all(h["matched_terms"] == [] for h in hits)  # dense arm: no term overlap
    assert "text" in hits[0] and hits[0]["text"]


def test_query_scope_filter(semantic_db):
    assert all(h["scope"] == "raw" for h in embed_index.query("revenue", scope="raw"))
    assert embed_index.query("revenue", scope="wiki") == []  # no wiki pages here


def test_query_empty_without_index(tmp_path, monkeypatch):
    monkeypatch.setattr(db_context, "DATA_ROOT", tmp_path)
    db_context.set_active_db("empty")
    monkeypatch.setenv("EMBED_MODEL", "toy")
    assert embed_index.query("anything") == []
    assert not embed_index.available()


def test_okf_prefix_applied_to_wiki_only_not_leaked(tmp_path, monkeypatch):
    monkeypatch.setattr(db_context, "DATA_ROOT", tmp_path)
    db_context.set_active_db("d")
    monkeypatch.setenv("EMBED_MODEL", "toy")
    captured = {}

    def _spy(texts, model_id):
        captured["texts"] = list(texts)
        return [_toy_vec(t) for t in texts]

    monkeypatch.setattr(embed_index.ollama_client, "embed", _spy)
    wiki = tmp_path / "d" / "wiki"
    wiki.mkdir(parents=True)
    (wiki / "concept-x.md").write_text(
        "---\ntitle: Photosynthesis\ntype: concept\n---\n## Key facts\n- Plants make sugar.\n")
    embed_index.build()
    # the wiki chunk was embedded WITH the OKF identity prefix ...
    assert any(t.startswith("type: concept | title: Photosynthesis") for t in captured["texts"])
    # ... but the prefix never reaches the returned hit text
    hits = embed_index.query("Photosynthesis", scope="wiki")
    assert hits and "type: concept | title:" not in hits[0]["text"]


# --- RRF fusion / graceful degradation ---------------------------------------

def test_search_falls_back_to_lexical_without_vectors(tmp_path, monkeypatch):
    monkeypatch.setattr(db_context, "DATA_ROOT", tmp_path)
    db_context.set_active_db("d")
    monkeypatch.setenv("EMBED_MODEL", "toy")
    chunker.write_chunks("radon.md", chunker.split(
        "## Radon\nRadon raises the neutron dose in the reactor."))
    lex_index.build()  # lexical only; no embed_index.build()
    assert not embed_index.available()
    fused = retrieval.search("radon dose", top_k=5)
    lexed = lex_index.query("radon dose", top_k=5)
    assert [h["chunk_id"] for h in fused] == [h["chunk_id"] for h in lexed]


def test_search_fuses_both_arms(semantic_db):
    fused = retrieval.search("neutron dose reactor", top_k=5)
    assert fused and fused[0]["source"] == "radon.md"
    # a fused hit keeps the lexical hit's fields (matched_terms present when lexical)
    top = fused[0]
    assert "matched_terms" in top and "score" in top


def test_rrf_prefers_lexical_hit_dict_on_overlap():
    lex = [{"chunk_id": "a", "source": "s", "matched_terms": ["x"], "text": "lex"}]
    sem = [{"chunk_id": "a", "source": "s", "matched_terms": [], "text": "sem"}]
    fused = retrieval._rrf_fuse(lex, sem, top_k=5)
    assert len(fused) == 1
    assert fused[0]["matched_terms"] == ["x"]  # lexical hit won the tie
    assert fused[0]["score"] > 0
