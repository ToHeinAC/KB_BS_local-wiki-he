"""Level-by-level reading in code (ideas/deep-chat-levels.md): definition reads, reverse
references, the level plan and the coverage gate."""

import chunker
import run_memory
import tools

# Excerpts of public law (gesetze-im-internet.de), in the converted markdown shape.
_ACT = """Gesetz zum Schutz vor der schädlichen Wirkung ionisierender Strahlung
# Strahlenschutzgesetz (StrlSchG)

## § 2 Exposition; Expositionssituationen
(1) Exposition ist die Einwirkung ionisierender Strahlung auf den menschlichen Körper.

## § 5 Sonstige Begriffsbestimmungen
(6) Bauprodukte: Baustoffe, Bausätze, Bauteile und Anlagen, die eingebaut werden.
(11) Effektive Dosis: Das gewichtete Mittel von Organ-Äquivalentdosen.
(22) Materialien: Stoffe, die natürlich vorkommende Radionuklide enthalten.
(32) Rückstände: Materialien, die in den in Anlage 1 genannten Prozessen anfallen.

## § 61 Anfall und Lagerung überwachungsbedürftiger Rückstände
(1) Wer Rückstände anfallen lässt, hat sie zu lagern.

## § 62 Entlassung von Rückständen aus der Überwachung
(1) Der nach § 61 Verpflichtete hat die Verwertung der Rückstände anzumelden.
(2) Die Behörde entlässt Rückstände, wenn der Schutz vor Exposition sichergestellt ist.
(3) Maßstab ist eine effektive Dosis von 1 Millisievert im Kalenderjahr.
Sollen die Rückstände als Bauprodukt verwertet werden, gelten die §§ 133 bis 135.

## § 63 Anzeige
(1) Rückstände sind anzuzeigen.
"""

_ORDINANCE = """Verordnung zum Schutz vor der schädlichen Wirkung ionisierender Strahlung
# Strahlenschutzverordnung (StrlSchV)

## § 1 Begriffsbestimmungen
(1) Ableitung: Abgabe radioaktiver Stoffe auf hierfür vorgesehenen Wegen.

## § 29 Entlassung überwachungsbedürftiger Rückstände
(1) Bei einer beabsichtigten Verwertung der Rückstände legt der Antragsteller Unterlagen vor.
(3) Die Behörde stellt zum Dosiskriterium nach § 62 Absatz 3 Satz 1 des
Strahlenschutzgesetzes das Einvernehmen her.

## § 40 Sonstiges
(1) Nichts zu Rückständen.
"""

_Q = "Wie können Rückstände entlassen werden?"


def _laws() -> None:
    for name, text in (("StrlSchG.md", _ACT), ("StrlSchV.md", _ORDINANCE)):
        (tools.db_context.raw_dir() / name).write_text(text, encoding="utf-8")
        chunker.write_chunks(name, chunker.split(text))


def _run() -> run_memory.RunMemory:
    _laws()
    mem = run_memory.begin_run(_Q)
    for q in ("a", "b", "c"):
        mem.mark_search(f"raw_search:{q}")
    return mem


# --- definition reads ---


def test_a_paragraph_of_a_definitions_section_is_read_on_its_own(wiki_dir):
    mem = _run()
    out = tools.raw_read.invoke({"filenames": ["StrlSchG.md § 5 Abs. 32"]})
    assert out.startswith("## Raw file: StrlSchG.md § 5 Abs. 32\n")
    assert "(32) Rückstände: Materialien" in out
    assert "Bauprodukte" not in out  # not the whole § 5
    assert "StrlSchG.md Anlage 1" in out  # its own references still get a footer
    assert ("StrlSchG.md § 5 Abs. 32", out.split("\n")[2]) in mem.ledger


def test_a_read_definition_counts_as_read_for_the_gate_and_an_unread_one_does_not(wiki_dir):
    mem = _run()
    tools.raw_read.invoke({"filenames": ["StrlSchG.md § 5 Abs. 32", "StrlSchV.md § 29"]})
    read = "x " * 200 + "[Source: StrlSchG.md § 5 Abs. 32] [Source: StrlSchV.md § 29]"
    assert not tools._submit_chat_impl(read).startswith("REJECTED: you cite")
    unread = read + " [Source: StrlSchG.md § 5 Abs. 6]"
    out = tools._submit_chat_impl(unread)
    assert out.startswith("REJECTED: you cite § 5 Abs. 6 of StrlSchG.md")
    assert mem.unread_due == ["StrlSchG.md § 5 Abs. 6"]


def test_two_definitions_of_one_section_are_two_citations(wiki_dir):
    _laws()
    a = tools.ref_key("StrlSchG.md § 5 Abs. 32")
    assert a == ("StrlSchG.md", "§ 5 Abs. 32")
    assert a != tools.ref_key("StrlSchG.md § 5 Abs. 6")
    assert tools.ref_key("StrlSchG.md § 5 (32)") == a


