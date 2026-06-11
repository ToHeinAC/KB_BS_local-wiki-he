"""Core wiki operations: init, ingest, query, lint, list, read."""

import os
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path

import frontmatter
from dotenv import load_dotenv

import chunker
import db_context
import dedup
import lex_index
import ollama_client
import qa_gen
import schema_loader
from prompts import (
    ANSWER_PROMPT,
    CONDENSE_PROMPT,
    DESCRIPTION_BUILD_PROMPT,
    DESCRIPTION_DELETE_PROMPT,
    DESCRIPTION_UPDATE_PROMPT,
    FILE_ANSWER_PROMPT,
    INGEST_PROMPT,
    LINT_PROMPT,
    RESOLVE_CONTRADICTION_PROMPT,
    SELECT_PROMPT,
)

load_dotenv()


def _wiki() -> Path:
    return db_context.wiki_dir()


def _raw() -> Path:
    return db_context.raw_dir()


def _index_path() -> Path:
    return _wiki() / "index.md"


def _log_path() -> Path:
    return _wiki() / "log.md"


def _description_path() -> Path:
    return _wiki() / "DESCRIPTION.md"


_INSIGHTS_DIR = "insights"
_SYSTEM_PAGES = ("index.md", "log.md", "DESCRIPTION.md")  # not real wiki pages
_DESCRIPTION_MAX_CHARS = 1800  # ~half a page; hard cap on the DB overview
_MAX_AFFECTED_PAGES = 5
_AFFECTED_QUERY_TOPK = 20  # BM25 chunk hits considered when mapping to wiki pages
# Per-page existing-content budget by BM25 rank: the most-relevant page gets the
# largest merge window so its merge stays accurate; tail pages get just enough
# for the LLM to recognise and link them. Index = rank (0 = top hit).
_EXISTING_BUDGET_BY_RANK = (4000, 2000, 2000, 800, 800)
# Query-path tuning (Q-1 hybrid selection + Q-3 section-level synthesis).
_QUERY_CANDIDATE_TOPK = 15       # BM25 hits scanned to build the candidate page set
_QUERY_MAX_CANDIDATES = 10       # candidate pages handed to the LLM re-ranker
_QUERY_CHUNKS_PER_PAGE = 2       # wiki chunks injected per selected page
_QUERY_SYNTH_MAX_CHARS = 8000    # hard cap on total synthesis context
_QUERY_PAGE_FALLBACK_CHARS = 1500  # body slice when a page had no BM25 chunk hit
_TEIL_SUFFIX_RE = re.compile(r"\s*\[Teil\s+\d+/\d+\]\s*(?:\.md)?\s*$")


def init_wiki() -> None:
    _wiki().mkdir(parents=True, exist_ok=True)
    _raw().mkdir(parents=True, exist_ok=True)
    if not _index_path().exists():
        _index_path().write_text("# Wiki Index\nUpdated: — | Pages: 0\n\n## Pages\n")
    if not _log_path().exists():
        _log_path().write_text("# Wiki Log\n")
    if not _description_path().exists():
        _description_path().write_text("")


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")


def _date() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _append_log(action: str, detail: str) -> None:
    entry = f"\n## {_now()} — {action}\n{detail}\n"
    with _log_path().open("a") as f:
        f.write(entry)


def _rebuild_index() -> None:
    pages = list_pages()
    lines = [f"# Wiki Index\nUpdated: {_date()} | Pages: {len(pages)}\n\n## Pages\n"]
    for p in pages:
        title = p.get("title", p["filename"])
        desc = p.get("description", "")
        lines.append(f"- [{title}]({p['filename']}) — {desc}\n")
    _index_path().write_text("".join(lines))


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


def _source_to_pages() -> dict[str, list[str]]:
    """Reverse map: raw-source filename → wiki pages derived from it.

    Built from each page's `sources:` frontmatter so BM25 hits (which carry a
    `source` field) can be mapped back to the wiki pages a new source touches.
    """
    mapping: dict[str, list[str]] = {}
    for page in list_pages():
        for src in (page.get("sources") or []):
            key = str(src).strip()
            if key:
                mapping.setdefault(key, []).append(page["filename"])
    return mapping


