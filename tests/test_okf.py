"""Tests for OKF v0.1 conformance helpers (src/okf.py)."""

import sys
from pathlib import Path

import frontmatter
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import okf


CONCEPT = """---
title: Copper
type: concept
sources:
  - munich-re.md
  - freeport.md
related: []
created: "2026-06-01"
updated: "2026-06-24"
confidence: high
---

## Key facts
- Copper is a base metal used in electrification [munich-re.md].
- Prices rose in 2026 [freeport.md].

## Detail
Some prose about copper demand.
"""


def _meta(content: str) -> dict:
    return frontmatter.loads(content).metadata


# --- enrich_frontmatter ------------------------------------------------------

def test_enrich_adds_okf_fields():
    post = frontmatter.loads(CONCEPT)
    m = okf.enrich_frontmatter(post.metadata, post.content, db="Investing")
    assert m["description"].startswith("Copper is a base metal")
    assert "[munich-re.md]" not in m["description"]  # inline cite stripped
    assert m["tags"] == ["investing", "concept"]
    assert m["timestamp"] == "2026-06-24T00:00:00Z"
    assert "resource" not in m  # concept has no single underlying asset


def test_enrich_defaults_missing_type_to_concept():
    post = frontmatter.loads("---\ntitle: X\n---\n\nbody")
    m = okf.enrich_frontmatter(post.metadata, post.content, db="KI")
    assert m["type"] == "concept"  # OKF's one hard rule


def test_enrich_resource_for_source_summary():
    post = frontmatter.loads(CONCEPT.replace("type: concept", "type: source-summary"))
    m = okf.enrich_frontmatter(post.metadata, post.content, db="Investing")
    assert m["resource"] == "raw/munich-re.md"


def test_enrich_keeps_existing_description():
    c = CONCEPT.replace('confidence: high', 'confidence: high\ndescription: "Hand written."')
    post = frontmatter.loads(c)
    m = okf.enrich_frontmatter(post.metadata, post.content, db="Investing")
    assert m["description"] == "Hand written."


def test_enrich_is_idempotent():
    post = frontmatter.loads(CONCEPT)
    m1 = okf.enrich_frontmatter(post.metadata, post.content, db="Investing")
    m2 = okf.enrich_frontmatter(m1, post.content, db="Investing")
    assert m1 == m2


# --- citations ---------------------------------------------------------------

def test_render_citations_numbered():
    out = okf.render_citations(["a.md", "b.md"])
    assert out == "## Citations\n\n1. a.md\n2. b.md\n"


def test_render_citations_empty():
    assert okf.render_citations([]) == ""


def test_apply_to_page_appends_citations_once():
    once = okf.apply_to_page(CONCEPT, db="Investing")
    twice = okf.apply_to_page(once, db="Investing")
    assert once == twice  # idempotent
    assert once.count("## Citations") == 1
    assert "1. munich-re.md" in once
    assert _meta(once)["tags"] == ["investing", "concept"]


def test_apply_to_page_refreshes_citations_on_source_change():
    once = okf.apply_to_page(CONCEPT, db="Investing")
    post = frontmatter.loads(once)
    post.metadata["sources"] = post.metadata["sources"] + ["newsrc.md"]
    out = okf.apply_to_page(frontmatter.dumps(post), db="Investing")
    assert out.count("## Citations") == 1
    assert "3. newsrc.md" in out


# --- log ---------------------------------------------------------------------

def test_add_log_entry_groups_by_date_newest_first():
    text = "---\ntitle: Activity Log\n---\n\n# Log\n"
    text = okf.add_log_entry(text, "Ingest: a", "created x", day="2026-07-01", time="09:00")
    text = okf.add_log_entry(text, "Ingest: b", "", day="2026-07-01", time="10:00")
    text = okf.add_log_entry(text, "Ingest: c", "", day="2026-07-02", time="08:00")
    body = frontmatter.loads(text).content
    assert body.index("## 2026-07-02") < body.index("## 2026-07-01")  # newest date first
    facts = body.split("## 2026-07-01")[1]
    assert facts.index("10:00") < facts.index("09:00")  # newest entry first in day


def test_reformat_legacy_log():
    legacy = ("# Wiki Log\n\n"
              "## 2026-06-01 09:00 — Ingest: a\nAffected: []\n\n"
              "## 2026-06-02 11:00 — Consolidate\nmerged\n")
    out = okf.reformat_log(legacy)
    body = frontmatter.loads(out).content
    assert body.count("## 2026-06-02") == 1
    assert body.index("## 2026-06-02") < body.index("## 2026-06-01")
    assert "- 09:00 — Ingest: a" in body


# --- validate ----------------------------------------------------------------

def test_validate_clean_bundle(tmp_path):
    (tmp_path / "index.md").write_text('---\nokf_version: "0.1"\n---\n\n# Pages\n')
    (tmp_path / "copper.md").write_text(okf.apply_to_page(CONCEPT, db="Investing"))
    (tmp_path / "log.md").write_text("---\ntitle: Activity Log\n---\n\n# Log\n")
    assert okf.okf_validate(tmp_path) == []


def test_validate_flags_missing_version_and_type(tmp_path):
    (tmp_path / "index.md").write_text("# Pages\n")  # no okf_version
    (tmp_path / "bad.md").write_text("---\ntitle: Bad\ntype: \n---\n\nbody\n")
    issues = okf.okf_validate(tmp_path)
    assert any("okf_version" in i for i in issues)
    assert any("bad.md" in i and "type" in i for i in issues)


# --- collapse_duplicate_sections ---------------------------------------------

def test_collapse_keeps_content_bearing_duplicate():
    body = (
        "## Key facts\n- A\n- B\n\n"                     # short outline
        "## Key facts\n- Real fact one is much longer.\n- Real fact two.\n\n"
        "## Details\nsome text\n"
    )
    out, removed = okf.collapse_duplicate_sections(body)
    assert removed == 1
    assert out.count("## Key facts") == 1
    assert "Real fact one is much longer." in out   # kept the longer section
    assert "- A\n- B" not in out                     # dropped the outline
    assert "## Details" in out                       # untouched


def test_collapse_noop_without_consecutive_duplicates():
    body = "## A\nx\n\n## B\ny\n\n## A\nz\n"          # repeat, but not adjacent
    out, removed = okf.collapse_duplicate_sections(body)
    assert removed == 0
    assert out == body
