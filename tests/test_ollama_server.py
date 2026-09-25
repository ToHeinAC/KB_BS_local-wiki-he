"""Stage F — the GPU-pinned Ollama daemon.

No daemon is ever started here: `_spawn` and the health probe are mocked. What is
tested is the contract around them — every failure path returns the configured
host unchanged (fail-open), an already-running pinned daemon is adopted rather
than duplicated, and the child gets the full env the pin actually needs.
"""

import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import gpu_placement
import ollama_server


@pytest.fixture(autouse=True)
def _fresh(monkeypatch):
    """Drop the per-process cache; never let a test reach a real daemon or GPU."""
    monkeypatch.setattr(ollama_server, "_state", None)
    monkeypatch.setattr(ollama_server, "_proc", None)
    monkeypatch.setattr(ollama_server, "_serving", lambda base, **k: False)
    monkeypatch.setattr(ollama_server, "_get_json", lambda url, timeout=3.0: None)
    monkeypatch.setattr(
        gpu_placement,
        "gpus",
        lambda: [
            gpu_placement.Gpu(index=0, name="card0", total_gib=24.0, free_gib=12.0),
            gpu_placement.Gpu(index=1, name="card1", total_gib=24.0, free_gib=22.0),
        ],
    )
    monkeypatch.delenv("OLLAMA_PIN_GPU", raising=False)
    monkeypatch.delenv("OLLAMA_PIN_PORT", raising=False)
    monkeypatch.setenv("OLLAMA_HOST", "http://localhost:11434")


class _FakeProc:
    """A daemon that is alive until told otherwise."""

    def __init__(self, alive: bool = True):
        self.returncode = None if alive else 1
        self.killed = self.terminated = False

    def poll(self):
        return self.returncode

    def terminate(self):
        self.terminated = True
        self.returncode = 0

    def kill(self):
        self.killed = True
        self.returncode = -9

    def wait(self, timeout=None):
        return self.returncode


def _spawns(monkeypatch, proc=None, comes_up=True) -> dict:
    """Record what _spawn was asked for, and whether the daemon came up."""
    seen: dict = {}
    proc = proc or _FakeProc()

    def _fake_spawn(port, gpu_index):
        seen.update(port=port, gpu_index=gpu_index, proc=proc)
        return proc

    monkeypatch.setattr(ollama_server, "_spawn", _fake_spawn)
    monkeypatch.setattr(ollama_server, "_wait_until_serving", lambda p, base, timeout_s: comes_up)
    return seen


# --- host configuration -------------------------------------------------------


def test_configured_host_normalises_a_bare_hostport(monkeypatch):
    monkeypatch.setenv("OLLAMA_HOST", "127.0.0.1:11434")
    assert ollama_server.configured_host() == "http://127.0.0.1:11434"


def test_configured_host_falls_back_when_unset_or_blank(monkeypatch):
    monkeypatch.delenv("OLLAMA_HOST", raising=False)
    assert ollama_server.configured_host() == ollama_server.DEFAULT_HOST
    monkeypatch.setenv("OLLAMA_HOST", "   ")
    assert ollama_server.configured_host() == ollama_server.DEFAULT_HOST


# --- the fail-open paths ------------------------------------------------------


def test_a_remote_ollama_host_is_never_hijacked(monkeypatch):
    monkeypatch.setenv("OLLAMA_HOST", "http://gpu-box.lan:11434")
    _spawns(monkeypatch)  # would be a bug to call
    status = ollama_server.status()
    assert status["host"] == "http://gpu-box.lan:11434"
    assert not status["pinned"]
    assert "remote" in status["reason"]


def test_pinning_off_uses_the_configured_host(monkeypatch):
    monkeypatch.setenv("OLLAMA_PIN_GPU", "off")
    _spawns(monkeypatch)
    status = ollama_server.status()
    assert status["host"] == "http://localhost:11434"
    assert not status["pinned"]