def _select_affected_pages(query_text: str, src_to_pages: dict[str, list[str]],
                           exclude_source: str = "") -> list[str]:
    """Rank existing wiki pages a new source likely updates, via BM25.

    Queries the pre-existing lexical index with the new source text, maps each
    hit's `source` back to the wiki pages derived from it, and returns those
    pages ranked by summed hit score (most relevant first), capped at
    `_MAX_AFFECTED_PAGES`. No LLM call. Returns [] when the index or map is empty
    (e.g. the first ingest into a fresh wiki).
    """
    if not src_to_pages or not query_text.strip():
        return []
    try:
        hits = lex_index.query(query_text, top_k=_AFFECTED_QUERY_TOPK, scope="raw")
    except Exception:
        return []
    page_score: dict[str, float] = {}
    for h in hits:
        src = (h.get("source") or "").strip()
        if not src or src == exclude_source:
            continue
        for page in src_to_pages.get(src, []):
            page_score[page] = page_score.get(page, 0.0) + float(h.get("score", 0.0))
    ranked = sorted(page_score, key=lambda p: (-page_score[p], p))
    return ranked[:_MAX_AFFECTED_PAGES]


def _build_existing_block(filenames: list[str]) -> str:
    """Render an 'Existing page content' block with rank-weighted per-page budgets.

    `filenames` is ordered most-relevant-first (BM25 rank). The top page gets the
    largest character window so its merge stays faithful; tail pages get a smaller
    window — enough for the LLM to recognise and link them. See
    `_EXISTING_BUDGET_BY_RANK`.
    """
    if not filenames:
        return ""
    parts = ["\nExisting page content (MERGE; do not overwrite-erase):\n"]
    for rank, fname in enumerate(filenames):
        path = _wiki() / fname
        if not path.exists():
            continue
        budget = (_EXISTING_BUDGET_BY_RANK[rank]
                  if rank < len(_EXISTING_BUDGET_BY_RANK)
                  else _EXISTING_BUDGET_BY_RANK[-1])
        body = path.read_text()
        if len(body) > budget:
            body = body[:budget] + "\n…[truncated]"
        parts.append(f"\n--- {fname} ---\n{body}\n")
    return "".join(parts) + "\n"


def _scrub_related(content: str, existing: set[str]) -> str:
    """Remove `related:` entries that don't exist as actual wiki pages."""
    try:
        post = frontmatter.loads(content)
    except Exception:
        return content
    related = post.metadata.get("related", []) or []
    cleaned = [r for r in related if str(r).strip() in existing]
    if len(cleaned) == len(related):
        return content
    post.metadata["related"] = cleaned
    return frontmatter.dumps(post)


def _ensure_source_in_frontmatter(content: str, source_name: str) -> str:
    """Append `source_name` to the frontmatter `sources:` list (idempotent).

    Parses with python-frontmatter so an existing `sources:` entry is preserved
    and merged. If the page has no frontmatter yet, leaves the content alone —
    `_ensure_frontmatter` will add a minimal block with `sources: [source_name]`.
    """
    if not source_name:
        return content
    try:
        post = frontmatter.loads(content)
    except Exception:
        return content
    existing = post.metadata.get("sources") or []
    if not isinstance(existing, list):
        existing = [existing]
    existing = [str(s).strip() for s in existing if str(s).strip()]
    if source_name not in existing:
        existing.append(source_name)
    post.metadata["sources"] = existing
    return frontmatter.dumps(post) + "\n"


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


def ingest_begin(full_text: str, source_name: str, user_meta: dict | None = None) -> dict:
    """Source-scoped ingest setup. Runs the once-per-source LLM/index work.

    Builds the chunk store, runs qa_gen on the whole document, and selects
    affected wiki pages — exactly once per uploaded source — then returns a
    `ctx` dict the per-piece synthesis and the final wrap-up consume.
    `lex_index.build()` is deferred to `ingest_end`.
    """
    system = schema_loader.get_system_prompt()
    index_text = _index_path().read_text() if _index_path().exists() else ""

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

    # Build the lexical ground-truth layer once on the whole document so § / ##
    # boundaries are honoured across former 40 KB cuts.
    chunks = chunker.split(full_text)
    if chunks:
        chunker.write_chunks(source_name, chunks)
        if os.getenv("INGEST_QA", "1") == "1":
            try:
                qa_items = qa_gen.generate(chunks, source=source_name)
                qa_gen.persist(qa_items, source_name)
            except Exception:
                pass  # qa-gen is best-effort; never fail ingest on it

    return {
        "system": system,
        "source_name": source_name,
        "index_text": index_text,
        "meta_block": meta_block,
        "example_extra": example_extra,
        # Affected pages are now selected per piece via BM25 (see ingest_piece);
        # `affected` accumulates the union across pieces for the result/log.
        "src_to_pages": _source_to_pages(),
        "affected": [],
        "chunks": chunks,
        "created": [],
        "updated": [],
        "contradictions": [],
        "existing_filenames": {p["filename"] for p in list_pages()},
    }


