"""Turn parsed requirements into schedulable units.

This replaces ``backend.cloud.engine._units``, which decided what to schedule
from the public ``kind`` field.  Because ``kind`` was ``milestone`` for anything
whose title mentioned "upper division", and credit-bearing milestones were
skipped, every directed upper-division elective block vanished from the map —
12 to 27 credits per audit, with no warning.  Units are now built from
``category``, which is derived structurally (see :mod:`backend.asu_catalog`).

Three rules shape the output:

*Name a course whenever DARS names one.*  ``COURSE LIST: MGT 300 MGT 303`` is a
choice between two real classes, not an unknown.  A small pool is resolved to a
concrete course with the rest offered as alternatives, so the student gets a
course code and a working Class Search link.  A large pool stays a labelled slot
— picking two of twenty-one advanced-skills courses is the student's decision,
and pretending otherwise would be a worse answer than an honest placeholder.

*Never drop a slot.*  An unnamed elective, an unresolved condition, a block we
could not categorize: each still becomes a unit carrying its hours, because a
visible "choose something" slot is the only version a student can act on.

*Give every slot its own identity.*  Splitting a nine-hour block into three
fragments that share one code corrupted ``placed_at`` and made the fragments
sort adjacently, which is what packed electives into a single term.
"""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Any

from .course_rules import substitutions_for
from .asu_catalog import (
    DEFAULT_COURSE_CREDITS,
    SCHEDULABLE_CATEGORIES,
    DesignationVocabulary,
)

#: Above this many options, choosing for the student is presumptuous; the slot
#: stays a labelled placeholder and carries every option as an alternative.
MAX_OPTIONS_TO_RESOLVE = 4

#: Longest slot label that still reads cleanly in a term card on the map.
MAX_SLOT_LABEL = 58

#: Known credit values for courses whose hours DARS states only as a block total.
KNOWN_CREDITS: dict[str, float] = {
    "BIO 181": 4.0, "BIO 182": 4.0, "CHM 113": 4.0, "CHM 116": 4.0,
    "CHM 117": 3.0, "CHM 118": 3.0, "CHM 111": 1.0, "CHM 112": 1.0,
    "CHM 233": 3.0, "CHM 234": 3.0, "CHM 237": 1.0, "CHM 238": 1.0,
    "CHM 333": 3.0, "CHM 334": 3.0, "CHM 337": 1.0, "CHM 338": 1.0,
    "PHY 111": 3.0, "PHY 112": 3.0, "PHY 113": 1.0, "PHY 114": 1.0,
    "BCH 361": 3.0,
}

_TITLE_NOISE_RE = re.compile(
    r"\s*:\s*[\d.]+\s*hours?.*$|\s*[-–]\s*\d+\s*(?:hours?|courses?).*$|"
    r",\s*[A-D][+-]?\s*minimum.*$|\s*:\s*$",
    re.IGNORECASE,
)


def clean_title(name: str) -> str:
    """"Upper Division Capstone Course: 3 hours, C minimum" -> the course name."""
    cleaned = _TITLE_NOISE_RE.sub("", name).strip(" .:,-")
    return re.sub(r"\s+", " ", cleaned)


def slot_label(
    requirement: dict[str, Any],
    vocabulary: DesignationVocabulary | None = None,
) -> str:
    """A short, student-readable name for an unresolved slot.

    Never the raw DARS sentence.  "Sustainability (SUST): 3 hours" becomes
    "Sustainability (SUST) elective" — something that reads like a thing to go
    and choose, and that fits in a box on the map.
    """
    resolver = vocabulary or DesignationVocabulary()
    designations = requirement.get("designations") or []
    if designations:
        code = designations[0]
        full = f"{resolver.label(code)} elective"
        # A few area names are long enough to break the card they sit in —
        # "Global Communities, Societies and Individuals (GCSI)" is one. The
        # bare code still identifies the area, and the full name stays on the
        # slot's criteria and in its justification.
        return full if len(full) <= MAX_SLOT_LABEL else f"{code} elective"
    wildcards = requirement.get("wildcards") or []
    if wildcards:
        return str(wildcards[0]["label"])
    title = clean_title(requirement.get("name", ""))
    if not title:
        title = clean_title(requirement.get("section", "")) or "Elective"
    if len(title) > MAX_SLOT_LABEL:
        title = f"{clean_title(requirement.get('section', ''))} elective"[:58]
    return title


def _slot_credits(requirement: dict[str, Any], count: int, index: int) -> float:
    """Split a block's outstanding hours across its slots, remainder first."""
    outstanding = requirement.get("credits_remaining") or requirement.get("credits_required") or 0.0
    if outstanding <= 0:
        return DEFAULT_COURSE_CREDITS
    if count <= 1:
        return round(outstanding, 2)
    base = outstanding / count
    # Keep whole-credit slots where the split is clean, so a 9/3 block reads as
    # three 3-credit classes rather than three 2.9999s.
    if abs(base - round(base)) < 0.01:
        return float(round(base))
    if index < count - 1:
        return round(min(DEFAULT_COURSE_CREDITS, base), 2)
    return round(outstanding - round(min(DEFAULT_COURSE_CREDITS, base), 2) * (count - 1), 2)