def test_a_model_too_big_for_one_card_stays_on_the_shared_daemon(monkeypatch):
    monkeypatch.setattr(ollama_server, "required_gib", lambda host: 40.0)
    _spawns(monkeypatch)
    status = ollama_server.status()
    assert status["host"] == "http://localhost:11434"
    assert not status["pinned"]
    assert "split" in status["reason"]


def test_a_missing_ollama_binary_falls_back(monkeypatch):
    monkeypatch.setattr(ollama_server, "_spawn", lambda port, gpu_index: None)
    status = ollama_server.status()
    assert status["host"] == "http://localhost:11434"
    assert not status["pinned"]
    assert "PATH" in status["reason"]


def test_a_daemon_that_never_comes_up_is_killed_and_falls_back(monkeypatch):
    proc = _FakeProc()
    _spawns(monkeypatch, proc=proc, comes_up=False)
    status = ollama_server.status()
    assert status["host"] == "http://localhost:11434"
    assert not status["pinned"]
    assert proc.killed, "a daemon that never answered must not be left running"
    assert ollama_server._proc is None


# --- the pinned paths ---------------------------------------------------------


def test_starts_a_pinned_daemon_on_the_emptiest_card(monkeypatch):
    seen = _spawns(monkeypatch)
    status = ollama_server.status()
    assert status["host"] == f"http://127.0.0.1:{ollama_server.DEFAULT_PORT}"
    assert status["pinned"]
    assert status["gpu"] == 1
    assert status["managed"]
    assert seen["gpu_index"] == 1
    assert seen["port"] == ollama_server.DEFAULT_PORT
    assert ollama_server._proc is seen["proc"]


def test_pin_gpu_can_name_a_card_explicitly(monkeypatch):
    monkeypatch.setenv("OLLAMA_PIN_GPU", "0")
    seen = _spawns(monkeypatch)
    assert ollama_server.status()["gpu"] == 0
    assert seen["gpu_index"] == 0


def test_port_is_configurable(monkeypatch):
    monkeypatch.setenv("OLLAMA_PIN_PORT", "11999")
    seen = _spawns(monkeypatch)
    assert ollama_server.status()["host"].endswith(":11999")
    assert seen["port"] == 11999


def test_a_nonsense_port_falls_back_to_the_default(monkeypatch):
    monkeypatch.setenv("OLLAMA_PIN_PORT", "not-a-port")
    seen = _spawns(monkeypatch)
    ollama_server.status()
    assert seen["port"] == ollama_server.DEFAULT_PORT


def test_an_existing_pinned_daemon_is_adopted_not_duplicated(monkeypatch):
    monkeypatch.setattr(ollama_server, "_serving", lambda base, **k: True)
    monkeypatch.setattr(
        ollama_server, "_spawn", lambda *a, **k: pytest.fail("must not start a second daemon")
    )
    status = ollama_server.status()
    assert status["pinned"]
    assert status["host"].endswith(str(ollama_server.DEFAULT_PORT))
    assert not status["managed"]
    assert "reusing" in status["reason"]
    assert ollama_server._proc is None


def test_resolution_is_cached_for_the_process(monkeypatch):
    calls = []
    _spawns(monkeypatch)
    original = ollama_server._spawn

    def _counted(port, gpu_index):
        calls.append(port)
        return original(port, gpu_index)

    monkeypatch.setattr(ollama_server, "_spawn", _counted)
    first, second = ollama_server.host(), ollama_server.host()
    assert first == second
    assert len(calls) == 1


# --- shutdown -----------------------------------------------------------------


def test_stop_terminates_a_daemon_we_own(monkeypatch):
    seen = _spawns(monkeypatch)
    ollama_server.status()
    ollama_server.stop()
    assert seen["proc"].terminated
    assert ollama_server._proc is None


def test_stop_leaves_an_adopted_daemon_running(monkeypatch):
    monkeypatch.setattr(ollama_server, "_serving", lambda base, **k: True)
    ollama_server.status()
    ollama_server.stop()  # must not raise; nothing of ours to reap


