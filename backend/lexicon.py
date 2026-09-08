"""A vocabulary that grows every time an audit is parsed.

The parser must read *any* class and *any* elective, including ones ASU has not
invented yet.  Three mechanisms cooperate, and they are deliberately ordered so
the weakest can never overrule the strongest:

1. **Structure** (:mod:`backend.pdf_parser`) — what the document *does*.  A block
   offering eight courses and needing three is a choice pool whatever it calls
   itself.  Dance's "Personal Movement Practice" contains no elective keyword at
   all and is still recognised, because the shape gives it away.
2. **The document's own words** (:class:`~backend.asu_catalog.DesignationVocabulary`)
   — what this report says about itself, learned per parse.
3. **This lexicon** — what every audit parsed so far has taught us.  A prior for
   the cases where the document is terse, and the place a new subject prefix or a
   new way of writing "elective" gets remembered.

The lexicon is an *additive prior*.  It never overrides layers 1 or 2, and an
empty or missing lexicon file only costs accuracy on genuinely ambiguous lines —
never correctness on clear ones.  That property is what keeps parsing
deterministic and reviewable: the same PDF yields the same requirements whether
or not the lexicon has ever seen its program.

**Privacy.** Only non-identifying vocabulary is retained — subject prefixes,
designation codes, and lowercase phrase shapes.  :func:`_clean_phrase` and the
subject/designation patterns reject anything carrying digits, course rows, names
or identifiers, so a transcript cannot reach this file even by accident.  Nothing
here is per-student and nothing is written during a request; growth happens only
when :func:`learn_from` is called by the offline corpus job.
"""

from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path
from typing import Any

LEXICON_PATH = Path(__file__).resolve().parent / "data" / "lexicon.json"
SCHEMA_VERSION = 1

#: A subject prefix as ASU writes it: two to four capitals, never digits.
SUBJECT_RE = re.compile(r"^[A-Z]{2,4}$")
#: A General Studies designation code.
DESIGNATION_RE = re.compile(r"^[A-Z]{1,6}$")
#: A retained phrase: lowercase words only.  Digits are excluded so a course
#: number, a student ID or an hour count can never be stored.
PHRASE_RE = re.compile(r"^[a-z][a-z \-]{2,47}$")

#: Phrase shapes that mean "choose from a pool" even with no keyword.  Seeded
#: from the three 2024-2025 major maps and extended by ``learn_from``.
SEED_ELECTIVE_PHRASES: tuple[str, ...] = (
    "elective",
    "related area course",
    "track course",
    "advanced skills course",
    "capstone course",
    "personal movement practice",
    "technical elective",
    "concentration course",
    "emphasis course",
    "focus area",
    "selective",
    "directed elective",
    "restricted elective",
    "free elective",
    "approved course",
    "supporting course",
    "breadth course",
    "cognate",
)

#: Subject prefixes seen in the shipped fixtures.  Only a prior — an unseen
#: prefix is still accepted on sight, because ``SUBJECT_RE`` is a shape, not a
#: whitelist.
SEED_SUBJECTS: tuple[str, ...] = (
    "ACC", "AEE", "AGB", "AST", "ASB", "ASU", "BCH", "BIO", "BME", "CEE", "CHE",
    "CHM", "CIS", "COM", "DCE", "DSC", "ECN", "EEE", "EGR", "ENG", "FIN", "FSE",
    "HCR", "HON", "HST", "HUM", "IEE", "JMC", "LES", "LIA", "MAE", "MAT", "MCO",
    "MEE", "MGT", "MKT", "MSE", "NEU", "PAF", "PHY", "POS", "PSY", "SCM", "SES",
    "SOC", "SPA", "STP", "STS", "SWU", "THE", "WPC",
)


def _empty() -> dict[str, Any]:
    return {
        "version": SCHEMA_VERSION,
        "updated": "",
        "subjects": {},
        "designations": {},
        "elective_phrases": {},
        "section_names": {},
    }


