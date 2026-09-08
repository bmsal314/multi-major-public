"""ASU vocabulary: General Studies designations, course codes, elective shapes.

Designations are not stable.  ASU has already replaced the legacy set
(``HU``/``SB``/``SQ``/``MA``/``CS``/``L``) with Gold
(``HUAD``/``SOBE``/``SCIT``/``QTRS``/``MATH``/``AMIT``/``CIVI``/``GCSI``/``SUST``),
audits from adjacent catalog years carry both at once, and the next revision will
land the same way — silently, in a student's PDF, before anyone updates this file.
So the table below is a *prior*, never the authority.

Resolution runs in three layers, most trustworthy first:

1. **Learned from the document.**  DARS states its own vocabulary twice: an
   all-caps section heading, then a numbered requirement repeating the same words
   with the code in parentheses.

   ::

       University General Studies Requirement - Gold
       SOCIAL AND BEHAVIORAL SCIENCES
       1) Social and Behavioral Sciences (SOBE): 3 hours

   A definition is accepted only when the document says it both ways, which is
   what keeps ``JMC 201: News Reporting and Writing (L)`` from teaching us that
   ``L`` means "News Reporting and Writing".  A code ASU invents next year is
   learned on first sight with its real name and no code change here.

2. **The known table.**  Supplies a name for a code used in passing — inside a
   course list, say — that the document never defines.

3. **Shape.**  A parenthesised token in a General Studies context that is neither
   learned nor known is still *recognised as a designation*, kept, and marked
   ``discovered`` so it is scheduled and shown rather than dropped.

Every requirement is then assigned exactly one :data:`CATEGORIES` value.  There is
no silent fall-through: anything unrecognised becomes ``unclassified``, which is
visible, schedulable and reported — the brief's rule that an ambiguous entry stays
on the map beats an interpretation that makes it disappear.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# Layer 2 — the known table (a prior, not the authority)
# ---------------------------------------------------------------------------

#: Gold General Studies, 2024-2025 catalog onward.
GOLD_DESIGNATIONS: dict[str, str] = {
    "HUAD": "Humanities, Arts and Design",
    "SOBE": "Social and Behavioral Sciences",
    "SCIT": "Scientific Thinking in Natural Sciences",
    "QTRS": "Quantitative Reasoning",
    "MATH": "Mathematics",
    "AMIT": "American Institutions",
    "CIVI": "Governance and Civic Engagement",
    "GCSI": "Global Communities, Societies and Individuals",
    "SUST": "Sustainability",
}

#: Pre-Gold designations, still present on older catalog years and transfer rows.
LEGACY_DESIGNATIONS: dict[str, str] = {
    "HU": "Humanities, Arts and Design",
    "SB": "Social-Behavioral Sciences",
    "SQ": "Natural Science — Quantitative",
    "SG": "Natural Science — General",
    "MA": "Mathematical Studies",
    "CS": "Computer, Statistics and Quantitative Applications",
    "L": "Literacy and Critical Inquiry",
    "C": "Cultural Diversity in the United States",
    "G": "Global Awareness",
    "H": "Historical Awareness",
}

KNOWN_DESIGNATIONS: dict[str, str] = {**GOLD_DESIGNATIONS, **LEGACY_DESIGNATIONS}

ERA_GOLD = "gold"
ERA_LEGACY = "legacy"
ERA_DISCOVERED = "discovered"

# ---------------------------------------------------------------------------
# Shapes
# ---------------------------------------------------------------------------

#: What a designation code can look like at all: 1-6 capitals, no digits.  Used
#: for discovery, so it must not be pinned to the codes we happen to know.
_CODE = r"[A-Z]{1,6}"

#: "(SOBE)", "(HUAD OR SB)", "(MATH OR CS)" — one or more codes, OR-separated.
DESIGNATION_GROUP_RE = re.compile(
    rf"\(\s*({_CODE}(?:\s+OR\s+{_CODE})*)\s*\)"
)

#: The self-definition DARS prints: a spelled-out name followed by its code.
DEFINITION_RE = re.compile(
    rf"([A-Za-z][A-Za-z,'&/\- ]{{3,70}}?)\s*\(\s*({_CODE}(?:\s+OR\s+{_CODE})*)\s*\)"
)

#: A concrete ASU course code: "FIN 361", "MAT 210", "CHM 233".
COURSE_CODE_RE = re.compile(r"\b([A-Z]{2,4})\s+(\d{3}[A-Z]?)\b")

#: A wildcard slot: "AEE OR MAE OR MEE 3** Elective", "MAE 4** Elective".
WILDCARD_RE = re.compile(
    r"\b([A-Z]{2,4}(?:\s+OR\s+[A-Z]{2,4})*)\s+(\d)\*\*(?:\s*(?:level\s*)?Elective)?\b",
    re.IGNORECASE,
)

#: "Students may choose no more than one course from the following:" — a cap on a
#: sibling list, not a requirement of its own.
#: "following" is optional because the PDF wraps the sentence: the requirement
#: title ends at "...from the" and "following:" lands on the next line. The
#: phrase is specific enough without it that nothing else matches.
CAPPED_SUBLIST_RE = re.compile(
    r"\b(?:may\s+)?choose\s+no\s+more\s+than\s+(one|two|three|four|five|\d+)\s+"
    r"(?:course|courses)\s+from\s+the\b",
    re.IGNORECASE,
)

#: "Complete 2 courses:" — the same category satisfied more than once.
COMPLETE_N_COURSES_RE = re.compile(r"\bComplete\s+(\d+)\s+courses?\b", re.IGNORECASE)

#: "- two courses", "3 COURSES", "2 SETS TAKEN".
#:
#: Two guards earn their place.  The count is capped at two digits because an
#: exclusion line reading "FIN 493 FIN 499 COURSE LIST: FIN 361" otherwise parses
#: as "499 courses" — a course number swallowed as a quantity.  And "COURSE LIST"
#: is excluded outright, since it introduces the options rather than counting
#: them.
COURSE_COUNT_RE = re.compile(
    r"(?:^|[-\s])(\d{1,2}|one|two|three|four|five|six|seven|eight|nine|ten)\s+"
    r"(?:courses?|sets?)\b(?!\s*LIST)",
    re.IGNORECASE,
)

_WORD_NUMBERS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
}

DEFAULT_COURSE_CREDITS = 3.0

#: Words that are never a designation name, so a definition containing one is
#: rejected before it can poison the vocabulary.
_NON_DEFINITION_WORDS = (
    "hours", "minimum", "course list", "needs", "earned", "elective",
    "credit", "gpa", "gold", "gpa check",
)


def to_int(value: str) -> int:
    """``"two"`` -> 2, ``"3"`` -> 3, anything else -> 0."""
    value = value.strip().casefold()
    return int(value) if value.isdigit() else _WORD_NUMBERS.get(value, 0)


def _split_codes(group: str) -> list[str]:
    return [code.strip().upper() for code in re.split(r"\s+OR\s+", group, flags=re.I) if code.strip()]


# ---------------------------------------------------------------------------
# Layer 1 — vocabulary learned from the document itself
# ---------------------------------------------------------------------------

@dataclass
class Designation:
    """One General Studies area as this document uses it."""

    code: str
    name: str
    era: str
    #: True when the document defined it; False when only the table or shape did.
    self_defined: bool = False

    @property
    def label(self) -> str:
        return f"{self.name} ({self.code})"


@dataclass
class DesignationVocabulary:
    """The designation codes one audit actually uses.

    Built by :meth:`learn` from the document, backed by
    :data:`KNOWN_DESIGNATIONS`, and open to codes neither source has seen.
    """

    entries: dict[str, Designation] = field(default_factory=dict)

    # -- construction -------------------------------------------------------

    @classmethod
    def learn(cls, lines: list[str]) -> "DesignationVocabulary":
        """Read a document's own designation definitions out of its headings."""
        vocabulary = cls()
        recent_headings: list[str] = []
        in_general_studies = False

        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue

            letters = [c for c in stripped if c.isalpha()]
            is_heading = bool(letters) and all(c.isupper() for c in letters) and len(stripped) < 90

            if re.search(r"general\s+studies", stripped, re.IGNORECASE):
                in_general_studies = True
                recent_headings.append(_normalize_name(stripped))
                continue
            if is_heading:
                # A heading is the candidate spelled-out name for whatever code
                # the next numbered line carries.  It also ends the General
                # Studies block: without this, a major section further down the
                # report would still look like General Studies context and a
                # course title such as "JMC 201: News Reporting and Writing (L)"
                # would teach us that L means "News Reporting and Writing".
                in_general_studies = False
                recent_headings.append(_normalize_name(stripped))
                del recent_headings[:-4]
                continue

            # A course row is never a definition, however it is punctuated.
            carries_course = bool(COURSE_CODE_RE.search(stripped)) or bool(
                re.match(r"^(?:FA|SP|SU)\d{2}\b", stripped)
            )

            for raw_name, group in DEFINITION_RE.findall(stripped):
                name = _clean_definition_name(raw_name)
                if not name:
                    continue
                normalized = _normalize_name(name)
                # Accept only when the document said it twice: once as a heading,
                # once beside the code.  Everything else is a passing mention.
                confirmed = normalized in recent_headings and not carries_course
                if not confirmed:
                    if carries_course or not in_general_studies:
                        continue
                    if not re.match(r"^\s*(?:IP\s+)?\d+\)", stripped):
                        continue
                for code in _split_codes(group):
                    vocabulary.define(code, name, self_defined=confirmed)

            if re.search(r"^\s*\**\s*END OF ANALYSIS", stripped, re.IGNORECASE):
                in_general_studies = False

        return vocabulary

    # -- resolution ---------------------------------------------------------

    def define(self, code: str, name: str, *, self_defined: bool) -> Designation:
        code = code.upper()
        existing = self.entries.get(code)
        # A confirmed self-definition always wins; otherwise keep the first name.
        if existing and (existing.self_defined or not self_defined):
            return existing
        entry = Designation(code=code, name=name, era=era_of(code), self_defined=self_defined)
        self.entries[code] = entry
        return entry

    def resolve(self, code: str) -> Designation:
        """Never fails.  Learned name, else known name, else the bare code."""
        code = code.upper()
        if code in self.entries:
            return self.entries[code]
        if code in KNOWN_DESIGNATIONS:
            return Designation(code, KNOWN_DESIGNATIONS[code], era_of(code))
        return Designation(code, code, ERA_DISCOVERED)

    def name(self, code: str) -> str:
        return self.resolve(code).name

    def label(self, code: str) -> str:
        return self.resolve(code).label

    def is_recognized(self, code: str) -> bool:
        return code.upper() in self.entries or code.upper() in KNOWN_DESIGNATIONS

    def codes(self) -> list[str]:
        return sorted(self.entries)

    def unknown_codes(self) -> list[str]:
        """Codes this document uses that the shipped table has never seen.

        Surfacing these is how a designation revision announces itself instead of
        quietly degrading everyone's plan.
        """
        return sorted(c for c in self.entries if c not in KNOWN_DESIGNATIONS)