def build_units(
    audits: list[dict[str, Any]],
    held_codes: set[str],
    prerequisites: dict[str, list[str]] | None = None,
    corequisites: dict[str, list[str]] | None = None,
    vocabulary: DesignationVocabulary | None = None,
    max_units: int = 1500,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Build schedulable units from every audit, merged across programs.

    Returns ``(units, notes)``.  ``notes`` are student-facing sentences about
    what still needs a human decision.
    """
    prerequisites = prerequisites or {}
    corequisites = corequisites or {}
    raw: list[dict[str, Any]] = []
    notes: list[str] = []

    for audit in audits:
        program = audit["name"]
        parents = {
            requirement.get("parent_id")
            for requirement in audit["requirements"]
            if requirement.get("parent_id")
        }
        for requirement in audit["requirements"]:
            if requirement["status"] == "complete" or requirement.get("satisfied_by"):
                continue
            category = requirement.get("category") or "unclassified"
            # Rules, caps and totals are reported, never scheduled.
            if category not in SCHEDULABLE_CATEGORIES:
                continue
            if requirement["id"] in parents:
                notes.append(
                    f"{program}: {clean_title(requirement['name'])} summarizes nested "
                    "requirements; review the aggregate separately."
                )
                continue

            outstanding = requirement.get("credits_remaining") or 0.0
            # A gate carrying no hours — the Barrett thesis approval, a portfolio
            # review — must stay on the map without inventing credits. It can be
            # flagged by either signal: the Barrett thesis categorizes as
            # ``honors`` while its ``kind`` stays ``project``, and reading only
            # one of the two dropped it from the plan entirely.
            zero_credit_gate = (
                (category == "project" or requirement.get("kind") == "project")
                and requirement.get("credits_required", 0.0) <= 0
                and outstanding <= 0
            )
            if outstanding <= 0 and not zero_credit_gate:
                if requirement["status"] == "in_progress":
                    continue
                notes.append(
                    f"{program}: confirm the credits and completion state of "
                    f"{clean_title(requirement['name'])}."
                )
                continue

            options = [
                code
                for code in requirement.get("course_options", [])
                if code not in held_codes
            ]
            count = 1 if zero_credit_gate else max(1, int(requirement.get("required_count") or 1))
            # One named course is one class. DARS states its hours as a block
            # total, and splitting "FIN 361: 3 hours" into three one-credit
            # fragments would invent classes that do not exist.
            if len(options) == 1 and count > 1:
                count = 1
            # Never claim more slots than the block has hours for.
            if not zero_credit_gate and outstanding > 0:
                count = min(count, max(1, round(outstanding / 1.0)))

            resolvable = 0 < len(options) <= MAX_OPTIONS_TO_RESOLVE
            if not resolvable and options:
                notes.append(
                    f"{program}: choose {count} approved course"
                    f"{'s' if count != 1 else ''} for "
                    f"{clean_title(requirement['name'])} from its {len(options)} options."
                )
            elif not options and not zero_credit_gate:
                notes.append(
                    f"{program}: {clean_title(requirement['name'])} needs "
                    "advisor-selected coursework; its hours are reserved on the map."
                )

            for index in range(count):
                named = resolvable and index < len(options)
                if named:
                    code = options[index]
                    label = code
                    credits = KNOWN_CREDITS.get(code, _slot_credits(requirement, count, index))
                    alternatives = [o for o in options if o != code]
                else:
                    label = slot_label(requirement, vocabulary)
                    # Each slot gets a distinct code. Sharing one made every
                    # fragment sort adjacently and collide in `placed_at`.
                    code = label if count == 1 else f"{label} #{index + 1}"
                    credits = 0.0 if zero_credit_gate else _slot_credits(requirement, count, index)
                    alternatives = list(options)

                if len(raw) >= max_units:
                    raise ValueError(
                        "Too many planning slots. Use a focused undergraduate audit."
                    )
                raw.append(
                    {
                        "code": code,
                        "label": label,
                        "credits": credits,
                        "majors": [program],
                        "requirement_ids": [requirement["id"]],
                        "requirement_names": [requirement["name"]],
                        "sections": [requirement["section"]],
                        "categories": [category],
                        "alternatives": alternatives,
                        "is_placeholder": not named,
                        "status": "milestone" if zero_credit_gate else "planned",
                        "prerequisites": prerequisites.get(code, []),
                        "corequisites": corequisites.get(code, []),
                        "attributes": list(requirement.get("designations") or []),
                        "advisories": [],
                        "criteria": list(requirement.get("criteria") or []),
                        "justification": _justify(requirement, program, named, code),
                    }
                )

    raw, substitution_notes = _apply_substitutions(raw, audits)
    notes.extend(substitution_notes)
    return _merge_across_programs(raw), list(dict.fromkeys(notes))


def _apply_substitutions(
    units: list[dict[str, Any]],
    audits: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[str]]:
    """Collapse a sequence DARS lists separately into the course actually taken.

    W. P. Carey's career-prep modules are the case this exists for. DARS lists
    WPC 148 and WPC 248 as two quarter-credit requirements and offers WPC 347
    only as an alternative to the second, which reads as though a continuing
    student should take all three. WPC 347 is the half-credit course that covers
    both, so scheduling 148 and 248 alongside it books a student into work they
    cannot take.
    """
    earned = max(
        (audit.get("summary", {}).get("earned_hours") or 0.0 for audit in audits),
        default=0.0,
    )
    required_codes = {unit["code"] for unit in units}
    notes: list[str] = []

    for rule in substitutions_for(earned, required_codes):
        superseded = [unit for unit in units if unit["code"] in rule["replaces"]]
        if not superseded:
            continue
        # Keep the identity of everything the replaced modules answered, so the
        # requirement is still shown as covered rather than quietly dropped.
        template = dict(superseded[0])
        template.update(
            code=rule["replacement_code"],
            label=rule["replacement_code"],
            credits=rule["replacement_credits"],
            is_placeholder=False,
            alternatives=[],
            requirement_ids=list(
                dict.fromkeys(i for unit in superseded for i in unit["requirement_ids"])
            ),
            requirement_names=list(
                dict.fromkeys(n for unit in superseded for n in unit["requirement_names"])
            ),
            sections=list(dict.fromkeys(x for unit in superseded for x in unit["sections"])),
            majors=list(dict.fromkeys(m for unit in superseded for m in unit["majors"])),
            justification=(
                f"{rule['replacement_code']} covers "
                f"{' and '.join(rule['replaces'])} in one class. {rule['detail']}"
            ),
        )
        units = [unit for unit in units if unit["code"] not in rule["replaces"]]
        # If the replacement was already scheduled in its own right, do not add a
        # second copy of it.
        if not any(unit["code"] == rule["replacement_code"] for unit in units):
            units.append(template)
        else:
            for unit in units:
                if unit["code"] == rule["replacement_code"]:
                    unit["credits"] = max(unit["credits"], rule["replacement_credits"])
                    unit["requirement_ids"] = list(
                        dict.fromkeys([*unit["requirement_ids"], *template["requirement_ids"]])
                    )
                    unit["justification"] = template["justification"]
        notes.append(
            f"{rule['replacement_code']} replaces "
            f"{' and '.join(rule['replaces'])} on your map: {rule['detail']} "
            f"Source: {rule['source']}."
        )
    return units, notes


def _justify(requirement: dict[str, Any], program: str, named: bool, code: str) -> str:
    title = clean_title(requirement["name"])
    if named:
        opening = f"Required for {program}"
    else:
        opening = f"Reserved for a {program} requirement you still choose"
    detail = f", satisfying “{title}”" if title and title != code else ""
    criteria = requirement.get("criteria") or []
    tail = f" It must be {criteria[0][0].lower()}{criteria[0][1:]}." if criteria else ""
    return f"{opening}{detail}.{tail}"


def _merge_across_programs(units: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Collapse a unit that answers the same thing for more than one program.

    Without this a student carrying two majors is told to take Sustainability
    twice — six credits scheduled for a three-credit rule. Merging happens only
    across *different* programs: DARS does not say a course may double-count
    inside one program, so we never assume it can.
    """
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for unit in units:
        grouped[unit["code"]].append(unit)

    merged: list[dict[str, Any]] = []
    for group in grouped.values():
        by_program: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for unit in group:
            by_program[unit["majors"][0]].append(unit)
        depth = max(len(items) for items in by_program.values())
        for index in range(depth):
            selected = [items[index] for items in by_program.values() if index < len(items)]
            base = dict(selected[0])
            if len(selected) > 1:
                base["credits"] = max(unit["credits"] for unit in selected)
                for field in ("majors", "requirement_ids", "requirement_names",
                              "sections", "categories", "alternatives", "criteria"):
                    base[field] = list(
                        dict.fromkeys(value for unit in selected for value in unit[field])
                    )
                programs = " and ".join(base["majors"])
                base["justification"] = (
                    f"Counts for {programs} at once"
                    f"{'' if base['is_placeholder'] else ''}. "
                    f"One class clears “{clean_title(base['requirement_names'][0])}” "
                    "in each program — confirm the double-count with an advisor."
                )
            merged.append(base)
    return merged