def test_stop_kills_a_daemon_that_ignores_terminate(monkeypatch):
    class _Stubborn(_FakeProc):
        def terminate(self):
            self.terminated = True  # stays alive

        def wait(self, timeout=None):
            if not self.killed:
                raise subprocess.TimeoutExpired("ollama", timeout or 0.0)
            return -9

    proc = _Stubborn()
    _spawns(monkeypatch, proc=proc)
    ollama_server.status()
    ollama_server.stop()
    assert proc.killed


# --- the model store and the size estimate ------------------------------------


def test_find_models_dir_prefers_the_store_with_the_most_manifests(monkeypatch, tmp_path):
    empty, full = tmp_path / "empty", tmp_path / "full"
    (empty / "manifests").mkdir(parents=True)
    (full / "manifests" / "registry" / "library").mkdir(parents=True)
    for name in ("a", "b", "c"):
        (full / "manifests" / "registry" / "library" / name).write_text("{}")
    monkeypatch.setattr(ollama_server, "_store_candidates", lambda: (str(empty), str(full)))
    assert ollama_server.find_models_dir() == str(full)


def test_find_models_dir_is_none_when_no_store_has_models(monkeypatch, tmp_path):
    monkeypatch.setattr(
        ollama_server,
        "_store_candidates",
        lambda: (None, str(tmp_path / "nope"), str(tmp_path / "also-nope")),
    )
    assert ollama_server.find_models_dir() is None


def test_configured_models_covers_every_role(monkeypatch):
    monkeypatch.setenv("OLLAMA_MODEL", "main:1b")
    monkeypatch.setenv("INGEST_MODEL", "ingest:2b")
    monkeypatch.setenv("QUERY_MODEL", "")  # unset roles fall back to OLLAMA_MODEL
    names = ollama_server.configured_models()
    assert {"main:1b", "ingest:2b"} <= names
    assert "" not in names


def test_required_gib_sums_distinct_models_plus_overhead(monkeypatch):
    for key in ("QUERY_MODEL", "INGEST_MODEL", "FAST_MODEL"):
        monkeypatch.setenv(key, "main:1b")  # same model in three roles
    monkeypatch.setenv("OLLAMA_MODEL", "main:1b")
    monkeypatch.setenv("EMBED_MODEL", "embed:1b")
    monkeypatch.setenv("REWRITE_MODEL", "main:1b")
    monkeypatch.setenv("OCR_MODEL", "main:1b")
    monkeypatch.setattr(
        ollama_server,
        "_get_json",
        lambda url, timeout=3.0: {
            "models": [
                {"name": "main:1b", "size": 4 * gpu_placement.GIB},
                {"name": "embed:1b", "size": 1 * gpu_placement.GIB},
                {"name": "unused:70b", "size": 40 * gpu_placement.GIB},
            ]
        },
    )
    assert ollama_server.required_gib("http://x") == pytest.approx(
        5.0 + gpu_placement.COMPUTE_OVERHEAD_GIB
    )


def test_required_gib_survives_an_unreachable_daemon(monkeypatch):
    monkeypatch.setattr(ollama_server, "_get_json", lambda url, timeout=3.0: None)
    # Only the overhead is left, so pinning still goes ahead: with no daemon
    # answering, ours is the app's only LLM.
    assert ollama_server.required_gib("http://x") == gpu_placement.COMPUTE_OVERHEAD_GIB


def test_a_model_never_pulled_contributes_nothing(monkeypatch):
    monkeypatch.setenv("OLLAMA_MODEL", "absent:1b")
    monkeypatch.setattr(ollama_server, "_get_json", lambda url, timeout=3.0: {"models": []})
    assert ollama_server.required_gib("http://x") == gpu_placement.COMPUTE_OVERHEAD_GIB


