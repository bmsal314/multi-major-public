"""Deterministic overlap-aware planning for parsed DARS requirements."""

from __future__ import annotations

import math
import re
from collections import defaultdict
from typing import Any
from urllib.parse import urlencode


from .course_rules import (
    ADVISOR_TRACKS,
    COURSE_COREQUISITES,
    COURSE_PREREQUISITES,
    MIN_TERM_CREDITS,
    PREREQUISITE_SOURCES,
    attribute_label,
    attributes_for,
    notes_for_course,
    subject_affinity,
)


UNPLACED_TERM = "Not yet placed"

# ---------------------------------------------------------------------------
# Term load ceilings
#
# These are stated as named constants rather than left implicit in the packing
# code, and every one of them is overridable per user through ``Preferences`` —
# none is tied to a particular programme.  Before this, the only ceiling was a
# credit total: nothing limited how many separate classes a term could hold, so
# a term could be handed fifteen items totalling six credits, and marking a term
# for MCAT preparation set a flag that no code ever read.
# ---------------------------------------------------------------------------

#: Load-bearing classes in one term, independent of credits. Six three-credit
#: classes is already a heavy term; the count matters as much as the hours
#: because each class is its own set of deadlines.
DEFAULT_TERM_COURSE_CEILING = 6

#: What counts as a class for that ceiling. The university's quarter-credit professional
#: development modules (WPC 148, WPC 248, WPC 348, WPC 448) are not a semester's
#: worth of deadlines, and counting them the same as a three-credit lecture
#: pushed real coursework off the end of the map.
COUNTED_CLASS_MIN_CREDITS = 1.0

#: An absolute cap on items in one term, whatever they weigh. This is the guard
#: against a term holding fifteen entries totalling six credits.
DEFAULT_TERM_ITEM_CEILING = 9

#: A term flagged for MCAT preparation. The exam needs months of study running
#: alongside coursework, so both ceilings drop — this is the difference between
#: a plan a pre-med student can actually follow and one they abandon.
DEFAULT_MCAT_CREDIT_CEILING = 12
DEFAULT_MCAT_COURSE_CEILING = 4

SEASONS = ("Spring", "Summer", "Fall")
SEASON_INDEX = {season: index for index, season in enumerate(SEASONS)}

__all__ = [
    "COURSE_COREQUISITES",
    "COURSE_PREREQUISITES",
    "UNPLACED_TERM",
    "build_planning_units",
    "build_recommendations",
    "class_search_url",
    "generate_plan",
    "generate_semester_plan",
]


def _parse_term(value: str) -> tuple[str, int] | None:
    value = value.strip()
    friendly = re.fullmatch(r"(Spring|Summer|Fall)\s+(\d{4})", value, re.IGNORECASE)
    if friendly:
        return friendly.group(1).title(), int(friendly.group(2))

    short = re.fullmatch(r"(SP|SU|FA)(\d{2,4})", value, re.IGNORECASE)
    if short:
        season = {"SP": "Spring", "SU": "Summer", "FA": "Fall"}[short.group(1).upper()]
        year = int(short.group(2))
        return season, year + 2000 if year < 100 else year
    return None


def _parse_term_code(value: str) -> tuple[str, int] | None:
    parsed = _parse_term(value)
    if not parsed:
        return None
    season, year = parsed
    return {"Spring": "SP", "Summer": "SU", "Fall": "FA"}[season], year


def _parse_graduation_date(value: str) -> tuple[str, int] | None:
    return _parse_term_code(value)


def _term_key(term: tuple[str, int]) -> int:
    season, year = term
    return year * 3 + SEASON_INDEX[season]


def _generate_terms(start: str, graduation: str, include_summer: bool) -> list[str]:
    parsed_start = _parse_term(start)
    parsed_end = _parse_term(graduation)
    if not parsed_start or not parsed_end or _term_key(parsed_start) > _term_key(parsed_end):
        return []

    terms: list[str] = []
    start_key = _term_key(parsed_start)
    end_key = _term_key(parsed_end)
    for year in range(parsed_start[1], parsed_end[1] + 1):
        for season in SEASONS:
            key = _term_key((season, year))
            if key < start_key or key > end_key:
                continue
            if season == "Summer" and not include_summer:
                continue
            terms.append(f"{season} {year}")
    return terms


def _generate_future_terms(
    current_season: str,
    current_year: int,
    grad_season: str,
    grad_year: int,
) -> list[dict[str, Any]]:
    season_names = {"SP": "Spring", "SU": "Summer", "FA": "Fall"}
    start = f"{season_names[current_season]} {current_year}"
    graduation = f"{season_names[grad_season]} {grad_year}"
    return [
        {
            "term_code": f"{ {'Spring': 'SP', 'Summer': 'SU', 'Fall': 'FA'}[term.split()[0]]}{term[-2:]}",
            "term_label": term,
            "is_summer": term.startswith("Summer"),
        }
        for term in _generate_terms(start, graduation, include_summer=True)[1:]
    ]


def _course_number(code: str) -> int:
    match = re.search(r"\b(\d{3})", code)
    return int(match.group(1)) if match else 999


def _friendly_course_term(value: str) -> str | None:
    parsed = _parse_term(value)
    if not parsed:
        return None
    return f"{parsed[0]} {parsed[1]}"


def _candidate_label(requirement: dict[str, Any]) -> str:
    if requirement.get("criteria"):
        criterion = requirement["criteria"][0]
        if criterion.startswith("ASU General Studies "):
            return criterion.removeprefix("ASU General Studies ") + " approved elective"
        if criterion == "Honors credit":
            return "Honors-designated elective"
        if "course" in criterion.casefold() or "elective" in criterion.casefold():
            return criterion
        return f"{criterion} elective"
    name = re.sub(r":.*$", "", requirement["name"]).strip()
    return name if len(name) <= 58 else f"{requirement['section']} elective"


def _term_code(term: str) -> str:
    """The university's four-digit term code, e.g. Fall 2026 -> 2267."""
    parsed = _parse_term(term)
    if not parsed:
        return ""
    season, year = parsed
    return f"2{year % 100:02d}{ {'Spring': 1, 'Summer': 4, 'Fall': 7}[season] }"


