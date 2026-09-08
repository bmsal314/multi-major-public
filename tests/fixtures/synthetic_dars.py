"""Synthesize ASU uAchieve/DARS reports from real major-map content.

The four fixtures below are *audits*, not major maps: they show satisfied,
in-progress and needed status against numbered requirement blocks, with the
transcript rows, hour checks and GPA lines a real report carries.  The layout
was learned from the real exports in ``tests/fixtures/dars_real/`` — see
``tests/reports/phase0_audit_summary.md`` §4 — and the course codes, credit
hours and requirement categories come from the three 2024-2025 major maps in
``tests/fixtures/major_maps/``.

Each fixture isolates one parsing challenge:

``journalism_early_semester``
    Bare, unnamed ``Elective`` line items carrying hours and no course detail
    (Term 4: 3 hrs, Term 8: 2 hrs), plus the advisor-approved but uncoded
    "Related Area Course" category.

``journalism_unresolved_elective_block``
    A large transfer-in block of generic elective credit with no course-level
    detail, to stress placeholder placement directly.

``dance_bfa_near_graduation``
    OR-grouped "Personal Movement Practice" requirements resolved against the
    separate lower/upper-division lookup pools at the end of the map, plus
    inline "Complete 2 courses" instructions needing the same category
    satisfied twice in one term.

``aerospace_transfer_credit_heavy``
    Wildcard course-number matching (``AEE OR MAE OR MEE 3** Elective``), the
    capped sub-list constraint ("no more than one course from the following"),
    and requirements satisfied by transfer/AP credit not tied to a term.
"""

from __future__ import annotations

from pathlib import Path

from textpdf import write_text_pdf

HEADER_STAMP = "9/3/26, 9:55 PM My Audit - Audit Results Tab"
FOOTER = (
    "https://webapp4.asu.edu/uachieve/audit/read.html?printerFriendly=true&"
    "id=JobQueueRun!!!!ISEhIWludFNlcU5vPTE3NDE1NTE4MA=="
)


def _header(degree: str, college: str, code: str, major: str, prepared: str) -> list[str]:
    return [
        HEADER_STAMP,
        "Test Student",
        degree,
        college,
        f"Prepared On {prepared} Program Code {code} Catalog Year Fall 2024",
        "Student ID 1234500000",
        "Open All Sections Close All Sections",
        "Full Requirements Degree Audit",
        "Logon to My ASU to request your degree audit",
        "Your official major/catalog year on file is:",
        f"{major}, Tempe For 24-25 CATALOG",
        "-----------------------------------------------------------------",
        ">>>>> AT LEAST ONE REQUIREMENT HAS NOT BEEN SATISFIED",
        "Major Verification",
        "This audit matches your declared major",
        "ASU Catalog Year Verification",
        "This audit matches your approved catalog: 2024-25.",
    ]


def _totals(earned: float, in_progress: float, ud_earned: float, ud_needed: float, gpa: float) -> list[str]:
    lines = [
        "TOTAL HOURS: 120 hours minimum",
        "IP 1) TOTAL HOURS: 120 hours minimum",
        f"{earned:.2f} Hours Earned",
    ]
    if in_progress:
        lines.append(f"IN-PROG> {in_progress:.2f} HOURS")
    lines += [
        "UPPER DIVISION: 45 Hours Minimum",
        "IP Upper Division - 45 hours",
        f"{ud_earned:.2f} Hours Earned",
    ]
    if ud_needed > 0:
        lines.append(f"NEEDS: {ud_needed:.2f} HOURS")
    lines += [
        "RESIDENT CREDIT: 30 hours at ASU",
        "IP Resident ASU hours: 30 hours",
        f"{earned:.2f} Hours Earned",
        "ASU GPA - courses taken at ASU",
        "2.00 minimum required",
        f"EARNED: {earned:.2f} HOURS {gpa:.2f} GPA",
    ]
    return lines


