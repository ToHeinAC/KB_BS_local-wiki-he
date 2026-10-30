"""Tests for definitions.py — the defined terms of a law, found and matched in code."""

import definitions

# Excerpts of public law (StrlSchG, gesetze-im-internet.de), in the converted markdown shape.
_LAW = """# Strahlenschutzgesetz

## § 2 Exposition; Expositionssituationen; Expositionskategorien
(1) Exposition ist die Einwirkung ionisierender Strahlung auf den menschlichen Körper.
(2) Geplante Expositionssituation ist eine Expositionssituation aus Tätigkeiten.
(5) Folgende Expositionskategorien werden unterschieden: 1.
Exposition der Bevölkerung,

## § 3 Begriff der radioaktiven Stoffe
(1) Radioaktive Stoffe (Kernbrennstoffe) im Sinne dieses Gesetzes sind alle Stoffe, die …

## § 5 Sonstige Begriffsbestimmungen
(1) Abfälle: Alle Stoffe, die Abfälle im Sinne des Kreislaufwirtschaftsgesetzes sind.
(6) Bauprodukte: Baustoffe, Bausätze, Bauteile und Anlagen, die eingebaut werden.
(7) Beruflich exponierte Person: Eine Person, die eine berufliche Exposition erhält, die 1.
eine effektive Dosis von 1 Millisievert im Kalenderjahr überschreitet,

2.
eine Organ-Äquivalentdosis der Augenlinse von 15 Millisievert im Kalenderjahr überschreitet.

(11) Effektive Dosis: Das gewichtete Mittel von Organ-Äquivalentdosen.
(14) Einzelperson der Bevölkerung: Person ohne berufliche Exposition.
(22) Materialien: Stoffe, die natürlich vorkommende Radionuklide enthalten.
(32) Rückstände: Materialien, die in den in Anlage 1 genannten Prozessen anfallen.

## § 25 Genehmigungsbedürftige Beschäftigung
(2) Dem Genehmigungsantrag sind die erforderlichen Unterlagen beizufügen.

## § 29 Voraussetzungen
(1) Der Antragsteller legt vor: 1.
eine Erklärung,
"""

_SECTION_62 = (
    "(2) Die zuständige Behörde entlässt überwachungsbedürftige Rückstände aus der "
    "Überwachung, wenn der Schutz der Bevölkerung vor Expositionen sichergestellt ist, die "
    "Körperdosis die Werte für die Einstufung als beruflich exponierte Person nicht "
    "überschreiten kann und keine Bedenken gegen die abfallrechtliche Zulässigkeit bestehen. "
    "(3) Richtwert für die Exposition von Einzelpersonen der Bevölkerung ist eine effektive "
    "Dosis von 1 Millisievert. Sollen die Rückstände als Bauprodukt verwertet werden, gelten "
    "die §§ 133 bis 135. Die Rückständen sind anzumelden."
)


def _terms(defs: list[definitions.Definition]) -> list[str]:
    return [d.term for d in defs]


def test_a_definitions_section_yields_each_numbered_term_with_its_verbatim_paragraph():
    defs = definitions.register(_LAW)
    by_term = {d.term: d for d in defs}
    d = by_term["Rückstände"]
    assert (d.anchor, d.number, d.section) == ("§ 5", "32", "§ 5 Abs. 32")
    assert (
        d.text
        == "(32) Rückstände: Materialien, die in den in Anlage 1 genannten Prozessen anfallen."
    )
    # A numbered list inside a definition stays with it.
    assert by_term["Beruflich exponierte Person"].text.endswith(
        "15 Millisievert im Kalenderjahr überschreitet."
    )


def test_x_ist_definitions_count_where_the_heading_names_the_term_or_says_begriff():
    terms = _terms(definitions.register(_LAW))
    assert {"Exposition", "Geplante Expositionssituation", "Radioaktive Stoffe"} <= set(terms)


def test_ordinary_paragraphs_are_no_definitions():
    terms = _terms(definitions.register(_LAW))
    # "werden unterschieden:" outside a Begriff section, an "X sind" duty, a list intro.
    assert "Folgende Expositionskategorien werden unterschieden" not in terms
    assert "Dem Genehmigungsantrag" not in terms
    assert "Der Antragsteller legt vor" not in terms


def test_a_text_uses_the_defined_terms_it_names_in_any_inflection():
    used = _terms(definitions.used_in(_SECTION_62, definitions.register(_LAW)))
    assert set(used) == {
        "Rückstände",
        "Exposition",
        "Beruflich exponierte Person",
        "Effektive Dosis",
        "Einzelperson der Bevölkerung",
        "Bauprodukte",
    }


def test_a_term_inside_a_longer_word_is_not_used():
    # "abfallrechtliche" is no use of "Abfälle", "Expositionssituation" none of "Exposition".
    defs = definitions.register(_LAW)
    assert definitions.used_in("die abfallrechtliche Zulässigkeit", defs) == []
    assert _terms(definitions.used_in("eine Expositionssituation", defs)) == []


def test_terms_the_question_names_come_first_then_the_most_used():
    defs = definitions.register(_LAW)
    used = _terms(
        definitions.used_in(_SECTION_62, defs, query="Wie wird ein Bauprodukt entlassen?")
    )
    assert used[:2] == ["Bauprodukte", "Rückstände"]  # asked; then three mentions


def test_a_paragraph_reference_names_one_definition():
    defs = definitions.register(_LAW)
    assert definitions.find(defs, "§ 5 Abs. 32") == next(d for d in defs if d.term == "Rückstände")
    assert definitions.find(defs, "§5 (32)") is not None
    assert definitions.find(defs, "§ 5 Absatz 32") is not None
    assert definitions.find(defs, "§ 5") is None
    assert definitions.find(defs, "§ 62 Abs. 2") is None