def era_of(code: str) -> str:
    code = code.upper()
    if code in GOLD_DESIGNATIONS:
        return ERA_GOLD
    if code in LEGACY_DESIGNATIONS:
        return ERA_LEGACY
    return ERA_DISCOVERED


def _normalize_name(value: str) -> str:
    """Fold a heading and a title to one comparable form."""
    value = re.sub(r"\(.*?\)", " ", value)
    value = re.sub(r"[^A-Za-z ]+", " ", value)
    value = re.sub(r"\s+", " ", value).strip().casefold()
    # DARS headings drop the serial comma and vary "and"/"&"; ignore both.
    return value.replace(" and ", " ").replace(" & ", " ")


def _clean_definition_name(value: str) -> str:
    value = re.sub(r"^\s*(?:IP\s+)?\d+(?:\.\d+)*\)\s*", "", value).strip(" :-–")
    value = re.sub(r"\s+", " ", value)
    if len(value) < 4 or len(value) > 70:
        return ""
    if any(word in value.casefold() for word in _NON_DEFINITION_WORDS):
        return ""
    # A definition is prose, not a course row.
    if COURSE_CODE_RE.search(value) or re.match(r"^(FA|SP|SU)\d{2}\b", value):
        return ""
    return value


# ---------------------------------------------------------------------------
# Extraction helpers
# ---------------------------------------------------------------------------

