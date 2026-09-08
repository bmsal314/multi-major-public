"""Answer one question: does this plan actually graduate on time?

The planner is good at placing coursework, but "every unit got a term" is not
the same as "every requirement is satisfied by the graduation term".  This
module re-reads the finished plan against the parsed audits and reports, rule by
rule, what is covered and what is not.

Every check is derived from the audits themselves — the hour minimums, GPA
checks, and college rules DARS states — rather than from hardcoded ASU policy,
so a catalog change flows through automatically.  Advisory items that depend on
information the audits do not contain (registration overload approval, the
full-time threshold) are reported as notes, never as failures.
"""

from __future__ import annotations

from typing import Any, Literal


CheckStatus = Literal["pass", "note", "gap"]

# A term below this many credits is normally part-time at ASU, which can affect
# aid, scholarships, insurance, and honors continuous-enrolment.  Reported as a
# note because a deliberately light term may be exactly what the student wants.
FULL_TIME_CREDITS = 12.0

# Above this, ASU requires approval for a credit overload.  Also a note: it is
# an administrative step, not a planning error.
OVERLOAD_CREDITS = 18.0


def _scheduled_semesters(plan: dict[str, Any]) -> list[dict[str, Any]]:
    """Real terms only.

    The plan ends with a holding area for work that fit nowhere.  Counting it as
    scheduled would turn every readiness question into a false pass, since the
    whole point of that area is that these classes have no term yet.
    """
    return [
        semester
        for semester in plan.get("semesters", [])
        if not semester.get("is_unplaced")
    ]


def _unplaced_courses(plan: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        course
        for semester in plan.get("semesters", [])
        if semester.get("is_unplaced")
        for course in semester["courses"]
    ]


def _check(
    identifier: str,
    label: str,
    status: CheckStatus,
    detail: str,
    evidence: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "id": identifier,
        "label": label,
        "status": status,
        "detail": detail,
        "evidence": evidence or [],
    }


def _planned_requirement_ids(plan: dict[str, Any]) -> set[str]:
    return {
        requirement_id
        for semester in _scheduled_semesters(plan)
        for course in semester["courses"]
        for requirement_id in course.get("requirement_ids", [])
    }


def _planned_credits_by_term(
    plan: dict[str, Any],
    include_registered: bool = True,
) -> list[tuple[str, float, float]]:
    """(term, credits counting toward load, credit limit) per term."""
    rows: list[tuple[str, float, float]] = []
    for semester in _scheduled_semesters(plan):
        if not include_registered and semester.get("is_in_progress"):
            continue
        rows.append(
            (
                semester["term"],
                float(semester["total_credits"]),
                float(semester["credit_limit"]),
            )
        )
    return rows


def _requirement_coverage(
    audits: list[dict[str, Any]],
    plan: dict[str, Any],
) -> list[dict[str, Any]]:
    """Every outstanding requirement must be referenced by the plan."""
    planned_ids = _planned_requirement_ids(plan)
    checks: list[dict[str, Any]] = []

    for audit in audits:
        uncovered = [
            requirement
            for requirement in audit["requirements"]
            if requirement["status"] == "remaining"
            and requirement["id"] not in planned_ids
            # A GPA rule is satisfied by performance, not by scheduling.
            and requirement["kind"] != "gpa"
            # An equivalence-cleared requirement needs no place in the plan.
            and not requirement.get("satisfied_by")
        ]
        if uncovered:
            checks.append(
                _check(
                    f"coverage:{audit['name']}",
                    f"{audit['name']}: every remaining requirement is scheduled",
                    "gap",
                    (
                        f"{len(uncovered)} remaining requirement"
                        f"{'s' if len(uncovered) != 1 else ''} in {audit['name']} "
                        "have no place in the plan before graduation."
                    ),
                    [
                        f"{requirement['section']} - {requirement['name']}"
                        for requirement in uncovered[:8]
                    ],
                )
            )
        else:
            checks.append(
                _check(
                    f"coverage:{audit['name']}",
                    f"{audit['name']}: every remaining requirement is scheduled",
                    "pass",
                    f"All outstanding {audit['name']} requirements appear in the plan.",
                )
            )
    return checks


