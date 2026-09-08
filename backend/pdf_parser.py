"""Hierarchy-aware parser for text-based ASU uAchieve/DARS PDF reports.

The report repeats the same transcript rows in many requirement sections.  The
parser therefore treats the document as two related data sets:

* a globally deduplicated transcript, and
* numbered requirement blocks nested under report section headings.

It deliberately ignores administrative limits and advisory-only sections.
Every returned requirement retains compact source text so a user can audit the
heuristic result without reopening the PDF.
"""

from __future__ import annotations

import hashlib
import io
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

import pdfplumber

from .lexicon import Lexicon
from .asu_catalog import (
    CAPPED_SUBLIST_RE,
    CATEGORY_LABELS,
    COMPLETE_N_COURSES_RE,
    COURSE_COUNT_RE,
    DesignationVocabulary,
    categorize,
    coverage_report,
    designations_in,
    to_int,
    wildcard_patterns_in,
)


#: Read once per process. The lexicon is an additive, read-only prior, so a
#: missing file costs only accuracy on ambiguous lines, never correctness.
LEXICON = Lexicon.load()

MAX_PDF_PAGES = 80
MAX_PDF_BYTES = 25 * 1024 * 1024

COURSE_LINE_RE = re.compile(
    r"^(FA|SP|SU)(\d{2})\s+"
    r"(?:([A-Z])\s+)?"
    r"([A-Z]{2,4})\s+(\d{3}[A-Z]?)\s+"
    r"(\d+(?:\.\d{1,2})?)\s+"
    r"([A-Z][A-Z0-9+\-*]*)\s*"
    r"(?:(>>|>#|>R)\s*)?"
    r"(.*)$"
)
COURSE_TOKEN_RE = re.compile(r"\b([A-Z]{2,4})\s+(\d{3}[A-Z]?)\b")
NUMBERED_REQUIREMENT_RE = re.compile(r"^(IP\s+)?(\d+(?:\.\d+)*)\)\s*(.*)$", re.IGNORECASE)
NEEDS_HOURS_RE = re.compile(r"NEEDS:\s*(\d+(?:\.\d+)?)\s*HOURS?", re.IGNORECASE)
NEEDS_GPA_RE = re.compile(r"NEEDS:\s*(\d+(?:\.\d+)?)\s*GPA", re.IGNORECASE)
EARNED_HOURS_RE = re.compile(
    r"(?:EARNED:\s*)?(\d+(?:\.\d+)?)\s*HOURS?\s+EARNED|"
    r"EARNED:\s*(\d+(?:\.\d+)?)\s*HOURS?",
    re.IGNORECASE,
)
INLINE_EARNED_RE = re.compile(r"^(\d+(?:\.\d+)?)\s*Hours?\s+Earned", re.IGNORECASE)
IN_PROGRESS_RE = re.compile(r"IN-PROG>\s*(\d+(?:\.\d+)?)\s*HOURS?", re.IGNORECASE)
HOURS_RE = re.compile(r"(?<![\d.])(\d+(?:\.\d+)?|\.\d+)\s*(?:hours?|credits?)", re.IGNORECASE)
GPA_RE = re.compile(r"(\d+\.\d+)\s*GPA", re.IGNORECASE)
CATALOG_RE = re.compile(r"(?:For\s+|approved catalog:\s*)(\d{2,4}-\d{2,4})", re.IGNORECASE)
OFFICIAL_MAJOR_RE = re.compile(
    r"^([A-Z][A-Za-z\s&/]+?)(?:\s*,\s*|\s+For\s+)(?:Tempe|Online|Polytechnic|Downtown|West|For|\d)",
)
UPPER_DIVISION_HONORS_RE = re.compile(
    r"^(\d+)\s+UPPER\s+DIVISION\s+HONORS\s+CREDITS?\b",
    re.IGNORECASE,
)
THESIS_GATE_RE = re.compile(
    r"^(?:FINAL\s+THESIS\s+APPROVAL|SUBMITTED\s+HONORS\s+THESIS\s+CHECK)\s*$",
    re.IGNORECASE,
)
MAJOR_SECTION_RE = re.compile(
    r"^(?:B[AS]\s+)?([A-Z][A-Z\s&/\-]+?)\s+Major(?:\s*-\s*\d+(?:\.\d+)?\s*hours?)?$",
    re.IGNORECASE,
)

COMPLETED_GRADES = {
    "A+", "A", "A-", "B+", "B", "B-", "C+", "C", "C-",
    "D+", "D", "D-", "P", "S", "Y", "TA", "XE", "IB", "IB*", "AP",
}
IN_PROGRESS_GRADES = {"NR"}
NOT_COMPLETED_GRADES = {"E", "EU", "W", "X", "I"}

GENERIC_SECTION_LINES = {
    "ATTENTION!",
    "UNIVERSITY REQUIREMENT",
    "UNIVERSITY GENERAL STUDIES REQUIREMENT - GOLD",
    "THE COLLEGE OF LIBERAL ARTS AND SCIENCES",
    "TOWARD A MINOR.",
    "BUSINESS CORE PRIOR TO REGISTRATION",
    "BUSINESS CAPSTONE REQUIRES THE COMPLETION OF THE",
    "TWO MAJOR COURSES ARE ALLOWED TO SHARE WITH A CERTIFICATE.",
    "DEVELOPMENT ONLY.",
    "ELECTIVES HOURS",
    "HOURS NOT USED TO MEET SPECIFIC REQUIREMENTS",
    "TO MEET SPECIFIC CERTIFICATE REQUIREMENTS",
    "IN PROGRESS COURSES (HONORS)",
    "PRECALCULUS",
}