def ingest_piece(ctx: dict, piece_text: str, index: int = 0, total: int = 1) -> None:
    """Run the LLM wiki-synthesis for one 40 KB piece. Mutates `ctx` in place."""
    piece_source = ctx["source_name"] if total == 1 else f"{ctx['source_name']} [Teil {index + 1}/{total}]"
    # BM25-select the existing pages THIS piece most likely updates, then inject
    # their content (rank-weighted budget) for an accurate merge. Per-piece so a
    # later piece of a long document can surface pages the first piece didn't.
    ranked = _select_affected_pages(piece_text, ctx["src_to_pages"], exclude_source=ctx["source_name"])
    for fname in ranked:
        if fname not in ctx["affected"]:
            ctx["affected"].append(fname)
    existing_block = _build_existing_block(ranked)
    prompt = INGEST_PROMPT.format(
        source_name=piece_source,
        meta_block=ctx["meta_block"],
        index_text=ctx["index_text"],
        existing_block=existing_block,
        text=piece_text,
        summary_slug=_title_to_filename(piece_source).replace(".md", ""),
        example_extra=ctx["example_extra"],
        date=_date(),
    )

    response = ollama_client.generate(ctx["system"], prompt, temperature=0.3, model_id=ollama_client._INGEST_MODEL)
    pages = _parse_llm_pages(response)

    if not pages:
        retry_prompt = (
            "Your previous response did not contain any `=== filename.md === ... === END ===` blocks. "
            "Reformat your output now using EXACTLY that delimiter. Same content, correct format.\n\n"
            f"Original task was:\n{prompt}"
        )
        response = ollama_client.generate(ctx["system"], retry_prompt, temperature=0.2, model_id=ollama_client._INGEST_MODEL)
        pages = _parse_llm_pages(response)

    for page in pages:
        dest = _wiki() / page["filename"]
        content = _ensure_frontmatter(page["content"], page["filename"])
        # Merge current source into frontmatter `sources:` so the graph viz can
        # draw `derived-from` edges (source → page) without trusting the LLM
        # to have written it correctly.
        content = _ensure_source_in_frontmatter(content, ctx["source_name"])
        content = _scrub_related(content, ctx["existing_filenames"])
        if dest.exists():
            if page["filename"] not in ctx["updated"] and page["filename"] not in ctx["created"]:
                ctx["updated"].append(page["filename"])
        else:
            if page["filename"] not in ctx["created"]:
                ctx["created"].append(page["filename"])
        dest.write_text(content)

    for line in response.splitlines():
        if line.startswith("UPDATE:"):
            fname = line.split(":", 1)[1].strip()
            if fname and fname not in ctx["updated"] and fname not in ctx["created"]:
                ctx["updated"].append(fname)
        elif line.startswith("CONTRADICTION:"):
            ctx["contradictions"].append(line.split(":", 1)[1].strip())


def ingest_end(ctx: dict) -> dict:
    """Finalise: single lex_index rebuild, index page rebuild, log entry."""
    if ctx["chunks"]:
        lex_index.build()
    _rebuild_index()
    if os.getenv("INGEST_DESCRIPTION", "1") == "1":
        try:
            update_description(ctx)
        except Exception:
            pass  # best-effort; never fail ingest on the overview refresh
    _append_log(
        f"Ingest: {ctx['source_name']}",
        f"Affected: {ctx['affected']}\nCreated: {ctx['created']}\n"
        f"Updated: {ctx['updated']}\nContradictions: {ctx['contradictions']}",
    )
    return {
        "created": ctx["created"],
        "updated": ctx["updated"],
        "contradictions": ctx["contradictions"],
        "affected": ctx["affected"],
        "chunks": len(ctx["chunks"]),
    }