def _unplaced_check(plan: dict[str, Any]) -> list[dict[str, Any]]:
    """Work sitting in the holding area blocks graduation until it has a term."""
    waiting = _unplaced_courses(plan)
    if not waiting:
        return []
    return [
        _check(
            "plan:unplaced",
            f"{len(waiting)} class{'es' if len(waiting) != 1 else ''} still need a term",
            "gap",
            (
                "These did not fit any term at its current ceiling and are waiting at "
                "the end of the map. Drag each into a term and raise that term's "
                "ceiling, add summer terms, or move graduation later."
            ),
            [
                f"{course['label']} ({course['credits']:g} cr)"
                for course in waiting[:8]
            ],
        )
    ]


def _equivalence_notes(audits: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Report requirements a course equivalence cleared rather than scheduling.

    These are never a pass on their own: DARS still lists the requirement, so
    it stays outstanding on the official record until an advisor records the
    substitution.  Saying so is the whole point of the check.
    """
    checks: list[dict[str, Any]] = []
    for audit in audits:
        cleared = [
            requirement
            for requirement in audit["requirements"]
            if requirement.get("satisfied_by")
        ]
        if not cleared:
            continue
        checks.append(
            _check(
                f"equivalence:{audit['name']}",
                f"{audit['name']}: {len(cleared)} requirement"
                f"{'s' if len(cleared) != 1 else ''} cleared by an equivalence",
                "note",
                (
                    "These are not scheduled because a course you already hold covers "
                    "them. DARS still lists them as remaining and will until an "
                    "advisor records the substitution, so confirm it is on your record "
                    "before the graduation audit."
                ),
                [
                    f"{requirement['name'].rstrip(':')} - {requirement['satisfied_by']}"
                    for requirement in cleared
                ],
            )
        )
    return checks


def _hour_minimums(
    audits: list[dict[str, Any]],
    plan: dict[str, Any],
) -> list[dict[str, Any]]:
    """Check DARS-stated hour minimums against earned + in-progress + planned."""
    planned_total = float(plan.get("planned_credits") or 0.0)
    checks: list[dict[str, Any]] = []
    seen: set[str] = set()

    for audit in audits:
        for requirement in audit["requirements"]:
            if requirement["kind"] != "milestone":
                continue
            required = float(requirement["credits_required"])
            if required <= 0:
                continue
            key = f"{requirement['name'].casefold()}|{required:g}"
            if key in seen:
                continue
            seen.add(key)

            earned = float(requirement["credits_earned"])
            in_progress = float(requirement["credits_in_progress"])
            shortfall = float(requirement["credits_remaining"])
            secured = earned + in_progress

            if shortfall <= 0:
                checks.append(
                    _check(
                        f"hours:{requirement['id']}",
                        f"{audit['name']}: {requirement['name']}",
                        "pass",
                        f"{secured:g} of {required:g} hours secured.",
                    )
                )
            elif shortfall <= planned_total:
                checks.append(
                    _check(
                        f"hours:{requirement['id']}",
                        f"{audit['name']}: {requirement['name']}",
                        "note",
                        (
                            f"{secured:g} of {required:g} hours secured; the remaining "
                            f"{shortfall:g} must come from planned coursework that "
                            "actually carries this designation."
                        ),
                        [requirement["section"]],
                    )
                )
            else:
                checks.append(
                    _check(
                        f"hours:{requirement['id']}",
                        f"{audit['name']}: {requirement['name']}",
                        "gap",
                        (
                            f"{secured:g} of {required:g} hours secured, but only "
                            f"{planned_total:g} credits are planned in total."
                        ),
                        [requirement["section"]],
                    )
                )
    return checks


def _thesis_and_milestones(plan: dict[str, Any]) -> list[dict[str, Any]]:
    """Zero-credit gates such as the Barrett thesis must have a term."""
    milestones = [
        (semester["term"], course)
        for semester in _scheduled_semesters(plan)
        for course in semester["courses"]
        if course.get("status") == "milestone"
    ]
    if not milestones:
        return []
    return [
        _check(
            "milestone:scheduled",
            "Non-course milestones have a term",
            "note",
            (
                f"{len(milestones)} milestone"
                f"{'s' if len(milestones) != 1 else ''} scheduled. These are gates, "
                "not classes: confirm the deadline and any required enrolment with "
                "the college."
            ),
            [f"{label} - {course['label']}" for label, course in milestones],
        )
    ]


def _placeholder_check(plan: dict[str, Any]) -> list[dict[str, Any]]:
    placeholders = [
        (semester["term"], course)
        for semester in _scheduled_semesters(plan)
        for course in semester["courses"]
        if course.get("is_placeholder") and course.get("status") != "personal"
    ]
    if not placeholders:
        return [
            _check(
                "placeholders",
                "Every planned slot names a specific course",
                "pass",
                "No unresolved placeholders remain.",
            )
        ]
    return [
        _check(
            "placeholders",
            "Every planned slot names a specific course",
            "note",
            (
                f"{len(placeholders)} slot{'s' if len(placeholders) != 1 else ''} still "
                "need a specific course chosen before registration."
            ),
            [f"{term} - {course['label']}" for term, course in placeholders[:10]],
        )
    ]


def _premed_before_mcat(
    premed: dict[str, Any],
    plan: dict[str, Any],
    mcat_term: str | None,
) -> list[dict[str, Any]]:
    """Core pre-med content should be finished before the MCAT term."""
    if not mcat_term:
        return []
    terms = [semester["term"] for semester in _scheduled_semesters(plan)]
    if mcat_term not in terms:
        return []
    mcat_index = terms.index(mcat_term)

    late: list[str] = []
    for index, semester in enumerate(_scheduled_semesters(plan)):
        if index < mcat_index:
            continue
        for course in semester["courses"]:
            if course.get("status") == "premed":
                late.append(f"{semester['term']} - {course['label']}")

    outstanding = [
        requirement["name"]
        for requirement in premed["requirements"]
        if requirement["required"] and requirement["status"] == "remaining"
    ]
    if not late and not outstanding:
        return [
            _check(
                "premed:before-mcat",
                f"Pre-med core complete before {mcat_term}",
                "pass",
                "The pre-health core is finished or in progress before the MCAT term.",
            )
        ]
    return [
        _check(
            "premed:before-mcat",
            f"Pre-med core complete before {mcat_term}",
            "note",
            (
                "Some pre-health core content is scheduled in or after the MCAT term. "
                "The MCAT covers this material, so confirm the timing is deliberate."
            ),
            late[:8] or outstanding[:8],
        )
    ]


def _term_load_notes(plan: dict[str, Any], mcat_term: str | None) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    light: list[str] = []
    heavy: list[str] = []

    # A term already registered for is settled: its load is not a decision left
    # to make, so it is neither a light-term warning nor an overload to approve.
    for term, credits, _limit in _planned_credits_by_term(plan, include_registered=False):
        if credits <= 0:
            continue
        if credits < FULL_TIME_CREDITS:
            light.append(f"{term} - {credits:g} credits")
        if credits > OVERLOAD_CREDITS:
            heavy.append(f"{term} - {credits:g} credits")

    if light:
        detail = (
            f"Below the {FULL_TIME_CREDITS:g}-credit full-time line, which can affect "
            "financial aid, scholarships, insurance, and honors continuous enrolment."
        )
        if mcat_term and any(item.startswith(f"{mcat_term} ") for item in light):
            detail += f" {mcat_term} is intentionally light for MCAT study."
        checks.append(
            _check("load:part-time", "Terms below full-time", "note", detail, light)
        )

    if heavy:
        checks.append(
            _check(
                "load:overload",
                "Terms above the standard credit ceiling",
                "note",
                (
                    f"Above this planner’s {OVERLOAD_CREDITS:g}-credit workload threshold, "
                    "check your college’s overload rules before registration. Approval limits can differ."
                ),
                heavy,
            )
        )

    empty = [
        term
        for term, credits, _limit in _planned_credits_by_term(plan)
        if credits <= 0
    ]
    if empty:
        checks.append(
            _check(
                "load:empty",
                "Terms with nothing scheduled",
                "note",
                "These terms are empty; work could be moved here to balance the load.",
                empty,
            )
        )
    return checks


def _prerequisite_coverage(plan: dict[str, Any]) -> list[dict[str, Any]]:
    """Say plainly which scheduled courses have no prerequisite data.

    Prerequisites are never guessed.  A course absent from the known map is
    reported as unverified rather than assumed to have none, so the plan's
    ordering is only trusted where there is real data behind it.
    """
    from .semester_planner import COURSE_COREQUISITES, COURSE_PREREQUISITES

    import re as _re

    known = set(COURSE_PREREQUISITES) | set(COURSE_COREQUISITES)
    for chain in (*COURSE_PREREQUISITES.values(), *COURSE_COREQUISITES.values()):
        known.update(chain)

    unverified: list[str] = []
    for semester in _scheduled_semesters(plan):
        for course in semester["courses"]:
            if course.get("status") in {"in_progress", "personal", "milestone"}:
                continue
            code = course["code"]
            # Only real course codes can be checked; placeholders have no code yet.
            if not _re.fullmatch(r"[A-Z]{2,4}\s+\d{3}[A-Z]?", code):
                continue
            if code not in known:
                unverified.append(f"{semester['term']} - {code}")

    if not unverified:
        return []
    return [
        _check(
            "prerequisites:unverified",
            "Prerequisite data for scheduled courses",
            "note",
            (
                f"{len(unverified)} scheduled course"
                f"{'s' if len(unverified) != 1 else ''} have no prerequisite data, so "
                "their term placement is unchecked. Confirm each against ASU Class "
                "Search before registering."
            ),
            unverified[:12],
        )
    ]


def evaluate_graduation_readiness(
    audits: list[dict[str, Any]],
    plan: dict[str, Any],
    premed: dict[str, Any],
    mcat_term: str | None = None,
) -> dict[str, Any]:
    """Produce a rule-by-rule readiness report for the graduation term."""
    checks: list[dict[str, Any]] = []
    checks.extend(_requirement_coverage(audits, plan))
    checks.extend(_hour_minimums(audits, plan))
    checks.extend(_thesis_and_milestones(plan))
    checks.extend(_placeholder_check(plan))
    checks.extend(_unplaced_check(plan))
    checks.extend(_equivalence_notes(audits))
    checks.extend(_premed_before_mcat(premed, plan, mcat_term))
    checks.extend(_prerequisite_coverage(plan))
    checks.extend(_term_load_notes(plan, mcat_term))

    # Coursework that fit nowhere is already reported by ``_unplaced_check``,
    # which names the classes and how to absorb them.  What is left here are the
    # items that were never schedulable at all — requirements DARS states without
    # naming a course or a criterion, which only an advisor can resolve.
    advisor_items = [
        item
        for item in (plan.get("unplanned_requirements") or [])
        if item not in {course["label"] for course in _unplaced_courses(plan)}
    ]
    if advisor_items:
        checks.append(
            _check(
                "planner:unplanned",
                "Every requirement is schedulable",
                "gap",
                (
                    f"{len(advisor_items)} requirement"
                    f"{'s' if len(advisor_items) != 1 else ''} name no course and no "
                    "criterion, so nothing could be planned for them. Ask an advisor "
                    "what satisfies each one, then add it to a term."
                ),
                advisor_items[:10],
            )
        )
    elif not _unplaced_courses(plan):
        checks.append(
            _check(
                "planner:unplanned",
                "Everything fits before graduation",
                "pass",
                "Every planning unit found a term within the window.",
            )
        )

    gaps = [check for check in checks if check["status"] == "gap"]
    notes = [check for check in checks if check["status"] == "note"]
    status = "blocked" if gaps else "on_track_with_notes" if notes else "on_track"

    return {
        "status": status,
        "graduation_term": plan.get("graduation_term", ""),
        "pass_count": sum(1 for check in checks if check["status"] == "pass"),
        "note_count": len(notes),
        "gap_count": len(gaps),
        "checks": checks,
    }
