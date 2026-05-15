"""Ingest-time hypothetical-question generator (HyDE, lexical-only).

For each chunk, the LLM emits 2–4 short questions the chunk directly answers.
Questions are persisted to `data/index/qa.jsonl` keyed by chunk_id. The lexical
index (`lex_index.build`) folds question tokens into the parent chunk's term
frequencies so user queries phrased as questions can match the document's
intent rather than only its surface vocabulary.

Best-effort: any LLM/parse failure yields zero questions for that batch, never
raises. Gated by `INGEST_QA=1` in `wiki_engine.ingest()`.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

from dotenv import load_dotenv

import ollama_client
import schema_loader
from prompts import GENERATE_QUESTIONS_PROMPT

load_dotenv()

INDEX_DIR = Path(os.getenv("INDEX_DIR", "data/index"))
QA_PATH = INDEX_DIR / "qa.jsonl"

# Larger batches → fewer Ollama round-trips. 12 chunks × ~500 chars ≈ 6 KB
# context, comfortable for any local model.
BATCH_SIZE = int(os.getenv("QA_BATCH_SIZE", "12"))
CHUNK_PREVIEW_CHARS = 600
# Total cap on hypothetical-question pairs persisted per source. Keeping this
# small is the dominant ingest-speed lever for long documents: at the source
# level only the top-N retrieval-valuable chunks get questions generated.
MAX_PAIRS_PER_SOURCE = int(os.getenv("QA_MAX_PAIRS_PER_SOURCE", "5"))


def _chunks_block(batch: list[dict]) -> str:
    parts: list[str] = []
    for ch in batch:
        text = (ch.get("text") or "")[:CHUNK_PREVIEW_CHARS].strip()
        anchor = ch.get("anchor") or ""
        parts.append(f"--- chunk_id: {ch['chunk_id']} ({anchor})\n{text}")
    return "\n\n".join(parts)


def _strip_json_fences(s: str) -> str:
    s = s.strip()
    if s.startswith("```"):
        s = re.sub(r"^```(?:json)?\s*", "", s)
        s = re.sub(r"\s*```\s*$", "", s)
    if not s.startswith("["):
        first = s.find("[")
        last = s.rfind("]")
        if first != -1 and last > first:
            s = s[first : last + 1]
    return s


def _run_batch(batch: list[dict]) -> list[tuple[str, str]]:
    try:
        system = schema_loader.get_system_prompt()
    except Exception:
        system = ""
    prompt = GENERATE_QUESTIONS_PROMPT.format(chunks_block=_chunks_block(batch))
    try:
        raw = ollama_client.generate(system, prompt, temperature=0.2)
    except Exception:
        return []
    try:
        data = json.loads(_strip_json_fences(raw))
    except Exception:
        return []
    if not isinstance(data, list):
        return []
    out: list[tuple[str, str]] = []
    valid_ids = {ch["chunk_id"] for ch in batch}
    for entry in data:
        if not isinstance(entry, dict):
            continue
        cid = str(entry.get("chunk_id", "")).strip()
        if cid not in valid_ids:
            continue
        for q in entry.get("questions", []) or []:
            q = str(q).strip()
            if q:
                out.append((cid, q))
    return out


def _select_target_chunks(chunks: list[dict], k: int) -> list[dict]:
    """Pick the top-k retrieval-valuable chunks (heading-anchored, dense).

    Heuristic (no LLM): prefer chunks whose anchor or heading_path names a
    semantic section (`§ N` or any markdown heading), then rank by unique-token
    count after stopword/variant normalisation (proxy for information density).
    Tie-break by chunk length, then by char_start for stable ordering.
    """
    if k <= 0 or not chunks:
        return []
    import lex_index

    def density(ch: dict) -> int:
        seen: set[str] = set()
        for tok in lex_index.tokenize(ch.get("text") or ""):
            for v in lex_index.variants(tok):
                seen.add(v)
        return len(seen)

    def is_anchored(ch: dict) -> int:
        anchor = (ch.get("anchor") or "").strip()
        if anchor.startswith("§") or anchor.startswith("#"):
            return 1
        if anchor and not anchor.lower().startswith(("preamble", "präambel", "part ")):
            return 1
        if ch.get("heading_path"):
            return 1
        return 0

    scored = [
        (
            -is_anchored(ch),       # anchored first
            -density(ch),           # then densest
            -len(ch.get("text") or ""),  # then longest
            ch.get("char_start", 0),     # stable
            i,                            # break remaining ties by input order
        )
        for i, ch in enumerate(chunks)
    ]
    scored.sort()
    return [chunks[t[-1]] for t in scored[:k]]


def generate(chunks: list[dict]) -> list[tuple[str, str]]:
    """Return up to `MAX_PAIRS_PER_SOURCE` (chunk_id, question) pairs.

    Picks the top-k highest-value chunks and runs a single LLM batch against
    them. Empty list on failure.
    """
    if not chunks:
        return []
    targets = _select_target_chunks(chunks, MAX_PAIRS_PER_SOURCE)
    if not targets:
        return []
    results: list[tuple[str, str]] = []
    for i in range(0, len(targets), BATCH_SIZE):
        batch = targets[i : i + BATCH_SIZE]
        results.extend(_run_batch(batch))
    return results[:MAX_PAIRS_PER_SOURCE]


def persist(items: list[tuple[str, str]], source: str) -> None:
    if not items:
        return
    INDEX_DIR.mkdir(parents=True, exist_ok=True)
    with QA_PATH.open("a") as f:
        for cid, q in items:
            f.write(json.dumps({"chunk_id": cid, "question": q, "source": source},
                               ensure_ascii=False) + "\n")


def load() -> dict[str, list[str]]:
    """Return {chunk_id: [questions]} from qa.jsonl."""
    if not QA_PATH.exists():
        return {}
    out: dict[str, list[str]] = {}
    for line in QA_PATH.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except Exception:
            continue
        cid = rec.get("chunk_id")
        q = rec.get("question")
        if cid and q:
            out.setdefault(cid, []).append(q)
    return out