def designations_in(text: str) -> list[str]:
    """Every designation-shaped code in ``text``, in order, deduplicated."""
    found: list[str] = []
    for group in DESIGNATION_GROUP_RE.findall(text):
        for code in _split_codes(group):
            if code not in found:
                found.append(code)
    return found


def course_codes_in(text: str) -> list[str]:
    found: list[str] = []
    for subject, number in COURSE_CODE_RE.findall(text):
        code = f"{subject} {number}"
        if code not in found:
            found.append(code)
    return found


def wildcard_patterns_in(text: str) -> list[dict[str, object]]:
    """Every wildcard course slot in ``text``.

    ``"AEE OR MAE OR MEE 3** Elective"`` becomes ``{"subjects": ["AEE", "MAE",
    "MEE"], "level": 3, ...}``: any 300-level course from any of those prefixes
    satisfies the slot.
    """
    patterns: list[dict[str, object]] = []
    seen: set[tuple[str, int]] = set()
    for subjects_text, level in WILDCARD_RE.findall(text):
        subjects = [s for s in _split_codes(subjects_text) if s]
        key = ("/".join(subjects), int(level))
        if not subjects or key in seen:
            continue
        seen.add(key)
        patterns.append(
            {
                "subjects": subjects,
                "level": int(level),
                "label": f"{'/'.join(subjects)} {int(level)}00-level elective",
            }
        )
    return patterns


