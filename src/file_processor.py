"""Extract plain text from uploaded documents."""

import os
from html.parser import HTMLParser
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

MAX_CHARS = int(os.getenv("MAX_INGEST_CHARS", "40000"))


class _HTMLStripper(HTMLParser):
    def __init__(self):
        super().__init__()
        self._parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self._parts.append(data)

    def get_text(self) -> str:
        return " ".join(self._parts)


def _extract_pdf(path: Path) -> str:
    from pypdf import PdfReader
    reader = PdfReader(str(path))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def _extract_docx(path: Path) -> str:
    from docx import Document
    doc = Document(str(path))
    return "\n".join(p.text for p in doc.paragraphs)


def _extract_html(path: Path) -> str:
    parser = _HTMLStripper()
    parser.feed(path.read_text(errors="replace"))
    return parser.get_text()


def extract_text(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        text = _extract_pdf(path)
    elif suffix == ".docx":
        text = _extract_docx(path)
    elif suffix in (".md", ".txt"):
        text = path.read_text(errors="replace")
    elif suffix in (".html", ".htm"):
        text = _extract_html(path)
    else:
        raise ValueError(f"Unsupported file type: {suffix}")
    return text


def chunk_text(text: str, chunk_size: int = MAX_CHARS) -> list[str]:
    """Split text into chunks at paragraph boundaries; fall back to hard split."""
    if len(text) <= chunk_size:
        return [text]
    chunks, start = [], 0
    while start < len(text):
        end = min(start + chunk_size, len(text))
        if end < len(text):
            boundary = text.rfind("\n\n", start, end)
            if boundary > start:
                end = boundary + 2
        chunks.append(text[start:end])
        start = end
    return chunks
