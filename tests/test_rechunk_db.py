"""scripts/rechunk_db.py: re-split originals whose chunking changed, then re-index."""

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import chunker
import db_context
import lex_index

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "rechunk_db.py"


def _script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("rechunk_db", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["rechunk_db"] = module
    spec.loader.exec_module(module)
    return module


_LAW = "".join(
    f"Nichtamtliches Inhaltsverzeichnis\r\n§ {n} Titel {n}\r\n"
    f"(1) Regel {n} gilt für Rückstände, die bei der Verarbeitung anfallen.\r\n"
    for n in (61, 62, 63)
)


def test_a_statute_chunked_before_plain_headings_were_recognised_is_re_split(wiki_dir):
    raw = db_context.raw_dir()
    (raw / "law.md").write_text(_LAW, encoding="utf-8")
    chunker.write_chunks("law.md", chunker._split_long(_LAW, "", [], 0, "de"))  # no § anchor
    (raw / "note.md").write_text("## A\nText eins.\n## B\nText zwei.\n", encoding="utf-8")
    chunker.write_chunks("note.md", chunker.split((raw / "note.md").read_text()))
    script = _script()
    assert script.rechunk(apply=False) == [("law.md", 1, 3)]  # dry run: nothing written
    assert [c["anchor"] for c in chunker.load_chunks("law.md")] == [""]
    script.rechunk(apply=True)
    assert [c["anchor"] for c in chunker.load_chunks("law.md")] == ["§ 61", "§ 62", "§ 63"]
    assert any(h.get("anchor") == "§ 62" for h in lex_index.query("Regel 62", 5, scope="raw"))
    assert script.rechunk(apply=False) == []