def row(term: str, code: str, credits: float, grade: str, title: str, campus: str = "M") -> str:
    """One transcript row exactly as uAchieve prints it."""
    marker = " >>" if grade == "NR" else ""
    campus_field = f"{campus} " if campus else ""
    return f"{term} {campus_field}{code} {credits:.2f} {grade}{marker} {title}"


def done(number: str, title: str, earned: float, rows: list[str], courses: int = 1) -> list[str]:
    lines = [f"{number}) {title}", f"{earned:.2f} Hours Earned {courses} Course" + ("s" if courses != 1 else "")]
    return lines + rows


def needs(number: str, title: str, hours: float, options: list[str] | None = None,
          note: list[str] | None = None, in_progress: bool = False) -> list[str]:
    lines = [f"{'IP ' if in_progress else ''}{number}) {title}"]
    lines += note or []
    lines.append(f"NEEDS: {hours:.2f} HOURS")
    if options:
        lines.append("COURSE LIST: " + " ".join(options))
    return lines


# --------------------------------------------------------------------------
# Journalism, BA — Walter Cronkite School (CSJMCBA), General Studies Gold
# --------------------------------------------------------------------------

def journalism_early_semester() -> str:
    """Two terms in: Terms 1-2 complete, Term 3 registered, Terms 4-8 owed."""
    lines = _header(
        "BA JOURNALISM", "WALTER CRONKITE SCHOOL OF JOURNALISM AND MASS COMM",
        "CS JMC BA", "Journalism", "08/24/2026 09:54 PM",
    )
    lines += [
        "OPT IN PROGRESS COURSES",
        "IP These courses are currently in progress:",
        row("FA26", "JMC 301", 3.0, "NR", "INTERMED REPORTING AND WRITING"),
        row("FA26", "JMC 366", 3.0, "NR", "MEDIA ETHICS"),
        row("FA26", "SPA 201", 4.0, "NR", "INTERMEDIATE SPANISH I"),
        row("FA26", "POS 110", 3.0, "NR", "GOVERNMENT AND POLITICS"),
        row("FA26", "SOC 101", 3.0, "NR", "INTRODUCTORY SOCIOLOGY"),
    ]
    lines += _totals(29.0, 16.0, 6.0, 39.0, 3.42)
    lines += [
        "The ASU Experience",
        "ASU 101 or college-specific equivalent First-Year Seminar",
        "is required for all first-year students.",
        "1) ASU 101 - The ASU Experience: 1 hour",
        row("FA25", "ASU 101", 1.0, "A", "THE ASU EXPERIENCE"),
        "University Requirement",
        "FIRST-YEAR COMPOSITION",
        "Students must complete ENG 101 and ENG 102; or ENG 107 and",
        "ENG 108; or ENG 105.",
        "ENG 101 and 102 or ENG 107 and 108",
        "EARNED: 2 SUB-GROUPS",
        *done("1", "ENG 101 OR ENG 107: 3 hours, C minimum", 3.0,
              [row("FA25", "ENG 101", 3.0, "A-", "FIRST-YEAR COMPOSITION")]),
        *done("2", "ENG 102 OR ENG 108: 3 hours, C minimum", 3.0,
              [row("SP26", "ENG 102", 3.0, "B+", "FIRST-YEAR COMPOSITION")]),
        "University General Studies Requirement - Gold",
        "HUMANITIES, ARTS AND DESIGN",
        *needs("1", "Humanities, Arts and Design (HUAD): 3 hours", 3.0),
        "University General Studies Requirement - Gold",
        "SOCIAL AND BEHAVIORAL SCIENCES",
        "IP 1) Social and Behavioral Sciences (SOBE): 3 hours",
        "IN-PROG> 3.00 HOURS",
        row("FA26", "SOC 101", 3.0, "NR", "INTRODUCTORY SOCIOLOGY"),
        "University General Studies Requirement - Gold",
        "SCIENTIFIC THINKING IN NATURAL SCIENCES",
        *needs("1", "Scientific Thinking in Natural Sciences (SCIT): 8 hours", 8.0,
               note=["- two courses"]),
        "University General Studies Requirement - Gold",
        "QUANTITATIVE REASONING",
        *needs("1", "Quantitative Reasoning (QTRS): 3 hours", 3.0),
        "University General Studies Requirement - Gold",
        "MATHEMATICS",
        *done("1", "Mathematics (MATH): 3 hours", 3.0,
              [row("SP26", "MAT 142", 3.0, "B", "COLLEGE MATHEMATICS")]),
        "University General Studies Requirement - Gold",
        "AMERICAN INSTITUTIONS",
        *needs("1", "American Institutions (AMIT): 3 hours", 3.0),
        "University General Studies Requirement - Gold",
        "GOVERNANCE AND CIVIC ENGAGEMENT",
        "IP 1) Governance and Civic Engagement (CIVI): 3 hours",
        "IN-PROG> 3.00 HOURS",
        row("FA26", "POS 110", 3.0, "NR", "GOVERNMENT AND POLITICS"),
        "University General Studies Requirement - Gold",
        "GLOBAL COMMUNITIES, SOCIETIES AND INDIVIDUALS",
        *needs("1", "Global Communities, Societies and Individuals (GCSI):", 3.0,
               note=["3 hours"]),
        "University General Studies Requirement - Gold",
        "SUSTAINABILITY",
        *needs("1", "Sustainability (SUST): 3 hours", 3.0),
        "\f",
        HEADER_STAMP,
        "SECOND LANGUAGE Requirement",
        "Requirement satisfied through completion of a language course",
        "at the intermediate level (202 or equivalent), including",
        "American Sign Language IV.",
        "IP 1) Second Language: 16 hours",
        "8.00 Hours Earned",
        "IN-PROG> 4.00 HOURS",
        "NEEDS: 4.00 HOURS",
        row("FA25", "SPA 101", 4.0, "A", "ELEMENTARY SPANISH I"),
        row("SP26", "SPA 102", 4.0, "A-", "ELEMENTARY SPANISH II"),
        row("FA26", "SPA 201", 4.0, "NR", "INTERMEDIATE SPANISH I"),
        "JOURNALISM Major - 120 hours",
        "----------------------------------------------------------",
        "Grade of C (2.00) or better required.",
        "----------------------------------------------------------",
        "NEEDS: 43.00 HOURS 15 SUB-GROUPS",
        *done("1", "JMC 101: 1 hour, Y minimum", 1.0,
              [row("FA25", "JMC 101", 1.0, "Y", "GRAMMAR FOR JOURNALISTS")]),
        *done("2", "JMC 102: 1 hour, C minimum", 1.0,
              [row("FA25", "JMC 102", 1.0, "A", "CODING FOR JOURNALISTS")]),
        *done("3", "JMC 110: 3 hours, C minimum", 3.0,
              [row("FA25", "JMC 110", 3.0, "A-", "PRIN AND HIST OF JOURNALISM")]),
        *done("4", "JMC 115: 1 hour, C minimum", 1.0,
              [row("FA25", "JMC 115", 1.0, "A", "CIVILITY AND COMMUNITY")]),
        *done("5", "JMC 201: 3 hours, C minimum", 3.0,
              [row("SP26", "JMC 201", 3.0, "B+", "NEWS REPORTING AND WRITING")]),
        *done("6", "JMC 305: 3 hours, C minimum", 3.0,
              [row("SP26", "JMC 305", 3.0, "A-", "MULTIMEDIA JOURNALISM")]),
        "IP 7) JMC 301: 3 hours, C minimum",
        "IN-PROG> 3.00 HOURS",
        row("FA26", "JMC 301", 3.0, "NR", "INTERMED REPORTING AND WRITING"),
        "IP 8) JMC 366: 3 hours, C minimum",
        "IN-PROG> 3.00 HOURS",
        row("FA26", "JMC 366", 3.0, "NR", "MEDIA ETHICS"),
        *needs("9", "JMC 313 OR JMC 345 OR JMC 448: 3 hours, C minimum", 3.0,
               ["JMC 313", "JMC 345", "JMC 448"]),
        *needs("10", "JMC 402: 3 hours, C minimum", 3.0, ["JMC 402"]),
        *needs("11", "JMC 484: 3 hours, Y minimum", 3.0, ["JMC 484"]),
        *needs("12", "JMC 473 OR JMC 310: 3 hours, C minimum", 3.0,
               ["JMC 473", "JMC 310"]),
        *needs("13", "Upper Division Advanced Skills Course: 6 hours,", 6.0,
               ["JMC 320", "JMC 330", "JMC 351", "JMC 412", "JMC 413", "JMC 414",
                "JMC 415", "JMC 421", "JMC 434", "JMC 436", "JMC 437", "JMC 440",
                "JMC 441", "JMC 442", "JMC 451", "JMC 453", "JMC 455", "JMC 457",
                "JMC 460", "JMC 465", "JMC 470"],
               note=["C minimum - 2 courses",
                     "Advanced Skills course should be selected in consultation",
                     "with academic adviser."]),
        *needs("14", "Upper Division Capstone Course: 3 hours, C minimum", 3.0,
               ["JMC 475", "JMC 476", "JMC 477", "JMC 478", "JMC 479", "JMC 486",
                "JMC 487", "JMC 498"]),
        *needs("15", "JMC OR MCO Upper Division Elective: 9 hours", 9.0,
               note=["- 3 courses"]),
        "RELATED AREA Requirement",
        "----------------------------------------------------------",
        "Related Area courses must be approved by an academic adviser.",
        "----------------------------------------------------------",
        *needs("1", "Related Area Course: 6 hours, C minimum", 6.0,
               note=["- 2 courses"]),
        *needs("2", "Upper Division Related Area Course: 6 hours, C minimum", 6.0,
               note=["- 2 courses"]),
        "ELECTIVES",
        "----------------------------------------------------------",
        "Hours to reach the 120-hour degree total.",
        "----------------------------------------------------------",
        *needs("1", "Elective: 3 hours", 3.0),
        *needs("2", "Elective: 2 hours", 2.0),
        "************************ END OF ANALYSIS ************************",
        FOOTER,
    ]
    return "\n".join(lines)


