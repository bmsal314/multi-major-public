"""Sequencing knowledge that DARS does not state, taken from named sources.

A degree audit says *what* is left. It does not say what order the coursework
has to happen in, which single course clears two programs at once, or which
policy footnote changes the requirement itself. That information lives in the
ASU eAdvisor major maps and in what an academic advisor says out loud.

Everything in this module is therefore attributed. Each entry carries the
source it came from, so a future catalog year can be reconciled against the
real document rather than against a guess. Nothing here is inferred from course
numbering, and nothing here silently overrides DARS: where a major map and a
DARS report disagree, the disagreement is surfaced as an advisory note for the
student to confirm, and the DARS reading is the one that is planned.

Sources
-------
- ``eAdvisor Tracking Tool`` major map, Finance BS (BAFINBS), catalog 2024-2025
- ``eAdvisor Tracking Tool`` major map, Neuroscience BS (LABMENBS), catalog 2024-2025
- Academic advising appointment, 2026-08-27 (finance core ordering)
- Student confirmation, 2026-08-27 (honors FIN 303 equivalence applies)
"""

from __future__ import annotations

from typing import Any


FINANCE_MAP = "Finance BS major map"
NEURO_MAP = "Neuroscience BS major map"
ADVISOR = "Academic advisor, 2026-08-27"
STUDENT = "Confirmed with the student, 2026-08-27"

# ASU treats 12 hours as full time, but scholarship and honors continuous
# enrolment conditions can sit above it.  This is the floor the planner refuses
# to schedule below and the lowest value the credit sliders offer.
MIN_TERM_CREDITS = 13

# Above this ASU requires a credit-overload approval.  Not an error, a step.
OVERLOAD_TERM_CREDITS = 18


# --------------------------------------------------------------------- ordering

# ``course: [must come strictly earlier]``
COURSE_PREREQUISITES: dict[str, list[str]] = {
    # Pre-med and science sequences (both major maps place these in order).
    "BIO 182": ["BIO 181"],
    "CHM 116": ["CHM 113"],
    "CHM 233": ["CHM 116"],
    "CHM 234": ["CHM 233"],
    "PHY 112": ["PHY 111"],
    "BIO 477": ["BIO 476"],
    "NEU 477": ["BIO 476"],
    # W. P. Carey career navigation ladder: 148 -> 248/347 -> 348 -> 448.
    "WPC 248": ["WPC 148"],
    "WPC 347": ["WPC 148"],
    "WPC 348": ["WPC 248", "WPC 347"],
    "WPC 448": ["WPC 348"],
    # Finance core.  FIN 303 is the honors version of FIN 302.
    "FIN 361": ["FIN 302", "FIN 303"],
    "FIN 421": ["FIN 361"],
    # The advisor sequenced 421 before 461; DARS only requires FIN 361 first.
    "FIN 461": ["FIN 361", "FIN 421"],
    # "All upper-division Business Core classes (including International
    # Business course) must be completed before enrolling in WPC 480."
    "WPC 480": [
        "WPC 300",
        "LES 305",
        "MGT 300",
        "MKT 300",
        "SCM 300",
        "AGB 302",
        "ECN 306",
        "MGT 302",
        "MKT 425",
        "SCM 463",
    ],
}

COURSE_COREQUISITES: dict[str, list[str]] = {
    "CHM 237": ["CHM 233"],
    "CHM 238": ["CHM 234"],
    "PHY 113": ["PHY 111"],
    "PHY 114": ["PHY 112"],
}

# Where a rule above came from, for the printable plan and the UI.
PREREQUISITE_SOURCES: dict[str, str] = {
    "WPC 480": FINANCE_MAP,
    "FIN 461": ADVISOR,
    "FIN 421": FINANCE_MAP,
    "FIN 361": FINANCE_MAP,
    "WPC 248": FINANCE_MAP,
    "WPC 347": FINANCE_MAP,
    "WPC 348": FINANCE_MAP,
    "WPC 448": FINANCE_MAP,
    "BIO 477": NEURO_MAP,
    "NEU 477": NEURO_MAP,
}


# ------------------------------------------------------------- advisor tracks