# --- the level plan ---


def _hits(*scored: tuple[str, float]) -> str:
    return "## Raw query: q\n" + "".join(
        f"[Raw hit {i}]\nfile: {ref}\nchunk_id: c{i}\nscore: {score}  matched: x\n---\n"
        for i, (ref, score) in enumerate(scored, 1)
    )


_HITS = _hits(
    ("StrlSchG.md § 62", 0.9),
    ("StrlSchG.md § 62 (Teil 2)", 0.85),
    ("StrlSchG.md § 63", 0.8),
    ("StrlSchV.md § 40", 0.3),
)


def test_the_core_is_the_top_two_distinct_sections_of_the_searches(wiki_dir):
    _laws()
    assert tools.core_refs([_HITS]) == ["StrlSchG.md § 62", "StrlSchG.md § 63"]


def test_a_second_section_scored_far_below_the_best_hit_is_not_core(wiki_dir):
    _laws()
    far = _hits(("StrlSchG.md § 62", 0.9), ("StrlSchG.md § 63", 0.4))
    other = _hits(("StrlSchV.md § 29", 0.95))  # a later search compares only to its own best
    assert tools.core_refs([far, other]) == ["StrlSchG.md § 62"]


def test_sections_of_other_laws_that_cite_a_core_section_are_found(wiki_dir):
    mem = _run()
    assert tools.citing_sections(mem, "StrlSchG.md § 62") == ["StrlSchV.md § 29"]
    assert tools.citing_sections(mem, "StrlSchG.md § 63") == []


def test_code_reads_the_core_then_its_terms_and_citing_sections_then_their_terms(wiki_dir):
    mem = _run()
    levels = tools.level_reads(_Q, [_HITS])
    assert [refs for refs, _ in levels] == [
        ["StrlSchG.md § 62", "StrlSchG.md § 63"],
        [
            "StrlSchG.md § 5 Abs. 32",  # the question names it
            "StrlSchG.md § 2 Abs. 1",
            "StrlSchG.md § 5 Abs. 11",
            "StrlSchG.md § 5 Abs. 6",
            "StrlSchV.md § 29",
        ],
        ["StrlSchG.md § 5 Abs. 22"],  # Materialien, inside the Rückstände definition
    ]
    assert levels[0][1].startswith("[level 1")
    assert "level by level" in levels[0][1]  # how to answer comes with the levels read
    assert mem.core_refs == ["StrlSchG.md § 62", "StrlSchG.md § 63"]
    assert mem.term_refs == ["StrlSchG.md § 5 Abs. 32"]  # and the terms the question names
    assert mem.levels[("StrlSchV.md", "§ 29")] == 2
    assert mem.levels[("StrlSchG.md", "§ 5 Abs. 22")] == 3


def test_the_core_keeps_every_paragraphs_rule_not_only_the_words_of_the_question(wiki_dir):
    # Abs. 3's 1 mSv criterion shares no word with the question; it still is the rule.
    mem = _run()
    tools.level_reads(_Q, [_HITS])
    quotes = [s for ref, s in mem.ledger if ref == "StrlSchG.md § 62"]
    assert any("1 Millisievert" in s for s in quotes)


def test_a_core_definitions_section_is_not_read_again_as_its_own_terms(wiki_dir):
    mem = _run()
    hits = "## Raw query: q\n[Raw hit 1]\nfile: StrlSchG.md § 5\n---\n"
    levels = tools.level_reads("Was sind Rückstände?", [hits])
    assert mem.core_refs == ["StrlSchG.md § 5"]
    assert not any(r.startswith("StrlSchG.md § 5 Abs.") for refs, _ in levels[1:] for r in refs)


def test_no_level_reads_without_a_section_hit(wiki_dir):
    _run()
    assert tools.level_reads(_Q, ["## Raw query: q\n(no results)"]) == []


# --- the coverage gate (replaces the word floor) ---


def _covered_answer(*refs: str) -> str:
    body = " ".join(
        f"Satz {i} erklärt die Vorschrift ausführlich. [Source: {r}]" for i, r in enumerate(refs)
    )
    return body + " " + "Erläuterung " * 300


