"""The five load scenarios the rebuild has to get right.

Each test names the defect it pins closed (see ``tests/bugs/BUGS.md``), because
every one of these passed silently before by producing a plan that looked
plausible and was wrong.
"""

from __future__ import annotations

import pytest

from backend.asu_catalog import SCHEDULABLE_CATEGORIES
from backend.cloud.contracts import Preferences
from backend.cloud.engine import build_result
from backend.semester_planner import COUNTED_CLASS_MIN_CREDITS


def plan_for(parsed, **preference_overrides):
    defaults = dict(start_term="Fall 2026", graduation_term="Spring 2030", credits_per_term=15)
    defaults.update(preference_overrides)
    return build_result([parsed], Preferences(**defaults))


def scheduled_terms(plan):
    return [s for s in plan["semesters"] if not s.get("is_unplaced")]


def classes_in(semester):
    return [
        course
        for course in semester["courses"]
        if course["status"] != "milestone"
        and course["credits"] >= COUNTED_CLASS_MIN_CREDITS
    ]


def owed_credits(audit):
    """Credits that are owed *and* schedulable.

    A hour check such as "TOTAL HOURS: 120" carries a large remaining figure and
    is deliberately never scheduled: it restates the sum of everything else.
    Counting it here would demand the plan schedule the same credits twice.
    """
    return sum(
        requirement["credits_remaining"]
        for requirement in audit["requirements"]
        if requirement["credits_remaining"] > 0
        and requirement["status"] in {"remaining", "in_progress"}
        and requirement["category"] in SCHEDULABLE_CATEGORIES
    )


# --------------------------------------------------------------- B-01, no loss

@pytest.mark.parametrize(
    "fixture",
    [
        "journalism_early_semester",
        "journalism_unresolved_elective_block",
        "dance_bfa_near_graduation",
        "aerospace_transfer_credit_heavy",
    ],
)
def test_no_owed_credit_is_dropped(parsed_synthetic, fixture) -> None:
    """B-01: 12 to 27 credits per audit used to vanish before reaching the map.

    Every credit-bearing requirement that is still owed must appear somewhere —
    a term, or the holding area. Nothing may simply stop existing.
    """
    audit = parsed_synthetic[fixture]
    result = plan_for(audit)
    planned_ids = {
        requirement_id
        for semester in result["plan"]["semesters"]
        for course in semester["courses"]
        for requirement_id in course["requirement_ids"]
    }
    lost = [
        requirement
        for requirement in audit["requirements"]
        if requirement["status"] == "remaining"
        and requirement["credits_remaining"] > 0
        and requirement["id"] not in planned_ids
    ]
    assert not lost, [r["name"] for r in lost]
    assert result["plan"]["planned_credits"] >= owed_credits(audit) - 0.01


# ------------------------------------------------------- B-02, the MCAT term

def test_the_mcat_term_is_held_to_the_load_the_student_chose(parsed_synthetic) -> None:
    """B-02: the flag was written and never read, so the exam term was never light."""
    audit = parsed_synthetic["journalism_early_semester"]
    result = plan_for(
        audit,
        premed=True,
        mcat_terms=["Spring 2028"],
        mcat_credit_ceiling=6,
        mcat_course_ceiling=2,
    )
    exam = next(s for s in scheduled_terms(result["plan"]) if s["is_mcat_term"])
    assert exam["credit_limit"] == 6
    assert exam["course_limit"] == 2
    assert exam["total_credits"] <= 6.01
    assert len(classes_in(exam)) <= 2


def test_the_mcat_load_is_the_students_call_in_either_direction(parsed_synthetic) -> None:
    """A student who wants a heavy exam term gets one; nothing clamps them down."""
    audit = parsed_synthetic["aerospace_transfer_credit_heavy"]
    heavy = plan_for(
        audit,
        premed=True,
        credits_per_term=15,
        mcat_terms=["Spring 2028"],
        mcat_credit_ceiling=15,
        mcat_course_ceiling=5,
    )
    exam = next(s for s in scheduled_terms(heavy["plan"]) if s["is_mcat_term"])
    assert exam["credit_limit"] == 15


def test_toggling_pre_med_only_lightens_the_exam_term(parsed_synthetic) -> None:
    """The same input, pre-med off then on, must not corrupt the distribution."""
    audit = parsed_synthetic["journalism_early_semester"]
    without = plan_for(audit)
    with_premed = plan_for(audit, premed=True, mcat_terms=["Spring 2028"])

    exam = next(s for s in scheduled_terms(with_premed["plan"]) if s["is_mcat_term"])
    same_term_before = next(
        s for s in scheduled_terms(without["plan"]) if s["term"] == "Spring 2028"
    )
    assert exam["credit_limit"] < same_term_before["credit_limit"]
    assert exam["total_credits"] <= exam["credit_limit"] + 0.01
    # Lightening one term must not lose work from the plan as a whole.
    assert with_premed["plan"]["planned_credits"] >= without["plan"]["planned_credits"] - 0.01


# ------------------------------------------- B-03/B-04, ceilings are enforced

@pytest.mark.parametrize(
    "fixture",
    [
        "journalism_early_semester",
        "journalism_unresolved_elective_block",
        "dance_bfa_near_graduation",
        "aerospace_transfer_credit_heavy",
    ],
)
def test_no_term_exceeds_either_ceiling(parsed_synthetic, fixture) -> None:
    """B-03/B-04: only credits were ever checked, and zero-credit items bypassed that."""
    result = plan_for(parsed_synthetic[fixture], premed=True, mcat_terms=["Spring 2028"])
    for semester in scheduled_terms(result["plan"]):
        if semester["is_in_progress"]:
            continue  # Already registered; not a planning choice.
        assert semester["total_credits"] <= semester["credit_limit"] + 0.01, semester["term"]
        assert len(classes_in(semester)) <= semester["course_limit"], semester["term"]