def journalism_unresolved_elective_block() -> str:
    """A transfer-heavy student whose electives arrive as undifferentiated credit."""
    lines = _header(
        "BA JOURNALISM", "WALTER CRONKITE SCHOOL OF JOURNALISM AND MASS COMM",
        "CS JMC BA", "Journalism", "08/24/2026 10:11 PM",
    )
    lines += _totals(74.0, 0.0, 12.0, 33.0, 3.11)
    lines += [
        "OPT DUPLICATE OR REPEATED COURSES may need processing by the",
        "Registrar.",
        "Duplicated or Repeated courses still carrying credit:",
        row("SU24", "TRANSFER DEC", 3.0, "IB", "TRANSFER DEPARTMENTAL ELECTIV", campus=""),
        "University General Studies Requirement - Gold",
        "HUMANITIES, ARTS AND DESIGN",
        *done("1", "Humanities, Arts and Design (HUAD): 6 hours - 2 courses", 6.0,
              [row("FA24", "HST 110", 3.0, "IB", "UNITED STATES SINCE 1865", campus=""),
               row("FA24", "ENG 200", 3.0, "IB", "CRITICAL READING AND WRITING", campus="")],
              courses=2),
        "University General Studies Requirement - Gold",
        "SUSTAINABILITY",
        *needs("1", "Sustainability (SUST): 3 hours", 3.0),
        "University General Studies Requirement - Gold",
        "AMERICAN INSTITUTIONS",
        *done("1", "American Institutions (AMIT): 3 hours", 3.0,
              [row("SU24", "HST 109", 3.0, "IB", "UNITED STATES TO 1865", campus="")]),
        "JOURNALISM Major - 120 hours",
        "NEEDS: 30.00 HOURS 8 SUB-GROUPS",
        *done("1", "JMC 110: 3 hours, C minimum", 3.0,
              [row("FA25", "JMC 110", 3.0, "B", "PRIN AND HIST OF JOURNALISM")]),
        *done("2", "JMC 201: 3 hours, C minimum", 3.0,
              [row("SP26", "JMC 201", 3.0, "B", "NEWS REPORTING AND WRITING")]),
        *needs("3", "JMC 301: 3 hours, C minimum", 3.0, ["JMC 301"]),
        *needs("4", "JMC 305: 3 hours, C minimum", 3.0, ["JMC 305"]),
        *needs("5", "JMC 402: 3 hours, C minimum", 3.0, ["JMC 402"]),
        *needs("6", "JMC 484: 3 hours, Y minimum", 3.0, ["JMC 484"]),
        *needs("7", "Upper Division Capstone Course: 3 hours, C minimum", 3.0,
               ["JMC 475", "JMC 476", "JMC 477", "JMC 478"]),
        *needs("8", "JMC OR MCO Upper Division Elective: 9 hours", 9.0,
               note=["- 3 courses"]),
        "RELATED AREA Requirement",
        "Related Area courses must be approved by an academic adviser.",
        *needs("1", "Related Area Course: 6 hours, C minimum", 6.0,
               note=["- 2 courses"]),
        *needs("2", "Upper Division Related Area Course: 6 hours, C minimum", 6.0,
               note=["- 2 courses"]),
        "ELECTIVES",
        "----------------------------------------------------------",
        "Hours applied from transfer credit with no course-level detail.",
        "----------------------------------------------------------",
        "1) Elective: 24 hours",
        "12.00 Hours Earned",
        "NEEDS: 12.00 HOURS",
        row("SU24", "TRANSFER DEC", 3.0, "IB", "TRANSFER DEPARTMENTAL ELECTIV", campus=""),
        row("SU24", "TRANSFER DEC", 3.0, "IB", "TRANSFER DEPARTMENTAL ELECTIV", campus=""),
        row("SU24", "TRANSFER LDE", 3.0, "IB", "TRANSFER LOWER DIVISION ELECT", campus=""),
        row("SU24", "TRANSFER LDE", 3.0, "IB", "TRANSFER LOWER DIVISION ELECT", campus=""),
        *needs("2", "Upper Division Elective: 9 hours", 9.0,
               note=["Hours to reach the 45 upper-division minimum."]),
        "************************ END OF ANALYSIS ************************",
        FOOTER,
    ]
    return "\n".join(lines)


