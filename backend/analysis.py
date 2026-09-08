"""Stateless orchestration for audit parsing, overlap, recommendations, and plan."""

from __future__ import annotations

import time
from typing import Any

from .course_rules import (
    ADVISORY_NOTES,
    MIN_TERM_CREDITS,
    attributes_for,
    equivalence_for,
)
from .graduation_check import evaluate_graduation_readiness
from .overlap_engine import compute_overlaps
from .pdf_parser import parse_dars_bytes
from .premed import evaluate_premed, remaining_premed_units
from .semester_planner import (
    build_planning_units,
    build_recommendations,
    generate_plan,
    sort_planning_units,
)


def _deduplicate_global_courses(audits: list[dict[str, Any]]) -> list[dict[str, Any]]:
    best: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for audit in audits:
        for course in audit.pop("courses"):
            key = (course["term"], course["subject"], course["number"], course["grade"])
            existing = best.get(key)
            if existing is None or (course["credits"], len(course["title"])) > (
                existing["credits"],
                len(existing["title"]),
            ):
                best[key] = course
    return sorted(best.values(), key=lambda course: (course["term"], course["code"]))


def _relevant_advisories(audits: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep only the major-map notes that apply to the programs uploaded.

    A note about a Finance rule is noise when no Finance audit was analyzed, and
    a note whose courses are all already complete no longer needs deciding.
    """
    programs = {audit["name"] for audit in audits}
    remaining_or_active = {
        code
        for audit in audits
        for requirement in audit["requirements"]
        if requirement["status"] != "complete"
        for code in [
            *requirement.get("course_options", []),
            *requirement.get("courses_in_progress", []),
        ]
    }
    notes: list[dict[str, Any]] = []
    for note in ADVISORY_NOTES:
        if note["program"] not in programs:
            continue
        if note["courses"] and not (set(note["courses"]) & remaining_or_active):
            continue
        notes.append(dict(note))
    return notes


def _apply_equivalences(
    audits: list[dict[str, Any]],
    held_codes: set[str],
) -> tuple[list[dict[str, Any]], list[str]]:
    """Clear requirements a confirmed course equivalence already covers.

    DARS cannot express "FIN 303 satisfies FIN 361 as well", so it keeps listing
    the second requirement.  Acting on the equivalence removes work the audit
    says is owed, which is why nothing here is inferred: a rule fires only when
    the student actually holds the triggering course, and it records the document
    it came from on the requirement it touches.

    The requirement is marked, not deleted, and its status stays whatever DARS
    said.  The hours it frees are returned as a replacement unit so the program's
    own hour total still adds up.
    """
    replacements: list[dict[str, Any]] = []
    notes: list[str] = []

    for rule in equivalence_for(held_codes):
        trigger = next(code for code in rule["when_holding"] if code in held_codes)
        attribution = f"{trigger} per the {rule['source']}, {rule['confirmed_by']}"
        cleared: list[str] = []

        for audit in audits:
            if audit["name"] != rule["program"]:
                continue
            for requirement in audit["requirements"]:
                if requirement["status"] != "remaining":
                    continue
                options = set(requirement.get("course_options", []))
                # Match only a requirement the equivalent course fully answers,
                # never a broad elective block that merely lists it as an option.
                if not options or not options.issubset(set(rule["also_clears"])):
                    continue
                requirement["satisfied_by"] = attribution
                # The freed hours move to the replacement slot below, so they
                # must not be counted as outstanding twice.
                requirement["credits_remaining"] = 0.0
                cleared.append(requirement["name"].rstrip(":"))

        if not cleared:
            continue

        replacement = rule["replacement"]
        replacements.append(
            {
                "code": replacement["label"],
                "label": replacement["label"],
                "credits": replacement["credits"],
                "majors": [rule["program"]],
                "requirement_ids": [f"equivalence:{rule['id']}"],
                "requirement_names": [replacement["label"]],
                "sections": [f"{rule['program']} Major - equivalence replacement"],
                "alternatives": list(replacement["options"]),
                "is_placeholder": True,
                "status": "planned",
                "prerequisites": [],
                "corequisites": [],
                "attributes": [],
                "advisories": [rule["id"]],
                "justification": (
                    f"Reserved for a {rule['program']} requirement you still choose. "
                    + replacement["reason"]
                ),
            }
        )
        notes.append(
            f"{trigger} clears {', '.join(cleared)} per the {rule['source']}. "
            f"A {replacement['label']} was added in its place so "
            f"{rule['program']} still reaches its required hours."
        )

    return replacements, notes


def _offer_attribute_courses(units: list[dict[str, Any]]) -> None:
    """Let a General Studies placeholder offer courses that already carry it.

    SCM 300 is required for the Finance core *and* carries Sustainability, so it
    can clear a SUST placeholder rather than adding a fourth class. The
    placeholder still has to be chosen by hand — this only puts the candidate in
    front of the student instead of leaving them to spot it.
    """
    required_codes = {
        unit["code"] for unit in units if not unit["is_placeholder"]
    }
    for unit in units:
        if not unit["is_placeholder"]:
            continue
        wanted = {
            criterion.removeprefix("ASU General Studies ")
            for name in unit.get("requirement_names", [])
            for criterion in [name]
        }
        # The criterion lives on the label for General Studies placeholders.
        label = unit.get("label", "")
        candidates = sorted(
            code
            for code in required_codes
            for attribute in attributes_for(code)
            if attribute in wanted
            or f"{attribute} approved elective" == label
            or attribute.casefold() in label.casefold()
        )
        if candidates:
            unit["alternatives"] = list(
                dict.fromkeys([*candidates, *unit.get("alternatives", [])])
            )
            unit["justification"] = (
                unit.get("justification", "").rstrip(".")
                + f". {candidates[0]} is already required elsewhere in the plan and "
                "carries this General Studies area, so choosing it here may avoid "
                "an extra class — confirm the double-count with an advisor."
            )


def analyze_documents(
    documents: list[tuple[str, bytes]],
    start_term: str,
    graduation_term: str,
    credits_per_term: int,
    include_summer: bool,
    term_credit_limits: dict[str, int] | None = None,
    mcat_terms: list[str] | None = None,
    min_credits: int = MIN_TERM_CREDITS,
) -> dict[str, Any]:
    started = time.perf_counter()
    parsed = [parse_dars_bytes(data, filename) for filename, data in documents]
    warnings: list[str] = []

    # Keep the richest audit when the same program was uploaded twice.
    by_program: dict[str, dict[str, Any]] = {}
    for audit in parsed:
        existing = by_program.get(audit["name"])
        if existing is None or len(audit["requirements"]) > len(existing["requirements"]):
            if existing is not None:
                warnings.append(f"Used the more complete {audit['name']} audit and ignored a duplicate.")
            by_program[audit["name"]] = audit
        else:
            warnings.append(f"Ignored duplicate audit for {audit['name']}.")
    audits = list(by_program.values())

    courses = _deduplicate_global_courses(audits)
    completed = [course for course in courses if course["status"] == "complete"]
    in_progress = [course for course in courses if course["status"] == "in_progress"]
    completed_codes = {course["code"] for course in completed}
    in_progress_codes = {course["code"] for course in in_progress}
    premed = evaluate_premed(courses)

    # Equivalences run before planning so a cleared requirement never becomes a
    # scheduled unit in the first place.
    replacement_units, equivalence_notes = _apply_equivalences(
        audits, completed_codes | in_progress_codes
    )
    warnings.extend(equivalence_notes)

    units, advisor_items = build_planning_units(
        audits,
        completed_codes=completed_codes,
        in_progress_codes=in_progress_codes,
    )
    units.extend(replacement_units)
    existing_unit_codes = {unit["code"] for unit in units}
    units.extend(
        unit
        for unit in remaining_premed_units(premed)
        if unit["code"] not in existing_unit_codes
    )
    _offer_attribute_courses(units)
    # Pre-med and equivalence-replacement units were appended, so the list has to
    # go back into priority order before anything reads it as a queue.
    units = sort_planning_units(units)
    overlaps = compute_overlaps(audits)
    recommendations = build_recommendations(units)
    plan = generate_plan(
        units,
        start_term=start_term,
        graduation_term=graduation_term,
        credits_per_term=credits_per_term,
        include_summer=include_summer,
        term_credit_limits=term_credit_limits,
        in_progress_courses=in_progress,
        completed_codes=completed_codes,
        mcat_terms=mcat_terms,
        min_credits=min_credits,
        include_dance=True,
    )
    plan["unplanned_requirements"] = list(
        dict.fromkeys([*plan["unplanned_requirements"], *advisor_items])
    )

    for audit in audits:
        warnings.extend(f"{audit['source_file']}: {warning}" for warning in audit["warnings"])

    primary_mcat_term = next(iter(mcat_terms or []), None)
    readiness = evaluate_graduation_readiness(audits, plan, premed, primary_mcat_term)
    advisories = _relevant_advisories(audits)

    return {
        "audits": audits,
        "readiness": readiness,
        "completed_courses": completed,
        "in_progress_courses": in_progress,
        "overlaps": overlaps,
        "recommendations": recommendations,
        "premed": premed,
        "plan": plan,
        "advisories": advisories,
        "warnings": list(dict.fromkeys(warnings)),
        "processing_ms": round((time.perf_counter() - started) * 1000),
    }