SECTION_STOP_PREFIXES = (
    "OPT TOTAL HOURS REQUIRED",
    "OPT ELECTIVES:",
    "OPT THE FOLLOWING",
    "OPT LOWER DIVISION",
    "HOURS NOT USED",
    "ELECTIVES HOURS",
    "************************ END",
)

ADMINISTRATIVE_PHRASES = (
    "maximum",
    "credit by exam",
    "two-year institution",
    "2-year institutions",
    "duplicate or repeated",
    "student athlete development",
)

BOILERPLATE_PHRASES = (
    "grade of c",
    "courses in this section cannot",
    "toward a minor",
    "strongly encouraged",
    "course list link",
    "check the requirements",
    "this audit",
    "registrar",
    "copyright",
    "privacy",
    "minimum 12 upper division",
    "minimum 18 upper division",
    "the needs hours note",
)


@dataclass
class _Block:
    section: str
    prefix_in_progress: bool
    number: str
    title: str
    lines: list[str] = field(default_factory=list)


def extract_text(pdf_path: str | Path) -> str:
    """Extract ordered text from every PDF page."""
    path = Path(pdf_path)
    if path.stat().st_size > MAX_PDF_BYTES:
        raise ValueError("PDF is larger than the 25 MB local safety limit.")

    pages: list[str] = []
    with pdfplumber.open(str(path)) as pdf:
        if len(pdf.pages) > MAX_PDF_PAGES:
            raise ValueError(f"PDF has more than {MAX_PDF_PAGES} pages.")
        for page in pdf.pages:
            pages.append(page.extract_text(x_tolerance=2, y_tolerance=3) or "")
    text = "\n\f\n".join(pages)
    if len(text.strip()) < 80:
        raise ValueError("No usable text was found. Export a text-based DARS PDF instead of a scan.")
    return text


def extract_text_bytes(data: bytes) -> str:
    """Extract DARS text directly from an uploaded PDF without persisting it."""
    if len(data) > MAX_PDF_BYTES:
        raise ValueError("PDF is larger than the 25 MB local safety limit.")
    if not data.startswith(b"%PDF"):
        raise ValueError("The uploaded file is not a valid PDF.")

    pages: list[str] = []
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        if pdf.doc.encryption: raise ValueError("Encrypted PDFs are unsupported. Export an unprotected DARS report.")
        if len(pdf.pages) > MAX_PDF_PAGES:
            raise ValueError(f"PDF has more than {MAX_PDF_PAGES} pages.")
        for page in pdf.pages:
            pages.append(page.extract_text(x_tolerance=2, y_tolerance=3) or "")
    text = "\n\f\n".join(pages)
    if len(text.strip()) < 80:
        raise ValueError("No usable text was found. Export a text-based DARS PDF instead of a scan.")
    return text


def _normalize_lines(text: str) -> list[str]:
    lines: list[str] = []
    for raw in text.replace("\u00a0", " ").splitlines():
        line = re.sub(r"\s+", " ", raw).strip()
        if line:
            lines.append(line)
    return lines


def _title_case_name(value: str) -> str:
    value = re.sub(r"^(?:BS|BA|B\.S\.|B\.A\.)\s+", "", value.strip(), flags=re.IGNORECASE)
    name = value.title()
    for source, target in ((" And ", " and "), (" Of ", " of "), (" In ", " in ")):
        name = name.replace(source, target)
    return name


def _extract_official_majors(lines: list[str]) -> list[str]:
    majors: list[str] = []
    expect_major = False
    for line in lines:
        if re.search(r"official major/catalog year on file is", line, re.IGNORECASE):
            expect_major = True
            continue
        if not expect_major:
            continue
        expect_major = False
        match = OFFICIAL_MAJOR_RE.match(line)
        if match:
            name = _title_case_name(match.group(1))
            if name not in majors:
                majors.append(name)
    return majors


def _detect_focus_major(lines: list[str], official_majors: list[str]) -> str:
    joined = "\n".join(lines)
    # Evaluated program headers take precedence over declared majors elsewhere.
    explicit = re.search(r"^(?:Evaluated Program|Program Name|Degree Program)\s*:\s*(.+)$", joined, re.M | re.I)
    if explicit:
        return _title_case_name(explicit.group(1))
    if re.search(
        r"Barrett,\s*The Honors College|HONORS CREDIT COUNT|LOWER DIVISION HONORS REQUIREMENTS",
        joined,
        re.IGNORECASE,
    ):
        return "Barrett Honors College"

    official_lookup = {m.casefold(): m for m in official_majors}
    candidates: list[str] = []
    for line in lines:
        match = MAJOR_SECTION_RE.match(line)
        if not match:
            continue
        raw = _title_case_name(match.group(1))
        matched = next(
            (
                canonical
                for key, canonical in official_lookup.items()
                if key in raw.casefold() or raw.casefold() in key
            ),
            raw,
        )
        if matched not in candidates:
            candidates.append(matched)
    if candidates:
        return candidates[-1]
    program = re.search(r"^(?:MINOR|CERTIFICATE)\s+(?:IN\s+)?(.+?)(?:\s+REQUIREMENTS)?$", joined, re.M | re.I)
    if program:
        return _title_case_name(program.group(0))
    metadata = re.search(r"Program Code\s+(.+?)(?=\s+Catalog Year|$)", joined, re.I | re.M)
    if metadata and not official_majors:
        return metadata.group(1).strip()
    if len(official_majors) == 1:
        return official_majors[0]
    raise ValueError("Could not determine which program this audit evaluates.")


def _course_status(grade: str) -> str:
    if grade in IN_PROGRESS_GRADES:
        return "in_progress"
    if grade in NOT_COMPLETED_GRADES:
        return "not_completed"
    if grade in COMPLETED_GRADES:
        return "complete"
    return "not_completed"


