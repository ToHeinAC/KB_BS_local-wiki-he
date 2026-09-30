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
