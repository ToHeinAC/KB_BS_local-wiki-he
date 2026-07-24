"""Lexical BM25 index over chunks for fast, recall-friendly retrieval.

Tokens are stored in up to four normalized variants per surface word:
  - surface lower-cased (preserves diacritics): "rückstände"
  - NFKD-folded ASCII:                          "ruckstande"
  - German digraph fold (ü→ue, ß→ss):           "rueckstaende"
  - light Snowball-style stem on the NFKD form: "ruckstand"

Query tokens are expanded to the same variants; a chunk that indexed any
variant becomes a candidate. BM25 scoring then ranks by relevance.

No external NLP deps: a small built-in German+English suffix stripper plays the
role of a stemmer. Good enough for the project's domains (legal German, English
investment docs) and keeps the dep footprint tiny.

The store is a single SQLite FTS5 table (`data/<DB>/index/chunks.sqlite`). It
holds the pre-expanded `variants()` token stream in an indexed `terms` column and
supplies `bm25()` scoring, so the whole index is one file with no per-query JSON
parse. The index is a pure derived artifact — `build()` regenerates it from
`chunks/` + `wiki/` + `qa.jsonl` — and supports per-source incremental updates
(`index_replace_source` / `index_replace_wiki_page` / `index_delete`) so ingest
and delete don't rebuild the whole corpus.
"""

from __future__ import annotations

import json
import re
import sqlite3
import unicodedata
from pathlib import Path

import frontmatter

import chunker
import db_context
import qa_gen


def _index_dir() -> Path:
    return db_context.index_dir()


def _fts5_path() -> Path:
    return _index_dir() / "chunks.sqlite"


MIN_TOKEN_LEN = 2

_STOPWORDS = {
    # German function words
    "der", "die", "das", "den", "dem", "des", "ein", "eine", "einen", "einem", "einer", "eines",
    "und", "oder", "aber", "doch", "ist", "war", "sind", "waren", "sein", "wird", "werden", "wurde",
    "von", "vom", "zu", "zum", "zur", "in", "im", "an", "am", "auf", "für", "mit", "ohne",
    "nicht", "kein", "keine", "auch", "nur", "noch", "schon", "wenn", "dass", "als", "wie",
    "bei", "nach", "vor", "über", "unter", "aus", "durch", "gegen", "um",
    # English function words
    "the", "a", "an", "and", "or", "but", "is", "are", "was", "were", "be", "been", "being",
    "to", "of", "in", "on", "at", "by", "for", "with", "from", "as", "that", "this", "these",
    "those", "it", "its", "not", "no", "if", "then", "than", "so", "do", "does", "did",
}

_TOKEN_RE = re.compile(r"\w+", re.UNICODE)

_UMLAUT_MAP = str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss",
                             "Ä": "ae", "Ö": "oe", "Ü": "ue"})

_GERMAN_SUFFIXES = ("erungen", "ierung", "ungen", "ierens", "ieren", "iert",
                    "lich", "isch", "ung", "keit", "heit", "schaft", "ern",
                    "end", "ten", "ein", "ene", "enem", "enen", "ener", "enes",
                    "em", "en", "er", "es", "et", "te", "st", "n", "e", "s")
_ENGLISH_SUFFIXES = ("ization", "isation", "ational", "tional", "ization",
                     "ingly", "ation", "ments", "ement", "ness", "ously", "ously",
                     "ize", "ise", "ing", "ies", "ied", "est", "ers", "ed",
                     "ly", "es", "er", "s")


def _nfkd_fold(token: str) -> str:
    """Strip combining marks (ü→u, é→e). Stable canonical form for stemming."""
    t = unicodedata.normalize("NFKD", token)
    return "".join(c for c in t if not unicodedata.combining(c))


def _umlaut_fold(token: str) -> str:
    """German digraph fold (ü→ue, ß→ss). Catches users who type ASCII digraphs."""
    return token.translate(_UMLAUT_MAP)


