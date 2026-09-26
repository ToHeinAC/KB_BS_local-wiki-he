"""The ontology stage in every search path (plan Phase 4: S1 retrieval, S2 briefing, S3 tool)."""

from pathlib import Path
from typing import Any

import frontmatter
import pytest
from langchain_core.messages import AIMessage, SystemMessage

import agent
import chat_agent
import chunker
import lex_index
import ollama_client
import ontology
import ontology_query
import ontology_store
import retrieval
import run_memory
import tools
import wiki_engine

STRLSCHG = """\
## § 78 Grenzwerte für beruflich exponierte Personen
Der Grenzwert der effektiven Dosis beträgt 20 Millisievert. Näheres regelt die StrlSchV.
Die StrlSchV bestimmt auch die Überwachung nach StrlSchV.
"""
STRLSCHV = """\
## § 55 Überwachung der Grenzwerte
Die Einhaltung der Grenzwerte wird durch Messung überwacht.

## § 56 Aufzeichnungen
Die Messwerte sind aufzuzeichnen und fünf Jahre aufzubewahren.
"""
QUESTION = "Grenzwerte nach StrlSchV"


def _page(wiki: Path, name: str, sources: list[str], body: str) -> None:
    post = frontmatter.Post(body, title=name, type="concept", sources=sources)
    (wiki / name).write_text(frontmatter.dumps(post) + "\n")


def _facts() -> None:
    def rule(subject: str, pred: str, obj: str) -> dict[str, Any]:
        return ontology.assertion(subject, pred, obj, by="rule")

    ontology_store.append_rows(
        [
            rule("src:StrlSchV.md", "class", "ordinance"),
            rule("src:StrlSchV.md", "work", "de-strlschv-2018"),
            rule("src:StrlSchG.md", "class", "federal-act"),
            rule("src:StrlSchG.md", "work", "de-strlschg-2017"),
            rule("work:de-strlschv-2018", "aliases", "StrlSchV"),
            rule("work:de-strlschv-2018", "aliases", "Strahlenschutzverordnung"),
            rule("work:de-strlschg-2017", "aliases", "StrlSchG"),
        ]
    )


