"""Stage D — cross-encoder reranking.

The model itself is never loaded here: `score_pairs` is mocked so the suite stays
fast and needs no GGUF. What is tested is the contract around it — fail-open,
position-aware blending, and the Fast/Deep split in `retrieval.search`.
"""

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import chunker
import db_context
import embed_index
import gpu_placement
import lex_index
import rerank
import retrieval


def _hits(n: int) -> list[dict]:
    """n fused hits, already in descending fused-score order."""
    return [
        {
            "chunk_id": f"c{i}",
            "source": "s.md",
            "text": f"body {i}",
            "score": round(1.0 - i * 0.01, 4),
        }
        for i in range(n)
    ]


# --- availability -------------------------------------------------------------


def test_unavailable_when_disabled(monkeypatch):
    monkeypatch.setenv("RERANK_ENABLED", "0")
    assert not rerank.available()


def test_unavailable_without_model_file(monkeypatch, tmp_path):
    monkeypatch.setenv("RERANK_ENABLED", "1")
    monkeypatch.setenv("RERANK_MODEL", str(tmp_path / "absent.gguf"))
    assert not rerank.available()


# --- fail open ----------------------------------------------------------------


def test_rerank_fails_open_when_scoring_returns_nothing(monkeypatch):
    """A down reranker must degrade ranking, never break search."""
    monkeypatch.setattr(rerank, "score_pairs", lambda q, docs: [])
    hits = _hits(8)
    assert rerank.rerank("q", hits, top_k=5) == hits[:5]


def test_rerank_fails_open_on_partial_scores(monkeypatch):
    monkeypatch.setattr(rerank, "score_pairs", lambda q, docs: [1.0, 2.0])
    hits = _hits(8)
    assert rerank.rerank("q", hits, top_k=5) == hits[:5]


def test_rerank_noop_on_trivial_list(monkeypatch):
    monkeypatch.setattr(rerank, "score_pairs", lambda q, docs: pytest.fail("should not score"))
    hits = _hits(1)
    assert rerank.rerank("q", hits, top_k=5) == hits


# --- blending -----------------------------------------------------------------


def test_blend_weight_tiers_are_position_aware():
    assert rerank._blend_weight(0) == rerank._blend_weight(2) == 0.25
    assert rerank._blend_weight(3) == rerank._blend_weight(9) == 0.40
    assert rerank._blend_weight(10) == rerank._blend_weight(99) == 0.50


def test_blend_weight_never_lets_reranker_dominate():
    """Tuned gentler than qmd's .75 tail: the tail regressed recall@10 on the
    KI fixtures. The reranker may never own more than half the decision."""
    assert max(rerank._blend_weight(r) for r in range(50)) <= 0.5


def test_normalize_handles_flat_input():
    assert rerank._normalize([3.0, 3.0, 3.0]) == [0.5, 0.5, 0.5]


def test_reranker_promotes_a_strong_tail_hit(monkeypatch):
    """The whole point of Stage D: a fused-rank-5 chunk the cross-encoder loves
    climbs past neighbours the lexical/dense arms ranked above it.

    It is promoted, not enthroned — the blend deliberately keeps a strong fused
    leader on top (see test_top_fused_hit_survives_a_maximal_tail_score), so the
    assertion is movement, not the #1 slot.
    """
    hits = _hits(8)
    logits = [0.0] * 8
    logits[5] = 10.0
    monkeypatch.setattr(rerank, "score_pairs", lambda q, docs: logits)
    out = rerank.rerank("q", hits, top_k=8)
    assert [h["chunk_id"] for h in out].index("c5") < 5


def test_top_fused_hit_survives_a_maximal_tail_score(monkeypatch):
    """Guards the regression the tuning fixed: an exact match at rank 0 must not
    be evicted by a rank-11 hit the cross-encoder happens to score highest."""
    hits = _hits(12)
    logits = [0.0] * 12
    logits[11] = 100.0
    monkeypatch.setattr(rerank, "score_pairs", lambda q, docs: logits)
    out = rerank.rerank("q", hits, top_k=3)
    assert out[0]["chunk_id"] == "c0"


def test_rerank_score_is_attached_for_stage_e(monkeypatch):
    """Stage E calibrates an abstention threshold on the raw logit, so it must
    survive onto the hit dict."""
    monkeypatch.setattr(rerank, "score_pairs", lambda q, docs: [2.5, -7.0, 0.0])
    out = rerank.rerank("q", _hits(3), top_k=3)
    assert {h["chunk_id"]: h["rerank_score"] for h in out}["c0"] == 2.5