#: A stored phrase must contain at least one of these.  Shape alone is not
#: enough: "jordan rivera" is a valid lowercase phrase and must never be
#: retained.  Requiring an academic token means a phrase can only survive if it
#: describes coursework, which is the whole purpose of the lexicon.
ACADEMIC_TOKENS: frozenset[str] = frozenset(
    """
    elective electives course courses requirement requirements area areas
    practice practices track tracks capstone seminar skills studies study
    language languages thesis project projects core major majors minor minors
    certificate honors division credit credits hours level concentration
    emphasis focus cognate selective breadth supporting approved directed
    restricted free general block sequence lab laboratory workshop studio
    topic topics field methods composition mathematics science sciences
    humanities arts design sustainability reasoning institutions engagement
    communities societies individuals thinking natural behavioral social
    quantitative internship residency experience movement somatic technical
    """.split()
)


#: DARS suffixes that describe the *rule*, not the thing being required.
#: These have to come off while the digits are still present, or "MGT 300:
#: 3 hours, C minimum" reduces to "mgt hours c minimum" — which then matches
#: every ordinary named course and turns it into a phantom choice pool.
_DARS_SUFFIX_RE = re.compile(
    r"\s*:\s*[\d.]+\s*hours?.*$"
    r"|\s*[-–]\s*\d+(?:\.\d+)?\s*(?:hours?|courses?).*$"
    r"|\s*,\s*[A-D][+-]?\s*minimum.*$"
    r"|\s*\b\d+(?:\.\d+)?\s*(?:hours?|courses?)\b.*$",
    re.IGNORECASE,
)


def _clean_phrase(value: str) -> str:
    """Reduce a heading to a storable shape, or "" if it must not be stored."""
    value = _DARS_SUFFIX_RE.sub("", value)
    # Course codes go before the digit strip, so "JMC 313 OR JMC 345" leaves
    # nothing rather than the meaningless "jmc or jmc".
    value = re.sub(r"\b[A-Z]{2,4}\s+\d{3}[A-Z]?\b", " ", value)
    value = re.sub(r"\(.*?\)", " ", value)
    value = re.sub(r"[^A-Za-z \-]+", " ", value)
    value = re.sub(r"\s+", " ", value).strip().casefold()
    value = re.sub(r"^(?:upper|lower)\s+division\s+", "", value)
    value = re.sub(r"^(?:or|and)\s+|\s+(?:or|and)$", "", value)
    value = re.sub(r"\s+(?:requirements?|course\(s\))$", "", value)
    value = re.sub(r"\s+", " ", value).strip()
    if not PHRASE_RE.fullmatch(value):
        return ""
    words = value.replace("-", " ").split()
    # A single leftover word is a fragment, not vocabulary.
    if len(words) < 2:
        return ""
    # Defence in depth: without an academic token this is not vocabulary, and
    # anything that is not vocabulary has no business being written to disk.
    if not (set(words) & ACADEMIC_TOKENS):
        return ""
    # Mostly-stripped course lists leave a run of orphan connectives.
    if all(word in {"or", "and", "the", "of", "in", "a"} or len(word) <= 3 for word in words):
        return ""
    return value