# --------------------------------------------------------- B-05, even spread

def test_a_heavy_load_is_spread_rather_than_front_loaded(parsed_synthetic) -> None:
    """B-05: first-fit filled the front of the window and starved the back."""
    result = plan_for(parsed_synthetic["journalism_early_semester"], credits_per_term=15)
    loads = [
        s["total_credits"]
        for s in scheduled_terms(result["plan"])
        if not s["is_in_progress"] and s["courses"]
    ]
    assert len(loads) >= 3
    # No occupied term may be a small fraction of the heaviest one.
    assert min(loads) >= max(loads) * 0.5, loads


def test_a_light_load_does_not_get_stretched_across_the_window(parsed_synthetic) -> None:
    """Balance must not delay graduation to flatten a graph."""
    result = plan_for(parsed_synthetic["dance_bfa_near_graduation"], graduation_term="Spring 2030")
    occupied = [s for s in scheduled_terms(result["plan"]) if s["courses"]]
    # Roughly 19 owed credits should not be smeared over eight semesters.
    assert len(occupied) <= 4, [s["term"] for s in occupied]


# ---------------------------------------- B-06/B-14, electives are real slots

def test_electives_are_named_or_labelled_never_a_dars_sentence(parsed_synthetic) -> None:
    """B-06/B-07: the whole DARS line used to become the course code."""
    result = plan_for(parsed_synthetic["journalism_early_semester"])
    for semester in result["plan"]["semesters"]:
        for course in semester["courses"]:
            assert "NEEDS:" not in course["code"]
            assert "hours" not in course["code"].casefold()
            assert len(course["code"]) <= 62, course["code"]
            # A named course must offer a working Class Search link.
            if not course["is_placeholder"] and course["subject"]:
                assert course["class_search_url"].startswith("https://")


def test_unnamed_electives_are_scheduled_not_dropped(parsed_synthetic) -> None:
    """A bare "Elective: 3 hours" still has to occupy a slot with its hours."""
    audit = parsed_synthetic["journalism_early_semester"]
    bare = [
        r for r in audit["requirements"]
        if r["name"].startswith("Elective") and r["status"] == "remaining"
    ]
    assert bare, "fixture should carry Journalism's two unnamed elective lines"
    result = plan_for(audit)
    scheduled = {
        requirement_id
        for semester in result["plan"]["semesters"]
        for course in semester["courses"]
        for requirement_id in course["requirement_ids"]
    }
    for requirement in bare:
        assert requirement["id"] in scheduled, requirement["name"]


def test_a_large_unresolved_transfer_block_is_placed_in_pieces(parsed_synthetic) -> None:
    """A 24-hour block with no course detail becomes several schedulable slots."""
    audit = parsed_synthetic["journalism_unresolved_elective_block"]
    block = next(r for r in audit["requirements"] if r["name"].startswith("Elective: 24"))
    assert block["required_count"] == 4, "12 remaining hours is four classes, not eight"
    result = plan_for(audit)
    slots = [
        course
        for semester in result["plan"]["semesters"]
        for course in semester["courses"]
        if block["id"] in course["requirement_ids"]
    ]
    assert len(slots) == 4
    assert sum(slot["credits"] for slot in slots) == pytest.approx(12.0)


def test_electives_do_not_all_land_in_one_term(parsed_synthetic) -> None:
    """B-14: fragments sharing one code sorted adjacently and packed together."""
    result = plan_for(parsed_synthetic["journalism_unresolved_elective_block"])
    per_term = [
        sum(1 for c in s["courses"] if c["is_placeholder"])
        for s in scheduled_terms(result["plan"])
        if not s["is_in_progress"]
    ]
    placeholders = sum(per_term)
    assert placeholders >= 4
    assert max(per_term) <= placeholders * 0.75, per_term


# ------------------------------------------ Structure-driven elective reading

def test_the_dance_pool_resolves_against_its_lookup_list(parsed_synthetic) -> None:
    """OR-grouped Personal Movement Practice, resolved from the table at the end."""
    audit = parsed_synthetic["dance_bfa_near_graduation"]
    pool = next(
        r for r in audit["requirements"]
        if "Personal Movement Practice" in r["name"] and r["credits_remaining"] > 0
    )
    assert pool["category"] == "elective_constrained"
    assert pool["required_count"] == 2, "the block says 'Complete 2 courses'"
    # The lower-division pool is excluded by "-> NOT FROM:".
    assert all(code.startswith("DCE 3") for code in pool["course_options"]), pool["course_options"]


def test_aerospace_wildcards_and_capped_list_are_read(parsed_synthetic) -> None:
    """Wildcards resolve; the cap is a constraint and is never scheduled."""
    audit = parsed_synthetic["aerospace_transfer_credit_heavy"]
    technical = next(
        r for r in audit["requirements"] if r["name"].startswith("Upper Division Technical Elective")
    )
    assert [p["level"] for p in technical["wildcards"]] == [3, 4]
    assert technical["required_count"] == 3

    cap = next(r for r in audit["requirements"] if r["category"] == "constraint")
    assert cap["capped_limit"] == 1
    assert len(cap["capped_options"]) > 10
    result = plan_for(audit)
    scheduled = {
        requirement_id
        for semester in result["plan"]["semesters"]
        for course in semester["courses"]
        for requirement_id in course["requirement_ids"]
    }
    assert cap["id"] not in scheduled, "a cap is a rule, not coursework"