def _justify(
    code: str,
    requirement_names: list[str],
    sections: list[str],
    majors: list[str],
    is_placeholder: bool,
) -> str:
    """One sentence saying why this class is on the plan, for the printed PDF.

    Ordering is deliberately left out: the printed plan states the prerequisite
    chain on its own line, so repeating it here only makes the sentence longer.
    """
    programs = " and ".join(majors)
    requirement = (requirement_names[0] if requirement_names else "").rstrip(":")
    section = sections[0].title() if sections else ""

    if len(majors) > 1:
        clause = f"Counts for {programs} at once"
    elif is_placeholder:
        clause = f"Reserved for a {programs} requirement you still choose"
    else:
        clause = f"Required for {programs}"

    if requirement:
        clause += f", satisfying “{requirement}”"
    if section and section.casefold() not in requirement.casefold():
        clause += f" in the {section} block"

    attributes = attributes_for(code)
    if attributes:
        labels = ", ".join(attribute_label(attribute) for attribute in attributes)
        clause += f". It also clears General Studies {labels}"

    return clause.rstrip(".") + "."


def build_planning_units(
    audits: list[dict[str, Any]],
    completed_codes: set[str],
    in_progress_codes: set[str],
) -> tuple[list[dict[str, Any]], list[str]]:
    """Convert requirements into conservative, schedulable units."""
    raw_units: list[dict[str, Any]] = []
    unplanned: list[str] = []

    for audit in audits:
        for requirement in audit["requirements"]:
            if requirement["status"] != "remaining":
                continue
            # A documented equivalence already covers this one; the hours it
            # freed come back as a replacement unit, added by the caller.
            if requirement.get("satisfied_by"):
                continue
            # DARS sometimes labels credit-bearing elective blocks as a
            # milestone simply because the title contains "upper division".
            # Keep those blocks schedulable when coursework evidence exists.
            if requirement["kind"] == "gpa" or (
                requirement["kind"] == "milestone"
                and not requirement.get("course_options")
                and not requirement.get("criteria")
            ):
                continue

            # Zero-credit gates such as the Barrett thesis approval must stay
            # visible in the plan without inventing credits or eating a term's
            # budget.  They are scheduled late by default and stay movable.
            if (
                requirement["kind"] == "project"
                and requirement["credits_required"] <= 0
                and requirement["credits_remaining"] <= 0
            ):
                raw_units.append(
                    {
                        "code": requirement["name"],
                        "label": requirement["name"],
                        "credits": 0.0,
                        "majors": [requirement["major"]],
                        "requirement_ids": [requirement["id"]],
                        "requirement_names": [requirement["name"]],
                        "sections": [requirement["section"]],
                        "alternatives": [],
                        "is_placeholder": False,
                        "status": "milestone",
                        "prerequisites": [],
                        "corequisites": [],
                        "attributes": [],
                        "advisories": [],
                        "justification": (
                            f"A {requirement['major']} gate with no credit hours. "
                            f"“{requirement['name'].rstrip(':')}” has to be signed off "
                            "before the degree is awarded."
                        ),
                    }
                )
                continue

            remaining = requirement["credits_remaining"] or requirement["credits_required"]
            if remaining <= 0:
                remaining = 3.0
            unit_count = max(1, math.ceil(remaining / 3.0))
            credits_left = remaining

            options = [
                code
                for code in requirement.get("course_options", [])
                if code not in completed_codes and code not in in_progress_codes
            ]
            options.sort(
                key=lambda code: (
                    subject_affinity(code, requirement["name"]),
                    _course_number(code),
                    code,
                )
            )

            for index in range(unit_count):
                credits = min(3.0, credits_left) if credits_left > 0 else 3.0
                credits_left = max(0.0, credits_left - credits)
                if index < len(options):
                    code = options[index]
                    label = code
                    placeholder = False
                else:
                    label = _candidate_label(requirement)
                    code = label
                    placeholder = True

                raw_units.append(
                    {
                        "code": code,
                        "label": label,
                        "credits": round(credits, 2),
                        "majors": [requirement["major"]],
                        "requirement_ids": [requirement["id"]],
                        "requirement_names": [requirement["name"]],
                        "sections": [requirement["section"]],
                        "alternatives": [option for option in options if option != code],
                        "is_placeholder": placeholder,
                        "status": "planned",
                        "prerequisites": COURSE_PREREQUISITES.get(code, []),
                        "corequisites": COURSE_COREQUISITES.get(code, []),
                        "attributes": attributes_for(code),
                        "advisories": [note["id"] for note in notes_for_course(code)],
                        "justification": _justify(
                            code,
                            [requirement["name"]],
                            [requirement["section"]],
                            [requirement["major"]],
                            placeholder,
                        ),
                    }
                )

            if not options and not requirement.get("criteria"):
                unplanned.append(
                    f"{requirement['major']}: {requirement['name']} needs advisor-selected coursework."
                )

    # Merge only across different majors.  This avoids claiming that a course
    # can double-count within one program when DARS has not explicitly said so.
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for unit in raw_units:
        grouped[unit["code"]].append(unit)

    merged: list[dict[str, Any]] = []
    for _code, group in grouped.items():
        by_major: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for unit in group:
            by_major[unit["majors"][0]].append(unit)
        merge_count = max(len(units) for units in by_major.values())
        for index in range(merge_count):
            selected = [
                units[index]
                for units in by_major.values()
                if index < len(units)
            ]
            base = dict(selected[0])
            base["credits"] = max(unit["credits"] for unit in selected)
            base["majors"] = sorted({major for unit in selected for major in unit["majors"]})
            base["requirement_ids"] = list(
                dict.fromkeys(req for unit in selected for req in unit["requirement_ids"])
            )
            base["requirement_names"] = list(
                dict.fromkeys(name for unit in selected for name in unit["requirement_names"])
            )
            base["sections"] = list(
                dict.fromkeys(section for unit in selected for section in unit["sections"])
            )
            base["alternatives"] = list(
                dict.fromkeys(option for unit in selected for option in unit["alternatives"])
            )
            # A merged unit now serves more than one program, so its reason has
            # to be rewritten from the merged requirement set rather than kept
            # from whichever single-program unit happened to be first.
            base["justification"] = _justify(
                base["code"],
                base["requirement_names"],
                base["sections"],
                base["majors"],
                base["is_placeholder"],
            )
            merged.append(base)

    return sort_planning_units(merged), list(dict.fromkeys(unplanned))


