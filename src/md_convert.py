"""Convert non-Markdown uploads (PDF / DOCX / images) to Markdown.

Pipeline ported and adapted from ToHeinAC/MD-maker (Apache-2.0):
https://github.com/ToHeinAC/MD-maker

- PDF: per-page routing — digital-text pages keep their extracted text word for
  word; scanned/empty pages are rasterized and OCR'd via a vision model. In code:
  pdfium's soft-hyphen markers are resolved, running heads/feet and page numbers
  dropped, words split across pages rejoined, and headings set — law structure for
  statutes, larger or bold lines for everything else.
- DOCX: deterministic heading/list/table mapping (no LLM).
- Images: OCR via the vision model.

All Ollama access goes through ollama_client; all prompts live in prompts.py.
"""

from __future__ import annotations

import base64
import ctypes
import io
import os
import re
from collections import Counter
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass
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


@dataclass(frozen=True)
class PdfLine:
    """One line of a PDF text layer: its text, its letters' typical glyph-box height in pt
    and font weight; 0 means unknown (OCR text, a font without the data)."""

    text: str
    size: float = 0.0
    weight: int = 0


# One PDF page: its text-layer lines, or a rendered image for OCR.
PdfPage = tuple[Literal["text"], list[PdfLine]] | tuple[Literal["image"], "Image"]


def is_convertible(filename: str) -> bool:
    """True if the file extension can be converted to Markdown."""
    return Path(filename).suffix.lower() in CONVERTIBLE_EXTS


# --- image / PDF helpers (from MD-maker pdf_utils.py) ----------------------


def _image_to_base64(pil_image: Image) -> str:
    buf = io.BytesIO()
    pil_image.convert("RGB").save(buf, format="JPEG", quality=85)
    return base64.b64encode(buf.getvalue()).decode()


def _mode(values: Iterable[Any], default: Any) -> Any:
    top = Counter(values).most_common(1)
    return top[0][0] if top else default


def _page_lines(textpage: Any, text: str) -> list[PdfLine]:
    """`text` (the page's text layer) as lines with the size and weight of their letters."""
    import pypdfium2.raw as pdfium_raw  # pyright: ignore[reportMissingTypeStubs]

    pdfium_c: Any = pdfium_raw  # ctypes bindings, unannotated
    exact = len(text) == textpage.count_chars()  # char index == string index
    box: Any = pdfium_c.FS_RECTF()
    out: list[PdfLine] = []
    pos = 0
    for line in text.split("\n"):  # pdfium ends lines with "\r\n"
        sizes: list[float] = []
        weights: list[int] = []
        for k in range(pos, pos + len(line)) if exact else ():
            if text[k].isalpha():
                pdfium_c.FPDFText_GetLooseCharBox(textpage.raw, k, ctypes.byref(box))
                sizes.append(round(box.top - box.bottom, 1))
                weights.append(pdfium_c.FPDFText_GetFontWeight(textpage.raw, k))
        out.append(PdfLine(line.rstrip("\r"), _mode(sizes, 0.0), _mode(weights, 0)))
        pos += len(line) + 1
    return out


def iter_pdf_pages(pdf_bytes: bytes, dpi: int = PDF_DPI) -> Iterator[PdfPage]:
    """Yield ('text', lines) for pages with extractable text, else ('image', PIL.Image)."""
    import pypdfium2 as pdfium  # pyright: ignore[reportMissingTypeStubs]

    scale = dpi / 72
    doc: Any = pdfium.PdfDocument(pdf_bytes)  # pypdfium2's helpers are unannotated
    for page in doc:
        textpage = page.get_textpage()
        text = textpage.get_text_range()
        if len(text.strip()) >= TEXT_THRESHOLD:
            yield "text", _page_lines(textpage, text)
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
    pages: list[list[PdfLine]] = []
    for i, page in enumerate(iter_pdf_pages(pdf_bytes)):
        if on_progress:
            kind = "OCR" if page[0] == "image" else "text"
            on_progress(i, total, f"Page {i + 1}/{total} ({kind})")
        if page[0] == "text":
            pages.append(page[1])
        else:
            pages.append([PdfLine(ln) for ln in convert_image(page[1]).splitlines()])
    if on_progress:
        on_progress(total, total, "Done")
    return _pages_to_markdown(pages)