# An ordered run of terms an advisor asked for explicitly.  Step 0 is the
# anchor: coursework already in progress that the rest of the run follows.
# Each later step is placed in its own term, in order, as early as the plan
# allows.  ``elective_of`` pulls one unit out of a named DARS elective block so
# a "major elective" in the advisor's sentence lands in the right term instead
# of wherever the generic packer happened to put it.
ADVISOR_TRACKS: list[dict[str, Any]] = [
    {
        "id": "finance-core",
        "label": "Finance core sequence",
        "source": ADVISOR,
        "detail": (
            "FIN 303 now, then ACC 340 with FIN 361, then FIN 421 with a major "
            "elective, then FIN 461 with a major elective."
        ),
        "anchor": ["FIN 302", "FIN 303"],
        "steps": [
            {"courses": ["ACC 340", "FIN 361"], "electives": []},
            {
                "courses": ["FIN 421"],
                "electives": [{"match": "Upper Division Finance Elective", "count": 1}],
            },
            {
                "courses": ["FIN 461"],
                "electives": [{"match": "Upper Division Finance Elective", "count": 1}],
            },
        ],
    },
]


# ------------------------------------------------------------- equivalences

# One course that clears more than one DARS requirement, where the audit cannot
# express it and therefore keeps listing the extra requirement as remaining.
#
# These are the sharpest edges in the whole file: acting on one *removes* work
# the audit says is owed, so each carries both the document it comes from and
# the confirmation that it applies to this student. When a rule fires the hours
# it frees do not disappear — ``replacement`` puts them back as a slot the
# student still has to fill, because the program's hour total has not changed.
EQUIVALENCE_RULES: list[dict[str, Any]] = [
    {
        "id": "honors-fin-303",
        "program": "Finance",
        "source": FINANCE_MAP,
        "confirmed_by": STUDENT,
        # Satisfied — completed or in progress — by any of these.
        "when_holding": ["FIN 303"],
        # DARS requirements it also clears, matched on their course options.
        "also_clears": ["FIN 361"],
        "detail": (
            "FIN 303 is the honors course that satisfies both FIN 302 and FIN 361. "
            "Taking it covers two of the seven Finance major requirements with one "
            "class, which leaves the 21-hour major three hours short."
        ),
        "replacement": {
            "label": "FIN 400-level course",
            "credits": 3.0,
            # Only courses the DARS elective list or the major map actually name.
            "options": ["FIN 427", "FIN 431", "FIN 455", "FIN 456", "FIN 484"],
            "criteria": ["Finance 400-level course"],
            "reason": (
                "Replaces the three hours FIN 303 freed by covering FIN 361. The "
                "Finance major map requires an additional FIN 400-level course in "
                "its place, so the 21 hours in the major still add up."
            ),
        },
    },
]


def equivalence_for(codes: set[str]) -> list[dict[str, Any]]:
    """Rules whose triggering course the student already holds."""
    return [
        rule
        for rule in EQUIVALENCE_RULES
        if set(rule["when_holding"]) & codes
    ]


# ------------------------------------------------- W. P. Carey career prep

#: The W. P. Carey career-preparation sequence, taken alongside the major.
#: DARS lists the quarter-credit modules separately and offers WPC 347 only as
#: an alternative to WPC 248, which understates it: for a student who is past
#: their first year, WPC 347 is the half-credit course that stands in for
#: *both* WPC 148 and WPC 248. Scheduling all three wastes a slot on work the
#: student cannot take, so the substitution is applied when the audit shows
#: they are no longer a freshman.
CAREER_PREP_SEQUENCE: list[str] = ["WPC 148", "WPC 248", "WPC 347", "WPC 348", "WPC 448"]

#: ASU class standing: freshman is under 24 earned hours, sophomore begins at 24.
NON_FRESHMAN_EARNED_HOURS = 24.0

