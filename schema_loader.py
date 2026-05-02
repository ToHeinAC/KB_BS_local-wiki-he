"""Load SCHEMA.md as the base system prompt for all wiki LLM calls."""

from pathlib import Path

_SCHEMA_PATH = Path(__file__).parent / "SCHEMA.md"


def get_system_prompt() -> str:
    return _SCHEMA_PATH.read_text()