def ingest(text: str, source_name: str, user_meta: dict | None = None) -> dict:
    """Back-compat single-call ingest. New callers should use begin/piece/end.

    Internally: begin + one piece + end. Identical end-state to the previous
    monolithic implementation, just routed through the three new helpers.
    """
    ctx = ingest_begin(text, source_name, user_meta)
    ingest_piece(ctx, text, 0, 1)
    return ingest_end(ctx)


def rebuild_lex_index() -> dict:
    """Rebuild the BM25 index from all persisted chunks. Returns a summary."""
    return lex_index.build()


def delete_source(source_name: str) -> dict:
    """Remove a source and all derived data. Wiki pages referencing it are deleted.

    Returns a summary dict with keys: raw, manifest, chunks, qa_rows, wiki_pages.
    """
    result: dict = {"raw": False, "manifest": False, "chunks": False, "qa_rows": 0, "wiki_pages": []}

    raw_file = _raw() / source_name
    if raw_file.exists():
        raw_file.unlink()
        result["raw"] = True

    result["manifest"] = dedup.deregister_source(source_name)

    chunk_file = db_context.chunks_dir() / f"{chunker._slug(source_name)}.jsonl"
    if chunk_file.exists():
        chunk_file.unlink()
        result["chunks"] = True

    result["qa_rows"] = qa_gen.delete_source_entries(source_name)

    # Cascade through wiki pages: drop this source from every page's
    # frontmatter; delete pages whose `sources:` becomes empty; then scrub
    # surviving pages' `related:` lists of any references to deleted pages.
    _SKIP = set(_SYSTEM_PAGES)
    insights = _wiki() / _INSIGHTS_DIR

    def _all_pages() -> list[Path]:
        out = [p for p in _wiki().glob("*.md") if p.name not in _SKIP]
        if insights.exists():
            out.extend(p for p in insights.glob("*.md") if p.name not in _SKIP)
        return out

    def _rel(md: Path) -> str:
        return md.name if md.parent == _wiki() else f"{_INSIGHTS_DIR}/{md.name}"

    removed_pages: set[str] = set()
    for md in _all_pages():
        try:
            post = frontmatter.load(str(md))
        except Exception:
            continue
        sources = post.metadata.get("sources", []) or []
        kept = [s for s in sources if not str(s).startswith(source_name)]
        if sources and not kept:
            md.unlink()
            removed_pages.add(_rel(md))
        elif len(kept) != len(sources):
            post.metadata["sources"] = kept
            post.metadata["updated"] = _date()
            md.write_text(frontmatter.dumps(post))

    scrubbed = 0
    if removed_pages:
        for md in _all_pages():
            try:
                post = frontmatter.load(str(md))
            except Exception:
                continue
            related = post.metadata.get("related", []) or []
            cleaned = [r for r in related if str(r).strip() not in removed_pages]
            if len(cleaned) != len(related):
                post.metadata["related"] = cleaned
                post.metadata["updated"] = _date()
                md.write_text(frontmatter.dumps(post))
                scrubbed += 1

    result["wiki_pages"] = sorted(removed_pages)
    result["related_scrubbed"] = scrubbed

    lex_index.build()
    _rebuild_index()
    if os.getenv("INGEST_DESCRIPTION", "1") == "1":
        try:
            refresh_description_after_delete(source_name, result["wiki_pages"])
        except Exception:
            pass  # best-effort; never fail deletion on the overview refresh
    _append_log(
        "Source deleted",
        f"Source: {source_name}\n"
        f"Raw file removed: {result['raw']}\n"
        f"Chunks removed: {result['chunks']}\n"
        f"QA rows removed: {result['qa_rows']}\n"
        f"Wiki pages removed: {result['wiki_pages']}\n"
        f"Related scrubbed: {scrubbed}",
    )
    return result