# --------------------------------------------------------------------------
# Dance, BFA — Herberger Institute (FADANBFA)
# --------------------------------------------------------------------------

def dance_bfa_near_graduation() -> str:
    """Terms 7-8 remain; most work satisfied, PMP pools still open."""
    lower_pmp = ["DCE 133", "DCE 134", "DCE 135", "DCE 136", "DCE 139",
                 "DCE 233", "DCE 234", "DCE 235", "DCE 236", "DCE 238", "DCE 239"]
    upper_pmp = ["DCE 333", "DCE 334", "DCE 335", "DCE 336", "DCE 339"]
    lines = _header(
        "BFA DANCE", "HERBERGER INSTITUTE FOR DESIGN AND THE ARTS",
        "FA DAN BFA", "Dance", "08/24/2026 10:22 PM",
    )
    lines += [
        "OPT IN PROGRESS COURSES",
        "IP These courses are currently in progress:",
        row("FA26", "DCE 460", 2.0, "NR", "TRANSITIONS I"),
        row("FA26", "DCE 361", 3.0, "NR", "CREATIVE PRACTICES VI"),
        row("FA26", "DCE 334", 3.0, "NR", "CONTEMPORARY MODERN III"),
    ]
    lines += _totals(98.0, 8.0, 34.0, 11.0, 3.71)
    lines += [
        "University General Studies Requirement - Gold",
        "AMERICAN INSTITUTIONS",
        *needs("1", "American Institutions (AMIT): 3 hours", 3.0),
        "University General Studies Requirement - Gold",
        "SUSTAINABILITY",
        *needs("1", "Sustainability (SUST): 3 hours", 3.0),
        "University General Studies Requirement - Gold",
        "HUMANITIES, ARTS AND DESIGN",
        *done("1", "Humanities, Arts and Design (HUAD): 6 hours - 2 courses", 6.0,
              [row("FA24", "DCE 100", 3.0, "A", "INTRODUCTION TO DANCE"),
               row("SP25", "THE 111", 3.0, "A-", "INTRODUCTION TO THEATRE")],
              courses=2),
        "DANCE Major - 120 hours",
        "----------------------------------------------------------",
        "Grade of C (2.00) or better required.",
        "----------------------------------------------------------",
        "NEEDS: 11.00 HOURS 4 SUB-GROUPS",
        *done("1", "DCE 132: 6 hours, C minimum", 6.0,
              [row("FA24", "DCE 132", 3.0, "A", "FIRST-YEAR DANCE TECHNIQUES"),
               row("SP25", "DCE 132", 3.0, "A", "FIRST-YEAR DANCE TECHNIQUES")],
              courses=2),
        *done("2", "DCE 160: 3 hours, C minimum", 3.0,
              [row("FA24", "DCE 160", 3.0, "A", "CREATIVE PRACTICES I")]),
        *done("3", "DCE 170: 2 hours, C minimum", 2.0,
              [row("FA24", "DCE 170", 2.0, "A", "FIRST-YEAR SEMINAR I")]),
        *done("4", "DCE 261: 3 hours, C minimum", 3.0,
              [row("SP26", "DCE 261", 3.0, "A-", "CREATIVE PRACTICES IV")]),
        "IP 5) DCE 361: 3 hours, C minimum",
        "IN-PROG> 3.00 HOURS",
        row("FA26", "DCE 361", 3.0, "NR", "CREATIVE PRACTICES VI"),
        "IP 6) DCE 460: 2 hours, C minimum",
        "IN-PROG> 2.00 HOURS",
        row("FA26", "DCE 460", 2.0, "NR", "TRANSITIONS I"),
        *needs("7", "DCE 461: 2 hours, C minimum", 2.0, ["DCE 461"]),
        *needs("8", "DCE 403 OR DCE 404: 3 hours, C minimum", 3.0,
               ["DCE 403", "DCE 404"]),
        "PERSONAL MOVEMENT PRACTICE Requirement",
        "----------------------------------------------------------",
        "Advancement in Personal Movement Practices is determined by",
        "instructor. Choose from the course list for each division.",
        "----------------------------------------------------------",
        "IP 1) Lower Division Personal Movement Practice: 12 hours",
        "12.00 Hours Earned 6 Courses",
        row("FA24", "DCE 134", 2.0, "A", "CONTEMPORARY MODERN I"),
        row("SP25", "DCE 135", 2.0, "A", "CONTEMPORARY BALLET I"),
        row("FA25", "DCE 234", 2.0, "A", "CONTEMPORARY MODERN II"),
        row("FA25", "DCE 133", 2.0, "A-", "HIP HOP I"),
        row("SP26", "DCE 235", 2.0, "A", "CONTEMPORARY BALLET II"),
        row("SP26", "DCE 139", 2.0, "A", "AFRO-LATIN I"),
        "IP 2) Upper Division Personal Movement Practice: 9 hours",
        "Complete 2 courses:",
        "3.00 Hours Earned",
        "IN-PROG> 3.00 HOURS",
        "NEEDS: 3.00 HOURS",
        "COURSE LIST: " + " ".join(upper_pmp),
        row("SP26", "DCE 333", 3.0, "A", "HIP HOP III"),
        row("FA26", "DCE 334", 3.0, "NR", "CONTEMPORARY MODERN III"),
        "-> NOT FROM: " + " ".join(lower_pmp),
        "DANCE ELECTIVES",
        *needs("1", "DCE Upper Division Elective: 2 hours", 2.0),
        *needs("2", "Upper Division Elective: 3 hours", 3.0),
        "************************ END OF ANALYSIS ************************",
        FOOTER,
    ]
    return "\n".join(lines)


