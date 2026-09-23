"""Page-language pinning: a wiki page keeps the language it was created in.

Everything that decides is deterministic code (small-model-safe): a page's
language, which lines of it are foreign, which original terms and hard facts a
translation must keep. The one LLM step, `translate()`, is a single-purpose call
whose output code verifies; on any doubt the caller keeps the original text as a
labelled quote instead — a fact is never lost, and mixing is only ever explicit.
See docs/architecture.md §Page language.
"""

from __future__ import annotations

import re

import frontmatter

import lang
import ollama_client
import schema_loader
from prompts import INGEST_LANGUAGE_DIRECTIVE, LANGUAGE_NAMES, TRANSLATE_CONTRIBUTION_PROMPT

_CITE_RE = re.compile(r"\[[^\]\n]+\](?!\()")          # [source.md], not [link](url)
_CODE_RE = re.compile(r"`([^`\n]{2,60})`")
_NUMBER_RE = re.compile(r"\d+(?:[.,]\d+)*")
_SECTION_REF_RE = re.compile(r"(?:§|Art\.)\s*\d+[a-z]?")
_WORD_RE = re.compile(r"[A-Za-zÄÖÜäöüß]{2,}")
_HEADING_RE = re.compile(r"^#{1,6}\s+(.*)$")
_MARKER_RE = re.compile(r"^(\s*(?:[-*+]|\d+\.)\s+)")
_FENCE_RE = re.compile(r"^(```|~~~)")
# Original terms the ingest model marks up: **bold**, *italic*, `code`, „quoted“.
_TERM_RES = (
    re.compile(r"\*\*([^*\n]{2,60}?)\*\*"),
    re.compile(r"(?<![*\w])\*([^*\n]{2,60}?)\*(?![*\w])"),
    _CODE_RE,
    re.compile(r"[„“\"]([^\"“”„\n]{2,60})[“”\"]"),
)
_MAX_TERMS = 30
_MIN_WORDS = 4      # shorter lines carry too little signal to classify
_JUDGE_WORDS = 8    # a whole reply shorter than this is not judged at all
_LEAD_LINES = 3     # the creator's lines — merges append below them
# Sections whose text is code-generated or deliberately original: never translated.
_EXEMPT_HEADINGS = ("## citations", "## contradictions", "## original (")


def other(code: str) -> str:
    return "en" if code == "de" else "de"


def text_lang(text: str, default: str) -> str:
    """Language of prose, ignoring citations and code (source names skew counts)."""
    return lang.detect(_CITE_RE.sub(" ", _CODE_RE.sub(" ", text or "")), default)


def clearly_other(text: str, plang: str) -> bool:
    """True when ``text`` is long enough to judge and is not in ``plang``."""
    words = len(_WORD_RE.findall(_CITE_RE.sub(" ", text or "")))
    return words >= _JUDGE_WORDS and text_lang(text, plang) != plang


def _line_lang(line: str) -> str | None:
    if len(_WORD_RE.findall(_CITE_RE.sub(" ", line))) < _MIN_WORDS:
        return None
    code = text_lang(line, "?")
    return None if code == "?" else code


def page_lang(content: str, default: str = "de") -> str:
    """A page's pinned language: its `lang` stamp, else its creator's lead lines."""
    try:
        post = frontmatter.loads(content)
    except Exception:
        return default
    code = str(post.metadata.get("lang") or "").strip().lower()
    if code in LANGUAGE_NAMES:
        return code
    lead = [ln for ln in post.content.splitlines()
            if len(_WORD_RE.findall(_CITE_RE.sub(" ", ln))) >= _MIN_WORDS
            and not ln.lstrip().startswith(("#", ">", "|"))][:_LEAD_LINES]
    return text_lang("\n".join(lead), default)


def original_terms(text: str) -> list[str]:
    """Marked-up terms of ``text`` (bold/italic/code/quoted), deduped, capped."""
    seen: set[str] = set()
    out: list[str] = []
    for rx in _TERM_RES:
        for m in rx.finditer(text):
            term = m.group(1).strip(" .,;:")
            if len(term) >= 2 and not term.isdigit() and term.lower() not in seen:
                seen.add(term.lower())
                out.append(term)
    return out[:_MAX_TERMS]


def missing_protected(source: str, translated: str) -> list[str]:
    """Numbers, § references and citations of ``source`` absent from ``translated``."""
    def numbers(t):
        return {re.sub(r"[.,]", "", n) for n in _NUMBER_RE.findall(t)}

    def refs(t):
        return {re.sub(r"\s+", "", r) for r in _SECTION_REF_RE.findall(t)}

    return (sorted(numbers(source) - numbers(translated))
            + sorted(refs(source) - refs(translated))
            + sorted(set(_CITE_RE.findall(source)) - set(_CITE_RE.findall(translated))))