def _unit_priority(unit: dict[str, Any]) -> tuple[int, int, int, int, int, str]:
    """Order units so the most constrained, most specific work is placed first.

    A named course outranks a slot still to be chosen, and among slots the ones
    that name their approved courses outrank generic filler — a "FIN 400-level
    course" is a specific major requirement, while an "Upper-division course" is
    hours to reach 120.  When a plan cannot fit everything, the filler is what
    should be left over.
    """
    section_text = " ".join(unit.get("sections", [])).casefold()
    core_rank = 0 if any(word in section_text for word in ("core", "major", "skill")) else 1
    course_number = _course_number(unit["code"])
    placeholder_rank = 1 if unit["is_placeholder"] else 0
    named_rank = 0 if unit.get("alternatives") else 1
    return (
        placeholder_rank,
        named_rank,
        course_number // 100,
        core_rank,
        course_number,
        unit["code"],
    )


def sort_planning_units(units: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Put a unit list back in placement priority order.

    Units added after ``build_planning_units`` — pre-med coursework, an
    equivalence replacement — have to re-enter this ordering rather than sit at
    the end of the list, or a required class ends up queued behind filler and is
    the thing that overflows.
    """
    return sorted(units, key=_unit_priority)


def split_course_code(code: str) -> tuple[str, str]:
    """("FIN 361") -> ("FIN", "361").  ("", "") when the text is not a course."""
    match = re.fullmatch(r"([A-Z]{2,4})\s*(\d{3}[A-Z]?)", code.strip().upper())
    if not match:
        return "", ""
    return match.group(1), match.group(2)


def class_search_url(code: str, term: str = "") -> str:
    """Deep-link the class-search catalog at one subject *and* catalog number.

    Class Search reads ``subject`` and ``catalogNbr`` as separate parameters, so
    the three-digit number has to be sent on its own — a single "FIN 361"
    keyword lands on every FIN course instead of the one.

    ``term`` is deliberately *not* forwarded. Class Search only accepts a term
    code it has already opened for registration, which today is the current term
    and no further; handed a future term it discards the whole query and shows a
    blank form. Since a degree plan is almost entirely future terms, omitting it
    is what keeps the link working: the page prefills the subject and number and
    opens on the newest published term, which the student can change there. The
    argument is accepted so callers can pass the planned term without caring.
    """
    del term  # See the docstring: forwarding it breaks the link.
    base = "https://catalog.apps.asu.edu/catalog/classes/classlist"
    subject, number = split_course_code(code)
    if not subject:
        return base
    query = {
        "searchType": "all",
        "subject": subject,
        "catalogNbr": number,
        "collapse": "Y",
    }
    # Class Search is a single-page app and needs the trailing fragment to
    # apply the query on a cold load.
    return f"{base}?{urlencode(query)}#!"


def build_recommendations(units: list[dict[str, Any]]) -> list[dict[str, Any]]:
    recommendations: list[dict[str, Any]] = []
    for unit in units:
        shared = len(unit["majors"]) > 1
        exact = not unit["is_placeholder"]
        priority = (40 if shared else 0) + (25 if exact else 10) + max(0, 20 - _course_number(unit["code"]) // 25)
        alternatives = unit.get("alternatives", [])[:8]
        reason = (
            f"Potentially clears {len(unit['requirement_ids'])} remaining requirements "
            f"across {' and '.join(unit['majors'])}."
            if shared
            else (
                f"Explicitly listed by DARS for {unit['requirement_names'][0]}."
                if exact
                else f"Planning placeholder for {unit['requirement_names'][0]}; choose an approved course."
            )
        )
        subject, catalog_number = split_course_code(unit["code"])
        recommendations.append(
            {
                "course_code": unit["code"],
                "subject": subject,
                "catalog_number": catalog_number,
                "majors": unit["majors"],
                "requirement_ids": unit["requirement_ids"],
                "requirement_names": unit["requirement_names"],
                "credits": unit["credits"],
                "priority": priority,
                "reason": reason,
                "alternatives": alternatives,
                "class_search_url": class_search_url(unit["code"]),
            }
        )
    return sorted(recommendations, key=lambda rec: (-rec["priority"], rec["course_code"]))


def _mcat_term_set(mcat_terms: list[str] | None, mcat_term: str | None) -> set[str]:
    """Accept either the list form or the older single-term keyword."""
    terms = {term.strip() for term in (mcat_terms or []) if term and term.strip()}
    if mcat_term and mcat_term.strip():
        terms.add(mcat_term.strip())
    return terms


def _advisor_forced_terms(
    units: list[dict[str, Any]],
    terms: list[str],
    placed_at: dict[str, int],
    first_open_index: int,
    tracks: list[dict[str, Any]] | None = None,
) -> tuple[dict[int, int], dict[int, str], list[str]]:
    """Resolve each advisor track into an earliest-term index per unit.

    A track is a run of consecutive terms an advisor asked for by name. The
    anchor is coursework already under way, so the run starts in the term after
    it; when no anchor is registered anywhere the run starts at the first term
    the plan can still write to.
    """
    forced: dict[int, int] = {}
    reasons: dict[int, str] = {}
    notes: list[str] = []
    by_code: dict[str, list[int]] = defaultdict(list)
    for index, unit in enumerate(units):
        by_code[unit["code"]].append(index)

    for track in (ADVISOR_TRACKS if tracks is None else tracks):
        anchor_index = max(
            (placed_at[code] for code in track["anchor"] if code in placed_at),
            default=None,
        )
        step_index = (anchor_index + 1) if anchor_index is not None else first_open_index
        step_index = max(step_index, first_open_index)
        matched_anything = False

        for step in track["steps"]:
            if step_index >= len(terms):
                notes.append(
                    f"{track['label']}: the planning window ends before "
                    f"{', '.join(step['courses']) or 'a later step'} can be scheduled."
                )
                break

            for code in step["courses"]:
                for unit_index in by_code.get(code, []):
                    if unit_index in forced:
                        continue
                    forced[unit_index] = step_index
                    reasons[unit_index] = track["source"]
                    matched_anything = True
                    break

            # "then FIN 421 and a major elective" — take one unit out of the
            # named elective block and hold it in the same term as the course
            # it was paired with, instead of leaving it to the generic packer.
            for elective in step.get("electives", []):
                taken = 0
                for unit_index, unit in enumerate(units):
                    if taken >= elective["count"]:
                        break
                    if unit_index in forced:
                        continue
                    if any(
                        elective["match"].casefold() in name.casefold()
                        for name in unit.get("requirement_names", [])
                    ):
                        forced[unit_index] = step_index
                        reasons[unit_index] = track["source"]
                        matched_anything = True
                        taken += 1

            step_index += 1

        if not matched_anything:
            notes.append(
                f"{track['label']} is already satisfied; nothing was left to sequence."
            )

    return forced, reasons, notes


def generate_plan(
    units: list[dict[str, Any]],
    start_term: str,
    graduation_term: str,
    credits_per_term: int,
    include_summer: bool,
    term_credit_limits: dict[str, int] | None = None,
    in_progress_courses: list[dict[str, Any]] | None = None,
    completed_codes: set[str] | None = None,
    mcat_terms: list[str] | None = None,
    min_credits: int = MIN_TERM_CREDITS,
    include_dance: bool = False,
    mcat_term: str | None = None,
    advisor_tracks: list[dict[str, Any]] | None = None,
    course_prerequisites: dict[str, list[str]] | None = None,
    course_corequisites: dict[str, list[str]] | None = None,
    course_ceiling: int | None = None,
    mcat_credit_ceiling: int = DEFAULT_MCAT_CREDIT_CEILING,
    mcat_course_ceiling: int = DEFAULT_MCAT_COURSE_CEILING,
    term_course_limits: dict[str, int] | None = None,
    recurring: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a prerequisite-aware plan with visible empty and in-progress terms.

    A term's credit ceiling is one number: whatever ``term_credit_limits`` says
    for it, falling back to ``credits_per_term``. Marking a term as an MCAT term
    is a label on that same ceiling, not a second competing limit — so lowering
    the MCAT term's load means lowering that term's own limit.
    """
    prerequisites_by_code = COURSE_PREREQUISITES if course_prerequisites is None else course_prerequisites
    corequisites_by_code = COURSE_COREQUISITES if course_corequisites is None else course_corequisites
    terms = _generate_terms(start_term, graduation_term, include_summer)
    warnings: list[str] = []
    if not terms:
        return {
            "start_term": start_term,
            "graduation_term": graduation_term,
            "semesters": [],
            "planned_credits": 0.0,
            "min_credits": min_credits,
            "unplanned_requirements": [],
            "pace": {"outstanding_credits": 0.0, "open_terms": 0, "required_per_term": 0.0,
                     "credit_ceiling": credits_per_term, "unplaced_credits": 0.0, "feasible": False},
            "warnings": ["The planning window is invalid; use terms such as 'Fall 2026' and 'Spring 2029'."],
        }

    # A class ceiling that ignores the credit ceiling fights the student. Someone
    # who sets a 30-credit term is asking for more than six classes, and the
    # default must follow that choice rather than silently overrule it. At the
    # usual three credits a class, the derived ceiling never blocks a load the
    # credit ceiling already permits — it only stops the pathology it exists for,
    # a term holding fifteen entries worth six credits.
    if course_ceiling is None:
        course_ceiling = max(
            DEFAULT_TERM_COURSE_CEILING, math.ceil(credits_per_term / 3.0)
        )
    term_credit_limits = term_credit_limits or {}
    term_course_limits = term_course_limits or {}
    in_progress_courses = in_progress_courses or []
    completed_codes = completed_codes or set()
    mcat_set = _mcat_term_set(mcat_terms, mcat_term)
    term_lookup = {term: index for index, term in enumerate(terms)}
    semesters: list[dict[str, Any]] = []
    for term in terms:
        is_mcat = term in mcat_set
        # Most specific setting wins, and nothing here overrides the student.
        #
        # Marking a term for MCAT preparation now *does* something — the flag was
        # previously recorded and never read, so the exam term kept the same
        # ceiling as every other term and reliably came out overloaded. But the
        # exam term's load is the student's call, not this planner's: how much
        # study one person needs alongside coursework is not something a constant
        # can know. `mcat_credit_ceiling` and `mcat_course_ceiling` are the
        # numbers they are asked for when they tick pre-med, and they are used
        # exactly as given, in either direction.
        if term in term_credit_limits:
            credit_limit = term_credit_limits[term]
        elif is_mcat:
            credit_limit = mcat_credit_ceiling
        else:
            credit_limit = credits_per_term
        if term in term_course_limits:
            course_limit = term_course_limits[term]
        elif is_mcat:
            course_limit = mcat_course_ceiling
        else:
            course_limit = course_ceiling
        semesters.append(
            {
                "term": term,
                "term_code": _term_code(term),
                "courses": [],
                "total_credits": 0.0,
                "credit_limit": credit_limit,
                "course_limit": course_limit,
                "min_credits": min_credits,
                "is_mcat_term": is_mcat,
                "is_in_progress": False,
                "is_unplaced": False,
            }
        )

    unknown_mcat = sorted(term for term in mcat_set if term not in term_lookup)
    if unknown_mcat:
        warnings.append(
            f"{', '.join(unknown_mcat)} is marked as an MCAT term but sits outside "
            "the planning window, so no term was held light for it."
        )

    def _planned_course(
        identifier: str,
        code: str,
        label: str,
        credits: float,
        majors: list[str],
        requirement_ids: list[str],
        term: str,
        *,
        is_placeholder: bool = False,
        status: str = "planned",
        movable: bool = True,
        prerequisites: list[str] | None = None,
        corequisites: list[str] | None = None,
        alternatives: list[str] | None = None,
        attributes: list[str] | None = None,
        advisories: list[str] | None = None,
        justification: str = "",
        sequenced_by: str = "",
    ) -> dict[str, Any]:
        subject, catalog_number = split_course_code(code)
        return {
            "id": identifier,
            "code": code,
            "subject": subject,
            "catalog_number": catalog_number,
            "label": label,
            "credits": credits,
            "majors": majors,
            "requirement_ids": requirement_ids,
            "is_placeholder": is_placeholder,
            "status": status,
            "movable": movable,
            "prerequisites": prerequisites or [],
            "corequisites": corequisites or [],
            "alternatives": alternatives or [],
            "attributes": attributes or [],
            "advisories": advisories or [],
            "justification": justification,
            "sequenced_by": sequenced_by,
            "class_search_url": class_search_url(code, term) if subject else "",
        }

    placed_at: dict[str, int] = {code: -1 for code in completed_codes}
    for index, course in enumerate(in_progress_courses):
        friendly_term = _friendly_course_term(course["term"])
        if friendly_term not in term_lookup:
            placed_at[course["code"]] = -1
            continue
        semester_index = term_lookup[friendly_term]
        semester = semesters[semester_index]
        semester["courses"].append(
            _planned_course(
                f"in-progress:{course['term']}:{course['code']}:{index}",
                course["code"],
                course.get("title") or course["code"],
                course["credits"],
                ["In progress"],
                [],
                semester["term"],
                status="in_progress",
                movable=False,
                prerequisites=prerequisites_by_code.get(course["code"], []),
                corequisites=corequisites_by_code.get(course["code"], []),
                attributes=attributes_for(course["code"]),
                advisories=[note["id"] for note in notes_for_course(course["code"])],
                justification="Already registered for this term.",
            )
        )
        semester["total_credits"] = round(semester["total_credits"] + course["credits"], 2)
        semester["is_in_progress"] = True
        # What is already registered is not a planning choice, so a registered
        # term is never "over" its ceiling: both ceilings rise to meet it.
        semester["credit_limit"] = max(
            semester["credit_limit"], math.ceil(semester["total_credits"])
        )
        semester["course_limit"] = max(
            semester["course_limit"], len(semester["courses"])
        )
        placed_at[course["code"]] = semester_index

    # A standing personal commitment: a class the student keeps taking every
    # term until they finish. It is reserved before coursework is placed so it
    # actually holds room, and it is confined to the planning window the caller
    # gives — which is what stops it running past graduation. Registration in
    # the same subject already satisfies it for the active term.
    commitment = recurring or (
        {"label": "Dance class", "code": "DCE", "credits": 2.0, "include_summer": False}
        if include_dance
        else None
    )
    if commitment:
        prefix = str(commitment["code"]).strip().upper()
        for semester in semesters:
            if semester["term"].startswith("Summer") and not commitment.get("include_summer"):
                continue
            already = any(
                course["code"].upper().startswith(prefix) for course in semester["courses"]
            )
            if already:
                continue
            credits = float(commitment.get("credits", 0.0))
            semester["courses"].append(
                _planned_course(
                    f"commitment:{semester['term']}",
                    prefix,
                    str(commitment.get("label") or prefix),
                    credits,
                    ["Personal commitment"],
                    ["personal:commitment"],
                    semester["term"],
                    is_placeholder=True,
                    status="personal",
                    justification=(
                        "A standing commitment you asked to keep every term, not a "
                        "degree requirement. It stops at graduation."
                    ),
                )
            )
            semester["total_credits"] = round(semester["total_credits"] + credits, 2)

    unit_codes = {unit["code"] for unit in units}
    dependents: dict[str, set[str]] = defaultdict(set)
    for unit in units:
        for dependency in [
            *unit.get("prerequisites", prerequisites_by_code.get(unit["code"], [])),
            *unit.get("corequisites", corequisites_by_code.get(unit["code"], [])),
        ]:
            if dependency in unit_codes:
                dependents[dependency].add(unit["code"])

    def dependency_depth(code: str, seen: set[str] | None = None) -> int:
        seen = seen or set()
        if code in seen:
            return 0
        return max(
            (1 + dependency_depth(child, {*seen, code}) for child in dependents.get(code, set())),
            default=0,
        )

    first_open_index = next(
        (
            index
            for index, semester in enumerate(semesters)
            if not semester["is_in_progress"]
        ),
        len(semesters),
    )
    forced_terms, forced_reasons, forced_notes = _advisor_forced_terms(
        units, terms, placed_at, first_open_index, advisor_tracks
    )
    warnings.extend(forced_notes)

    ordered_units = sorted(
        enumerate(units),
        key=lambda item: (
            # An advisor's named sequence outranks everything else, earliest
            # step first, so it claims its terms before the generic packer.
            0 if item[0] in forced_terms else 1,
            forced_terms.get(item[0], 0),
            0 if item[1].get("status") == "premed" else 1,
            -dependency_depth(item[1]["code"]),
            1 if item[1].get("is_placeholder") else 0,
            item[0],
        ),
    )

    # A soft target per term, so packing spreads instead of front-loading.
    #
    # First-fit filled the earliest terms to their ceiling and left the last
    # terms nearly empty — the run that started this work put 26, 12.75, 15,
    # 12.25, 15 and then 3 credits across six terms. Each open term now gets a
    # share of the outstanding work proportional to its own ceiling, which also
    # means a term held light for the MCAT is asked to carry proportionally less
    # rather than being packed first and rescued afterwards.
    open_indexes = [
        index for index, semester in enumerate(semesters) if not semester["is_in_progress"]
    ]
    outstanding_credits = sum(unit["credits"] for _, unit in ordered_units)
    capacity = sum(semesters[index]["credit_limit"] for index in open_indexes) or 1.0
    targets = {
        index: min(
            semesters[index]["credit_limit"],
            # Never aim below the full-time floor: spreading eight credits of
            # work thinly over six terms is "even" and useless, because each of
            # those terms drops the student out of full-time standing.
            max(
                float(min_credits),
                outstanding_credits * semesters[index]["credit_limit"] / capacity,
            ),
        )
        for index in open_indexes
    }

    def _class_count(semester: dict[str, Any]) -> int:
        return sum(
            1
            for course in semester["courses"]
            if course["status"] != "milestone"
            and course["credits"] >= COUNTED_CLASS_MIN_CREDITS
        )

    def _item_count(semester: dict[str, Any]) -> int:
        return sum(1 for course in semester["courses"] if course["status"] != "milestone")

    def _fits(semester: dict[str, Any], unit: dict[str, Any], *, target: float | None) -> bool:
        """Both ceilings, and optionally the soft target, in one place.

        The course-count ceiling is the half that never existed. Only credits
        were ever checked, so zero-credit milestones passed unconditionally and
        a term could end up holding fifteen items worth six credits.
        """
        if semester["is_in_progress"]:
            return False
        if semester["total_credits"] + unit["credits"] > semester["credit_limit"] + 0.01:
            return False
        # A zero-credit gate — a thesis approval, a portfolio review — is not a
        # class the student attends, so it consumes neither ceiling. Counting it
        # against the class limit would push the very milestone that has to be
        # visible off the end of the map.
        if unit.get("status") != "milestone":
            if unit["credits"] >= COUNTED_CLASS_MIN_CREDITS and (
                _class_count(semester) + 1 > semester["course_limit"]
            ):
                return False
            if _item_count(semester) + 1 > max(DEFAULT_TERM_ITEM_CEILING, course_ceiling + 3):
                return False
        if target is not None and semester["total_credits"] + unit["credits"] > target + 0.01:
            return False
        return True

    overflow: list[dict[str, Any]] = []
    for unit_index, unit in ordered_units:
        placed = False
        prerequisites = unit.get("prerequisites", prerequisites_by_code.get(unit["code"], []))
        corequisites = unit.get("corequisites", corequisites_by_code.get(unit["code"], []))
        earliest_index = 0
        known_prerequisite = False
        for prerequisite in prerequisites:
            if prerequisite in placed_at:
                earliest_index = max(earliest_index, placed_at[prerequisite] + 1)
                known_prerequisite = True
        for corequisite in corequisites:
            if corequisite in placed_at:
                earliest_index = max(earliest_index, placed_at[corequisite])
                known_prerequisite = True
        pending_dependencies = [
            dependency
            for dependency in [*prerequisites, *corequisites]
            if dependency in unit_codes and dependency not in placed_at
        ]
        if pending_dependencies:
            overflow.append(
                _planned_course(
                    f"unplaced:{unit['code']}:{unit_index}",
                    unit["code"],
                    unit["label"],
                    unit["credits"],
                    unit["majors"],
                    unit["requirement_ids"],
                    UNPLACED_TERM,
                    is_placeholder=unit["is_placeholder"],
                    status=unit.get("status", "planned"),
                    prerequisites=prerequisites,
                    corequisites=corequisites,
                    justification=unit.get("justification", ""),
                )
            )
            warnings.append(
                f"{unit['code']} could not be placed before {', '.join(pending_dependencies)}."
            )
            continue
        if (prerequisites or corequisites) and not known_prerequisite:
            warnings.append(
                f"Verify prerequisites for {unit['code']}; its prerequisite is not visible in this plan."
            )

        # Milestones belong as late as the window allows: a thesis approval or
        # similar gate is the last thing to happen, not the first free slot.
        search_order: range | list[int] = range(earliest_index, len(semesters))
        if unit.get("status") == "milestone":
            search_order = list(range(len(semesters) - 1, earliest_index - 1, -1))
        elif unit_index in forced_terms:
            target = max(earliest_index, forced_terms[unit_index])
            # Try the advisor's term first, then fall forward from it.
            search_order = list(range(target, len(semesters)))

        # Placement takes the earliest term the unit actually fits in. Evening
        # out the load is a separate concern, handled by `_rebalance_terms`
        # afterwards, because folding it in here made placement non-monotonic:
        # a one-credit lab could leapfrog into a later term whose share of the
        # target was still unspent, stranding it a semester away from the
        # lecture it belongs with.
        for semester_index in search_order:
            semester = semesters[semester_index]
            if not _fits(semester, unit, target=None):
                continue
            identifier = ":".join(unit.get("requirement_ids", [])) or str(unit_index)
            semester["courses"].append(
                _planned_course(
                    f"planned:{unit['code']}:{identifier}:{unit_index}",
                    unit["code"],
                    unit["label"],
                    unit["credits"],
                    unit["majors"],
                    unit["requirement_ids"],
                    semester["term"],
                    is_placeholder=unit["is_placeholder"],
                    status=unit.get("status", "planned"),
                    prerequisites=prerequisites,
                    corequisites=corequisites,
                    alternatives=unit.get("alternatives"),
                    attributes=unit.get("attributes") or attributes_for(unit["code"]),
                    advisories=unit.get("advisories")
                    or [note["id"] for note in notes_for_course(unit["code"])],
                    justification=unit.get("justification", ""),
                    sequenced_by=forced_reasons.get(unit_index, ""),
                )
            )
            semester["total_credits"] = round(semester["total_credits"] + unit["credits"], 2)
            placed_at[unit["code"]] = semester_index
            placed = True
            if unit_index in forced_terms and semester_index != forced_terms[unit_index]:
                warnings.append(
                    f"{unit['code']} was asked for in {terms[forced_terms[unit_index]]} but "
                    f"that term was full, so it moved to {semester['term']}. Raise the "
                    f"{terms[forced_terms[unit_index]]} credit limit to hold it there."
                )
            break
        if not placed:
            overflow.append(
                _planned_course(
                    f"unplaced:{unit['code']}:{unit_index}",
                    unit["code"],
                    unit["label"],
                    unit["credits"],
                    unit["majors"],
                    unit["requirement_ids"],
                    UNPLACED_TERM,
                    is_placeholder=unit["is_placeholder"],
                    status=unit.get("status", "planned"),
                    prerequisites=prerequisites,
                    corequisites=corequisites,
                    alternatives=unit.get("alternatives"),
                    attributes=unit.get("attributes") or attributes_for(unit["code"]),
                    advisories=unit.get("advisories")
                    or [note["id"] for note in notes_for_course(unit["code"])],
                    justification=unit.get("justification", ""),
                    sequenced_by=forced_reasons.get(unit_index, ""),
                )
            )

    # What the student's own target actually demands of each term.
    #
    # The graduation term is an input now, so the useful question is no longer
    # "when will they finish" but "does the ceiling they picked get them there".
    # Answering it with a number they can act on beats a bare overflow count.
    open_semesters = [
        semester for semester in semesters
        if not semester["is_in_progress"] and not semester.get("is_unplaced")
    ]
    placed_outstanding = sum(
        course["credits"]
        for semester in open_semesters
        for course in semester["courses"]
        if course["status"] not in ("in_progress",)
    )
    overflow_credits = round(sum(course["credits"] for course in overflow), 2)
    outstanding = round(placed_outstanding + overflow_credits, 2)
    open_count = len(open_semesters)
    required_per_term = round(outstanding / open_count, 1) if open_count else 0.0
    headroom = sum(s["credit_limit"] for s in open_semesters)
    pace = {
        "outstanding_credits": outstanding,
        "open_terms": open_count,
        "required_per_term": required_per_term,
        "credit_ceiling": credits_per_term,
        "unplaced_credits": overflow_credits,
        "feasible": overflow_credits <= 0.01,
    }

    if overflow:
        # Name the number that would work rather than listing four vague options.
        shortfall = round(outstanding - headroom, 2)
        needed = math.ceil(required_per_term) if open_count else credits_per_term
        remedy = (
            f"About {needed} credits a term would fit it. "
            if needed > credits_per_term
            else "Prerequisite order, not total capacity, is what is blocking them. "
        )
        summers = "" if include_summer else "Adding summer terms is the other lever. "
        warnings.append(
            f"{len(overflow)} item{'s' if len(overflow) != 1 else ''} "
            f"({overflow_credits:g} credits) did not fit before {graduation_term}. "
            f"Your ceiling is {credits_per_term} credits a term across {open_count} "
            f"remaining term{'s' if open_count != 1 else ''}, which holds {headroom:g}; "
            f"you have {outstanding:g} to place"
            + (f", so you are {shortfall:g} short. " if shortfall > 0 else ". ")
            + remedy
            + summers
            + "They are waiting at the end of the map until you place them."
        )
    elif open_count and required_per_term > credits_per_term + 0.01:
        warnings.append(
            f"Graduating by {graduation_term} needs about {required_per_term:g} credits "
            f"a term, above the {credits_per_term} you set. The map fits only because "
            "some terms run over; raise the ceiling or move graduation later."
        )
    settled_targets = _settled_targets(semesters, min_credits)
    warnings.extend(_rebalance_terms(semesters, settled_targets, placed_at, min_credits))
    warnings.extend(_top_up_light_terms(semesters, min_credits, placed_at))
    warnings.extend(under_minimum_warnings(semesters, min_credits))
    planned_credits = round(
        sum(
            course["credits"]
            for semester in semesters
            for course in semester["courses"]
            if course["status"] != "in_progress"
        ),
        2,
    )
    # The holding area is appended last so it reads as the end of the runway.
    # It carries no ceiling and no floor, because it is not a term.
    if overflow:
        semesters.append(
            {
                "term": UNPLACED_TERM,
                "term_code": "",
                "courses": overflow,
                "total_credits": round(
                    sum(course["credits"] for course in overflow), 2
                ),
                "credit_limit": 99,
                "min_credits": 0,
                "is_mcat_term": False,
                "is_in_progress": False,
                "is_unplaced": True,
                "note": "",
            }
        )
    return {
        "start_term": start_term,
        "graduation_term": graduation_term,
        "semesters": semesters,
        "planned_credits": planned_credits,
        "min_credits": min_credits,
        "unplanned_requirements": [course["label"] for course in overflow],
        "pace": pace,
        "warnings": list(dict.fromkeys(warnings)),
    }


def _settled_targets(
    semesters: list[dict[str, Any]],
    min_credits: int,
) -> dict[int, float]:
    """Each open term's fair share of the work actually on the map.

    Computed after placement rather than before it, so personal commitments and
    anything already registered count towards a term's load instead of being
    invisible to the balance.
    """
    open_indexes = [
        index
        for index, semester in enumerate(semesters)
        if not semester["is_in_progress"] and not semester.get("is_unplaced")
    ]
    placed = sum(semesters[index]["total_credits"] for index in open_indexes)

    # Balance *within the span the work actually needs*, never across the whole
    # window. Spreading two classes evenly over six terms is arithmetically even
    # and academically absurd: it delays graduation to flatten a graph. Terms
    # past the horizon get no share, so nothing is ever moved into them.
    horizon: list[int] = []
    running = 0.0
    for index in open_indexes:
        if running >= placed - 0.01:
            break
        horizon.append(index)
        running += semesters[index]["credit_limit"]
    if not horizon:
        horizon = open_indexes[:1]

    capacity = sum(semesters[index]["credit_limit"] for index in horizon) or 1.0
    targets = {
        index: min(
            semesters[index]["credit_limit"],
            max(float(min_credits), placed * semesters[index]["credit_limit"] / capacity),
        )
        for index in horizon
    }
    # A term beyond the horizon is not a destination: give it a target it can
    # never be under, so the rebalancer will not push work into it.
    for index in open_indexes:
        targets.setdefault(index, 0.0)
    return targets


def _can_move(
    course: dict[str, Any],
    destination_index: int,
    semesters: list[dict[str, Any]],
    placed_at: dict[str, int],
) -> bool:
    """Is it safe to move this class to ``destination_index``?

    Safe means three things: the class is movable at all, everything it depends
    on still lands before it, and nothing that depends on *it* is left stranded
    ahead of it.
    """
    if not course["movable"] or course["status"] in {"milestone", "personal"}:
        return False
    # A term an advisor named is an instruction; balancing must not undo it.
    if course.get("sequenced_by"):
        return False
    for prerequisite in course["prerequisites"]:
        if placed_at.get(prerequisite, -1) >= destination_index:
            return False
    for corequisite in course["corequisites"]:
        if placed_at.get(corequisite, -1) > destination_index:
            return False
        # A lecture and its lab belong in the same term. Evening out a credit
        # total is never a good enough reason to separate them.
        if placed_at.get(corequisite, destination_index) != destination_index:
            return False
    for stage in semesters:
        for other in stage["courses"]:
            if other["id"] == course["id"]:
                continue
            if course["code"] in other["prerequisites"]:
                if placed_at.get(other["code"], len(semesters)) <= destination_index:
                    return False
            if course["code"] in other["corequisites"]:
                if placed_at.get(other["code"], len(semesters)) < destination_index:
                    return False
    return True


def _rebalance_terms(
    semesters: list[dict[str, Any]],
    targets: dict[int, float],
    placed_at: dict[str, int],
    min_credits: int,
) -> list[str]:
    """Even out the load once everything has a term.

    Placement fills the earliest term a class fits in, which on its own packs
    the front of the window to the ceiling and leaves the back nearly empty —
    the run that opened this work ended 26, 12.75, 15, 12.25, 15, 3 across six
    terms. This pass moves work *later*, out of terms above their share and into
    terms below it, which is the direction the old `_top_up_light_terms` could
    never go: it only ever pulled work earlier, reinforcing the skew.

    Nothing is moved that would break a prerequisite chain, split a class from
    its corequisite, or drop the source term under the full-time floor. When no
    safe move exists the plan is simply left as it is.
    """
    messages: list[str] = []
    movable_indexes = [
        index
        for index, semester in enumerate(semesters)
        if not semester["is_in_progress"] and not semester.get("is_unplaced")
    ]
    if len(movable_indexes) < 2:
        return messages

    for _sweep in range(len(movable_indexes) * 3):
        source_index = max(
            movable_indexes,
            key=lambda i: semesters[i]["total_credits"] - targets.get(i, 0.0),
        )
        source = semesters[source_index]
        excess = source["total_credits"] - targets.get(source_index, 0.0)
        if excess <= 0.01:
            break

        moved = False
        # Prefer the emptiest term relative to its own share, so the class lands
        # where it is most needed rather than merely somewhere legal.
        for destination_index in sorted(
            movable_indexes,
            key=lambda i: semesters[i]["total_credits"] - targets.get(i, 0.0),
        ):
            if destination_index == source_index:
                continue
            destination = semesters[destination_index]
            if destination["total_credits"] >= targets.get(destination_index, 0.0) - 0.01:
                continue
            for course in sorted(
                source["courses"], key=lambda c: -c["credits"]
            ):
                if destination["total_credits"] + course["credits"] > destination["credit_limit"] + 0.01:
                    continue
                classes = sum(
                    1
                    for item in destination["courses"]
                    if item["status"] != "milestone"
                    and item["credits"] >= COUNTED_CLASS_MIN_CREDITS
                )
                if course["credits"] >= COUNTED_CLASS_MIN_CREDITS and (
                    classes + 1 > destination["course_limit"]
                ):
                    continue
                # Moving must not create the opposite problem in the source.
                if source["total_credits"] - course["credits"] < min_credits - 0.01:
                    continue
                if not _can_move(course, destination_index, semesters, placed_at):
                    continue
                source["courses"] = [
                    item for item in source["courses"] if item["id"] != course["id"]
                ]
                source["total_credits"] = round(
                    source["total_credits"] - course["credits"], 2
                )
                destination["courses"].append(course)
                destination["total_credits"] = round(
                    destination["total_credits"] + course["credits"], 2
                )
                placed_at[course["code"]] = destination_index
                messages.append(
                    f"{course['code']} moved to {destination['term']} to even out "
                    "the load across your remaining terms."
                )
                moved = True
                break
            if moved:
                break
        if not moved:
            break
    return messages


def _top_up_light_terms(
    semesters: list[dict[str, Any]],
    min_credits: int,
    placed_at: dict[str, int],
) -> list[str]:
    """Pull work earlier into a term sitting under the full-time floor.

    The packer fills terms front to back, which can leave an early term short
    while later ones are full.  Being short is not a cosmetic problem here: below
    the floor the student stops being full time and loses scholarship money.  So
    any class from a later term that fits under this term's ceiling, and whose
    prerequisites are already behind it, gets moved up.

    Nothing is forced.  When no class fits — usually because the term's own
    ceiling leaves no room for one more 3-credit course — the term is left short
    and ``under_minimum_warnings`` says so.
    """
    messages: list[str] = []
    for index, semester in enumerate(semesters):
        if semester["is_in_progress"] or not semester["courses"]:
            continue
        if semester.get("is_unplaced") or semester["total_credits"] >= min_credits:
            continue

        moved = True
        while moved and semester["total_credits"] < min_credits:
            moved = False
            headroom = semester["credit_limit"] - semester["total_credits"]
            for later in semesters[index + 1:]:
                if later["is_in_progress"]:
                    continue
                candidate = next(
                    (
                        course
                        for course in later["courses"]
                        if course["movable"]
                        and course["status"] not in {"milestone", "personal"}
                        and course["credits"] <= headroom + 0.01
                        and all(
                            placed_at.get(prerequisite, -1) < index
                            for prerequisite in course["prerequisites"]
                        )
                        and all(
                            placed_at.get(corequisite, -1) <= index
                            for corequisite in course["corequisites"]
                        )
                        # Moving a class earlier must not strand something that
                        # depends on it in the same term or before it.
                        and not any(
                            course["code"] in other["prerequisites"]
                            and placed_at.get(other["code"], len(semesters)) <= index
                            for stage in semesters
                            for other in stage["courses"]
                        )
                    ),
                    None,
                )
                if candidate is None:
                    continue
                later["courses"] = [
                    course for course in later["courses"] if course["id"] != candidate["id"]
                ]
                later["total_credits"] = round(later["total_credits"] - candidate["credits"], 2)
                semester["courses"].append(candidate)
                semester["total_credits"] = round(
                    semester["total_credits"] + candidate["credits"], 2
                )
                placed_at[candidate["code"]] = index
                messages.append(
                    f"{candidate['code']} was moved up to {semester['term']} to keep it at or "
                    f"above the {min_credits}-credit minimum."
                )
                moved = True
                break
    return messages


def under_minimum_warnings(
    semesters: list[dict[str, Any]],
    min_credits: int,
) -> list[str]:
    """Flag terms scheduled below the full-time floor the student must hold.

    An empty term is not flagged: nothing is scheduled there yet, so it is a
    gap in the plan rather than a term that would drop them below full time.
    A term whose own ceiling sits under the floor is flagged against its
    ceiling, because no arrangement of classes inside it can reach the floor.
    """
    messages: list[str] = []
    for semester in semesters:
        if not semester["courses"] or semester["is_in_progress"]:
            continue
        if semester.get("is_unplaced"):
            continue
        if semester["credit_limit"] < min_credits:
            messages.append(
                f"{semester['term']} is capped at {semester['credit_limit']} credits, "
                f"below the {min_credits}-credit minimum you have to stay above."
            )
        elif semester["total_credits"] < min_credits:
            # The usual cause is a ceiling with no room for one more 3-credit
            # class, so name the ceiling that would fit one.
            needed = math.ceil(semester["total_credits"] + 3)
            suggestion = (
                f" Raising its ceiling to {needed} would let one more 3-credit class in."
                if needed > semester["credit_limit"]
                else ""
            )
            messages.append(
                f"{semester['term']} holds "
                f"{semester['total_credits']:g} credits, under the {min_credits}-credit "
                f"minimum for full-time status and scholarships.{suggestion}"
            )
    return messages




def generate_semester_plan(
    remaining_requirements: list[dict[str, Any]],
    current_term: str,
    graduation_date: str,
    min_credits: int = 12,
    max_credits: int = 18,
) -> dict[str, Any]:
    """Compatibility wrapper for the original public helper."""
    audit = {"requirements": remaining_requirements}
    units, unplanned = build_planning_units([audit], set(), set())
    parsed = _parse_term(current_term)
    start = (
        f"{parsed[0]} {parsed[1]}"
        if parsed
        else "Fall 2026"
    )
    result = generate_plan(units, start, graduation_date or "Fall 2028", max_credits, False)
    return {
        "semesters": [
            {
                "term_code": f"{ {'Spring': 'SP', 'Summer': 'SU', 'Fall': 'FA'}[semester['term'].split()[0]]}{semester['term'][-2:]}",
                "term_label": semester["term"],
                "courses": [course["code"] for course in semester["courses"]],
                "total_credits": semester["total_credits"],
                "major_breakdown": {},
            }
            for semester in result["semesters"]
        ],
        "total_remaining_credits": result["planned_credits"],
        "warnings": [*result["warnings"], *unplanned],
    }