# --------------------------------------------------------------------------
# Aerospace Engineering (Aeronautics), BSE — Fulton (ESAEROBSE)
# --------------------------------------------------------------------------

def aerospace_transfer_credit_heavy() -> str:
    """Transfer/AP-satisfied requirements, wildcards, and a capped sub-list."""
    technical = ["BME 467", "BME 494", "CEE 494", "CHE 494", "EEE 350", "EEE 407",
                 "EEE 473", "EEE 480", "EEE 481", "EEE 498", "MSE 494", "SES 494"]
    capped = ["AST 321", "AST 322", "BME 350", "CEE 440", "CHE 468", "CHE 478",
              "CHM 325", "EEE 304", "EEE 333", "EEE 334", "EGR 317", "EGR 433",
              "FSE 301", "FSE 394", "FSE 404", "IEE 300", "MAT 300", "MAT 371",
              "MAT 420", "MAT 421", "MAT 423", "MAT 425", "MAT 451", "MSE 330",
              "PHY 310", "PHY 361", "SES 311", "SES 350", "SES 405", "SES 407",
              "SES 410"]
    sobe = ["PAF 311", "PAF 410", "POS 301", "STS 304", "SWU 349", "SWU 350"]
    lines = _header(
        "BSE AEROSPACE ENGINEERING", "IRA A. FULTON SCHOOLS OF ENGINEERING",
        "ES AERO BSE", "Aerospace Engineering", "08/24/2026 10:31 PM",
    )
    lines += [
        "OPT Credit By Exam and Military Credit 60-Hour Maximum",
        "1) Credit By Exam and Military Credit hours:",
        "60 hours Maximum.",
        "27.00 Hours Earned",
        "OPT Two-Year Institution 64 Hour Maximum",
        "1) Two-year institution hours: 64 hours Maximum.",
        "15.00 Hours Earned",
        "OPT IN PROGRESS COURSES",
        "IP These courses are currently in progress:",
        row("FA26", "AEE 344", 3.0, "NR", "FUNDAMENTALS OF AIRCRAFT DESIGN"),
        row("FA26", "AEE 362", 3.0, "NR", "HIGH-SPEED AERODYNAMICS"),
        row("FA26", "MAE 318", 3.0, "NR", "SYSTEM DYNAMICS AND CONTROL"),
    ]
    lines += _totals(82.0, 9.0, 21.0, 24.0, 3.55)
    lines += [
        "University General Studies Requirement - Gold",
        "MATHEMATICS",
        *done("1", "Mathematics (MATH): 3 hours", 5.0,
              [row("SU23", "MAT 265", 3.0, "AP", "CALCULUS FOR ENGINEERS I", campus="")]),
        "University General Studies Requirement - Gold",
        "SCIENTIFIC THINKING IN NATURAL SCIENCES",
        *done("1", "Scientific Thinking in Natural Sciences (SCIT): 8 hours", 8.0,
              [row("SU23", "PHY 121", 4.0, "AP", "UNIVERSITY PHYSICS I", campus=""),
               row("SU23", "CHM 114", 4.0, "AP", "GENERAL CHEMISTRY", campus="")],
              courses=2),
        "University General Studies Requirement - Gold",
        "HUMANITIES, ARTS AND DESIGN",
        *done("1", "Humanities, Arts and Design (HUAD): 3 hours", 3.0,
              [row("SU23", "HUM 100", 3.0, "IB", "HUMANITIES SEMINAR", campus="")]),
        "University General Studies Requirement - Gold",
        "AMERICAN INSTITUTIONS",
        *needs("1", "American Institutions (AMIT): 3 hours", 3.0),
        "University General Studies Requirement - Gold",
        "GLOBAL COMMUNITIES, SOCIETIES AND INDIVIDUALS",
        *needs("1", "Global Communities, Societies and Individuals (GCSI):", 3.0,
               note=["3 hours"]),
        "University General Studies Requirement - Gold",
        "GOVERNANCE AND CIVIC ENGAGEMENT",
        *needs("1", "Governance and Civic Engagement (CIVI): 3 hours", 3.0),
        "\f",
        HEADER_STAMP,
        "AEROSPACE ENGINEERING Major - 120 hours",
        "----------------------------------------------------------",
        "Grade of C (2.00) or better required.",
        "----------------------------------------------------------",
        "NEEDS: 24.00 HOURS 8 SUB-GROUPS",
        *done("1", "MAT 267: 4 hours, C minimum", 4.0,
              [row("FA24", "MAT 267", 4.0, "A", "CALCULUS FOR ENGINEERS III")]),
        *done("2", "AEE 261: 3 hours, C minimum", 3.0,
              [row("SP25", "AEE 261", 3.0, "B+", "INTRO TO AEROSPACE ENGINEERING")]),
        "IP 3) AEE 344: 3 hours, C minimum",
        "IN-PROG> 3.00 HOURS",
        row("FA26", "AEE 344", 3.0, "NR", "FUNDAMENTALS OF AIRCRAFT DESIGN"),
        "IP 4) AEE 362: 3 hours, C minimum",
        "IN-PROG> 3.00 HOURS",
        row("FA26", "AEE 362", 3.0, "NR", "HIGH-SPEED AERODYNAMICS"),
        *needs("5", "AEE 415: 3 hours, C minimum", 3.0, ["AEE 415"]),
        *needs("6", "AEE 462: 3 hours, C minimum", 3.0, ["AEE 462"]),
        *needs("7", "AEE 463: 3 hours, C minimum", 3.0, ["AEE 463"]),
        *needs("8", "AEE 468: 3 hours, C minimum", 3.0, ["AEE 468"]),
        "UPPER DIVISION TECHNICAL ELECTIVES",
        "----------------------------------------------------------",
        "Courses not listed here require a program petition prior to",
        "enrollment. Please check with your advisor.",
        "----------------------------------------------------------",
        "1) Upper Division Technical Elective: 9 hours - 3 courses",
        "NEEDS: 9.00 HOURS 3 COURSES",
        "COURSE LIST: AEE OR MAE OR MEE 3** Elective",
        "AEE OR MAE OR MEE 4** Elective",
        "COURSE LIST: " + " ".join(technical),
        "2) Students may choose no more than one course from the",
        "following:",
        "NEEDS: 0.00 HOURS 1 COURSE MAXIMUM",
        "COURSE LIST: " + " ".join(capped),
        "UPPER DIVISION SOBE TRACK",
        "----------------------------------------------------------",
        "Choose an Upper Division SOBE Track Course from the list.",
        "----------------------------------------------------------",
        *needs("1", "Upper Division SOBE Track Course: 3 hours", 3.0, sobe),
        "************************ END OF ANALYSIS ************************",
        FOOTER,
    ]
    return "\n".join(lines)


FIXTURES = {
    "journalism_early_semester": journalism_early_semester,
    "journalism_unresolved_elective_block": journalism_unresolved_elective_block,
    "dance_bfa_near_graduation": dance_bfa_near_graduation,
    "aerospace_transfer_credit_heavy": aerospace_transfer_credit_heavy,
}


def synthetic_dir() -> Path:
    return Path(__file__).resolve().parent / "dars_synthetic"


def build_all(destination: Path | None = None) -> dict[str, Path]:
    """Render every fixture, and return {name: path}. Idempotent."""
    target = destination or synthetic_dir()
    written: dict[str, Path] = {}
    for name, builder in FIXTURES.items():
        written[name] = write_text_pdf(target / f"{name}.pdf", builder())
    return written


if __name__ == "__main__":
    for name, path in build_all().items():
        print(f"{name}: {path} ({path.stat().st_size} bytes)")
