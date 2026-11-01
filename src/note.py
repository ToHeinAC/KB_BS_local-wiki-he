"""Typed notes for the second brain: a note written on 2BrAIn is cleaned up by the local model
(typos, Markdown structure, explicit references, key facts, keywords) before it joins an upload
batch. The model only rewrites; code pins the language, keeps only keywords the note contains,
flags numbers the note does not contain, and stores the typed text verbatim below the cleaned
version, so every citation can be checked against what was actually written."""

import re
import unicodedata
from datetime import date

import lang
import ollama_client
import prompts

ORIGINAL_HEADING = "## Original note"
_SLUG_MAX = 50
_UMLAUTS = str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss"})
_KEYWORDS_RE = re.compile(r"^[*_]*keywords[*_]*\s*:[*_]*\s*(.*)$", re.IGNORECASE | re.MULTILINE)
_WORD_RE = re.compile(r"\w+")
_NUMBER_RE = re.compile(r"\d+(?:[.,:/-]\d+)*")


def _slug(text: str) -> str:
    ascii_text = unicodedata.normalize("NFKD", text.lower().translate(_UMLAUTS))
    ascii_text = ascii_text.encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_text).strip("-")
    if len(slug) > _SLUG_MAX:
        cut = slug[: _SLUG_MAX + 1]
        slug = cut.rsplit("-", 1)[0] if "-" in cut else slug[:_SLUG_MAX]
    return slug


def _topic(title: str, cleaned: str) -> str:
    """The title, else the cleaned note's first heading, else its first line."""
    if title.strip():
        return title
    lines = [line.strip() for line in cleaned.splitlines() if line.strip()]
    heading = next((line for line in lines if line.startswith("# ")), "")
    return (heading or (lines[0] if lines else "")).lstrip("#")


def file_name(title: str, cleaned: str, day: date) -> str:
    """`note-<day>-<slug>.md`, the slug from the topic in lowercase ASCII."""
    slug = _slug(_topic(title, cleaned))
    return f"note-{day.isoformat()}{'-' + slug if slug else ''}.md"


def keep_known_keywords(cleaned: str, original: str) -> str:
    """Keep only keywords whose words all occur in the note; drop the line if none is left."""
    matches = list(_KEYWORDS_RE.finditer(cleaned))
    if not matches:
        return cleaned
    match = matches[-1]
    known = {w.lower() for w in _WORD_RE.findall(original)}
    terms = [t.strip().strip("*_") for t in match.group(1).split(",")]
    kept = [t for t in terms if t and {w.lower() for w in _WORD_RE.findall(t)} <= known]
    line = f"Keywords: {', '.join(kept)}" if kept else ""
    return (cleaned[: match.start()] + line + cleaned[match.end() :]).rstrip()


def new_numbers(cleaned: str, original: str) -> list[str]:
    """Numbers in the cleaned note that the typed note does not contain, in order."""
    known = set(_NUMBER_RE.findall(original))
    return list(dict.fromkeys(n for n in _NUMBER_RE.findall(cleaned) if n not in known))


def compose(cleaned: str, original: str) -> str:
    """The stored source: the cleaned note, then the typed note verbatim as a quote (so its
    lines cannot become headings of their own)."""
    quoted = "\n".join(f"> {line}" if line else ">" for line in original.strip().splitlines())
    return f"{cleaned.rstrip()}\n\n{ORIGINAL_HEADING}\n\n{quoted}\n"


def _unfence(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else ""
        text = text.removesuffix("```")
    return text.strip()


def clean(text: str, title: str) -> str:
    """The note cleaned up by the local model (blocking: run in a worker). Raises RuntimeError
    when Ollama fails."""
    system = (
        f"{prompts.NOTE_CLEANUP_SYSTEM}\n\n{prompts.NOTE_LANGUAGE_DIRECTIVE[lang.detect(text)]}"
    )
    title_rule = prompts.NOTE_TITLE_RULE.format(title=title.strip()) if title.strip() else ""
    prompt = prompts.NOTE_CLEANUP_PROMPT.format(title_rule=title_rule, note=text.strip())
    reply = ollama_client.generate(system, prompt, temperature=0.2)
    return keep_known_keywords(_unfence(reply), text)