class Lexicon:
    """Accumulated, non-identifying parsing vocabulary."""

    def __init__(self, data: dict[str, Any] | None = None) -> None:
        base = _empty()
        base.update(data or {})
        self.data = base
        # Seeds are merged in memory rather than written to disk, so the shipped
        # file stays a record of what was actually observed.
        self._subjects = {*SEED_SUBJECTS, *self.data["subjects"]}
        self._phrases = {*SEED_ELECTIVE_PHRASES, *self.data["elective_phrases"]}

    # -- loading ------------------------------------------------------------

    @classmethod
    def load(cls, path: Path | None = None) -> "Lexicon":
        """Read the lexicon.  A missing or corrupt file degrades to the seeds."""
        target = path or LEXICON_PATH
        try:
            data = json.loads(target.read_text())
        except (OSError, ValueError):
            return cls()
        if not isinstance(data, dict) or data.get("version") != SCHEMA_VERSION:
            return cls()
        return cls(data)

    def save(self, path: Path | None = None) -> Path:
        target = path or LEXICON_PATH
        target.parent.mkdir(parents=True, exist_ok=True)
        self.data["updated"] = date.today().isoformat()
        target.write_text(json.dumps(self.data, indent=1, sort_keys=True) + "\n")
        return target

    # -- reading ------------------------------------------------------------

    def knows_subject(self, subject: str) -> bool:
        return subject.upper() in self._subjects

    def elective_phrases(self) -> frozenset[str]:
        return frozenset(self._phrases)

    def looks_like_choice_pool(self, text: str) -> bool:
        """Does this wording name a pool the student chooses from?

        Only a *hint*.  The parser decides on structure first and consults this
        when the block offers no options to count.
        """
        folded = re.sub(r"\s+", " ", text).casefold()
        return any(phrase in folded for phrase in self._phrases)

    def designation_name(self, code: str) -> str:
        entry = self.data["designations"].get(code.upper())
        return entry.get("name", "") if isinstance(entry, dict) else ""

    # -- growing ------------------------------------------------------------

    def observe_subject(self, subject: str) -> None:
        subject = subject.upper()
        if not SUBJECT_RE.fullmatch(subject):
            return
        self.data["subjects"][subject] = self.data["subjects"].get(subject, 0) + 1
        self._subjects.add(subject)

    def observe_designation(self, code: str, name: str, era: str) -> None:
        code = code.upper()
        if not DESIGNATION_RE.fullmatch(code):
            return
        entry = self.data["designations"].setdefault(
            code, {"name": name, "era": era, "count": 0}
        )
        entry["count"] += 1
        # A self-defined name from a document beats whatever we stored before.
        if name and len(name) > 3:
            entry["name"] = name
        entry["era"] = era

    def observe_elective_phrase(self, text: str) -> None:
        phrase = _clean_phrase(text)
        if not phrase:
            return
        self.data["elective_phrases"][phrase] = (
            self.data["elective_phrases"].get(phrase, 0) + 1
        )
        self._phrases.add(phrase)

    def observe_section(self, text: str) -> None:
        phrase = _clean_phrase(text)
        if not phrase:
            return
        self.data["section_names"][phrase] = (
            self.data["section_names"].get(phrase, 0) + 1
        )

    def summary(self) -> dict[str, int]:
        return {
            "subjects": len(self.data["subjects"]),
            "designations": len(self.data["designations"]),
            "elective_phrases": len(self.data["elective_phrases"]),
            "section_names": len(self.data["section_names"]),
        }


def learn_from(audits: list[dict[str, Any]], path: Path | None = None) -> Lexicon:
    """Fold parsed audits into the stored lexicon and persist it.

    Called by ``scripts/grow_lexicon.py`` over a corpus, never inside a request:
    parsing a student's report must not mutate shared state, and a web process
    should not be writing to the deployment bundle.
    """
    lexicon = Lexicon.load(path)
    for audit in audits:
        for requirement in audit.get("requirements", []):
            for code in requirement.get("course_options", []):
                subject = code.split()[0] if " " in code else ""
                lexicon.observe_subject(subject)
            for code in requirement.get("designations", []):
                lexicon.observe_designation(code, "", "discovered")
            if requirement.get("category") in {
                "elective_open", "elective_constrained",
            }:
                lexicon.observe_elective_phrase(requirement.get("name", ""))
            lexicon.observe_section(requirement.get("section", ""))
        for course in audit.get("courses", []):
            lexicon.observe_subject(course.get("subject", ""))
    lexicon.save(path)
    return lexicon
