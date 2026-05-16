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
"""

from __future__ import annotations

import json
import math
import os
import re
import unicodedata
from pathlib import Path

from dotenv import load_dotenv

import chunker
import qa_gen

load_dotenv()

INDEX_DIR = Path(os.getenv("INDEX_DIR", "data/index"))
POSTINGS_PATH = INDEX_DIR / "postings.json"
STATS_PATH = INDEX_DIR / "stats.json"

BM25_K1 = 1.5
BM25_B = 0.75
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


def build(chunks: list[dict] | None = None) -> dict:
    """Build (or rebuild) the index over all chunks. Returns a small summary."""
    if chunks is None:
        chunks = chunker.all_chunks()
    postings: dict[str, dict[str, int]] = {}
    chunk_meta: dict[str, dict] = {}
    chunk_dl: dict[str, int] = {}
    df: dict[str, int] = {}
    qa_by_chunk = qa_gen.load()  # {chunk_id: [question, ...]}

    for ch in chunks:
        cid = ch["chunk_id"]
        if cid in chunk_meta:
            continue  # duplicate chunk (same content across sources)
        body_tokens = [t for t in tokenize(ch["text"])
                       if t not in _STOPWORDS and len(t) >= MIN_TOKEN_LEN]
        # Hypothetical-question tokens contribute to TF but NOT to doc length —
        # otherwise BM25's b-normalization would penalize chunks for carrying
        # their own retrieval hints.
        qa_tokens = [t for t in tokenize(" ".join(qa_by_chunk.get(cid, [])))
                     if t not in _STOPWORDS and len(t) >= MIN_TOKEN_LEN]
        surface_tokens = body_tokens + qa_tokens
        dl = len(body_tokens)
        chunk_dl[cid] = dl
        chunk_meta[cid] = {
            "source": ch.get("source", ""),
            "anchor": ch.get("anchor", ""),
            "heading_path": ch.get("heading_path", []),
            "char_start": ch.get("char_start", 0),
            "char_end": ch.get("char_end", 0),
            "lang": ch.get("lang", ""),
        }
        seen_in_doc: set[str] = set()
        for tok in surface_tokens:
            for v in variants(tok):
                postings.setdefault(v, {})
                postings[v][cid] = postings[v].get(cid, 0) + 1
                if v not in seen_in_doc:
                    df[v] = df.get(v, 0) + 1
                    seen_in_doc.add(v)

    n = len(chunk_meta)
    avg_dl = (sum(chunk_dl.values()) / n) if n else 0.0
    stats = {
        "n": n,
        "avg_dl": avg_dl,
        "df": df,
        "chunk_dl": chunk_dl,
        "chunk_meta": chunk_meta,
    }

    INDEX_DIR.mkdir(parents=True, exist_ok=True)
    POSTINGS_PATH.write_text(json.dumps(postings, ensure_ascii=False))
    STATS_PATH.write_text(json.dumps(stats, ensure_ascii=False))
    return {"chunks": n, "tokens": len(postings), "avg_dl": avg_dl}


def _load() -> tuple[dict, dict]:
    if not POSTINGS_PATH.exists() or not STATS_PATH.exists():
        return {}, {"n": 0, "avg_dl": 0.0, "df": {}, "chunk_dl": {}, "chunk_meta": {}}
    postings = json.loads(POSTINGS_PATH.read_text())
    stats = json.loads(STATS_PATH.read_text())
    return postings, stats


def query(q: str, top_k: int = 10) -> list[dict]:
    """BM25 over chunks. Returns up to top_k hits.

    Each hit: {chunk_id, score, source, anchor, heading_path, char_start, char_end,
               text_preview, lang, matched_terms}.
    """
    postings, stats = _load()
    n = stats.get("n", 0)
    if n == 0:
        return []
    avg_dl = stats.get("avg_dl") or 1.0
    df = stats.get("df", {})
    chunk_dl = stats.get("chunk_dl", {})
    chunk_meta = stats.get("chunk_meta", {})

    expanded: list[str] = []
    for tok in tokenize(q):
        for v in variants(tok):
            if v in postings and v not in expanded:
                expanded.append(v)

    if not expanded:
        return []

    scores: dict[str, float] = {}
    matched: dict[str, set[str]] = {}
    for term in expanded:
        plist = postings.get(term, {})
        n_t = df.get(term, len(plist)) or 1
        idf = math.log(1 + (n - n_t + 0.5) / (n_t + 0.5))
        for cid, tf in plist.items():
            dl = chunk_dl.get(cid, int(avg_dl)) or 1
            denom = tf + BM25_K1 * (1 - BM25_B + BM25_B * dl / avg_dl)
            score = idf * (tf * (BM25_K1 + 1)) / denom
            scores[cid] = scores.get(cid, 0.0) + score
            matched.setdefault(cid, set()).add(term)

    ranked = sorted(scores.items(), key=lambda kv: -kv[1])[:top_k]
    if not ranked:
        return []

    # Load chunk texts lazily from JSONL (cache per source)
    text_cache: dict[str, dict[str, str]] = {}

    def _text_for(cid: str, source: str) -> str:
        if source not in text_cache:
            text_cache[source] = {c["chunk_id"]: c["text"] for c in chunker.load_chunks(source)}
        return text_cache[source].get(cid, "")

    out: list[dict] = []
    for cid, score in ranked:
        meta = chunk_meta.get(cid, {})
        text = _text_for(cid, meta.get("source", ""))
        preview = text.replace("\n", " ").strip()
        if len(preview) > 320:
            preview = preview[:320] + "…"
        out.append({
            "chunk_id": cid,
            "score": round(score, 3),
            "source": meta.get("source", ""),
            "anchor": meta.get("anchor", ""),
            "heading_path": meta.get("heading_path", []),
            "char_start": meta.get("char_start", 0),
            "char_end": meta.get("char_end", 0),
            "lang": meta.get("lang", ""),
            "text": text,
            "preview": preview,
            "matched_terms": sorted(matched.get(cid, set())),
        })
    return out
