"""The launcher picks the server from FRONTEND (docs/ui.md): NiceGUI or Streamlit."""

import importlib.util
import re
import subprocess
import sys
import time
from pathlib import Path
from types import ModuleType

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "run_app.py"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("run_app", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["run_app"] = module
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("frontend", ["broadsheet", " Broadsheet "])
def test_broadsheet_starts_the_nicegui_app(frontend: str) -> None:
    cmd = _load().command(frontend, 8520)
    assert cmd[-3:] == ["src/gui_app.py", "--port", "8520"]
    assert "streamlit" not in cmd


@pytest.mark.parametrize("frontend", ["default", "newspaper", "", "unknown"])
def test_everything_else_starts_streamlit_on_the_same_port(frontend: str) -> None:
    cmd = _load().command(frontend, 8520)
    assert cmd[1:5] == ["run", "streamlit", "run", "src/app.py"]
    assert cmd[cmd.index("--server.port") + 1] == "8520"
    assert "--server.headless" in cmd


def test_the_broadsheet_frontend_is_the_default() -> None:
    assert _load().DEFAULT_FRONTEND == "broadsheet"


# --- the launch scripts find either server by one pattern -------------------------------

ROOT = SCRIPT.parents[1]
SCRIPTS = [ROOT / "tunnel.sh", ROOT / ".claude/skills/restart-app/scripts/restart_app.sh"]


def _pattern(script: Path) -> re.Pattern[str]:
    line = next(ln for ln in script.read_text().splitlines() if ln.startswith("APP_PATTERN="))
    return re.compile(line.split("=", 1)[1].strip("'\"").replace("$PORT", "8520"))


@pytest.mark.parametrize("script", SCRIPTS, ids=lambda p: p.name)
def test_the_app_pattern_matches_both_servers_and_never_the_tunnel(script: Path) -> None:
    pattern = _pattern(script)
    for frontend in ("broadsheet", "default"):
        argv = " ".join(_load().command(frontend, 8520))
        assert pattern.search(argv), argv
    for other in (
        "cloudflared tunnel --url http://localhost:8520",
        "uv run streamlit run src/app.py --server.port 8511",
        "python src/gui_app.py --port 85201",
    ):
        assert not pattern.search(other), other


@pytest.mark.parametrize("script", SCRIPTS, ids=lambda p: p.name)
def test_the_scripts_launch_through_the_frontend_launcher(script: Path) -> None:
    text = script.read_text()
    assert "scripts/run_app.py" in text
    assert "streamlit run src/app.py --server.port" not in text


def _relaunch_block(script: str) -> str:
    """The restart script's relaunch command (from the `run_app.py` line to its closing `&`)."""
    lines = script.splitlines()
    start = next(i for i, ln in enumerate(lines) if "scripts/run_app.py" in ln)
    end = next(i for i in range(start, len(lines)) if lines[i].rstrip().endswith(("&", "& )")))
    return "\n".join(lines[start : end + 1])


def test_restart_relaunch_releases_the_scripts_output(tmp_path: Path) -> None:
    """The relaunch must not leave a subshell holding the caller's stdout: whoever reads the
    script's output (a pipe, a tool) would otherwise wait until the app exits."""
    block = (
        _relaunch_block(SCRIPTS[1].read_text())
        .replace('uv run python scripts/run_app.py --port "$PORT"', "sleep 3")
        .replace('"$REPO"', str(tmp_path))
        .replace('"$APP_LOG"', str(tmp_path / "app.log"))
    )
    runnable = tmp_path / "launch.sh"
    runnable.write_text(block + "\necho launched\n")
    started = time.monotonic()
    out = subprocess.run(["bash", str(runnable)], capture_output=True, text=True, timeout=10)
    assert out.stdout.strip() == "launched"
    assert time.monotonic() - started < 2


def test_the_launcher_heals_missing_indexes_before_the_server_starts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load()
    started: list[list[str]] = []
    monkeypatch.setattr(module.subprocess, "run", lambda argv, **_k: started.append(argv))
    monkeypatch.setattr(module.os, "execvp", lambda *_a: started.append(["exec"]))
    monkeypatch.setattr(module.os, "chdir", lambda _p: None)
    monkeypatch.setattr(sys, "argv", ["run_app.py"])
    module.main()
    assert started == [["uv", "run", "python", "scripts/heal_indexes.py"], ["exec"]]
