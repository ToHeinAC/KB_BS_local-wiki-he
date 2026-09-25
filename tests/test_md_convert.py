"""Tests for md_convert.py — non-Markdown → Markdown conversion."""

import io

import pytest
from PIL import Image

import md_convert

# --- is_convertible --------------------------------------------------------


@pytest.mark.parametrize("name", ["a.pdf", "A.PDF", "b.docx", "c.png", "d.JPG", "e.tiff"])
def test_is_convertible_true(name):
    assert md_convert.is_convertible(name) is True


@pytest.mark.parametrize("name", ["a.md", "b.txt", "c.html", "d", "e.csv"])
def test_is_convertible_false(name):
    assert md_convert.is_convertible(name) is False


# --- DOCX (deterministic, no LLM) ------------------------------------------


def _make_docx() -> bytes:
    from docx import Document

    doc = Document()
    doc.add_heading("Title", level=1)
    doc.add_heading("Section", level=2)
    doc.add_paragraph("Body text.")
    table = doc.add_table(rows=2, cols=2)
    table.rows[0].cells[0].text = "A"
    table.rows[0].cells[1].text = "B"
    table.rows[1].cells[0].text = "1"
    table.rows[1].cells[1].text = "2"
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def test_extract_docx_headings_and_paragraph():
    md = md_convert.extract_docx_text(_make_docx())
    assert "# Title" in md
    assert "## Section" in md
    assert "Body text." in md


def test_extract_docx_table():
    md = md_convert.extract_docx_text(_make_docx())
    assert "| A | B |" in md
    assert "| --- | --- |" in md
    assert "| 1 | 2 |" in md


def test_convert_to_markdown_docx_routes_to_extractor():
    md = md_convert.convert_to_markdown(_make_docx(), "doc.docx")
    assert "# Title" in md


# --- PDF routing (monkeypatched, no real model / no pypdfium2) --------------


def test_pdf_routing_text_and_image(monkeypatch):
    pages = [("text", "raw text page"), ("image", object())]
    monkeypatch.setattr(md_convert, "_pdf_page_count", lambda b: len(pages))
    monkeypatch.setattr(md_convert, "iter_pdf_pages", lambda b, dpi=md_convert.PDF_DPI: iter(pages))
    monkeypatch.setattr(md_convert, "rewrite_text", lambda t: f"REWRITE[{t}]")
    monkeypatch.setattr(md_convert, "convert_image", lambda img: "OCR")

    md = md_convert.convert_to_markdown(b"fake-pdf", "x.pdf")
    assert md == "REWRITE[raw text page]\n\nOCR"


def test_pdf_progress_callback(monkeypatch):
    pages = [("text", "a"), ("text", "b")]
    monkeypatch.setattr(md_convert, "_pdf_page_count", lambda b: len(pages))
    monkeypatch.setattr(md_convert, "iter_pdf_pages", lambda b, dpi=md_convert.PDF_DPI: iter(pages))
    monkeypatch.setattr(md_convert, "rewrite_text", lambda t: t)
    calls = []
    md_convert.convert_to_markdown(
        b"x", "x.pdf", on_progress=lambda d, t, _label: calls.append((d, t))
    )
    assert calls[-1] == (2, 2)  # final "Done" tick


# --- image OCR routing ------------------------------------------------------


def test_image_routes_to_convert_image(monkeypatch):
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (2, 2), "white").save(buf, format="PNG")
    monkeypatch.setattr(md_convert, "convert_image", lambda img: "IMG-OCR")
    md = md_convert.convert_to_markdown(buf.getvalue(), "scan.png")
    assert md == "IMG-OCR"


# --- LLM wrappers select the right prompt ----------------------------------


def test_convert_image_uses_deepseek_prompt(monkeypatch):
    seen = {}
    monkeypatch.setattr(md_convert, "_image_to_base64", lambda img: "b64")
    monkeypatch.setattr(
        md_convert.ollama_client,
        "ocr",
        lambda model, prompt, img_b64: seen.update(model=model, prompt=prompt) or "ok",
    )
    md_convert.convert_image(Image.new("RGB", (1, 1)), model_id="deepseek-ocr:3b")
    assert seen["prompt"] == md_convert.OCR_DEEPSEEK_PROMPT


