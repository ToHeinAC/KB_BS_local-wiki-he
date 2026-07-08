"""Core wiki operations: init, ingest, query, lint, list, read."""

import os
import re
import shutil
from datetime import date, datetime, timezone
from pathlib import Path

import frontmatter
from dotenv import load_dotenv

import chunker
import db_context
import dedup
import lang
import lex_index
import okf
import ollama_client
import qa_gen
import schema_loader
from prompts import (
    ANSWER_PROMPT,
    CONDENSE_PROMPT,
    CONSOLIDATE_POLISH_PROMPT,
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
# Temporal staleness (E-1): a page is stale when `updated` + TTL < today. TTL is the
# page's own `expires_after_days` frontmatter if set, else this default.
_DEFAULT_EXPIRE_DAYS = int(os.getenv("STALE_AFTER_DAYS", "365"))
_TEIL_SUFFIX_RE = re.compile(r"\s*\[Teil\s+\d+/\d+\]\s*(?:\.md)?\s*$")


def init_wiki() -> None:
    _wiki().mkdir(parents=True, exist_ok=True)
    _raw().mkdir(parents=True, exist_ok=True)
    if not _index_path().exists():
        _index_path().write_text(
            f'---\ntitle: Index\nokf_version: "{okf.OKF_VERSION}"\n---\n\n# Pages\n'
        )
    if not _log_path().exists():
        _log_path().write_text("---\ntitle: Activity Log\n---\n\n# Log\n")
    if not _description_path().exists():
        _description_path().write_text("")


def _date() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _parse_date(value) -> date | None:
    try:
        return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


def is_page_stale(meta: dict, today: date | None = None) -> bool:
    """True when a page is past its freshness window (E-1).

    Window = the page's `expires_after_days` frontmatter (int), else
    `_DEFAULT_EXPIRE_DAYS`. A non-positive TTL or an unparseable `updated` date
    means 'never stale'.
    """
    updated = _parse_date(meta.get("updated"))
    if updated is None:
        return False
    try:
        ttl = int(meta.get("expires_after_days"))
    except (TypeError, ValueError):
        ttl = _DEFAULT_EXPIRE_DAYS
    if ttl <= 0:
        return False
    today = today or datetime.now(timezone.utc).date()
    return (today - updated).days > ttl


def stale_pages() -> list[str]:
    """Filenames of all pages (incl. insights) currently flagged stale."""
    return [p["filename"] for p in list_pages(include_insights=True) if is_page_stale(p)]


def _append_log(action: str, detail: str) -> None:
    """OKF-format log write: newest-first under a `## YYYY-MM-DD` date section."""
    path = _log_path()
    text = path.read_text() if path.exists() else ""
    time = datetime.now(timezone.utc).strftime("%H:%M")
    path.write_text(okf.add_log_entry(text, action, detail, day=_date(), time=time))


def _rebuild_index() -> None:
    pages = list_pages(include_insights=True)
    main = [p for p in pages if p.get("type") != "insight"]
    insights = [p for p in pages if p.get("type") == "insight"]

    def _line(p: dict) -> str:
        return f"* [{p.get('title', p['filename'])}]({p['filename']}) - {p.get('description', '')}\n"

    head = ("---\ntitle: Index\n"
            f'okf_version: "{okf.OKF_VERSION}"\n'
            f'updated: "{_date()}"\n---\n\n# Pages\n')
    lines = [head]
    lines += [_line(p) for p in main]
    if insights:
        lines.append("\n# Insights\n")
        lines += [_line(p) for p in insights]
    _index_path().write_text("".join(lines))


def _title_to_filename(title: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return f"{slug}.md"


# --- Deterministic dedup-routing + merge (model-independent) -----------------
# These helpers let a small local model name pages freely while CODE decides
# whether a freshly-synthesised page is the same topic as an existing one and,
# if so, merges them. All matching is deterministic so model quality is moot.

_STOPWORDS_SLUG = {"of", "the", "and", "a", "an", "to", "in", "for", "on",
                   "with", "md", "der", "die", "das", "und", "von", "im"}
_PAGE_PREFIX_RE = re.compile(r"^(concept|entity|summary|report|insight)-")
_FILE_TEIL_RE = re.compile(r"-teil-\d+-\d+(?=\.md$|$)")
_KEY_FACTS_HEADING = "## Key facts"
_TERM_OVERLAP_THRESHOLD = 0.7
_MAX_KEY_TERMS = 12
# number+unit pairs used for the deterministic contradiction check. Units are a
# pragmatic mix of the project's domains (radiation, generic %, sizes, time).
_NUM_UNIT_RE = re.compile(
    r"(\d+(?:[.,]\d+)?)\s*(%|mSv|µSv|uSv|Sv|mGy|Gy|Bq|kg|km|mm|cm|gb|tb|mb|"
    r"days?|jahre?|years?|hours?|tokens?|mio|mrd)\b",
    re.IGNORECASE,
)


def _depluralize(tok: str) -> str:
    """Fold simple English plurals the lex stemmer's 4-char floor misses.

    `lex_index._stem` leaves <=4-char tokens untouched, so `llms` would not fold
    to `llm` — the flagship duplicate case. This closes that gap.
    """
    if len(tok) >= 5 and tok.endswith("es"):
        return tok[:-2]
    if len(tok) >= 4 and tok.endswith("s") and not tok.endswith("ss"):
        return tok[:-1]
    return tok


def _term_key(tok: str) -> str:
    """Canonical comparison key for one surface token.

    Depluralize only when the lex stemmer left the token unchanged — otherwise
    the stemmer already handled the suffix and a second strip would over-trim
    (e.g. `densing`→`dens` must NOT become `den`).
    """
    folded = lex_index._nfkd_fold(tok.lower())
    stemmed = lex_index._stem(folded)
    return _depluralize(stemmed) if stemmed == folded else stemmed


def _canonical_slug_tokens(name: str) -> frozenset[str]:
    """Topic token-set for a filename or title (prefix/stopwords/plurals folded)."""
    base = name.lower()
    if base.endswith(".md"):
        base = base[:-3]
    base = _PAGE_PREFIX_RE.sub("", base)
    keys = {_term_key(t) for t in re.split(r"[^a-z0-9]+", base)
            if t and t not in _STOPWORDS_SLUG}
    return frozenset(k for k in keys if k)


def _parse_index_block(body: str) -> list[str]:
    """Bullet lines under a leading '## Key facts' heading (the page's index)."""
    out, capturing = [], False
    for line in body.splitlines():
        s = line.strip()
        if s.lower().startswith("## key facts"):
            capturing = True
            continue
        if capturing:
            if s.startswith("## "):
                break
            if s.startswith("- "):
                out.append(s[2:].strip())
    return out


def _extract_key_terms(content: str) -> list[str]:
    """Canonical key terms from the title + the `## Key facts` bullets (capped)."""
    try:
        post = frontmatter.loads(content)
        title, body = str(post.metadata.get("title", "")), post.content
    except Exception:
        title, body = "", content
    text = title + "\n" + "\n".join(_parse_index_block(body))
    terms, seen = [], set()
    for tok in re.split(r"[^A-Za-z0-9]+", text):
        if len(tok) < 2 or tok.lower() in _STOPWORDS_SLUG:
            continue
        k = _term_key(tok)
        if k and k not in seen:
            seen.add(k)
            terms.append(k)
        if len(terms) >= _MAX_KEY_TERMS:
            break
    return terms


def _ensure_key_terms(content: str) -> str:
    """Stamp the derived `key_terms` list into frontmatter (idempotent)."""
    try:
        post = frontmatter.loads(content)
    except Exception:
        return content
    post.metadata["key_terms"] = _extract_key_terms(content)
    return frontmatter.dumps(post) + "\n"


def _readable_facts(content: str) -> list[str]:
    """Human-readable index bullets: page title + its `##`/`###` section headings."""
    try:
        post = frontmatter.loads(content)
        title, body = str(post.metadata.get("title", "")), post.content
    except Exception:
        title, body = "", content
    facts = [title] if title else []
    for line in body.splitlines():
        if re.match(r"^#{2,3}\s", line.strip()):
            h = line.strip().lstrip("#").strip()
            if h and h.lower() != "key facts" and h not in facts:
                facts.append(h)
        if len(facts) >= 5:
            break
    return facts[:5]


def _ensure_index_block(content: str) -> str:
    """Prepend a `## Key facts` index when the model didn't write one.

    Synthesised bullets use the title + section headings (readable), not the
    internal stem `key_terms`. Pages that already have a `## Key facts` block
    (e.g. fresh model output) are left untouched.
    """
    try:
        post = frontmatter.loads(content)
    except Exception:
        return content
    if _parse_index_block(post.content):
        return content
    facts = _readable_facts(content)
    if not facts:
        return content
    block = _KEY_FACTS_HEADING + "\n" + "\n".join(f"- {f}" for f in facts)
    post.content = block + "\n\n" + post.content.lstrip()
    return frontmatter.dumps(post) + "\n"


def _page_type(content: str, filename: str = "") -> str:
    try:
        t = str(frontmatter.loads(content).metadata.get("type", "") or "").strip().lower()
    except Exception:
        t = ""
    if t:
        return t
    return "source-summary" if filename.startswith("summary-") else "concept"


def _page_title(content: str, filename: str = "") -> str:
    try:
        return str(frontmatter.loads(content).metadata.get("title", "") or "") or filename
    except Exception:
        return filename


def _overlap_coef(a: frozenset, b: frozenset) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / min(len(a), len(b))


def _route_page(ptype: str, tokens: frozenset, terms: frozenset,
                registry: dict, self_filename: str) -> str | None:
    """Existing filename this page should merge into, or None to create new.

    Same `type` only. Exact topic-token match wins; otherwise a subset relation
    (one topic is a specialization of the other) gated by >= 0.7 key-term overlap.
    """
    if not tokens:
        return None
    exact = subset = None
    for fname, info in registry.items():
        if fname == self_filename or info["type"] != ptype:
            continue
        ctoks = info["tokens"]
        if not ctoks:
            continue
        if tokens == ctoks:
            exact = exact or fname
        elif (tokens <= ctoks or ctoks <= tokens) and \
                _overlap_coef(terms, info["terms"]) >= _TERM_OVERLAP_THRESHOLD:
            subset = subset or fname
    return exact or subset


def _split_sections(body: str) -> list[list]:
    """[[heading, [lines]]]; pre-heading lead text uses heading ''."""
    sections: list[list] = [["", []]]
    for line in body.splitlines():
        if re.match(r"^#{1,6}\s", line):
            sections.append([line.strip(), []])
        else:
            sections[-1][1].append(line)
    return sections


def _norm_line(line: str) -> str:
    return re.sub(r"\s+", " ", line.strip().lower())


def _merge_bodies(existing: str, new: str) -> str:
    """Union of sections; appends only non-duplicate lines (no fact dropped)."""
    e_secs = _split_sections(existing)
    heading_idx = {h.lower(): i for i, (h, _) in enumerate(e_secs) if h}
    seen = {_norm_line(l) for _, ls in e_secs for l in ls if l.strip()}
    for h, lines in _split_sections(new):
        add = [l for l in lines if not l.strip() or _norm_line(l) not in seen]
        add = [l for l in add if l.strip() or (add and h)]  # drop leading blanks
        key = h.lower()
        if h and key in heading_idx:
            e_secs[heading_idx[key]][1].extend(l for l in add if l.strip())
        elif h:
            e_secs.append([h, [l for l in lines if l.strip()]])
            heading_idx[key] = len(e_secs) - 1
        else:
            e_secs[0][1].extend(l for l in add if l.strip())
        seen.update(_norm_line(l) for l in lines if l.strip())
    out: list[str] = []
    for h, lines in e_secs:
        if h:
            out.append(h)
        out.extend(lines)
    return "\n".join(out).strip() + "\n"


def _union_list(a, b) -> list:
    merged = [str(x).strip() for x in (a or []) if str(x).strip()]
    for v in (b or []):
        v = str(v).strip()
        if v and v not in merged:
            merged.append(v)
    return merged


def _is_newer(nmeta: dict, emeta: dict) -> bool:
    nd = _parse_date(nmeta.get("effective as of") or nmeta.get("updated") or nmeta.get("created"))
    ed = _parse_date(emeta.get("effective as of") or emeta.get("updated") or emeta.get("created"))
    return bool(nd and ed and nd > ed)


def _extract_facts(text: str) -> dict[str, set[str]]:
    """Map `term|unit` -> set of values, for the contradiction check."""
    facts: dict[str, set[str]] = {}
    for m in _NUM_UNIT_RE.finditer(text):
        num, unit = m.group(1).replace(",", "."), m.group(2).lower()
        words = re.findall(r"[A-Za-zÄÖÜäöüß][\w-]+", text[max(0, m.start() - 40):m.start()])
        term = _term_key(words[-1]) if words else ""
        facts.setdefault(f"{term}|{unit}", set()).add(f"{num} {unit}")
    return facts


def _contradiction_check(existing: str, new: str, emeta: dict, nmeta: dict) -> list[str]:
    """Flag same-term/same-unit numeric conflicts. Resolves only on a date signal."""
    ef, nf = _extract_facts(existing), _extract_facts(new)
    newer = _is_newer(nmeta, emeta)
    out = []
    for key, nvals in nf.items():
        evals = ef.get(key)
        if not evals or not (nvals - evals):
            continue
        term = key.split("|")[0]
        old, newv = ", ".join(sorted(evals)), ", ".join(sorted(nvals))
        if newer:
            out.append(f"{term}: now {newv} per the newer source; previously {old}")
        else:
            out.append(f"{term}: sources disagree — {old} vs {newv} (unresolved)")
    return out


def _merge_pages(existing: str, new: str, source: str) -> str:
    """Deterministic, no-LLM merge of `new` into `existing`. Never drops a fact."""
    try:
        ep, np_ = frontmatter.loads(existing), frontmatter.loads(new)
    except Exception:
        return existing
    meta = dict(ep.metadata)
    for key in ("sources", "related", "key_terms"):
        meta[key] = _union_list(ep.metadata.get(key), np_.metadata.get(key))
    nc = _parse_date(np_.metadata.get("created"))
    ec = _parse_date(ep.metadata.get("created"))
    if nc and (not ec or nc < ec):
        meta["created"] = np_.metadata.get("created")
    meta["updated"] = _date()
    body = _merge_bodies(ep.content, np_.content)
    contradictions = _contradiction_check(ep.content, np_.content, ep.metadata, np_.metadata)
    if contradictions:
        body = body.rstrip() + "\n\n## Contradictions\n" + \
            "\n".join(f"- {c}" for c in contradictions) + "\n"
        meta["confidence"] = "low"
    out = frontmatter.dumps(frontmatter.Post(body, **meta)) + "\n"
    out = _ensure_key_terms(out)
    out = _ensure_index_block(out)
    return _okf_apply(out)  # keep merged pages OKF-conformant for every caller


def _build_registry() -> dict:
    """{filename: {type, tokens, terms}} for every existing page (routing input)."""
    reg: dict[str, dict] = {}
    for p in list_pages():
        fn = p["filename"]
        terms = p.get("key_terms")
        if not terms:
            terms = _extract_key_terms(read_page(fn))
        reg[fn] = {
            "type": str(p.get("type") or "concept").strip().lower(),
            "tokens": _canonical_slug_tokens(str(p.get("title") or fn)),
            "terms": frozenset(terms or []),
        }
    return reg


def _registry_add(registry: dict, target: str, content: str) -> None:
    registry[target] = {
        "type": _page_type(content, target),
        "tokens": _canonical_slug_tokens(_page_title(content, target)),
        "terms": frozenset(_extract_key_terms(content)),
    }


def _resolve_target(content: str, llm_filename: str, ctx: dict) -> str:
    """Deterministic on-disk filename for an LLM-emitted page.

    Source-summaries always collapse to one stable `summary-<doc>.md` (kills the
    per-Teil explosion). Concept/entity pages route into an existing near-duplicate
    when one exists, else keep the model's filename.
    """
    ptype = _page_type(content, llm_filename)
    if ptype == "source-summary":
        return f"summary-{ctx['summary_slug']}.md"
    tokens = _canonical_slug_tokens(_page_title(content, llm_filename))
    terms = frozenset(_extract_key_terms(content))
    routed = _route_page(ptype, tokens, terms, ctx["registry"], llm_filename)
    return routed or llm_filename


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


def _build_candidate_index_block(filenames: list[str]) -> str:
    """Cheap candidate index: filename — title: key facts (NOT full bodies).

    Nudges the model to REUSE an existing filename; code-side routing/merge is
    the real safety net, so this stays tiny — only each page's `## Key facts`.
    """
    if not filenames:
        return ""
    parts = ["\nExisting pages you may extend "
             "(REUSE the exact filename if your topic matches one):\n"]
    for fname in filenames:
        path = _wiki() / fname
        if not path.exists():
            continue
        try:
            post = frontmatter.load(str(path))
            facts = "; ".join(_parse_index_block(post.content)[:5])
            title = post.metadata.get("title", fname)
        except Exception:
            facts, title = "", fname
        parts.append(f"- {fname} — {title}: {facts}\n")
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


def _okf_apply(content: str) -> str:
    """Stamp OKF fields + `## Citations` on a page (deterministic, no LLM)."""
    return okf.apply_to_page(content, db=db_context.get_active_db())


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
    # Pin the page-writer to the source's language via the system prompt (always
    # preserved by Ollama, unlike the prompt tail where the 40 KB piece is
    # truncated). Detection is deterministic; wording lives in prompts.py.
    system = schema_loader.get_system_prompt() + "\n\n" + lang.ingest_directive(full_text)
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
        # One stable source-summary slug for the WHOLE document (no per-Teil
        # explosion); plus the routing registry of every existing page.
        "summary_slug": _title_to_filename(Path(_TEIL_SUFFIX_RE.sub("", source_name)).stem).replace(".md", ""),
        "registry": _build_registry(),
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
    # Inject only the cheap candidate INDEX (key facts), not full bodies — the
    # actual merge is done deterministically in code below, so the small model
    # only needs a nudge to reuse an existing filename.
    existing_block = _build_candidate_index_block(ranked)
    prompt = INGEST_PROMPT.format(
        source_name=piece_source,
        meta_block=ctx["meta_block"],
        index_text=ctx["index_text"],
        existing_block=existing_block,
        text=piece_text,
        summary_slug=ctx["summary_slug"],
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
        content = _ensure_frontmatter(page["content"], page["filename"])
        # Merge current source into frontmatter `sources:` so the graph viz can
        # draw `derived-from` edges (source → page) without trusting the LLM
        # to have written it correctly.
        content = _ensure_source_in_frontmatter(content, ctx["source_name"])
        content = _scrub_related(content, ctx["existing_filenames"])
        content = _ensure_key_terms(content)
        content = _ensure_index_block(content)
        target = _resolve_target(content, page["filename"], ctx)
        dest = _wiki() / target
        if dest.exists():
            # Deterministic, no-LLM merge: never drops a prior fact, dedupes lines,
            # flags numeric contradictions (date-resolved when possible).
            content = _merge_pages(dest.read_text(), content, ctx["source_name"])
            if target not in ctx["updated"] and target not in ctx["created"]:
                ctx["updated"].append(target)
        elif target not in ctx["created"]:
            ctx["created"].append(target)
        content = _okf_apply(content)  # OKF frontmatter + citations (deterministic)
        dest.write_text(content)
        ctx["existing_filenames"].add(target)
        _registry_add(ctx["registry"], target, content)

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


# --- One-off consolidation (clean up legacy chunk-derived duplicates) --------

def _clean_teil_text(text: str) -> str:
    """Strip `[Teil n/m]` markers and collapse any repeated `.md.md…` runs."""
    text = re.sub(r"\s*\[Teil\s+\d+/\d+\]", "", text)
    return re.sub(r"(\.md){2,}", ".md", text)


def _strip_teil_sources(content: str) -> str:
    """De-Teil and dedupe the frontmatter `sources:` list."""
    try:
        post = frontmatter.loads(content)
    except Exception:
        return content
    cleaned: list[str] = []
    for s in (post.metadata.get("sources") or []):
        s2 = _TEIL_SUFFIX_RE.sub("", str(s)).strip()
        if s2 and s2 not in cleaned:
            cleaned.append(s2)
    post.metadata["sources"] = cleaned
    return frontmatter.dumps(post) + "\n"


def _summary_base(filename: str) -> str:
    base = filename[:-3] if filename.endswith(".md") else filename
    base = _FILE_TEIL_RE.sub("", base)
    if base.startswith("summary-"):
        base = base[len("summary-"):]
    # drop stray `source-summary-`/`concept-`/`entity-` infixes left by old ingests
    base = re.sub(r"^(source-summary-|concept-|entity-)+", "", base)
    if base.endswith("-md"):
        base = base[:-3]
    return re.sub(r"[^a-z0-9]+", "-", base.lower()).strip("-")  # normalize separators


def _needs_cleanup(filename: str) -> bool:
    p = _wiki() / filename
    if not p.exists():
        return False
    if _FILE_TEIL_RE.search(filename):
        return True
    txt = p.read_text()
    return "[Teil " in txt or ".md.md" in txt


def _group_concept_pages(pages: list[dict]) -> list[list[str]]:
    """Connected components of concept/entity pages under the same-topic relation."""
    items = []
    for p in pages:
        if str(p.get("type") or "").lower() not in ("concept", "entity"):
            continue
        fn = p["filename"]
        terms = p.get("key_terms") or _extract_key_terms(read_page(fn))
        items.append((fn, str(p.get("type")).lower(),
                      _canonical_slug_tokens(str(p.get("title") or fn)),
                      frozenset(terms or [])))
    parent = {it[0]: it[0] for it in items}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for i in range(len(items)):
        for j in range(i + 1, len(items)):
            a, b = items[i], items[j]
            if a[1] != b[1] or not a[2] or not b[2]:
                continue
            if a[2] == b[2] or ((a[2] <= b[2] or b[2] <= a[2])
                                and _overlap_coef(a[3], b[3]) >= _TERM_OVERLAP_THRESHOLD):
                parent[find(a[0])] = find(b[0])
    groups: dict[str, list[str]] = {}
    for fn in parent:
        groups.setdefault(find(fn), []).append(fn)
    return list(groups.values())


def _canonical_concept(members: list[str], title_by: dict[str, str]) -> str:
    """Most-general member: fewest topic tokens, then shortest filename."""
    return min(members, key=lambda m: (len(_canonical_slug_tokens(title_by.get(m, m))),
                                       len(m), m))


def _plan_groups(pages: list[dict]) -> list[dict]:
    """Build {canonical, members, base} merge plans for summaries + concepts."""
    plans: list[dict] = []
    summaries: dict[str, list[str]] = {}
    for p in pages:
        if str(p.get("type") or "").lower() == "source-summary" or p["filename"].startswith("summary-"):
            summaries.setdefault(_summary_base(p["filename"]), []).append(p["filename"])
    for base, members in summaries.items():
        canonical = f"summary-{base}.md"
        base_member = max(members, key=lambda m: (_wiki() / m).stat().st_size
                          if (_wiki() / m).exists() else 0)
        if len(members) == 1 and members[0] == canonical and not _needs_cleanup(canonical):
            continue
        plans.append({"canonical": canonical, "members": members, "base": base_member})
    title_by = {p["filename"]: str(p.get("title") or p["filename"]) for p in pages}
    for members in _group_concept_pages(pages):
        canonical = _canonical_concept(members, title_by)
        if len(members) == 1 and not _needs_cleanup(canonical):
            continue
        plans.append({"canonical": canonical, "members": members, "base": canonical})
    # Catch-all: any remaining page (incl. those with a missing/other `type`)
    # that still carries Teil markers gets a singleton cleanup pass.
    grouped = {m for pl in plans for m in pl["members"]}
    for p in pages:
        fn = p["filename"]
        if fn not in grouped and _needs_cleanup(fn):
            plans.append({"canonical": fn, "members": [fn], "base": fn})
    return plans


def _merge_group(contents: list[str]) -> str:
    base = contents[0]
    for c in contents[1:]:
        base = _merge_pages(base, c, "")
    return base


def _remap_related(rename: dict[str, str]) -> None:
    """Repoint every page's `related:` away from merged-out files; drop self/dupes."""
    for p in _wiki().glob("*.md"):
        if p.name in _SYSTEM_PAGES:
            continue
        try:
            post = frontmatter.load(str(p))
        except Exception:
            continue
        related = post.metadata.get("related") or []
        new: list[str] = []
        for r in related:
            r2 = rename.get(str(r).strip(), str(r).strip())
            if r2 and r2 != p.name and r2 not in new:
                new.append(r2)
        if new != related:
            post.metadata["related"] = new
            p.write_text(frontmatter.dumps(post) + "\n")


def _polish_page(content: str) -> str:
    """Optional LLM prose-smoothing of a merged page (facts must be preserved)."""
    try:
        post = frontmatter.loads(content)
    except Exception:
        return content
    try:
        resp = ollama_client.generate(schema_loader.get_system_prompt(),
                                       CONSOLIDATE_POLISH_PROMPT.format(page=post.content),
                                       temperature=0.2, model_id=ollama_client._INGEST_MODEL)
    except Exception:
        return content
    if resp and resp.strip():
        post.content = resp.strip()
    return frontmatter.dumps(post) + "\n"


def consolidate(db: str | None = None, dry_run: bool = True, llm_polish: bool = False) -> dict:
    """Collapse legacy chunk-derived duplicate pages into one page per topic.

    Groups source-summaries by document base (Teil-stripped) and concept/entity
    pages by the same-topic relation, merges each group deterministically
    (`_merge_pages` — no fact dropped), de-Teils filenames/sources/citations,
    repoints `related:`, deletes the merged-out files and rebuilds the indexes.
    `dry_run=True` only reports the plan. Optionally switches active DB first.
    """
    prev = db_context.get_active_db()
    if db and db != prev:
        db_context.set_active_db(db)
    try:
        return _consolidate_active(dry_run, llm_polish)
    finally:
        if db and db != prev:
            db_context.set_active_db(prev)


def _consolidate_active(dry_run: bool, llm_polish: bool) -> dict:
    pages = list_pages()
    plans = _plan_groups(pages)
    rename = {m: pl["canonical"] for pl in plans for m in pl["members"] if m != pl["canonical"]}
    grouped = {m for pl in plans for m in pl["members"]}
    after = len([p for p in pages if p["filename"] not in grouped]) + \
        len({pl["canonical"] for pl in plans})
    summary = {"before": len(pages), "after": after,
               "groups": [(pl["canonical"], pl["members"]) for pl in plans],
               "rename": rename}
    if dry_run:
        return summary
    for pl in plans:
        order = [pl["base"]] + sorted(m for m in pl["members"] if m != pl["base"])
        content = _merge_group([read_page(m) for m in order])
        content = _strip_teil_sources(_clean_teil_text(content))
        if llm_polish:
            content = _polish_page(content)
        content = _ensure_index_block(_ensure_key_terms(content))
        (_wiki() / pl["canonical"]).write_text(content)  # write canonical BEFORE deleting
    _remap_related(rename)
    for old, canon in rename.items():
        if old != canon:
            (_wiki() / old).unlink(missing_ok=True)
    lex_index.build()
    _rebuild_index()
    _append_log("Consolidate",
                f"Merged {len(rename)} pages into {len(plans)} canonical pages.")
    return summary


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

    answer_prompt = ANSWER_PROMPT.format(
        pages_text=pages_text, question=question,
        language_directive=lang.response_directive(question),
    )
    answer = ollama_client.generate(system, answer_prompt, temperature=0.7)
    return {"answer": answer, "sources": used_sources, "raw_sources": sorted(raw_sources_set)}


def lint() -> str:
    """Run wiki health check. Returns the lint report."""
    system = schema_loader.get_system_prompt(mode="query")
    all_pages = ""
    files = sorted(_wiki().glob("*.md")) + sorted((_wiki() / _INSIGHTS_DIR).glob("*.md"))
    for md in files:
        if md.name in _SYSTEM_PAGES:
            continue
        label = f"{_INSIGHTS_DIR}/{md.name}" if md.parent.name == _INSIGHTS_DIR else md.name
        all_pages += f"\n\n--- {label} ---\n{md.read_text()}"

    if not all_pages:
        return "Wiki is empty — nothing to lint."

    report = ollama_client.generate(
        system, LINT_PROMPT.format(all_pages=all_pages, today=_date()),
        temperature=0.3, model_id=ollama_client._FAST_MODEL)

    prog_blocks = []
    orphans = find_orphans()
    if orphans:
        prog_blocks.append("**Orphans (no in-links from `related` frontmatter):**\n"
                           + "\n".join(f"- {o}" for o in orphans))
    stale = stale_pages()
    if stale:
        prog_blocks.append(f"**Possibly stale (past freshness window as of {_date()}):**\n"
                           + "\n".join(f"- {s}" for s in stale))
    if prog_blocks:
        report = "## Programmatic checks\n\n" + "\n\n".join(prog_blocks) + "\n\n---\n\n" + report

    _append_log("Lint", report[:500])
    return report


def list_pages(include_insights: bool = False) -> list[dict]:
    """Return metadata for all non-system wiki pages.

    With `include_insights=True`, also lists `insights/*.md` (E-2) — their
    `filename` carries the `insights/` prefix (so `read_page` resolves them) and
    their `type` is forced to `insight`.
    """
    files = sorted(_wiki().glob("*.md"))
    if include_insights:
        files += sorted((_wiki() / _INSIGHTS_DIR).glob("*.md"))
    results = []
    for md in files:
        if md.name in _SYSTEM_PAGES:
            continue
        is_insight = md.parent.name == _INSIGHTS_DIR
        fname = f"{_INSIGHTS_DIR}/{md.name}" if is_insight else md.name
        try:
            post = frontmatter.load(str(md))
            meta = dict(post.metadata)
            meta["filename"] = fname
            if is_insight:
                meta["type"] = "insight"
            meta.setdefault("description", post.content[:120].replace("\n", " "))
            results.append(meta)
        except Exception:
            results.append({"filename": fname, "title": md.stem, "description": "",
                            **({"type": "insight"} if is_insight else {})})
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


_TYPE_GROUPS = ("concept", "entity", "source-summary", "comparison", "insight")


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

    Returns dict keyed by type (concept/entity/source-summary/comparison/insight/
    other), only including non-empty groups. Order within a group matches
    list_pages(). Each page dict is annotated with `stale` (E-1).
    """
    today = datetime.now(timezone.utc).date()
    tree: dict[str, list[dict]] = {}
    for page in list_pages(include_insights=True):
        t = str(page.get("type", "")).strip().lower()
        key = t if t in _TYPE_GROUPS else "other"
        page["stale"] = is_page_stale(page, today)
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
    dest.write_text(_okf_apply(page))
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


def linked_pages(filenames: list[str], limit: int = 5) -> list[dict]:
    """1-hop link expansion: neighbours of `filenames` via frontmatter `related:`.

    Used by link-aware retrieval — after a wiki search, pull the related pages of
    the top hits into context so a query reaches material it didn't lexically
    match. Returns up to `limit` page dicts `{filename, title, excerpt, via}` that
    are NOT already in `filenames`. Neighbours linked by more seeds rank first
    (insertion order breaks ties); `via` is the first seed that links each one.
    Only existing wiki pages are returned (insights included, `insights/`-prefixed).
    """
    seeds = [f for f in filenames if f]
    if not seeds or limit <= 0:
        return []
    seed_set = set(seeds)
    titles = {p["filename"]: str(p.get("title", p["filename"]))
              for p in list_pages(include_insights=True)}
    order: list[str] = []
    counts: dict[str, int] = {}
    via: dict[str, str] = {}
    for seed in seeds:
        for r in read_page_parsed(seed).get("related", []) or []:
            r = str(r).strip()
            if not r or r in seed_set or r not in titles:
                continue
            if r not in counts:
                counts[r] = 0
                via[r] = seed
                order.append(r)
            counts[r] += 1
    order.sort(key=lambda r: -counts[r])  # stable: equal counts keep insertion order
    out: list[dict] = []
    for r in order[:limit]:
        body = read_page_parsed(r).get("content", "")
        excerpt = " ".join(body.split())[:240]
        out.append({"filename": r, "title": titles[r], "excerpt": excerpt, "via": via[r]})
    return out


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
        dest.write_text(_okf_apply(_ensure_frontmatter(page["content"], page["filename"])))
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
