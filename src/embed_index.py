"""Semantic (embedding) arm of retrieval — Stage C.

Local, file-backed dense-vector index over the SAME chunks the lexical arm indexes.
Vectors are computed via the already-required local Ollama `/api/embed` — no cloud
API, no external vector database or service. Storage matches the lexical index's
derived-artifact model, per DB:

    data/<DB>/index/vectors.npy    # float16 matrix, L2-normalized rows
    data/<DB>/index/vectors.json   # model name + aligned per-row chunk metadata

Search is brute-force cosine (rows are normalized, so cosine == dot product). At
10^4..10^5 chunks per DB this is single-digit milliseconds; an ANN index would be
unearned complexity.

The arm is OPTIONAL and GRACEFUL: `build()` regenerates everything from chunks/ +
wiki/, so the vectors are a pure cache. When a DB has no vectors, or they were
built with a different model, or the embed model is unreachable, callers fall back
to the lexical arm with zero behaviour change (see `src/retrieval.py`).

Per idea.md §3.3, wiki pseudo-chunks are embedded with a deterministic OKF identity
prefix (type/title/about/tags) so a page's own topic words boost chunks whose body
omits them. The prefix affects the *embedded* text only — never `chunk.text`, the
char anchors, or anything returned to the UI, so citations stay exact.
"""

from __future__ import annotations

import functools
import json
import os
from pathlib import Path

import frontmatter
import numpy as np

import chunker
import db_context
import lex_index
import ollama_client
import okf

_EMBED_BATCH = 64
# Cap each embed input so a pathologically long chunk/page can't exceed the embed
# model's context window (bge-m3 = 8192 tokens) and fail the whole build. ~8000
# chars is comfortably under that for DE/EN text. Truncation affects the EMBEDDED
# text only — the chunk text returned to the UI and citations is never touched.
_MAX_EMBED_CHARS = 8000


def _model() -> str:
    return os.getenv("EMBED_MODEL", "bge-m3").strip()


def _vectors_path() -> Path:
    return db_context.index_dir() / "vectors.npy"


def _meta_path() -> Path:
    return db_context.index_dir() / "vectors.json"


# --- embedding ---------------------------------------------------------------