def reset_all_data() -> dict:
    """Wipe every raw source, chunk, lexical index entry, and wiki page.

    Re-initialises the wiki to its empty bootstrap state. Returns a count
    of files removed per top-level data directory.
    """
    targets = [_raw(), db_context.chunks_dir(), db_context.index_dir(), _wiki()]
    counts: dict[str, int] = {}
    for d in targets:
        if d.exists():
            counts[d.name] = sum(1 for p in d.rglob("*") if p.is_file())
            shutil.rmtree(d)
        else:
            counts[d.name] = 0
    init_wiki()
    db_context.chunks_dir().mkdir(parents=True, exist_ok=True)
    db_context.index_dir().mkdir(parents=True, exist_ok=True)
    lex_index.build()
    _append_log("Reset all data", f"Files removed per dir: {counts}")
    return counts


def query(question: str) -> str:
    """Answer a question using wiki content (string form, kept for back-compat)."""
    return query_with_sources(question)["answer"]


def condense_followup(prev_q: str, prev_a: str, followup: str) -> str:
    """Rewrite a follow-up into a standalone question. Falls back to the raw
    follow-up if the model errors or returns empty."""
    try:
        out = ollama_client.generate(
            system="You rewrite follow-up questions into standalone ones.",
            prompt=CONDENSE_PROMPT.format(
                prev_q=prev_q, prev_a=(prev_a or "")[:1600], followup=followup),
            temperature=0.1,
        ).strip()
        return out or followup
    except Exception:
        return followup


def _candidate_pages_for_query(question: str) -> list[str]:
    """BM25 candidate wiki pages for a question (Q-1).

    Unions wiki-scope hits (the hit `source` IS the page filename) with raw-scope
    hits mapped to pages via `_source_to_pages()`, preserving score order. Empty
    when the index has no match — the caller then falls back to index-blurb LLM
    selection.
    """
    cands: list[str] = []
    seen: set[str] = set()

    def _add(fname: str) -> None:
        f = (fname or "").strip()
        if f and f not in seen and f not in _SYSTEM_PAGES and (_wiki() / f).exists():
            seen.add(f)
            cands.append(f)

    try:
        for h in lex_index.query(question, top_k=_QUERY_CANDIDATE_TOPK, scope="wiki"):
            _add(h.get("source", ""))
    except Exception:
        pass
    src_map = _source_to_pages()
    try:
        for h in lex_index.query(question, top_k=_QUERY_CANDIDATE_TOPK, scope="raw"):
            for f in src_map.get((h.get("source") or "").strip(), []):
                _add(f)
    except Exception:
        pass
    return cands[:_QUERY_MAX_CANDIDATES]


def _index_text_for(filenames: list[str]) -> str:
    """A minimal `index.md`-style block (title — description) for given pages."""
    by_name = {p["filename"]: p for p in list_pages()}
    lines = []
    for f in filenames:
        p = by_name.get(f)
        if p:
            lines.append(f"- [{p.get('title', f)}]({f}) — {p.get('description', '')}")
    return "\n".join(lines)


def _select_pages(question: str, system: str, index_text: str) -> list[str]:
    """Pick the wiki pages to answer from (Q-1: BM25 pre-select → LLM re-rank).

    When BM25 surfaces candidates, the LLM re-ranks only those (high precision);
    otherwise it selects from the full index (recall fallback). Always returns
    valid existing page filenames, capped at 5.
    """
    candidates = _candidate_pages_for_query(question)
    rank_index = _index_text_for(candidates) if candidates else index_text
    select_prompt = SELECT_PROMPT.format(index_text=rank_index, question=question)
    selected_raw = ollama_client.generate(
        system, select_prompt, temperature=0.1, model_id=ollama_client._QUERY_MODEL)
    selected = [
        ln.strip()
        for ln in selected_raw.splitlines()
        if ln.strip().endswith(".md") and ln.strip() not in _SYSTEM_PAGES
    ]
    if candidates:
        cand_set = set(candidates)
        selected = [s for s in selected if s in cand_set] or candidates[:5]
    return [s for s in selected if (_wiki() / s).exists()][:5]


