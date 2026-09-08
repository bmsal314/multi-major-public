"""Transparent pre-med coursework matching against a parsed transcript."""

from __future__ import annotations

import re
from typing import Any


PREHEALTH_URL = "https://prehealth.asu.edu/future-students/curriculum"
AAMC_REQUIREMENTS_URL = (
    "https://students-residents.aamc.org/medical-school-admission-requirements/"
    "admission-requirements"
)


CORE_RULES = (
    {
        "id": "biology",
        "name": "General biology I and II",
        "detail": "One full year of biology",
        "groups": (("BIO 181",), ("BIO 182",)),
    },
    {
        "id": "general-chemistry",
        "name": "General chemistry I and II",
        "detail": "One full year of general chemistry",
        "groups": (("CHM 113", "CHM 117"), ("CHM 116", "CHM 118")),
    },
    {
        "id": "organic-chemistry",
        "name": "Organic chemistry I and II with labs",
        "detail": "CHM 233/237 and CHM 234/238, or the majors sequence",
        "groups": (
            ("CHM 233", "CHM 333"),
            ("CHM 237", "CHM 337"),
            ("CHM 234", "CHM 334"),
            ("CHM 238", "CHM 338"),
        ),
    },
    {
        "id": "physics",
        "name": "General physics I and II with labs",
        "detail": "One full year of physics: PHY 111/113 and PHY 112/114",
        "groups": (("PHY 111",), ("PHY 113",), ("PHY 112",), ("PHY 114",)),
    },
    {
        "id": "biochemistry",
        "name": "Biochemistry",
        "detail": "One semester of biochemistry",
        "groups": (("BCH 361",),),
    },
    {
        "id": "statistics",
        "name": "Statistics",
        "detail": "At least one semester",
        "groups": (("STP 226", "STP 231", "PSY 230", "HCD 300"),),
    },
    {
        "id": "english",
        "name": "English or writing-intensive coursework",
        "detail": "At least two semesters",
        "minimum": 2,
        "groups": (("ENG 101", "ENG 102", "ENG 105", "HON 171", "ENG 301"),),
    },
    {
        # The MCAT devotes an entire section to Psychological, Social and
        # Biological Foundations of Behavior, and the AAMC's behavioural and
        # social science expectation is about six credit hours. Carrying this as
        # merely "recommended" understated it: a student can finish every other
        # core requirement and still walk into a quarter of the exam untaught.
        "id": "behavioral-social",
        "name": "Psychology and sociology",
        "detail": (
            "Roughly two semesters of behavioural and social science. The MCAT's "
            "Psychological, Social and Biological Foundations of Behavior section "
            "draws directly on introductory psychology and sociology."
        ),
        "minimum": 2,
        "groups": (
            (
                "PSY 101", "SOC 101", "PSY 230", "PSY 290", "PSY 324", "PSY 340",
                "SOC 201", "SOC 331", "ASB 102", "ASB 100", "FAS 101",
            ),
        ),
    },
)


RECOMMENDED_RULES = (
    ("genetics", "Genetics", (("BIO 340",),)),
    ("developmental-biology", "Developmental biology", (("BIO 351",),)),
    ("cell-biology", "Cell biology", (("BIO 353",),)),
    ("physiology", "Animal physiology", (("BIO 360",),)),
    ("anatomy", "Human anatomy and physiology", (("BIO 201",),)),
    ("microbiology", "Microbiology with lab", (("MIC 205", "MIC 220"), ("MIC 206",))),
    ("sociology-upper", "Upper-division social science", (("SOC 331", "PSY 324"),)),
)


def _status_for_groups(
    groups: tuple[tuple[str, ...], ...],
    completed: set[str],
    in_progress: set[str],
    minimum: int | None = None,
) -> tuple[str, list[str], list[str], list[str]]:
    if minimum is not None:
        choices = groups[0]
        completed_matches = [code for code in choices if code in completed]
        progress_matches = [code for code in choices if code in in_progress]
        remaining_count = max(0, minimum - len(completed_matches) - len(progress_matches))
        remaining = (
            [f"{remaining_count} more approved course{'s' if remaining_count != 1 else ''}"]
            if remaining_count
            else []
        )
        status = "complete" if len(completed_matches) >= minimum else "in_progress" if not remaining else "remaining"
        return status, completed_matches, progress_matches, remaining, remaining_count, list(choices)

    completed_matches: list[str] = []
    progress_matches: list[str] = []
    remaining: list[str] = []
    for alternatives in groups:
        completed_choice = next((code for code in alternatives if code in completed), None)
        progress_choice = next((code for code in alternatives if code in in_progress), None)
        if completed_choice:
            completed_matches.append(completed_choice)
        elif progress_choice:
            progress_matches.append(progress_choice)
        else:
            remaining.append(alternatives[0])
    status = "complete" if not progress_matches and not remaining else "in_progress" if not remaining else "remaining"
    return status, completed_matches, progress_matches, remaining, 0, []


