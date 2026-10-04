"""Start the LocalWiki server for the frontend chosen by `FRONTEND` in `.env`.

`broadsheet` (the default) runs the NiceGUI app (src/gui_app.py); `default` or `newspaper`
runs the Streamlit app (src/app.py) with that skin. Both serve port 8520 under /wiwi. The
process is replaced (`exec`), so the server's PID is the one you stop; see docs/ui.md. Before
it starts, `scripts/heal_indexes.py` rebuilds any search index that is missing.

Usage:
    uv run python scripts/run_app.py [--port 8520]
"""

from __future__ import annotations

import argparse
import os
import subprocess
from pathlib import Path

from dotenv import load_dotenv

DEFAULT_FRONTEND = "broadsheet"
DEFAULT_PORT = 8520
ROOT = Path(__file__).resolve().parent.parent
HEAL = ["uv", "run", "python", "scripts/heal_indexes.py"]


def command(frontend: str, port: int) -> list[str]:
    """The argv that serves `frontend` on `port` (run from the repository root)."""
    if frontend.strip().lower() == "broadsheet":
        return ["uv", "run", "python", "src/gui_app.py", "--port", str(port)]
    return [
        "uv", "run", "streamlit", "run", "src/app.py",
        "--server.port", str(port), "--server.headless", "true",
    ]  # fmt: skip


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    port = parser.parse_args().port
    load_dotenv(ROOT / ".env")
    argv = command(os.getenv("FRONTEND", DEFAULT_FRONTEND), port)
    os.chdir(ROOT)
    subprocess.run(HEAL, check=False)  # rebuild missing search indexes first; never blocks a start
    os.execvp(argv[0], argv)


if __name__ == "__main__":
    main()