def query_with_sources(question: str) -> dict:
    """Answer a question using wiki content. Returns {answer, sources, raw_sources}."""
    system = schema_loader.get_system_prompt(mode="query")
    index_text = _index_path().read_text() if _index_path().exists() else "(empty wiki)"

    selected = _select_pages(question, system, index_text)

    # Q-3: inject the most relevant chunks per page (with anchors), not full pages.
    hits_by_page: dict[str, list[dict]] = {}
    try:
        for h in lex_index.query(question, top_k=_QUERY_CANDIDATE_TOPK, scope="wiki"):
            hits_by_page.setdefault(h.get("source", ""), []).append(h)
    except Exception:
        pass

    pages_text = ""
    used_sources = []
    raw_sources_set: set[str] = set()
    for fname in selected:
        path = _wiki() / fname
        if not path.exists():
            continue
        used_sources.append(fname)
        try:
            raw_sources_set.update(frontmatter.loads(path.read_text()).get("sources", []))
        except Exception:
            pass
        hits = hits_by_page.get(fname, [])[:_QUERY_CHUNKS_PER_PAGE]
        if hits:
            for h in hits:
                anchor = h.get("anchor") or ""
                header = f"--- {fname}{(' ' + anchor) if anchor else ''} ---"
                pages_text += f"\n\n{header}\n{h.get('text', '')}"
        else:  # page not surfaced by the wiki query (title-only / fallback select)
            body = read_page_parsed(fname)["content"]
            pages_text += f"\n\n--- {fname} ---\n{body[:_QUERY_PAGE_FALLBACK_CHARS]}"
        if len(pages_text) >= _QUERY_SYNTH_MAX_CHARS:
            pages_text = pages_text[:_QUERY_SYNTH_MAX_CHARS] + "\n…[truncated]"
            break

    if not pages_text:
        pages_text = "(no relevant pages found)"

    answer_prompt = ANSWER_PROMPT.format(pages_text=pages_text, question=question)
    answer = ollama_client.generate(system, answer_prompt, temperature=0.7)
    return {"answer": answer, "sources": used_sources, "raw_sources": sorted(raw_sources_set)}


def lint() -> str:
    """Run wiki health check. Returns the lint report."""
    system = schema_loader.get_system_prompt(mode="query")
    all_pages = ""
    for md in sorted(_wiki().glob("*.md")):
        if md.name in _SYSTEM_PAGES:
            continue
        all_pages += f"\n\n--- {md.name} ---\n{md.read_text()}"

    if not all_pages:
        return "Wiki is empty — nothing to lint."

    report = ollama_client.generate(system, LINT_PROMPT.format(all_pages=all_pages), temperature=0.3, model_id=ollama_client._FAST_MODEL)

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
    for md in sorted(_wiki().glob("*.md")):
        if md.name in _SYSTEM_PAGES:
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
    path = _wiki() / filename
    if not path.exists():
        return f"Page not found: {filename}"
    return path.read_text()


def read_page_parsed(filename: str) -> dict:
    """Return body content and frontmatter sources/related without the YAML header."""
    path = _wiki() / filename
    if not path.exists():
        return {"content": f"Page not found: {filename}", "sources": [], "related": []}
    post = frontmatter.load(str(path))
    return {
        "content": post.content,
        "sources": post.metadata.get("sources", []),
        "related": post.metadata.get("related", []),
    }


def read_raw_source(filename: str) -> bytes | None:
    path = _raw() / filename
    return path.read_bytes() if path.exists() else None


# --- DESCRIPTION.md: half-page high-level overview of the whole database ----

def _cap_description(text: str) -> str:
    """Trim the overview to _DESCRIPTION_MAX_CHARS on a paragraph/sentence break."""
    text = text.strip()
    if len(text) <= _DESCRIPTION_MAX_CHARS:
        return text
    cut = text[:_DESCRIPTION_MAX_CHARS]
    for sep in ("\n\n", ". ", " "):
        idx = cut.rfind(sep)
        if idx > _DESCRIPTION_MAX_CHARS // 2:
            return cut[:idx].strip()
    return cut.strip()


def read_description() -> str:
    """Return the database overview text, or '' if missing/empty."""
    path = _description_path()
    return path.read_text().strip() if path.exists() else ""


def build_description() -> str:
    """Synthesize the database overview from the current wiki index and persist it."""
    system = schema_loader.get_system_prompt(mode="query")
    index_text = _index_path().read_text() if _index_path().exists() else ""
    prompt = DESCRIPTION_BUILD_PROMPT.format(
        db_name=db_context.get_active_db(), index_text=index_text
    )
    text = _cap_description(ollama_client.generate(system, prompt, temperature=0.3))
    _description_path().write_text(text)
    return text