def matches_wildcard(code: str, pattern: dict[str, object]) -> bool:
    match = re.fullmatch(r"([A-Z]{2,4})\s*(\d)(\d\d)[A-Z]?", code.strip().upper())
    if not match:
        return False
    return match.group(1) in pattern["subjects"] and int(match.group(2)) == pattern["level"]


def course_level(code: str) -> int:
    """``"FIN 361"`` -> 3.  0 when the text is not a course code."""
    match = re.search(r"\b(\d)\d\d[A-Z]?\b", code)
    return int(match.group(1)) if match else 0


def is_upper_division(code: str) -> bool:
    return course_level(code) >= 3


# ---------------------------------------------------------------------------
# Categories — every requirement gets exactly one
# ---------------------------------------------------------------------------

#: Ordered by precedence.  ``categorize`` returns the first that matches, and
#: ``unclassified`` is the guaranteed floor, so nothing is ever uncategorized.
CATEGORIES: tuple[str, ...] = (
    "gpa",
    "hour_check",
    "constraint",
    "general_studies",
    "first_year",
    "language",
    "honors",
    "project",
    "minor",
    "certificate",
    "major",
    "elective_constrained",
    "elective_open",
    "unclassified",
)

#: Human labels, used on the map and in the coverage report.
CATEGORY_LABELS: dict[str, str] = {
    "gpa": "GPA requirement",
    "hour_check": "Hour check",
    "constraint": "Constraint",
    "general_studies": "General Studies",
    "first_year": "First-year requirement",
    "language": "Second language",
    "honors": "Honors",
    "project": "Thesis or capstone milestone",
    "minor": "Minor",
    "certificate": "Certificate",
    "major": "Major coursework",
    "elective_constrained": "Directed elective",
    "elective_open": "Open elective",
    "unclassified": "Needs advisor review",
}

#: Categories that consume credit hours and therefore belong on the map.
SCHEDULABLE_CATEGORIES = frozenset(
    {
        "general_studies", "first_year", "language", "honors", "project",
        "minor", "certificate", "major", "elective_constrained",
        "elective_open", "unclassified",
    }
)


