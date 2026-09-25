"""Which GPU a locally-loaded model should sit on — Stage F.

Default policy: keep a model on **one** card whenever it fits. Splitting layers
across cards does not make single-stream decoding faster — the GPUs run
sequentially, each idling while the other works, and every token pays a
cross-device hop. A split buys capacity, not speed, so it is worth taking only
when one card cannot hold the model.

Measured on this box (2x RTX 4090, gemma4:e4b, ctx 8192): llama.cpp 94 -> 170
tok/s and Ollama 149 -> 164 tok/s once placement was pinned. Here it is also a
*stability* fix: a compute graph split across cards is what trips the
GGML_SCHED_MAX_SPLIT_INPUTS assert during ingest synthesis (see `ollama_client`).

Two traps, each one a debugging round-trip:

1. **`CUDA_VISIBLE_DEVICES` alone silently fails for Ollama.** It offers every
   card through CUDA *and* Vulkan, so a card hidden from CUDA reappears as a
   Vulkan device and the model loads there anyway — asking for GPU 1 lands you
   on GPU 0. `OLLAMA_VULKAN=0` (set by `ollama_server`) makes the CUDA filter
   authoritative.
2. **CUDA orders devices fastest-first, not by PCI bus.** Without
   `CUDA_DEVICE_ORDER=PCI_BUS_ID`, index N here need not be nvidia-smi's GPU N.
   `cuda_env()` always sets both, and never one without the other.

OPTIONAL AND GRACEFUL, like the semantic arm and the reranker: no nvidia-smi, a
single card, or a model too big for one card all yield an unpinned `Placement`
and the runtime places the model exactly as it does today.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass

GIB = 1024**3

# Compute buffers, the graph and allocator slack. Rounded up: under-estimating
# means the runtime spills to CPU, which costs far more than an unneeded split.
COMPUTE_OVERHEAD_GIB = 1.0
# Spare VRAM left on the card after the estimate, so a co-tenant process
# (the other apps on this box share these GPUs) does not push us into a spill.
HEADROOM_GIB = 1.0

# Note "0" is NOT an off-switch: it is a valid GPU index, and the whole point of
# the setting is to be able to name a card.
_OFF = ("off", "false", "no", "none")


@dataclass(frozen=True)
class Gpu:
    index: int
    name: str
    total_gib: float
    free_gib: float


@dataclass(frozen=True)
class Placement:
    index: int | None  # None = leave placement to the runtime (i.e. split)
    reason: str

    @property
    def is_pinned(self) -> bool:
        return self.index is not None


def gpus() -> list[Gpu]:
    """The NVIDIA cards nvidia-smi reports, with their *current* free memory.

    Returns [] on any failure — placement is an optimisation, never a reason to
    fail a run."""
    try:
        proc = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=index,name,memory.total,memory.used",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    if proc.returncode != 0:
        return []
    found: list[Gpu] = []
    for line in proc.stdout.strip().splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) != 4:
            continue
        try:
            index, total_mib, used_mib = int(parts[0]), float(parts[2]), float(parts[3])
        except ValueError:
            continue
        found.append(
            Gpu(
                index=index,
                name=parts[1],
                total_gib=total_mib / 1024,
                free_gib=(total_mib - used_mib) / 1024,
            )
        )
    return found


def plan(required_gib: float, mode: str = "auto", headroom_gib: float = HEADROOM_GIB) -> Placement:
    """Pick the card for a model needing `required_gib`.

    `mode` is the raw value of a `*_PIN_GPU` env var: "auto" pins to the emptiest
    card that fits and otherwise leaves the model split; an integer forces that
    card and skips the estimate; "off" disables pinning entirely.
    """
    mode = (mode or "auto").strip().lower() or "auto"
    if mode in _OFF:
        return Placement(None, "pinning disabled")

    devices = gpus()
    if mode != "auto":
        try:
            forced = int(mode)
        except ValueError:
            return Placement(
                None, f"unusable pin setting {mode!r} — expected auto, off or a GPU index"
            )
        if devices and not any(g.index == forced for g in devices):
            return Placement(
                None, f"GPU {forced} is not present — leaving placement to the runtime"
            )
        return Placement(forced, f"pinned to GPU {forced} (requested)")

    if not devices:
        return Placement(None, "no NVIDIA GPU visible — leaving placement to the runtime")
    if len(devices) < 2:
        return Placement(None, f"only one GPU ({devices[0].name}); nothing to split across")

    best = max(devices, key=lambda g: g.free_gib)
    if best.free_gib >= required_gib + headroom_gib:
        return Placement(
            best.index,
            f"fits on GPU {best.index} alone (needs ~{required_gib:.1f} GiB, "
            f"{best.free_gib:.1f} GiB free) — no cross-GPU hop per token",
        )
    return Placement(
        None,
        f"needs ~{required_gib:.1f} GiB but the emptiest card (GPU {best.index}) has "
        f"only {best.free_gib:.1f} GiB free — left split across all GPUs",
    )


def cuda_env(index: int) -> dict[str, str]:
    """Env that makes a child process see exactly one card, as GPU `index`.

    `CUDA_DEVICE_ORDER` is not optional: CUDA's default ordering is fastest-first,
    so without it the filter can select a different card than nvidia-smi's GPU N.
    """
    return {"CUDA_VISIBLE_DEVICES": str(index), "CUDA_DEVICE_ORDER": "PCI_BUS_ID"}
