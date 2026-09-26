"""`outdated` pages (plan Phase 5): built only on superseded versions — graph, health, lint."""

from datetime import date
from pathlib import Path
from typing import Any

import frontmatter
import pytest

import graph_export
import ollama_client
import ontology
import ontology_store
import wiki_engine

TODAY = date(2026, 9, 26)


def _page(wiki: Path, name: str, sources: list[str]) -> None:
    post = frontmatter.Post(f"# {name}\n\nText.", title=name, type="concept", sources=sources)
    (wiki / name).write_text(frontmatter.dumps(post) + "\n")


@pytest.fixture
def versions(wiki_dir: Path) -> Path:
    _page(wiki_dir, "alt.md", ["A.md §5"])
    _page(wiki_dir, "neu.md", ["B.md"])
    _page(wiki_dir, "beide.md", ["A.md", "B.md"])
    ontology_store.binding_path().write_text("modules: [core, legal-de]\n")

    def rule(subject: str, pred: str, obj: str) -> dict[str, Any]:
        return ontology.assertion(subject, pred, obj, by="rule")

    ontology_store.append_rows(
        [
            rule("src:A.md", "work", "de-strlschv-2018"),
            rule("src:A.md", "version_date", "2020-01-01"),
            rule("src:B.md", "work", "de-strlschv-2018"),
            rule("src:B.md", "version_date", "2024-10-23"),
        ]
    )
    return wiki_dir


def test_outdated_pages_rest_only_on_superseded_versions(versions: Path) -> None:
    assert wiki_engine.outdated_pages(TODAY) == ["alt.md"]
    assert wiki_engine.outdated_pages(date(2022, 1, 1)) == []


def test_without_ontology_nothing_is_outdated(wiki_dir: Path) -> None:
    _page(wiki_dir, "alt.md", ["A.md"])
    assert wiki_engine.outdated_pages(TODAY) == []


def test_graph_and_health_carry_the_outdated_flag(versions: Path) -> None:
    payload = graph_export.export(today=TODAY)
    flags = {n["id"]: n["outdated"] for n in payload["nodes"] if n["kind"] == "page"}
    assert flags == {"alt.md": True, "neu.md": False, "beide.md": False}
    assert graph_export.health(payload, today=TODAY)["outdated"] == ["alt.md"]


def test_lint_lists_outdated_pages(versions: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ollama_client, "generate", lambda *a, **k: "LLM report")
    report = wiki_engine.lint()
    assert "Built on superseded versions" in report
    assert "- alt.md" in report