def test_convert_image_uses_system_prompt_for_non_deepseek(monkeypatch):
    seen = {}
    monkeypatch.setattr(md_convert, "_image_to_base64", lambda img: "b64")
    monkeypatch.setattr(
        md_convert.ollama_client,
        "ocr",
        lambda model, prompt, img_b64: seen.update(prompt=prompt) or "ok",
    )
    md_convert.convert_image(Image.new("RGB", (1, 1)), model_id="some-vision:1b")
    assert md_convert.OCR_SYSTEM_PROMPT in seen["prompt"]


def test_unsupported_extension_raises():
    with pytest.raises(ValueError, match="Unsupported file type"):
        md_convert.convert_to_markdown(b"x", "file.csv")


# --- real PDF parsing (pypdfium2, no model) -----------------------------------

_PDF_TEXT = "Paragraph one of a digital page with enough extractable characters."


def _pdf(pages: list[bytes]) -> bytes:
    """A minimal PDF: one page per content stream, Helvetica for text pages."""
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>", b""]
    kids = []
    for stream in pages:
        content_no = len(objs) + 2
        kids.append(len(objs) + 1)
        objs.append(
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Resources << /Font << /F1 << /Type /Font /Subtype /Type1 "
            b"/BaseFont /Helvetica >> >> >> " + f"/Contents {content_no} 0 R >>".encode()
        )
        objs.append(f"<< /Length {len(stream)} >>\nstream\n".encode() + stream + b"\nendstream")
    refs = " ".join(f"{k} 0 R" for k in kids)
    objs[1] = f"<< /Type /Pages /Kids [{refs}] /Count {len(kids)} >>".encode()
    out, offsets = b"%PDF-1.4\n", []
    for i, body in enumerate(objs, 1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    out += b"".join(f"{o:010d} 00000 n \n".encode() for o in offsets)
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF".encode()
    return out


def test_pdf_pages_route_text_and_image():
    text_page = f"BT /F1 12 Tf 72 700 Td ({_PDF_TEXT}) Tj ET".encode()
    blank_page = b"0 0 m 10 10 l S"  # vector only: no extractable text
    pdf = _pdf([text_page, blank_page])
    assert md_convert._pdf_page_count(pdf) == 2
    pages = list(md_convert.iter_pdf_pages(pdf, dpi=36))
    assert pages[0] == ("text", _PDF_TEXT)
    assert pages[1][0] == "image"
    assert md_convert._image_to_base64(pages[1][1])  # rendered bitmap encodes as JPEG


def test_rewrite_text_prefixes_the_prompt(monkeypatch):
    seen = {}
    monkeypatch.setattr(
        md_convert.ollama_client,
        "rewrite",
        lambda model, prompt: seen.update(model=model, prompt=prompt) or "md",
    )
    assert md_convert.rewrite_text("body", model_id="m") == "md"
    assert seen["prompt"].endswith("body")
    assert seen["model"] == "m"


def test_docx_styles_and_empty_paragraphs():
    from docx import Document

    doc = Document()
    doc.add_heading("Sub", level=3)
    doc.add_paragraph("item", style="List Bullet")
    doc.add_paragraph("step", style="List Number")
    doc.add_paragraph("   ")
    buf = io.BytesIO()
    doc.save(buf)
    assert md_convert.extract_docx_text(buf.getvalue()) == "### Sub\n\n- item\n\n1. step"


def test_docx_and_image_report_progress(monkeypatch):
    from PIL import Image

    monkeypatch.setattr(md_convert, "convert_image", lambda img: "OCR")
    monkeypatch.setattr(md_convert.ollama_client, "unload", lambda m: None)
    calls = []
    md_convert.convert_to_markdown(_make_docx(), "a.docx", lambda d, t, label: calls.append(label))
    buf = io.BytesIO()
    Image.new("RGB", (2, 2)).save(buf, format="PNG")
    md_convert.convert_to_markdown(buf.getvalue(), "a.png", lambda d, t, label: calls.append(label))
    assert calls == ["Converting DOCX", "Done", "OCR image", "Done"]
