"""Core wiki operations: init, ingest, query, lint, list, read."""

import os
import re
from datetime import datetime, timezone
from pathlib import Path

import frontmatter
from dotenv import load_dotenv

import ollama_client
import schema_loader
from prompts import (
    ANSWER_PROMPT,
    FILE_ANSWER_PROMPT,
    INGEST_PROMPT,
    LINT_PROMPT,
    RESOLVE_CONTRADICTION_PROMPT,
    SELECT_AFFECTED_PROMPT,
    SELECT_PROMPT,
)

load_dotenv()

WIKI_DIR = Path(os.getenv("WIKI_DIR", "data/wiki"))
RAW_DIR = Path(os.getenv("RAW_DIR", "data/raw"))

_INDEX = WIKI_DIR / "index.md"
_LOG = WIKI_DIR / "log.md"
_INSIGHTS_DIR = "insights"
_MAX_AFFECTED_PAGES = 5
_MAX_EXISTING_CHARS = 8000  # cap injected existing-content per ingest call


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


def _select_affected_pages(system: str, source_name: str, index_text: str, text: str) -> list[str]:
    """Ask the LLM which existing pages a new source likely updates."""
    if not index_text.strip():
        return []
    excerpt = text[:2000]
    prompt = SELECT_AFFECTED_PROMPT.format(
        source_name=source_name, index_text=index_text, excerpt=excerpt
    )
    try:
        raw = ollama_client.generate(system, prompt, temperature=0.1)
    except RuntimeError:
        return []
    candidates = []
    for ln in raw.splitlines():
        s = ln.strip().strip("-• ").strip()
        if s.lower() == "none":
            return []
        if s.endswith(".md") and s not in ("index.md", "log.md"):
            if (WIKI_DIR / s).exists() and s not in candidates:
                candidates.append(s)
        if len(candidates) >= _MAX_AFFECTED_PAGES:
            break
    return candidates


def _build_existing_block(filenames: list[str]) -> str:
    """Render an 'Existing page content' block bounded by _MAX_EXISTING_CHARS."""
    if not filenames:
        return ""
    parts = ["\nExisting page content (MERGE; do not overwrite-erase):\n"]
    budget = _MAX_EXISTING_CHARS
    for fname in filenames:
        path = WIKI_DIR / fname
        if not path.exists():
            continue
        body = path.read_text()
        if len(body) > budget:
            body = body[:budget] + "\n…[truncated]"
        parts.append(f"\n--- {fname} ---\n{body}\n")
        budget -= len(body)
        if budget <= 0:
            break
    return "".join(parts) + "\n"


def _ensure_frontmatter(content: str, fname: str) -> str:
    """Patch minimal YAML frontmatter when the LLM omitted it."""
    if content.lstrip().startswith("---"):
        return content
    title = fname.replace(".md", "").replace("-", " ").title()
    today = _date()
    fm = (
        "---\n"
        f'title: "{title}"\n'
        "type: concept\n"
        "sources: []\n"
        "related: []\n"
        f'created: "{today}"\n'
        f'updated: "{today}"\n'
        "confidence: low\n"
        "---\n"
    )
    return fm + content.lstrip()


