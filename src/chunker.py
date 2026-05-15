"""Structural chunker for ingested sources.

Splits a source into semantically bounded chunks with stable, content-addressable
ids and precise anchors. Chunks are the ground truth for retrieval and citation;
wiki pages become LLM summaries over them.

Boundary strategy (first matching rule wins):
1. Legal-style: lines like `## § N Title` (German statutes). Each § is one chunk.
2. Markdown headings: split on `##`/`###`. Long sections are paragraph-windowed.
3. Plain text: paragraph windows with overlap.

Output:
- A list[dict] of chunks, each with: chunk_id, source, anchor, heading_path,
  char_start, char_end, text, lang.
- Persistence: `data/chunks/<source-slug>.jsonl` (one chunk per line).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import unicodedata
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

CHUNKS_DIR = Path(os.getenv("CHUNKS_DIR", "data/chunks"))

MAX_CHUNK_CHARS = 4000
MIN_CHUNK_CHARS = 80
OVERLAP_CHARS = 300

_LEGAL_HEAD_RE = re.compile(r"^(#{1,4})\s*§\s*(\d+[a-z]?)\b(.*)$", re.MULTILINE)
_MD_HEAD_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$", re.MULTILINE)


def _slug(name: str) -> str:
    base = Path(name).stem.lower()
    return re.sub(r"[^a-z0-9]+", "-", base).strip("-") or "source"


def _normalize_for_hash(text: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFC", text)).strip().lower()


def chunk_id(text: str) -> str:
    """Stable 16-hex chunk id from normalized content."""
    return hashlib.sha256(_normalize_for_hash(text).encode("utf-8")).hexdigest()[:16]


def _detect_lang(text: str) -> str:
    sample = text[:4000].lower()
    de_markers = sum(sample.count(m) for m in (" der ", " die ", " und ", " ist ", "ä", "ö", "ü", "ß"))
    en_markers = sum(sample.count(m) for m in (" the ", " and ", " of ", " to ", " is "))
    return "de" if de_markers > en_markers else "en"


def _is_legal(text: str) -> bool:
    return len(_LEGAL_HEAD_RE.findall(text)) >= 3


def _split_long(text: str, anchor: str, heading_path: list[str], base_offset: int,
                lang: str) -> list[dict]:
    """Window an oversize section into overlapping paragraph-bounded chunks."""
    if len(text) <= MAX_CHUNK_CHARS:
        return [_mk(text, anchor, heading_path, base_offset, lang)]
    out: list[dict] = []
    paragraphs = re.split(r"\n\s*\n", text)
    buf: list[str] = []
    buf_len = 0
    cursor = base_offset
    part_no = 1
    for para in paragraphs:
        para_len = len(para) + 2
        if buf_len + para_len > MAX_CHUNK_CHARS and buf:
            joined = "\n\n".join(buf)
            sub_anchor = f"{anchor} (Teil {part_no})" if anchor else f"part {part_no}"
            out.append(_mk(joined, sub_anchor, heading_path, cursor, lang))
            # overlap: keep tail paragraphs covering OVERLAP_CHARS
            tail: list[str] = []
            tail_len = 0
            for p in reversed(buf):
                if tail_len >= OVERLAP_CHARS:
                    break
                tail.insert(0, p)
                tail_len += len(p) + 2
            buf = tail + [para]
            buf_len = sum(len(p) + 2 for p in buf)
            cursor += len(joined) - tail_len
            part_no += 1
        else:
            buf.append(para)
            buf_len += para_len
    if buf:
        joined = "\n\n".join(buf)
        sub_anchor = f"{anchor} (Teil {part_no})" if (anchor and part_no > 1) else anchor
        out.append(_mk(joined, sub_anchor, heading_path, cursor, lang))
    return out


def _mk(text: str, anchor: str, heading_path: list[str], char_start: int,
        lang: str) -> dict:
    text = text.strip()
    return {
        "chunk_id": chunk_id(text),
        "anchor": anchor,
        "heading_path": list(heading_path),
        "char_start": char_start,
        "char_end": char_start + len(text),
        "text": text,
        "lang": lang,
    }


def _chunk_legal(text: str, lang: str) -> list[dict]:
    """Split on `## § N` headers. Each § becomes one chunk (windowed if huge)."""
    matches = list(_LEGAL_HEAD_RE.finditer(text))
    chunks: list[dict] = []
    # Preamble before first §
    if matches and matches[0].start() > 0:
        pre = text[: matches[0].start()]
        if len(pre.strip()) >= MIN_CHUNK_CHARS:
            chunks.extend(_split_long(pre, "Präambel", [], 0, lang))
    for i, m in enumerate(matches):
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        section = text[start:end]
        anchor = f"§ {m.group(2)}"
        title = m.group(3).strip()
        heading_path = [anchor + (f" {title}" if title else "")]
        chunks.extend(_split_long(section, anchor, heading_path, start, lang))
    return chunks


def _chunk_markdown(text: str, lang: str) -> list[dict]:
    """Split on `##`/`###` headings; window long sections."""
    matches = [m for m in _MD_HEAD_RE.finditer(text) if 2 <= len(m.group(1)) <= 4]
    if not matches:
        return _chunk_plain(text, lang)
    chunks: list[dict] = []
    heading_stack: list[tuple[int, str]] = []
    # Preamble
    if matches[0].start() > 0:
        pre = text[: matches[0].start()]
        if len(pre.strip()) >= MIN_CHUNK_CHARS:
            chunks.extend(_split_long(pre, "Preamble", [], 0, lang))
    for i, m in enumerate(matches):
        level = len(m.group(1))
        title = m.group(2).strip()
        # Maintain stack of (level, title)
        heading_stack = [(lv, ti) for (lv, ti) in heading_stack if lv < level]
        heading_stack.append((level, title))
        heading_path = [ti for (_, ti) in heading_stack]
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        section = text[start:end]
        chunks.extend(_split_long(section, title, heading_path, start, lang))
    return chunks


def _chunk_plain(text: str, lang: str) -> list[dict]:
    return _split_long(text, "", [], 0, lang)


def split(text: str) -> list[dict]:
    """Return a list of chunk dicts for `text`. Pure function — no I/O."""
    if not text or not text.strip():
        return []
    lang = _detect_lang(text)
    if _is_legal(text):
        chunks = _chunk_legal(text, lang)
    else:
        chunks = _chunk_markdown(text, lang)
    # Drop too-small chunks (merge into previous when feasible)
    merged: list[dict] = []
    for ch in chunks:
        if merged and len(ch["text"]) < MIN_CHUNK_CHARS:
            prev = merged[-1]
            combined = prev["text"] + "\n\n" + ch["text"]
            prev["text"] = combined
            prev["char_end"] = ch["char_end"]
            prev["chunk_id"] = chunk_id(combined)
        else:
            merged.append(ch)
    return merged


def write_chunks(source_name: str, chunks: list[dict]) -> Path:
    """Persist chunks for a source as JSONL. Returns the file path."""
    CHUNKS_DIR.mkdir(parents=True, exist_ok=True)
    out = CHUNKS_DIR / f"{_slug(source_name)}.jsonl"
    with out.open("w") as f:
        for ch in chunks:
            record = dict(ch)
            record["source"] = source_name
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    return out


def load_chunks(source_name: str) -> list[dict]:
    path = CHUNKS_DIR / f"{_slug(source_name)}.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def all_chunks() -> list[dict]:
    """Load every chunk across every source. Used for index rebuilds."""
    if not CHUNKS_DIR.exists():
        return []
    out: list[dict] = []
    for p in sorted(CHUNKS_DIR.glob("*.jsonl")):
        for line in p.read_text().splitlines():
            if line.strip():
                out.append(json.loads(line))
    return out