def _pages_to_markdown(pages: list[list[PdfLine]]) -> str:
    """The document's Markdown, every word of its body kept: without running heads/feet,
    with words split across pages rejoined and soft hyphens resolved; headings from the
    law structure for a statute, else from larger or bold lines."""
    pages = _strip_furniture(pages)
    plain = clean_text(_join_pages(["\n".join(ln.text for ln in p) for p in pages]))
    law = _promote_headings(plain)
    if law != plain:
        return law
    return clean_text(_join_pages(_font_heading_pages(pages)))


# --- text-layer cleanup ------------------------------------------------------

# A line end inside "Bau- und Möbel": the hyphen stays, the words stay apart.
_NO_JOIN = r"(?!(?:und|oder|bzw|sowie|bis|and|or|to)\b)"
# pdfium's marker of a line-end hyphen, before the word's lower-case rest.
_SOFT_HYPHEN_RE = re.compile("\ufffe(?:\r?\n)?(?=[a-zäöüß])" + _NO_JOIN)


def clean_text(text: str) -> str:
    """`text` with PDF text-layer artifacts resolved, every word kept: pdfium's line-end
    hyphen marker (U+FFFE) rejoins a split word ("Gru\ufffebenwässer" → "Grubenwässer") or
    stays a hyphen ("Gamma-Ortsdosisleistung"); a Symbol-font bullet (U+F0B7) becomes "•".
    Left in, "\\w+" tokenizing cuts the word in two and search misses it."""
    text = _SOFT_HYPHEN_RE.sub("", text)
    return text.replace("\ufffe", "-").replace("\uf0b7", "•")


_ZONE = 3  # lines at a page's top and bottom where running heads and feet sit
# A page number: "- 2 -", "17", "5.81", "C.3", "xvi".
_DASHES = "-\u2013\u2012\u2014"  # hyphen, en, figure and em dash
_PAGE_NO_RE = re.compile(
    rf"^[{_DASHES}\s]*(?:[A-Z]?\d+(?:[.-]\d+)*|[ivxlcdm]+)[{_DASHES}\s]*$", re.I
)


def _furniture_key(line: str) -> str:
    s = line.strip()
    return "#" if _PAGE_NO_RE.match(s) else re.sub(r"\d+", "#", s)


def _zone(lines: list[PdfLine]) -> set[int]:
    filled = [i for i, ln in enumerate(lines) if ln.text.strip()]
    return set(filled[:_ZONE] + filled[-_ZONE:])


