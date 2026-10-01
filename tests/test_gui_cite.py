"""Numbered citations for the Broadsheet answer view (src/gui_cite.py): pure text logic."""

import gui_cite


def test_tags_become_numbered_superscripts_in_order_of_first_appearance() -> None:
    text, notes = gui_cite.number_citations(
        "A [Source: a.md] and B [Wiki: p.md] and again A [Source: a.md]."
    )
    assert text == (
        'A <sup class="cite" data-n="1">1</sup> and B <sup class="cite" data-n="2">2</sup> '
        'and again A <sup class="cite" data-n="1">1</sup>.'
    )
    assert [(n.n, n.kind, n.file, n.section) for n in notes] == [
        (1, "source", "a.md", ""),
        (2, "wiki", "p.md", ""),
    ]


def test_sections_of_the_same_file_are_distinct_notes() -> None:
    _, notes = gui_cite.number_citations("[Source: law.md §62] x [Source: law.md §63] y")
    assert [(n.n, n.file, n.section, n.label) for n in notes] == [
        (1, "law.md", "§62", "law.md §62"),
        (2, "law.md", "§63", "law.md §63"),
    ]


def test_hash_sections_and_database_qualified_files() -> None:
    _, notes = gui_cite.number_citations("[Source: KI::doc.md #intro]")
    assert (notes[0].file, notes[0].section, notes[0].ref) == ("KI::doc.md", "#intro", "KI::doc.md")


def test_web_urls_are_web_notes() -> None:
    _, notes = gui_cite.number_citations("[Source: https://example.org/x#frag]")
    assert (notes[0].kind, notes[0].file, notes[0].section) == (
        "web",
        "https://example.org/x#frag",
        "",
    )


def test_text_without_tags_and_unknown_brackets_is_untouched() -> None:
    text, notes = gui_cite.number_citations("Plain [Seitentitel] text [1].")
    assert (text, notes) == ("Plain [Seitentitel] text [1].", [])


def test_empty_and_whitespace_tags_are_ignored() -> None:
    text, notes = gui_cite.number_citations("x [Source:   ] y")
    assert (text, notes) == ("x [Source:   ] y", [])


def test_uncited_lists_the_sources_no_inline_tag_points_at() -> None:
    _, notes = gui_cite.number_citations("[Source: a.md §1] [Wiki: p.md]")
    refs = ["a.md", "p.md", "KI::b.md [Teil 2/3]", "c.md"]
    assert gui_cite.uncited(notes, refs) == ["KI::b.md [Teil 2/3]", "c.md"]


def test_an_answer_exports_as_markdown_with_footnotes() -> None:
    md = gui_cite.answer_markdown(
        "What is X?",
        "X is Y [Source: a.pdf §2]. See [Wiki: x.md], [Source: https://e.org/p] "
        "and [Source: a.pdf §2].",
        "Fast answer, KI, 2026-10-01",
    )
    assert md == (
        "# What is X?\n\n"
        "_Fast answer, KI, 2026-10-01_\n\n"
        "X is Y[^1]. See[^2],[^3] and[^1].\n\n"
        "## Sources\n\n"
        "[^1]: a.pdf §2\n"
        "[^2]: x.md (wiki page)\n"
        "[^3]: https://e.org/p\n"
    )


def test_an_answer_without_citations_exports_without_a_sources_list() -> None:
    assert gui_cite.answer_markdown("Q", "Plain.", "m") == "# Q\n\n_m_\n\nPlain.\n"


def test_the_export_is_named_after_the_question() -> None:
    assert gui_cite.export_name("Was ist §5 BImSchG?") == "was-ist-5-bimschg.md"
    assert gui_cite.export_name("???") == "answer.md"


def test_a_tag_with_several_sources_becomes_several_notes() -> None:
    text, notes = gui_cite.number_citations("A [Source: a.md; Source: b.md §2] B.")
    assert text == (
        'A <sup class="cite" data-n="1">1</sup><sup class="cite-sep">,</sup>'
        '<sup class="cite" data-n="2">2</sup> B.'
    )
    assert [(n.n, n.kind, n.file, n.section) for n in notes] == [
        (1, "source", "a.md", ""),
        (2, "source", "b.md", "§2"),
    ]
    _, mixed = gui_cite.number_citations("[Source: a.md, Wiki: p.md]")
    assert [(n.kind, n.file) for n in mixed] == [("source", "a.md"), ("wiki", "p.md")]
    _, one = gui_cite.number_citations("[Source: Report, final.md]")  # a comma inside a name
    assert [n.file for n in one] == ["Report, final.md"]


def test_markdown_escapes_in_cited_names_are_undone() -> None:
    _, notes = gui_cite.number_citations("[Source: JEN\\_KOINNO.md] [Wiki: a\\*b.md]")
    assert [n.file for n in notes] == ["JEN_KOINNO.md", "a*b.md"]


def test_latex_becomes_mathml_and_everything_else_stays() -> None:
    inline = gui_cite.render_math("Planning $\\to$ Tool call \\(x^2\\)")
    assert inline.count('<math xmlns="http://www.w3.org/1998/Math/MathML" display="inline">') == 2
    assert "$" not in inline
    assert "\\to" not in inline
    block = gui_cite.render_math("Energy:\n\n$$E=mc^2$$\n")
    assert 'display="block"' in block
    for plain in (
        "It costs $5 and $10.",  # currency, not math
        "Run `echo ${HOME}` and $x$ stays",  # code untouched; no LaTeX marker in $x$
        "```\n$a^2$\n```",  # fenced code untouched
        "Broken $\\frac{$ stays",  # conversion failure keeps the text
    ):
        assert gui_cite.render_math(plain) == plain
