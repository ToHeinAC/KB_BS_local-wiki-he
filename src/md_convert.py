"""Convert non-Markdown uploads (PDF / DOCX / images) to Markdown.

Pipeline ported and adapted from ToHeinAC/MD-maker (Apache-2.0):
https://github.com/ToHeinAC/MD-maker

- PDF: per-page routing — digital-text pages keep their extracted text word for
  word (law structure promoted to headings in code); scanned/empty pages are
  rasterized and OCR'd via a vision model.
- DOCX: deterministic heading/list/table mapping (no LLM).
- Images: OCR via the vision model.

All Ollama access goes through ollama_client; all prompts live in prompts.py.
"""

from __future__ import annotations

import base64
import io
import os
import re
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from dotenv import load_dotenv

import ollama_client
from prompts import OCR_DEEPSEEK_PROMPT, OCR_SYSTEM_PROMPT, OCR_USER_PROMPT

if TYPE_CHECKING:
    from docx.table import Table
    from docx.text.paragraph import Paragraph
    from PIL.Image import Image

load_dotenv()

OCR_MODEL = os.getenv("OCR_MODEL", "deepseek-ocr:3b")
PDF_DPI = int(os.getenv("PDF_DPI", "150"))

TEXT_THRESHOLD = 40  # chars; below this a PDF page is treated as image-only

CONVERTIBLE_EXTS = {
    ".pdf",
    ".docx",
    ".png",
    ".jpg",
    ".jpeg",
    ".tiff",
    ".tif",
    ".bmp",
}
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".tiff", ".tif", ".bmp"}

# Callback signature: on_progress(done: int, total: int, label: str) -> None
ProgressCb = Callable[[int, int, str], None]
# One PDF page: extractable text, or a rendered image for OCR.
PdfPage = tuple[Literal["text"], str] | tuple[Literal["image"], "Image"]


def is_convertible(filename: str) -> bool:
    """True if the file extension can be converted to Markdown."""
    return Path(filename).suffix.lower() in CONVERTIBLE_EXTS


# --- image / PDF helpers (from MD-maker pdf_utils.py) ----------------------


def _image_to_base64(pil_image: Image) -> str:
    buf = io.BytesIO()
    pil_image.convert("RGB").save(buf, format="JPEG", quality=85)
    return base64.b64encode(buf.getvalue()).decode()


def iter_pdf_pages(pdf_bytes: bytes, dpi: int = PDF_DPI) -> Iterator[PdfPage]:
    """Yield ('text', str) for pages with extractable text, else ('image', PIL.Image)."""
    import pypdfium2 as pdfium  # pyright: ignore[reportMissingTypeStubs]

    scale = dpi / 72
    doc: Any = pdfium.PdfDocument(pdf_bytes)  # pypdfium2's helpers are unannotated
    for page in doc:
        textpage = page.get_textpage()
        text = textpage.get_text_range().strip()
        if len(text) >= TEXT_THRESHOLD:
            yield "text", text
        else:
            bitmap = page.render(scale=scale)
            yield "image", bitmap.to_pil()


def _pdf_page_count(pdf_bytes: bytes) -> int:
    import pypdfium2 as pdfium  # pyright: ignore[reportMissingTypeStubs]

    return len(pdfium.PdfDocument(pdf_bytes))


# --- LLM calls (from MD-maker models.py) -----------------------------------


def convert_image(pil_image: Image, model_id: str = OCR_MODEL) -> str:
    """OCR one image to Markdown via a vision model."""
    img_b64 = _image_to_base64(pil_image)
    if model_id.startswith("deepseek-ocr"):
        prompt = OCR_DEEPSEEK_PROMPT
    else:
        prompt = f"{OCR_SYSTEM_PROMPT}\n\n{OCR_USER_PROMPT}"
    return ollama_client.ocr(model_id, prompt, img_b64)


# --- DOCX helpers (from MD-maker docx_utils.py) ----------------------------


def _paragraph_md(para: Paragraph) -> str | None:
    text = para.text.strip()
    if not text:
        return None
    style = (para.style.name if para.style else None) or ""
    if style.startswith("Heading 1"):
        return f"# {text}"
    if style.startswith("Heading 2"):
        return f"## {text}"
    if style.startswith("Heading 3"):
        return f"### {text}"
    if "Bullet" in style:
        return f"- {text}"
    if "Number" in style:
        return f"1. {text}"
    return text