def ensure_description() -> None:
    """One-time seed: build the overview if it's missing and the wiki has pages."""
    if read_description() or not list_pages():
        return
    try:
        build_description()
    except Exception:
        pass  # best-effort; never block the page render on it


def update_description(ctx: dict) -> None:
    """Conditionally refresh the overview after an ingest (LLM decides via NO_CHANGE)."""
    current = read_description()
    if not current:
        if list_pages():
            build_description()
        return
    titles = ctx.get("created", []) + ctx.get("updated", [])
    change_summary = (
        f"Source: {ctx['source_name']}\n"
        f"Pages created/updated: {', '.join(titles) if titles else '(none)'}"
    )
    system = schema_loader.get_system_prompt(mode="query")
    index_text = _index_path().read_text() if _index_path().exists() else ""
    prompt = DESCRIPTION_UPDATE_PROMPT.format(
        db_name=db_context.get_active_db(),
        current=current,
        change_summary=change_summary,
        index_text=index_text,
    )
    response = ollama_client.generate(system, prompt, temperature=0.3).strip()
    if response and response != "NO_CHANGE":
        _description_path().write_text(_cap_description(response))


def refresh_description_after_delete(source_name: str, removed_pages: list[str]) -> None:
    """Conditionally refresh the overview after a source deletion."""
    if not list_pages():
        _description_path().write_text("")  # nothing left to describe
        return
    if not removed_pages:
        return  # page set unchanged → overview still representative
    current = read_description()
    if not current:
        return  # nothing to update; ensure_description() seeds it lazily on render
    change_summary = (
        f"Deleted source: {source_name}\n"
        f"Wiki pages removed: {', '.join(removed_pages)}"
    )
    system = schema_loader.get_system_prompt(mode="query")
    index_text = _index_path().read_text() if _index_path().exists() else ""
    prompt = DESCRIPTION_DELETE_PROMPT.format(
        db_name=db_context.get_active_db(),
        current=current,
        change_summary=change_summary,
        index_text=index_text,
    )
    response = ollama_client.generate(system, prompt, temperature=0.3).strip()
    if response and response != "NO_CHANGE":
        _description_path().write_text(_cap_description(response))


_TYPE_GROUPS = ("concept", "entity", "source-summary", "comparison")


def search_wiki(query: str) -> list[dict]:
    """BM25 full-text search over wiki page bodies (R-1).

    Queries the wiki-scoped lexical index (page bodies + their title/filename),
    deduplicates to one result per page (best-scoring chunk wins), and returns
    `{"filename", "title", "excerpt"}`. Empty query returns []. Requires the index
    to have been built (ingest_end / rebuild); returns [] if it is empty.
    """
    q = query.strip()
    if not q:
        return []
    try:
        hits = lex_index.query(q, top_k=30, scope="wiki")
    except Exception:
        hits = []
    titles = {p["filename"]: str(p.get("title", p["filename"])) for p in list_pages()}
    results: list[dict] = []
    seen: set[str] = set()
    for h in hits:
        fname = h.get("source", "")
        if not fname or fname in seen:
            continue
        seen.add(fname)
        excerpt = (h.get("preview") or h.get("text", "")[:320]).replace("\n", " ").strip()
        results.append({
            "filename": fname,
            "title": titles.get(fname, fname.replace(".md", "")),
            "excerpt": excerpt,
        })
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
    return _log_path().read_text() if _log_path().exists() else "(no log yet)"