def _strip_fence(text: str) -> str:
    lines = text.strip().splitlines()
    if lines and _FENCE_RE.match(lines[0]):
        lines = lines[1:]
        if lines and _FENCE_RE.match(lines[-1]):
            lines = lines[:-1]
    return "\n".join(lines).strip()


def _restore_markers(source: str, translated: str) -> str:
    """Re-add list markers the model dropped, when the lines still pair up 1:1."""
    src = [ln for ln in source.splitlines() if ln.strip()]
    out = translated.splitlines()
    idx = [i for i, ln in enumerate(out) if ln.strip()]
    if len(src) != len(idx):
        return translated
    for s_line, i in zip(src, idx):
        m = _MARKER_RE.match(s_line)
        if m and not _MARKER_RE.match(out[i]) and not _HEADING_RE.match(out[i].strip()):
            out[i] = m.group(1) + out[i].lstrip()
    return "\n".join(out)


def translate(text: str, src: str, tgt: str) -> str | None:
    """Translate ``text`` src→tgt keeping original terms; None unless verified.

    Rejected (None) when the call fails, returns nothing or the input unchanged,
    drops a number, § reference or citation, or is clearly not in ``tgt``.
    """
    prompt = TRANSLATE_CONTRIBUTION_PROMPT.format(
        source_language=LANGUAGE_NAMES[src], target_language=LANGUAGE_NAMES[tgt],
        terms="; ".join(original_terms(text)) or "(none)", text=text)
    system = schema_loader.get_system_prompt() + "\n\n" + INGEST_LANGUAGE_DIRECTIVE[tgt]
    try:
        out = _strip_fence(ollama_client.generate(
            system, prompt, temperature=0.1, model_id=ollama_client._INGEST_MODEL) or "")
    except Exception:
        return None
    if not out or out == text.strip() or missing_protected(text, out) or clearly_other(out, tgt):
        return None
    return _restore_markers(text, out)


def quote(text: str) -> list[str]:
    """``text`` as blockquote lines (headings become bold) — the labelled fallback."""
    out = []
    for line in text.splitlines():
        if not line.strip():
            continue
        m = _HEADING_RE.match(line.strip())
        out.append(f"> **{m.group(1)}**" if m else f"> {line.rstrip()}")
    return out


def _classify(lines: list[str], plang: str) -> list[str | None]:
    """Per line: 'f' foreign, 'k' keep (breaks a run), None neutral (blank/short)."""
    foreign = other(plang)
    cls: list[str | None] = [None] * len(lines)
    section_of = [-1] * len(lines)
    head, exempt, fence = -1, False, False
    for i, line in enumerate(lines):
        s = line.strip()
        if _FENCE_RE.match(s) or fence:
            fence = fence != bool(_FENCE_RE.match(s))
            cls[i] = "k"
        elif _HEADING_RE.match(s):
            head, exempt, cls[i] = i, s.lower().startswith(_EXEMPT_HEADINGS), "k"
        elif s:
            section_of[i] = head
            if exempt or s.startswith((">", "|")):
                cls[i] = "k"
            else:
                code = _line_lang(s)
                cls[i] = "f" if code == foreign else ("k" if code == plang else None)
    # A heading is foreign when every classified line of its section is.
    for h in {s for s in section_of if s >= 0}:
        if lines[h].strip().lower() == "## key facts":
            continue
        body = [cls[j] for j, s in enumerate(section_of) if s == h and cls[j]]
        if body and all(c == "f" for c in body):
            cls[h] = "f"
    return cls


def foreign_runs(body: str, plang: str) -> list[tuple[int, int]]:
    """[start, end) line ranges of consecutive foreign lines (blanks/short lines inside)."""
    cls = _classify(body.splitlines(), plang)
    runs, i = [], 0
    while i < len(cls):
        if cls[i] != "f":
            i += 1
            continue
        last = k = i
        while k < len(cls) and cls[k] != "k":
            last = k if cls[k] == "f" else last
            k += 1
        runs.append((i, last + 1))
        i = last + 1
    return runs


def foreign_line_count(body: str, plang: str) -> int:
    lines = body.splitlines()
    return sum(1 for s, e in foreign_runs(body, plang) for ln in lines[s:e] if ln.strip())


def normalize_body(body: str, plang: str) -> str:
    """Translate each foreign run in place; a labelled original quote on failure."""
    lines = body.splitlines()
    src = other(plang)
    for s, e in reversed(foreign_runs(body, plang)):
        text = "\n".join(lines[s:e])
        done = translate(text, src, plang)
        lines[s:e] = done.splitlines() if done else [f"> **Original ({src.upper()}):**", *quote(text)]
    return "\n".join(lines).rstrip() + "\n"
