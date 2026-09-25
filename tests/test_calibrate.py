"""Stage E — calibrated abstention (src/calibrate.py).

The reranker is never loaded here: hits carry a synthetic `rerank_score` and τ comes
from a written `calibration.json`. What is tested is the contract — monotonic display
map, per-DB threshold resolution, and the fail-safe that abstention fires ONLY under a
genuine calibrated below-τ signal.
"""

import itertools
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import calibrate
import db_context


def _calibrated_db(monkeypatch, tmp_path: Path, tau: float, db: str = "KI") -> None:
    """Point db_context at an isolated root and write a calibration.json with τ."""
    monkeypatch.setattr(db_context, "DATA_ROOT", tmp_path)
    db_context.set_active_db(db)
    idx = tmp_path / db / "index"
    idx.mkdir(parents=True, exist_ok=True)
    (idx / "calibration.json").write_text(json.dumps({"tau": tau}))


def _hits(*scores: float) -> list[dict]:
    return [{"source": f"p{i}.md", "rerank_score": s} for i, s in enumerate(scores)]


# --- relevance display map ----------------------------------------------------


def test_relevance_monotonic_and_bounded():
    xs = [-10.0, -4.0, 0.0, 3.0, 8.0]
    ys = [calibrate.relevance(x) for x in xs]
    assert all(0.0 < y < 1.0 for y in ys)
    assert all(a < b for a, b in itertools.pairwise(ys))
    assert calibrate.relevance(0.0) == 0.5


# --- threshold resolution -----------------------------------------------------


def test_threshold_reads_calibration_file(monkeypatch, tmp_path):
    _calibrated_db(monkeypatch, tmp_path, tau=-4.14)
    assert calibrate.threshold("KI") == -4.14


def test_threshold_env_fallback_when_no_file(monkeypatch, tmp_path):
    monkeypatch.setattr(db_context, "DATA_ROOT", tmp_path)
    db_context.set_active_db("KI")
    monkeypatch.setenv("ABSTAIN_TAU_DEFAULT", "-3.0")
    assert calibrate.threshold("KI") == -3.0


def test_threshold_none_when_uncalibrated(monkeypatch, tmp_path):
    monkeypatch.setattr(db_context, "DATA_ROOT", tmp_path)
    db_context.set_active_db("KI")
    monkeypatch.delenv("ABSTAIN_TAU_DEFAULT", raising=False)
    assert calibrate.threshold("KI") is None


# --- assess: the abstention decision ------------------------------------------


def test_abstains_below_threshold(monkeypatch, tmp_path):
    _calibrated_db(monkeypatch, tmp_path, tau=-4.14)
    confident, rel, closest = calibrate.assess(_hits(-6.0, -5.5), db="KI")
    assert confident is False
    assert closest is not None
    assert closest["source"] == "p1.md"  # best (max) passage of the two
    assert 0.0 < rel < 0.5


def test_confident_above_threshold(monkeypatch, tmp_path):
    _calibrated_db(monkeypatch, tmp_path, tau=-4.14)
    confident, _, _ = calibrate.assess(_hits(-6.0, 2.0), db="KI")
    assert confident is True  # best passage (2.0) clears τ


def test_failsafe_no_rerank_score(monkeypatch, tmp_path):
    """Reranker unavailable / failed open: no rerank_score ⇒ never abstain."""
    _calibrated_db(monkeypatch, tmp_path, tau=-4.14)
    confident, rel, closest = calibrate.assess([{"source": "p.md", "score": 0.9}], db="KI")
    assert confident is True
    assert closest is None
    assert rel == 1.0


def test_failsafe_uncalibrated_db(monkeypatch, tmp_path):
    """No calibration.json and no env default ⇒ never abstain, even on a weak score."""
    monkeypatch.setattr(db_context, "DATA_ROOT", tmp_path)
    db_context.set_active_db("KI")
    monkeypatch.delenv("ABSTAIN_TAU_DEFAULT", raising=False)
    confident, _, _ = calibrate.assess(_hits(-9.0), db="KI")
    assert confident is True


def test_master_switch_off(monkeypatch, tmp_path):
    _calibrated_db(monkeypatch, tmp_path, tau=-4.14)
    monkeypatch.setenv("ABSTAIN_ENABLED", "0")
    confident, _, _ = calibrate.assess(_hits(-9.0), db="KI")
    assert confident is True


# --- justify: the search-ladder rung-4 audit record --------------------------


def test_justify_splits_by_tau_highest_first():
    rec = calibrate.justify([("a", -2.0), ("b", -5.0), ("c", 1.0)], tau=-4.0)
    assert rec["kept"] == [("c", 1.0), ("a", -2.0)]  # sorted high→low, both clear τ
    assert rec["below_tau"] == [("b", -5.0)]
    assert rec["over_cap"] == []
    assert rec["tau"] == -4.0


def test_justify_failopen_on_none_tau_keeps_all():
    rec = calibrate.justify([("a", -9.0), ("b", 0.0)], tau=None)
    assert {n for n, _ in rec["kept"]} == {"a", "b"}
    assert rec["below_tau"] == []


def test_justify_none_score_kept_and_sorted_last():
    rec = calibrate.justify([("scored", -1.0), ("unscored", None)], tau=-4.0)
    assert rec["kept"] == [("scored", -1.0), ("unscored", None)]  # None never below τ, sorts last


def test_justify_cap_moves_surplus_to_over_cap():
    rec = calibrate.justify([("a", 3.0), ("b", 2.0), ("c", 1.0)], tau=-4.0, cap=2)
    assert rec["kept"] == [("a", 3.0), ("b", 2.0)]
    assert rec["over_cap"] == [("c", 1.0)]
