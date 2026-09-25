"""Stage F — single-GPU placement policy.

nvidia-smi is never actually run: `gpus()` is mocked so the suite gives the same
answer on a two-card box, a one-card box and CI with no GPU at all. What is
tested is the policy — pin when it fits, stay split when it does not, and
degrade to unpinned on every unusual input.
"""

import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import gpu_placement
from gpu_placement import Gpu

SMI_TWO_CARDS = "0, NVIDIA GeForce RTX 4090, 24564, 1075\n1, NVIDIA GeForce RTX 4090, 24564, 918\n"


def _cards(*free_gib: float) -> list[Gpu]:
    return [
        Gpu(index=i, name=f"card{i}", total_gib=24.0, free_gib=f) for i, f in enumerate(free_gib)
    ]


def _fake_gpus(monkeypatch, cards: list[Gpu]) -> None:
    monkeypatch.setattr(gpu_placement, "gpus", lambda: cards)


# --- device discovery ---------------------------------------------------------


def test_gpus_parses_nvidia_smi(monkeypatch):
    monkeypatch.setattr(
        subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a, 0, SMI_TWO_CARDS, "")
    )
    cards = gpu_placement.gpus()
    assert [c.index for c in cards] == [0, 1]
    assert cards[0].name == "NVIDIA GeForce RTX 4090"
    assert cards[0].total_gib == pytest.approx(23.99, abs=0.01)
    # free = total - used, so card 1 (less used) is the emptier one
    assert cards[1].free_gib > cards[0].free_gib


def test_gpus_survives_a_missing_nvidia_smi(monkeypatch):
    def _boom(*a, **k):
        raise FileNotFoundError("nvidia-smi")

    monkeypatch.setattr(subprocess, "run", _boom)
    assert gpu_placement.gpus() == []


def test_gpus_ignores_unparseable_rows(monkeypatch):
    noisy = SMI_TWO_CARDS + "[N/A], broken row\n2, card, N/A, N/A\n"
    monkeypatch.setattr(
        subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a, 0, noisy, "")
    )
    assert [c.index for c in gpu_placement.gpus()] == [0, 1]


def test_gpus_empty_on_nonzero_exit(monkeypatch):
    monkeypatch.setattr(
        subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a, 9, "", "no driver")
    )
    assert gpu_placement.gpus() == []


# --- policy -------------------------------------------------------------------


def test_pins_to_the_emptiest_card_that_fits(monkeypatch):
    _fake_gpus(monkeypatch, _cards(12.0, 22.0))
    placement = gpu_placement.plan(10.0)
    assert placement.index == 1
    assert placement.is_pinned
    assert "fits on GPU 1" in placement.reason


def test_stays_split_when_no_card_can_hold_it(monkeypatch):
    _fake_gpus(monkeypatch, _cards(12.0, 14.0))
    placement = gpu_placement.plan(20.0)
    assert placement.index is None
    assert not placement.is_pinned
    assert "split" in placement.reason


def test_headroom_is_required_on_top_of_the_estimate(monkeypatch):
    _fake_gpus(monkeypatch, _cards(1.0, 10.5))
    # 10.0 needed + 1.0 headroom > 10.5 free
    assert gpu_placement.plan(10.0).index is None
    assert gpu_placement.plan(10.0, headroom_gib=0.0).index == 1


def test_off_disables_pinning(monkeypatch):
    _fake_gpus(monkeypatch, _cards(22.0, 22.0))
    for mode in ("off", "false", "no", "none", "OFF"):
        assert gpu_placement.plan(1.0, mode).index is None


def test_zero_names_gpu_zero_and_is_not_an_off_switch(monkeypatch):
    _fake_gpus(monkeypatch, _cards(22.0, 22.0))
    assert gpu_placement.plan(1.0, "0").index == 0


def test_blank_and_none_mean_auto(monkeypatch):
    _fake_gpus(monkeypatch, _cards(12.0, 22.0))
    assert gpu_placement.plan(1.0, "").index == 1
    assert gpu_placement.plan(1.0, None).index == 1


def test_explicit_index_skips_the_estimate(monkeypatch):
    _fake_gpus(monkeypatch, _cards(2.0, 2.0))
    placement = gpu_placement.plan(999.0, "0")
    assert placement.index == 0
    assert "requested" in placement.reason


def test_explicit_index_that_is_not_present_is_refused(monkeypatch):
    _fake_gpus(monkeypatch, _cards(22.0, 22.0))
    assert gpu_placement.plan(1.0, "7").index is None


def test_unusable_mode_degrades_instead_of_raising(monkeypatch):
    _fake_gpus(monkeypatch, _cards(22.0, 22.0))
    placement = gpu_placement.plan(1.0, "gpu1")
    assert placement.index is None
    assert "expected auto" in placement.reason


def test_single_card_is_left_alone(monkeypatch):
    _fake_gpus(monkeypatch, _cards(22.0))
    placement = gpu_placement.plan(1.0)
    assert placement.index is None
    assert "nothing to split across" in placement.reason


def test_no_gpu_at_all_is_left_alone(monkeypatch):
    _fake_gpus(monkeypatch, [])
    assert gpu_placement.plan(1.0).index is None


# --- child-process env --------------------------------------------------------


def test_cuda_env_always_pins_the_ordering_too():
    """CUDA_VISIBLE_DEVICES without PCI_BUS_ID can select a different card."""
    env = gpu_placement.cuda_env(1)
    assert env == {"CUDA_VISIBLE_DEVICES": "1", "CUDA_DEVICE_ORDER": "PCI_BUS_ID"}