def _stem(folded: str) -> str:
    """Trim the longest known suffix (greedy, single-pass).

    Operates on the folded form so umlauts don't trip suffix matching. Always
    leaves at least 4 chars.
    """
    if len(folded) <= 4:
        return folded
    for suf in _GERMAN_SUFFIXES + _ENGLISH_SUFFIXES:
        if folded.endswith(suf) and len(folded) - len(suf) >= 4:
            return folded[: -len(suf)]
    return folded


def variants(token: str) -> list[str]:
    """Up to 4 normalized variants per surface word.

    The two fold paths (NFKD-strip vs. umlaut-digraph) catch both writing styles
    ("rückstände" vs. "rueckstaende"). The stem is always taken from the NFKD
    form so the same suffix rules apply regardless of input writing style.
    """
    t = token.lower()
    if len(t) < MIN_TOKEN_LEN or t in _STOPWORDS:
        return []
    nfkd = _nfkd_fold(t)
    umlaut = _umlaut_fold(t)
    stem = _stem(nfkd)
    seen: list[str] = []
    for v in (t, nfkd, umlaut, stem):
        if v and v not in seen:
            seen.append(v)
    return seen


def tokenize(text: str) -> list[str]:
    """Surface lowercase tokens from text (no normalization, no dedup)."""
    return [m.group(0).lower() for m in _TOKEN_RE.finditer(text)]


_WIKI_SYSTEM_PAGES = {"index.md", "log.md", "DESCRIPTION.md"}


def _wiki_page_chunks(md: Path) -> list[dict]:
    """Pseudo-chunks over one wiki page's body, tagged scope='wiki' (R-1).

    The page title + filename stem are prepended so a term that lives only in the
    title still matches; each chunk's `source` is the page filename and its `text`
    is carried inline (wiki pseudo-chunks aren't persisted to data/chunks/).
    System pages (index/log/DESCRIPTION) index to nothing.
    """
    if md.name in _WIKI_SYSTEM_PAGES:
        return []
    try:
        post = frontmatter.load(str(md))
        title = str(post.metadata.get("title", md.stem))
        body = post.content
    except Exception:
        title, body = md.stem, md.read_text()
    indexable = f"{title} {md.stem}\n\n{body}".strip()
    if not indexable:
        return []
    out: list[dict] = []
    for ch in chunker.split(indexable):
        c = dict(ch)
        c["chunk_id"] = f"wiki:{md.name}:{ch['chunk_id']}"
        c["source"] = md.name
        c["scope"] = "wiki"
        out.append(c)
    return out


def _wiki_chunks() -> list[dict]:
    """Pseudo-chunks over all wiki page bodies (main + insights). See R-1.

    Lets BM25 search synthesized/merged wiki content — which may use different
    vocabulary than the original sources — instead of an O(n·m) string scan.
    """
    wiki = db_context.wiki_dir()
    if not wiki.exists():
        return []
    out: list[dict] = []
    for md in sorted(wiki.glob("*.md")) + sorted(wiki.glob("insights/*.md")):
        out.extend(_wiki_page_chunks(md))
    return out


# --- FTS5 store --------------------------------------------------------------

_FTS_CREATE = (
    "CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5("
    "terms, chunk_id UNINDEXED, source UNINDEXED, scope UNINDEXED, "
    "anchor UNINDEXED, heading_path UNINDEXED, char_start UNINDEXED, "
    "char_end UNINDEXED, lang UNINDEXED, text UNINDEXED, "
    "tokenize='unicode61 remove_diacritics 0')"
)
_FTS_INSERT = (
    "INSERT INTO chunks_fts (terms, chunk_id, source, scope, anchor, "
    "heading_path, char_start, char_end, lang, text) VALUES (?,?,?,?,?,?,?,?,?,?)"
)