COURSE_SUBSTITUTIONS: list[dict[str, Any]] = [
    {
        "id": "wpc-career-prep-347",
        "program_signal": ["WPC 148", "WPC 248"],
        "replaces": ["WPC 148", "WPC 248"],
        "replacement_code": "WPC 347",
        "replacement_credits": 0.5,
        "min_earned_hours": NON_FRESHMAN_EARNED_HOURS,
        "source": "W. P. Carey career prep sequence",
        "confirmed_by": STUDENT,
        "detail": (
            "WPC 347 is the half-credit career-prep course for students past their "
            "first year. It replaces WPC 148 and WPC 248 — two quarter-credit "
            "modules — so one class is scheduled instead of two. WPC 348 and "
            "WPC 448 still follow it."
        ),
    },
]


def substitutions_for(earned_hours: float, required_codes: set[str]) -> list[dict[str, Any]]:
    """Substitution rules that apply to this student and this programme."""
    return [
        rule
        for rule in COURSE_SUBSTITUTIONS
        if earned_hours >= rule["min_earned_hours"]
        and set(rule["program_signal"]) & required_codes
    ]


# ------------------------------------------------- General Studies attributes

# Parenthetical General Studies codes printed next to a course on a major map.
# These let one required major course also clear a general-studies area, which
# is the only kind of double-count this app will claim on its own.
GENERAL_STUDIES_ATTRIBUTES: dict[str, list[str]] = {
    "CIS 105": ["QTRS"],
    "MAT 210": ["MATH"],
    "MAT 211": ["MATH"],
    "ECN 211": ["SOBE"],
    "ECN 212": ["SOBE"],
    "ECN 221": ["QTRS"],
    "PSY 101": ["SOBE"],
    "COM 259": ["CIVI"],
    "BIO 181": ["SCIT"],
    "BIO 182": ["SCIT"],
    "HST 109": ["AMIT"],
    "WPC 300": ["QTRS"],
    "SCM 300": ["SUST"],
    "SCM 303": ["SUST"],
    # Upper-division international business options all carry GCSI.
    "AGB 302": ["GCSI"],
    "ECN 306": ["GCSI"],
    "MGT 302": ["GCSI"],
    "MKT 425": ["GCSI"],
    "SCM 463": ["GCSI"],
}

ATTRIBUTE_NAMES: dict[str, str] = {
    "AMIT": "American Institutions",
    "CIVI": "Governance and Civic Engagement",
    "GCSI": "Global Communities, Societies and Individuals",
    "HUAD": "Humanities, Arts and Design",
    "MATH": "Mathematics",
    "QTRS": "Quantitative Reasoning",
    "SCIT": "Scientific Thinking in Natural Sciences",
    "SOBE": "Social and Behavioral Sciences",
    "SUST": "Sustainability",
}

ATTRIBUTE_SOURCES: dict[str, str] = {code: FINANCE_MAP for code in GENERAL_STUDIES_ATTRIBUTES}


def attributes_for(code: str) -> list[str]:
    return GENERAL_STUDIES_ATTRIBUTES.get(code, [])


def attribute_label(attribute: str) -> str:
    return ATTRIBUTE_NAMES.get(attribute, attribute)


# ------------------------------------------------------------ advisory notices

