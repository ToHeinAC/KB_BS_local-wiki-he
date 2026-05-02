"""Tests for file_processor.py — text extraction from various formats."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import file_processor


# --- TXT / MD ---

def test_txt_extracts_plain_text(tmp_path):
    f = tmp_path / "doc.txt"
    f.write_text("hello world")
    assert file_processor.extract_text(f) == "hello world"


def test_md_extracts_as_is(tmp_path):
    f = tmp_path / "note.md"
    f.write_text("# Heading\nsome text")
    result = file_processor.extract_text(f)
    assert "# Heading" in result
    assert "some text" in result


# --- HTML ---

def test_htm_treated_as_html(tmp_path):
    f = tmp_path / "page.htm"
    f.write_text("<p>content</p>")
    result = file_processor.extract_text(f)
    assert "content" in result
    assert "<p>" not in result


def test_html_strips_tags(tmp_path):
    f = tmp_path / "page.html"
    f.write_text("<h1>Title</h1><p>Body</p>")
    result = file_processor.extract_text(f)
    assert "<h1>" not in result
    assert "<p>" not in result


def test_html_extracts_only_text(tmp_path):
    f = tmp_path / "page.html"
    f.write_text("<div><span>hello</span> <em>world</em></div>")
    result = file_processor.extract_text(f)
    assert "hello" in result
    assert "world" in result


# --- Error handling ---

def test_unsupported_suffix_raises_value_error(tmp_path):
    f = tmp_path / "file.xyz"
    f.write_bytes(b"data")
    with pytest.raises(ValueError, match="Unsupported"):
        file_processor.extract_text(f)


# --- Truncation ---

def test_truncation_respects_max_chars(tmp_path, monkeypatch):
    monkeypatch.setattr(file_processor, "MAX_CHARS", 10)
    f = tmp_path / "big.txt"
    f.write_text("a" * 100)
    result = file_processor.extract_text(f)
    assert len(result) <= 10


def test_result_len_at_most_max_chars(tmp_path, monkeypatch):
    monkeypatch.setattr(file_processor, "MAX_CHARS", 5)
    f = tmp_path / "long.md"
    f.write_text("x" * 50)
    assert len(file_processor.extract_text(f)) == 5


# --- Edge cases ---

def test_empty_txt_returns_empty_string(tmp_path):
    f = tmp_path / "empty.txt"
    f.write_text("")
    assert file_processor.extract_text(f) == ""


def test_non_utf8_handled_with_replace(tmp_path):
    f = tmp_path / "bad.txt"
    f.write_bytes(b"hello \xff world")
    result = file_processor.extract_text(f)
    assert isinstance(result, str)
    assert "hello" in result


# --- PDF (mocked) ---

def test_pdf_extracts_text(tmp_path):
    f = tmp_path / "doc.pdf"
    f.write_bytes(b"%PDF fake")
    mock_page = MagicMock()
    mock_page.extract_text.return_value = "pdf text"
    mock_reader = MagicMock()
    mock_reader.pages = [mock_page]
    with patch("pypdf.PdfReader", return_value=mock_reader):
        result = file_processor.extract_text(f)
    assert "pdf text" in result


def test_pdf_multi_page_joins(tmp_path):
    f = tmp_path / "multi.pdf"
    f.write_bytes(b"%PDF fake")
    pages = [MagicMock(), MagicMock()]
    pages[0].extract_text.return_value = "page one"
    pages[1].extract_text.return_value = "page two"
    mock_reader = MagicMock()
    mock_reader.pages = pages
    with patch("pypdf.PdfReader", return_value=mock_reader):
        result = file_processor.extract_text(f)
    assert "page one" in result
    assert "page two" in result


# --- DOCX (mocked) ---

def test_docx_extracts_paragraphs(tmp_path):
    f = tmp_path / "doc.docx"
    f.write_bytes(b"PK fake")
    para = MagicMock()
    para.text = "paragraph text"
    mock_doc = MagicMock()
    mock_doc.paragraphs = [para]
    with patch("docx.Document", return_value=mock_doc):
        result = file_processor.extract_text(f)
    assert "paragraph text" in result


def test_docx_multi_para_joins(tmp_path):
    f = tmp_path / "multi.docx"
    f.write_bytes(b"PK fake")
    paras = [MagicMock(), MagicMock()]
    paras[0].text = "first"
    paras[1].text = "second"
    mock_doc = MagicMock()
    mock_doc.paragraphs = paras
    with patch("docx.Document", return_value=mock_doc):
        result = file_processor.extract_text(f)
    assert "first" in result
    assert "second" in result


# --- Return type ---

def test_extract_text_always_returns_str(tmp_path):
    f = tmp_path / "t.txt"
    f.write_text("data")
    assert isinstance(file_processor.extract_text(f), str)


# --- Large file truncation detail ---

def test_large_file_content_after_max_absent(tmp_path, monkeypatch):
    monkeypatch.setattr(file_processor, "MAX_CHARS", 5)
    f = tmp_path / "large.txt"
    f.write_text("AAAAA" + "BBBBB")
    result = file_processor.extract_text(f)
    assert "B" not in result