def _row_for_chunk(ch: dict, qa_by_chunk: dict) -> tuple:
    """Build the FTS5 row for one chunk: the pre-expanded variant token stream
    plus the metadata columns the hit dict is rebuilt from.

    Hypothetical-question tokens (qa_gen) are folded into the same `terms` stream
    so a chunk is retrievable by the questions it answers.
    """
    cid = ch["chunk_id"]
    body_tokens = [t for t in tokenize(ch.get("text", ""))
                   if t not in _STOPWORDS and len(t) >= MIN_TOKEN_LEN]
    qa_tokens = [t for t in tokenize(" ".join(qa_by_chunk.get(cid, [])))
                 if t not in _STOPWORDS and len(t) >= MIN_TOKEN_LEN]
    terms: list[str] = []
    for tok in body_tokens + qa_tokens:
        terms.extend(variants(tok))
    scope = ch.get("scope", "raw")
    # Wiki pseudo-chunks aren't in data/chunks/; keep their text inline so the
    # hit dict can supply it without a JSONL lookup.
    inline = ch.get("text", "") if scope != "raw" else ""
    return (
        " ".join(terms), cid, ch.get("source", ""), scope, ch.get("anchor", ""),
        json.dumps(ch.get("heading_path", []), ensure_ascii=False),
        ch.get("char_start", 0), ch.get("char_end", 0), ch.get("lang", ""), inline,
    )


def _dedup(chunks: list[dict]):
    """Yield chunks skipping repeated chunk_ids (same content across sources)."""
    seen: set[str] = set()
    for ch in chunks:
        cid = ch["chunk_id"]
        if cid in seen:
            continue
        seen.add(cid)
        yield ch


def build(chunks: list[dict] | None = None) -> dict:
    """Full (re)build of the FTS5 index over all chunks. Returns a small summary.

    When no chunks are passed, indexes raw source chunks (scope='raw') plus wiki
    page pseudo-chunks (scope='wiki') so both layers are searchable from one store.
    Rebuilds from scratch; for single-source updates prefer the incremental
    `index_replace_source` / `index_delete` helpers.
    """
    if chunks is None:
        chunks = chunker.all_chunks() + _wiki_chunks()
    qa_by_chunk = qa_gen.load()
    rows = [_row_for_chunk(ch, qa_by_chunk) for ch in _dedup(chunks)]

    _index_dir().mkdir(parents=True, exist_ok=True)
    path = _fts5_path()
    if path.exists():
        path.unlink()
    con = sqlite3.connect(str(path))
    try:
        con.execute(_FTS_CREATE)
        con.executemany(_FTS_INSERT, rows)
        con.commit()
    finally:
        con.close()
    return {"chunks": len(rows)}


# --- Incremental updates (per source, keyed on the `source` column) ----------

def index_replace_source(source: str, chunks: list[dict], qa: dict | None = None) -> None:
    """Replace all rows for `source` with rows for `chunks` (delete + insert).

    O(change), not O(corpus): only this source's rows are touched. Creates the
    table/file if the index doesn't exist yet. `qa` may be passed to avoid a
    reload; pass `{}` for wiki pages (their chunk_ids never carry QA questions).
    """
    if qa is None:
        qa = qa_gen.load()
    rows = [_row_for_chunk(ch, qa) for ch in _dedup(chunks)]
    _index_dir().mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(_fts5_path()))
    try:
        con.execute(_FTS_CREATE)
        con.execute("DELETE FROM chunks_fts WHERE source = ?", (source,))
        con.executemany(_FTS_INSERT, rows)
        con.commit()
    finally:
        con.close()


def index_replace_wiki_page(name: str) -> None:
    """Re-index a single wiki page's body (the `source` is its filename).

    Used by incremental ingest so a page rewrite doesn't rebuild the whole index.
    If the page no longer exists (renamed/removed) its rows are simply dropped.
    """
    md = db_context.wiki_dir() / name
    if not md.exists():
        index_delete(name)
        return
    index_replace_source(name, _wiki_page_chunks(md), qa={})


def index_delete(source: str) -> None:
    """Drop every row for `source`. No-op if the index doesn't exist yet."""
    path = _fts5_path()
    if not path.exists():
        return
    con = sqlite3.connect(str(path))
    try:
        con.execute(_FTS_CREATE)
        con.execute("DELETE FROM chunks_fts WHERE source = ?", (source,))
        con.commit()
    finally:
        con.close()