def _table_md(table: Table) -> str | None:
    rows = table.rows
    if not rows:
        return None
    lines: list[str] = []
    header = [c.text.strip() for c in rows[0].cells]
    lines.append("| " + " | ".join(header) + " |")
    lines.append("| " + " | ".join("---" for _ in header) + " |")
    for row in rows[1:]:
        cells = [c.text.strip() for c in row.cells]
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def extract_docx_text(docx_bytes: bytes) -> str:
    """Convert a .docx file to Markdown, preserving document order (no LLM step)."""
    from docx import Document
    from docx.text.paragraph import Paragraph

    doc = Document(io.BytesIO(docx_bytes))
    parts: list[str] = []
    for block in doc.iter_inner_content():  # body-level paragraphs and tables, in order
        md = _paragraph_md(block) if isinstance(block, Paragraph) else _table_md(block)
        if md:
            parts.append(md)
    return "\n\n".join(parts)


# --- unified entry point ---------------------------------------------------


def _convert_pdf(pdf_bytes: bytes, on_progress: ProgressCb | None) -> str:
    total = _pdf_page_count(pdf_bytes)
    parts: list[str] = []
    for i, page in enumerate(iter_pdf_pages(pdf_bytes)):
        if on_progress:
            kind = "OCR" if page[0] == "image" else "text"
            on_progress(i, total, f"Page {i + 1}/{total} ({kind})")
        if page[0] == "text":
            parts.append(page[1])
        else:
            parts.append(convert_image(page[1]))
    if on_progress:
        on_progress(total, total, "Done")
    return _promote_headings("\n\n".join(parts))


# A section's title line in extracted law text ("§ 62 Entlassung …"), not a wrapped
# sentence that starts with a reference ("§ 61 Absatz 2 Satz 2, …").
_SECTION_LINE_RE = re.compile(
    r"^§\s*\d+[a-z]?\s+(?!(?:Abs\.|Absatz|Satz|Nr\.|Nummer|und|oder|bis)\b)[A-ZÄÖÜ(].{0,200}$"
)
# Page header/footer lines between a heading and what follows it (official law PDFs).
_PAGE_FURNITURE_RE = re.compile(
    r"^(?:-\s*)?Seite \d+ von \d+(?:\s*-)?$|^Ein Service des Bundesministerium"
)
_STRUCTURE_LINE_RE = re.compile(r"^(?:Teil|Kapitel|Abschnitt|Unterabschnitt|Anlage)\s+\d+[a-z]?$")


def _promote_headings(text: str) -> str:
    """`text` with law structure as `## ` headings, every word kept: a line that is only
    "Teil 2" / "Kapitel 1" / "Abschnitt 3" / "Anlage 1", and a "§ n Title" line that body
    text follows (a run of § lines is a table of contents and stays plain), so the chunker
    gets one anchor per section."""
    lines = text.splitlines()
    out: list[str] = []
    for i, line in enumerate(lines):
        s = line.strip()
        if _STRUCTURE_LINE_RE.match(s) or (_SECTION_LINE_RE.match(s) and _has_body(lines, i)):
            out.append(f"## {s}")
        else:
            out.append(line)
    return "\n".join(out)


def _has_body(lines: list[str], i: int) -> bool:
    """Body text follows `lines[i]`: the next non-empty line is no heading, and is not a
    wrapped title's tail (no sentence end) that another heading follows, as in the
    table of contents."""
    following = (lines[j].strip() for j in range(i + 1, len(lines)))
    nxt = (ln for ln in following if ln and not _PAGE_FURNITURE_RE.match(ln))
    first, second = next(nxt, ""), next(nxt, "")
    if not first or _is_heading_line(first):
        return False
    return first.endswith((".", ":", ";")) or not _is_heading_line(second)


def _is_heading_line(line: str) -> bool:
    return bool(_SECTION_LINE_RE.match(line) or _STRUCTURE_LINE_RE.match(line))


def convert_to_markdown(
    file_bytes: bytes, filename: str, on_progress: ProgressCb | None = None
) -> str:
    """Convert a supported file to a Markdown string. Dispatch by extension."""
    suffix = Path(filename).suffix.lower()
    if suffix == ".pdf":
        try:
            return _convert_pdf(file_bytes, on_progress)
        finally:
            # Free the OCR model so the ingest step (a text model) gets the full
            # GPU instead of sharing/splitting VRAM with the resident vision model.
            ollama_client.unload(OCR_MODEL)
    if suffix == ".docx":
        if on_progress:
            on_progress(0, 1, "Converting DOCX")
        md = extract_docx_text(file_bytes)
        if on_progress:
            on_progress(1, 1, "Done")
        return md
    if suffix in IMAGE_EXTS:
        from PIL import Image

        if on_progress:
            on_progress(0, 1, "OCR image")
        try:
            md = convert_image(Image.open(io.BytesIO(file_bytes)))
        finally:
            ollama_client.unload(OCR_MODEL)  # free VRAM for the ingest text model
        if on_progress:
            on_progress(1, 1, "Done")
        return md
    raise ValueError(f"Unsupported file type: {suffix}")
