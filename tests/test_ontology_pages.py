"""Classes for wiki concept pages (plan Phase 8): proposals, stamping, search."""

from pathlib import Path
from typing import Any

import frontmatter
import pytest

import auth
import lex_index
import ollama_client
import ontology
import ontology_detect
import ontology_store
import retrieval
import wiki_engine


@pytest.fixture(scope="module")
def schema() -> ontology.Schema:
    shared = ontology_store.shared_modules()
    built, errors = ontology.build_schema([shared["core"], shared["ai-tech"]])
    assert built is not None, errors
    return built


def test_page_classes_are_never_used_for_documents(schema: ontology.Schema) -> None:
    doc_options = ontology_detect.classify_options(schema)
    page_options = ontology_detect.page_class_options(schema)
    assert "research-report" in doc_options
    assert "ai-model" not in doc_options
    assert set(page_options) == {
        "ai-model",
        "technique",
        "organisation",
        "product",
        "person",
        "phenomenon",
    }
    text = "# GPT-5\n\nAn AI model. Executive Summary follows."
    assert ontology_detect.detect(text, schema).class_id == "research-report"


def _page(wiki: Path, name: str, body: str, ptype: str = "concept") -> Path:
    post = frontmatter.Post(f"# {name}\n\n{body}", title=name.removesuffix(".md"), type=ptype)
    post.metadata.update({"sources": ["doc.md"], "lang": "en"})
    path = wiki / name
    path.write_text(frontmatter.dumps(post) + "\n")
    return path


@pytest.fixture
def ki(wiki_dir: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("RERANK_ENABLED", "0")
    ontology_store.binding_path().write_text("modules: [core, ai-tech]\n")
    auth.add_user("maint", "pw", ["test"], maintains=["test"])
    _page(wiki_dir, "concept-attention.md", "Attention is a technique that weighs tokens.")
    _page(wiki_dir, "gpt-5.md", "GPT-5 is a large language model by OpenAI.", ptype="entity")
    _page(wiki_dir, "summary-doc.md", "Summary.", ptype="source-summary")
    return wiki_dir


def _answers(monkeypatch: pytest.MonkeyPatch, by_title: dict[str, str]) -> None:
    def fake(system: str, prompt: str, **_k: Any) -> str:
        for title, answer in by_title.items():
            if f"# {title}" in prompt:
                return answer
        return '{"class": "none", "quote": ""}'

    monkeypatch.setattr(ollama_client, "generate", fake)


def test_pages_get_class_proposals_with_verbatim_quotes(
    ki: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _answers(
        monkeypatch,
        {
            "concept-attention.md": '{"class": "technique", '
            '"quote": "Attention is a technique that weighs tokens."}',
            # not verbatim in the page:
            "gpt-5.md": '{"class": "ai-model", "quote": "GPT-5 is a secret model."}',
        },
    )
    made = wiki_engine.propose_page_classes("maint", limit=10)
    assert made == 1
    [row] = ontology_store.proposals()
    assert (row["subject"], row["object"], row["by"]) == (
        "page:concept-attention.md",
        "technique",
        "llm",
    )
    assert wiki_engine.propose_page_classes("maint", limit=10) == 0  # already proposed


def test_a_confirmed_page_class_is_stamped_on_the_page(
    ki: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _answers(
        monkeypatch,
        {
            "gpt-5.md": '{"class": "ai-model", '
            '"quote": "GPT-5 is a large language model by OpenAI."}'
        },
    )
    wiki_engine.propose_page_classes("maint", limit=10)
    [row] = ontology_store.proposals()
    wiki_engine.decide_proposal(row["id"], accept=True, user="maint")
    assert frontmatter.load(str(ki / "gpt-5.md")).metadata["class"] == "ai-model"
    assert "class" not in frontmatter.load(str(ki / "summary-doc.md")).metadata


def test_only_maintainers_ask_for_page_classes(ki: Path) -> None:
    with pytest.raises(PermissionError):
        wiki_engine.propose_page_classes("nobody", limit=1)


def test_a_page_class_word_lifts_pages_of_that_class(ki: Path) -> None:
    _page(ki, "concept-attention.md", "Attention weighs tokens inside a model.")
    _page(ki, "gpt-5.md", "GPT-5 is a model. The model is a large model.", ptype="entity")
    ontology_store.append_rows(
        [ontology.assertion("page:concept-attention.md", "class", "technique", by="user")]
    )
    lex_index.build()
    q = "model verfahren"
    off = [h["source"] for h in retrieval.search(q, scope="wiki", use_ontology=False)]
    assert off[0] == "gpt-5.md"  # lexically the entity page wins
    assert next(h["filename"] for h in wiki_engine.search_wiki(q)) == "concept-attention.md"
