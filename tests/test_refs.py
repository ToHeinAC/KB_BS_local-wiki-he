"""References inside originals ("nach § 12 der VerordnungB"), resolved in code (src/refs.py)."""

import refs

FILES = {"verordnungb": "VerordnungB.md", "richtliniec": "RichtlinieC.md"}
ANCHORS = {
    "GesetzA.md": {"§ 7", "§ 8"},
    "VerordnungB.md": {"§ 12"},
    "RichtlinieC.md": {"Anlage 3"},
}


def _resolve(name: str) -> str | None:
    return FILES.get(name.casefold())


def _has(file: str, anchor: str) -> bool:
    return anchor in ANCHORS.get(file, set())


def _find(text: str, self_anchor: str | None = None) -> list[refs.Ref]:
    return refs.find_refs(text, "GesetzA.md", self_anchor, _resolve, _has)


def test_a_reference_naming_another_work_resolves_to_that_file():
    (ref,) = _find("Die Pflichten richten sich nach § 12 der VerordnungB.")
    assert (ref.target, ref.anchor, ref.kind, ref.found) == (
        "VerordnungB.md",
        "§ 12",
        "cross",
        True,
    )


def test_an_annex_reference_resolves_like_a_section():
    (ref,) = _find("Die Werte stehen in Anlage 3 der RichtlinieC.")
    assert (ref.target, ref.anchor, ref.kind) == ("RichtlinieC.md", "Anlage 3", "cross")


def test_a_bare_section_is_a_same_file_reference_and_the_own_section_is_skipped():
    found = _find("Abweichend von § 8 Abs. 2 Satz 1 gilt § 7 nicht.", self_anchor="§ 7")
    assert [(r.target, r.anchor, r.kind) for r in found] == [("GesetzA.md", "§ 8", "same")]


def test_a_missing_anchor_is_flagged_never_guessed():
    (ref,) = _find("Siehe § 99 der VerordnungB.")
    assert ref.kind == "cross"
    assert ref.found is False


def test_an_unknown_law_is_out_of_scope_and_a_plain_noun_is_not_a_law():
    out = _find("Nach § 2 AtG und § 3 des Atomgesetzes gilt § 8 der Behörde.")
    assert [(r.work, r.kind) for r in out] == [
        ("AtG", "out_of_scope"),
        ("Atomgesetzes", "out_of_scope"),
        ("", "same"),
    ]


def test_ranges_expand_and_are_capped():
    out = _find("Die §§ 7 bis 8 sowie §§ 1 bis 40 gelten.")
    anchors = [r.anchor for r in out]
    assert anchors[:2] == ["§ 7", "§ 8"]
    assert len(out) <= refs.MAX_REFS


def test_duplicates_are_listed_once_in_order_of_first_mention():
    out = _find("§ 12 der VerordnungB, § 8, und erneut § 12 der VerordnungB.")
    assert [r.anchor for r in out] == ["§ 12", "§ 8"]


def test_section_numbers_tolerate_letter_suffixes_and_no_space():
    out = _find("Vgl. §8 und § 7a.")
    assert [r.anchor for r in out] == ["§ 8", "§ 7a"]


def test_every_spelling_of_annex_and_article_is_a_reference():
    out = _find("Nach Art. 5, Artikel 6, Anlagen 2 und Anlage 3 der RichtlinieC.")
    assert [r.anchor for r in out] == ["Artikel 5", "Artikel 6", "Anlage 2", "Anlage 3"]
