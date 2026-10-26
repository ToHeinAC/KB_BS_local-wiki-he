"""Tests for md_convert.py — non-Markdown → Markdown conversion."""

import io

import pytest
from PIL import Image

import chunker
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
    monkeypatch.setattr(md_convert, "convert_image", lambda img: "OCR")

    md = md_convert.convert_to_markdown(b"fake-pdf", "x.pdf")
    assert md == "raw text page\n\nOCR"


_LAW_PAGE = (
    "Strahlenschutzgesetz\n"
    "§ 61 Anfall und Lagerung\n"
    "§ 62 Entlassung von Rückständen aus der Überwachung\n"
    "Teil 2\n"
    "Kapitel 1\n"
    "§ 61 Anfall und Lagerung\n"
    "(1) Wer überwachungsbedürftige Rückstände erzeugt, hat dies der zuständigen Behörde "
    "innerhalb eines Monats anzuzeigen.\n"
    "§ 62 Entlassung von Rückständen aus der Überwachung\n"
    "(2) Die Behörde entlässt Rückstände aus der Überwachung auf Antrag nach\n"
    "§ 61 Absatz 2 Satz 2, wenn die Dosis 1 Millisievert nicht überschreitet.\n"
    "§ 63 In der Überwachung verbleibende Rückstände\n"
    "(1) Ist eine Entlassung nicht möglich, so hat der Verpflichtete Art und Masse der "
    "Rückstände anzuzeigen.\n"
    "Anlage 1\n"
    "Rückstände nach § 5"
)


def _words(text: str) -> list[str]:
    return sorted(w for w in text.replace("#", " ").split())


def test_pdf_text_pages_keep_every_word_without_a_model(monkeypatch):
    # A text layer is already exact: a 1.2B rewrite echoed its prompt ("Critical Rule"),
    # translated titles and invented sentences into the stored originals.
    pages = [("text", _LAW_PAGE), ("text", "Seite 2 bleibt wörtlich.")]
    monkeypatch.setattr(md_convert, "_pdf_page_count", lambda b: len(pages))
    monkeypatch.setattr(md_convert, "iter_pdf_pages", lambda b, dpi=md_convert.PDF_DPI: iter(pages))
    monkeypatch.setattr(md_convert.ollama_client, "chat", lambda *a, **k: 1 / 0, raising=False)
    monkeypatch.setattr(md_convert.ollama_client, "unload", lambda m: None)
    md = md_convert.convert_to_markdown(b"fake-pdf", "x.pdf")
    assert _words(md) == _words(_LAW_PAGE + "\n" + "Seite 2 bleibt wörtlich.")


def test_section_lines_with_a_body_become_headings_the_chunker_anchors(monkeypatch):
    md = md_convert._promote_headings(_LAW_PAGE)
    lines = md.splitlines()
    assert lines[1:3] == [  # table of contents: § lines without a body stay plain
        "§ 61 Anfall und Lagerung",
        "§ 62 Entlassung von Rückständen aus der Überwachung",
    ]
    assert {"## Teil 2", "## Kapitel 1", "## Anlage 1"} <= set(lines)
    assert "## § 61 Anfall und Lagerung" in lines
    assert "## § 62 Entlassung von Rückständen aus der Überwachung" in lines
    assert "§ 61 Absatz 2 Satz 2, wenn die Dosis 1 Millisievert nicht überschreitet." in lines
    anchors = {c["anchor"] for c in chunker.split(md)}
    assert {"§ 61", "§ 62", "§ 63"} <= anchors


def test_a_wrapped_table_of_contents_entry_stays_plain():
    # The official PDF wraps long titles: "§ 13 … Aussetzung des" / "Genehmigungsverfahrens"
    # in the contents must not become a second, empty § 13 next to the real one.
    text = (
        "§ 13 Allgemeine Voraussetzungen; Aussetzung des\n"
        "Genehmigungsverfahrens\n"
        "§ 14 Besondere Voraussetzungen\n"
        "§ 13 Allgemeine Voraussetzungen; Aussetzung des\n"
        "Genehmigungsverfahrens\n"
        "(1) Die Genehmigung ist zu erteilen, wenn die Voraussetzungen vorliegen.\n"
        "§ 14 Besondere Voraussetzungen\n"
        "Die Genehmigung setzt voraus, dass die Anwendung gerechtfertigt ist."
    )
    heads = [ln for ln in md_convert._promote_headings(text).splitlines() if ln.startswith("##")]
    assert heads == [
        "## § 13 Allgemeine Voraussetzungen; Aussetzung des",
        "## § 14 Besondere Voraussetzungen",
    ]


def test_page_furniture_does_not_break_the_table_of_contents():
    text = (
        "§ 31a Antrag auf Genehmigung einer Anwendung\n"
        "- Seite 2 von 132 -\n\n"
        "Ein Service des Bundesministerium der Justiz und für Verbraucherschutz\n"
        "§ 31b Prüfung des Antrags\n"
        "§ 31a Antrag auf Genehmigung einer Anwendung\n"
        "Der Antrag ist schriftlich bei der zuständigen Behörde zu stellen."
    )
    heads = [ln for ln in md_convert._promote_headings(text).splitlines() if ln.startswith("##")]
    assert heads == ["## § 31a Antrag auf Genehmigung einer Anwendung"]


def test_pdf_progress_callback(monkeypatch):
    pages = [("text", "a"), ("text", "b")]
    monkeypatch.setattr(md_convert, "_pdf_page_count", lambda b: len(pages))
    monkeypatch.setattr(md_convert, "iter_pdf_pages", lambda b, dpi=md_convert.PDF_DPI: iter(pages))
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
