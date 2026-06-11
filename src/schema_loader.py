"""Load the wiki system prompt.

Two variants:
- ``full`` (default) — the complete SCHEMA.md with page-type templates; used for ingest
  and any call that *writes* structured wiki pages.
- ``query`` — the trimmed SCHEMA_QUERY.md (writing rules + confidence only); used for
  read/answer/describe/lint calls that never emit a full page. Saves prompt budget and
  keeps query context focused.
"""

from pathlib import Path

_BASE = Path(__file__).parent.parent
_SCHEMA_PATH = _BASE / "SCHEMA.md"
_SCHEMA_QUERY_PATH = _BASE / "SCHEMA_QUERY.md"


def get_system_prompt(mode: str = "full") -> str:
    if mode == "query" and _SCHEMA_QUERY_PATH.exists():
        return _SCHEMA_QUERY_PATH.read_text()
    return _SCHEMA_PATH.read_text()
