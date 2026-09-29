"""Pure classification model: levels, shard ids, high-water mark, upload plan."""

import pytest

import classification as cl
import db_context
import tools


def test_levels_are_ordered_normal_confidential_strict():
    assert cl.LEVELS == ("normal", "confidential", "strict")
    assert [cl.level_index(n) for n in cl.LEVELS] == [0, 1, 2]


def test_normal_shard_is_the_bare_db_name():
    assert cl.shard_id("KI", 0) == "KI"
    assert cl.shard_id("KI", 2) == "KI@strict"
    assert cl.parse_shard("KI") == ("KI", 0)
    assert cl.parse_shard("KI@confidential") == ("KI", 1)


@pytest.mark.parametrize("bad", ["KI@normal", "KI@secret", "@strict", "KI@", "KI@strict@strict"])
def test_non_canonical_shard_ids_are_rejected(bad):
    with pytest.raises(ValueError, match="Invalid shard id"):
        cl.parse_shard(bad)


def test_shard_id_rejects_an_unknown_level():
    with pytest.raises(ValueError, match="Unknown classification level"):
        cl.shard_id("KI", 3)


def test_labels_are_english_and_normal_stays_plain():
    assert cl.label("KI") == "KI"
    assert cl.label("KI@strict") == "KI · Strictly confidential"
    assert cl.level_label(1) == "Confidential"


def test_high_water_is_the_highest_level_read():
    assert cl.high_water([]) == 0
    assert cl.high_water(["KI", "KI@strict", "Inv@confidential"]) == 2


def test_upload_plan_groups_by_level_and_reports_gaps():
    rows = {"a.pdf": "normal", "b.pdf": "strict", "c.pdf": None, "d.pdf": "confidential"}
    plan = cl.plan_upload(rows, max_level=1)
    assert plan.by_level == {0: ["a.pdf"], 1: ["d.pdf"]}
    assert plan.missing == ["c.pdf"]
    assert plan.denied == ["b.pdf"]
    assert not plan.ok


def test_upload_plan_accepts_display_labels_and_is_ok_when_complete():
    plan = cl.plan_upload({"a.pdf": "Strictly confidential"}, max_level=2)
    assert plan.by_level == {2: ["a.pdf"]}
    assert plan.ok


def test_the_level_separator_survives_every_citation_regex():
    """`#`/`§` mark citation sections; a shard id must pass through them intact."""
    ref = "KI@strict::StrlSchG.md"
    assert tools._CITE_SECTION_RE.sub("", ref) == ref
    assert cl.LEVEL_SEP not in "#§"
    assert db_context.SCOPE_SEP not in cl.LEVEL_SEP
    assert not db_context.is_valid_db_name("KI@strict")
