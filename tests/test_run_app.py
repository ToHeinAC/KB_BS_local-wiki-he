"""The launcher picks the server from FRONTEND (docs/ui.md): NiceGUI or Streamlit."""

import importlib.util
import sys
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


def test_default_frontend_is_streamlit_until_cutover() -> None:
    assert _load().DEFAULT_FRONTEND == "default"
