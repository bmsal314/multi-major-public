"""Defects reported from the deployed app on 2026-09-03.

Each of these produced a plausible-looking wrong answer in front of a student,
which is why they are pinned here rather than left to the scenario tests.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.cloud.contracts import Preferences, PersonalRules, RecurringCommitment
from backend.cloud.engine import build_result, parse_documents
from backend.pdf_parser import parse_dars_pdf

REAL = Path(__file__).resolve().parents[1] / "fixtures" / "dars_real"


@pytest.fixture(scope="module")
def real_audits(real_dir: Path):
    return parse_documents([
        (real_dir / name).read_bytes()
        for name in ("finance_dars.pdf", "neuroscience_dars.pdf", "honors_dars.pdf")
    ])


# ------------------------------------------------- unread DARS conditions

@pytest.mark.parametrize("name", ["finance_dars", "neuroscience_dars", "honors_dars"])
def test_a_complete_audit_reports_no_unread_conditions(real_dir: Path, name: str) -> None:
    """Twelve "Unresolved condition N" rows appeared on audits with nothing unread.

    Three separate causes, all false positives:
      * a requirement's evidence is truncated to 900 characters for display, and
        the check compared against that, so long blocks lost their own NEEDS line;
      * DARS prints a section total above its numbered children, and that summary
        was counted as another thing the student owed;
      * "15.00 ATTEMPTED HOURS 59.00 POINTS 3.93 GPA" is almost all uppercase and
        was read as a section heading, which closed the block it belonged to.

    Each surfaced to the student as a *blocking* graduation check.
    """
    audit = parse_dars_pdf(str(real_dir / f"{name}.pdf"))
    unread = [r for r in audit["requirements"] if r["section"] == "Unresolved DARS conditions"]
    assert unread == [], [r["source_text"][:80] for r in unread]


def test_a_statistics_row_is_not_a_section_heading() -> None:
    from backend.pdf_parser import _looks_like_section

    assert _looks_like_section("15.00 ATTEMPTED HOURS 59.00 POINTS 3.93 GPA") is False
    assert _looks_like_section("3.00 Hours Earned 1 Course") is False
    # Real headings still read as headings.
    assert _looks_like_section("BUSINESS CORE Requirements") is True


# ------------------------------------------- the standing commitment (2038)

def test_a_standing_commitment_never_extends_the_plan(real_audits) -> None:
    """"Path to Spring 2038" for a student finishing in 2028.

    The commitment was modelled as an ordinary unit, so it occupied every term
    in the planning window — and with no graduation term set that window is
    twenty-four terms. The graduation term was then read off the last occupied
    term, which was always the last term in the window.
    """
    without = build_result(real_audits, Preferences(
        premed=True, start_term="Fall 2026", credits_per_term=30, min_credits=13))
    with_dance = build_result(real_audits, Preferences(
        premed=True, start_term="Fall 2026", credits_per_term=30, min_credits=13,
        personal_rules=PersonalRules(dance=True)))

    assert with_dance["plan"]["graduation_term"] == without["plan"]["graduation_term"], (
        "a personal commitment must not change when the degree finishes"
    )
    terms = [s for s in with_dance["plan"]["semesters"] if not s["is_unplaced"]]
    assert len(terms) <= 8, [s["term"] for s in terms]
    # Every term up to graduation carries it, and none past graduation exists.
    for semester in terms:
        if semester["is_in_progress"] or semester["term"].startswith("Summer"):
            continue
        assert any(c["status"] == "personal" for c in semester["courses"]), semester["term"]


def test_the_commitment_is_not_hardcoded_to_dance(real_audits) -> None:
    """A STEM student protecting one non-technical class needs the same feature."""
    result = build_result(real_audits, Preferences(
        start_term="Fall 2026", credits_per_term=15,
        recurring_commitment=RecurringCommitment(
            enabled=True, label="Concert band", code="MUP", credits=1.0)))
    personal = [
        course
        for semester in result["plan"]["semesters"]
        for course in semester["courses"]
        if course["status"] == "personal"
    ]
    assert personal, "the commitment should be reserved every term"
    assert {c["label"] for c in personal} == {"Concert band"}
    assert {c["credits"] for c in personal} == {1.0}


def test_a_commitment_holds_real_room_rather_than_overflowing_a_term(real_audits) -> None:
    """Reserved before coursework is placed, so no term ends up over its ceiling."""
    result = build_result(real_audits, Preferences(
        start_term="Fall 2026", graduation_term="Spring 2029", credits_per_term=15,
        recurring_commitment=RecurringCommitment(enabled=True, credits=2.0)))
    for semester in result["plan"]["semesters"]:
        if semester["is_unplaced"] or semester["is_in_progress"]:
            continue
        assert semester["total_credits"] <= semester["credit_limit"] + 0.01, semester["term"]


# ------------------------------------- the graduation date is stated, not guessed

def test_the_stated_graduation_term_is_honoured_exactly(real_audits) -> None:
    """The planner must not move the date the student gave it.

    It used to infer one from wherever the last course landed, which is how a
    standing commitment produced a 2038 graduation. The window now ends where
    the student said it ends, whatever fits inside it.
    """
    for target in ("Spring 2029", "Fall 2029", "Spring 2030"):
        result = build_result(real_audits, Preferences(
            start_term="Fall 2026", graduation_term=target, credits_per_term=15))
        assert result["plan"]["graduation_term"] == target
        terms = [s["term"] for s in result["plan"]["semesters"] if not s["is_unplaced"]]
        assert terms[-1] == target


def test_the_pace_reports_what_the_target_costs(real_audits) -> None:
    """A ceiling that cannot reach the target has to say so, with a number."""
    tight = build_result(real_audits, Preferences(
        start_term="Fall 2026", graduation_term="Spring 2029", credits_per_term=15))
    pace = tight["plan"]["pace"]
    assert pace["open_terms"] > 0
    assert pace["required_per_term"] > pace["credit_ceiling"]
    assert pace["feasible"] is False
    assert pace["unplaced_credits"] > 0
    # The warning names the ceiling that would actually work.
    assert any(
        "did not fit" in w and "credits a term would fit it" in w
        for w in tight["plan"]["warnings"]
    ), tight["plan"]["warnings"]

    roomy = build_result(real_audits, Preferences(
        start_term="Fall 2026", graduation_term="Spring 2029", credits_per_term=26))
    assert roomy["plan"]["pace"]["feasible"] is True
    assert roomy["plan"]["pace"]["unplaced_credits"] == 0


def test_finishing_early_is_reported_rather_than_silently_retimed(real_audits) -> None:
    """Work that ends before the target is worth saying, not worth rewriting."""
    result = build_result(real_audits, Preferences(
        start_term="Fall 2026", graduation_term="Spring 2032", credits_per_term=26))
    assert result["plan"]["graduation_term"] == "Spring 2032"
    assert any("could graduate earlier" in w for w in result["plan"]["warnings"])
