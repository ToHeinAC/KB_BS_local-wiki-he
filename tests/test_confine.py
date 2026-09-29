"""Path confinement: a page or raw name can never resolve outside its own directory.

Names reach the readers from LLM output (tool arguments, page selection), so a
`../` or absolute name must behave exactly like a missing file — never read a
sibling DB or anything else on disk.
"""

import pytest

import db_context
import tools
import wiki_engine

CANARY = "zebraquartz7731"


@pytest.fixture
def sibling_secret(tmp_path, monkeypatch):
    """Active DB `Alpha` (empty) next to DB `Beta` holding a canary page and raw file."""
    monkeypatch.setattr(db_context, "DATA_ROOT", tmp_path)
    for db in ("Alpha", "Beta"):
        for sub in ("raw", "chunks", "index", "wiki"):
            (tmp_path / db / sub).mkdir(parents=True, exist_ok=True)
    (tmp_path / "Beta" / "wiki" / "secret.md").write_text(f"---\ntitle: S\n---\n{CANARY}\n")
    (tmp_path / "Beta" / "raw" / "secret.md").write_text(f"# Secret\n{CANARY}\n")
    db_context.set_active_db("Alpha")
    db_context.set_search_scope([])
    return tmp_path


def _escapes(root) -> list[str]:
    return [
        "../../Beta/wiki/secret.md",
        "../../Beta/raw/secret.md",
        "../Beta/raw/secret.md",
        str(root / "Beta" / "wiki" / "secret.md"),
        str(root / "Beta" / "raw" / "secret.md"),
    ]


def test_confine_accepts_names_inside_base(tmp_path):
    assert db_context.confine(tmp_path, "a.md") == (tmp_path / "a.md").resolve()
    assert db_context.confine(tmp_path, "insights/a.md") == (tmp_path / "insights/a.md").resolve()


@pytest.mark.parametrize("name", ["../a.md", "x/../../a.md", "/etc/passwd", ""])
def test_confine_rejects_names_outside_base(tmp_path, name):
    with pytest.raises(db_context.AccessDenied):
        db_context.confine(tmp_path / "wiki", name)


def test_page_readers_treat_escaping_names_as_missing(sibling_secret):
    for name in _escapes(sibling_secret):
        assert CANARY not in wiki_engine.read_page(name)
        assert CANARY not in wiki_engine.read_page_parsed(name)["content"]
        assert wiki_engine.read_raw_source(name) is None


def test_read_tools_cannot_traverse_into_a_sibling_db(sibling_secret):
    for name in _escapes(sibling_secret):
        assert CANARY not in tools.wiki_read.invoke({"filenames": [name]})
        assert CANARY not in tools.raw_read.invoke({"filenames": [name]})


def test_denied_name_reads_exactly_like_a_missing_one(sibling_secret):
    """No existence oracle: the reply for an escaping name matches a plain miss."""
    denied = wiki_engine.read_page("../../Beta/wiki/secret.md")
    missing = wiki_engine.read_page("../../Beta/wiki/nothing.md")
    assert denied.replace("secret", "X") == missing.replace("nothing", "X")


def test_llm_page_selection_cannot_escape_the_wiki(sibling_secret, monkeypatch):
    monkeypatch.setattr(wiki_engine, "_candidate_pages_for_query", lambda _q: [])
    monkeypatch.setattr(
        wiki_engine.ollama_client, "generate", lambda *_a, **_k: "../../Beta/wiki/secret.md"
    )
    assert wiki_engine._select_pages("q", "sys", "index") == []
