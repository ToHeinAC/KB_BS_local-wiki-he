"""Core wiki operations: init, ingest, query, lint, list, read."""

import os
import re
from datetime import datetime, timezone
from pathlib import Path

import frontmatter
from dotenv import load_dotenv

import ollama_client
import schema_loader
from prompts import ANSWER_PROMPT, INGEST_PROMPT, LINT_PROMPT, SELECT_PROMPT

load_dotenv()

WIKI_DIR = Path(os.getenv("WIKI_DIR", "data/wiki"))
RAW_DIR = Path(os.getenv("RAW_DIR", "data/raw"))

_INDEX = WIKI_DIR / "index.md"
_LOG = WIKI_DIR / "log.md"


def init_wiki() -> None:
    WIKI_DIR.mkdir(parents=True, exist_ok=True)
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    if not _INDEX.exists():
        _INDEX.write_text("# Wiki Index\nUpdated: — | Pages: 0\n\n## Pages\n")
    if not _LOG.exists():
        _LOG.write_text("# Wiki Log\n")


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")


def _date() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _append_log(action: str, detail: str) -> None:
    entry = f"\n## {_now()} — {action}\n{detail}\n"
    with _LOG.open("a") as f:
        f.write(entry)


def _rebuild_index() -> None:
    pages = list_pages()
    lines = [f"# Wiki Index\nUpdated: {_date()} | Pages: {len(pages)}\n\n## Pages\n"]
    for p in pages:
        title = p.get("title", p["filename"])
        desc = p.get("description", "")
        lines.append(f"- [{title}]({p['filename']}) — {desc}\n")
    _INDEX.write_text("".join(lines))


def _title_to_filename(title: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return f"{slug}.md"


def _parse_llm_pages(response: str) -> list[dict]:
    """Extract filename→content pairs from LLM output.

    Expected LLM format:
    === filename.md ===
    <full page content including frontmatter>
    === END ===
    """
    pages = []
    pattern = re.compile(r"===\s*([\w\-\.]+\.md)\s*===\s*(.*?)(?====|\Z)", re.DOTALL)
    for match in pattern.finditer(response):
        fname = match.group(1).strip()
        content = match.group(2).strip()
        if content:
            pages.append({"filename": fname, "content": content})
    return pages


def ingest(text: str, source_name: str, user_meta: dict | None = None) -> dict:
    """Run LLM ingest pipeline. Returns {created, updated, contradictions}.

    `user_meta` is an optional dict of user-supplied fields (from
    templates/insert.md) — name, fullname, description, effective as of,
    part of. Non-blank values are injected into the prompt as authoritative
    metadata and must be carried into the source-summary page frontmatter.
    """
    system = schema_loader.get_system_prompt()
    index_text = _INDEX.read_text() if _INDEX.exists() else ""

    clean_meta = {k: v for k, v in (user_meta or {}).items() if v and str(v).strip()}
    if clean_meta:
        meta_lines = "\n".join(f"- {k}: {v}" for k, v in clean_meta.items())
        meta_block = (
            "User-supplied metadata (authoritative — prefer these over filename inference;\n"
            "use `name`/`fullname` for the page title and copy `description`,\n"
            "`effective as of`, `part of` verbatim into the source-summary frontmatter):\n"
            f"{meta_lines}\n\n"
        )
        extra_frontmatter = "\n".join(f'{k}: "{v}"' for k, v in clean_meta.items())
        example_extra = "\n" + extra_frontmatter
    else:
        meta_block = ""
        example_extra = ""

    prompt = INGEST_PROMPT.format(
        source_name=source_name,
        meta_block=meta_block,
        index_text=index_text,
        text=text,
        summary_slug=_title_to_filename(source_name).replace(".md", ""),
        example_extra=example_extra,
        date=_date(),
    )

    response = ollama_client.generate(system, prompt, temperature=0.3)
    pages = _parse_llm_pages(response)

    created, updated, contradictions = [], [], []
    index_content = _INDEX.read_text() if _INDEX.exists() else ""

    for page in pages:
        dest = WIKI_DIR / page["filename"]
        if dest.exists():
            updated.append(page["filename"])
        else:
            created.append(page["filename"])
        dest.write_text(page["content"])

    # Extract UPDATE and CONTRADICTION lines from raw response
    for line in response.splitlines():
        if line.startswith("UPDATE:"):
            fname = line.split(":", 1)[1].strip()
            if fname not in updated:
                updated.append(fname)
        elif line.startswith("CONTRADICTION:"):
            contradictions.append(line.split(":", 1)[1].strip())

    _rebuild_index()
    _append_log(
        f"Ingest: {source_name}",
        f"Created: {created}\nUpdated: {updated}\nContradictions: {contradictions}",
    )

    return {"created": created, "updated": updated, "contradictions": contradictions}


def query(question: str) -> str:
    """Answer a question using wiki content."""
    system = schema_loader.get_system_prompt()
    index_text = _INDEX.read_text() if _INDEX.exists() else "(empty wiki)"

    # Ask LLM to select relevant pages
    select_prompt = SELECT_PROMPT.format(index_text=index_text, question=question)
    selected_raw = ollama_client.generate(system, select_prompt, temperature=0.1)
    selected = [
        ln.strip()
        for ln in selected_raw.splitlines()
        if ln.strip().endswith(".md") and ln.strip() != "index.md"
    ][:5]

    pages_text = ""
    for fname in selected:
        path = WIKI_DIR / fname
        if path.exists():
            pages_text += f"\n\n--- {fname} ---\n{path.read_text()}"

    if not pages_text:
        pages_text = "(no relevant pages found)"

    answer_prompt = ANSWER_PROMPT.format(pages_text=pages_text, question=question)
    return ollama_client.generate(system, answer_prompt, temperature=0.7)


def lint() -> str:
    """Run wiki health check. Returns the lint report."""
    system = schema_loader.get_system_prompt()
    all_pages = ""
    for md in sorted(WIKI_DIR.glob("*.md")):
        if md.name in ("index.md", "log.md"):
            continue
        all_pages += f"\n\n--- {md.name} ---\n{md.read_text()}"

    if not all_pages:
        return "Wiki is empty — nothing to lint."

    report = ollama_client.generate(system, LINT_PROMPT.format(all_pages=all_pages), temperature=0.3)
    _append_log("Lint", report[:500])
    return report


def list_pages() -> list[dict]:
    """Return metadata for all non-system wiki pages."""
    results = []
    for md in sorted(WIKI_DIR.glob("*.md")):
        if md.name in ("index.md", "log.md"):
            continue
        try:
            post = frontmatter.load(str(md))
            meta = dict(post.metadata)
            meta["filename"] = md.name
            meta.setdefault("description", post.content[:120].replace("\n", " "))
            results.append(meta)
        except Exception:
            results.append({"filename": md.name, "title": md.stem, "description": ""})
    return results


def read_page(filename: str) -> str:
    path = WIKI_DIR / filename
    if not path.exists():
        return f"Page not found: {filename}"
    return path.read_text()


def read_log() -> str:
    return _LOG.read_text() if _LOG.exists() else "(no log yet)"


def stats() -> dict:
    pages = list_pages()
    raw_count = len(list(RAW_DIR.glob("*"))) - 1 if RAW_DIR.exists() else 0  # exclude manifest
    log_size = _LOG.stat().st_size if _LOG.exists() else 0
    return {
        "pages": len(pages),
        "raw_files": max(0, raw_count),
        "log_bytes": log_size,
    }