def file_answer(question: str, answer: str, related: list[str] | None = None) -> str:
    """Persist a Q&A as a wiki insight page (Karpathy filing-back mechanic).

    Returns the relative filename written under data/wiki/insights/.
    """
    insights_dir = _wiki() / _INSIGHTS_DIR
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
    insights = _wiki() / _INSIGHTS_DIR
    if insights.exists():
        for md in insights.glob("*.md"):
            existing.add(f"{_INSIGHTS_DIR}/{md.name}")

    graph: dict[str, set[str]] = {}
    targets = [_wiki().glob("*.md")]
    if insights.exists():
        targets.append(insights.glob("*.md"))

    for src_iter in targets:
        for md in src_iter:
            if md.name in _SYSTEM_PAGES:
                continue
            try:
                post = frontmatter.load(str(md))
                rel = post.metadata.get("related", []) or []
            except Exception:
                rel = []
            key = md.name if md.parent == _wiki() else f"{_INSIGHTS_DIR}/{md.name}"
            edges = set()
            for r in rel:
                r = str(r).strip()
                if r and r != key and r in existing and r not in _SYSTEM_PAGES:
                    edges.add(r)
            graph[key] = edges
    return graph


def build_typed_graph() -> dict:
    """Return a typed node/edge list for the wiki graph viz.

    Two node types:
      - `page`   : wiki page filename (e.g. `strahlenschutzgesetz.md`)
      - `source` : raw source filename pulled from each page's `sources:` field

    Two edge types:
      - `related-to`  : page ↔ page, from frontmatter `related:` (existing)
      - `derived-from`: page → source, from frontmatter `sources:`
    """
    existing = {p["filename"] for p in list_pages()}
    insights = _wiki() / _INSIGHTS_DIR
    if insights.exists():
        for md in insights.glob("*.md"):
            existing.add(f"{_INSIGHTS_DIR}/{md.name}")

    def _raw_source(name: str) -> str:
        return _TEIL_SUFFIX_RE.sub("", str(name)).strip()

    nodes: dict[str, dict] = {}
    edges: list[dict] = []
    related_pairs: set[frozenset[str]] = set()
    derived_pairs: set[tuple[str, str]] = set()
    source_set: set[str] = set()


    targets = [_wiki().glob("*.md")]
    if insights.exists():
        targets.append(insights.glob("*.md"))

    for src_iter in targets:
        for md in src_iter:
            if md.name in _SYSTEM_PAGES:
                continue
            try:
                post = frontmatter.load(str(md))
                related = post.metadata.get("related", []) or []
                sources = post.metadata.get("sources", []) or []
                title = str(post.metadata.get("title", md.stem))
                ptype = str(post.metadata.get("type", "other")).strip().lower()
            except Exception:
                related, sources, title, ptype = [], [], md.stem, "other"
            if ptype not in ("concept", "entity", "source-summary"):
                continue
            is_page = ptype in ("concept", "entity")
            page_id = md.name if md.parent == _wiki() else f"{_INSIGHTS_DIR}/{md.name}"
            if is_page:
                nodes[page_id] = {"id": page_id, "type": "page", "label": title}
                for r in related:
                    r = str(r).strip()
                    if r and r != page_id and r in existing and r not in _SYSTEM_PAGES:
                        pair = frozenset({page_id, r})
                        if pair not in related_pairs:
                            related_pairs.add(pair)
                            edges.append({"from": page_id, "to": r, "type": "related-to"})
            for s in sources:
                raw = _raw_source(s)
                if (
                    not raw
                    or raw == "chat"
                    or raw.startswith("summary-")
                    or raw.startswith("concept-")
                    or raw.startswith("entity-")
                ):
                    continue
                source_id = f"source::{raw}"
                source_set.add(raw)
                if not is_page:
                    # source-summary: register source node but emit no page→source edge
                    continue
                pair = (page_id, source_id)
                if pair in derived_pairs:
                    continue
                derived_pairs.add(pair)
                edges.append({"from": page_id, "to": source_id, "type": "derived-from"})

    for s in source_set:
        nodes[f"source::{s}"] = {"id": f"source::{s}", "type": "source", "label": s}


    return {"nodes": list(nodes.values()), "edges": edges}


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
        path = _wiki() / fname
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
        dest = _wiki() / page["filename"]
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
    raw_count = len(list(_raw().glob("*"))) - 1 if _raw().exists() else 0  # exclude manifest
    data_bytes = (
        sum(p.stat().st_size for p in _wiki().rglob("*") if p.is_file()) if _wiki().exists() else 0
    ) + (
        sum(p.stat().st_size for p in _raw().rglob("*") if p.is_file()) if _raw().exists() else 0
    )
    return {
        "pages": len(pages),
        "raw_files": max(0, raw_count),
        "data_bytes": data_bytes,
    }
