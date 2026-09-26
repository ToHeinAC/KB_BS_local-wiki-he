"""Valid time in merges (plan Phase 5): the `_is_newer` fix (F2) and version succession."""

from pathlib import Path
from typing import Any

import frontmatter
import pytest

import ontology
import ontology_store
import wiki_engine

# --- F2: only legal dates decide "newer" ---------------------------------------------


def test_an_undated_contribution_is_not_newer_than_a_dated_page() -> None:
    """F2 regression: the write date of an upload is not a legal date."""
    assert not wiki_engine._is_newer({"updated": "2026-09-26"}, {"effective as of": "2021-01-01"})


def test_write_dates_never_decide() -> None:
    new, old = {"created": "2026-09-01", "updated": "2026-09-26"}, {"updated": "2020-01-01"}
    assert not wiki_engine._is_newer(new, old)


def test_legal_dates_decide() -> None:
    assert wiki_engine._is_newer(
        {"effective as of": "2024-10-23"}, {"effective as of": "2020-01-01"}
    )
    assert not wiki_engine._is_newer(
        {"effective as of": "2019-01-01"}, {"effective as of": "2020-01-01"}
    )


@pytest.fixture
def versions(wiki_dir: Path) -> Path:
    ontology_store.binding_path().write_text("modules: [core, legal-de]\n")

    def rule(subject: str, pred: str, obj: str) -> dict[str, Any]:
        return ontology.assertion(subject, pred, obj, by="rule")

    ontology_store.append_rows(
        [
            rule("src:A.md", "work", "de-strlschv-2018"),
            rule("src:A.md", "version_date", "2020-01-01"),
            rule("src:B.md", "work", "de-strlschv-2018"),
            rule("src:B.md", "version_date", "2024-10-23"),
            rule("src:G.md", "work", "de-strlschg-2017"),
            rule("src:G.md", "version_date", "2024-10-23"),
        ]
    )
    return wiki_dir


def test_version_dates_of_the_page_sources_count(versions: Path) -> None:
    assert wiki_engine._is_newer({"sources": ["B.md"]}, {"sources": ["A.md §55"]})
    assert not wiki_engine._is_newer({"sources": ["A.md"]}, {"sources": ["B.md"]})


# --- succession: two versions of one work change, they do not contradict -------------


def _page(sources: list[str], body: str) -> str:
    post = frontmatter.Post(f"# Grenzwerte\n\n{body}", title="Grenzwerte", type="concept")
    post.metadata.update({"sources": sources, "lang": "de"})
    return frontmatter.dumps(post) + "\n"


def test_a_newer_version_of_the_same_work_is_a_change_note(versions: Path) -> None:
    existing = _page(["A.md"], "- Der Grenzwert liegt bei 20 mSv pro Jahr.")
    new = _page(["B.md"], "- Der Grenzwert liegt bei 6 mSv pro Jahr.")
    merged = frontmatter.loads(wiki_engine._merge_pages(existing, new, "B.md"))
    assert "## Changes" in merged.content
    assert "## Contradictions" not in merged.content
    assert "6 msv" in merged.content.split("## Changes")[1].lower()
    assert merged.metadata.get("confidence") != "low"


def test_different_works_still_contradict(versions: Path) -> None:
    existing = _page(["A.md"], "- Der Grenzwert liegt bei 20 mSv pro Jahr.")
    new = _page(["G.md"], "- Der Grenzwert liegt bei 6 mSv pro Jahr.")
    merged = frontmatter.loads(wiki_engine._merge_pages(existing, new, "G.md"))
    assert "## Contradictions" in merged.content
    assert merged.metadata["confidence"] == "low"