def test_rerank_preserves_hit_shape(monkeypatch):
    monkeypatch.setattr(rerank, "score_pairs", lambda q, docs: [1.0, 2.0, 3.0])
    out = rerank.rerank("q", _hits(3), top_k=3)
    for key in ("chunk_id", "source", "text", "score"):
        assert all(key in h for h in out)


# --- integration with retrieval.search ---------------------------------------


def test_search_is_unchanged_when_reranker_unavailable(tmp_path, monkeypatch):
    """Enabling the flag on a machine without the model can never change results."""
    monkeypatch.setattr(db_context, "DATA_ROOT", tmp_path)
    db_context.set_active_db("d")
    monkeypatch.setenv("RERANK_ENABLED", "0")
    chunker.write_chunks(
        "radon.md", chunker.split("## Radon\nRadon raises the neutron dose in the reactor.")
    )
    lex_index.build()
    assert not embed_index.available()
    plain = retrieval.search("radon dose", top_k=5)
    deep = retrieval.search("radon dose", top_k=5, use_rerank=True)
    assert [h["chunk_id"] for h in plain] == [h["chunk_id"] for h in deep]


def test_search_fast_path_never_calls_the_reranker(tmp_path, monkeypatch):
    """Fast (browsing) stays fusion-only per idea.md §6.9.2 — no model load."""
    monkeypatch.setattr(db_context, "DATA_ROOT", tmp_path)
    db_context.set_active_db("d")
    monkeypatch.setattr(rerank, "available", lambda: True)
    monkeypatch.setattr(rerank, "rerank", lambda *a, **k: pytest.fail("Fast path must not rerank"))
    chunker.write_chunks("radon.md", chunker.split("## Radon\nNeutron dose."))
    lex_index.build()
    retrieval.search("radon dose", top_k=5)


# --- GPU placement ------------------------------------------------------------


class _FakeLlamaCpp:
    """Just enough of llama_cpp for `_model_params`; the real one needs CUDA."""

    LLAMA_SPLIT_MODE_NONE = 0
    LLAMA_SPLIT_MODE_LAYER = 1

    @staticmethod
    def llama_model_default_params():
        return SimpleNamespace(split_mode=1, main_gpu=0, n_gpu_layers=-1)


@pytest.fixture
def _gguf(monkeypatch, tmp_path):
    """A stand-in reranker GGUF of a known size."""
    path = tmp_path / "reranker.gguf"
    path.write_bytes(b"\0" * 1024)
    monkeypatch.setattr(rerank, "_model_path", lambda: path)
    monkeypatch.delenv("RERANK_PIN_GPU", raising=False)
    return path


def _two_cards(monkeypatch, free0: float = 12.0, free1: float = 22.0) -> None:
    monkeypatch.setattr(
        gpu_placement,
        "gpus",
        lambda: [
            gpu_placement.Gpu(index=0, name="card0", total_gib=24.0, free_gib=free0),
            gpu_placement.Gpu(index=1, name="card1", total_gib=24.0, free_gib=free1),
        ],
    )


def test_model_params_pin_to_one_card(_gguf, monkeypatch):
    """llama.cpp defaults to splitting layers across every GPU; we override that."""
    _two_cards(monkeypatch)
    params = rerank._model_params(_FakeLlamaCpp)
    assert params.split_mode == _FakeLlamaCpp.LLAMA_SPLIT_MODE_NONE
    assert params.main_gpu == 1  # the emptier card


def test_pinning_can_be_turned_off(_gguf, monkeypatch):
    _two_cards(monkeypatch)
    monkeypatch.setenv("RERANK_PIN_GPU", "off")
    params = rerank._model_params(_FakeLlamaCpp)
    assert params.split_mode == _FakeLlamaCpp.LLAMA_SPLIT_MODE_LAYER


def test_pin_gpu_can_name_a_card(_gguf, monkeypatch):
    _two_cards(monkeypatch)
    monkeypatch.setenv("RERANK_PIN_GPU", "0")
    assert rerank._model_params(_FakeLlamaCpp).main_gpu == 0


def test_no_gpu_leaves_the_defaults_alone(_gguf, monkeypatch):
    monkeypatch.setattr(gpu_placement, "gpus", lambda: [])
    params = rerank._model_params(_FakeLlamaCpp)
    assert params.split_mode == _FakeLlamaCpp.LLAMA_SPLIT_MODE_LAYER


def test_an_unreadable_gguf_leaves_the_defaults_alone(monkeypatch, tmp_path):
    monkeypatch.setattr(rerank, "_model_path", lambda: tmp_path / "absent.gguf")
    _two_cards(monkeypatch)
    params = rerank._model_params(_FakeLlamaCpp)
    assert params.split_mode == _FakeLlamaCpp.LLAMA_SPLIT_MODE_LAYER