def test_an_answer_must_cite_a_core_section_and_the_terms_the_question_names(wiki_dir):
    _run()
    tools.level_reads(_Q, [_HITS])
    core_only = _covered_answer("StrlSchG.md § 62", "StrlSchG.md § 63")
    out = tools._submit_chat_impl(core_only)
    assert out.startswith("REJECTED: explain the defined terms")
    assert "[Source: StrlSchG.md § 5 Abs. 32]" in out
    term_only = _covered_answer("StrlSchG.md § 5 Abs. 32", "StrlSchV.md § 29")
    out = tools._submit_chat_impl(term_only)
    assert "[Source: StrlSchG.md § 62], [Source: StrlSchG.md § 63]" in out
    # one core section suffices: a top hit can be off the question; the terms the
    # question does not name are offered, not forced
    enough = _covered_answer("StrlSchG.md § 63", "StrlSchG.md § 5 Abs. 32")
    assert tools._submit_chat_impl(enough).startswith("ACCEPTED")


def test_a_named_term_is_required_only_from_the_document_whose_core_the_answer_cites(wiki_dir):
    # a top hit from another document must not force that document's definitions
    mem = run_memory.begin_run(_Q)
    mem.core_refs = ["StrlSchV.md § 29", "StrlSchG.md § 62"]
    mem.term_refs = ["StrlSchG.md § 5 Abs. 32"]
    assert tools._coverage_gap({"StrlSchV.md § 29"}) is None
    out = tools._coverage_gap({"StrlSchG.md § 62"}) or ""
    assert "[Source: StrlSchG.md § 5 Abs. 32]" in out


_MANUAL = """# Pump manual

## Installation
Mount the pump on a level base. Connect the inlet before the outlet.

## Maintenance
Replace the seal every 2000 operating hours. Check the inlet filter monthly.

## Warranty
The warranty covers two years.
"""


def test_levels_on_a_document_without_definitions_read_the_core_and_require_only_it(wiki_dir):
    (tools.db_context.raw_dir() / "manual.md").write_text(_MANUAL, encoding="utf-8")
    chunker.write_chunks("manual.md", chunker.split(_MANUAL))
    mem = run_memory.begin_run("How often is the seal replaced?")
    hits = _hits(("manual.md Maintenance", 0.9), ("manual.md Warranty", 0.2))
    levels = tools.level_reads("How often is the seal replaced?", [hits])
    assert [refs for refs, _ in levels] == [["manual.md Maintenance"]]
    assert (mem.core_refs, mem.term_refs) == (["manual.md Maintenance"], [])


def test_a_terse_answer_is_sent_back_once_to_explain_each_source(wiki_dir):
    _run()
    tools.raw_read.invoke({"filenames": ["StrlSchG.md § 62", "StrlSchV.md § 29"]})
    terse = "Kurz. [Source: StrlSchG.md § 62] [Source: StrlSchV.md § 29]"
    assert tools._submit_chat_impl(terse).startswith("REJECTED: the answer is too short")
    assert tools._submit_chat_impl(terse).startswith("ACCEPTED")  # once only: no padding loop


# --- Quick research ---


def test_a_research_report_must_cover_the_levels_and_has_no_word_floor(wiki_dir, monkeypatch):
    monkeypatch.setattr(tools, "MIN_URLS", 1)
    mem = run_memory.begin_run("q")
    mem.core_refs = ["a.md § 1"]
    out = tools._submit_final_impl("T", "Kurz [Source: b.md]")
    assert out.startswith("REJECTED: explain the core section(s)")
    ok = tools._submit_final_impl("T", "Erläuterung " * 50 + "[Source: a.md § 1]")
    assert ok.startswith("ACCEPTED")


def test_citations_of_markdown_heading_sections_count_as_sources(wiki_dir):
    # code's own tags for a heading section carry its title, not a § or #
    (tools.db_context.raw_dir() / "manual.md").write_text(_MANUAL, encoding="utf-8")
    chunker.write_chunks("manual.md", chunker.split(_MANUAL))
    mem = run_memory.begin_run("How is the pump installed and maintained?")
    for q in ("a", "b", "c"):
        mem.mark_search(f"raw_search:{q}")
    tools.raw_read.invoke({"filenames": ["manual.md Installation", "manual.md Maintenance"]})
    answer = _covered_answer("manual.md Installation", "manual.md Maintenance")
    assert tools._submit_chat_impl(answer).startswith("ACCEPTED")


def test_a_section_the_chunks_do_not_hold_is_read_from_its_heading_not_the_file_start(wiki_dir):
    # chunked before plain § headings were recognised: the parts carry no § anchor
    text = "Vorspann " * 2000 + "\n§ 62 Entlassung von Rückständen\n(1) Die Behörde entlässt.\n"
    (tools.db_context.raw_dir() / "old.md").write_text(text, encoding="utf-8")
    chunker.write_chunks("old.md", chunker._split_long(text, "", [], 0, "de"))
    run_memory.begin_run(_Q)
    out = tools.raw_read.invoke({"filenames": ["old.md § 62"]})
    assert "\n§ 62 Entlassung von Rückständen\n(1) Die Behörde entlässt." in out
    assert "(bytes 0-" not in out