def evaluate_premed(courses: list[dict[str, Any]]) -> dict[str, Any]:
    completed = {course["code"] for course in courses if course["status"] == "complete"}
    in_progress = {course["code"] for course in courses if course["status"] == "in_progress"}
    requirements: list[dict[str, Any]] = []

    for rule in CORE_RULES:
        # The catalog documents two composition pathways, not any arbitrary pair.
        if rule['id']=='english':
            pathways=((("ENG 101",),("ENG 102",)),(("ENG 105",),("HON 171","ENG 301")))
            evaluated=[_status_for_groups(pathway,completed,in_progress) for pathway in pathways]
            status,done,underway,remaining,short,options=min(evaluated,key=lambda item:(len(item[3]),len(item[2])))
        else:
            status, done, underway, remaining, short, options = _status_for_groups(
            rule["groups"], completed, in_progress, rule.get("minimum")
        )
        requirements.append(
            {
                "id": rule["id"],
                "name": rule["name"],
                "detail": rule["detail"],
                "status": status,
                "required": rule["id"] != "statistics",
                "completed_courses": done,
                "in_progress_courses": underway,
                "remaining_courses": remaining,
                # How many more, as a number the planner can act on. Encoding it
                # only in prose meant a rewording turned the sentence itself into
                # a scheduled "course".
                "count_remaining": short,
                "options": options,
                "note": "Recommended, not a universal prerequisite." if rule["id"] == "statistics" else "Pre-health sequence; confirm every target school's policy. AP, transfer and online acceptance varies.",
            }
        )

    for identity, name, groups in RECOMMENDED_RULES:
        status, done, underway, remaining, short, options = _status_for_groups(groups, completed, in_progress)
        requirements.append(
            {
                "id": identity,
                "name": name,
                "detail": "Recommended for medical-school preparation",
                "status": status,
                "required": False,
                "completed_courses": done,
                "in_progress_courses": underway,
                "remaining_courses": remaining,
                "count_remaining": short,
                "options": options,
                "note": "Recommended, not a universal prerequisite.",
            }
        )

    # Majors chemistry substitutes do not remove the separate lab requirement.
    for lecture, lab in (("CHM 117","CHM 111"),("CHM 118","CHM 112")):
        if lecture in completed | in_progress:
            status, done, underway, remaining, short, options = _status_for_groups(((lab,),), completed, in_progress)
            requirements.append({"id":lab.lower().replace(" ","-"),"name":f"{lecture} laboratory", "detail":f"{lab} accompanies the majors chemistry sequence", "status":status,"required":True,"completed_courses":done,"in_progress_courses":underway,"remaining_courses":remaining,"count_remaining":short,"options":options,"note":"Pre-health curriculum; target-school policies vary."})
    core = [item for item in requirements if item["required"]]
    return {
        "framework": "Pre-health core sequence",
        "complete_count": sum(item["status"] == "complete" for item in core),
        "in_progress_count": sum(item["status"] == "in_progress" for item in core),
        "remaining_count": sum(item["status"] == "remaining" for item in core),
        "requirements": requirements,
        "sources": [
            {
                "label": "Pre-health curriculum",
                "url": PREHEALTH_URL,
                "note": "Course sequences and recommended medical-school preparation.",
            },
            {
                "label": "AAMC admission requirements",
                "url": AAMC_REQUIREMENTS_URL,
                "note": "School-specific requirements vary; verify target schools before applying.",
            },
        ],
    }


def remaining_premed_units(premed: dict[str, Any]) -> list[dict[str, Any]]:
    """Create schedule units only for unmet core courses, never recommendations."""
    credits = {
        "CHM 111": 1.0,
        "CHM 112": 1.0,
        "BIO 181": 4.0,
        "BIO 182": 4.0,
        "CHM 113": 4.0,
        "CHM 116": 4.0,
        "CHM 233": 3.0,
        "CHM 237": 1.0,
        "CHM 234": 3.0,
        "CHM 238": 1.0,
        "PHY 111": 3.0,
        "PHY 113": 1.0,
        "PHY 112": 3.0,
        "PHY 114": 1.0,
        "BCH 361": 3.0,
        "STP 226": 3.0,
    }
    units: list[dict[str, Any]] = []
    for requirement in premed["requirements"]:
        if not requirement["required"]:
            continue
        # A counted requirement ("two semesters of X") names no specific course,
        # so it becomes that many labelled slots carrying its approved list —
        # the same shape the parser uses for a pool.
        for index in range(int(requirement.get("count_remaining") or 0)):
            options = list(requirement.get("options") or [])
            units.append(
                {
                    "code": f"{requirement['name']} #{index + 1}",
                    "label": requirement["name"],
                    "credits": 3.0,
                    "majors": ["Pre-med"],
                    "requirement_ids": [f"premed:{requirement['id']}"],
                    "requirement_names": [requirement["name"]],
                    "sections": ["Pre-med core"],
                    "alternatives": options,
                    "is_placeholder": True,
                    "status": "premed",
                    "attributes": [],
                    "advisories": [],
                    "prerequisites": [],
                    "corequisites": [],
                    "justification": (
                        f"{requirement['name']} for the MCAT. {requirement['detail']}"
                    ),
                }
            )
        for code in requirement["remaining_courses"]:
            # Prose left in remaining_courses for display; it is not a course.
            if not isinstance(code, str) or not re.fullmatch(r"[A-Z]{2,4} \d{3}[A-Z]?", code):
                continue
            units.append(
                {
                    "code": code,
                    "label": code,
                    "credits": credits.get(code, 3.0),
                    "majors": ["Pre-med"],
                    "requirement_ids": [f"premed:{requirement['id']}"],
                    "requirement_names": [requirement["name"]],
                    "sections": ["Pre-med core"],
                    "alternatives": [],
                    "is_placeholder": False,
                    "status": "premed",
                    "attributes": [],
                    "advisories": [],
                    "justification": (
                        f"A medical-school prerequisite, not a degree requirement: "
                        f"{requirement['detail'][0].lower()}{requirement['detail'][1:]}."
                    ),
                }
            )
    return units
