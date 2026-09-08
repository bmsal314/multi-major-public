"""The designation resolver must survive ASU changing its designations."""

from __future__ import annotations

from backend.asu_catalog import (
    CATEGORIES,
    DesignationVocabulary,
    categorize,
    designations_in,
    matches_wildcard,
    wildcard_patterns_in,
)
from backend.lexicon import Lexicon, _clean_phrase

GENERAL_STUDIES_BLOCK = """University General Studies Requirement - Gold
SOCIAL AND BEHAVIORAL SCIENCES
1) Social and Behavioral Sciences (SOBE): 3 hours
NEEDS: 3.00 HOURS"""


def test_a_document_defines_its_own_designations() -> None:
    vocabulary = DesignationVocabulary.learn(GENERAL_STUDIES_BLOCK.splitlines())
    entry = vocabulary.resolve("SOBE")
    assert entry.name == "Social and Behavioral Sciences"
    assert entry.self_defined is True


def test_a_designation_the_table_has_never_seen_is_still_learned() -> None:
    """The next revision arrives inside a student's PDF, not in this repository."""
    future = """University General Studies Requirement - Platinum
PLANETARY STEWARDSHIP
1) Planetary Stewardship (PLST): 3 hours
NEEDS: 3.00 HOURS"""
    vocabulary = DesignationVocabulary.learn(future.splitlines())
    assert vocabulary.resolve("PLST").name == "Planetary Stewardship"
    assert vocabulary.resolve("PLST").era == "discovered"
    # And it is reported, so a revision announces itself rather than degrading
    # every plan built from that catalog year.
    assert vocabulary.unknown_codes() == ["PLST"]


def test_a_course_title_cannot_redefine_a_designation() -> None:
    """"JMC 201: News Reporting and Writing (L)" must not teach us what L means."""
    lines = [
        "JOURNALISM Major - 120 hours",
        "1) JMC 201: News Reporting and Writing (L): 3 hours, C minimum",
    ]
    vocabulary = DesignationVocabulary.learn(lines)
    assert "L" not in vocabulary.entries
    assert vocabulary.resolve("L").name == "Literacy and Critical Inquiry"


def test_designations_are_read_from_or_groups() -> None:
    assert designations_in("JMC 110: Principles (HUAD OR SB)") == ["HUAD", "SB"]
    assert designations_in("MAT 421: Applied (MATH OR CS)") == ["MATH", "CS"]


def test_wildcard_slots_are_first_class() -> None:
    patterns = wildcard_patterns_in("AEE OR MAE OR MEE 3** Elective")
    assert patterns[0]["subjects"] == ["AEE", "MAE", "MEE"]
    assert patterns[0]["level"] == 3
    assert matches_wildcard("MAE 384", patterns[0]) is True
    assert matches_wildcard("MAE 484", patterns[0]) is False
    assert matches_wildcard("EEE 350", patterns[0]) is False


def test_a_pool_is_recognised_without_the_word_elective() -> None:
    """Dance's Personal Movement Practice never says "elective" and still is one."""
    category = categorize(
        "PERSONAL MOVEMENT PRACTICE Requirement",
        "Upper Division Personal Movement Practice: 9 hours",
        option_count=5,
        required_count=2,
        credits_required=9.0,
    )
    assert category == "elective_constrained"


def test_a_capped_sub_list_is_a_constraint_not_a_requirement() -> None:
    assert (
        categorize(
            "UPPER DIVISION TECHNICAL ELECTIVES",
            "Students may choose no more than one course from the",
        )
        == "constraint"
    )


def test_every_category_is_a_declared_one() -> None:
    """There is no silent fall-through: something unreadable is still placed."""
    assert categorize("MYSTERY BLOCK", "Something we have never seen", credits_required=3.0) in CATEGORIES
    assert categorize("", "") == "unclassified"


def test_the_lexicon_never_stores_a_person() -> None:
    """A stored phrase must be vocabulary, so a name cannot reach the file."""
    assert _clean_phrase("Related Area Course") == "related area course"
    assert _clean_phrase("Personal Movement Practice") == "personal movement practice"
    for private in ("Jordan Rivera", "Jane Doe", "Student ID 1234517910"):
        assert _clean_phrase(private) == ""


def test_the_lexicon_degrades_to_seeds_when_missing(tmp_path) -> None:
    lexicon = Lexicon.load(tmp_path / "absent.json")
    assert lexicon.looks_like_choice_pool("Upper Division Technical Elective") is True


def test_the_lexicon_does_not_turn_a_named_course_into_a_pool() -> None:
    """A stored phrase must not match every ordinary requirement.

    Stripping digits before the DARS suffix reduced "MGT 300: 3 hours, C
    minimum" to "mgt hours c minimum", which then matched any named course and
    made it look like something the student had to choose.
    """
    lexicon = Lexicon.load()
    for named in (
        "MGT 300: 3 hours, C minimum",
        "FIN 361: 3 hours, C minimum",
        "JMC 402: 3 hours, C minimum",
    ):
        assert lexicon.looks_like_choice_pool(named) is False, named
    for pool in (
        "Upper Division Technical Elective: 9 hours",
        "Upper Division Personal Movement Practice: 9 hours",
        "Related Area Course: 6 hours, C minimum",
    ):
        assert lexicon.looks_like_choice_pool(pool) is True, pool


def test_stored_phrases_are_vocabulary_not_fragments() -> None:
    from backend.lexicon import _clean_phrase

    # Course lists reduce to nothing rather than to orphan connectives.
    assert _clean_phrase("JMC 313 OR JMC 345 OR JMC 448: 3 hours, C minimum") == ""
    assert _clean_phrase("MGT 300: 3 hours, C minimum") == ""
    # Real vocabulary survives with its rule text removed.
    assert _clean_phrase("Upper Division Technical Elective: 9 hours - 3 courses") == "technical elective"