# --- Query -------------------------------------------------------------------

def index_health() -> dict:
    """Row counts per scope for the active DB's FTS5 store: `{raw, wiki}`.

    Both zero means the index is missing or empty — `query()` silently returns []
    in that state, so callers use this to tell "no match" apart from "no index"
    (databases last built before the FTS5 cutover have no `chunks.sqlite`).
    """
    path = _fts5_path()
    if not path.exists():
        return {"raw": 0, "wiki": 0}
    con = sqlite3.connect(str(path))
    try:
        rows = con.execute("SELECT scope, count(*) FROM chunks_fts GROUP BY scope").fetchall()
    except sqlite3.Error:
        return {"raw": 0, "wiki": 0}
    finally:
        con.close()
    counts = dict(rows)
    return {"raw": int(counts.get("raw", 0)), "wiki": int(counts.get("wiki", 0))}


def query(q: str, top_k: int = 10, scope: str | None = None) -> list[dict]:
    """BM25 over the FTS5 chunk index. Returns up to top_k hits (empty if no index).

    `scope` filters by chunk scope: "raw" (source chunks), "wiki" (wiki page
    bodies), or None (both).

    Each hit: {chunk_id, score, source, scope, anchor, heading_path, char_start,
               char_end, text, preview, lang, matched_terms}.
    """
    if not _fts5_path().exists():
        return []
    return _query_fts5(q, top_k, scope)


def _query_fts5(q: str, top_k: int = 10, scope: str | None = None) -> list[dict]:
    """BM25 over the FTS5 index.

    Query tokens are expanded to the same `variants()` forms the index stored, so
    German morphology matching is deterministic and identical at index and query
    time. FTS5's `bm25()` returns lower=better, so it is negated into the usual
    higher=better score. Results are deduplicated by chunk_id (a chunk shared by
    two sources can appear twice after incremental updates); the higher-scored row
    wins since rows arrive best-first.
    """
    expanded: list[str] = []
    for tok in tokenize(q):
        for v in variants(tok):
            if v not in expanded:
                expanded.append(v)
    if not expanded:
        return []

    match = " OR ".join(f'"{v}"' for v in expanded)
    sql = ("SELECT chunk_id, source, scope, anchor, heading_path, char_start, "
           "char_end, lang, text, terms, bm25(chunks_fts) AS score "
           "FROM chunks_fts WHERE chunks_fts MATCH ?")
    params: list = [match]
    if scope is not None:
        sql += " AND scope = ?"
        params.append(scope)
    sql += " ORDER BY score LIMIT ?"
    params.append(top_k * 2 + 8)  # over-fetch; dedup by chunk_id then trim to top_k

    con = sqlite3.connect(str(_fts5_path()))
    try:
        rows = con.execute(sql, params).fetchall()
    except sqlite3.Error:
        return []
    finally:
        con.close()

    exp_set = set(expanded)
    text_cache: dict[str, dict[str, str]] = {}

    def _text_for(cid: str, source: str, inline: str) -> str:
        if inline:
            return inline
        if source not in text_cache:
            text_cache[source] = {c["chunk_id"]: c["text"]
                                  for c in chunker.load_chunks(source)}
        return text_cache[source].get(cid, "")

    out: list[dict] = []
    seen: set[str] = set()
    for (cid, source, sc, anchor, hp_json, cs, ce, lang, inline, terms, score) in rows:
        if cid in seen:
            continue
        seen.add(cid)
        text = _text_for(cid, source, inline)
        preview = text.replace("\n", " ").strip()
        if len(preview) > 320:
            preview = preview[:320] + "…"
        out.append({
            "chunk_id": cid,
            "score": round(-score, 3),
            "source": source,
            "scope": sc,
            "anchor": anchor,
            "heading_path": json.loads(hp_json) if hp_json else [],
            "char_start": cs,
            "char_end": ce,
            "lang": lang,
            "text": text,
            "preview": preview,
            "matched_terms": sorted(exp_set.intersection(terms.split())),
        })
        if len(out) >= top_k:
            break
    return out