@pytest.fixture
def corpus(wiki_dir: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Two laws; the statute mentions "StrlSchV" often, the ordinance never names itself."""
    monkeypatch.setenv("RERANK_ENABLED", "0")  # never load a local cross-encoder in tests
    chunker.write_chunks("StrlSchG.md", chunker.split(STRLSCHG))
    chunker.write_chunks("StrlSchV.md", chunker.split(STRLSCHV))
    _page(wiki_dir, "grenzwerte-g.md", ["StrlSchG.md"], "Grenzwerte: StrlSchV StrlSchV StrlSchV.")
    _page(wiki_dir, "ueberwachung.md", ["StrlSchV.md §55"], "Die Grenzwerte werden überwacht.")
    lex_index.build()
    return wiki_dir


@pytest.fixture
def onto(corpus: Path) -> Path:
    ontology_store.binding_path().write_text("modules: [core, legal-de]\n")
    _facts()
    return corpus


def _sources(hits: list[dict[str, Any]]) -> list[str]:
    return [h["source"] for h in hits]


# --- view and adapter --------------------------------------------------------------------


def test_view_is_none_without_ontology_and_cached_until_facts_change(corpus: Path) -> None:
    assert ontology_store.view() is None
    ontology_store.binding_path().write_text("modules: [core, legal-de]\n")
    _facts()
    first = ontology_store.view()
    assert first is not None
    assert ontology_store.view() is first
    ontology_store.append_rows([ontology.assertion("src:x.md", "class", "report", by="rule")])
    second = ontology_store.view()
    assert second is not first
    assert second is not None
    assert "x.md" in second.sources


def test_lexical_query_can_be_restricted_to_sources(corpus: Path) -> None:
    hits = lex_index.query("Grenzwerte", top_k=10, scope="raw", sources=["StrlSchV.md"])
    assert set(_sources(hits)) == {"StrlSchV.md"}
    assert lex_index.query("Grenzwerte", scope="raw", sources=[]) == []


# --- S1: retrieval.search and search_wiki ------------------------------------------------


def test_naming_a_work_lifts_its_own_chunks(onto: Path) -> None:
    off = retrieval.search(QUESTION, top_k=5, scope="raw", use_ontology=False)
    on = retrieval.search(QUESTION, top_k=5, scope="raw")
    assert _sources(off)[0] == "StrlSchG.md"
    assert _sources(on)[0] == "StrlSchV.md"
    assert set(_sources(on)) >= set(_sources(off))  # reorders and adds, never drops


def test_a_class_word_boosts_but_never_removes(onto: Path) -> None:
    on = retrieval.search("Grenzwerte Rechtsverordnung", top_k=5, scope="raw")
    assert _sources(on)[0] == "StrlSchV.md"
    assert "StrlSchG.md" in _sources(on)


def test_without_ontology_search_is_byte_identical(corpus: Path) -> None:
    baseline = lex_index.query(QUESTION, top_k=40, scope="raw")[:5]
    assert retrieval.search(QUESTION, top_k=5, scope="raw") == baseline


def test_a_question_naming_nothing_is_unchanged(onto: Path) -> None:
    q = "Messwerte aufbewahren"
    assert retrieval.search(q, top_k=5, scope="raw") == retrieval.search(
        q, top_k=5, scope="raw", use_ontology=False
    )


def test_every_search_path_resolves_exactly_once(
    onto: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []
    real = ontology_query.resolve

    def spy(q: str, view: ontology_query.View) -> ontology_query.QueryFrame | None:
        calls.append(q)
        return real(q, view)

    monkeypatch.setattr(ontology_query, "resolve", spy)
    retrieval.search(QUESTION, scope="raw")
    assert calls == [QUESTION]
    wiki_engine.search_wiki(QUESTION)
    assert calls == [QUESTION, QUESTION]


def test_wiki_search_lifts_pages_citing_the_work(onto: Path) -> None:
    assert wiki_engine.search_wiki(QUESTION)[0]["filename"] == "ueberwachung.md"
    assert retrieval.last_frame() == {
        "matched": ["StrlSchV"],
        "works": ["de-strlschv-2018"],
        "classes": [],
        "sources": ["StrlSchV.md"],
    }


# --- tools: badges and ontology_lookup (S3) ----------------------------------------------


def test_raw_hits_carry_an_ontology_badge(onto: Path) -> None:
    out = tools.TOOL_FUNCTIONS["raw_search"](query=QUESTION, max_results=3)
    assert "ontology: ordinance · de-strlschv-2018" in out


def test_raw_hits_have_no_badge_without_ontology(corpus: Path) -> None:
    assert "ontology:" not in tools.TOOL_FUNCTIONS["raw_search"](query=QUESTION, max_results=3)


def test_lookup_tool_is_offered_only_with_an_ontology(corpus: Path) -> None:
    assert tools.with_ontology(tools.CHAT_TOOLS) == tools.CHAT_TOOLS
    ontology_store.binding_path().write_text("modules: [core]\n")
    assert tools.with_ontology(tools.CHAT_TOOLS)[-1] is tools.ontology_lookup


def test_lookup_tool_answers_and_dedupes(onto: Path) -> None:
    run_memory.begin_run()
    first = tools.ontology_lookup.invoke({"term": "StrlSchV"})
    assert "Work de-strlschv-2018" in first
    assert "StrlSchV.md" in first
    assert "[memory]" in tools.ontology_lookup.invoke({"term": "strlschv "})


# --- S2: briefings, and the audit record ------------------------------------------------


class _FakeLLM:
    def __init__(self) -> None:
        self.calls: list[list[Any]] = []

    def invoke(self, messages: list[Any]) -> AIMessage:
        self.calls.append(messages)
        return AIMessage(content="done")


def _system_text(fake: _FakeLLM) -> str:
    return str(next(m.content for m in fake.calls[0] if isinstance(m, SystemMessage)))


@pytest.mark.parametrize("module", [chat_agent, agent])
def test_agents_get_the_briefing_before_their_first_call(
    onto: Path, monkeypatch: pytest.MonkeyPatch, module: Any
) -> None:
    fake = _FakeLLM()
    monkeypatch.setattr(module, "_build_llm", lambda: fake)
    monkeypatch.setattr(ollama_client, "generate", lambda *a, **k: "fallback")
    run = module.run_chat_agent if module is chat_agent else module.run_research_agent
    steps = list(run(QUESTION))
    assert "Ontology frame" in _system_text(fake)
    assert "de-strlschv-2018" in _system_text(fake)
    assert any(s["type"] == "ontology" for s in steps)
    audit = tools.current_run_audit()
    assert audit is not None
    assert audit["ontology"][0]["works"] == ["de-strlschv-2018"]


def test_agents_get_no_briefing_when_nothing_is_named(
    onto: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = _FakeLLM()
    monkeypatch.setattr(chat_agent, "_build_llm", lambda: fake)
    monkeypatch.setattr(ollama_client, "generate", lambda *a, **k: "fallback")
    steps = list(chat_agent.run_chat_agent("Wie lange sind Messwerte aufzubewahren?"))
    assert "Ontology frame" not in _system_text(fake)
    assert not any(s["type"] == "ontology" for s in steps)


def test_quick_chat_synthesis_gets_the_briefing_and_the_audit(
    onto: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    systems: list[str] = []

    def fake(system: str, prompt: str, **_k: Any) -> str:
        systems.append(system)
        return "[]" if "select" in prompt.lower() else "Antwort."

    monkeypatch.setattr(ollama_client, "generate", fake)
    result = wiki_engine.query_with_sources(QUESTION)
    assert any("Ontology frame" in s for s in systems)
    assert result["audit"]["ontology"][0]["works"] == ["de-strlschv-2018"]
