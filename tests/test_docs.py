"""Enforces AGENTS.md §5.1: docs stay small and every local link or @import resolves."""

import os
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKIP_DIRS = {
    ".git",
    ".venv",
    ".pytest_cache",
    ".ruff_cache",
    "data",
    "htmlcov",
    "node_modules",
    "models",
    "graft",
}
MAX_LINES = {"AGENTS.md": 200, "IMPLEMENTATION.md": 500, "README.md": 300}
MAX_LINES_DEFAULT = 800
ARCHIVE = "docs/_bup_"  # frozen verbatim copies; their links point where the original lived
# Not project docs: raw notes, on-demand skill references, archives.
SIZE_EXEMPT = ("ideas/", ".claude/skills/", ARCHIVE)
LINK = re.compile(r"\]\(([^)#\s]+)")  # markdown link target, anchor stripped
IMPORT = re.compile(r"(?:^|\s)@([\w./-]+\.md)\b")  # Claude Code @import
CODE = re.compile(r"```.*?```|`[^`\n]*`", re.DOTALL)  # fenced blocks and inline spans


def markdown_files() -> list[Path]:
    files = []
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        files += [Path(dirpath, f) for f in filenames if f.endswith(".md")]
    return files


def broken_refs(doc: Path) -> list[str]:
    text = CODE.sub("", doc.read_text(encoding="utf-8"))  # code holds examples, not links
    targets = LINK.findall(text) + IMPORT.findall(text)
    return [t for t in targets if ":" not in t and not (doc.parent / t).exists()]


def _rel(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def link_checked(rel: str) -> bool:
    return not rel.startswith(ARCHIVE)


def size_limit(rel: str) -> int | None:
    """Max lines for the doc at repo-relative ``rel``; None if it is exempt."""
    if rel.startswith(SIZE_EXEMPT):
        return None
    return MAX_LINES.get(rel, MAX_LINES_DEFAULT)


def test_broken_refs_detects_missing_targets(tmp_path: Path) -> None:
    (tmp_path / "ok.md").write_text("")
    doc = tmp_path / "doc.md"
    doc.write_text("[a](ok.md) [b](missing.md) @gone.md [c](https://x.org) [d](ok.md#part)")
    assert broken_refs(doc) == ["missing.md", "gone.md"]


def test_broken_refs_ignores_code_examples(tmp_path: Path) -> None:
    doc = tmp_path / "doc.md"
    doc.write_text("`[a](gone.md)` `x` [c](missing.md)\n```md\n[b](gone.md)\n```\n")
    assert broken_refs(doc) == ["missing.md"]


def test_archives_are_not_link_checked() -> None:
    assert not link_checked("docs/_bup_AGENTS.md")
    assert link_checked("docs/ui.md")


def test_local_links_resolve() -> None:
    broken = {
        _rel(p): refs
        for p in markdown_files()
        if link_checked(_rel(p)) and (refs := broken_refs(p))
    }
    assert broken == {}


def test_size_limit_exempts_notes_and_skill_references() -> None:
    assert size_limit("ideas/idea.md") is None
    assert size_limit(".claude/skills/x/references/y.md") is None
    assert size_limit("docs/_bup_PRD.md") is None
    assert size_limit("docs/retrieval.md") == MAX_LINES_DEFAULT
    assert size_limit("AGENTS.md") == 200


def test_docs_within_size_limits() -> None:
    too_long = {
        _rel(p): n
        for p in markdown_files()
        if (limit := size_limit(_rel(p))) is not None
        and (n := len(p.read_text(encoding="utf-8").splitlines())) > limit
    }
    assert too_long == {}