def test_latest_suffix_matches_either_way(monkeypatch):
    monkeypatch.setenv("OLLAMA_MODEL", "vendor/m")
    for key in ("QUERY_MODEL", "INGEST_MODEL", "FAST_MODEL", "REWRITE_MODEL", "OCR_MODEL"):
        monkeypatch.setenv(key, "vendor/m")
    monkeypatch.setenv("EMBED_MODEL", "vendor/m")
    monkeypatch.setattr(
        ollama_server,
        "_get_json",
        lambda url, timeout=3.0: {
            "models": [
                {"name": "vendor/m:latest", "size": 2 * gpu_placement.GIB},
            ]
        },
    )
    assert ollama_server.required_gib("http://x") == pytest.approx(
        2.0 + gpu_placement.COMPUTE_OVERHEAD_GIB
    )


# --- spawning and waiting (no real process) -----------------------------------


def test_spawn_needs_the_ollama_binary(monkeypatch):
    monkeypatch.setattr(ollama_server.shutil, "which", lambda name: None)
    assert ollama_server._spawn(11435, 1) is None


def test_spawn_pins_the_daemon(monkeypatch, tmp_path):
    started = {}
    monkeypatch.setattr(ollama_server.shutil, "which", lambda name: "/usr/bin/ollama")
    monkeypatch.setattr(ollama_server, "find_models_dir", lambda: str(tmp_path))
    monkeypatch.setattr(
        ollama_server.subprocess, "Popen", lambda cmd, **kw: started.update(cmd=cmd, **kw) or "proc"
    )
    assert ollama_server._spawn(11435, 1) == "proc"
    env = started["env"]
    assert started["cmd"] == ["/usr/bin/ollama", "serve"]
    assert env["OLLAMA_HOST"] == "127.0.0.1:11435"
    assert env["OLLAMA_VULKAN"] == "0"
    assert env["OLLAMA_NUM_PARALLEL"] == "1"
    assert env["OLLAMA_MODELS"] == str(tmp_path)
    assert started["start_new_session"] is True


def test_spawn_os_error_returns_none(monkeypatch):
    def boom(*a, **k):
        raise OSError("exec format error")

    monkeypatch.setattr(ollama_server.shutil, "which", lambda name: "/usr/bin/ollama")
    monkeypatch.setattr(ollama_server, "find_models_dir", lambda: None)
    monkeypatch.setattr(ollama_server.subprocess, "Popen", boom)
    assert ollama_server._spawn(11435, 0) is None


def test_wait_until_serving(monkeypatch):
    monkeypatch.setattr(ollama_server.time, "sleep", lambda s: None)
    monkeypatch.setattr(ollama_server, "_serving", lambda base: True)
    alive: Any = _FakeProc()
    dead: Any = _FakeProc(alive=False)
    assert ollama_server._wait_until_serving(alive, "b", 5.0) is True
    assert ollama_server._wait_until_serving(dead, "b", 5.0) is False
    monkeypatch.setattr(ollama_server, "_serving", lambda base: False)
    clock = iter([0.0, 1.0, 10.0])
    monkeypatch.setattr(ollama_server.time, "monotonic", lambda: next(clock))
    assert ollama_server._wait_until_serving(alive, "b", 5.0) is False


def test_reset_drops_the_cached_state(monkeypatch):
    stopped = []
    monkeypatch.setattr(ollama_server, "_state", {"host": "x"})
    monkeypatch.setattr(ollama_server, "stop", lambda: stopped.append(True))
    ollama_server.reset()
    assert ollama_server._state is None
    assert stopped == [True]


def test_models_dir_prefers_the_fullest_store(monkeypatch, tmp_path):
    empty, full = tmp_path / "empty", tmp_path / "full"
    (empty / "manifests").mkdir(parents=True)
    (full / "manifests" / "lib").mkdir(parents=True)
    (full / "manifests" / "lib" / "m1").write_text("")
    monkeypatch.setattr(
        ollama_server,
        "_store_candidates",
        lambda: (None, str(empty), str(tmp_path / "x"), str(full)),
    )
    assert ollama_server.find_models_dir() == str(full)