# Rules a major map states that DARS cannot express, or states differently.
# ``conflicts_with`` names the DARS requirement the note argues with, so the
# UI can put the warning next to the class it is about instead of in a footer.
ADVISORY_NOTES: list[dict[str, Any]] = [
    {
        "id": "honors-fin-303",
        "program": "Finance",
        "severity": "applied",
        "courses": ["FIN 303", "FIN 361"],
        "source": FINANCE_MAP,
        "title": "FIN 303 covers FIN 361 — a FIN 400-level course takes its place",
        "detail": (
            "The Finance major map states that an honors student who takes FIN 303 "
            "satisfies both FIN 302 and FIN 361, and must instead take an additional "
            "FIN 400-level course to reach the hours required in the major. You have "
            "confirmed this applies to you, so this plan does not schedule FIN 361 "
            "and adds a FIN 400-level slot in its place — keeping the Finance major "
            "at 21 hours. Your Finance DARS still lists FIN 361 as remaining and "
            "will keep doing so until an advisor records the substitution, so have "
            "it noted on your record before your graduation audit."
        ),
    },
    {
        "id": "wpc-480-gate",
        "program": "Finance",
        "severity": "sequencing",
        "courses": ["WPC 480"],
        "source": FINANCE_MAP,
        "title": "WPC 480 comes after the whole upper-division business core",
        "detail": (
            "LES 305, MGT 300, MKT 300, SCM 300, WPC 300, and the upper-division "
            "international business course must all be complete before you can "
            "enroll in WPC 480. This plan enforces that ordering."
        ),
    },
    {
        "id": "wpc-concurrent-unique",
        "program": "Finance",
        "severity": "confirm",
        "courses": [],
        "source": FINANCE_MAP,
        "title": "W. P. Carey major coursework cannot be shared",
        "detail": (
            "Students pursuing concurrent degrees within W. P. Carey cannot share "
            "coursework in the major. Neuroscience sits in The College, not W. P. "
            "Carey, so the Finance/Neuroscience overlaps this app reports are not "
            "covered by that rule — but any second W. P. Carey program would be."
        ),
    },
    {
        "id": "acc-340-substitution",
        "program": "Finance",
        "severity": "confirm",
        "courses": ["ACC 340", "ACC 350", "ACC 440"],
        "source": FINANCE_MAP,
        "title": "ACC 350 and ACC 440 are restricted as the finance elective",
        "detail": (
            "Accountancy and Finance concurrent-degree students may not use ACC 350 "
            "or ACC 440 as the Finance upper-division elective, and must take an "
            "additional finance upper-division elective in place of ACC 340. This "
            "applies only to an Accountancy concurrent degree."
        ),
    },
    {
        "id": "neu-elective-cap",
        "program": "Neuroscience",
        "severity": "cap",
        "courses": ["NEU 394", "NEU 484", "NEU 492", "NEU 493", "NEU 499"],
        "source": NEURO_MAP,
        "title": "At most 6 hours of NEU 394/484/492/493/499 count",
        "detail": (
            "The Neuroscience major electives total 18 hours, and a maximum of 6 of "
            "those hours may come from NEU 394 (Genes, Data and the Brain), NEU 394 "
            "(Undergraduate Teaching Assistant), NEU 484, NEU 492, NEU 493, and "
            "NEU 499 combined. Keep research and teaching credit under that ceiling."
        ),
    },
    {
        "id": "clas-residency",
        "program": "Neuroscience",
        "severity": "sequencing",
        "courses": [],
        "source": NEURO_MAP,
        "title": "12 upper-division major hours must come from The College",
        "detail": (
            "Before graduation, at least 12 credit hours of upper-division (300 and "
            "400 level) major coursework must be completed through courses offered "
            "by The College of Liberal Arts and Sciences."
        ),
    },
]

# Courses a major map lists whose hours exist only to reach 120 total.  They are
# real, but they are not tied to a named requirement, so the planner should not
# invent a specific course for them.
GENERIC_FILLER_LABELS = (
    "Elective",
    "Upper Division Elective",
)


# Words a requirement title uses for the subject that owns it.  Used only to
# break ties between equally valid options: a "Finance Elective" should offer
# FIN 331 before ACC 350 even though ACC 350 sorts lower by number.
SUBJECT_WORDS: dict[str, tuple[str, ...]] = {
    "ACC": ("accounting", "accountancy"),
    "BIO": ("biology", "biological"),
    "COM": ("communication",),
    "ECN": ("economics",),
    "ENG": ("english", "writing"),
    "FIN": ("finance", "financial"),
    "LES": ("legal",),
    "MGT": ("management",),
    "MKT": ("marketing",),
    "NEU": ("neuroscience",),
    "SCM": ("supply chain",),
    "WPC": ("business",),
}


def subject_affinity(code: str, requirement_name: str) -> int:
    """0 when the option's subject is named in the requirement, else 1."""
    subject = code.split()[0] if code.split() else ""
    haystack = requirement_name.casefold()
    words = SUBJECT_WORDS.get(subject, ())
    return 0 if any(word in haystack for word in words) else 1


def notes_for_course(code: str) -> list[dict[str, Any]]:
    return [note for note in ADVISORY_NOTES if code in note["courses"]]


def notes_for_program(program: str) -> list[dict[str, Any]]:
    return [note for note in ADVISORY_NOTES if note["program"] == program]
