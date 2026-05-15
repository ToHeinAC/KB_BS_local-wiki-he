"""Ingest-time term/acronym/fact extraction.

One LLM call per source produces structured sidecars that retrieval consumes
directly:

- aliases.json : cross-language and abbreviation synonyms
- acronyms.json: short → expansion
- terms.json   : defined terms with anchor and short definition
- facts.jsonl  : numeric facts with unit and anchor

Failures are swallowed — extraction is best-effort, never fatal to `ingest()`.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

from dotenv import load_dotenv

import ollama_client
import schema_loader
from prompts import EXTRACT_TERMS_PROMPT

load_dotenv()

INDEX_DIR = Path(os.getenv("INDEX_DIR", "data/index"))
ALIASES_PATH = INDEX_DIR / "aliases.json"
ACRONYMS_PATH = INDEX_DIR / "acronyms.json"
TERMS_PATH = INDEX_DIR / "terms.json"
FACTS_PATH = INDEX_DIR / "facts.jsonl"

# Sources larger than this get a digest (heading list + chunk previews) instead
# of the full text. Keeps the LLM context bounded.
DIGEST_THRESHOLD = 30_000
DIGEST_PREVIEW_CHARS = 200


def _build_digest(chunks: list[dict]) -> str:
    """Heading + first-N-chars-of-each-chunk digest for very large sources."""
    parts: list[str] = []
    for ch in chunks:
        anchor = ch.get("anchor") or ""
        prev = (ch.get("text") or "")[:DIGEST_PREVIEW_CHARS].replace("\n", " ").strip()
        parts.append(f"[{anchor}] {prev}")
    return "\n".join(parts)


def _strip_json_fences(s: str) -> str:
    s = s.strip()
    if s.startswith("```"):
        s = re.sub(r"^```(?:json)?\s*", "", s)
        s = re.sub(r"\s*```\s*$", "", s)
    # Some models prepend prose; try to find the first { and last } pair.
    if not s.startswith("{"):
        first = s.find("{")
        last = s.rfind("}")
        if first != -1 and last > first:
            s = s[first : last + 1]
    return s


def _empty() -> dict:
    return {"aliases": [], "acronyms": [], "terms": [], "facts": []}


def extract(source_name: str, text: str, chunks: list[dict] | None = None) -> dict:
    """Run the LLM extraction. Returns dict with the four keys, possibly empty."""
    if not text or not text.strip():
        return _empty()
    payload = text
    if len(text) > DIGEST_THRESHOLD and chunks:
        payload = _build_digest(chunks)
    try:
        system = schema_loader.get_system_prompt()
    except Exception:
        system = ""
    prompt = EXTRACT_TERMS_PROMPT.format(source_name=source_name, text=payload)
    try:
        raw = ollama_client.generate(system, prompt, temperature=0.1)
    except Exception:
        return _empty()
    try:
        data = json.loads(_strip_json_fences(raw))
    except Exception:
        return _empty()
    if not isinstance(data, dict):
        return _empty()
    out = _empty()
    for key in out:
        val = data.get(key)
        if isinstance(val, list):
            out[key] = val
    return out


def _load_json(path: Path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text())
    except Exception:
        return default


def _merge_aliases(existing: list[dict], incoming: list[dict]) -> list[dict]:
    # First-writer-wins on the canonical surface form so repeated persists are
    # stable. Variants accumulate as a set keyed off the canonical's lowercase.
    canon_key: dict[str, str] = {}
    variants_set: dict[str, set[str]] = {}
    for entry in existing + incoming:
        canon = str(entry.get("canonical", "")).strip()
        if not canon:
            continue
        key = canon.lower()
        canon_key.setdefault(key, canon)
        variants_set.setdefault(key, set())
        for v in entry.get("variants", []) or []:
            v = str(v).strip()
            if v and v != canon_key[key]:
                variants_set[key].add(v)
    return [
        {"canonical": canon_key[k], "variants": sorted(variants_set[k])}
        for k in sorted(canon_key)
    ]


def _merge_acronyms(existing: list[dict], incoming: list[dict]) -> list[dict]:
    by_acro: dict[str, str] = {}
    for entry in existing + incoming:
        acro = str(entry.get("acronym", "")).strip()
        exp = str(entry.get("expansion", "")).strip()
        if not acro or not exp:
            continue
        by_acro.setdefault(acro, exp)  # first writer wins
    return [{"acronym": a, "expansion": e} for a, e in sorted(by_acro.items())]


def _merge_terms(existing: list[dict], incoming: list[dict], source: str) -> list[dict]:
    by_term: dict[str, dict] = {}
    for entry in existing:
        term = str(entry.get("term", "")).strip()
        if term:
            by_term[term.lower()] = entry
    for entry in incoming:
        term = str(entry.get("term", "")).strip()
        if not term:
            continue
        entry = dict(entry)
        entry["term"] = term
        entry.setdefault("source", source)
        by_term.setdefault(term.lower(), entry)
    return list(by_term.values())


def persist(source_name: str, result: dict) -> None:
    """Merge extraction result into sidecars. Idempotent over re-ingests."""
    if not any(result.get(k) for k in ("aliases", "acronyms", "terms", "facts")):
        return
    INDEX_DIR.mkdir(parents=True, exist_ok=True)

    aliases = _merge_aliases(_load_json(ALIASES_PATH, []), result.get("aliases", []))
    ALIASES_PATH.write_text(json.dumps(aliases, ensure_ascii=False, indent=2))

    acronyms = _merge_acronyms(_load_json(ACRONYMS_PATH, []), result.get("acronyms", []))
    ACRONYMS_PATH.write_text(json.dumps(acronyms, ensure_ascii=False, indent=2))

    terms = _merge_terms(_load_json(TERMS_PATH, []), result.get("terms", []), source_name)
    TERMS_PATH.write_text(json.dumps(terms, ensure_ascii=False, indent=2))

    # facts: append-only JSONL with source tag
    with FACTS_PATH.open("a") as f:
        for fact in result.get("facts", []) or []:
            if not isinstance(fact, dict):
                continue
            record = dict(fact)
            record["source"] = source_name
            f.write(json.dumps(record, ensure_ascii=False) + "\n")


def load_aliases() -> list[dict]:
    return _load_json(ALIASES_PATH, [])


def load_acronyms() -> list[dict]:
    return _load_json(ACRONYMS_PATH, [])


def load_facts() -> list[dict]:
    if not FACTS_PATH.exists():
        return []
    out: list[dict] = []
    for line in FACTS_PATH.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except Exception:
            continue
    return out