def _furniture(pages: list[list[PdfLine]], zones: list[set[int]]) -> list[str]:
    """The keys of the lines among the pages' top or bottom _ZONE lines whose text (digits
    aside; any page number counts as one) recurs there on at least half the pages, and on 3
    or more — in reading order."""
    counts: Counter[str] = Counter()
    for p, z in zip(pages, zones, strict=True):
        counts.update(list(dict.fromkeys(_furniture_key(p[i].text) for i in sorted(z))))
    need = max(3, (len(pages) + 1) // 2)
    return [k for k, n in counts.items() if n >= need]


_MIN_LOOSE = 20  # chars; a shorter running-head piece is dropped only in the zones


def _strip_furniture(pages: list[list[PdfLine]]) -> list[list[PdfLine]]:
    """`pages` without running heads and feet (`_furniture`). Elsewhere on a page, a line
    that is a piece of them goes too: the official law PDFs set the two-line foot as one
    line in the middle of an annex's table."""
    zones = [_zone(p) for p in pages]
    keys = _furniture(pages, zones)
    known, blob = set(keys), " ".join(keys)

    def furniture(text: str, in_zone: bool) -> bool:
        key = _furniture_key(text)
        if in_zone and key in known:
            return True
        return key != "#" and len(key) >= _MIN_LOOSE and key in blob

    return [
        [ln for i, ln in enumerate(p) if not furniture(ln.text, i in z)]
        for p, z in zip(pages, zones, strict=True)
    ]


_BROKEN_WORD_RE = re.compile(r"[a-zäöüß]-$")
_CONTINUES_RE = re.compile(_NO_JOIN + r"[a-zäöüß]")


def _join_pages(pages: list[str]) -> str:
    """The pages' texts, blank-line separated; a word hyphenated across a page break
    ("kontaminier-" / "ten") is rejoined."""
    parts: list[str] = []
    for page in (p.strip() for p in pages):
        if parts and _BROKEN_WORD_RE.search(parts[-1]) and _CONTINUES_RE.match(page):
            parts[-1] = parts[-1][:-1] + page
        elif page:
            parts.append(page)
    return "\n\n".join(parts)


# --- headings of a non-statute from the font -----------------------------------

_SIZE_STEP = 0.5  # pt above the body text's glyph height
_BOLD_STEP = 200  # font weight above the body text's
_TOC_RE = re.compile(r"(?:\.\s?){4,}|…{2,}")
_NUMBERED_RE = re.compile(r"^(\d+(?:\.\d+)*)\.?\s+\S")
_MAX_HEADING = 200
_MAX_WORDS = 12  # an unnumbered line with more words is text in a larger font
_BULLETS = "·•▪-–*\uf0b7"


def _body_style(lines: Iterable[PdfLine]) -> tuple[float, int]:
    """(size, weight) of most of the text."""
    sizes: Counter[float] = Counter()
    weights: Counter[int] = Counter()
    for ln in lines:
        sizes[ln.size] += len(ln.text)
        weights[ln.weight] += len(ln.text)
    return _mode(sizes.elements(), 0.0), _mode(weights.elements(), 0)


def _stands_out(ln: PdfLine, body: tuple[float, int]) -> bool:
    """Larger than the body text, or bold and numbered (an unnumbered bold line is mostly
    a table's column head)."""
    size, weight = body
    if ln.size and size and ln.size >= size + _SIZE_STEP:
        return True
    bold = bool(ln.weight and weight) and ln.weight >= weight + _BOLD_STEP
    return bold and bool(_NUMBERED_RE.match(ln.text.strip()))


def _is_font_heading(ln: PdfLine, body: tuple[float, int]) -> bool:
    """A short title line in a larger or bolder font: no sentence or list tail, no
    contents-page dot leaders, not a bullet or a lower-case continuation, and unless
    numbered at most _MAX_WORDS words."""
    s = ln.text.strip()
    if not 3 <= len(s) <= 160 or not any(c.isalpha() for c in s) or s[0] in _BULLETS:
        return False
    if s[0].islower() or (len(s.split()) > _MAX_WORDS and not _NUMBERED_RE.match(s)):
        return False
    return _stands_out(ln, body) and not s.endswith((".", ",", ";", ":")) and not _TOC_RE.search(s)


def _heading_prefix(title: str) -> str:
    """ "##" for "1." / "5.0" / an unnumbered title, "###" for "3.1.", "####" deeper."""
    m = _NUMBERED_RE.match(title)
    parts = m[1].split(".") if m else ["1"]
    while len(parts) > 1 and parts[-1] == "0":
        parts.pop()
    return "#" * min(len(parts) + 1, 4)


def _paragraph_goes_on(lines: list[PdfLine], i: int) -> bool:
    """`lines[i]` wraps onto a lower-case line of its own style: a paragraph in a larger
    font, not a heading."""
    nxt = lines[i + 1] if i + 1 < len(lines) else None
    if nxt is None or (nxt.size, nxt.weight) != (lines[i].size, lines[i].weight):
        return False
    return nxt.text.strip()[:1].islower()


def _mark_headings(lines: list[PdfLine], body: tuple[float, int]) -> list[str]:
    """The lines' texts, heading lines prefixed; a heading wrapped onto lines of the same
    style becomes one heading line (unless the next line starts a numbered one)."""
    out: list[str] = []
    prev: PdfLine | None = None
    for i, ln in enumerate(lines):
        if not _is_font_heading(ln, body) or _paragraph_goes_on(lines, i):
            out.append(ln.text)
            prev = None
            continue
        s = ln.text.strip()
        wraps = prev is not None and (prev.size, prev.weight) == (ln.size, ln.weight)
        if wraps and not _NUMBERED_RE.match(s) and len(out[-1]) + len(s) < _MAX_HEADING:
            out[-1] = f"{out[-1]} {s}"
        else:
            out.append(f"{_heading_prefix(s)} {s}")
        prev = ln
    return out


def _font_heading_pages(pages: list[list[PdfLine]]) -> list[str]:
    body = _body_style(ln for p in pages for ln in p)
    return ["\n".join(_mark_headings(p, body)) for p in pages]


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