def _embed_raw(texts: list[str]) -> np.ndarray:
    """One Ollama embed call + L2-normalize each row (float32). Raises on failure."""
    vecs = ollama_client.embed(list(texts), _model())
    arr = np.asarray(vecs, dtype=np.float32)
    norms = np.linalg.norm(arr, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return arr / norms


def _too_long(exc: Exception) -> bool:
    m = str(exc).lower()
    return "context length" in m or "exceeds" in m or "too large" in m


def _embed_resilient(texts: list[str]) -> np.ndarray:
    """Embed a batch, isolating any input that overflows the model's context.

    Char-capping alone can't guarantee the token count (dense text tokenizes to far
    more tokens per char), so on a context-length 400 we split the batch to isolate
    the offending input, then progressively hard-truncate just that input until it
    fits. Other errors (e.g. Ollama down) propagate. Truncation affects the embedded
    text only — never the stored chunk text or citations."""
    try:
        return _embed_raw(texts)
    except Exception as exc:
        if not _too_long(exc):
            raise
        if len(texts) == 1:
            for cap in (4000, 2000, 1000, 500):
                try:
                    return _embed_raw([texts[0][:cap]])
                except Exception as inner:
                    if not _too_long(inner):
                        raise
            raise
        mid = len(texts) // 2
        return np.vstack([_embed_resilient(texts[:mid]), _embed_resilient(texts[mid:])])


def embed_texts(texts: list[str]) -> np.ndarray:
    """Embed texts via Ollama and L2-normalize each row (float32).

    Each input is first truncated to `_MAX_EMBED_CHARS`; oversized-for-context inputs
    are then handled resiliently (see `_embed_resilient`) so one pathological chunk
    can't fail a whole DB's build."""
    return _embed_resilient([t[:_MAX_EMBED_CHARS] for t in texts])


@functools.lru_cache(maxsize=128)
def _embed_query(q: str, model: str) -> np.ndarray:
    """Cached single-query embedding (float16). A chat turn hits several retrieval
    paths with the same question; keyed on `model` so it invalidates on model change.
    The returned array is shared — callers must treat it read-only."""
    return embed_texts([q])[0].astype(np.float16)


def _okf_prefix_map() -> dict[str, str]:
    """filename -> deterministic OKF identity prefix, for wiki pages only."""
    wiki = db_context.wiki_dir()
    out: dict[str, str] = {}
    if not wiki.exists():
        return out
    db = db_context.get_active_db()
    for md in wiki.glob("*.md"):
        if md.name in lex_index._WIKI_SYSTEM_PAGES:
            continue
        try:
            post = frontmatter.load(str(md))
            m = okf.enrich_frontmatter(post.metadata, post.content, db=db)
        except Exception:
            continue
        out[md.name] = (
            f"type: {m.get('type', '')} | title: {m.get('title', md.stem)} | "
            f"about: {m.get('description', '')} | tags: {', '.join(m.get('tags', []))}"
        )
    return out


def _embed_text(ch: dict, prefix_map: dict[str, str]) -> str:
    """Text actually embedded for a chunk (may differ from `chunk.text`)."""
    text = ch.get("text", "")
    if ch.get("scope") == "wiki":
        prefix = prefix_map.get(ch.get("source", ""))
        if prefix:
            return f"{prefix}\n\n{text}"
    return text


def _row_meta(ch: dict) -> dict:
    """Per-row metadata persisted alongside the vector (rebuilds the hit dict)."""
    scope = ch.get("scope", "raw")
    meta = {
        "chunk_id": ch["chunk_id"],
        "source": ch.get("source", ""),
        "scope": scope,
        "anchor": ch.get("anchor", ""),
        "heading_path": ch.get("heading_path", []),
        "char_start": ch.get("char_start", 0),
        "char_end": ch.get("char_end", 0),
        "lang": ch.get("lang", ""),
    }
    if scope != "raw":
        meta["text"] = ch.get("text", "")  # wiki chunks aren't in data/chunks/
    return meta


def _embed_chunks(chunks: list[dict], *, progress=None) -> tuple[np.ndarray, list[dict]]:
    """Embed chunks (dedup by chunk_id) → (float16 matrix, aligned row metadata).

    Wiki chunks get the deterministic OKF identity prefix; the wiki-frontmatter scan
    is skipped entirely when there are no wiki chunks (raw-only ingest)."""
    seen: set[str] = set()
    uniq = [ch for ch in chunks if not (ch["chunk_id"] in seen or seen.add(ch["chunk_id"]))]
    if not uniq:
        return np.zeros((0, 0), dtype=np.float16), []
    prefix_map = _okf_prefix_map() if any(c.get("scope") == "wiki" for c in uniq) else {}
    rows = [_row_meta(ch) for ch in uniq]
    inputs = [_embed_text(ch, prefix_map) for ch in uniq]
    mats: list[np.ndarray] = []
    for i in range(0, len(inputs), _EMBED_BATCH):
        mats.append(embed_texts(inputs[i:i + _EMBED_BATCH]))
        if progress:
            progress(min(i + _EMBED_BATCH, len(inputs)), len(inputs))
    return np.vstack(mats).astype(np.float16), rows


def build(chunks: list[dict] | None = None, *, progress=None) -> dict:
    """Full (re)build of the semantic index over all chunks. Returns a summary.

    Embeds raw source chunks (scope='raw') + wiki page pseudo-chunks (scope='wiki').
    Stamps the current model. `progress` is an optional callable(done, total).
    """
    if chunks is None:
        chunks = chunker.all_chunks() + lex_index._wiki_chunks()
    matrix, rows = _embed_chunks(chunks, progress=progress)
    _write(matrix, rows)
    return {"chunks": len(rows), "model": _model(),
            "dim": int(matrix.shape[1]) if matrix.size else 0}


def _write(matrix: np.ndarray, rows: list[dict], *, model: str | None = None) -> None:
    """Persist matrix + aligned rows. `model` defaults to the current model (full
    build); incremental ops pass the existing index's model to avoid restamping."""
    db_context.index_dir().mkdir(parents=True, exist_ok=True)
    np.save(_vectors_path(), matrix)
    _meta_path().write_text(json.dumps(
        {"model": model or _model(),
         "dim": int(matrix.shape[1]) if matrix.size else 0, "rows": rows},
        ensure_ascii=False,
    ))


# --- Incremental updates (per source; mirror lex_index) ----------------------

def index_delete(source: str) -> None:
    """Drop every row for `source` from the vector index. No-op if no index."""
    if not _vectors_path().exists() or not _meta_path().exists():
        return
    try:
        meta = json.loads(_meta_path().read_text())
    except Exception:
        return
    rows = meta.get("rows", [])
    keep = [i for i, r in enumerate(rows) if r.get("source") != source]
    if len(keep) == len(rows):
        return  # nothing for this source
    matrix = np.load(_vectors_path())
    dim = matrix.shape[1] if matrix.ndim == 2 and matrix.size else 0
    new_matrix = matrix[keep] if keep else np.zeros((0, dim), dtype=np.float16)
    _write(new_matrix, [rows[i] for i in keep], model=meta.get("model"))


def index_replace_source(source: str, chunks: list[dict]) -> None:
    """Re-embed one source's chunks and replace its rows. O(change) embed calls.

    Only touches an EXISTING, model-matching index (`available()`); DBs with no
    vectors stay lexical-only until a deliberate full backfill, so the semantic
    index never ends up with partial corpus coverage."""
    if not available():
        return
    meta = json.loads(_meta_path().read_text())
    model = meta["model"]
    matrix = np.load(_vectors_path())
    dim = matrix.shape[1] if matrix.ndim == 2 and matrix.size else 0
    keep = [i for i, r in enumerate(meta["rows"]) if r.get("source") != source]
    kept_rows = [meta["rows"][i] for i in keep]
    kept_mat = matrix[keep] if keep else np.zeros((0, dim), dtype=np.float16)

    new_mat, new_rows = _embed_chunks(chunks)
    if not new_rows:
        _write(kept_mat, kept_rows, model=model)
        return
    combined_mat = np.vstack([kept_mat, new_mat]) if kept_mat.size else new_mat
    _write(combined_mat, kept_rows + new_rows, model=model)


def index_replace_wiki_page(name: str) -> None:
    """Re-embed a single wiki page's body (its `source` is the filename). No-op
    without an existing model-matching index; drops rows if the page is gone."""
    if not available():
        return
    md = db_context.wiki_dir() / name
    if not md.exists():
        index_delete(name)
        return
    index_replace_source(name, lex_index._wiki_page_chunks(md))


# --- query -------------------------------------------------------------------

def available() -> bool:
    """True when this DB has vectors built with the currently-configured model."""
    if not _vectors_path().exists() or not _meta_path().exists():
        return False
    try:
        meta = json.loads(_meta_path().read_text())
    except Exception:
        return False
    return bool(meta.get("rows")) and meta.get("model") == _model()


def query(q: str, top_k: int = 10, scope: str | None = None) -> list[dict]:
    """Cosine search over the vector matrix. Same hit-dict shape as lex_index.query.

    Returns [] (never raises) when the arm is unavailable or the query can't be
    embedded, so it composes into graceful fallback.
    """
    if not q.strip() or not available():
        return []
    try:
        meta = json.loads(_meta_path().read_text())
        matrix = np.load(_vectors_path())
        qv = _embed_query(q, _model())
    except Exception:
        return []
    if matrix.size == 0:
        return []

    sims = matrix.astype(np.float32) @ qv.astype(np.float32)
    rows = meta["rows"]
    order = np.argsort(-sims)

    text_cache: dict[str, dict[str, str]] = {}

    def _text_for(row: dict) -> str:
        if "text" in row:
            return row["text"]
        source = row.get("source", "")
        if source not in text_cache:
            text_cache[source] = {c["chunk_id"]: c["text"]
                                  for c in chunker.load_chunks(source)}
        return text_cache[source].get(row["chunk_id"], "")

    out: list[dict] = []
    for i in order:
        row = rows[int(i)]
        if scope is not None and row.get("scope", "raw") != scope:
            continue
        text = _text_for(row)
        preview = text.replace("\n", " ").strip()
        if len(preview) > 320:
            preview = preview[:320] + "…"
        out.append({
            "chunk_id": row["chunk_id"],
            "score": round(float(sims[int(i)]), 4),
            "source": row.get("source", ""),
            "scope": row.get("scope", "raw"),
            "anchor": row.get("anchor", ""),
            "heading_path": row.get("heading_path", []),
            "char_start": row.get("char_start", 0),
            "char_end": row.get("char_end", 0),
            "lang": row.get("lang", ""),
            "text": text,
            "preview": preview,
            "matched_terms": [],  # dense arm has no lexical term overlap
        })
        if len(out) >= top_k:
            break
    return out