def ingest(text: str, source_name: str, user_meta: dict | None = None) -> dict:
    """Run LLM ingest pipeline. Returns {created, updated, contradictions}.

    Two-pass for true incremental compilation: a lightweight LLM call selects
    pages affected by the new source, their full bodies are loaded, and
    injected into the main ingest prompt so the LLM merges rather than
    rewrites blindly.

    `user_meta` is an optional dict of user-supplied fields (from
    templates/insert.md). Non-blank values are injected as authoritative
    metadata and copied into the source-summary frontmatter.
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

    affected = _select_affected_pages(system, source_name, index_text, text)
    existing_block = _build_existing_block(affected)

    prompt = INGEST_PROMPT.format(
        source_name=source_name,
        meta_block=meta_block,
        index_text=index_text,
        existing_block=existing_block,
        text=text,
        summary_slug=_title_to_filename(source_name).replace(".md", ""),
        example_extra=example_extra,
        date=_date(),
    )

    response = ollama_client.generate(system, prompt, temperature=0.3)
    pages = _parse_llm_pages(response)

    # Single retry with a stricter reformatting prompt if parsing failed.
    if not pages:
        retry_prompt = (
            "Your previous response did not contain any `=== filename.md === ... === END ===` blocks. "
            "Reformat your output now using EXACTLY that delimiter. Same content, correct format.\n\n"
            f"Original task was:\n{prompt}"
        )
        response = ollama_client.generate(system, retry_prompt, temperature=0.2)
        pages = _parse_llm_pages(response)

    created, updated, contradictions = [], [], []

    for page in pages:
        dest = WIKI_DIR / page["filename"]
        content = _ensure_frontmatter(page["content"], page["filename"])
        if dest.exists():
            updated.append(page["filename"])
        else:
            created.append(page["filename"])
        dest.write_text(content)

    for line in response.splitlines():
        if line.startswith("UPDATE:"):
            fname = line.split(":", 1)[1].strip()
            if fname and fname not in updated:
                updated.append(fname)
        elif line.startswith("CONTRADICTION:"):
            contradictions.append(line.split(":", 1)[1].strip())

    _rebuild_index()
    _append_log(
        f"Ingest: {source_name}",
        f"Affected: {affected}\nCreated: {created}\nUpdated: {updated}\nContradictions: {contradictions}",
    )

    return {
        "created": created,
        "updated": updated,
        "contradictions": contradictions,
        "affected": affected,
    }


def query(question: str) -> str:
    """Answer a question using wiki content (string form, kept for back-compat)."""
    return query_with_sources(question)["answer"]


def query_with_sources(question: str) -> dict:
    """Answer a question using wiki content. Returns {answer, sources, raw_sources}."""
    system = schema_loader.get_system_prompt()
    index_text = _INDEX.read_text() if _INDEX.exists() else "(empty wiki)"

    select_prompt = SELECT_PROMPT.format(index_text=index_text, question=question)
    selected_raw = ollama_client.generate(system, select_prompt, temperature=0.1)
    selected = [
        ln.strip()
        for ln in selected_raw.splitlines()
        if ln.strip().endswith(".md") and ln.strip() != "index.md"
    ][:5]

    pages_text = ""
    used_sources = []
    raw_sources_set: set[str] = set()
    for fname in selected:
        path = WIKI_DIR / fname
        if path.exists():
            text = path.read_text()
            pages_text += f"\n\n--- {fname} ---\n{text}"
            used_sources.append(fname)
            try:
                page_fm = frontmatter.loads(text)
                raw_sources_set.update(page_fm.get("sources", []))
            except Exception:
                pass

    if not pages_text:
        pages_text = "(no relevant pages found)"

    answer_prompt = ANSWER_PROMPT.format(pages_text=pages_text, question=question)
    answer = ollama_client.generate(system, answer_prompt, temperature=0.7)
    return {"answer": answer, "sources": used_sources, "raw_sources": sorted(raw_sources_set)}


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

    orphans = find_orphans()
    if orphans:
        prog = "## Programmatic checks\n\n**Orphans (no in-links from `related` frontmatter):**\n" + "\n".join(
            f"- {o}" for o in orphans
        ) + "\n\n---\n\n"
        report = prog + report

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


_TYPE_GROUPS = ("concept", "entity", "source-summary", "comparison")


def search_wiki(query: str) -> list[dict]:
    """Case-insensitive full-text search across page titles, filenames, and bodies.

    Returns list of {"filename", "title", "excerpt"} for matching pages.
    Excerpt is ~160 chars centred on the first body match, or page start
    when the match is in title/filename only. Empty query returns [].
    """
    q = query.strip().lower()
    if not q:
        return []
    results = []
    for md in sorted(WIKI_DIR.glob("*.md")):
        if md.name in ("index.md", "log.md"):
            continue
        try:
            post = frontmatter.load(str(md))
            title = str(post.metadata.get("title", md.stem))
            body = post.content
        except Exception:
            title = md.stem
            body = md.read_text()
        body_lower = body.lower()
        idx = body_lower.find(q)
        if idx == -1 and q not in title.lower() and q not in md.name.lower():
            continue
        if idx == -1:
            excerpt = body[:160].replace("\n", " ").strip()
        else:
            start = max(0, idx - 60)
            end = min(len(body), idx + 100)
            excerpt = body[start:end].replace("\n", " ").strip()
            if start > 0:
                excerpt = "…" + excerpt
            if end < len(body):
                excerpt = excerpt + "…"
        results.append({"filename": md.name, "title": title, "excerpt": excerpt})
    return results


def get_wiki_tree() -> dict[str, list[dict]]:
    """Group `list_pages()` output by frontmatter `type`.

    Returns dict keyed by type (concept/entity/source-summary/comparison/other),
    only including non-empty groups. Order within a group matches list_pages().
    """
    tree: dict[str, list[dict]] = {}
    for page in list_pages():
        t = str(page.get("type", "")).strip().lower()
        key = t if t in _TYPE_GROUPS else "other"
        tree.setdefault(key, []).append(page)
    return tree


def read_log() -> str:
    return _LOG.read_text() if _LOG.exists() else "(no log yet)"


def file_answer(question: str, answer: str, related: list[str] | None = None) -> str:
    """Persist a Q&A as a wiki insight page (Karpathy filing-back mechanic).

    Returns the relative filename written under data/wiki/insights/.
    """
    insights_dir = WIKI_DIR / _INSIGHTS_DIR
    insights_dir.mkdir(parents=True, exist_ok=True)

    slug_source = (question[:80] or "insight").strip()
    slug = _title_to_filename(slug_source).replace(".md", "")
    fname = f"insight-{slug}.md"
    rel = f"{_INSIGHTS_DIR}/{fname}"
    dest = insights_dir / fname

    related_yaml = "[" + ", ".join(f'"{r}"' for r in (related or [])) + "]"
    today = _date()
    title = question.strip().rstrip("?.!").strip() or "Insight"
    body = answer.strip()

    page = (
        "---\n"
        f'title: "{title}"\n'
        "type: comparison\n"
        'sources: ["chat"]\n'
        f"related: {related_yaml}\n"
        f'created: "{today}"\n'
        f'updated: "{today}"\n'
        "confidence: medium\n"
        "---\n\n"
        f"## Question\n{question.strip()}\n\n"
        f"## Answer\n{body}\n"
    )
    dest.write_text(page)
    _append_log("Insight filed", f"{rel}\nQ: {question[:120]}")
    _rebuild_index()
    return rel


def build_link_graph() -> dict[str, set[str]]:
    """Return adjacency map filename → set(related filenames) from frontmatter.

    Edges include only targets that exist as wiki pages; non-existent or system
    targets are dropped silently.
    """
    existing = {p["filename"] for p in list_pages()}
    # Insights live in a subdir — include them too.
    insights = WIKI_DIR / _INSIGHTS_DIR
    if insights.exists():
        for md in insights.glob("*.md"):
            existing.add(f"{_INSIGHTS_DIR}/{md.name}")

    graph: dict[str, set[str]] = {}
    targets = [WIKI_DIR.glob("*.md")]
    if insights.exists():
        targets.append(insights.glob("*.md"))

    for src_iter in targets:
        for md in src_iter:
            if md.name in ("index.md", "log.md"):
                continue
            try:
                post = frontmatter.load(str(md))
                rel = post.metadata.get("related", []) or []
            except Exception:
                rel = []
            key = md.name if md.parent == WIKI_DIR else f"{_INSIGHTS_DIR}/{md.name}"
            edges = set()
            for r in rel:
                r = str(r).strip()
                if r and r != key and r in existing and r not in ("index.md", "log.md"):
                    edges.add(r)
            graph[key] = edges
    return graph


def find_orphans() -> list[str]:
    """Pages with zero in-edges in the link graph (not linked from any other page)."""
    graph = build_link_graph()
    in_deg: dict[str, int] = {n: 0 for n in graph}
    for _src, edges in graph.items():
        for tgt in edges:
            in_deg[tgt] = in_deg.get(tgt, 0) + 1
    return sorted(n for n, d in in_deg.items() if d == 0)


def resolve_contradiction(description: str, page_filenames: list[str], user_guidance: str = "") -> dict:
    """Reconcile a contradiction across pages via a focused LLM call.

    Rewrites the affected pages in place using the standard ingest delimiter
    format. Returns {updated: [...], description}.
    """
    system = schema_loader.get_system_prompt()
    pages_text = ""
    for fname in page_filenames:
        path = WIKI_DIR / fname
        if path.exists():
            pages_text += f"\n--- {fname} ---\n{path.read_text()}\n"
    if not pages_text:
        return {"updated": [], "description": description}

    prompt = RESOLVE_CONTRADICTION_PROMPT.format(
        description=description,
        pages_text=pages_text,
        user_guidance=user_guidance or "(none)",
    )
    response = ollama_client.generate(system, prompt, temperature=0.2)
    pages = _parse_llm_pages(response)

    updated = []
    for page in pages:
        dest = WIKI_DIR / page["filename"]
        if not dest.exists():
            continue
        dest.write_text(_ensure_frontmatter(page["content"], page["filename"]))
        updated.append(page["filename"])

    _append_log(
        "Contradiction resolved",
        f"Description: {description}\nUpdated: {updated}\nGuidance: {user_guidance[:200]}",
    )
    _rebuild_index()
    return {"updated": updated, "description": description}


def stats() -> dict:
    pages = list_pages()
    raw_count = len(list(RAW_DIR.glob("*"))) - 1 if RAW_DIR.exists() else 0  # exclude manifest
    log_size = _LOG.stat().st_size if _LOG.exists() else 0
    return {
        "pages": len(pages),
        "raw_files": max(0, raw_count),
        "log_bytes": log_size,
    }