def _parse_course_line(line: str) -> dict[str, Any] | None:
    match = COURSE_LINE_RE.match(line)
    if not match:
        return None
    season, year, campus, subject, number, credits, grade, _marker, title = match.groups()
    return {
        "code": f"{subject} {number}",
        "term": f"{season}{year}",
        "campus": campus or "",
        "subject": subject,
        "number": number,
        "credits": float(credits),
        "grade": grade,
        "title": title.strip(),
        "status": _course_status(grade),
    }


def _deduplicate_courses(courses: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Deduplicate report repeats while preserving legitimate retakes."""
    best: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    status_rank = {"not_completed": 0, "in_progress": 1, "complete": 2}
    for course in courses:
        key = (course["term"], course["subject"], course["number"], course["grade"])
        existing = best.get(key)
        if existing is None or (
            course["credits"],
            status_rank[course["status"]],
            len(course["title"]),
        ) > (
            existing["credits"],
            status_rank[existing["status"]],
            len(existing["title"]),
        ):
            best[key] = course
    return sorted(best.values(), key=lambda c: (c["term"], c["subject"], c["number"], c["grade"]))


def _looks_like_section(line: str) -> bool:
    if line.upper() in GENERIC_SECTION_LINES:
        return False
    if line.startswith(("NEEDS:", "EARNED:", "IN-PROG>", "COURSE LIST:", "NOTE:", "->")):
        return False
    if INLINE_EARNED_RE.search(line) or re.fullmatch(r"\d+\s+Courses?", line, re.IGNORECASE):
        return False
    # A measurement row is data, not a heading. "15.00 ATTEMPTED HOURS 59.00
    # POINTS 3.93 GPA" is almost entirely uppercase, so the ratio test below
    # read it as a new section and closed the block it belongs to — which left
    # that block's own "NEEDS: 2.00 GPA" orphaned and reported as a condition
    # the parser had failed to read.
    if re.match(r"^\d", line) and re.search(
        r"\b(?:ATTEMPTED\s+HOURS|POINTS|GPA|HOURS?|SUB-?GROUPS?|COURSES?|SETS?\s+TAKEN)\b",
        line,
        re.IGNORECASE,
    ):
        return False
    if (
        _parse_course_line(line)
        or re.match(r"^(?:FA|SP|SU)\d{2}\s+", line)
        or NUMBERED_REQUIREMENT_RE.match(line)
    ):
        return False
    if any(phrase in line.casefold() for phrase in BOILERPLATE_PHRASES):
        return False
    if re.fullmatch(r"[*~=\- ]+", line):
        return False

    letters = [char for char in line if char.isalpha()]
    uppercase_ratio = (
        sum(char.isupper() for char in letters) / len(letters)
        if letters
        else 0.0
    )
    semantic_header = re.match(
        r"^(?:"
        r".+\s+Requirements?|"
        r".+\s+Major(?:\s*-\s*\d+(?:\.\d+)?\s*hours?)?|"
        r".+\s+Hour Check|"
        r"UD HOURS CHECK.*|"
        r"TOTAL HOURS:.*|UPPER DIVISION:.*|RESIDENT CREDIT:.*|"
        r"Honors Credit Count:.*"
        r")$",
        line,
        re.IGNORECASE,
    )
    return bool(
        3 < len(line) < 90
        and (
            uppercase_ratio >= 0.82
            or semantic_header
            or line in {"The ASU Experience", "Graduation With Academic Recognition"}
        )
    )


def _clean_section(line: str) -> str:
    cleaned = re.sub(r"^(?:OPT|IP)\s+", "", line).strip(" :-")
    return re.sub(r"\s+", " ", cleaned)


def _extract_course_tokens(text: str) -> list[str]:
    found: list[str] = []
    for subject, number in COURSE_TOKEN_RE.findall(text):
        code = f"{subject} {number}"
        if code not in found:
            found.append(code)
    return found


def _find_float(pattern: re.Pattern[str], lines: Iterable[str]) -> float | None:
    for line in lines:
        match = pattern.search(line)
        if match:
            for group in match.groups():
                if group is not None:
                    return float(group)
    return None


def _extract_required_credits(title: str, lines: list[str]) -> float:
    match = HOURS_RE.search(title)
    if match:
        return float(match.group(1))
    for line in lines:
        if line.startswith("- ") or re.fullmatch(r"\d+(?:\.\d+)?\s*hours?", line, re.IGNORECASE):
            match = HOURS_RE.search(line)
            if match:
                return float(match.group(1))
    return 0.0


#: How a category presents on the map.  ``kind`` is the long-standing public
#: field (see ``Requirement`` in the generated TypeScript contract); ``category``
#: is the richer signal introduced alongside it.  Deriving one from the other
#: keeps them from ever disagreeing.
_KIND_BY_CATEGORY = {
    "gpa": "gpa",
    "hour_check": "milestone",
    "constraint": "milestone",
    "project": "project",
    "general_studies": "elective",
    "elective_open": "elective",
    "elective_constrained": "elective",
    "language": "elective",
    "unclassified": "elective",
}


def _requirement_kind(category: str, options: list[str]) -> str:
    """Map a category onto the public ``kind`` field.

    The previous implementation matched the words "upper division" anywhere in a
    section or title and returned ``milestone``.  That swallowed every directed
    upper-division elective block — "Upper Division Technical Elective: 9 hours",
    "Upper Division Capstone Course", "JMC OR MCO Upper Division Elective" — and
    the hosted engine drops credit-bearing milestones, so 12 to 27 credits per
    audit disappeared from the map with no warning.  Categories distinguish an
    hour check from an elective that merely mentions upper division.
    """
    mapped = _KIND_BY_CATEGORY.get(category)
    if mapped:
        return mapped
    return "course" if options else "elective"


def _criteria_for(
    section: str,
    title: str,
    options: list[str],
    lines: list[str],
    vocabulary: DesignationVocabulary | None = None,
    wildcards: list[dict[str, Any]] | None = None,
) -> list[str]:
    """Plain-language conditions a course must meet to fill this requirement.

    These become the visible slot label, so they are written for a student
    choosing a class, not for the parser.  General Studies areas resolve through
    ``vocabulary``, which prefers the name this document gave the code over the
    shipped table, so a designation ASU renames still reads correctly.
    """
    combined = " ".join([section, title, *lines])
    criteria: list[str] = []
    if re.search(r"upper division|300-400", combined, re.IGNORECASE):
        criteria.append("Upper-division course")
    if re.search(r"lower division", combined, re.IGNORECASE):
        criteria.append("Lower-division course")
    subject_elective = re.search(r"\b([A-Z]{2,4})\s+Elective\b", title)
    if subject_elective and not options:
        criteria.append(f"{subject_elective.group(1)} elective")
    for pattern in wildcards or []:
        criteria.append(str(pattern["label"]).capitalize())
    resolver = vocabulary or DesignationVocabulary()
    for code in designations_in(title) or designations_in(section):
        criteria.append(f"ASU General Studies {resolver.label(code)}")
    if re.search(r"related area", combined, re.IGNORECASE):
        criteria.append("Advisor-approved related area course")
    if re.search(r"\btrack course\b", combined, re.IGNORECASE):
        criteria.append("Approved track course")
    if "science and society" in combined.casefold():
        criteria.append("Approved Science and Society course")
    if "honors remaining credits" in combined.casefold():
        criteria.append("Honors credit")
    return list(dict.fromkeys(criteria))


def _block_to_requirement(
    block: _Block,
    major: str,
    source_file: str,
    vocabulary: DesignationVocabulary | None = None,
) -> dict[str, Any] | None:
    title = re.sub(r"\s+", " ", block.title).strip(" .")
    section = _clean_section(block.section) or "Degree requirements"
    if re.fullmatch(r"\d+(?:\.\d+)?\s*Hours Earned", title, re.IGNORECASE):
        title = section
    combined = " ".join([section, title, *block.lines])
    lowered = combined.casefold()
    heading_lowered = f"{section} {title}".casefold()

    if any(phrase in heading_lowered for phrase in ADMINISTRATIVE_PHRASES):
        return None
    if section.upper().startswith(SECTION_STOP_PREFIXES):
        return None

    exact_options = _extract_course_tokens(title)
    # A wildcard slot ("AEE OR MAE OR MEE 3** Elective") names a whole level of a
    # department rather than a course, so COURSE_TOKEN_RE never sees it. Captured
    # as a first-class pattern it stays resolvable instead of decaying into a
    # generic placeholder.
    wildcards = wildcard_patterns_in(title)
    # "Students may choose no more than one course from the following:" caps a
    # sibling list. Its courses are permissions, not requirements, so they are
    # held apart from the options that can satisfy this block.
    capped_options: list[str] = []
    capped_limit = 0
    in_capped_list = False
    # DARS states the cap either as its own numbered requirement — "2) Students
    # may choose no more than one course from the following:" — or as a note
    # inside a block, so both the title and the body have to be read.
    title_cap = CAPPED_SUBLIST_RE.search(title)
    if title_cap:
        in_capped_list = True
        capped_limit = to_int(title_cap.group(1)) or 1

    for line in block.lines:
        if line.startswith("-> NOT FROM:"):
            continue
        capped = CAPPED_SUBLIST_RE.search(line)
        if capped:
            in_capped_list = True
            capped_limit = to_int(capped.group(1)) or 1
            continue
        if in_capped_list:
            capped_options.extend(
                code for code in _extract_course_tokens(line) if code not in capped_options
            )
            continue
        for pattern in wildcard_patterns_in(line):
            if pattern not in wildcards:
                wildcards.append(pattern)
        if line.startswith("COURSE LIST:") or exact_options or "elective" in title.casefold():
            for code in _extract_course_tokens(line):
                if code not in exact_options:
                    exact_options.append(code)

    exclusions: list[str] = []
    for line in block.lines:
        if line.startswith("-> NOT FROM:"):
            exclusions.extend(_extract_course_tokens(line))
    exclusions = list(dict.fromkeys(exclusions))
    exact_options = [code for code in exact_options if code not in exclusions]

    completed_rows = [
        parsed
        for line in block.lines
        if (parsed := _parse_course_line(line)) and parsed["status"] == "complete"
    ]
    progress_rows = [
        parsed
        for line in block.lines
        if (parsed := _parse_course_line(line)) and parsed["status"] == "in_progress"
    ]

    earned = _find_float(INLINE_EARNED_RE, block.lines)
    if earned is None:
        earned = _find_float(EARNED_HOURS_RE, block.lines)
    earned = earned if earned is not None else sum(c["credits"] for c in completed_rows)

    in_progress = _find_float(IN_PROGRESS_RE, block.lines)
    in_progress = (
        in_progress
        if in_progress is not None
        else sum(c["credits"] for c in progress_rows)
    )
    needed = _find_float(NEEDS_HOURS_RE, block.lines)
    required = _extract_required_credits(title, block.lines)
    if required <= 0 and needed is not None:
        required = earned + in_progress + needed

    needs_gpa = _find_float(NEEDS_GPA_RE, block.lines)
    if needs_gpa is not None:
        required = needs_gpa

    if needed is not None and needed > 0:
        status = "in_progress" if (block.prefix_in_progress or in_progress > 0) else "remaining"
    elif required > 0 and earned >= required:
        status = "complete"
    elif block.prefix_in_progress or in_progress > 0:
        status = "in_progress"
    elif earned > 0 or completed_rows:
        # Thesis gates carry no hours or course rows and are handled by
        # _honors_thesis_requirements, which knows the wording advances as the
        # student progresses.  They must not be inferred complete from a title.
        status = "complete"
    elif required > 0 or exact_options or "elective" in lowered:
        status = "remaining"
    else:
        return None

    remaining = (
        needed
        if needed is not None
        else max(0.0, required - earned - in_progress)
    )
    if status == "complete":
        remaining = 0.0

    body_text = " ".join(block.lines)
    designations = designations_in(title) or designations_in(section)

    # "Complete 2 courses:" and "- two courses" both say how many separate
    # classes this block needs, which is what stops a 9-hour block from being
    # planned as one impossible 9-credit class.  It is also the denominator in
    # the structural elective test below, so it has to be known first.
    required_count = 0
    for source in (title, body_text):
        match = COMPLETE_N_COURSES_RE.search(source) or COURSE_COUNT_RE.search(source)
        if match:
            required_count = max(required_count, to_int(match.group(1)))
    if not required_count and required > 0:
        # Size the slot count from what is still owed, not from the block's
        # lifetime total: a 24-hour elective block with 12 hours already earned
        # needs four more classes, not eight.
        outstanding = remaining if status == "remaining" and remaining > 0 else required
        required_count = max(1, round(outstanding / 3.0))

    category = categorize(
        section,
        title,
        body_text,
        designations=designations,
        has_options=bool(exact_options or wildcards),
        option_count=len(exact_options),
        required_count=required_count,
        has_wildcards=bool(wildcards),
        credits_required=required,
        lexicon=LEXICON,
    )
    criteria = _criteria_for(section, title, exact_options, block.lines, vocabulary, wildcards)
    kind = _requirement_kind(category, exact_options)
    source_lines = [f"{block.number}) {title}", *block.lines]
    source_text = " · ".join(dict.fromkeys(source_lines))[:900]

    confidence = 0.98
    if not exact_options and kind in {"course", "elective"}:
        confidence = 0.84 if criteria else 0.72
    if status == "complete" and not completed_rows and earned <= 0:
        confidence = min(confidence, 0.8)

    identity = f"{major}|{section}|{block.number}|{title}"
    requirement_id = hashlib.sha1(identity.encode("utf-8")).hexdigest()[:12]
    return {
        "id": requirement_id,
        "major": major,
        "section": section,
        "name": title or section,
        "kind": kind,
        "status": status,
        "credits_required": round(required, 2),
        "credits_earned": round(earned, 2),
        "credits_in_progress": round(in_progress, 2),
        "credits_remaining": round(remaining, 2),
        "course_options": exact_options,
        "courses_completed": list(dict.fromkeys(c["code"] for c in completed_rows)),
        "courses_in_progress": list(dict.fromkeys(c["code"] for c in progress_rows)),
        "criteria": criteria,
        "exclusions": exclusions,
        "category": category,
        "category_label": CATEGORY_LABELS[category],
        "designations": designations,
        "wildcards": wildcards,
        "required_count": required_count,
        "capped_options": capped_options,
        "capped_limit": capped_limit,
        "source_text": source_text,
        "confidence": confidence,
        "source_label": block.number,
        "logic": "all" if re.search(r"\bAND\b|\s&\s", title, re.I) else "any" if re.search(r"\bOR\b", combined, re.I) else "unknown",
        "minimum_grade": (m.group(1) if (m := re.search(r"(?:minimum grade(?: of)?|grade of)\s+([A-D][+-]?)\b", combined, re.I)) else ""),
        "needs_review": confidence < 0.8,
    }


def _special_requirements(lines: list[str], major: str, source_file: str) -> list[dict[str, Any]]:
    """Capture important non-numbered DARS summaries."""
    special: list[dict[str, Any]] = []

    if major == "Barrett Honors College":
        gpa_line = next((line for line in lines if line == "3.25 ASU GPA"), None)
        if gpa_line:
            next_index = lines.index(gpa_line) + 1
            earned_gpa = _find_float(GPA_RE, lines[next_index:next_index + 3])
            special.append(
                _special_requirement(
                    major,
                    source_file,
                    "Honors foundations",
                    "3.25 ASU GPA",
                    "gpa",
                    "complete" if (earned_gpa or 0) >= 3.25 else "remaining",
                    3.25,
                    earned_gpa or 0.0,
                    0.0,
                    0.0 if (earned_gpa or 0) >= 3.25 else 3.25 - (earned_gpa or 0),
                    [gpa_line, *lines[next_index:next_index + 1]],
                )
            )

        count_index = next(
            (index for index, line in enumerate(lines) if line.startswith("HONORS CREDIT COUNT:")),
            None,
        )
        if count_index is not None:
            needed = _find_float(NEEDS_HOURS_RE, lines[count_index:count_index + 3]) or 0.0
            required = _extract_required_credits(lines[count_index], [])
            special.append(
                _special_requirement(
                    major,
                    source_file,
                    "Honors credit",
                    "36 honors credits",
                    "elective",
                    "remaining" if needed > 0 else "complete",
                    required,
                    max(0.0, required - needed),
                    0.0,
                    needed,
                    lines[count_index:count_index + 3],
                    ["Honors credit"],
                )
            )

        upper_index = next(
            (
                index
                for index, line in enumerate(lines)
                if UPPER_DIVISION_HONORS_RE.match(line)
            ),
            None,
        )
        if upper_index is not None:
            window = lines[upper_index:upper_index + 4]
            required = _extract_required_credits(lines[upper_index], []) or 18.0
            earned = _find_float(EARNED_HOURS_RE, window) or 0.0
            in_progress = _find_float(IN_PROGRESS_RE, window) or 0.0
            remaining = max(0.0, required - earned - in_progress)
            if remaining > 0:
                status = "in_progress" if in_progress > 0 else "remaining"
            else:
                status = "complete" if in_progress <= 0 else "in_progress"
            special.append(
                _special_requirement(
                    major,
                    source_file,
                    "Honors credit",
                    f"{required:g} upper-division honors credits",
                    "elective",
                    status,
                    required,
                    earned,
                    in_progress,
                    remaining,
                    window,
                    ["Honors credit", "Upper-division course"],
                )
            )

        special.extend(_honors_thesis_requirements(lines, major, source_file))
    return special


def _honors_thesis_requirements(
    lines: list[str],
    major: str,
    source_file: str,
) -> list[dict[str, Any]]:
    """Track the Barrett thesis, which DARS reports as a moving gate.

    The report shows only the *current* gate, and renames it as the student
    advances: ``SUBMITTED HONORS THESIS CHECK`` ("Honors Thesis submitted")
    becomes ``FINAL THESIS APPROVAL`` ("Final Thesis Approval received") once
    the thesis has been handed in.  The wording therefore describes what is
    still required, not what has happened, so an active gate means the thesis
    is still outstanding.  These blocks carry no hours and no course rows, so
    the generic requirement parser discards them entirely.

    The thesis is recorded as a zero-credit milestone: it must appear in the
    plan and be scheduled before graduation, but Barrett determines the actual
    thesis-credit enrolment, so no credits are invented here.
    """
    gate_index = next(
        (index for index, line in enumerate(lines) if THESIS_GATE_RE.match(line)),
        None,
    )
    if gate_index is None:
        return []

    window = lines[gate_index:gate_index + 3]
    detail = next(
        (line for line in window[1:] if NUMBERED_REQUIREMENT_RE.match(line)),
        lines[gate_index],
    )
    awaiting_approval = any(
        re.search(r"final thesis approval", line, re.IGNORECASE) for line in window
    )
    name = (
        "Honors thesis final approval"
        if awaiting_approval
        else "Honors thesis submission"
    )
    pending_note = any(
        re.search(r"pending\s+(?:honors\s+projects|final evaluation)", line, re.IGNORECASE)
        for line in lines
    )
    source_lines = [*window]
    if pending_note:
        source_lines.append("OPT PENDING HONORS PROJECTS: pending final evaluation")

    return [
        _special_requirement(
            major,
            source_file,
            "Honors thesis",
            name,
            "project",
            "remaining",
            0.0,
            0.0,
            0.0,
            0.0,
            source_lines,
            ["Barrett thesis milestone"],
        )
    ]


def _special_requirement(
    major: str,
    source_file: str,
    section: str,
    name: str,
    kind: str,
    status: str,
    required: float,
    earned: float,
    in_progress: float,
    remaining: float,
    source_lines: list[str],
    criteria: list[str] | None = None,
    category: str = "",
) -> dict[str, Any]:
    identity = f"{source_file}|{major}|{section}|{name}"
    category = category or categorize(section, name, " ".join(source_lines))
    return {
        "id": hashlib.sha1(identity.encode("utf-8")).hexdigest()[:12],
        "major": major,
        "section": section,
        "name": name,
        "kind": kind,
        "status": status,
        "credits_required": round(required, 2),
        "credits_earned": round(earned, 2),
        "credits_in_progress": round(in_progress, 2),
        "credits_remaining": round(remaining, 2),
        "course_options": [],
        "courses_completed": [],
        "courses_in_progress": [],
        "criteria": criteria or [],
        "exclusions": [],
        "category": category,
        "category_label": CATEGORY_LABELS[category],
        "designations": [],
        "wildcards": [],
        "required_count": 1 if required > 0 else 0,
        "capped_options": [],
        "capped_limit": 0,
        "source_text": " · ".join(source_lines)[:900],
        "confidence": 0.98,
    }


def _parse_requirement_blocks(
    lines: list[str],
    major: str,
    source_file: str,
    vocabulary: DesignationVocabulary | None = None,
) -> list[dict[str, Any]]:
    requirements: list[dict[str, Any]] = []
    current_section = "Degree requirements"
    block: _Block | None = None
    ignore_remainder = False
    # Every line any block took in, whether or not that block survived. The
    # unread-condition check reads this instead of the requirement's stored
    # source text, which is truncated for display and so made long blocks look
    # as though their own NEEDS line had never been seen.
    consumed: set[str] = set()
    # Sections that produced at least one numbered requirement. DARS prints a
    # section total before its children — "NEEDS: 18.00 HOURS 6 SUB-GROUPS"
    # above six numbered rows — and that total is a summary of them, not a
    # thirteenth thing the student owes.
    sections_with_children: set[str] = set()
    section_totals: dict[str, list[str]] = {}

    def flush() -> None:
        nonlocal block
        if block:
            consumed.update(block.lines)
            consumed.add(f"{block.number}) {block.title}")
            parsed = _block_to_requirement(block, major, source_file, vocabulary)
            if parsed:
                requirements.append(parsed)
                sections_with_children.add(parsed["section"].casefold())
        block = None

    for line in lines:
        if line.upper().startswith(SECTION_STOP_PREFIXES):
            flush()
            ignore_remainder = True
            continue
        if ignore_remainder:
            # Deliberately out of scope — student-athlete totals, free-elective
            # explanatory notes. Skipping these is the intent, so they must not
            # then be reported as conditions the parser failed to interpret.
            consumed.add(line)
            continue

        numbered = NUMBERED_REQUIREMENT_RE.match(line)
        if numbered:
            flush()
            prefix, number, title = numbered.groups()
            block = _Block(
                section=current_section,
                prefix_in_progress=bool(prefix),
                number=number,
                title=title,
            )
            continue

        # Course-list continuations can look like uppercase section headings
        # (for example "Cell/Molecular: BIO 327 ...").  Once a numbered block
        # is open, course-bearing lines belong to that block.
        if block and (
            line.startswith(("COURSE LIST:", "-> NOT FROM:"))
            or COURSE_TOKEN_RE.search(line)
            or _parse_course_line(line)
        ):
            block.lines.append(line)
            continue

        if _looks_like_section(line):
            flush()
            current_section = _clean_section(line)
            continue

        if block:
            if any(phrase in line.casefold() for phrase in BOILERPLATE_PHRASES):
                continue
            block.lines.append(line)
        elif NEEDS_HOURS_RE.search(line) or NEEDS_GPA_RE.search(line) or "NEEDS:" in line:
            # Outside any numbered block: this is the section's own total.
            section_totals.setdefault(_clean_section(current_section).casefold(), []).append(line)

    flush()

    # Exact duplicate numbered lines occur in some generated reports.
    deduped: dict[tuple[str, str], dict[str, Any]] = {}
    status_rank = {"remaining": 0, "in_progress": 1, "complete": 2}
    for requirement in requirements:
        key = (requirement["section"].casefold(), requirement["name"].casefold())
        existing = deduped.get(key)
        if existing is None or (
            status_rank[requirement["status"]],
            requirement["credits_earned"],
            len(requirement["course_options"]),
        ) > (
            status_rank[existing["status"]],
            existing["credits_earned"],
            len(existing["course_options"]),
        ):
            deduped[key] = requirement

    parsed = list(deduped.values())
    special = _special_requirements(lines, major, source_file)
    parsed.extend(special)
    # These readers work off raw lines rather than blocks, so record what they
    # covered or their evidence looks unread.
    for requirement in special:
        consumed.update(requirement["source_text"].split(" · "))
        sections_with_children.add(requirement["section"].casefold())
    return parsed, consumed, sections_with_children, section_totals


def _overall_summary(lines: list[str]) -> tuple[float | None, float, float | None]:
    earned_hours: float | None = None
    in_progress_hours = 0.0
    gpa: float | None = None
    for index, line in enumerate(lines):
        if line.startswith("TOTAL HOURS:"):
            window = lines[index:index + 10]
            earned_hours = _find_float(INLINE_EARNED_RE, window)
            in_progress_hours = _find_float(IN_PROGRESS_RE, window) or 0.0
        match = re.search(r"EARNED:\s*(\d+(?:\.\d+)?)\s*HOURS\s+(\d+\.\d+)\s*GPA", line, re.IGNORECASE)
        if match and gpa is None:
            if earned_hours is None:
                earned_hours = float(match.group(1))
            gpa = float(match.group(2))
    return earned_hours, in_progress_hours, gpa


def parse_dars_text(text: str, source_file: str = "DARS.pdf") -> dict[str, Any]:
    """Parse extracted DARS text into one focused program audit."""
    # Strip identifying headers before they can enter requirement evidence.
    raw_lines=text.splitlines()
    clean=[]; skip_next=False
    for line in raw_lines:
        if skip_next:
            skip_next=False
            continue
        if re.match(r"^\s*(?:Student\s*(?:Name|ID|Number)|ASU\s*(?:ID|ID Number)|EMPLID|Name|Email|Date of Birth)\s*[:#]", line, re.I):
            skip_next=not bool(line.split(':',1)[-1].strip()) if ':' in line else False
            continue
        clean.append(line)
    clean_text="\n".join(clean)
    clean_text=re.sub(r'\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b','[email removed]',clean_text,flags=re.I)
    clean_text=re.sub(r'\b\d{9,12}\b','[identifier removed]',clean_text)
    lines = _normalize_lines(clean_text)
    # Layer 1: let the document teach us its own designation vocabulary before
    # anything is categorized, so a code ASU has not shipped yet still resolves
    # to the real name the report gives it.
    vocabulary = DesignationVocabulary.learn(lines)
    official_majors = _extract_official_majors(lines)
    focus_major = _detect_focus_major(lines, official_majors)
    catalog_match = next((CATALOG_RE.search(line) for line in lines if CATALOG_RE.search(line)), None)
    catalog_year = catalog_match.group(1) if catalog_match else None
    header_catalog=re.search(r"Catalog Year\s+((?:Fall|Spring|Summer)\s+20\d{2}|\d{2,4}-\d{2,4})", clean_text,re.I)
    if header_catalog and not catalog_year: catalog_year=header_catalog.group(1)
    code_match=re.search(r"Program Code\s+(.+?)(?=\s+Catalog Year|$)",clean_text,re.I|re.M)
    program_code=re.sub(r"\s+","",code_match.group(1)) if code_match else focus_major
    prepared=re.search(r"Prepared On\s+(\d{2}/\d{2}/\d{4}\s+\d{1,2}:\d{2}\s*[AP]M)",clean_text,re.I)
    prepared_on=""
    if prepared:
        from datetime import datetime
        try: prepared_on=datetime.strptime(prepared.group(1),"%m/%d/%Y %I:%M %p").isoformat()
        except ValueError: pass

    all_course_rows = [
        parsed
        for line in lines
        if (parsed := _parse_course_line(line)) is not None
    ]
    courses = _deduplicate_courses(all_course_rows)
    requirements, consumed_lines, sections_with_children, section_totals = _parse_requirement_blocks(
        lines, focus_major, source_file, vocabulary
    )

    earned_hours, in_progress_hours, gpa = _overall_summary(lines)
    warnings: list[str] = []
    if not requirements:
        warnings.append("No requirement blocks could be interpreted. This audit cannot establish graduation readiness.")
    pages=text.split("\f")
    by_label={}
    for requirement in requirements:
        requirement['source_pages']=[i+1 for i,page in enumerate(pages) if requirement['name'].rstrip(':') in page]
        label=requirement.get('source_label','')
        requirement['id']=hashlib.sha256(f"{program_code}|{catalog_year}|{requirement['section']}|{label or requirement['name']}".encode()).hexdigest()[:24]
        by_label[label]=requirement['id']
    for requirement in requirements:
        parent=requirement.get('source_label','').rsplit('.',1)
        requirement['parent_id']=by_label.get(parent[0]) if len(parent)>1 else None
    # Conditions the parser genuinely never read.
    #
    # Every "NEEDS:" line used to be compared against each requirement's stored
    # source text, which is truncated to 900 characters for display — so a long
    # block's own NEEDS line fell off the end and was reported as unread. Worse,
    # DARS prints a *section* total above its numbered children ("NEEDS: 18.00
    # HOURS 6 SUB-GROUPS" over six rows), and that summary was counted as a
    # thirteenth thing the student owed. Between them these produced twelve
    # "Unresolved condition N" entries on an audit where nothing was actually
    # unread, and each one surfaced as a blocking graduation check.
    #
    # A line now counts as unread only if no block consumed it *and* it is not a
    # section total whose children were parsed.
    aggregate_lines = {
        line
        for section, totals in section_totals.items()
        if section in sections_with_children
        for line in totals
    }
    unmet = [line for line in lines if re.search(r"NEEDS:\s*[1-9]", line)]
    unresolved = [
        line
        for line in unmet
        if line not in consumed_lines and line not in aggregate_lines
    ]
    if unresolved:
        warnings.append("Some unmet DARS statements were not fully interpreted; confirm them with your advisor.")
        for ordinal,line in enumerate(dict.fromkeys(unresolved)):
            requirements.append({'id':hashlib.sha256(f'{program_code}|{catalog_year}|unresolved|{line}'.encode()).hexdigest()[:24],
                'major':focus_major,'section':'Unresolved DARS conditions','name':f'Unresolved condition {ordinal+1}',
                'kind':'milestone','status':'remaining','credits_required':0.,'credits_earned':0.,'credits_in_progress':0.,'credits_remaining':0.,
                'course_options':[],'courses_completed':[],'courses_in_progress':[],'criteria':['Advisor interpretation needed'],
                'exclusions':[],'category':'unclassified','category_label':CATEGORY_LABELS['unclassified'],
                'designations':[],'wildcards':[],'required_count':0,'capped_options':[],'capped_limit':0,
                'source_text':line[:900],'confidence':0.0,'needs_review':True,
                'source_pages':[i+1 for i,page in enumerate(pages) if line in page]})
    low_confidence = sum(1 for requirement in requirements if requirement["confidence"] < 0.8)
    if low_confidence:
        warnings.append(
            f"{low_confidence} requirement{'s' if low_confidence != 1 else ''} "
            "lack an explicit course list; verify those rows with an advisor."
        )

    status_counts = {
        status: sum(1 for requirement in requirements if requirement["status"] == status)
        for status in ("complete", "in_progress", "remaining")
    }
    remaining_specific = sum(
        requirement["credits_remaining"]
        for requirement in requirements
        if requirement["status"] == "remaining"
        and requirement["kind"] in {"course", "elective"}
    )

    # Account for every requirement: each one carries exactly one category, and
    # the totals are returned so a fall-through can be seen rather than guessed.
    coverage = coverage_report(requirements)
    new_codes = vocabulary.unknown_codes()
    if new_codes:
        # A designation revision announces itself here instead of quietly
        # degrading every plan built from this catalog year.
        warnings.append(
            "This audit uses General Studies designation"
            f"{'s' if len(new_codes) != 1 else ''} {', '.join(new_codes)}, which "
            "post-date this planner's built-in table. They were read from the "
            "report itself; confirm the areas with your advisor."
        )
    if coverage["unclassified"]:
        warnings.append(
            f"{coverage['unclassified']} requirement"
            f"{'s' if coverage['unclassified'] != 1 else ''} could not be "
            "categorized and are kept on the map for advisor review."
        )

    return {
        "name": focus_major,
        "source_file": source_file,
        "designations": [
            {
                "code": code,
                "name": vocabulary.resolve(code).name,
                "era": vocabulary.resolve(code).era,
                "self_defined": vocabulary.resolve(code).self_defined,
            }
            for code in vocabulary.codes()
        ],
        "coverage": coverage,
        "official_majors": official_majors,
        "program_code": program_code,
        "prepared_on": prepared_on,
        "campus": next((c for c in ("Tempe","Online","Polytechnic","Downtown","West") if any(c in line for line in lines[:30])), ""),
        "summary": {
            "earned_hours": earned_hours,
            "in_progress_hours": in_progress_hours,
            "gpa": gpa,
            "catalog_year": catalog_year,
            "complete_requirements": status_counts["complete"],
            "in_progress_requirements": status_counts["in_progress"],
            "remaining_requirements": status_counts["remaining"],
            "remaining_specific_credits": round(remaining_specific, 2),
        },
        "requirements": requirements,
        "courses": courses,
        "warnings": warnings,
    }


def parse_dars_pdf(pdf_path: str | Path, source_file: str | None = None) -> dict[str, Any]:
    path = Path(pdf_path)
    return parse_dars_text(extract_text(path), source_file or path.name)


def parse_dars_bytes(data: bytes, source_file: str) -> dict[str, Any]:
    return parse_dars_text(extract_text_bytes(data), source_file)