def categorize(
    section: str,
    title: str,
    body: str = "",
    *,
    designations: list[str] | None = None,
    has_options: bool = False,
    option_count: int = 0,
    required_count: int = 0,
    has_wildcards: bool = False,
    credits_required: float = 0.0,
    lexicon: object | None = None,
) -> str:
    """Assign one category.  Always returns a member of :data:`CATEGORIES`.

    **Structure decides before wording does.**  A block that lists eight courses
    and needs three is a pool the student chooses from, whatever it is called —
    which is how Dance's "Personal Movement Practice" is recognised as an
    elective despite never using the word.  Only once the shape is uninformative
    (no options to count) does phrasing get a vote, and the phrase list itself is
    the growing lexicon rather than a fixed set.

    Precedence runs from the most structurally certain signal to the least, so a
    GPA rule is never mistaken for coursework and an open elective is concluded
    only after every stronger reading is ruled out.
    """
    heading = f"{section} {title}".casefold()
    everything = f"{section} {title} {body}".casefold()
    option_count = option_count or (1 if has_options else 0)

    # -- 1. Rules that are not coursework at all ---------------------------
    if re.search(r"\bgpa\b", heading):
        return "gpa"
    if CAPPED_SUBLIST_RE.search(everything) and not option_count:
        return "constraint"
    if re.search(r"\bno more than\b|\bmaximum\b|\bmay not\b|\bcannot also be used\b", heading):
        return "constraint"
    if re.search(
        r"total hours|hour check|hours check|resident credit|residency|"
        r"\bupper division\b\s*[-:]?\s*\d+\s*hours?\s*(?:minimum|maximum)|"
        r"\d+-?\s*year institutions?",
        heading,
    ):
        return "hour_check"

    # -- 2. Named programme areas ------------------------------------------
    if designations or re.search(r"general studies", heading):
        return "general_studies"
    if re.search(r"first-?year composition|asu 101|the asu experience|first-?year seminar", heading):
        return "first_year"
    if re.search(r"second language|language requirement|foreign language", heading):
        return "language"
    if re.search(r"\bhonors\b|barrett", heading):
        return "honors"
    if re.search(r"\bthesis\b|final .*approval|\bportfolio\b", heading):
        return "project"
    if re.search(r"\bminor\b", heading):
        return "minor"
    if re.search(r"\bcertificate\b", heading):
        return "certificate"

    # -- 3. Structure: does the block offer more than it demands? ----------
    # This is the general elective test and it needs no vocabulary at all.
    directed = has_wildcards or bool(
        re.search(r"upper division|lower division|\b\d00-level\b", heading)
    )
    if option_count:
        if has_wildcards:
            return "elective_constrained"
        if required_count and option_count > required_count:
            return "elective_constrained"
        if not required_count and option_count > 1 and credits_required > 3.0:
            # Several options and more hours than one course: a pool, not an
            # "A or B" substitution for a single named course.
            return "elective_constrained"
        # Every listed course is required, or it is a one-of-two substitution.
        return "major"

    # -- 4. No options to count: fall back to wording ----------------------
    phrase_hit = bool(
        lexicon is not None and lexicon.looks_like_choice_pool(f"{section} {title}")
    )
    if re.search(r"\belective\b|\btrack course\b|\brelated area\b", heading) or phrase_hit:
        return "elective_constrained" if directed else "elective_open"
    if re.search(r"\bcapstone\b", heading):
        return "project"
    if re.search(r"\bmajor\b|\bcore\b|\bskill\b|requirements?$", heading):
        return "major"
    if credits_required > 0:
        # Credit-bearing and unrecognised. It stays on the map and is flagged,
        # because a slot a student can see and question beats a silent drop.
        return "unclassified"
    return "unclassified"


def coverage_report(records: list[dict[str, object]]) -> dict[str, object]:
    """Account for every category in one audit.

    Returns the count per category, the General Studies areas seen with their
    status, and any code the shipped table does not know — so a designation
    revision is reported rather than absorbed.
    """
    counts: dict[str, int] = {name: 0 for name in CATEGORIES}
    for record in records:
        counts[str(record.get("category") or "unclassified")] += 1
    return {
        "counts": counts,
        "categorized": sum(counts.values()),
        "unclassified": counts["unclassified"],
    }
